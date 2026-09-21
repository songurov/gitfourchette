"""
Deciding whether an open merge request is owed a review.

A merge request is not reviewed once. It opens, it gets reviewed, its author
pushes again, and the review is owed afresh - until it is merged or closed. So
the question this module answers is never "has this been reviewed" but "has
this been reviewed *at the commit it is on now*".

The answer lives on the merge request itself, not in a file here. Each review
leaves a marker in its summary note naming the commit it looked at, and each
finding carries its own fingerprint in the thread it opened. Reading those back
is what makes the loop idempotent: a second pass over the same commit has
nothing to say, a pass after a push has everything to say except what it
already said.
"""

import dataclasses
import enum
import re

from gitfourchette.exttools.aireview import Finding

RUN_MARKER = re.compile(r"<!--\s*gf-review-run v1 provider=(\S+) sha=(\S+)\s*-->")
FINDING_MARKER = re.compile(r"<!--\s*gf-review v1 provider=(\S+) fp=(\w+)")

# A heading the CI reviewers write ("## 🤖 DeepSeek Code Review"). Matching the
# words rather than the provider keeps this true for whichever reviewer the
# pipeline runs.
CI_REVIEW_HEADING = re.compile(r"^#{1,3}\s*\S*\s*\w[\w .-]*Code Review\s*$", re.MULTILINE)


class Verdict(enum.StrEnum):
    Due = "due"
    Draft = "draft"
    ReviewedHere = "reviewed-here"
    "Already reviewed by us, at this very commit."
    ReviewedByCi = "reviewed-by-ci"
    NoHead = "no-head"
    "The merge request didn't say which commit it is on; nothing to anchor to."


@dataclasses.dataclass
class Decision:
    verdict: Verdict
    reason: str = ""

    @property
    def due(self) -> bool:
        return self.verdict == Verdict.Due


def runMarker(provider: str, sha: str) -> str:
    return f"<!-- gf-review-run v1 provider={provider} sha={sha} -->"


def reviewedShas(notes, provider="") -> set[str]:
    """Which commits we have already reviewed, read back from our own notes."""
    found = set()
    for note in notes if isinstance(notes, list) else []:
        body = note.get("body") if isinstance(note, dict) else None
        for markedProvider, sha in RUN_MARKER.findall(body or ""):
            if not provider or markedProvider == provider:
                found.add(sha)
    return found


def postedFingerprints(notes) -> set[str]:
    """Findings we have already put on this merge request, whatever the commit."""
    found = set()
    for note in notes if isinstance(notes, list) else []:
        body = note.get("body") if isinstance(note, dict) else None
        found.update(fingerprint for _provider, fingerprint in FINDING_MARKER.findall(body or ""))
    return found


def hasCiReview(notes, since="") -> bool:
    """
    Whether a pipeline reviewer has already covered the current code.

    `since` is the head commit's timestamp: a review note older than the commit
    it would have to be about reviewed something else.
    """
    for note in notes if isinstance(notes, list) else []:
        if not isinstance(note, dict) or note.get("system"):
            continue
        body = note.get("body") or ""
        if not CI_REVIEW_HEADING.search(body) or RUN_MARKER.search(body):
            continue  # ours carries a run marker; the pipeline's does not
        if not since:
            return True
        created = str(note.get("created_at") or "")
        if created and created >= since:
            return True
    return False


def decide(changeRequest, notes, provider="", headCommitDate="", skipDrafts=True, skipCiReviewed=True) -> Decision:
    """Whether this merge request is owed a review right now, and why not."""
    head = changeRequest.refs.headSha
    if not head:
        return Decision(Verdict.NoHead, "the merge request didn’t say which commit it is on")
    if skipDrafts and changeRequest.draft:
        return Decision(Verdict.Draft, "it is still a draft")
    if head in reviewedShas(notes, provider):
        return Decision(Verdict.ReviewedHere, f"already reviewed at {head[:8]}")
    if skipCiReviewed and hasCiReview(notes, headCommitDate):
        return Decision(Verdict.ReviewedByCi, "the pipeline already reviewed this commit")
    return Decision(Verdict.Due)


def unsaidFindings(findings: list[Finding], notes) -> list[Finding]:
    """
    The findings that aren't already on the merge request.

    A finding that survived the author's next push is still true, and still
    posted - saying it twice only teaches people to stop reading.
    """
    already = postedFingerprints(notes)
    return [finding for finding in findings if finding.fingerprint() not in already]
