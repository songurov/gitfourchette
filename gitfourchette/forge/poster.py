"""
Putting a review on a merge request, one finding at a time.

Sequential on purpose: hosts rate-limit, and a half-posted review whose order
is unknown is far harder to clean up than a slow one. Every finding ends in a
result the reviewer can read - posted, snapped to a nearby line, left for the
summary because it couldn't be placed, or refused with the host's own reason.
"""

from __future__ import annotations

import dataclasses
import enum

from gitfourchette.exttools.aireview import Finding, formatFinding
from gitfourchette.forge.diffindex import diffLineIndex, resolvePosition
from gitfourchette.forge.gitlab import (
    ChangeRequest, ForgeProject, canApplySuggestion, discussionPayload,
    discussionsUrl, isFullDiffPage, mergeRequestChangesUrl, mergeRequestDiffsUrl, notePayload, notesUrl,
    readDiffIndex, readMergeRequest)
from gitfourchette.forge.session import ForgeSession
from gitfourchette.localization import *
from gitfourchette.qt import *


MAX_DIFF_PAGES = 10
"""A merge request past a thousand changed files is not one a person reviews a
line at a time; the findings that don't land travel in the summary note."""


class PostState(enum.StrEnum):
    Posted = "posted"
    Snapped = "snapped"
    "Posted, but on the nearest changed line rather than the one the model named."
    Unplaced = "unplaced"
    "Not on the diff; it travels in the summary note instead."
    Failed = "failed"


@dataclasses.dataclass
class PostResult:
    finding: Finding
    state: PostState
    message: str = ""


class ReviewPoster(QObject):
    """Posts the selected findings, then the summary note that gathers them all."""

    progress = Signal(int, int, str)
    "Done, total, and what is happening right now."

    finished = Signal(list)
    "list[PostResult], in the order the findings were given."

    failed = Signal(str)
    "The run stopped before posting anything: no merge request, no diff refs, bad token."

    def __init__(self, project: ForgeProject, token: str, changeRequest: ChangeRequest,
                 diffText: str, findings: list[Finding], provider: str, language="",
                 summaryBuilder=None, bodies=None, index=None, parent=None):
        super().__init__(parent)
        self.project = project
        self.changeRequest = changeRequest
        self.findings = list(findings)
        self.provider = provider
        self.language = language
        self.summaryBuilder = summaryBuilder
        self.bodies = dict(bodies or {})
        """Fingerprint -> the reviewer's own wording, when they rewrote a finding."""
        self.index = index if index else diffLineIndex(diffText)
        """Where a finding may be anchored. Built from the local diff to begin
        with, and replaced by the host's own diff before anything is posted -
        unless the caller already read that diff and handed it over."""
        self.onHostDiff = bool(index)
        self.diffPage = 1
        self.triedChanges = False
        self.results: list[PostResult] = []
        self.cursor = 0
        self.posted = 0
        self.session = ForgeSession(token, self)

    def total(self) -> int:
        return len(self.findings) + (1 if self.summaryBuilder else 0)

    def start(self):
        refs = self.changeRequest.refs
        if refs.isComplete():
            self._postNext() if self.onHostDiff else self._fetchDiff()
            return
        # The list endpoint doesn't carry diff_refs; without them an inline
        # comment has nothing to anchor to, so fetch the merge request itself.
        self.progress.emit(0, self.total(), _("Reading the merge request…"))
        self.session.get(self.project.mergeRequestRoot(self.changeRequest.iid), self._gotMergeRequest)

    def _gotMergeRequest(self, payload, error):
        if error:
            self.failed.emit(error)
            return
        fresh = readMergeRequest(payload) if isinstance(payload, dict) else None
        if fresh is None or not fresh.refs.isComplete():
            self.failed.emit(_("This merge request didn’t return the diff revisions needed to place comments."))
            return
        self.changeRequest.refs = fresh.refs
        self._postNext() if self.onHostDiff else self._fetchDiff()

    def _fetchDiff(self):
        """
        Ask the host for its own version of the change.

        A comment's position is only valid against the diff the host holds: it
        generates a line code from that, and a local branch one commit ahead or
        behind produces line numbers it rejects outright ("line_code can't be
        blank"). Reviewing locally is fine; anchoring locally is not.
        """
        self.progress.emit(0, self.total(), _("Reading the merge request’s diff…"))
        self.session.get(mergeRequestDiffsUrl(self.project, self.changeRequest.iid, self.diffPage), self._gotDiff)

    def _gotDiff(self, payload, error):
        if error:
            if not self.triedChanges:
                # A big merge request can make the paginated endpoint fail
                # outright (a 68-file one answered 500 here). The older endpoint
                # returns every file in one answer and still works.
                self.triedChanges = True
                self.session.get(mergeRequestChangesUrl(self.project, self.changeRequest.iid), self._gotDiff)
                return
            # Better to try the local diff and report each refusal than to
            # refuse to post anything at all.
            self.progress.emit(0, self.total(), _("Couldn’t read the merge request’s diff: {0}", error))
            self._postNext()
            return
        index = self.index if self.onHostDiff else {}
        readDiffIndex(payload, index)
        self.onHostDiff = True
        self.index = index
        if not self.triedChanges and isFullDiffPage(payload) and self.diffPage < MAX_DIFF_PAGES:
            self.diffPage += 1
            self._fetchDiff()
            return
        self._postNext()

    def _postNext(self):
        if self.cursor >= len(self.findings):
            self._postSummary()
            return
        finding = self.findings[self.cursor]
        self.progress.emit(len(self.results), self.total(),
                           _("Posting {0}:{1}…", finding.file, finding.line))
        position = resolvePosition(self.index, finding.file, finding.line)
        if position is None:
            self._record(PostState.Unplaced, _("Not on a line this merge request changes."))
            return
        edited = self.bodies.get(finding.fingerprint(), "").strip()
        if edited:
            # Hand-written wording goes out as written; only the marker is added,
            # because the next run reads it back to know what it already said.
            body = edited + "\n\n" + finding.marker(self.provider)
        else:
            applicable = canApplySuggestion(finding, position)
            body = formatFinding(finding, language=self.language, provider=self.provider,
                                 applicableSuggestion=applicable)
        payload = discussionPayload(body, position, self.changeRequest.refs)
        state = PostState.Snapped if position.snapped else PostState.Posted
        message = _("Moved to line {0}, the nearest changed line.", position.newLine) if position.snapped else ""
        self.session.post(discussionsUrl(self.project, self.changeRequest.iid), payload,
                          lambda reply, error, state=state, message=message: self._posted(reply, error, state, message))

    def _posted(self, _payload, error, state, message):
        if error:
            self._record(PostState.Failed, error)
            return
        self.posted += 1
        self._record(state, message)

    def _record(self, state: PostState, message: str):
        self.results.append(PostResult(self.findings[self.cursor], state, message))
        self.cursor += 1
        self._postNext()

    def _postSummary(self):
        if not self.summaryBuilder:
            self.finished.emit(self.results)
            return
        body = self.summaryBuilder(self.posted)
        self.progress.emit(len(self.results), self.total(), _("Posting the summary…"))
        self.session.post(notesUrl(self.project, self.changeRequest.iid), notePayload(body), self._summaryPosted)

    def _summaryPosted(self, _payload, error):
        if error:
            # The findings are already on the merge request; say what is missing
            # rather than pretending the whole run failed.
            self.failed.emit(_("The comments were posted, but the summary note wasn’t: {0}", error))
            return
        self.finished.emit(self.results)
