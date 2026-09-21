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


class AuditWatcher(QObject):
    """Sweeps the configured projects on a timer, one merge request at a time."""

    progress = Signal(str)
    ran = Signal(object)
    "A RunOutcome per merge request considered, whether or not it was reviewed."
    sweepFinished = Signal(int, int)
    "Reviewed, considered."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sweep)
        self.queue: list = []
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
        self.timer.stop()
        self.queue.clear()
        if self.run is not None:
            self.run.stop()
            self.run = None
        self.sweeping = False

    # --- One sweep ------------------------------------------------------------

    def sweep(self):
        if self.sweeping or not self.enabled():
            return
        providers = availableProviders()
        provider = settings.history.aiProvider
        if provider not in providers:
            provider = next(iter(providers), "")
        if not provider:
            self.progress.emit(_("No assistant installed: the audit has nothing to review with."))
            self.reschedule()
            return

        self.sweeping = True
        self.queue = []
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
            remoteUrl = next((repo.remotes[name].url for name in ("origin", *repo.remotes.names())
                              if name in repo.remotes), "")
            project = gitlab.projectFromRemote(remoteUrl)
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
                self.queue.append((repo, project, token, changeRequest))
        self.pending -= 1
        if self.pending == 0:
            self.progress.emit(_n("Audit: {n} open merge request to look at…",
                                  "Audit: {n} open merge requests to look at…", len(self.queue)))
            self._next()

    def _next(self):
        if not self.queue:
            self._finishSweep()
            return
        repo, project, token, changeRequest = self.queue.pop(0)
        self.considered += 1
        self.run = ReviewRun(
            repo, project, token, changeRequest, self.providerPath, self.provider,
            model=(settings.history.aiModels or {}).get(self.provider, ""),
            language=settings.history.aiLanguage,
            dimensions=settings.history.reviewDimensions,
            skipDrafts=settings.prefs.auditSkipDrafts,
            skipCiReviewed=settings.prefs.auditSkipCiReviewed,
            parent=self)
        self.run.progress.connect(self.progress)
        self.run.finished.connect(self._ran)
        self.run.start()

    def _ran(self, outcome: RunOutcome):
        if self.run is not None:
            self.run.deleteLater()
            self.run = None
        if outcome.decision.due and not outcome.error:
            self.reviewed += 1
        self.ran.emit(outcome)
        self.progress.emit(outcome.summary())
        self._next()

    def _finishSweep(self):
        self.sweeping = False
        self.sweepFinished.emit(self.reviewed, self.considered)
        self.reschedule()
