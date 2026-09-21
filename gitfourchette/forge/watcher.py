"""
The standing audit: every open merge request of the projects you picked,
reviewed as often as it changes.

A merge request opens, gets reviewed, its author pushes, and is owed a review
again - that loop is the whole point, and it runs on the merge request's own
memory (see audit.py) rather than on a list kept here. Nothing about a sweep is
remembered between runs: if GitFourchette is closed mid-sweep, the next one
picks up exactly the work that is still owed.
"""

from __future__ import annotations

import dataclasses
import enum
import logging

from gitfourchette import settings
from gitfourchette.exttools.aichat import availableProviders
from gitfourchette.forge import gitlab
from gitfourchette.forge.accounts import loadAccounts
from gitfourchette.forge.reviewrun import ReviewRun, RunOutcome
from gitfourchette.forge.session import ForgeSession
from gitfourchette.localization import *
from gitfourchette.porcelain import Repo
from gitfourchette.qt import *

logger = logging.getLogger(__name__)

MAX_MERGE_REQUESTS = 50


class ItemState(enum.StrEnum):
    Queued = "queued"
    Running = "running"
    Posted = "posted"
    Skipped = "skipped"
    Failed = "failed"
    Cancelled = "cancelled"


@dataclasses.dataclass
class AuditItem:
    """One merge request in the current sweep, and what became of it."""
    host: str = ""
    project: str = ""
    iid: int = 0
    title: str = ""
    author: str = ""
    draft: bool = False
    state: ItemState = ItemState.Queued
    detail: str = ""
    elapsed: float = 0.0
    tokens: int = 0
    comments: list = dataclasses.field(default_factory=list)
    "The comments this review posted, kept so they can be read here."

    def caption(self) -> str:
        if not self.iid:
            return self.title
        draft = "" if not self.draft or self.title.lower().startswith("draft") else _("Draft: ")
        return f"!{self.iid} {draft}{self.title}"

    def webUrl(self) -> str:
        return f"https://{self.host}/{self.project}/-/merge_requests/{self.iid}" if self.host and self.iid else ""


class AuditWatcher(QObject):
    """Sweeps the configured projects on a timer, one merge request at a time."""

    progress = Signal(str)
    ran = Signal(object)
    "A RunOutcome per merge request considered, whether or not it was reviewed."
    sweepFinished = Signal(int, int)
    "Reviewed, considered."
    itemsChanged = Signal()
    "The list (and the state of anything in it) moved; redraw whatever shows it."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sweep)
        self.queue: list = []
        self.items: list[AuditItem] = []
        """Every merge request of the current sweep, in order, with its state.
        Kept after the sweep so the window still shows what happened."""
        self.run: ReviewRun | None = None
        self.session: ForgeSession | None = None
        self.pending = 0
        self.reviewed = 0
        self.considered = 0
        self.sweeping = False

    # --- The timer ------------------------------------------------------------

    def enabled(self) -> bool:
        return bool(settings.prefs.auditEnabled and settings.prefs.auditRepos)

    def reschedule(self):
        """Follow whatever Settings says now, including being switched off."""
        self.timer.stop()
        if self.enabled() and not self.sweeping:
            self.timer.start(max(1, settings.prefs.auditIntervalMinutes) * 60_000)

    def stop(self):
        """Stop the sweep. What was posted stays posted; the rest is dropped."""
        self.timer.stop()
        wasSweeping = self.sweeping
        self.queue.clear()
        if self.run is not None:
            self.run.stop()
            self.run.deleteLater()
            self.run = None
        for item in self.items:
            if item.state in (ItemState.Queued, ItemState.Running):
                item.state = ItemState.Cancelled
                item.detail = _("stopped")
        self.sweeping = False
        self.itemsChanged.emit()
        if wasSweeping:
            self.sweepFinished.emit(self.reviewed, self.considered)
        self.reschedule()

    # --- One sweep ------------------------------------------------------------

    def sweep(self, force=False):
        """
        Walk the configured projects now.

        `force` is the menu item behind it: running one sweep by hand must work
        whether or not the timer is switched on, and must say why when it
        can't, rather than doing nothing in silence.
        """
        if self.sweeping:
            self.progress.emit(_("The audit is already running."))
            return
        if not force and not self.enabled():
            return
        if not settings.prefs.auditRepos:
            self.progress.emit(_("Choose the projects to audit in Settings first."))
            return
        providers = availableProviders()
        # Settings decides; the review window's last choice is the fallback, and
        # whatever is installed is the last resort - with a word about it, so a
        # reviewer isn't left wondering who wrote the comments.
        wanted = settings.prefs.auditProvider or settings.history.aiProvider
        provider = wanted if wanted in providers else next(iter(providers), "")
        if not provider:
            self.progress.emit(_("No assistant installed: the audit has nothing to review with."))
            self.reschedule()
            return
        if wanted and provider != wanted:
            self.progress.emit(_("{0} isn’t installed: reviewing with {1} instead.",
                                 wanted.capitalize(), provider.capitalize()))

        self.sweeping = True
        self.queue = []
        self.items = []
        self.itemsChanged.emit()
        self.reviewed = self.considered = 0
        self.provider = provider
        self.providerPath = providers[provider]
        self.pending = 0

        accounts = loadAccounts()
        targets = []
        for path in settings.prefs.auditRepos:
            try:
                repo = Repo(path)
            except Exception:
                self.progress.emit(_("Can’t open {0}: skipping it.", path))
                continue
            project = gitlab.projectFromRemote(gitlab.remoteUrlOf(repo))
            token = accounts.tokenFor(project.host) if project else ""
            if not project or not token:
                self.progress.emit(_("No GitLab token for {0}: skipping it.", path))
                continue
            targets.append((repo, project, token))

        if not targets:
            self._finishSweep()
            return

        self.pending = len(targets)
        for repo, project, token in targets:
            session = ForgeSession(token, self)
            query = f"{project.mergeRequestsRoot}?state=opened&per_page={MAX_MERGE_REQUESTS}&order_by=updated_at"
            session.get(query, lambda payload, error, r=repo, p=project, t=token, s=session:
                        self._gotMergeRequests(payload, error, r, p, t, s))

    def _gotMergeRequests(self, payload, error, repo, project, token, _session):
        if error:
            self.progress.emit(_("{0}: {1}", project.path, error))
        else:
            for changeRequest in gitlab.readMergeRequests(payload):
                item = AuditItem(host=project.host, project=project.path, iid=changeRequest.iid,
                                 title=changeRequest.title, author=changeRequest.author,
                                 draft=changeRequest.draft)
                self.items.append(item)
                self.queue.append((repo, project, token, changeRequest, item))
        self.pending -= 1
        self.itemsChanged.emit()
        if self.pending == 0:
            self.progress.emit(_n("Audit: {n} open merge request to look at…",
                                  "Audit: {n} open merge requests to look at…", len(self.queue)))
            self._next()

    def _next(self):
        if not self.queue:
            self._finishSweep()
            return
        repo, project, token, changeRequest, item = self.queue.pop(0)
        self.considered += 1
        self.item = item
        item.state = ItemState.Running
        item.detail = _("reading the merge request…")
        self.itemsChanged.emit()
        self.run = ReviewRun(
            repo, project, token, changeRequest, self.providerPath, self.provider,
            model=settings.prefs.auditModel or (settings.history.aiModels or {}).get(self.provider, ""),
            language=settings.history.aiLanguage,
            dimensions=settings.history.reviewDimensions,
            skipDrafts=settings.prefs.auditSkipDrafts,
            skipCiReviewed=settings.prefs.auditSkipCiReviewed,
            parent=self)
        self.run.progress.connect(self.progress)
        self.run.progress.connect(self._runSaid)
        self.run.finished.connect(self._ran)
        self.run.start()

    def _runSaid(self, message: str):
        """The run's own words, kept beside the merge request they belong to."""
        item = getattr(self, "item", None)
        if item is not None and item.state == ItemState.Running:
            item.detail = message.split(": ", 1)[-1]
            self.itemsChanged.emit()

    def _ran(self, outcome: RunOutcome):
        if self.run is not None:
            self.run.deleteLater()
            self.run = None
        item = getattr(self, "item", None)
        if item is not None:
            item.elapsed = outcome.elapsed
            item.tokens = outcome.inputTokens + outcome.outputTokens
            item.comments = outcome.comments
            if outcome.error:
                item.state, item.detail = ItemState.Failed, outcome.error
            elif not outcome.decision.due:
                item.state, item.detail = ItemState.Skipped, outcome.decision.reason
            else:
                item.state = ItemState.Posted
                item.detail = (_n("{n} comment posted", "{n} comments posted", outcome.posted)
                               if outcome.posted else _("nothing worth a comment"))
                if outcome.repeated:
                    item.detail += ", " + _n("{n} already said", "{n} already said", outcome.repeated)
            self.itemsChanged.emit()
        if outcome.decision.due and not outcome.error:
            self.reviewed += 1
        self.ran.emit(outcome)
        self.progress.emit(outcome.summary())
        self._next()

    def _finishSweep(self):
        self.sweeping = False
        self.sweepFinished.emit(self.reviewed, self.considered)
        self.reschedule()
