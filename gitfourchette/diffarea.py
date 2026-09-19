# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import json
import logging
import typing
from typing import Literal

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffbuttons import DiffButtons
from gitfourchette.diffview.diffdocument import DiffDocument
from gitfourchette.diffview.diffview import DiffView
from gitfourchette.diffview.specialdiff import ImageDelta, SpecialDiffError
from gitfourchette.diffview.specialdiffview import SpecialDiffView
from gitfourchette.diffview.sidebysidediffview import SideBySideDiffView
from gitfourchette.filelists.committedfiles import CommittedFiles
from gitfourchette.filelists.dirtyfiles import DirtyFiles
from gitfourchette.filelists.filelist import FileList
from gitfourchette.filelists.stagedfiles import StagedFiles
from gitfourchette.exttools.aichat import availableProviders, cliArguments, configuredModel, ResponseStream
from gitfourchette.forms.banner import Banner
from gitfourchette.forms.conflictview import ConflictView
from gitfourchette.forms.commitdetailview import CommitDetailView
from gitfourchette.forms.contextheader import ContextHeader
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext, NavLocator, NavFlags
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook, AmendCommit, NewCommit, NewStash
from gitfourchette.toolbox import *

FileStackPage = Literal["workdir", "commit"]
DiffStackPage = Literal["text", "special", "conflict"]

FILEHEADER_HEIGHT = 24

logger = logging.getLogger(__name__)


def gridPadding():
    return QSpacerItem(3, 1, QSizePolicy.Policy.Fixed)


class DiffArea(QWidget):
    CommitTab = 0
    ChangesTab = 1

    def __init__(self, repoModel, parent):
        super().__init__(parent)
        self.setObjectName("CommitExplorer")
        self.repoModel = repoModel
        self.commitAiProcess = None
        self.inlineCommitPending = False
        self.commitAiProviders = availableProviders()
        self.fileViewActions = []

        fileStack = self._makeFileStack(repoModel)
        diffContainer = self._makeDiffContainer(repoModel)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("Split_DiffArea")

        # The commit's own story (who, when, message, what it touched) sits in
        # a tab of its own, next to its changes - like Fork does it. Clicking a
        # file there opens its diff right below, without leaving the tab.
        commitDetailView = CommitDetailView(self)
        commitPatchStack, commitPatchView, commitSpecialPatchView = self._makeCommitPatchStack()

        commitPage = QSplitter(Qt.Orientation.Vertical, self)
        commitPage.setObjectName("Split_CommitTab")
        commitPage.addWidget(commitDetailView)
        commitPage.addWidget(commitPatchStack)
        commitPage.setSizes([300, 400])
        commitPage.setChildrenCollapsible(False)

        pageStack = QStackedWidget(self)
        pageStack.addWidget(commitPage)
        pageStack.addWidget(splitter)

        commitTabs = QTabBar(self)
        commitTabs.setObjectName("CommitTabs")
        commitTabs.setDrawBase(False)
        commitTabs.setExpanding(False)
        commitTabs.addTab(_p("noun", "Commit"))
        commitTabs.addTab(_p("noun", "Changes"))
        commitTabs.setCurrentIndex(self.ChangesTab)
        commitTabs.currentChanged.connect(pageStack.setCurrentIndex)
        commitTabs.setVisible(False)

        contextHeader = ContextHeader(self)

        diffBanner = Banner(self, orientation=Qt.Orientation.Horizontal)
        diffBanner.setProperty("class", "diff")
        diffBanner.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(commitTabs)
        layout.addWidget(contextHeader)
        layout.addWidget(diffBanner)
        layout.addWidget(QFaintSeparator(self))
        layout.addWidget(pageStack, 1)

        splitter.addWidget(fileStack)
        splitter.addWidget(diffContainer)
        splitter.setStretchFactor(0, 0)  # don't auto-stretch file lists when resizing window
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)

        self.fileStack = fileStack
        self.diffBanner = diffBanner
        self.contextHeader = contextHeader
        self.commitTabs = commitTabs
        self.pageStack = pageStack
        self.commitDetailView = commitDetailView
        self.commitPatchStack = commitPatchStack
        self.commitPatchView = commitPatchView
        self.commitSpecialPatchView = commitSpecialPatchView

        for passiveWidget in (
                self.diffHeader,
                self.committedHeader,
                self.dirtyHeader,
                self.stagedHeader
        ):
            passiveWidget.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        GFApplication.instance().prefsChanged.connect(self.diffButtons.refreshPrefs)
        GFApplication.instance().prefsChanged.connect(self.refreshDiffPresentation)
        GFApplication.instance().prefsChanged.connect(self.refreshCommitFormPlacement)
        GFApplication.instance().prefsChanged.connect(self.refreshFileViewActions)
        self.diffButtons.refreshPrefs()
        self.refreshDiffPresentation()
        self.refreshCommitFormPlacement()
        self.refreshFileViewActions()

        # If the commit form sits under the file lists, start out wide enough for
        # each row of its controls to fit on one line (they wrap onto more lines
        # if the user narrows the file lists down). Leave room for the commit
        # button's caption to grow: it counts the staged files once loaded.
        fileStackWidth = 260
        if settings.prefs.commitFormPlacement != settings.CommitFormPlacement.BottomBar:
            fileStackWidth = max(fileStackWidth, fileStack.sizeHint().width() + self.commitButton.sizeHint().width())
        splitter.setSizes([fileStackWidth, 500])

        # Ignore height in size policy to keep DiffArea from jumping around when we're showing a banner.
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Ignored)
        self.setMinimumHeight(175)

    # -------------------------------------------------------------------------
    # Constructor helpers

    def refreshFileViewActions(self):
        for listAction, treeAction in self.fileViewActions:
            listAction.setChecked(not settings.prefs.fileTreeView)
            treeAction.setChecked(settings.prefs.fileTreeView)

    def refreshDiffPresentation(self):
        self.diffPresentationStack.setCurrentIndex(int(settings.prefs.sideBySideDiff))

    def _makeFileViewButton(self):
        button = QToolButton(self)
        button.setObjectName("fileViewButton")
        button.setText("☰")
        button.setToolTip(_("File display"))
        button.setAutoRaise(True)
        button.setFixedSize(FILEHEADER_HEIGHT, FILEHEADER_HEIGHT)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(button)
        group = QActionGroup(menu)
        group.setExclusive(True)
        listAction = menu.addAction(_("Show as Path List"))
        treeAction = menu.addAction(_("Show as Filesystem Tree"))
        for action in (listAction, treeAction):
            action.setCheckable(True)
            group.addAction(action)
        listAction.triggered.connect(lambda: GFApplication.applyPrefs(fileTreeView=False))
        treeAction.triggered.connect(lambda: GFApplication.applyPrefs(fileTreeView=True))
        button.setMenu(menu)
        self.fileViewActions.append((listAction, treeAction))
        return button

    def refreshCommitFormPlacement(self):
        bottom = settings.prefs.commitFormPlacement == settings.CommitFormPlacement.BottomBar
        oldLayout = self.commitForm.parentWidget().layout()
        if oldLayout is not None:
            oldLayout.removeWidget(self.commitForm)
        targetLayout = self.bottomCommitFormLayout if bottom else self.stageCommitFormLayout
        targetLayout.addWidget(self.commitForm)
        self.stageCommitFormHost.setVisible(not bottom)
        self.bottomCommitFormHost.setVisible(bottom)
        if bottom and self.bottomCommitSplitter.sizes()[1] < 120:
            self.bottomCommitSplitter.setSizes([max(300, self.height() - 220), 220])

    def _makeFileStack(self, repoModel):
        dirtyContainer = self._makeDirtyContainer(repoModel)
        stageContainer = self._makeStageContainer(repoModel)
        committedFilesContainer = self._makeCommittedFilesContainer(repoModel)

        stagingSplitter = QSplitter(Qt.Orientation.Vertical, self)
        stagingSplitter.addWidget(dirtyContainer)
        stagingSplitter.addWidget(stageContainer)
        stagingSplitter.setObjectName("Split_Staging")
        stagingSplitter.setChildrenCollapsible(False)

        fileStack = QStackedWidget()
        fileStack.addWidget(stagingSplitter)
        fileStack.addWidget(committedFilesContainer)
        return fileStack

    def _makeDirtyContainer(self, repoModel):
        header = QElidedLabel(" ")
        header.setProperty("class", "panelTitle")
        header.setObjectName("dirtyHeader")
        header.setToolTip(_("Unstaged files: will not be included in the commit unless you stage them."))
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setEnabled(False)

        dirtyFiles = DirtyFiles(repoModel, self)
        fileViewButton = self._makeFileViewButton()
        stageAllButton = QToolButton(self)
        stageAllButton.setObjectName("stageAllButton")
        stageAllButton.setText(_("Stage All"))
        stageAllButton.setIcon(stockIcon("git-stage"))
        stageAllButton.setToolTip(_("Stage all files"))
        worktreeAiButton = QToolButton(self)
        worktreeAiButton.setObjectName("worktreeAiButton")
        worktreeAiButton.setText(_("AI"))
        worktreeAiButton.setAutoRaise(True)
        stageButton = QToolButton(self)
        stageButton.setObjectName("stageButton")
        stageButton.setText(_("Stage"))
        stageButton.setIcon(stockIcon("git-stage"))
        stageButton.setToolTip(_("Stage selected files"))
        appendShortcutToToolTip(stageButton, GlobalShortcuts.stageHotkeys[0])

        discardButton = QToolButton(self)
        discardButton.setObjectName("discardButton")
        discardButton.setText(_("Discard"))
        discardButton.setIcon(stockIcon("git-discard"))
        discardButton.setToolTip(_("Discard changes in selected files"))
        appendShortcutToToolTip(discardButton, GlobalShortcuts.discardHotkeys[0])

        container = QWidget(self)
        layout = QGridLayout(container)
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        layout.setContentsMargins(QMargins())
        # Row 0
        layout.addItem(gridPadding(),           0, 0)
        layout.addWidget(header,                0, 1)
        layout.addWidget(stageAllButton,        0, 2)
        layout.addWidget(stageButton,           0, 3)
        layout.addWidget(discardButton,         0, 4)
        layout.addWidget(worktreeAiButton,      0, 5)
        layout.addWidget(fileViewButton,        0, 6)
        # Row 1
        layout.addItem(QSpacerItem(1, 1),       1, 0, 1, 7)
        # Row 2
        layout.addWidget(dirtyFiles.searchBar,  2, 0, 1, 7)
        # Row 3
        layout.addWidget(dirtyFiles,            3, 0, 1, 7)
        layout.setRowStretch(3, 100)

        stageAllButton.clicked.connect(dirtyFiles.stageAll)
        stageButton.clicked.connect(dirtyFiles.stage)
        discardButton.clicked.connect(dirtyFiles.discard)
        dirtyFiles.selectedCountChanged.connect(lambda n: stageButton.setEnabled(n > 0))
        dirtyFiles.selectedCountChanged.connect(lambda n: discardButton.setEnabled(n > 0))
        dirtyFiles.selectedCountChanged.connect(self.refreshWorktreeAiButton)
        dirtyFiles.flModel.modelReset.connect(
            lambda: stageAllButton.setEnabled(not dirtyFiles.isEmpty()))

        self.dirtyFiles = dirtyFiles
        self.dirtyHeader = header
        self.stageButton = stageButton
        self.stageAllButton = stageAllButton
        self.discardButton = discardButton
        self.worktreeAiButton = worktreeAiButton
        worktreeAiButton.clicked.connect(self.askAiAboutSelectedChanges)

        return container

    def _makeStageContainer(self, repoModel):
        header = QElidedLabel(" ")
        header.setObjectName("stagedHeader")
        header.setProperty("class", "panelTitle")
        header.setToolTip(_("Staged files: will be included in the commit."))
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setEnabled(False)

        stagedFiles = StagedFiles(repoModel, self)
        fileViewButton = self._makeFileViewButton()

        unstageAllButton = QToolButton(self)
        unstageAllButton.setObjectName("unstageAllButton")
        unstageAllButton.setText(_("Unstage All"))
        unstageAllButton.setIcon(stockIcon("git-unstage"))
        unstageAllButton.setToolTip(_("Unstage all files"))

        unstageButton = QToolButton(self)
        unstageButton.setObjectName("unstageButton")
        unstageButton.setText(_("Unstage"))
        unstageButton.setIcon(stockIcon("git-unstage"))
        unstageButton.setToolTip(_("Unstage selected files"))
        appendShortcutToToolTip(unstageButton, GlobalShortcuts.discardHotkeys[0])

        messageEditor = QPlainTextEdit(self)
        messageEditor.setObjectName("commitMessageEditor")
        messageEditor.setPlaceholderText(
            _("Enter commit message. Use an empty line to separate subject and description."))
        messageEditor.setTabChangesFocus(True)
        messageEditor.setMinimumHeight(105)
        messageEditor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        subjectCounter = QLabel(self)
        subjectCounter.setObjectName("commitSubjectCounter")
        subjectCounter.setEnabled(False)
        subjectCounter.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        signoffCheckBox = QCheckBox(_("Sign Off"), self)
        signoffCheckBox.setObjectName("signoffCommitCheckBox")
        noVerifyCheckBox = QCheckBox(_("No-Verify"), self)
        noVerifyCheckBox.setObjectName("noVerifyCommitCheckBox")

        amendCheckBox = QCheckBox(_("Amend"), self)
        amendCheckBox.setObjectName("amendCommitCheckBox")
        amendCheckBox.setToolTip(TaskBook.tips[AmendCommit])

        stashButton = QToolButton(self)
        stashButton.setObjectName("stashButton")
        stashButton.setText(_("Stash…"))
        stashButton.setIcon(stockIcon("git-stash"))
        stashButton.setToolTip(TaskBook.tips[NewStash])
        stashButton.setAutoRaise(True)
        stashButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        aiButton = QToolButton(self)
        aiButton.setObjectName("commitAiButton")
        aiButton.setText(_("AI"))
        aiButton.setIcon(stockIcon("hint"))
        aiButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        aiButton.setAutoRaise(True)

        aiLanguageCombo = QComboBox(self)
        aiLanguageCombo.setObjectName("commitAiLanguageCombo")
        aiLanguageCombo.addItems([
            "Română", "English", "Русский", "Українська", "Deutsch", "Français", "Español"])
        aiLanguageCombo.setCurrentText(settings.history.aiLanguage)
        aiLanguageCombo.setToolTip(_("Language for the AI-generated commit message"))
        aiLanguageCombo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        aiLanguageCombo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        aiDetailCombo = QComboBox(self)
        aiDetailCombo.setObjectName("commitAiDetailCombo")
        aiDetailCombo.addItem(_("Concise"), "concise")
        aiDetailCombo.addItem(_("Detailed"), "detailed")
        aiDetailCombo.addItem(_("Deep"), "deep")
        detailIndex = aiDetailCombo.findData(settings.history.aiCommitDetail)
        aiDetailCombo.setCurrentIndex(max(0, detailIndex))
        aiDetailCombo.setToolTip(_("Level of detail and structure for the AI-generated commit message"))
        aiDetailCombo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        aiDetailCombo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        commitButton = QToolButton(self)
        commitButton.setObjectName("commitButton")
        commitButton.setText(_p("verb", "Commit"))
        commitButton.setIcon(stockIcon("git-commit", "gray=#599E5E"))
        commitButton.setToolTip(appendShortcutToToolTipText(TaskBook.tips[NewCommit], TaskBook.shortcuts[NewCommit][0]))
        commitButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        commitButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        commitButton.setAutoRaise(True)
        commitButton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

        commitPushButton = QPushButton(_("Commit && Push"), self)
        commitPushButton.setObjectName("commitPushButton")

        # Connect signals
        unstageButton.clicked.connect(stagedFiles.unstage)
        unstageAllButton.clicked.connect(stagedFiles.unstageAll)
        stagedFiles.selectedCountChanged.connect(lambda n: unstageButton.setEnabled(n > 0))
        stagedFiles.selectedCountChanged.connect(self.refreshWorktreeAiButton)
        stagedFiles.flModel.modelReset.connect(
            lambda: unstageAllButton.setEnabled(not stagedFiles.isEmpty()))
        stagedFiles.flModel.modelReset.connect(self.refreshCommitAiButton)
        stagedFiles.flModel.modelReset.connect(self.resetCompletedInlineCommit)

        def fullMessage():
            return messageEditor.toPlainText().strip()

        def beginCommit(pushAfter=False):
            message = fullMessage()
            task = AmendCommit if amendCheckBox.isChecked() else NewCommit
            if message:
                self.inlineCommitPending = True
                task.invoke(
                    self,
                    message,
                    signoffCheckBox.isChecked(),
                    noVerifyCheckBox.isChecked(),
                    pushAfter)
            else:
                # Preserve the keyboard shortcut/button workflow: an empty
                # inline form opens the full commit dialog as before.
                task.invoke(self)

        def updateSubjectCounter():
            text = messageEditor.toPlainText()
            subjectLength = len(text.split("\n", 1)[0])
            subjectCounter.setText(_("SUBJECT {0}/50").format(subjectLength))
            commitPushButton.setEnabled(bool(text.strip()))

        commitButton.clicked.connect(lambda: beginCommit(False))
        commitButtonMenu = ActionDef.makeQMenu(
            commitButton,
            [
                TaskBook.action(self, NewCommit),
                TaskBook.action(self, AmendCommit),
                TaskBook.action(self, NewStash),
            ])
        # Prevent shortcuts from taking over
        for action in commitButtonMenu.actions():
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        commitButton.setMenu(commitButtonMenu)
        commitPushButton.clicked.connect(lambda: beginCommit(True))
        stashButton.clicked.connect(lambda: NewStash.invoke(self))
        aiButton.clicked.connect(self.generateCommitMessage)
        def saveAiCommitOptions():
            settings.history.aiLanguage = aiLanguageCombo.currentText()
            settings.history.aiCommitDetail = aiDetailCombo.currentData()
            settings.history.setDirty()
        aiLanguageCombo.currentTextChanged.connect(saveAiCommitOptions)
        aiDetailCombo.currentIndexChanged.connect(saveAiCommitOptions)
        messageEditor.textChanged.connect(updateSubjectCounter)
        updateSubjectCounter()

        # The controls wrap onto more lines in a narrow panel,
        # instead of forcing the whole window to be wider.
        optionsRow = QFlowLayout()
        optionsRow.setSpacing(4)
        for widget in stashButton, aiButton, aiLanguageCombo, aiDetailCombo, subjectCounter:
            optionsRow.addWidget(widget)
        optionsRow.setAlignment(subjectCounter, Qt.AlignmentFlag.AlignRight)

        actionsRow = QFlowLayout()
        actionsRow.setSpacing(4)
        for widget in signoffCheckBox, noVerifyCheckBox, amendCheckBox, commitButton, commitPushButton:
            actionsRow.addWidget(widget)
        for widget in commitButton, commitPushButton:
            actionsRow.setAlignment(widget, Qt.AlignmentFlag.AlignRight)

        commitForm = QWidget(self)
        commitForm.setObjectName("commitForm")
        commitFormLayout = QVBoxLayout(commitForm)
        commitFormLayout.setContentsMargins(QMargins())
        commitFormLayout.setSpacing(4)
        commitFormLayout.addWidget(messageEditor, 1)
        commitFormLayout.addLayout(optionsRow)
        commitFormLayout.addLayout(actionsRow)
        commitForm.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        stageCommitFormHost = QWidget(self)
        stageCommitFormHost.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        stageCommitFormLayout = QVBoxLayout(stageCommitFormHost)
        stageCommitFormLayout.setContentsMargins(QMargins())
        stageCommitFormLayout.setSpacing(0)
        stageCommitFormLayout.addWidget(commitForm)

        # Lay out container
        container = QWidget(self)
        layout = QGridLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        # Row 0
        layout.addItem(gridPadding(),           0, 0)
        layout.addWidget(header,                0, 1)
        layout.addWidget(unstageAllButton,      0, 2)
        layout.addWidget(unstageButton,         0, 3)
        layout.addWidget(fileViewButton,        0, 4)
        # Row 1
        layout.addItem(QSpacerItem(1, 1),       1, 0)
        # Row 2
        layout.addWidget(stagedFiles.searchBar, 2, 0, 1, 5)  # row col rowspan colspan
        layout.addWidget(stagedFiles,           3, 0, 1, 5)
        layout.addWidget(stageCommitFormHost,   4, 0, 1, 5)
        layout.setRowStretch(3, 100)

        # Save references
        self.stagedHeader = header
        self.stagedFiles = stagedFiles
        self.unstageButton = unstageButton
        self.unstageAllButton = unstageAllButton
        self.commitButton = commitButton
        self.commitPushButton = commitPushButton
        self.commitAiButton = aiButton
        self.commitAiLanguageCombo = aiLanguageCombo
        self.commitAiDetailCombo = aiDetailCombo
        self.commitMessageEditor = messageEditor
        self.commitSubjectCounter = subjectCounter
        self.signoffCommitCheckBox = signoffCheckBox
        self.noVerifyCommitCheckBox = noVerifyCheckBox
        self.amendCommitCheckBox = amendCheckBox
        self.commitForm = commitForm
        self.stageCommitFormHost = stageCommitFormHost
        self.stageCommitFormLayout = stageCommitFormLayout
        self.refreshCommitAiButton()
        self.refreshWorktreeAiButton()

        return container

    def resetCompletedInlineCommit(self):
        if not self.inlineCommitPending or not self.stagedFiles.isEmpty():
            return
        self.inlineCommitPending = False
        self.commitMessageEditor.clear()
        self.signoffCommitCheckBox.setChecked(False)
        self.noVerifyCommitCheckBox.setChecked(False)
        self.amendCommitCheckBox.setChecked(False)

    def selectedWorktreePaths(self):
        paths = []
        for fileList in (self.dirtyFiles, self.stagedFiles):
            for delta in fileList.selectedDeltas():
                path = delta.new.path or delta.old.path
                if path and path not in paths:
                    paths.append(path)
        return paths

    def refreshWorktreeAiButton(self):
        if not hasattr(self, "worktreeAiButton") or not hasattr(self, "stagedFiles"):
            return
        paths = self.selectedWorktreePaths()
        hasProvider = bool(self.commitAiProviders)
        self.worktreeAiButton.setEnabled(hasProvider and bool(paths))
        if not hasProvider:
            tip = _("Install and configure Codex CLI or Claude Code to discuss changes with AI.")
        elif not paths:
            tip = _("Select one or more staged or unstaged files to ask AI about them.")
        else:
            tip = _n("Ask AI about the selected file…", "Ask AI about {n} selected files…", len(paths))
        self.worktreeAiButton.setToolTip(tip)

    def askAiAboutSelectedChanges(self):
        paths = self.selectedWorktreePaths()
        if not paths or not self.commitAiProviders:
            self.refreshWorktreeAiButton()
            return
        from gitfourchette.forms.aichatdialog import AiChatDialog
        dialog = AiChatDialog(self.repoModel.repo, [], self, worktreePaths=paths)
        dialog.open()

    def refreshCommitAiButton(self):
        """Enable commit-message generation only when it can do useful work."""
        hasProvider = bool(self.commitAiProviders)
        hasStagedChanges = hasattr(self, "stagedFiles") and not self.stagedFiles.isEmpty()
        busy = self.commitAiProcess is not None
        self.commitAiButton.setEnabled(hasProvider and hasStagedChanges and not busy)
        if busy:
            tip = _("Generating a commit message…")
        elif not hasProvider:
            tip = _("Install and configure Codex CLI or Claude Code to generate a commit message.")
        elif not hasStagedChanges:
            tip = _("Stage files to generate a commit message with AI.")
        else:
            provider = settings.history.aiProvider
            if provider not in self.commitAiProviders:
                provider = next(iter(self.commitAiProviders))
            tip = _("Generate a commit message from staged changes with {0}.", provider.capitalize())
        self.commitAiButton.setToolTip(tip)

    def generateCommitMessage(self):
        if self.commitAiProcess is not None or self.stagedFiles.isEmpty():
            return
        provider = settings.history.aiProvider
        if provider not in self.commitAiProviders:
            provider = next(iter(self.commitAiProviders), "")
        if not provider:
            self.refreshCommitAiButton()
            return
        self.commitAiProvider = provider
        self.commitAiPhase = "diff"
        self.commitAiOutput = b""
        self.commitAiError = b""
        self.commitAiButton.setText(_("AI…"))
        self._startCommitAiProcess(
            "git",
            ["--no-pager", "diff", "--cached", "--no-ext-diff", "--no-textconv", "--stat", "--patch", "--"],
        )

    def _startCommitAiProcess(self, program, arguments, prompt=""):
        process = QProcess(self)
        self.commitAiProcess = process
        process.setWorkingDirectory(self.repoModel.repo.workdir or self.repoModel.repo.path)
        process.readyReadStandardOutput.connect(
            lambda: self._readCommitAiOutput(bytes(process.readAllStandardOutput())))
        process.readyReadStandardError.connect(
            lambda: setattr(self, "commitAiError", (self.commitAiError + bytes(process.readAllStandardError()))[-16000:]))
        process.finished.connect(self._commitAiFinished)
        process.errorOccurred.connect(self._commitAiProcessError)
        if prompt:
            process.started.connect(lambda: (process.write(prompt.encode("utf-8")), process.closeWriteChannel()))
        process.start(program, arguments)
        self.refreshCommitAiButton()

    def _readCommitAiOutput(self, data):
        self.commitAiOutput += data

    def _commitAiProcessError(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.commitAiProcess:
            self._finishCommitAiWithError(self.commitAiProcess.errorString())

    def _commitAiFinished(self, code, exitStatus):
        process = self.commitAiProcess
        if process is None:
            return
        self._readCommitAiOutput(bytes(process.readAllStandardOutput()))
        self.commitAiError = (self.commitAiError + bytes(process.readAllStandardError()))[-16000:]
        process.deleteLater()
        self.commitAiProcess = None
        if code != 0 or exitStatus == QProcess.ExitStatus.CrashExit:
            self._finishCommitAiWithError(
                self.commitAiError.decode("utf-8", errors="replace") or _("CLI exited with code {0}.", code))
            return
        if self.commitAiPhase == "diff":
            diff = self.commitAiOutput.decode("utf-8", errors="replace")
            if not diff.strip():
                self._finishCommitAiWithError(_("There are no staged changes to describe."))
                return
            provider = self.commitAiProvider
            model = settings.history.aiModels.get(provider, "") or configuredModel(provider)
            language = self.commitAiLanguageCombo.currentText() or "the user's language"
            detail = self.commitAiDetailCombo.currentData()
            if detail == "concise":
                formatInstructions = (
                    "After the subject, add a blank line and a compact body of 3-6 informative lines. "
                    "Group related changes when more than one application area is affected.")
            elif detail == "deep":
                formatInstructions = (
                    "After the subject, add a blank line and a thorough, structured body. Group changes under "
                    "relevant component headings such as Backend, Frontend, Mobile, Tests, Infrastructure, or "
                    "Documentation. Include only areas evidenced by the diff. Under each heading use clear bullets "
                    "covering behavior, important implementation decisions, compatibility or risk, and tests. "
                    "Aim for 12-24 useful lines; do not claim tests were run unless the diff proves it.")
            else:
                formatInstructions = (
                    "After the subject, add a blank line and a structured body of 6-12 useful lines. Group changes "
                    "under relevant component headings such as Backend, Frontend, Mobile, Tests, Infrastructure, "
                    "or Documentation. Include only areas evidenced by the diff and use concise bullets.")
            prompt = (
                "Write a Git commit message for the staged changes below. Return only the commit message as plain "
                "text, starting with an imperative subject of at most 50 characters. " + formatInstructions +
                " Do not use Markdown fences, surrounding quotes, or meta-commentary. Use this language: "
                + language + ".\n\nStaged diff:\n" + diff[:180_000]
            )
            self.commitAiPhase = "assistant"
            self.commitAiOutput = b""
            self.commitAiError = b""
            self.commitAiStream = ResponseStream(provider)
            self._startCommitAiProcess(
                self.commitAiProviders[provider], cliArguments(provider, model), prompt)
            return

        for line in self.commitAiOutput.splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    self.commitAiStream.consume(event)
            except (ValueError, TypeError, AttributeError):
                continue
        message = self.commitAiStream.text.strip()
        if self.commitAiStream.error or not message:
            self._finishCommitAiWithError(
                self.commitAiStream.error or _("The CLI returned no commit message."))
            return
        self.commitMessageEditor.setPlainText(message)
        self.commitMessageEditor.setFocus()
        self.commitAiButton.setText(_("AI"))
        self.refreshCommitAiButton()

    def _finishCommitAiWithError(self, message):
        if self.commitAiProcess:
            self.commitAiProcess.deleteLater()
            self.commitAiProcess = None
        self.commitAiButton.setText(_("AI"))
        self.refreshCommitAiButton()
        showWarning(self, _("AI commit message"), message)

    def _makeCommittedFilesContainer(self, repoModel):
        committedFiles = CommittedFiles(repoModel, self)
        fileViewButton = self._makeFileViewButton()
        header = QElidedLabel(" ")
        header.setObjectName("committedHeader")
        header.setProperty("class", "panelTitle")
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setEnabled(False)

        container = QWidget(self)
        layout = QGridLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        layout.addItem(gridPadding(),               0, 0)
        layout.addWidget(header,                    0, 1)
        layout.addWidget(fileViewButton,            0, 2)
        layout.addWidget(committedFiles.searchBar,  1, 0, 1, 3)
        layout.addItem(QSpacerItem(1, 1),           2, 0, 1, 3)
        layout.addWidget(committedFiles,            3, 0, 1, 3)

        self.committedFiles = committedFiles
        self.committedHeader = header
        return container

    def _makeCommitPatchStack(self):
        """The Commit tab's own patch pane: a text diff, or a special one."""

        patchView = DiffView(self)
        patchContainer = QWidget(self)
        patchLayout = QVBoxLayout(patchContainer)
        patchLayout.setContentsMargins(0, 0, 0, 0)
        patchLayout.setSpacing(0)
        patchLayout.addWidget(patchView.searchBar)
        patchLayout.addWidget(patchView)

        specialPatchView = SpecialDiffView(self)

        stack = QStackedWidget(self)
        stack.addWidget(patchContainer)
        stack.addWidget(specialPatchView)
        stack.setVisible(False)  # nothing picked yet

        return stack, patchView, specialPatchView

    def _makeDiffContainer(self, repoModel):
        header = QLabel(" ")
        header.setObjectName("diffHeader")
        header.setProperty("class", "panelTitle")
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setContentsMargins(4, 0, 4, 0)
        header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Absorb horizontal space so the path stays left and toolbar stays right.
        header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)

        diffTools = DiffButtons(self)

        topContainer = QWidget(self)
        topLayout = QHBoxLayout(topContainer)
        topLayout.setContentsMargins(0, 0, 0, 0)
        topLayout.setSpacing(0)
        topLayout.addWidget(header, 1)
        topLayout.addWidget(diffTools, 0)

        diff = DiffView(self)

        diffViewContainer = QWidget(self)
        diffViewContainerLayout = QVBoxLayout(diffViewContainer)
        diffViewContainerLayout.setSpacing(0)
        diffViewContainerLayout.setContentsMargins(0, 0, 0, 0)
        diffViewContainerLayout.addWidget(diff.searchBar)
        diffViewContainerLayout.addWidget(diff)

        specialDiff = SpecialDiffView(self)

        sideBySideDiff = SideBySideDiffView(self)
        diff.documentReplaced.connect(sideBySideDiff.replaceDocument)

        diffPresentationStack = QStackedWidget(self)
        diffPresentationStack.addWidget(diffViewContainer)
        diffPresentationStack.addWidget(sideBySideDiff)

        conflict = ConflictView(repoModel, self)
        conflictScroll = QScrollArea()
        conflictScroll.setWidget(conflict)
        conflictScroll.setWidgetResizable(True)

        stack = QStackedWidget(self)
        # Add widgets in same order as DiffStackPage
        stack.addWidget(diffPresentationStack)
        stack.addWidget(specialDiff)
        stack.addWidget(conflictScroll)
        stack.setCurrentIndex(0)

        stackContainer = QWidget(self)
        layout = QVBoxLayout(stackContainer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(topContainer)
        layout.addWidget(stack)

        bottomCommitFormHost = QWidget(self)
        bottomCommitFormHost.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        bottomCommitFormLayout = QVBoxLayout(bottomCommitFormHost)
        bottomCommitFormLayout.setContentsMargins(QMargins())
        bottomCommitFormLayout.setSpacing(0)

        bottomCommitSplitter = QSplitter(Qt.Orientation.Vertical, self)
        bottomCommitSplitter.setObjectName("Split_BottomCommitForm")
        bottomCommitSplitter.setChildrenCollapsible(False)
        bottomCommitSplitter.addWidget(stackContainer)
        bottomCommitSplitter.addWidget(bottomCommitFormHost)
        bottomCommitSplitter.setStretchFactor(0, 1)
        bottomCommitSplitter.setStretchFactor(1, 0)
        bottomCommitSplitter.setSizes([500, 220])

        self.diffHeader = header
        self.diffStack = stack
        self.conflictView = conflict
        self.specialDiffView = specialDiff
        self.diffView = diff
        self.sideBySideDiffView = sideBySideDiff
        self.diffPresentationStack = diffPresentationStack
        self.diffButtons = diffTools
        self.bottomCommitFormHost = bottomCommitFormHost
        self.bottomCommitFormLayout = bottomCommitFormLayout
        self.bottomCommitSplitter = bottomCommitSplitter

        return bottomCommitSplitter

    def applyCustomStyling(self):
        for smallButton in (
                self.stageAllButton,
                self.worktreeAiButton,
                self.discardButton,
                self.unstageAllButton,
                self.unstageButton,
                self.stageButton,
                *self.diffButtons.buttons,
        ):
            smallButton.setMaximumHeight(FILEHEADER_HEIGHT)
            smallButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            smallButton.setAutoRaise(True)
            smallButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        for button in self.stageButton, self.unstageButton, self.discardButton:
            button.setEnabled(False)

        # Smaller font for header text
        for smallWidget in (
                self.contextHeader,
                self.diffHeader,
                self.committedHeader,
                self.dirtyHeader,
                self.stagedHeader,
                self.stageButton,
                self.stageAllButton,
                self.worktreeAiButton,
                self.unstageButton,
                self.unstageAllButton,
                self.discardButton,
                *self.diffButtons.buttons,
        ):
            tweakWidgetFont(smallWidget, 90)

    # -------------------------------------------------------------------------
    # File navigation

    def selectNextFile(self, down=True):
        page = self.fileStackPage()
        widgets: list[FileList]
        if page == "commit":
            widgets = [self.committedFiles]
        elif page == "workdir":
            widgets = [self.dirtyFiles, self.stagedFiles]
        else:
            raise NotImplementedError(f"Unknown FileStackPage {page}")

        numWidgets = len(widgets)
        selections = [w.selectedIndexes() for w in widgets]
        lengths = [w.fileCount() for w in widgets]

        # find widget to start from: topmost widget that has any selection
        leader = -1
        for i, selection in enumerate(selections):
            if selection:
                leader = i
                break

        if leader < 0:
            # selection empty; pick first non-empty widget as leader
            leader = 0
            row = 0
            while (leader < numWidgets) and (lengths[leader] == 0):
                leader += 1
        else:
            # get selected row in leader widget - TODO: this may not be accurate when multiple rows are selected
            row = widgets[leader].earliestSelectedRow()

            if down:
                row += 1
                while (leader < numWidgets) and (row >= lengths[leader]):
                    # out of rows in leader widget; jump to first row in next widget
                    leader += 1
                    row = 0
            else:
                row -= 1
                while (leader >= 0) and (row < 0):
                    # out of rows in leader widget; jump to last row in prev widget
                    leader -= 1
                    if leader >= 0:
                        row = lengths[leader] - 1

        # if we have a new valid selection, apply it, otherwise bail
        if 0 <= leader < numWidgets and 0 <= row < lengths[leader]:
            widgets[leader].setFocus()
            with QSignalBlockerContext(widgets[leader]):
                widgets[leader].clearSelection()
            widgets[leader].selectRow(row)
        else:
            # No valid selection
            QApplication.beep()

            # Focus on the widget that has some selected files in it
            for w in widgets:
                if len(w.selectedIndexes()) > 0:
                    w.setFocus()
                    break

    def fileListByContext(self, context: NavContext) -> FileList:
        if context == NavContext.STAGED:
            return self.stagedFiles
        elif context == NavContext.UNSTAGED:
            return self.dirtyFiles
        else:
            return self.committedFiles

    def setUpForLocator(self, locator: NavLocator) -> NavLocator:
        """
        Show relevant FileList widget, select correct file in it,
        and adjust auxiliary widgets (stage/unstage/discard buttons).

        If the desired path isn't available in the FileList,
        returns a new locator with a blank path.
        """
        fileList = self.fileListByContext(locator.context)

        with QSignalBlockerContext(self.dirtyFiles, self.stagedFiles, self.committedFiles):
            # Select correct row in FileList
            hasFile = False
            if locator.path:
                # Fix multiple "ghost" selections in DirtyFiles/StagedFiles with JumpBackOrForward.
                if not locator.hasFlags(NavFlags.BypassFileSelect):
                    fileList.clearSelection()
                # Select the file, if possible
                hasFile = fileList.selectFile(locator.path)

            # Blank selection?
            if not hasFile and locator.context != NavContext.SPECIAL:
                locator = locator.replace(path="")
                fileList.clearSelection()

            # Special treatment for workdir
            if locator.context.isWorkdir():
                staged = locator.context == NavContext.STAGED

                # Sync workdir buttons
                self.stageButton.setEnabled(hasFile and not staged)
                self.discardButton.setEnabled(hasFile and not staged)
                self.unstageButton.setEnabled(hasFile and staged)

                # Clear selection in opposite FileList
                oppositeFileList = self.dirtyFiles if staged else self.stagedFiles
                oppositeFileList.clearSelection()
                if hasFile:
                    oppositeFileList.highlightCounterpart(locator)

            # Set correct card in fileStack (after selecting the file to avoid flashing)
            self.setFileStackPageByContext(locator.context)

        self.refreshWorktreeAiButton()
        return locator

    # -------------------------------------------------------------------------
    # Commit tab

    def setCommitDetail(self, repoModel, commit, deltas, isStash=False):
        """Show the tabs and fill the Commit tab for the commit being viewed."""
        self.commitDetailView.setCommit(repoModel, commit, deltas, isStash)
        self.commitTabs.setVisible(True)
        self.hideCommitPatch()

    def hideCommitPatch(self):
        """Back to just the commit's story, until a file is picked again."""
        self.commitPatchStack.setVisible(False)
        self.commitPatchView.clear()

    def showCommitPatch(self, repo, delta, locator, document):
        """A file picked in the Commit tab: show its diff without leaving it."""

        if isinstance(document, DiffDocument):
            self.commitPatchView.replaceDocument(repo, delta, locator, document)
            self.commitPatchStack.setCurrentIndex(0)
        elif isinstance(document, ImageDelta):
            self.commitSpecialPatchView.displayImageDelta(document)
            self.commitPatchStack.setCurrentIndex(1)
        else:
            # Conflicts belong to the working directory, which has no Commit tab
            assert isinstance(document, SpecialDiffError), f"can't show {type(document)} here"
            self.commitSpecialPatchView.displaySpecialDiffError(document)
            self.commitPatchStack.setCurrentIndex(1)

        self.commitPatchStack.setVisible(True)

        # The patch pane just took half the room; once the layout settles,
        # bring the file list up so the next file is still one click away
        QTimer.singleShot(0, self.commitDetailView.scrollToFiles)

    def hideCommitDetail(self):
        """No commit in sight (the working directory, say): no tabs either."""
        self.commitDetailView.clear()
        self.commitTabs.setVisible(False)
        self.hideCommitPatch()
        self.showChangesTab()

    def showChangesTab(self):
        self.commitTabs.setCurrentIndex(DiffArea.ChangesTab)
        self.pageStack.setCurrentIndex(DiffArea.ChangesTab)

    # -------------------------------------------------------------------------
    # Clear

    def clearDocument(self, locator: NavLocator):
        # Enter empty special page
        self.specialDiffView.clear()
        self.setDiffStackPage("special")

        # Might as well free up any memory taken by DiffView document
        self.diffView.clear()

        self.diffHeader.setText(" ")

        self.setUpForLocator(locator)

    # -------------------------------------------------------------------------
    # Stacked widget helpers

    @property
    def _fileStackPageValues(self):
        return typing.get_args(FileStackPage)

    def fileStackPage(self) -> FileStackPage:
        return self._fileStackPageValues[self.fileStack.currentIndex()]

    def setFileStackPage(self, p: FileStackPage):
        self.fileStack.setCurrentIndex(self._fileStackPageValues.index(p))

    def setFileStackPageByContext(self, context: NavContext):
        page: FileStackPage = "workdir" if context.isWorkdir() else "commit"
        self.setFileStackPage(page)

    @property
    def _diffStackPageValues(self):
        return typing.get_args(DiffStackPage)

    def diffStackPage(self) -> DiffStackPage:
        return self._diffStackPageValues[self.diffStack.currentIndex()]

    def setDiffStackPage(self, p: DiffStackPage):
        self.diffStack.setCurrentIndex(self._diffStackPageValues.index(p))
