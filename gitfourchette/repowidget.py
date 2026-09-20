# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
import shlex
from collections.abc import Container
from contextlib import suppress
from typing import ClassVar

from gitfourchette import trtables
from gitfourchette import settings
from gitfourchette import tasks
from gitfourchette.diffarea import DiffArea
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.exttools.usercommand import UserCommand
from gitfourchette.forms.banner import Banner
from gitfourchette.forms.processdialog import ProcessDialog
from gitfourchette.forms.quicklaunch import QUICKLAUNCH_SEARCH_ONLY
from gitfourchette.forms.repostub import RepoStub
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.graphview.graphview import GraphView
from gitfourchette.localization import *
from gitfourchette.nav import NavHistory, NavLocator, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel, UC_FAKEID
from gitfourchette.sidebar.sidebar import Sidebar
from gitfourchette.syntax import LexJobCache
from gitfourchette.tasks import RepoTaskRunner, TaskEffects, TaskBook, gitflowtasks
from gitfourchette.tasks.misctasks import VerifyGpgQueue
from gitfourchette.tasks.nettasks import AutoFetchRemotes
from gitfourchette.themes import activeTheme
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class RepoWidget(QWidget):
    sharedSplitterSizes: ClassVar[dict[str, list[int]]] = {}
    "Shared reference among all RepoWidgets"

    nameChange = Signal()
    openRepo = Signal(str, NavLocator)
    openPrefs = Signal(str)
    locatorChanged = Signal(NavLocator)
    historyChanged = Signal()
    requestAttention = Signal()
    becameVisible = Signal()
    mustReplaceWithStub = Signal(RepoStub)
    aboutToDelete = Signal()

    busyMessage = Signal(str)
    statusMessage = Signal(str)
    clearStatus = Signal()
    statusChanged = Signal()
    """What this repo has outstanding may have changed (refreshed, committed, pushed…)."""

    repoModel: RepoModel
    taskRunner: RepoTaskRunner

    navLocator: NavLocator
    navHistory: NavHistory

    splittersToSave: list[QSplitter]
    centralSplitSizesBackup: list[int]

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    @property
    def workdir(self):
        return os.path.normpath(self.repoModel.repo.workdir)

    @property
    def superproject(self):
        return self.repoModel.superproject

    def __init__(self, repoModel: RepoModel, taskRunner: RepoTaskRunner, parent: QWidget):
        super().__init__(parent)
        self.setObjectName(f"{type(self).__name__}({repoModel.shortName})")

        # The stylesheet must be refreshed so that subsequent tweakFont calls can take effect.
        reevaluateStyleSheet(self)

        # Use RepoTaskRunner to schedule git operations to run on a separate thread.
        self.taskRunner = taskRunner
        self.taskRunner.setParent(self)
        self.taskRunner.ready.connect(self.onTaskRunnerReady)
        self.taskRunner.progress.connect(self.onRepoTaskProgress)
        self.taskRunner.repoGone.connect(self.onRepoGone)
        self.taskRunner.requestAttention.connect(self.requestAttention)

        # Report progress in long-running background processes
        self.processDialog = ProcessDialog(self)
        self.taskRunner.processStarted.connect(self.processDialog.connectProcess)

        self.repoModel = repoModel
        self.lastAutoFetchTime = QDateTime.currentSecsSinceEpoch()

        self.busyCursorDelayer = QTimer(self)
        self.busyCursorDelayer.setSingleShot(True)
        self.busyCursorDelayer.setInterval(100)
        self.busyCursorDelayer.timeout.connect(self.onBusyCursorDelayerTimeout)

        self.navLocator = NavLocator()
        self.navHistory = NavHistory()

        self.centralSplitSizesBackup = []

        # ----------------------------------
        # Splitters

        sideSplitter = QSplitter(Qt.Orientation.Horizontal, self)
        sideSplitter.setObjectName("Split_Side")
        self.sideSplitter = sideSplitter

        centralSplitter = QSplitter(Qt.Orientation.Vertical, self)
        centralSplitter.setObjectName("Split_Central")
        self.centralSplitter = centralSplitter

        dummyLayout = QVBoxLayout()
        dummyLayout.setSpacing(0)
        dummyLayout.setContentsMargins(QMargins())
        dummyLayout.addWidget(sideSplitter)
        self.setLayout(dummyLayout)

        # ----------------------------------
        # Build widgets

        sidebarContainer = self._makeSidebarContainer()
        graphContainer = self._makeGraphContainer()

        self.diffArea = DiffArea(self.repoModel, self)
        # Bridges for legacy code
        self.dirtyFiles = self.diffArea.dirtyFiles
        self.stagedFiles = self.diffArea.stagedFiles
        self.committedFiles = self.diffArea.committedFiles
        self.diffView = self.diffArea.diffView
        self.specialDiffView = self.diffArea.specialDiffView
        self.conflictView = self.diffArea.conflictView
        self.diffBanner = self.diffArea.diffBanner

        # ----------------------------------
        # Add widgets in splitters

        sideSplitter.addWidget(sidebarContainer)
        sideSplitter.addWidget(centralSplitter)
        # The splitter doesn't let the sidebar collapse, so hiding it is how
        # View > Show Sidebar gives its room to the graph and the diff
        self.sidebarContainer = sidebarContainer
        sidebarContainer.setVisible(settings.prefs.showSidebar)
        setDefaultSplitterSizes(sideSplitter, [self.defaultSidebarWidth(), 500])
        sideSplitter.setStretchFactor(0, 0)  # don't auto-stretch sidebar when resizing window
        sideSplitter.setStretchFactor(1, 1)
        sideSplitter.setChildrenCollapsible(False)

        centralSplitter.addWidget(graphContainer)
        centralSplitter.addWidget(self.diffArea)
        setDefaultSplitterSizes(centralSplitter, [100, 150])
        centralSplitter.setCollapsible(0, True)  # Let DiffArea be maximized, thereby hiding the graph
        centralSplitter.setCollapsible(1, False)  # DiffArea can never be collapsed
        self.centralSplitSizesBackup = centralSplitter.sizes()
        self.diffArea.contextHeader.maximizeButton.clicked.connect(self.maximizeDiffArea)
        centralSplitter.splitterMoved.connect(self.syncDiffAreaMaximizeButton)

        splitters: list[QSplitter] = self.findChildren(QSplitter)
        assert all(s.objectName() for s in splitters), "all splitters must be named, or state saving won't work!"
        self.splittersToSave = splitters

        # ----------------------------------
        # Connect signals

        # save splitter state in splitterMoved signal
        for splitter in self.splittersToSave:
            splitter.splitterMoved.connect(lambda pos, index, s=splitter: self.saveSplitterState(s))

        for fileList in self.dirtyFiles, self.stagedFiles, self.committedFiles:
            # File list view selections are mutually exclusive.
            fileList.nothingClicked.connect(lambda: self.diffArea.clearDocument(NavLocator.inWorkdir()))
            fileList.statusMessage.connect(self.statusMessage)
            fileList.openSubRepo.connect(lambda path: self.openRepo.emit(self.repo.in_workdir(path), NavLocator()))

        self.graphView.linkActivated.connect(self.processInternalLink)
        self.graphView.statusMessage.connect(self.statusMessage)
        self.graphView.clDelegate.requestSignatureVerification.connect(self.repoModel.queueGpgVerification)
        self.graphView.clDelegate.requestSignatureVerification.connect(self.scheduleFlushGpgVerificationQueue)

        self.diffArea.conflictView.openPrefs.connect(self.openPrefs)
        self.diffArea.commitDetailView.jumpRequested.connect(self.jumpFromCommitDetail)
        self.diffArea.commitDetailView.fileClicked.connect(self.openFileFromCommitDetail)

        # The Commit tab has a patch pane of its own; it answers the same way
        for diffView in self.diffArea.diffView, self.diffArea.commitPatchView:
            diffView.contextualHelp.connect(self.statusMessage)
        self.diffArea.specialDiffView.linkActivated.connect(self.processInternalLink)
        self.diffArea.commitSpecialPatchView.linkActivated.connect(self.processLinkFromCommitTab)

        self.sidebar.statusMessage.connect(self.statusMessage)
        self.sidebar.toggleHideRefPattern.connect(self.toggleHideRefPattern)
        self.sidebar.openSubmoduleRepo.connect(self.openSubmoduleRepo)
        self.sidebar.openSubmoduleFolder.connect(self.openSubmoduleFolder)
        self.sidebar.openWorktreeRepo.connect(lambda path: self.openRepo.emit(path, NavLocator()))
        self.sidebar.openWorktreeFolder.connect(openFolder)

        self.nameChange.connect(self.refreshWindowTitle)
        self.nameChange.connect(self.sidebar.sidebarModel.refreshRepoName)

        # ----------------------------------
        # Styling

        # Remove sidebar frame
        self.sidebar.setFrameStyle(QFrame.Shape.NoFrame)

        # Smaller fonts in diffArea buttons
        self.diffArea.applyCustomStyling()

        setTabOrder(
            self.sidebar.searchBar.lineEdit,
            self.sidebar,
            self.graphView.searchBar.lineEdit,
            self.graphView,
            self.diffArea.committedFiles.searchBar.lineEdit,
            self.diffArea.committedFiles,
            self.diffArea.dirtyFiles.searchBar.lineEdit,
            self.diffArea.dirtyFiles,
            self.diffArea.stagedFiles.searchBar.lineEdit,
            self.diffArea.stagedFiles,
            self.diffArea.diffView.searchBar.lineEdit,
            self.diffArea.diffView,
            self.diffArea.specialDiffView,
            self.diffArea.conflictView,
        )

        # ----------------------------------
        # Prime GraphView

        with QSignalBlockerContext(self.graphView):
            self.graphView.selectRowForLocator(NavLocator.inWorkdir())

        # ----------------------------------
        # Prime Sidebar

        with QSignalBlockerContext(self.sidebar):
            collapseCache = repoModel.prefs.collapseCache
            if collapseCache:
                self.sidebar.sidebarModel.collapseCache.update(collapseCache)
            self.sidebar.refresh(repoModel)

        # ----------------------------------
        self.restoreSplitterStates()
        self.refreshWindowTitle()
        self.refreshBanner()

        # Every second, check if we should auto-fetch.
        self.autoFetchTimer = QTimer(self)
        self.autoFetchTimer.timeout.connect(self.onAutoFetchTimerTimeout)
        self.autoFetchTimer.setInterval(1000)
        self.autoFetchTimer.start()

    def replaceWithStub(
            self,
            locator: NavLocator = NavLocator.Empty,
            maxCommits: int = -1,
            message: str = ""
    ) -> RepoStub:
        locator = locator or self.navLocator
        stub = RepoStub(parent=self.window(), workdir=self.workdir,
                        locator=locator, maxCommits=maxCommits)
        if message:
            stub.disableAutoLoad(message)
        self.mustReplaceWithStub.emit(stub)
        return stub

    def overridePendingLocator(self, locator: NavLocator):
        self.taskRunner.pendingEpilog.jumpTo = locator

    # -------------------------------------------------------------------------
    # Initial layout

    def _makeGraphContainer(self):
        graphView = GraphView(self.repoModel, self)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(graphView.searchBar)
        layout.addWidget(graphView)

        self.graphView = graphView
        return container

    def _makeSidebarContainer(self):
        sidebar = Sidebar(self)

        banner = Banner(self, orientation=Qt.Orientation.Vertical)
        banner.setProperty("class", "merge")
        banner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(sidebar.searchBar)
        layout.addWidget(sidebar)
        layout.addWidget(banner)

        self.sidebar = sidebar
        self.mergeBanner = banner

        return container

    # -------------------------------------------------------------------------
    # Splitter state

    def saveSplitterState(self, splitter: QSplitter):
        # QSplitter.saveState() saves a bunch of properties that we may want to
        # override in later versions, such as whether child widgets are
        # collapsible, the width of the splitter handle, etc. So, don't use
        # saveState(); instead, save the raw sizes for predictable results.
        name = splitter.objectName()
        sizes = splitter.sizes()[:]
        self.sharedSplitterSizes[name] = sizes

    def restoreSplitterStates(self):
        for splitter in self.splittersToSave:
            with suppress(KeyError):
                name = splitter.objectName()
                sizes = self.sharedSplitterSizes[name]
                splitter.setSizes(sizes)
        self.syncDiffAreaMaximizeButton()

    @staticmethod
    def defaultSidebarWidth() -> int:
        """The theme's width for a new tab's sidebar."""
        theme = activeTheme()
        return theme.sidebarWidth if theme is not None else 220

    def resetLayout(self, names: Container[str] | None = None):
        """
        Give every pane, or those of the splitters named, the size it has in a
        new tab (see MainWindow.resetLayout). The theme may have changed since
        this tab opened: the panes whose sizes it sets go by the current one.
        """
        themeDefaults = {
            self.sideSplitter.objectName(): [self.defaultSidebarWidth(), 500],
            **self.diffArea.themeDefaultSizes(),
        }
        for splitter in self.splittersToSave:
            name = splitter.objectName()
            if names is None or name in names:
                restoreDefaultSplitterSizes(splitter, themeDefaults.get(name))
        self.centralSplitSizesBackup = self.centralSplitter.sizes()
        self.syncDiffAreaMaximizeButton()

    def isDiffAreaMaximized(self):
        sizes = self.centralSplitter.sizes()
        return sizes[0] == 0

    def maximizeDiffArea(self):
        if self.isDiffAreaMaximized():
            # Diff area was maximized - restore non-collapsed sizes
            newSizes = self.centralSplitSizesBackup
        else:
            # Maximize diff area - back up current sizes
            self.centralSplitSizesBackup = self.centralSplitter.sizes()
            newSizes = [0, 1]
        self.centralSplitter.setSizes(newSizes)
        self.saveSplitterState(self.centralSplitter)
        self.syncDiffAreaMaximizeButton()

    def syncDiffAreaMaximizeButton(self):
        isMaximized = self.isDiffAreaMaximized()
        self.diffArea.contextHeader.maximizeButton.setChecked(isMaximized)

    # -------------------------------------------------------------------------
    # Navigation

    def saveFilePositions(self):
        if self.diffView.isVisibleTo(self):
            newLocator = self.diffView.preciseLocator()
            if not newLocator.isSimilarEnoughTo(self.navLocator):
                warnings.warn(f"RepoWidget/DiffView locator mismatch: {self.navLocator} vs. {newLocator}")
        else:
            newLocator = self.navLocator.coarse()

        self.navHistory.push(newLocator)
        self.navLocator = newLocator

    def jumpFromCommitDetail(self, locator: NavLocator):
        """A parent clicked in the Commit tab: go to that commit."""
        self.jump(locator)

    def openFileFromCommitDetail(self, deltaIndex: int):
        """A file clicked in the Commit tab: show its diff right there."""
        detailView = self.diffArea.commitDetailView
        delta = detailView.deltas[deltaIndex]
        path = delta.new.path or delta.old.path
        locator = NavLocator.inCommit(self.navLocator.commit, path)
        tasks.LoadPatchInCommitTab.invoke(self, delta, locator)

    def processLinkFromCommitTab(self, url: QUrl | str):
        """
        A link in the Commit tab's patch pane, e.g. "load this diff anyway".
        When it just asks for the same file under different terms, reload it
        where the user is looking instead of sending them to the Changes tab.
        """
        qurl = url if isinstance(url, QUrl) else QUrl(url)

        if qurl.scheme() == APP_URL_SCHEME and qurl.authority() == NavLocator.URL_AUTHORITY:
            locator = NavLocator.parseUrl(qurl)
            delta = self.diffArea.commitDetailView.deltaForPath(locator.path)
            if delta is not None and locator.commit == self.navLocator.commit:
                tasks.LoadPatchInCommitTab.invoke(self, delta, locator)
                return

        self.processInternalLink(url)

    def jump(self, locator: NavLocator, check=False):
        tasks.Jump.invoke(self, locator)
        if check:
            self.taskRunner.joinWorkerThread()
            assert self.navLocator.isSimilarEnoughTo(locator), f"failed to jump to: {locator}"

    def navigateBack(self):
        tasks.JumpBack.invoke(self)

    def navigateForward(self):
        tasks.JumpForward.invoke(self)

    # -------------------------------------------------------------------------

    def getTitle(self) -> str:
        return self.repoModel.shortName

    def statusIconKey(self) -> str:
        """
        Which marker this repo's tab should wear.

        Uncommitted work and unpushed commits are separate problems, and a tab
        that only counts working-directory files lets you believe you're done
        when your commits are still sitting on your machine. So they are shown
        apart: a dot for uncommitted, an arrow for unpushed, both for both.
        """
        dirty = self.repoModel.numUncommittedChanges > 0
        unpushed = self.unpushedCommitCount() > 0
        if dirty and unpushed:
            return "git-status-dirty-unpushed"
        elif dirty:
            return "git-status-dirty"
        elif unpushed:
            return "git-status-unpushed"
        return ""

    def statusTooltip(self) -> str:
        lines = [compactPath(self.workdir)]
        numChanges = self.repoModel.numUncommittedChanges
        if numChanges > 0:
            lines.append(_n("{n} uncommitted change", "{n} uncommitted changes", numChanges))
        ahead = self.unpushedCommitCount()
        if ahead > 0:
            lines.append(_n("{n} commit not pushed to {0}", "{n} commits not pushed to {0}",
                            ahead, self.repoModel.upstreams.get(self.repoModel.homeBranch, "")))
        if numChanges <= 0 and ahead <= 0:
            lines.append(_("Nothing outstanding"))
        return "\n".join(lines)

    def unpushedCommitCount(self) -> int:
        branch = self.repoModel.homeBranch
        if not branch:
            return 0
        ahead, _behind = self.repoModel.aheadBehind.get(branch, (0, 0))
        return ahead

    def closeEvent(self, event: QCloseEvent):
        """ Called when closing a repo tab """
        try:
            self.prepareForDeletion()
        except Exception as exc:  # pragma: no cover
            excMessageBox(exc, abortUnitTest=True)
        return super().closeEvent(event)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.becameVisible.emit()

    def prepareForDeletion(self):
        assert onAppThread()
        assert not hasattr(self, "_dead"), "RepoWidget already dead"
        self._dead = True

        # Kill any ongoing task then block UI thread until the task dies cleanly
        self.taskRunner.prepareForDeletion()

        self.aboutToDelete.emit()

        # Save sidebar collapse cache
        with NonCriticalOperation("Write repo prefs"):  # May raise OSError
            uiPrefs = self.repoModel.prefs
            collapseCache = self.sidebar.sidebarModel.collapseCacheLayers[0]
            if uiPrefs.collapseCache != collapseCache:
                uiPrefs.collapseCache = collapseCache.copy()
                uiPrefs.setDirty()
            if uiPrefs.isDirty():
                uiPrefs.write()

        # -----------------------------
        # GC help

        # Detangle cross-references to help out garbage collector
        self.diffView.prepareForDeletion()
        self.sidebar.repoWidget = None
        self.graphView.repoWidget = None
        for searchBar in self.findChildren(SearchBar):  # Help collect FileLists, GraphView, DiffView
            searchBar.buddy = None
        # Release any LexJobs that we own (it's not a big deal if we lose cached jobs for other tabs)
        LexJobCache.clear()

    def blameFile(self, path="", atCommit=NULL_OID):
        # Path not specified: pick one from the current locator
        if not path:
            loc = self.navLocator
            path = loc.path
            atCommit = self.navLocator.commit

            # If it's an uncommitted rename, start tracing the file's history
            # from its old name.
            if loc.context.isWorkdir():
                assert atCommit == NULL_OID
                delta = self.repoModel.findWorkdirDelta(loc.path)
                if delta is not None:
                    path = delta.old.path

        if not path:
            showInformation(self, tasks.OpenBlame.name(), _("Please select a file before performing this action."))
            return

        tasks.OpenBlame.invoke(self, path, atCommit)

    def openSubmoduleRepo(self, submoduleKey: str):
        path = self.repo.get_submodule_workdir(submoduleKey)
        self.openRepo.emit(path, NavLocator())

    def openSubmoduleFolder(self, submoduleKey: str):
        path = self.repo.get_submodule_workdir(submoduleKey)
        openFolder(path)

    def openRepoFolder(self):
        openFolder(self.workdir)

    def openSuperproject(self):
        superproject = self.superproject
        if superproject:
            self.openRepo.emit(superproject, NavLocator())
        else:
            showInformation(self, _("Open Superproject"), _("This repository does not have a superproject."))

    def copyRepoPath(self):
        text = self.workdir
        QApplication.clipboard().setText(text)
        self.statusMessage.emit(clipboardStatusMessage(text))

    def openGitignore(self):
        path = self.repo.in_workdir(".gitignore")
        self._openLocalConfigFile(path)

    def openLocalConfig(self):
        path = self.repo.in_gitdir("config")
        self._openLocalConfigFile(path)

    def openLocalExclude(self):
        path = self.repo.in_gitdir("info/exclude")
        self._openLocalConfigFile(path)

    def _openLocalConfigFile(self, fullPath: str):
        def createAndOpen():
            open(fullPath, "ab").close()
            ToolProcess.startTextEditor(self, fullPath)

        if not os.path.exists(fullPath):
            basename = os.path.basename(fullPath)
            askConfirmation(
                self,
                _("Open {0}", tquo(basename)),
                paragraphs(
                    _("File {0} does not exist.", bquo(fullPath)),
                    _("Do you want to create it?")),
                okButtonText=_("Create {0}", lquo(basename)),
                callback=createAndOpen)
        else:
            ToolProcess.startTextEditor(self, fullPath)

    def openTerminal(self):
        ToolProcess.startTerminal(self, self.workdir)

    def executeUserCommand(self, command: UserCommand):
        title = _("Run Command")

        try:
            compiledCommand = command.compile(self)
        except UserCommand.MultiTokenError as mte:
            errorText = (
                    _("The prerequisites for your command are not met:")
                    + f"<p><tt>{escape(command.command)}</tt></p>"
                    + toTightUL(f"{escape(str(error))} (<b>{escape(token)}</b>)"
                                for token, error in mte.tokenErrors.items()))
            showWarning(self, title, errorText)
            return

        def run():
            ToolProcess.startTerminal(self, self.workdir, compiledCommand)

        if command.alwaysConfirm or settings.prefs.confirmCommands:
            if not command.userTitle:
                question = _("Do you want to run this command in a terminal?")
            else:
                question = _("Do you want to run {0} in a terminal?").format(hquo(stripAccelerators(command.userTitle)))
            commandString = shlex.join(compiledCommand)
            question += f"<p><tt>{escape(commandString)}</tt></p>"
            askConfirmation(self, title, question, callback=run)
        else:
            run()

    # -------------------------------------------------------------------------
    # Entry point for generic "Find" command

    def dispatchSearchCommand(self, op: SearchBar.Op):
        searchBars = {
            self.sidebar: self.sidebar.searchBar,
            self.diffArea.dirtyFiles: self.diffArea.dirtyFiles.searchBar,
            self.diffArea.stagedFiles: self.diffArea.stagedFiles.searchBar,
            self.diffArea.committedFiles: self.diffArea.committedFiles.searchBar,
            self.diffArea.diffView: self.diffArea.diffView.searchBar,
        }

        # Find a sink to redirect search to
        focus = self.focusWidget()
        for sink, searchBar in searchBars.items():
            # Stop scanning if this sink or searchBar have focus
            if sink.isVisibleTo(self) and (focus is sink or focus is searchBar.lineEdit):
                break
        else:
            # Fall back to searching GraphView if nothing has focus
            searchBar = self.graphView.searchBar

        # Kick off search
        searchBar.popUp(op)

    # -------------------------------------------------------------------------

    def toggleHideRefPattern(self, refPattern: str, allButThis: bool = False):
        wasVisibleInGraph = self.graphView.isLocatorVisible(self.navLocator)

        assert refPattern.startswith("refs/")
        self.repoModel.toggleHideRefPattern(refPattern, allButThis)
        self.graphView.clFilter.updateHiddenCommits()

        # Hide/draw refboxes for commits that are shared by non-hidden refs
        self.graphView.viewport().update()

        # Re-jump to the locator if it just became visible/hidden.
        # This will display/hide the "hidden branch" banner.
        if wasVisibleInGraph != self.graphView.isLocatorVisible(self.navLocator):
            self.jump(self.navLocator)

    # -------------------------------------------------------------------------

    def refreshRepo(self):
        """Refresh the repo as soon as possible."""
        self.taskRunner.pendingEpilog.effects |= TaskEffects.DefaultRefresh
        self.onTaskRunnerReady()

    def onTaskRunnerReady(self):
        # Don't refresh if in background or task runner busy
        if not self.isVisible() or self.taskRunner.isBusy():
            return

        effects, jumpTo = self.taskRunner.consumePendingEffectsAndLocator()
        if effects:
            tasks.RefreshRepo.invoke(self, effects, jumpTo)
        elif jumpTo:
            tasks.Jump.invoke(self, jumpTo)

    def refreshWindowTitle(self):
        title = self.getTitle()
        inBrackets = ""
        repo = self.repo

        if repo.head_is_unborn:
            inBrackets = _("Unborn HEAD")
        elif repo.head_is_detached:
            oid = repo.head_commit_id
            inBrackets = f'{_("Detached HEAD")} @ {shortHash(oid)}'
        else:
            with suppress(GitError):
                inBrackets = repo.head_branch_shorthand

        if inBrackets:
            title = f"{title} [{inBrackets}]"

        self.setWindowTitle(title)
        # The tab shows what's outstanding, and that changes with every refresh
        self.statusChanged.emit()

    def refreshBanner(self):
        """ Refresh state banner (merging, cherrypicking, reverting, etc.) """
        repo = self.repo

        rstate = repo.state() if repo else RepositoryState.NONE

        bannerTitle = trtables.enum(rstate) if rstate != RepositoryState.NONE else ""
        bannerText = ""
        bannerHeeded = False
        bannerAction = ""
        bannerCallback = None

        def abortMerge():
            tasks.AbortMerge.invoke(self)

        if rstate == RepositoryState.MERGE:
            mergingWhat = ""
            with suppress(IndexError, KeyError):
                mergehead = self.repoModel.mergeheads[0]
                mergingWhat = shortHash(mergehead)  # Take commit hash first in case refsAt raises KeyError
                mergingWhat = self.repoModel.refsAt[mergehead][0]
                mergingWhat = RefPrefix.split(mergingWhat)[1]
            bannerTitle = _("Merging {0}", bquo(mergingWhat))

            if not repo.any_conflicts:
                bannerText += _("All conflicts fixed. Commit to conclude.")
                bannerHeeded = True
            else:
                bannerText += _("Conflicts need fixing.")

            bannerAction = englishTitleCase(_("Abort merge"))
            bannerCallback = abortMerge

        elif rstate == RepositoryState.CHERRYPICK:
            if not repo.any_conflicts:
                bannerText += _("Commit to conclude the cherry-pick.")
                bannerHeeded = True
            else:
                bannerText += _("Conflicts need fixing.")

            bannerAction = englishTitleCase(_("Abort cherry-pick"))
            bannerCallback = abortMerge

        elif rstate == RepositoryState.REVERT:
            if not repo.any_conflicts:
                bannerText += _("Commit to conclude the revert.")
                bannerHeeded = True
            else:
                bannerText += _("Conflicts need fixing.")

            bannerAction = englishTitleCase(_("Abort revert"))
            bannerCallback = abortMerge

        elif rstate == RepositoryState.NONE:
            if repo.any_conflicts:
                bannerTitle = _("Conflicts")
                bannerText = _("Fix the conflicts among the uncommitted changes.")
                bannerAction = englishTitleCase(_("Reset index"))
                bannerCallback = abortMerge

        else:
            bannerTitle = _("Warning")
            bannerText = _(
                "The repo is currently in state {state}, which {app} doesn’t support yet. "
                "Use <code>git</code> on the command line to continue.",
                app=qAppName(), state=bquo(trtables.enum(rstate)))

        with DisableWidgetUpdatesContext(self.sideSplitter):
            if bannerText or bannerTitle:
                self.mergeBanner.popUp(bannerTitle, bannerText, heeded=bannerHeeded, canDismiss=False)
                if bannerAction:
                    self.mergeBanner.addButton(bannerAction, bannerCallback)
            else:
                self.mergeBanner.setVisible(False)

    def refreshNumUncommittedChanges(self):
        self.sidebar.repaintUncommittedChanges()
        self.graphView.repaintCommit(UC_FAKEID)

    # -------------------------------------------------------------------------

    def selectRef(self, refName: str):
        oid = self.repo.commit_id_from_refname(refName)
        self.jump(NavLocator(NavContext.COMMITTED, commit=oid))

    # -------------------------------------------------------------------------

    def onRepoTaskProgress(self, progressText: str, withSpinner: bool = False):
        if withSpinner:
            self.busyMessage.emit(progressText)
        elif progressText:
            self.statusMessage.emit(progressText)
        else:
            self.clearStatus.emit()

        if not withSpinner:
            self.busyCursorDelayer.stop()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif not self.busyCursorDelayer.isActive():
            self.busyCursorDelayer.start()

    def onBusyCursorDelayerTimeout(self):
        self.setCursor(Qt.CursorShape.BusyCursor)

    def onRepoGone(self):
        message = _("Repository folder went missing:") + "\n" + escamp(self.workdir)
        self.replaceWithStub(message=message)

    def onAutoFetchTimerTimeout(self):
        if not settings.prefs.autoFetch or not self.isVisible() or self.taskRunner.isBusy():
            return

        # Check if it's time to auto-fetch.
        now = QDateTime.currentSecsSinceEpoch()
        interval = max(1, settings.prefs.autoFetchMinutes) * 60
        if now - self.lastAutoFetchTime > interval:
            AutoFetchRemotes.invoke(self)
            self.lastAutoFetchTime = now

    # -------------------------------------------------------------------------

    def processInternalLink(self, url: QUrl | str):
        if not isinstance(url, QUrl):
            url = QUrl(url)

        if url.isLocalFile():
            locator = NavLocator()
            fragment = url.fragment()
            if fragment:
                with suppress(ValueError):
                    locator = NavLocator.inCommit(Oid(hex=fragment))

            self.openRepo.emit(url.toLocalFile(), locator)
            return

        if url.scheme() != APP_URL_SCHEME:
            warnings.warn(f"Unsupported scheme in internal link: {url.toDisplayString()}")
            return

        logger.info(f"Internal link: {url.toDisplayString()}")

        simplePath = url.path().removeprefix("/")
        kwargs = dict(QUrlQuery(url).queryItems(QUrl.ComponentFormattingOption.FullyDecoded))

        if url.authority() == NavLocator.URL_AUTHORITY:
            locator = NavLocator.parseUrl(url)
            self.jump(locator)
        elif url.authority() == "expandlog":
            # After loading, jump back to what is currently the last commit
            jumpTo = NavLocator.inCommit(self.repoModel.commitSequence[-1].id)
            # Reload the repo
            maxCommits = int(kwargs.get("n", self.repoModel.nextTruncationThreshold))
            self.replaceWithStub(jumpTo, maxCommits)
        elif url.authority() == "prefs":
            self.openPrefs.emit(simplePath)
        else:  # pragma: no cover
            warnings.warn(f"Unsupported authority in internal link: {url.toDisplayString()}")

    # -------------------------------------------------------------------------

    def contextMenuItems(self):
        return self.contextMenuItemsByProxy(self, lambda: self)

    @classmethod
    def contextMenuItemsByProxy(cls, invoker, proxy):
        return [
            TaskBook.action(invoker, tasks.NewCommit, accel="C"),
            TaskBook.action(invoker, tasks.AmendCommit, accel="A"),
            TaskBook.action(invoker, tasks.NewStash),

            ActionDef.SEPARATOR,

            TaskBook.action(invoker, tasks.NewBranchFromHead, accel="B"),
            TaskBook.action(invoker, tasks.NewWorktree, accel="W"),
            TaskBook.action(invoker, tasks.FetchRemotes, accel="F"),
            TaskBook.action(invoker, tasks.PullBranch, accel="L"),
            TaskBook.action(invoker, tasks.PushBranch, accel="P"),

            TaskBook.action(invoker, tasks.NewRemote),

            ActionDef.SEPARATOR,

            # The menu bar keeps one live Git Flow menu for the repo in front.
            # A context menu gets its own: on macOS a native menu hangs under
            # one parent item only, so sharing it could take it off the menu bar.
            ActionDef(_("&Git Flow"), submenu=(invoker.gitFlowMenu if invoker is invoker.window()
                                               else proxy().gitFlowMenuItems())),

            ActionDef.SEPARATOR,

            TaskBook.action(invoker, tasks.RecallCommit),

            ActionDef.SEPARATOR,

            # TODO: Yech (invoker.window())
            *invoker.window().repolessActions(lambda: proxy().workdir),

            ActionDef.SEPARATOR,

            ActionDef(
                _("&Local Config Files"),
                submenu=[
                    ActionDef(".gitignore", lambda: proxy().openGitignore()),
                    ActionDef("config", lambda: proxy().openLocalConfig()),
                    ActionDef("exclude", lambda: proxy().openLocalExclude()),
                ]),

            TaskBook.action(invoker, tasks.EditRepoSettings),
        ]

    def gitFlowMenuItems(self) -> list[ActionDef]:
        """What Repo > Git Flow offers for this repo."""
        cfg = self.repo.gitflow_config()

        if cfg is None:
            # A repo that doesn't use Git Flow sees this one item, and only in
            # the menu: Quick Launch lists it once you type
            return [TaskBook.action(self, tasks.GitFlowInit, properties={QUICKLAUNCH_SEARCH_ONLY: True})]

        # A branch type whose prefix is empty is switched off
        items = [TaskBook.action(self, task) for kind, task in gitflowtasks.START_TASKS.items() if cfg.prefix(kind)]

        finishable = self.gitFlowFinishableBranches(cfg)
        if finishable:
            items.append(ActionDef.SEPARATOR)
        for kind, (branch, name) in finishable.items():
            task = gitflowtasks.FINISH_TASKS[kind]
            items.append(TaskBook.action(self, task, gitflowtasks.finishActionName(kind, name), taskArgs=branch))

        return items

    def gitFlowFinishableBranches(self, cfg: GitFlowConfig) -> dict[GitFlowKind, tuple[str, str]]:
        """
        Git Flow branches worth offering to finish from the Repo menu, at most
        one per kind, as {kind: (branch, name without prefix)}: the current
        branch, and the one whose finish just stopped on a merge that is now
        committed (HEAD is that merge, on the production or development branch).
        """
        repo = self.repo
        homeBranch = self.repoModel.homeBranch
        found: dict[GitFlowKind, tuple[str, str]] = {}

        classified = cfg.classify(homeBranch) if homeBranch else None
        if classified and classified[0] in gitflowtasks.FINISH_TASKS:
            found[classified[0]] = (homeBranch, classified[1])

        if homeBranch not in (cfg.master, cfg.develop):
            return found
        mergedIn = repo.head_commit.parent_ids[1:2]
        if not mergedIn:
            return found

        # Not every flow branch that is already merged: that would list every
        # merged-but-kept branch and every branch without commits, forever.
        for branch in repo.branches.local:
            classified = cfg.classify(branch)
            if not classified or classified[0] in found or classified[0] not in gitflowtasks.FINISH_TASKS:
                continue
            kind, name = classified
            if repo.branches.local[branch].target == mergedIn[0]:
                found[kind] = (branch, name)
            elif kind != GitFlowKind.FEATURE:
                # A release or hotfix is merged back into develop through its version tag
                with suppress(KeyError):
                    if repo.commit_id_from_tag_name(cfg.tag_name(name)) == mergedIn[0]:
                        found[kind] = (branch, name)

        return found

    @CallbackAccumulator.deferredMethod(250)
    def scheduleFlushGpgVerificationQueue(self):
        if self.taskRunner.isBusy():
            # Thanks to the deferredMethod decorator, this will reschedule
            # the call (instead of recursing).
            logger.debug("Rescheduling VerifyGpgQueue...")
            self.scheduleFlushGpgVerificationQueue()
            return

        VerifyGpgQueue.invoke(self)
