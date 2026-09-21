"""
Where a finding sits in a diff, in the terms a hosting service accepts.

A model reports "file X, line 42". A merge request wants to know which side of
the diff that line is on, and refuses a position that isn't on a line the diff
touches. This maps one to the other by reading the unified diff itself, so a
comment either lands on the right line or is honestly reported as unplaceable -
never guessed onto a line the reader didn't change.
"""

import dataclasses
import re

HUNK = re.compile(r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")

# How far a finding's line may miss by and still be snapped to the nearest line
# the diff adds. A one-off slip in the model's arithmetic should still land on
# the change it was about; anything further away is left unanchored on purpose,
# because a comment on an unrelated line is worse than one in the summary only.
SNAP_WINDOW = 5


@dataclasses.dataclass
class FileDiff:
    oldPath: str = ""
    added: dict[int, bool] = dataclasses.field(default_factory=dict)
    "New-side line numbers this diff adds."
    context: dict[int, int] = dataclasses.field(default_factory=dict)
    "New-side line number -> old-side line number, for unchanged lines in a hunk."


@dataclasses.dataclass
class DiffPosition:
    newPath: str
    oldPath: str
    newLine: int
    oldLine: int = 0
    "Set only for a context line, which exists on both sides; hosts reject one without the other."
    snapped: bool = False
    "True when the finding's own line wasn't in the diff and we moved it to the nearest added line."


def diffLineIndex(diffText: str) -> dict[str, FileDiff]:
    """Every line a unified diff touches, by file, in new-side numbering."""
    index: dict[str, FileDiff] = {}
    entry = None
    pendingOld = ""
    newNo = oldNo = 0
    # inHunk keeps content from being mistaken for a header: a deleted line
    # whose text starts with "-- " is emitted as "--- ...", and an added line
    # starting with "++ " as "+++ ...". Both match the header patterns exactly,
    # and unguarded they desynchronize every line that follows.
    inHunk = False

    for line in diffText.splitlines():
        if line.startswith("diff --git "):
            entry, pendingOld, inHunk = None, "", False
            continue
        if not inHunk and line.startswith("--- "):
            path = line[4:].strip()
            pendingOld = "" if path == "/dev/null" else path.removeprefix("a/")
            continue
        if not inHunk and line.startswith("+++ "):
            path = line[4:].strip()
            newPath = "" if path == "/dev/null" else path.removeprefix("b/")
            entry = index.setdefault(newPath, FileDiff(oldPath=pendingOld or newPath)) if newPath else None
            continue
        match = HUNK.match(line)
        if match:
            oldNo, newNo = int(match.group(1)), int(match.group(2))
            inHunk = True
            continue
        if entry is None or line.startswith("\\"):  # "\ No newline at end of file"
            continue
        if line.startswith("+"):
            entry.added[newNo] = True
            newNo += 1
        elif line.startswith("-"):
            oldNo += 1
        elif line.startswith(" "):
            entry.context[newNo] = oldNo
            newNo += 1
            oldNo += 1
    return index


def indexFileHunks(index: dict[str, FileDiff], newPath: str, oldPath: str, hunks: str):
    """
    Add one file's hunks to an index, when the paths come from outside the text.

    A hosting service returns its diff as a path pair plus the hunks alone, with
    no 'diff --git' or '+++' headers. Anchoring to THAT diff rather than to one
    computed locally is what makes a comment's position valid: the host
    generates a line code from its own version of the change, and a local
    branch that is one commit ahead or behind produces line numbers it will
    refuse.
    """
    if not newPath:
        return
    entry = index.setdefault(newPath, FileDiff(oldPath=oldPath or newPath))
    newNo = oldNo = 0
    inHunk = False
    for line in hunks.splitlines():
        match = HUNK.match(line)
        if match:
            oldNo, newNo = int(match.group(1)), int(match.group(2))
            inHunk = True
            continue
        if not inHunk or line.startswith("\\"):
            continue
        if line.startswith("+"):
            entry.added[newNo] = True
            newNo += 1
        elif line.startswith("-"):
            oldNo += 1
        elif line.startswith(" ") or not line:
            # An empty element is a context line whose text is empty: the host
            # strips the leading space on a blank line.
            entry.context[newNo] = oldNo
            newNo += 1
            oldNo += 1


def resolvePosition(index: dict[str, FileDiff], file: str, line: int, snapWindow=SNAP_WINDOW) -> DiffPosition | None:
    """The position to comment at, or None when the finding can't be placed on the diff."""
    entry = index.get(file)
    if entry is None:
        return None
    if line in entry.added:
        return DiffPosition(file, entry.oldPath, line)
    if line in entry.context:
        return DiffPosition(file, entry.oldPath, line, oldLine=entry.context[line])
    best = min(entry.added, key=lambda candidate: (abs(candidate - line), candidate), default=None)
    if best is not None and abs(best - line) <= snapWindow:
        return DiffPosition(file, entry.oldPath, best, snapped=True)
    return None
