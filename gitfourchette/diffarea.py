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
from gitfourchette.filelists.filelistheader import FileListHeader, FileListTitle
from gitfourchette.filelists.stagedfiles import StagedFiles
from gitfourchette.exttools.aichat import availableProviders, cliArguments, configuredModel, ResponseStream
from gitfourchette.forms.banner import Banner
from gitfourchette.forms.commitarea import (
    BadgeToolButton, CommitDescriptionEdit, CommitMessageBox, MenuToolButton, PrimaryMenuButton, setStyleProperty)
from gitfourchette.forms.conflictview import ConflictView
from gitfourchette.forms.commitdetailview import CommitDetailView
from gitfourchette.forms.contextheader import ContextHeader
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext, NavLocator, NavFlags
from gitfourchette.porcelain import RepositoryState
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook, AmendCommit, NewCommit, NewStash
from gitfourchette.tasks.committasks import recentCommitSummaries
from gitfourchette.themes import ThemeVariant, activeTheme
from gitfourchette.toolbox import *

FileStackPage = Literal["workdir", "commit"]
DiffStackPage = Literal["text", "special", "conflict"]

FILEHEADER_HEIGHT = 24

AI_LANGUAGES = ["Română", "English", "Русский", "Українська", "Deutsch", "Français", "Español"]
"Languages offered for AI-written commit messages (the AI chat also takes any other one typed in)."

SUBJECT_SOFT_LIMIT = 50
"A commit subject longer than this gets cut short in some tools."

logger = logging.getLogger(__name__)


class DiffArea(QWidget):
    CommitTab = 0
    ChangesTab = 1
    FileTreeTab = 2

    def __init__(self, repoModel, parent):
        super().__init__(parent)
        self.setObjectName("CommitExplorer")
        self.repoModel = repoModel
        self.commitAiProcess = None
        self.inlineCommitPending = False
        self.commitTabFollowsFile = False
        "Once a file has been picked in the Commit tab, its patch pane keeps up with the file the user is on."
        self.commitAiProviders = availableProviders()
        self.fileViewActions = []
        self.fileListHeaders: list[FileListHeader] = []
        self.fileListGaps: list[QSpacerItem] = []
        "The pixel between each header and its list, where Neutral draws a line instead"

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
        setDefaultSplitterSizes(commitPage, [300, 400])
        commitPage.setChildrenCollapsible(False)

        pageStack = QStackedWidget(self)
        pageStack.addWidget(commitPage)
        pageStack.addWidget(splitter)

        # Three ways to look at the commit, as Fork lays them out: its own
        # story, the files it touched, and those files under their folders.
        commitTabs = QTabBar(self)
        commitTabs.setObjectName("CommitTabs")
        commitTabs.setDrawBase(False)
        commitTabs.setExpanding(False)
        commitTabs.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        commitTabs.setAccessibleName(_("Views of this commit"))
        for title, description in [
            (_p("noun", "Commit"), _("What this commit says, and who made it")),
            (_p("noun", "Changes"), _("The files this commit touched")),
            (_p("noun", "File Tree"), _("The files this commit touched, under their folders")),
        ]:
            tabIndex = commitTabs.addTab(title)
            commitTabs.setTabToolTip(tabIndex, description)
            commitTabs.setAccessibleTabName(tabIndex, title)
        commitTabs.setCurrentIndex(self.ChangesTab)
        commitTabs.currentChanged.connect(self.setCommitTabPage)

        # Neutral hugs the tabs with a track (see refreshTheme); the other
        # looks let them run the width of the pane, as they always have.
        commitTabBar = QWidget(self)
        commitTabBar.setObjectName("CommitTabBar")
        commitTabRow = QHBoxLayout(commitTabBar)
        commitTabRow.setContentsMargins(QMargins())
        commitTabRow.setSpacing(0)
        commitTabRow.addWidget(commitTabs, 1)
        commitTabFiller = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        commitTabRow.addSpacerItem(commitTabFiller)
        commitTabBar.setVisible(False)

        contextHeader = ContextHeader(self)

        diffBanner = Banner(self, orientation=Qt.Orientation.Horizontal)
        diffBanner.setProperty("class", "diff")
        diffBanner.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(commitTabBar)
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
        self.commitTabBar = commitTabBar
        self.commitTabRow = commitTabRow
        self.commitTabFiller = commitTabFiller
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
        # The buttons that are on wear the accent: a new theme is a new accent
        GFApplication.instance().restyle.connect(self.diffButtons.refreshPrefs)
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
        self.commitFormWidth = 0
        if settings.prefs.commitFormPlacement != settings.CommitFormPlacement.BottomBar:
            self.commitFormWidth = fileStack.sizeHint().width() + self.commitButton.sizeHint().width()

        defaults = self.themeDefaultSizes()
        setDefaultSplitterSizes(splitter, defaults[splitter.objectName()])
        if defaults[self.stagingSplitter.objectName()]:
            setDefaultSplitterSizes(self.stagingSplitter, defaults[self.stagingSplitter.objectName()])

        # Ignore height in size policy to keep DiffArea from jumping around when we're showing a banner.
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Ignored)
        self.setMinimumHeight(175)

    def themeDefaultSizes(self) -> dict[str, list[int]]:
        """
        The sizes the file lists start out with in the current theme, by
        splitter; [] leaves a splitter to Qt. The theme may want the file lists
        wider than the commit form needs: Neutral's are Fork's 360 px, with
        Unstaged over Staged at 70/30.
        """
        theme = activeTheme()
        width = max(260, theme.fileColumnWidth if theme is not None else 0, self.commitFormWidth)
        share = round(theme.unstagedShare * 1000) if theme is not None else 0
        return {
            "Split_DiffArea": [width, 500],
            "Split_Staging": [share, 1000 - share] if share else [],
        }

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
        button.setIcon(stockIcon("view-list-tree"))
        button.setAccessibleName(_("File display"))
        button.setToolTip(_("Show as list or folder tree"))
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
        # Under the diff, the commit area starts out as tall as it needs to be
        formHeight = self.commitForm.sizeHint().height()
        if (self.refreshBottomCommitFormVisibility()
                and self.bottomCommitSplitter.sizes()[1] < self.commitForm.minimumSizeHint().height()):
            self.bottomCommitSplitter.setSizes([max(300, self.height() - formHeight), formHeight])

    def refreshBottomCommitFormVisibility(self) -> bool:
        """
        Show the bottom-bar commit form under the working directory's diffs only.

        Like the form under the staged files, it belongs to the working
        directory: a past commit's diff runs to the bottom. While hidden, the
        splitter keeps the height the user gave the form.
        """
        bottom = settings.prefs.commitFormPlacement == settings.CommitFormPlacement.BottomBar
        visible = bottom and self.fileStackPage() == "workdir"
        self.bottomCommitFormHost.setVisible(visible)
        return visible

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
        self.stagingSplitter = stagingSplitter
        return fileStack

    def _makeFileListGap(self) -> QSpacerItem:
        gap = QSpacerItem(1, 1)
        self.fileListGaps.append(gap)
        return gap

    def _makeDirtyContainer(self, repoModel):
        header = FileListTitle(" ")
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
        stageAllButton.setAccessibleName(stageAllButton.toolTip())
        worktreeAiButton = QToolButton(self)
        worktreeAiButton.setObjectName("worktreeAiButton")
        worktreeAiButton.setText(_("AI"))
        worktreeAiButton.setAccessibleName(_("Ask AI about the selected files"))
        worktreeAiButton.setAutoRaise(True)
        stageButton = QToolButton(self)
        stageButton.setObjectName("stageButton")
        stageButton.setText(_("Stage"))
        stageButton.setIcon(stockIcon("git-stage"))
        stageButton.setToolTip(_("Stage selected files"))
        stageButton.setAccessibleName(stageButton.toolTip())
        appendShortcutToToolTip(stageButton, GlobalShortcuts.stageHotkeys[0])

        discardButton = QToolButton(self)
        discardButton.setObjectName("discardButton")
        discardButton.setText(_("Discard"))
        discardButton.setIcon(stockIcon("git-discard"))
        discardButton.setToolTip(_("Discard changes in selected files"))
        discardButton.setAccessibleName(discardButton.toolTip())
        appendShortcutToToolTip(discardButton, GlobalShortcuts.discardHotkeys[0])

        headerBar = FileListHeader(
            self, header, [stageAllButton, stageButton, discardButton, worktreeAiButton, fileViewButton],
            pill=stageButton)
        headerBar.setNeutralIcon(worktreeAiButton, "ai-sparkle")
        headerBar.setNeutralIcon(fileViewButton, "view-list-tree")
        self.fileListHeaders.append(headerBar)

        container = QWidget(self)
        layout = QGridLayout(container)
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        layout.setContentsMargins(QMargins())
        layout.addWidget(headerBar,             0, 0)
        layout.addItem(self._makeFileListGap(), 1, 0)
        layout.addWidget(dirtyFiles.searchBar,  2, 0)
        layout.addWidget(dirtyFiles,            3, 0)
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
        header = FileListTitle(" ")
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
        unstageAllButton.setAccessibleName(unstageAllButton.toolTip())

        unstageButton = QToolButton(self)
        unstageButton.setObjectName("unstageButton")
        unstageButton.setText(_("Unstage"))
        unstageButton.setIcon(stockIcon("git-unstage"))
        unstageButton.setToolTip(_("Unstage selected files"))
        unstageButton.setAccessibleName(unstageButton.toolTip())
        appendShortcutToToolTip(unstageButton, GlobalShortcuts.discardHotkeys[0])

        stageCommitFormHost = self._makeCommitForm(stagedFiles)

        # Connect signals
        unstageButton.clicked.connect(stagedFiles.unstage)
        unstageAllButton.clicked.connect(stagedFiles.unstageAll)
        stagedFiles.selectedCountChanged.connect(lambda n: unstageButton.setEnabled(n > 0))
        stagedFiles.selectedCountChanged.connect(self.refreshWorktreeAiButton)
        stagedFiles.flModel.modelReset.connect(
            lambda: unstageAllButton.setEnabled(not stagedFiles.isEmpty()))

        headerBar = FileListHeader(self, header, [unstageAllButton, unstageButton, fileViewButton], pill=unstageButton)
        headerBar.setNeutralIcon(fileViewButton, "view-list-tree")
        self.fileListHeaders.append(headerBar)

        # Lay out container
        container = QWidget(self)
        layout = QGridLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        layout.addWidget(headerBar,             0, 0)
        layout.addItem(self._makeFileListGap(), 1, 0)
        layout.addWidget(stagedFiles.searchBar, 2, 0)
        layout.addWidget(stagedFiles,           3, 0)
        layout.addWidget(stageCommitFormHost,   4, 0)
        layout.setRowStretch(3, 100)

        # Save references
        self.stagedHeader = header
        self.stagedFiles = stagedFiles
        self.unstageButton = unstageButton
        self.unstageAllButton = unstageAllButton
        self.refreshCommitAiButton()
        self.refreshCommitButton()
        self.refreshWorktreeAiButton()

        return container

    # -------------------------------------------------------------------------
    # Commit area

    def _makeCommitForm(self, stagedFiles: StagedFiles) -> QWidget:
        """
        The commit area: one box with the subject over the description, then
        one row with Amend, the other options (⋯), the subject's length and
        Commit, the one accented button. Returns the host that places it under
        the staged files; refreshCommitFormPlacement moves it under the diff.
        """

        subjectEditor = QLineEdit(self)
        subjectEditor.setObjectName("commitSubjectEditor")
        subjectEditor.setPlaceholderText(_("Commit subject"))
        subjectEditor.setAccessibleName(_("Commit subject"))
        subjectEditor.setFrame(False)

        descriptionEditor = CommitDescriptionEdit(self)
        descriptionEditor.setObjectName("commitDescriptionEditor")
        descriptionEditor.setPlaceholderText(_("Description"))
        descriptionEditor.setAccessibleName(_("Description"))

        # ✦: a click writes the message, the arrow picks its language and detail
        aiButton = MenuToolButton(self)
        aiButton.setObjectName("commitAiButton")
        aiButton.setIcon(stockIcon("ai-sparkle"))
        aiButton.setAccessibleName(_("Write the commit message with AI"))
        aiButton.setAutoRaise(True)
        aiButton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        aiMenu = QMenu(aiButton)
        aiMenu.setObjectName("commitAiMenu")
        aiMenu.aboutToShow.connect(self.fillCommitAiMenu)
        aiButton.setMenu(aiMenu)

        aiSpinner = QBusySpinner(self)
        aiSpinner.setVisible(False)

        # ⏱: pick the subject of a recent commit, as in the commit dialog
        recentButton = MenuToolButton(self)
        recentButton.setObjectName("commitRecentButton")
        recentButton.setIcon(stockIcon("commit-history"))
        recentButton.setAccessibleName(_("Recent messages"))
        recentButton.setToolTip(_("Recent messages"))
        recentButton.setAutoRaise(True)
        recentButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        recentMenu = QMenu(recentButton)
        recentMenu.setObjectName("commitRecentMenu")
        recentMenu.aboutToShow.connect(self.fillRecentSummariesMenu)
        recentButton.setMenu(recentMenu)

        subjectRow = QHBoxLayout()
        subjectRow.setContentsMargins(0, 0, 2, 0)
        subjectRow.setSpacing(0)
        subjectRow.addWidget(subjectEditor, 1)
        subjectRow.addWidget(aiSpinner)
        subjectRow.addWidget(aiButton)
        subjectRow.addWidget(recentButton)

        messageBox = CommitMessageBox(self)
        messageBox.setObjectName("commitMessageBox")
        messageBox.watchFocus(subjectEditor, descriptionEditor)
        boxLayout = QVBoxLayout(messageBox)
        boxLayout.setContentsMargins(1, 1, 1, 1)
        boxLayout.setSpacing(0)
        boxLayout.addLayout(subjectRow)
        boxLayout.addWidget(QFaintSeparator(messageBox))
        boxLayout.addWidget(descriptionEditor, 1)

        amendCheckBox = QCheckBox(_("Amend"), self)
        amendCheckBox.setObjectName("amendCommitCheckBox")
        amendCheckBox.setToolTip(TaskBook.tips[AmendCommit])

        # ⋯: the options that are usually off, with a dot on it while one is on
        signoffAction = QAction(_("Sign Off"), self)
        signoffAction.setObjectName("commitSignoffAction")
        signoffAction.setCheckable(True)
        signoffAction.setToolTip(_("Add a “Signed-off-by” line to the message (git commit --signoff)"))
        noVerifyAction = QAction(_("No-Verify"), self)
        noVerifyAction.setObjectName("commitNoVerifyAction")
        noVerifyAction.setCheckable(True)
        noVerifyAction.setToolTip(_("Skip the pre-commit and commit-msg hooks (git commit --no-verify)"))

        optionsButton = BadgeToolButton(self)
        optionsButton.setObjectName("commitOptionsButton")
        optionsButton.setIcon(stockIcon("more-circle"))
        optionsButton.setAccessibleName(_("More commit options"))
        optionsButton.setAutoRaise(True)
        optionsButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        optionsMenu = ActionDef.makeQMenu(optionsButton, [
            signoffAction,
            noVerifyAction,
            ActionDef.SEPARATOR,
            TaskBook.action(self, NewStash),
        ])
        optionsMenu.setToolTipsVisible(True)
        optionsButton.setMenu(optionsMenu)

        subjectCounter = QLabel(self)
        subjectCounter.setObjectName("commitSubjectCounter")
        subjectCounter.setProperty("class", "secondary")
        subjectCounter.setToolTip(_("Characters in the subject. Up to {0} reads well everywhere; "
                                    "some tools cut longer subjects short.", SUBJECT_SOFT_LIMIT))

        # Commit and Commit & Push work from the keyboard anywhere in the commit area
        commitAction = QAction(_p("verb", "Commit"), self)
        commitAction.setShortcuts(makeMultiShortcut("Ctrl+Return", "Ctrl+Enter"))
        commitAction.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        commitAction.triggered.connect(lambda: self.beginInlineCommit(pushAfter=False))
        commitPushAction = QAction(_("Commit && Push"), self)
        commitPushAction.setObjectName("commitPushAction")
        commitPushAction.setShortcuts(makeMultiShortcut("Ctrl+Alt+Return", "Ctrl+Alt+Enter"))
        commitPushAction.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        commitPushAction.triggered.connect(lambda: self.beginInlineCommit(pushAfter=True))

        commitButton = PrimaryMenuButton(self)
        commitButton.setObjectName("commitButton")
        commitButton.setText(_p("verb", "Commit"))
        commitButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        commitButton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        commitButton.clicked.connect(lambda: self.beginInlineCommit(pushAfter=False))
        commitButtonMenu = ActionDef.makeQMenu(commitButton, [
            commitPushAction,
            ActionDef.SEPARATOR,
            TaskBook.action(self, NewCommit),
            TaskBook.action(self, AmendCommit),
        ])
        commitButton.setMenu(commitButtonMenu)

        # The menus' task actions have the same shortcuts as the Repo menu:
        # leave those to the main window, or Qt would find them ambiguous.
        for menu in commitButtonMenu, optionsMenu:
            for action in menu.actions():
                if action is not commitPushAction:
                    action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)

        # Buttons and the check box keep the focus in the message when clicked
        for widget in aiButton, recentButton, amendCheckBox, optionsButton, commitButton:
            widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        # The row's controls wrap onto more lines in a narrow panel,
        # instead of forcing the whole window to be wider.
        actionsRow = QFlowLayout()
        actionsRow.setSpacing(8)
        for widget in amendCheckBox, optionsButton, subjectCounter, commitButton:
            actionsRow.addWidget(widget)
        for widget in subjectCounter, commitButton:
            actionsRow.setAlignment(widget, Qt.AlignmentFlag.AlignRight)

        commitForm = QWidget(self)
        commitForm.setObjectName("commitForm")
        commitForm.addActions([commitAction, commitPushAction])
        commitFormLayout = QVBoxLayout(commitForm)
        commitFormLayout.setContentsMargins(8, 8, 8, 8)
        commitFormLayout.setSpacing(6)
        commitFormLayout.addWidget(messageBox, 1)
        commitFormLayout.addLayout(actionsRow)
        commitForm.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        setTabOrder(subjectEditor, descriptionEditor, aiButton, recentButton, amendCheckBox, optionsButton, commitButton)

        stageCommitFormHost = QWidget(self)
        stageCommitFormHost.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        stageCommitFormLayout = QVBoxLayout(stageCommitFormHost)
        stageCommitFormLayout.setContentsMargins(QMargins())
        stageCommitFormLayout.setSpacing(0)
        stageCommitFormLayout.addWidget(commitForm)

        # Connect signals
        aiButton.clicked.connect(self.onCommitAiButtonClicked)
        subjectEditor.textEdited.connect(self.moveExtraLinesToDescription)
        subjectEditor.returnPressed.connect(descriptionEditor.setFocus)
        subjectEditor.textChanged.connect(self.refreshCommitSubjectCounter)
        subjectEditor.textChanged.connect(self.refreshCommitPushAction)
        descriptionEditor.textChanged.connect(self.refreshCommitPushAction)
        amendCheckBox.toggled.connect(self.onAmendToggled)
        signoffAction.toggled.connect(self.refreshCommitOptionsButton)
        noVerifyAction.toggled.connect(self.refreshCommitOptionsButton)
        stagedFiles.flModel.modelReset.connect(self.refreshCommitAiButton)
        stagedFiles.flModel.modelReset.connect(self.refreshCommitButton)
        stagedFiles.flModel.modelReset.connect(self.resetCompletedInlineCommit)

        # Save references
        self.commitForm = commitForm
        self.commitMessageBox = messageBox
        self.commitSubjectEditor = subjectEditor
        self.commitDescriptionEditor = descriptionEditor
        self.commitAiButton = aiButton
        self.commitAiSpinner = aiSpinner
        self.commitRecentButton = recentButton
        self.amendCommitCheckBox = amendCheckBox
        self.commitOptionsButton = optionsButton
        self.commitSignoffAction = signoffAction
        self.commitNoVerifyAction = noVerifyAction
        self.commitSubjectCounter = subjectCounter
        self.commitButton = commitButton
        self.commitAction = commitAction
        self.commitPushAction = commitPushAction
        self.stageCommitFormHost = stageCommitFormHost
        self.stageCommitFormLayout = stageCommitFormLayout
        self.amendPrefill: str | None = None
        self.loadedMessage = ""
        self.loadedMessageSplit = ("", "")

        self.refreshCommitSubjectCounter()
        self.refreshCommitOptionsButton()

        return stageCommitFormHost

    def commitMessage(self) -> str:
        """The message in the commit area: the subject, then a blank line and the description if there's one."""
        subject = self.commitSubjectEditor.text().strip()
        description = self.commitDescriptionEditor.toPlainText().strip()
        if (subject, description) == self.loadedMessageSplit:
            # A message that came in and wasn't touched goes back out word for
            # word: amending mustn't reflow a body that had no blank line
            # after its subject.
            return self.loadedMessage
        return "\n\n".join(part for part in (subject, description) if part)

    def setCommitMessage(self, message: str):
        """Put a message in the commit area: its first line in the subject, the rest in the description."""
        message = message.strip()
        subject, _newline, description = message.partition("\n")
        subject = subject.strip()
        description = description.strip("\n")
        self.commitSubjectEditor.setText(subject)
        self.commitDescriptionEditor.setPlainText(description)
        self.loadedMessage = message
        self.loadedMessageSplit = (subject, description.strip())

    def moveExtraLinesToDescription(self, text: str):
        """A message pasted into the subject: its first line stays there, the other lines join the description."""
        if "\n" not in text:
            return
        subject, _newline, extra = text.partition("\n")
        with QSignalBlockerContext(self.commitSubjectEditor):
            self.commitSubjectEditor.setText(subject.rstrip())
        self.commitSubjectEditor.textChanged.emit(self.commitSubjectEditor.text())
        extra = extra.strip("\n")
        if not extra:
            return
        # Whatever was already written in the description stays: the pasted lines come after it
        description = self.commitDescriptionEditor.toPlainText().rstrip()
        self.commitDescriptionEditor.setPlainText(f"{description}\n\n{extra}" if description else extra)

    def beginInlineCommit(self, pushAfter=False):
        if not self.commitAction.isEnabled():
            QApplication.beep()
            return
        message = self.commitMessage()
        task = AmendCommit if self.amendCommitCheckBox.isChecked() else NewCommit
        if message:
            self.inlineCommitPending = True
            task.invoke(
                self,
                message,
                self.commitSignoffAction.isChecked(),
                self.commitNoVerifyAction.isChecked(),
                pushAfter)
        else:
            # Preserve the keyboard shortcut/button workflow: an empty
            # inline form opens the full commit dialog as before.
            task.invoke(self)

    def onAmendToggled(self, amend: bool):
        """
        Ticking Amend with nothing written loads the last commit's message, to
        edit. Unticking it straight away takes that message back out.
        """
        repo = self.repoModel.repo
        if amend and not self.commitMessage() and not repo.head_is_unborn:
            self.setCommitMessage(repo.head_commit.message)
            self.amendPrefill = self.commitMessage()
        elif not amend:
            if self.amendPrefill is not None and self.commitMessage() == self.amendPrefill:
                self.setCommitMessage("")
            self.amendPrefill = None
        self.refreshCommitButton()

    def refreshCommitButton(self):
        """
        Commit is the one accented button, and it's ready to go only when
        there's something to commit: staged files, Amend ticked (which may only
        reword), or a merge, cherry-pick or revert to conclude. Otherwise it
        looks and acts dead, but its menu stays open for business.
        """
        if not hasattr(self, "stagedFiles"):
            return
        numStaged = self.stagedFiles.fileCount()
        amend = self.amendCommitCheckBox.isChecked()
        concluding = self.repoModel.repo.state() != RepositoryState.NONE
        ready = amend or numStaged > 0 or concluding

        if amend:
            self.commitButton.setText(_("Amend"))
            self.commitPushAction.setText(_("Amend && Push"))
            tip = TaskBook.tips[AmendCommit]
        else:
            self.commitButton.setText(_p("verb", "Commit"))
            self.commitPushAction.setText(_("Commit && Push"))
            if numStaged:
                tip = _n("Commit {n} staged file", "Commit {n} staged files", numStaged)
            elif concluding:
                tip = TaskBook.tips[NewCommit]
            else:
                tip = _("Nothing is staged. Stage files first, or tick Amend to change the last commit.")

        # The button itself stays enabled even when it's not ready, so that New
        # Commit…, Amend Last Commit… and Commit & Push keep their way in
        self.commitButton.setReady(ready)
        self.commitAction.setEnabled(ready)
        self.refreshCommitPushAction()
        self.commitButton.setAccessibleDescription(tip)
        if ready:
            tip = appendShortcutToToolTipText(tip, self.commitAction.shortcut())
        self.commitButton.setToolTip(tip)

    def refreshCommitPushAction(self):
        # Commit & Push goes straight through, so it needs a message (an empty one opens the dialog)
        self.commitPushAction.setEnabled(self.commitAction.isEnabled() and bool(self.commitMessage()))

    def refreshCommitSubjectCounter(self):
        length = len(self.commitSubjectEditor.text())
        counter = self.commitSubjectCounter
        counter.setText(f"{length}/{SUBJECT_SOFT_LIMIT}")
        counter.setVisible(length > 0)
        setStyleProperty(counter, "state", "long" if length > SUBJECT_SOFT_LIMIT else "")

    def refreshCommitOptionsButton(self):
        onNames = [stripAccelerators(action.text())
                   for action in (self.commitSignoffAction, self.commitNoVerifyAction) if action.isChecked()]
        tip = _("More commit options")
        if onNames:
            tip += "\n" + _("On: {0}", ", ".join(onNames))
        self.commitOptionsButton.setBadge(bool(onNames))
        self.commitOptionsButton.setToolTip(tip)
        self.commitOptionsButton.setAccessibleDescription(tip)

    def fillRecentSummariesMenu(self):
        menu = self.commitRecentButton.menu()
        menu.clear()
        summaries = recentCommitSummaries(self.repoModel.repo, settings.prefs.recentCommitMessages)
        for summary in summaries:
            action = menu.addAction(escamp(summary))
            action.triggered.connect(lambda _checked=False, s=summary: self.commitSubjectEditor.setText(s))
        if not summaries:
            menu.addAction(_("No recent messages")).setEnabled(False)

    def fillCommitAiMenu(self):
        menu = self.commitAiButton.menu()
        menu.clear()

        language = settings.history.aiLanguage
        languages = AI_LANGUAGES if not language or language in AI_LANGUAGES else [language, *AI_LANGUAGES]

        def setLanguage(value):
            settings.history.aiLanguage = value
            settings.history.setDirty()
            self.refreshCommitAiButton()

        def setDetail(value):
            settings.history.aiCommitDetail = value
            settings.history.setDirty()
            self.refreshCommitAiButton()

        ActionDef.addToQMenu(
            menu,
            ActionDef(_("AI message language"), kind=ActionDef.Kind.Section),
            *(ActionDef(name, lambda v=name: setLanguage(v), radioGroup="language",
                        checkState=1 if name == language else -1)
              for name in languages),
            ActionDef(_("AI message detail"), kind=ActionDef.Kind.Section),
            *(ActionDef(caption, lambda v=value: setDetail(v), radioGroup="detail",
                        checkState=1 if value == self.commitAiDetail() else -1)
              for value, caption in self.commitAiDetailNames().items()),
        )

    @staticmethod
    def commitAiDetailNames() -> dict[str, str]:
        return {"concise": _("Concise"), "detailed": _("Detailed"), "deep": _("Deep")}

    def commitAiDetail(self) -> str:
        detail = settings.history.aiCommitDetail
        return detail if detail in self.commitAiDetailNames() else "deep"

    def resetCompletedInlineCommit(self):
        if not self.inlineCommitPending or not self.stagedFiles.isEmpty():
            return
        self.inlineCommitPending = False
        self.setCommitMessage("")
        self.commitSignoffAction.setChecked(False)
        self.commitNoVerifyAction.setChecked(False)
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
        # While it writes, the button stays enabled to stop it
        self.commitAiButton.setEnabled(hasProvider and (hasStagedChanges or busy))
        self.commitAiSpinner.setVisible(busy)
        if busy:
            tip = _("Generating a commit message… Click to stop.")
        elif not hasProvider:
            tip = _("Install and configure Codex CLI or Claude Code to generate a commit message.")
        elif not hasStagedChanges:
            tip = _("Stage files to generate a commit message with AI.")
        else:
            provider = settings.history.aiProvider
            if provider not in self.commitAiProviders:
                provider = next(iter(self.commitAiProviders))
            tip = _("Generate a commit message from staged changes with {0}.", provider.capitalize())
            detail = self.commitAiDetailNames()[self.commitAiDetail()]
            tip += "\n" + f"{settings.history.aiLanguage} · {detail}"
        self.commitAiButton.setToolTip(tip)

    def onCommitAiButtonClicked(self):
        if self.commitAiProcess is not None:
            self.stopCommitAi()
        else:
            self.generateCommitMessage()

    def stopCommitAi(self):
        process = self.commitAiProcess
        if process is None:
            return
        self.commitAiProcess = None
        # Stopped on purpose: its end is no error to report
        process.finished.disconnect(self._commitAiFinished)
        process.errorOccurred.disconnect(self._commitAiProcessError)
        process.finished.connect(process.deleteLater)
        process.kill()
        self.commitSubjectEditor.setPlaceholderText(_("Commit subject"))
        self.refreshCommitAiButton()

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
        self.commitSubjectEditor.setPlaceholderText(_("Writing a message with {0}…", provider.capitalize()))
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
            language = settings.history.aiLanguage or "the user's language"
            detail = self.commitAiDetail()
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
        self.setCommitMessage(message)
        self.commitSubjectEditor.setFocus()
        self.commitSubjectEditor.setPlaceholderText(_("Commit subject"))
        self.refreshCommitAiButton()

    def _finishCommitAiWithError(self, message):
        if self.commitAiProcess:
            self.commitAiProcess.deleteLater()
            self.commitAiProcess = None
        self.commitSubjectEditor.setPlaceholderText(_("Commit subject"))
        self.refreshCommitAiButton()
        showWarning(self, _("AI commit message"), message)

    def _makeCommittedFilesContainer(self, repoModel):
        committedFiles = CommittedFiles(repoModel, self)
        fileViewButton = self._makeFileViewButton()
        header = FileListTitle(" ")
        header.setObjectName("committedHeader")
        header.setProperty("class", "panelTitle")
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setEnabled(False)

        headerBar = FileListHeader(self, header, [fileViewButton])
        headerBar.setNeutralIcon(fileViewButton, "view-list-tree")
        self.fileListHeaders.append(headerBar)

        container = QWidget(self)
        layout = QGridLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        layout.addWidget(headerBar,                 0, 0)
        layout.addWidget(committedFiles.searchBar,  1, 0)
        layout.addItem(self._makeFileListGap(),     2, 0)
        layout.addWidget(committedFiles,            3, 0)

        self.committedFiles = committedFiles
        self.committedHeader = header
        self.committedFileViewButton = fileViewButton
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
        diff.documentRecolored.connect(sideBySideDiff.recolor)

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
        # Not "Split_BottomCommitForm" any more: heights saved for the old,
        # taller form would dwarf the commit area it has become.
        bottomCommitSplitter.setObjectName("Split_CommitArea")
        bottomCommitSplitter.setChildrenCollapsible(False)
        bottomCommitSplitter.addWidget(stackContainer)
        bottomCommitSplitter.addWidget(bottomCommitFormHost)
        bottomCommitSplitter.setStretchFactor(0, 1)
        bottomCommitSplitter.setStretchFactor(1, 0)
        setDefaultSplitterSizes(bottomCommitSplitter, [500, 220])

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

        # Tab goes from pane to pane, past the file headers: the file lists do
        # their buttons' work from the keyboard (Return, Delete). The diff's
        # options have no such way in, so Tab stops on them after the diff (on
        # macOS, with Full Keyboard Access on). A click still leaves the focus
        # where it was.
        for button in self.diffButtons.buttons:
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        for button in self.stageButton, self.unstageButton, self.discardButton:
            button.setEnabled(False)

        GFApplication.instance().prefsChanged.connect(self.refreshTheme)
        GFApplication.instance().restyle.connect(self.refreshTheme)

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

        self.refreshTheme()

    def refreshTheme(self):
        """Neutral gives the file lists' headers Fork's shape (see FileListHeader)."""
        theme = activeTheme()
        for header in self.fileListHeaders:
            header.applyTheme(theme)
        # Neutral's headers draw the line under them themselves
        neutral = theme is not None and theme.variant == ThemeVariant.Neutral
        for gap in self.fileListGaps:
            gap.changeSize(1, 0 if neutral else 1)
        for header in self.fileListHeaders:
            header.parentWidget().layout().invalidate()

        # Neutral's commit tabs are a segmented control: the track stops at
        # the last tab, with room around it. Elsewhere they span the pane.
        self.commitTabRow.setContentsMargins(QMargins(8, 4, 8, 4) if neutral else QMargins())
        self.commitTabFiller.changeSize(
            0, 0,
            QSizePolicy.Policy.Expanding if neutral else QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Minimum)
        self.commitTabRow.setStretch(0, 0 if neutral else 1)
        self.commitTabRow.invalidate()

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
        self.commitTabBar.setVisible(True)
        self.hideCommitPatch()

    def hideCommitPatch(self):
        """Back to just the commit's story, until a file is picked again."""
        self.commitPatchStack.setVisible(False)
        # The patch we were mirroring is the Changes tab's own document: give
        # it back rather than clear it, which would empty it over there too.
        self.commitPatchView.dropDocument(heir=self.diffView)
        self.commitTabFollowsFile = False

    def followFileInCommitTab(self):
        """A file was picked in the Commit tab: from now on its pane keeps up with the locator."""
        self.commitTabFollowsFile = True

    def mirrorPatchInCommitTab(self, repo, delta, locator: NavLocator, document):
        """
        Feed the Commit tab's patch pane the file the user just went to, so
        the three tabs stay on one file without loading its diff twice. Only
        once a file has been picked there: a commit opens on its story.
        """
        if not self.commitTabFollowsFile:
            return
        if delta is None or document is None or locator.context != NavContext.COMMITTED:
            return
        self.showCommitPatch(repo, delta, locator, document)

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
        self.commitTabFollowsFile = True

        # The patch pane just took half the room; once the layout settles,
        # bring the file list up so the next file is still one click away
        QTimer.singleShot(0, self.commitDetailView.scrollToFiles)

    def hideCommitDetail(self):
        """No commit in sight (the working directory, say): no tabs either."""
        self.commitDetailView.clear()
        self.commitTabBar.setVisible(False)
        self.hideCommitPatch()
        self.showChangesTab()

    def showChangesTab(self):
        self.commitTabs.setCurrentIndex(DiffArea.ChangesTab)
        self.setCommitTabPage(DiffArea.ChangesTab)

    def setCommitTabPage(self, index: int):
        """
        Changes and File Tree are one page with two faces: the commit's files
        as a flat list, or under their folders. Which face a tab wears is the
        tab's own business, so the preference that the working directory's
        lists follow stays where the user put it.
        """
        self.pageStack.setCurrentIndex(min(index, DiffArea.ChangesTab))
        tree = index == DiffArea.FileTreeTab
        self.committedFiles.setTreeModeOverride(True if tree else None)
        # The tab already says it's a tree: nothing left for the switch to say
        self.committedFileViewButton.setVisible(not tree)

    # -------------------------------------------------------------------------
    # Clear

    def clearDocument(self, locator: NavLocator):
        # Enter empty special page
        self.specialDiffView.clear()
        self.setDiffStackPage("special")

        # Might as well free up any memory taken by DiffView document - unless
        # the Commit tab's pane is still showing it, in which case let go of it
        # without emptying it
        self.diffView.dropDocument()

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
        self.refreshBottomCommitFormVisibility()

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
