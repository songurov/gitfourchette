"""
One merge request, reviewed and answered without anyone watching.

The same three steps the dialog takes - read the change, ask the assistant,
post what comes back - with the decisions a person would otherwise make written
down instead: whether this merge request is owed a review at all, and which of
the findings it has already been told.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import subprocess
import tempfile
import time

from gitfourchette.exttools.aichat import ResponseStream, cliArguments
from gitfourchette.exttools.aireview import formatFinding, makeReviewPrompt, parseReview, summaryNote
from gitfourchette.exttools.aireviewcontext import projectGuidance
from gitfourchette.forge import audit, gitlab
from gitfourchette.forge.poster import PostState, ReviewPoster
from gitfourchette.forge.session import ForgeSession
from gitfourchette.localization import *
from gitfourchette.qt import *

logger = logging.getLogger(__name__)

MAX_NOTE_PAGES = 5


@dataclasses.dataclass
class PostedComment:
    where: str = ""
    "file:line, or empty for the summary note."
    state: str = ""
    body: str = ""


@dataclasses.dataclass
class RunOutcome:
    iid: int = 0
    caption: str = ""
    elapsed: float = 0.0
    "Seconds from the first request to the last comment posted."
    inputTokens: int = 0
    cachedInputTokens: int = 0
    outputTokens: int = 0
    comments: list = dataclasses.field(default_factory=list)
    "Every comment this run posted, as it was posted (see PostedComment)."
    decision: audit.Decision = dataclasses.field(default_factory=lambda: audit.Decision(audit.Verdict.Due))
    findings: int = 0
    posted: int = 0
    repeated: int = 0
    "Findings this merge request had already been told, and wasn't told twice."
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return _("{0}: {1}", self.caption, self.error)
        if not self.decision.due:
            return _("{0}: skipped, {1}", self.caption, self.decision.reason)
        if not self.findings:
            return _("{0}: reviewed, nothing worth a comment", self.caption)
        return _n("{0}: {n} comment posted", "{0}: {n} comments posted", self.posted, self.caption)


class ReviewRun(QObject):
    """Reviews one merge request and posts the result, or explains why it didn't."""

    progress = Signal(str)
    finished = Signal(object)
    "RunOutcome, always - a run that decided to do nothing still says so."

    def __init__(self, repo, project, token: str, changeRequest, providerPath: str, provider: str,
                 model="", language="", dimensions=(), rules=True, skipDrafts=True,
                 skipCiReviewed=True, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.project = project
        self.changeRequest = changeRequest
        self.provider = provider
        self.providerPath = providerPath
        self.model = model
        self.language = language
        self.dimensions = list(dimensions)
        self.rules = rules
        self.skipDrafts = skipDrafts
        self.skipCiReviewed = skipCiReviewed

        self.session = ForgeSession(token, self)
        self.outcome = RunOutcome(iid=changeRequest.iid, caption=changeRequest.caption())
        self.notes: list = []
        self.notePage = 1
        self.diffPage = 1
        self.index: dict = {}
        self.diffText = ""
        self.process = None
        self.stream = None
        self.stopped = False
        self.startedAt = 0.0
        self.summaryBody = ""
        self.checkout = ""
        """A worktree holding exactly the commit under review, so the assistant
        reads the code this merge request produces - not the branch that
        happens to be checked out here."""
        self.gitProcess = None

    # --- Reading the merge request -------------------------------------------

    def start(self):
        self.startedAt = time.monotonic()
        if not self.changeRequest.refs.isComplete():
            self.session.get(self.project.mergeRequestRoot(self.changeRequest.iid), self._gotMergeRequest)
        else:
            self._fetchNotes()

    def _gotMergeRequest(self, payload, error):
        if error:
            self._fail(error)
            return
        full = gitlab.readMergeRequest(payload) if isinstance(payload, dict) else None
        if full is None:
            self._fail(_("The merge request couldn’t be read."))
            return
        self.changeRequest = full
        self.outcome.caption = full.caption()
        self._fetchNotes()

    def _fetchNotes(self):
        self.session.get(gitlab.notesUrl(self.project, self.changeRequest.iid)
                         + f"?per_page=100&page={self.notePage}", self._gotNotes)

    def _gotNotes(self, payload, error):
        if error:
            self._fail(error)
            return
        page = payload if isinstance(payload, list) else []
        self.notes.extend(page)
        if len(page) >= 100 and self.notePage < MAX_NOTE_PAGES:
            self.notePage += 1
            self._fetchNotes()
            return
        # The head commit's date only matters when a pipeline review is there to
        # be judged against it, so it is fetched only then.
        if self.skipCiReviewed and audit.hasCiReview(self.notes):
            self.session.get(f"{self.project.apiRoot}/projects/{self.project.encodedPath}"
                             f"/repository/commits/{self.changeRequest.refs.headSha}", self._gotHeadCommit)
            return
        self._decide("")

    def _gotHeadCommit(self, payload, error):
        committedDate = ""
        if not error and isinstance(payload, dict):
            committedDate = str(payload.get("committed_date") or payload.get("created_at") or "")
        self._decide(committedDate)

    def _decide(self, headCommitDate: str):
        decision = audit.decide(self.changeRequest, self.notes, provider=self.provider,
                                headCommitDate=headCommitDate, skipDrafts=self.skipDrafts,
                                skipCiReviewed=self.skipCiReviewed)
        self.outcome.decision = decision
        if not decision.due:
            self._finish()
            return
        self.progress.emit(_("{0}: reading the diff…", self.outcome.caption))
        self._fetchDiff()

    def _fetchDiff(self):
        self.session.get(gitlab.mergeRequestDiffsUrl(self.project, self.changeRequest.iid, self.diffPage),
                         self._gotDiff)

    def _gotDiff(self, payload, error):
        if error:
            if self.diffPage == 1:
                self.session.get(gitlab.mergeRequestChangesUrl(self.project, self.changeRequest.iid), self._gotChanges)
                return
            self._fail(error)
            return
        gitlab.readDiffIndex(payload, self.index)
        self.diffText += gitlab.readDiffText(payload)
        if gitlab.isFullDiffPage(payload) and self.diffPage < 10:
            self.diffPage += 1
            self._fetchDiff()
            return
        self._prepareCheckout()

    def _gotChanges(self, payload, error):
        if error:
            self._fail(error)
            return
        gitlab.readDiffIndex(payload, self.index)
        self.diffText = gitlab.readDiffText(payload)
        self._prepareCheckout()

    # --- Putting the reviewed commit on disk ----------------------------------

    def _runGit(self, args: list[str], callback, workdir=""):
        process = QProcess(self)
        self.gitProcess = process
        process.setWorkingDirectory(workdir or self.repo.workdir)
        process.finished.connect(lambda code, _status: callback(code == 0))
        process.errorOccurred.connect(lambda _error: callback(False))
        process.start("git", args)

    def _prepareCheckout(self):
        """
        Fetch the merge request's own commit, then check it out beside the clone.

        A merge request lives on a ref the clone does not track
        (refs/merge-requests/N/head), and its branch is usually not checked out
        here at all. Without this the assistant would read whatever branch the
        reviewer happens to be on and call it the change under review.
        """
        head = self.changeRequest.refs.headSha
        remote = gitlab.preferredRemoteName(self.repo)
        if not head or not remote:
            self._review()
            return
        self.progress.emit(_("{0}: fetching the commit under review…", self.outcome.caption))
        self._runGit(["fetch", "--no-tags", "--quiet", remote,
                      f"+refs/merge-requests/{self.changeRequest.iid}/head"], self._fetched)

    def _fetched(self, ok: bool):
        head = self.changeRequest.refs.headSha
        if not ok:
            # Reviewing from the diff alone still works; it just cannot verify
            # anything the diff doesn't show, and the prompt will say so.
            logger.info("Couldn't fetch the merge request head; reviewing from the diff alone")
            self._review()
            return
        self.checkout = tempfile.mkdtemp(prefix="gitfourchette-review-")
        self._runGit(["worktree", "add", "--detach", "--quiet", self.checkout, head], self._checkedOut)

    def _checkedOut(self, ok: bool):
        if not ok:
            self._dropCheckout()
        self._review()

    def _dropCheckout(self):
        """Take the worktree away again, whatever happened to the review."""
        checkout, self.checkout = self.checkout, ""
        if not checkout:
            return
        subprocess.run(["git", "worktree", "remove", "--force", checkout],
                       cwd=self.repo.workdir, capture_output=True, check=False)
        shutil.rmtree(checkout, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo.workdir, capture_output=True, check=False)

    # --- Asking the assistant -------------------------------------------------

    def guidance(self) -> str:
        if not self.rules:
            return ""
        try:
            # The rules as they are in the merge request, when we have it:
            # a change that edits a rule is reviewed against the rule it ships.
            revision = self.changeRequest.refs.headSha if self.checkout else str(self.repo.head_commit_id)
            paths = set(self.index)
            text, _included, omitted = projectGuidance(self.repo, revision, paths)
            if omitted:
                text += ("\n\nGuidance omitted due to limits; do not claim full rule compliance:\n"
                         + "\n".join(omitted))
            return text
        except Exception:
            # Rules are criteria, not the review itself: losing them is worth a
            # line in the log, not the whole run.
            logger.warning("Couldn't read project guidance", exc_info=True)
            return ""

    def _review(self):
        if not self.diffText.strip():
            self.outcome.error = _("the merge request’s diff came back empty")
            self._finish()
            return
        scope = _("merge request !{0}, {1} into {2}", self.changeRequest.iid,
                  self.changeRequest.sourceBranch, self.changeRequest.targetBranch)
        prompt = makeReviewPrompt(self.diffText, dimensions=self.dimensions, guidance=self.guidance(),
                                  language=self.language, scope=scope,
                                  revision=self.changeRequest.refs.headSha if self.checkout else "")
        self.progress.emit(_("{0}: reviewing with {1}…", self.outcome.caption, self.provider.capitalize()))
        self.stream = ResponseStream(self.provider)
        process = QProcess(self)
        self.process = process
        if hasattr(QProcess, "UnixProcessParameters"):
            parameters = QProcess.UnixProcessParameters()
            parameters.flags = QProcess.UnixProcessFlag.CreateNewSession
            process.setUnixProcessParameters(parameters)
        process.setWorkingDirectory(self.checkout or self.repo.workdir)
        process.readyReadStandardOutput.connect(self._readOutput)
        process.finished.connect(self._reviewed)
        process.errorOccurred.connect(lambda _error: self._fail(process.errorString()))
        process.started.connect(lambda: (process.write(prompt.encode("utf-8")), process.closeWriteChannel()))
        process.start(self.providerPath, cliArguments(self.provider, self.model))

    def _readOutput(self):
        if not self.process:
            return
        self.buffer = getattr(self, "buffer", b"") + bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                self.stream.consume(event)

    def _reviewed(self, _code, _status):
        self._readOutput()
        if self.process:
            self.process.deleteLater()
        self.process = None
        review = parseReview(self.stream.text if self.stream else "")
        if review is None:
            self._fail(_("the assistant didn’t answer with a review"))
            return

        unsaid = audit.unsaidFindings(review.findings, self.notes)
        self.outcome.findings = len(review.findings)
        self.outcome.repeated = len(review.findings) - len(unsaid)
        review.findings = unsaid
        if not unsaid and not review.summary:
            self._finish()
            return

        marker = audit.runMarker(self.provider, self.changeRequest.refs.headSha)
        headerLines = [_("{0} → {1}", self.changeRequest.sourceBranch, self.changeRequest.targetBranch)]
        if self.outcome.repeated:
            headerLines.append(_n("{n} finding was already on this merge request",
                                  "{n} findings were already on this merge request", self.outcome.repeated))

        def buildSummary(inlineCount: int) -> str:
            self.summaryBody = summaryNote(review, _("Code Review"), headerLines=headerLines,
                                           inlineCount=inlineCount, language=self.language, marker=marker)
            return self.summaryBody

        self.progress.emit(_n("{0}: posting {n} comment…", "{0}: posting {n} comments…",
                              len(unsaid), self.outcome.caption))
        poster = ReviewPoster(self.project, self.session.token, self.changeRequest, "", unsaid,
                              provider=self.provider, language=self.language,
                              summaryBuilder=buildSummary, index=self.index, parent=self)
        poster.finished.connect(self._posted)
        poster.failed.connect(self._fail)
        poster.start()

    def _posted(self, results):
        self.outcome.posted = sum(1 for r in results if r.state in (PostState.Posted, PostState.Snapped))
        for result in results:
            self.outcome.comments.append(PostedComment(
                where=f"{result.finding.file}:{result.finding.line}",
                state=str(result.state),
                body=formatFinding(result.finding, language=self.language)))
        if self.summaryBody:
            self.outcome.comments.append(PostedComment(where="", state="summary", body=self.summaryBody))
        self._finish()

    def _fail(self, message: str):
        if self.stopped:
            return
        self.outcome.error = message
        self._finish()

    def _finish(self):
        """Close the books: how long it took, and what it spent."""
        self._dropCheckout()
        if self.startedAt:
            self.outcome.elapsed = time.monotonic() - self.startedAt
        if self.stream is not None:
            usage = self.stream.usage
            self.outcome.inputTokens = usage.inputTokens
            self.outcome.cachedInputTokens = usage.cachedInputTokens
            self.outcome.outputTokens = usage.outputTokens
        self.finished.emit(self.outcome)

    def stop(self):
        self.stopped = True
        self.session.abandon()
        self._dropCheckout()
        if self.process is not None:
            process, self.process = self.process, None
            process.kill()
