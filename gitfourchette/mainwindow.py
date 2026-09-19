# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import copy
import dataclasses
import gc
import logging
import os
import re
from collections.abc import Sequence, Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal

from gitfourchette import settings
from gitfourchette import tasks
from gitfourchette.application import GFApplication
from gitfourchette.codeview.codeview import CodeView
from gitfourchette.dropzone import DropAction, DropZone
from gitfourchette.exttools.toolprocess import ToolProcess, setUpToolCommand
from gitfourchette.exttools.usercommand import UserCommand
from gitfourchette.forms.aboutdialog import AboutDialog
from gitfourchette.forms.analysisview import AnalysisDialog
from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.maintoolbar import MainToolBar
from gitfourchette.forms.quicklaunch import (
    QUICKLAUNCH_ACTION_NAME, WORKS_WITHOUT_REPO, QuickLaunch, QuickLaunchEntry, QuickLaunchSection, menuBarEntries)
from gitfourchette.forms.repostub import RepoStub
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.forms.workspacedialog import WorkspaceDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.forms.welcomewidget import WelcomeWidget
from gitfourchette.forms.whatsnewdialog import WhatsNewDialog, versionCaption
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repowidget import RepoWidget
from gitfourchette.settings import PrefEffects, TabBarClick, getExternalEditorName
from gitfourchette.syntax import LexJobCache
from gitfourchette.tasks import TaskBook, RepoTaskRunner
from gitfourchette.tasks.newrepotasks import NewRepo
from gitfourchette.toolbox import *
from gitfourchette.trash import Trash

logger = logging.getLogger(__name__)

USERS_GUIDE_URL = "https://gitfourchette.org/guide"


WITHOUT_REPO = {WORKS_WITHOUT_REPO: True}
"""ActionDef properties for a command that works on Home, with no repo open."""


class NoRepoWidgetError(Exception):
    pass


class MainWindow(QMainWindow):
    welcomeStack: QStackedWidget
    welcomeWidget: WelcomeWidget
    tabs: QTabWidget2

    recentMenu: QMenu
    workspaceMenu: QMenu
    showStatusBarAction: QAction
    showMenuBarAction: QAction

    def __init__(self) -> None:
        super().__init__()

        self.welcomeStack = QStackedWidget(self)
        self.setCentralWidget(self.welcomeStack)

        self.setObjectName("GFMainWindow")

        self.setWindowTitle(qAppName())

        initialSize = .75 * QApplication.primaryScreen().availableSize()
        self.resize(initialSize)

        self.tabs = QTabWidget2(self)
        self.tabs.currentWidgetChanged.connect(self.onTabCurrentWidgetChanged)
        self.tabs.tabCloseRequested.connect(self.closeTab)
        self.tabs.tabContextMenuRequested.connect(self.onTabContextMenu)
        self.tabs.tabMiddleClicked.connect(self.onTabMiddleClicked)
        self.tabs.tabDoubleClicked.connect(self.onTabDoubleClicked)

        self.welcomeWidget = WelcomeWidget(self)
        self.welcomeWidget.newRepo.connect(self.newRepo)
        self.welcomeWidget.openRepo.connect(self.openDialog)
        self.welcomeWidget.cloneRepo.connect(self.cloneDialog)
        self.welcomeWidget.openRepoPath.connect(lambda path: self.openRepo(path, exactMatch=True))

        self.welcomeStack.addWidget(self.welcomeWidget)
        self.welcomeStack.addWidget(self.tabs)
        self.welcomeStack.setCurrentWidget(self.welcomeWidget)

        self.globalMenuBar = QMenuBar(self)
        self.globalMenuBar.setObjectName("GFMainMenuBar")
        self.setMenuBar(self.globalMenuBar)
        self.autoHideMenuBar = AutoHideMenuBar(self.globalMenuBar)

        self.statusBar2 = QStatusBar2(self)
        self.setStatusBar(self.statusBar2)
        self.buildVersionCorner()

        self.mainToolBar = MainToolBar(self)
        self.addToolBar(self.mainToolBar)
        self.mainToolBar.openPrefs.connect(GFApplication.instance().openPrefsDialog)
        self.mainToolBar.setDarkThemeRequested.connect(self.onSetDarkTheme)
        self.mainToolBar.setCompactRequested.connect(
            lambda compact: GFApplication.applyPrefs(compactUi=compact))
        self.refreshThemeButton()

        self.repoMenu2 = QMenu(self)
        self.repoMenu2.setObjectName("ToolBarRepoMenu")
        self.repoMenu2.aboutToShow.connect(self.fillRepoButtonMenu)
        self.mainToolBar.repoAction.setMenu(self.repoMenu2)

        self.openInMenu = QMenu(self)
        self.openInMenu.setObjectName("OpenInMenu")
        self.openInMenu.setToolTipsVisible(True)
        self.openInMenu.aboutToShow.connect(self.fillOpenInMenu)
        self.mainToolBar.openInAction.setMenu(self.openInMenu)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)

        self.recentMenu = QMenu(self)
        self.recentMenu.setObjectName("RecentMenu")
        self.recentMenu.setToolTipsVisible(True)

        self.workspaceMenu = QMenu(self)
        self.workspaceMenu.setObjectName("WorkspaceMenu")
        self.workspaceMenu.setToolTipsVisible(True)
        self.workspaceMenu.aboutToShow.connect(self.fillWorkspaceMenu)
        self._switchingWorkspace = False
        self.fillRecentMenu()
        self.fillWorkspaceMenu()

        self.welcomeWidget.ui.recentReposButton.setMenu(self.recentMenu)
        self.mainToolBar.workspaceAction.setMenu(self.workspaceMenu)
        self.mainToolBar.openRepoAction.triggered.connect(self.openDialog)
        self.mainToolBar.cloneRepoAction.triggered.connect(lambda: self.cloneDialog())  # not triggered(checked) as the URL
        self.mainToolBar.newRepoAction.triggered.connect(self.newRepo)
        self.mainToolBar.quickLaunchAction.triggered.connect(self.openQuickLaunch)

        self.fillGlobalMenuBar()

        self.setAcceptDrops(True)

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

        self.dropZone = DropZone(self)
        self.dropZone.setVisible(False)

    # -------------------------------------------------------------------------
    # RepoTask

    @property
    def taskRunner(self) -> RepoTaskRunner:
        """
        Return the foreground RepoWidget's RepoTaskRunner.
        This provides compatibility for TaskInvocation's RepoTaskRunner lookup.
        May raise NoRepoWidgetError, aborting the lookup.
        """
        return self.currentRepoWidget().taskRunner

    # -------------------------------------------------------------------------
    # Event handlers

    def onMouseSideButtonPressed(self, forward: bool) -> None:
        if not self.isActiveWindow():
            return
        with suppress(NoRepoWidgetError):
            repoWidget = self.currentRepoWidget()
            if forward:
                repoWidget.navigateForward()
            else:
                repoWidget.navigateBack()

    def onFileDraggedToDockIcon(self, path: str) -> None:
        outcome = self.getDropOutcomeFromLocalFilePath(path)
        self.handleDrop(*outcome)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Alt and self.autoHideMenuBar.enabled:
            self.autoHideMenuBar.toggle()
        else:
            super().keyReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        try:
            action, data = self.getDropOutcomeFromMimeData(event.mimeData())
            if action == DropAction.Deny and not data:
                event.setAccepted(False)
                return
            self.dropZone.install(action, data)
            if action == DropAction.Deny:
                event.setDropAction(Qt.DropAction.IgnoreAction)  # 'nope' cursor on KDE
            else:
                event.acceptProposedAction()
        except Exception:  # pragma: no cover - Don't let this crash the application
            logger.exception("dragEnterEvent failed")
            event.setAccepted(False)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.dropZone.setVisible(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self.dropZone.setVisible(False)
        action, data = self.getDropOutcomeFromMimeData(event.mimeData())
        event.setAccepted(True)  # keep dragged item from coming back to cursor on macOS
        self.handleDrop(action, data)

    # -------------------------------------------------------------------------
    # Menu bar

    def fillGlobalMenuBar(self) -> None:
        menubar = self.globalMenuBar
        menuObjectNamePrefix = "MWMainMenu"

        # Delete old menu objects
        for m in menubar.findChildren(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if m.objectName().startswith(menuObjectNamePrefix):
                m.deleteLater()

        menubar.clear()

        # -------------------------------------------------------------
        # Set up root menus

        menuNames = {
            "File": _("&File"),
            "Edit": _("&Edit"),
            "View": _("&View"),
            "Analysis": _("&Data"),
            "Repo": _("&Repo"),
            "Commands": _("&Commands"),
            "Mount": _("&Mount"),
            "Help": _("&Help"),
        }

        rootMenus: dict[str, QMenu] = {}
        for key, name in menuNames.items():
            menu = menubar.addMenu(name)
            menu.setObjectName(f"{menuObjectNamePrefix}{key}")
            menu.setToolTipsVisible(True)
            rootMenus[key] = menu

        fileMenu, editMenu, viewMenu, analysisMenu, repoMenu, commandsMenu, mountMenu, helpMenu = iter(rootMenus.values())

        self.autoHideMenuBar.reconnectToMenus()

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            fileMenu,

            ActionDef(_("&New Repository…"), self.newRepo,
                      shortcuts=QKeySequence.StandardKey.New, icon="folder-new",
                      tip=_("Create an empty Git repo"), properties=WITHOUT_REPO),

            ActionDef(_("C&lone Repository…"), self.cloneDialog,
                      shortcuts="Ctrl+Shift+N", icon="folder-download",
                      tip=_("Download a Git repo and open it"), properties=WITHOUT_REPO),

            ActionDef.SEPARATOR,

            ActionDef(_("&Open Repository…"), self.openDialog,
                      shortcuts=QKeySequence.StandardKey.Open, icon="folder-open",
                      tip=_("Open a Git repo on your machine"), properties=WITHOUT_REPO),

            ActionDef(_("Open &Recent"),
                      icon="folder-open-recent",
                      tip=_("List of recently opened Git repos"),
                      submenu=self.recentMenu),

            ActionDef(_("&Workspace"),
                      icon="folder-open-recent",
                      tip=_("Named sets of repos you switch between"),
                      submenu=self.workspaceMenu),

            ActionDef.SEPARATOR,

            TaskBook.action(self, tasks.ApplyPatchFile),
            TaskBook.action(self, tasks.ApplyPatchFileReverse),

            ActionDef.SEPARATOR,

            ActionDef(_("&Settings…"), GFApplication.instance().openPrefsDialog,
                      shortcuts=QKeySequence.StandardKey.Preferences, icon="configure",
                      menuRole=QAction.MenuRole.PreferencesRole,
                      tip=_("Configure {app}", app=qAppName()), properties=WITHOUT_REPO),

            TaskBook.action(self, tasks.SetUpGitIdentity, taskArgs=('', False)
                            ).replace(menuRole=QAction.MenuRole.ApplicationSpecificRole),

            ActionDef.SEPARATOR,

            ActionDef(_("&Close Tab"), self.dispatchCloseCommand,
                      shortcuts=QKeySequence.StandardKey.Close, icon="document-close",
                      tip=_("Close current repository tab")),

            ActionDef(_("&Quit"), self.close,
                      shortcuts=QKeySequence.StandardKey.Quit, icon="application-exit",
                      tip=_("Quit {app}", app=qAppName()),
                      menuRole=QAction.MenuRole.QuitRole, properties=WITHOUT_REPO),
        )

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            editMenu,

            ActionDef(_("&Find…"), lambda: self.dispatchSearchCommand(),
                      shortcuts=GlobalShortcuts.find, icon="edit-find",
                      tip=_("Search for a piece of text in commit messages, the current diff, or the name of a file")),

            ActionDef(_("Find Next"), lambda: self.dispatchSearchCommand(SearchBar.Op.Next),
                      shortcuts=GlobalShortcuts.findNext,
                      tip=_("Find next occurrence")),

            ActionDef(_("Find Previous"), lambda: self.dispatchSearchCommand(SearchBar.Op.Previous),
                      shortcuts=GlobalShortcuts.findPrevious,
                      tip=_("Find previous occurrence")),
        )

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            analysisMenu,
            ActionDef(_("&Overview"), lambda: self.openAnalysis(AnalysisDialog.OVERVIEW_TAB)),
            ActionDef(_("Developer &KPI"), lambda: self.openAnalysis(AnalysisDialog.DEVELOPER_TAB)),
            ActionDef(_("Developer &Commits"), lambda: self.openAnalysis(AnalysisDialog.COMMITS_TAB)),
        )

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            repoMenu,
            *RepoWidget.contextMenuItemsByProxy(self, self.currentRepoWidget),
        )

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            viewMenu,
            ActionDef(_("&Quick Launch…"), self.openQuickLaunch,
                      shortcuts=GlobalShortcuts.quickLaunch, icon="edit-find",
                      objectName=QUICKLAUNCH_ACTION_NAME,
                      tip=_("Type a few letters of any command, repo or workspace, and press Enter")),
            ActionDef.SEPARATOR,
            self.mainToolBar.toggleViewAction(),
            ActionDef(englishTitleCase(_("Show status bar")), self.toggleStatusBar, checkState=-1,
                      objectName="ShowStatusBarAction", properties=WITHOUT_REPO),
            ActionDef(englishTitleCase(_("Show menu bar")), self.toggleMenuBar, checkState=-1,
                      objectName="ShowMenuBarAction", properties=WITHOUT_REPO),
            ActionDef.SEPARATOR,
            TaskBook.action(self, tasks.JumpToUncommittedChanges, accel="U"),
            TaskBook.action(self, tasks.JumpToHEAD, accel="H"),
            ActionDef.SEPARATOR,
            ActionDef(_("Focus on Sidebar"), self.focusSidebar, shortcuts="Alt+1"),
            ActionDef(_("Focus on Commit Log"), self.focusGraph, shortcuts="Alt+2"),
            ActionDef(_("Focus on File List"), self.focusFiles, shortcuts="Alt+3"),
            ActionDef(_("Focus on Code View"), self.focusDiff, shortcuts="Alt+4"),
            ActionDef.SEPARATOR,
            ActionDef(_("Blame File…"), self.blameFile, icon=TaskBook.icons[tasks.OpenBlame], shortcuts=TaskBook.shortcuts[tasks.OpenBlame]),
            ActionDef(_("Next File"), self.nextFile, shortcuts="Ctrl+]"),
            ActionDef(_("Previous File"), self.previousFile, shortcuts="Ctrl+["),
            ActionDef.SEPARATOR,
            ActionDef(_("&Next Tab"), self.nextTab, shortcuts="Ctrl+Shift+]" if MACOS else "Ctrl+Tab"),
            ActionDef(_("&Previous Tab"), self.previousTab, shortcuts="Ctrl+Shift+[" if MACOS else "Ctrl+Shift+Tab"),
            ActionDef.SEPARATOR,
            TaskBook.action(self, tasks.JumpBack),
            TaskBook.action(self, tasks.JumpForward),
            ActionDef("Dump Nav Log", lambda: logger.info(self.currentRepoWidget().navHistory.getTextLog()), objectName="DumpNavLogAction"),
            ActionDef.SEPARATOR,
            ActionDef(
                _("&Refresh"),
                lambda: self.currentRepoWidget().refreshRepo(),
                shortcuts=GlobalShortcuts.refresh,
                icon="SP_BrowserReload",
                tip=_("Check for changes in the repo (on the local filesystem only – will not fetch remotes)"),
            ),
            ActionDef(
                _("Reloa&d"),
                lambda: self.currentRepoWidget().replaceWithStub(),
                shortcuts="Ctrl+F5",
                tip=_("Reopen the repo from scratch"),
            ),
        )

        self.mainToolBar.toggleViewAction().setProperty(WORKS_WITHOUT_REPO, True)
        self.showStatusBarAction = viewMenu.findChild(QAction, "ShowStatusBarAction")
        self.showMenuBarAction = viewMenu.findChild(QAction, "ShowMenuBarAction")
        self.showMenuBarAction.setVisible(not MACOS)
        viewMenu.findChild(QAction, "DumpNavLogAction").setVisible(APP_DEBUG)

        # -------------------------------------------------------------

        self.parseUserCommands()
        if self.userCommands:
            commandActions = [
                ActionDef.SEPARATOR if command.isSeparator
                else ActionDef(
                    command.menuTitle(),
                    lambda c=command: self.currentRepoWidget().executeUserCommand(c),
                    tip=command.menuToolTip(),
                    shortcuts=command.shortcut
                )
                for command in self.userCommands
            ]

            ActionDef.addToQMenu(
                commandsMenu,
                *commandActions,
                ActionDef.SEPARATOR,
                ActionDef(_("Edit Commands…"), icon="document-edit",
                          callback=lambda: GFApplication.instance().openPrefsDialog("commands"),
                          properties=WITHOUT_REPO),
            )

            # Don't share commandsMenu with the toolbar button: commandsMenu.aboutToShow
            # would fire via that button's popup routine, causing AutoHideMenuBar to
            # show the entire menu bar.
            # Do share the actions themselves so that the keyboard shortcuts work.
            self.mainToolBar.setUserCommandActions(commandsMenu.actions())
        else:
            commandsMenu.deleteLater()
            self.mainToolBar.setUserCommandActions([])

        # -------------------------------------------------------------

        mountItems = GFApplication.instance().mountManager.makeMenu(self)
        if mountItems:
            # Mounted commits outlive the tab they came from
            mountItems = [item if item is ActionDef.SEPARATOR else item.replace(properties=WITHOUT_REPO)
                          for item in mountItems]
            ActionDef.addToQMenu(mountMenu, *mountItems)
        else:
            mountMenu.deleteLater()

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            helpMenu,

            ActionDef(
                _("&About {0}", qAppName()),
                lambda: AboutDialog.popUp(self),
                icon="gitfourchette",
                menuRole=QAction.MenuRole.AboutRole, properties=WITHOUT_REPO),

            ActionDef(
                _("{0} User’s Guide", qAppName()),
                lambda: QDesktopServices.openUrl(QUrl(USERS_GUIDE_URL)),
                icon="help-contents", properties=WITHOUT_REPO),

            ActionDef(
                _("What’s New…"),
                self.openWhatsNew,
                tip=_("This year’s releases, what they brought, and who made them"),
                properties=WITHOUT_REPO),

            ActionDef.SEPARATOR,

            ActionDef(
                _("Open Trash…"),
                self.openRescueFolder,
                icon="SP_TrashIcon",
                tip=_("Explore changes that you may have discarded by mistake"), properties=WITHOUT_REPO),

            ActionDef(
                _("Empty Trash…"),
                self.clearRescueFolder,
                tip=_("Delete all discarded changes from the trash folder"), properties=WITHOUT_REPO),
        )

    def quickLaunchSections(self) -> list[QuickLaunchSection]:
        """What the Quick Launch palette offers, section by section."""
        history = settings.history

        # On Home there's no repo for Push, Blame or Find to act on: offer only
        # what works there, plus what the Home page itself can do
        try:
            self.currentRepoWidget()
            onHome = False
        except NoRepoWidgetError:
            onHome = True
        commands = menuBarEntries(self.globalMenuBar, skip=[self.recentMenu, self.workspaceMenu],
                                  withoutRepo=onHome)
        if onHome:
            welcome = self.welcomeWidget
            commands += [
                QuickLaunchEntry(_("Fetch All Repositories"), welcome.fetchAllButton.click, icon="git-fetch",
                                 keywords=_("home")),
                QuickLaunchEntry(_("Rescan Repositories"), lambda: welcome.rescan(force=True),
                                 icon="SP_BrowserReload", keywords=_("home search folders")),
            ]

        # Light or dark, from the keyboard - the same switch as the toolbar's Theme button
        from gitfourchette.themes import isDarkStyle
        dark = isDarkStyle(settings.prefs.qtStyle)
        commands += [
            QuickLaunchEntry(_("Dark Theme"), lambda: self.onSetDarkTheme(True), icon="theme-dark",
                             detail=_("current") if dark else "", keywords=_("appearance mode")),
            QuickLaunchEntry(_("Light Theme"), lambda: self.onSetDarkTheme(False), icon="theme-light",
                             detail=_("current") if not dark else "", keywords=_("appearance mode")),
        ]
        commands.sort(key=lambda e: e.title.casefold())

        current = history.currentWorkspace
        home = QuickLaunchEntry(
            _("Home"), lambda: self.switchToWorkspace(""), icon="git-home",
            detail=_("current") if not current else "", keywords=_("workspace"))
        named = []
        for name in history.workspaceNames():
            numRepos = len((history.getWorkspace(name) or {}).get("repos", []))
            detail = _("current") if name == current else _n("{n} repo", "{n} repos", numRepos)
            named.append(QuickLaunchEntry(
                name, lambda n=name: self.switchToWorkspace(n), detail=detail, icon="folder-recent",
                keywords=_("workspace")))
        switch = QuickLaunchEntry(
            _("Switch Workspace…"), lambda: None, icon="folder-recent",
            detail=_n("{n} workspace", "{n} workspaces", len(named)),
            drillDown=QuickLaunchSection(_("Switch Workspace"), [home, *named]))
        # Home and Switch Workspace stay one keystroke away; the named workspaces
        # only show up once you type (Switch Workspace lists them all)
        workspaces = [home, switch, *(dataclasses.replace(e, searchOnly=True) for e in named)]

        repos = []
        for path in history.getRecentRepoPaths(settings.prefs.maxRecentRepos):
            nickname = history.getRepoNickname(path)
            repos.append(QuickLaunchEntry(
                nickname, lambda p=path: self.openRepo(p, exactMatch=True),
                detail=compactPath(path), icon="git-folder", keywords=path))

        return [
            QuickLaunchSection(_("Recent Repositories"), repos),
            QuickLaunchSection(_("Workspaces"), workspaces),
            QuickLaunchSection(_("Commands"), commands),
        ]

    def buildVersionCorner(self) -> None:
        """Bottom-right of the status bar: which build this is, and what's new in it."""
        self.versionLabel = QLabel(versionCaption(), self.statusBar2)
        self.versionLabel.setObjectName("StatusBarVersion")
        self.versionLabel.setEnabled(False)  # dimmed, like a footnote
        tweakWidgetFont(self.versionLabel, 90)

        self.whatsNewButton = QToolButton(self.statusBar2)
        self.whatsNewButton.setObjectName("StatusBarWhatsNew")
        self.whatsNewButton.setText(_("What’s New"))
        self.whatsNewButton.setToolTip(_("This year’s releases, what they brought, and who made them"))
        self.whatsNewButton.setAutoRaise(True)
        self.whatsNewButton.clicked.connect(self.openWhatsNew)

        self.statusBar2.addPermanentWidget(self.versionLabel)
        self.statusBar2.addPermanentWidget(self.whatsNewButton)

    def openWhatsNew(self) -> WhatsNewDialog:
        dialog = WhatsNewDialog(self)
        dialog.show()
        return dialog

    def openQuickLaunch(self) -> QuickLaunch:
        palette = QuickLaunch(self, self.quickLaunchSections())
        palette.popUp()
        return palette

    def fillRecentMenu(self) -> None:
        actions = []
        for path in settings.history.getRecentRepoPaths(settings.prefs.maxRecentRepos):
            caption = compactPath(path)
            nickname = settings.history.getRepoNickname(path, strict=True)
            if nickname:
                caption += f" ({tquo(nickname)})"

            caption = elide(caption, ems=60)  # don't let menus get absurdly wide

            openAction = ActionDef(
                escamp(caption),
                lambda p=path: self.openRepo(p, exactMatch=True),
                tip=path)
            actions.append(openAction)

        self.recentMenu.clear()
        ActionDef.addToQMenu(
            self.recentMenu,
            *actions,
            ActionDef.SEPARATOR,
            ActionDef(
                _("Clear List"), self.onClearRecentMenu, "edit-clear-history",
                tip=_("Clear the list of recently opened repositories"),
            ))

    def onSetDarkTheme(self, dark: bool) -> None:
        from gitfourchette.themes import withThemeMode
        GFApplication.applyPrefs(qtStyle=withThemeMode(settings.prefs.qtStyle, dark))
        self.refreshThemeButton()


    def refreshThemeButton(self) -> None:
        from gitfourchette.themes import isDarkStyle
        self.mainToolBar.setDarkTheme(isDarkStyle(settings.prefs.qtStyle))

    def fillRepoButtonMenu(self) -> None:
        """Switching branch is what you'd want next after reading where you are."""
        try:
            rw = self.currentRepoWidget()
        except NoRepoWidgetError:  # pragma: no cover - the button hides without a repo
            return

        current = rw.repoModel.homeBranch
        actions = []
        for name in rw.repo.branches.local:
            actions.append(ActionDef(
                escamp(elide(name, ems=40)),
                lambda n=name: tasks.SwitchBranch.invoke(rw, n),
                checkState=1 if name == current else -1,
                radioGroup="branch"))
        if actions:
            actions.append(ActionDef.SEPARATOR)
        actions.append(TaskBook.action(self, tasks.NewBranchFromHead))

        self.repoMenu2.clear()
        ActionDef.addToQMenu(self.repoMenu2, *actions)
        # This menu is created on demand from the toolbar. A shortcut owned by
        # the transient QMenu can otherwise be swallowed while the menu grabs
        # the keyboard, even though Ctrl+B is displayed beside the action.
        newBranchAction = self.repoMenu2.actions()[-1]
        newBranchAction.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

    def refreshRepoButton(self) -> None:
        try:
            # Raises for an unloaded stub too, which has read nothing to report
            rw = self.currentRepoWidget()
        except NoRepoWidgetError:
            self.mainToolBar.setRepoSummary("", "", False)
            return
        self.mainToolBar.setRepoSummary(
            settings.history.peekRepoNickname(rw.workdir),
            rw.repoModel.homeBranch,
            rw.repoModel.numUncommittedChanges > 0)

    def fillOpenInMenu(self) -> None:
        """Where to take the repo that's in front of you."""
        try:
            rw = self.currentRepoWidget()
        except NoRepoWidgetError:  # pragma: no cover - the button hides without a repo
            return

        # The Repo menu already knows how to do this; don't invent a second copy
        actions = self.repolessActions(rw.workdir)[:4]
        if self.mainToolBar.userCommandActions:
            actions += [ActionDef.SEPARATOR, *self.mainToolBar.userCommandActions]

        self.openInMenu.clear()
        ActionDef.addToQMenu(self.openInMenu, *actions)

    def fillWorkspaceMenu(self) -> None:
        if self._switchingWorkspace:
            # Rebuilding now would delete the QAction whose handler is running
            return
        history = settings.history
        current = history.currentWorkspace
        names = history.workspaceNames()

        actions = [ActionDef(
            _("&Home"), lambda: self.switchToWorkspace(""),
            checkState=1 if not current else -1,
            radioGroup="workspace",
            icon="git-home",
            tip=_("Every repo on this machine, and nothing open"))]
        if names:
            actions.append(ActionDef.SEPARATOR)

        for name in names:
            workspace = history.getWorkspace(name)
            numRepos = len(workspace.get("repos", []))
            actions.append(ActionDef(
                escamp(elide(name, ems=40)),
                lambda n=name: self.switchToWorkspace(n),
                checkState=1 if name == current else -1,
                radioGroup="workspace",
                tip=_n("{n} repo", "{n} repos", numRepos)))

        if actions:
            actions.append(ActionDef.SEPARATOR)

        actions.append(ActionDef(
            _("&New Workspace…"), self.newWorkspace,
            icon="document-save-as",
            tip=_("Pick the repos that belong together and name the set")))

        if current:
            actions += [
                ActionDef(_("&Edit {0}…", tquo(current)), self.editCurrentWorkspace,
                          icon="document-edit",
                          tip=_("Rename it, or change which repos are in it")),
                ActionDef(_("&Delete {0}…", tquo(current)), self.deleteCurrentWorkspace,
                          icon="SP_TrashIcon"),
            ]

        self.workspaceMenu.clear()
        ActionDef.addToQMenu(self.workspaceMenu, *actions)
        self.mainToolBar.setWorkspaceName(current if history.getWorkspace(current) else "")


    def rememberCurrentWorkspace(self) -> None:
        """Keep the active workspace in sync with the tabs that are open."""
        name = settings.history.currentWorkspace
        if not name or settings.history.getWorkspace(name) is None:
            return
        paths = [widget.workdir for widget in self.tabs.widgets()]
        if not paths:
            # Closing every tab isn't "this workspace is empty now" - it's a
            # transient state on the way to opening another one.
            return
        settings.history.setWorkspace(name, paths, self.tabs.currentIndex())

    def switchToWorkspace(self, name: str) -> None:
        """Open the repos of `name`, and only those. An empty name means Home."""
        history = settings.history
        workspace = history.getWorkspace(name) if name else None
        if name and workspace is None:  # pragma: no cover - menu is rebuilt from the same list
            return

        if name and name == history.currentWorkspace:
            return
        if not name and self.tabs.count() == 0:
            # Already on Home with nothing open: there's nothing to do.
            # Note that an empty currentWorkspace is also the ad-hoc state -
            # repos open, no workspace saved - and Home must still clear that.
            return

        # Don't lose the curation of the workspace we're leaving
        self.rememberCurrentWorkspace()

        self._switchingWorkspace = True
        try:
            self.closeAllTabs()
            history.setCurrentWorkspace(name)

            if workspace is not None:
                session = settings.Session()
                session.splitterSizes = copy.deepcopy(RepoWidget.sharedSplitterSizes)
                session.tabs = list(workspace.get("repos", []))
                session.activeTabIndex = workspace.get("activeIndex", 0)
                self.restoreSession(session)
        finally:
            self._switchingWorkspace = False

        history.write()
        self.fillWorkspaceMenu()

    def workspaceCandidates(self, preferredOrder: list[str]) -> list[tuple[str, str]]:
        """
        Every repo we could put in a workspace, with `preferredOrder` first.

        That's more than the recent list: a repo found on disk but never opened
        still belongs to a workspace you're assembling.
        """
        history = settings.history
        seen = []

        def remember(path: str):
            path = os.path.normpath(path)
            if path not in seen:
                seen.append(path)

        for path in preferredOrder:
            remember(path)
        for path in history.getRecentRepoPaths(settings.prefs.maxRecentRepos):
            remember(path)
        for entry in sorted(history.scannedRepos, key=lambda e: e.get("path", "").casefold()):
            remember(entry.get("path", ""))

        candidates = []
        for path in seen:
            if not path:  # pragma: no cover - a cache entry without a path
                continue
            name = history.peekRepoNickname(path)
            compact = compactPath(path)
            if compact != name:
                name = f"{name}  —  {elide(compact, ems=50)}"
            candidates.append((path, name))
        return candidates

    def openTabPaths(self) -> list[str]:
        return [os.path.normpath(widget.workdir) for widget in self.tabs.widgets()]

    def newWorkspace(self) -> None:
        # Nothing is ticked to begin with: a new workspace is a deliberate
        # choice, not "whatever happens to be open right now".
        dlg = WorkspaceDialog(
            _("New workspace"), "",
            self.workspaceCandidates(self.openTabPaths()), [],
            settings.history.workspaceNames(), parent=self)
        dlg.acceptButton.setText(_("Create"))
        dlg.accepted.connect(lambda: self.onWorkspaceEdited("", dlg.workspaceName, dlg.checkedPaths()))
        dlg.show()

    def editCurrentWorkspace(self) -> None:
        history = settings.history
        oldName = history.currentWorkspace
        workspace = history.getWorkspace(oldName)
        if workspace is None:  # pragma: no cover - action only exists when one is current
            return
        repos = list(workspace.get("repos", []))

        dlg = WorkspaceDialog(
            _("Edit workspace"), oldName,
            self.workspaceCandidates(repos + self.openTabPaths()), repos,
            [n for n in history.workspaceNames() if n != oldName], parent=self)
        dlg.acceptButton.setText(_("Save"))
        dlg.accepted.connect(lambda: self.onWorkspaceEdited(oldName, dlg.workspaceName, dlg.checkedPaths()))
        dlg.show()

    def onWorkspaceEdited(self, oldName: str, newName: str, paths: list[str]) -> None:
        history = settings.history
        if oldName and oldName != newName:
            history.renameWorkspace(oldName, newName)

        previous = history.getWorkspace(newName)
        activeIndex = previous.get("activeIndex", 0) if previous else self.tabs.currentIndex()
        history.setWorkspace(newName, paths, activeIndex)
        history.setCurrentWorkspace(newName)
        history.write()
        self.fillWorkspaceMenu()

        # A workspace is what you see, so make the tabs match what was picked
        self.openWorkspaceTabs(newName)

    def openWorkspaceTabs(self, name: str) -> None:
        workspace = settings.history.getWorkspace(name)
        if workspace is None:  # pragma: no cover - called right after writing it
            return
        self._switchingWorkspace = True
        try:
            self.closeAllTabs()
            session = settings.Session()
            session.splitterSizes = copy.deepcopy(RepoWidget.sharedSplitterSizes)
            session.tabs = list(workspace.get("repos", []))
            session.activeTabIndex = workspace.get("activeIndex", 0)
            self.restoreSession(session)
        finally:
            self._switchingWorkspace = False
        self.fillWorkspaceMenu()

    def deleteCurrentWorkspace(self) -> None:
        history = settings.history
        name = history.currentWorkspace
        if not name:  # pragma: no cover - action only exists when one is current
            return

        qmb = asyncMessageBox(
            self, "question", _("Delete workspace"),
            paragraphs(_("Really delete workspace {0}?", bquo(name)),
                       _("The repos stay where they are; only the grouping is forgotten.")),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        qmb.button(QMessageBox.StandardButton.Ok).setText(_("Delete"))
        qmb.accepted.connect(lambda: self.onWorkspaceDeleteConfirmed(name))
        qmb.show()

    def onWorkspaceDeleteConfirmed(self, name: str) -> None:
        settings.history.deleteWorkspace(name)
        settings.history.write()
        self.fillWorkspaceMenu()

    def onClearRecentMenu(self) -> None:
        settings.history.clearRepoHistory()
        settings.history.write()
        self.fillRecentMenu()

    def showMenuBarHiddenWarning(self):
        return showInformation(
            self, _("Menu bar hidden"),
            _("The menu bar is now hidden. Press the Alt key to toggle it."))

    # -------------------------------------------------------------------------
    # Tabs

    def currentRepoWidget(self) -> RepoWidget:
        rw = self.tabs.currentWidget()
        if not isinstance(rw, RepoWidget):  # it might be a RepoStub
            raise NoRepoWidgetError()
        return rw

    def openAnalysis(self, tabIndex: int = 0) -> None:
        """Open the local repository analysis dashboard for the active tab."""
        try:
            repoWidget = self.currentRepoWidget()
        except NoRepoWidgetError:
            self.statusBar2.showMessage(_("Open a repository before running Analysis."))
            return

        dialog = getattr(self, "analysisDialog", None)
        if dialog is not None:
            # WA_DeleteOnClose can leave a Python wrapper behind after Qt has
            # destroyed the dialog. Clear the reference before closing so a
            # second Analysis invocation never calls into a dead C++ object.
            self.analysisDialog = None
            try:
                dialog.close()
            except RuntimeError:
                pass

        def showCommit(oid: Oid):
            # The dashboard stays open next to the repo, so you can go through
            # a developer's commits one after the other
            repoWidget.jump(NavLocator.inCommit(oid))
            self.raise_()
            self.activateWindow()

        dialog = AnalysisDialog(self, repoWidget.workdir, showCommit=showCommit)
        dialog.tabs.setCurrentIndex(max(0, min(tabIndex, dialog.tabs.count() - 1)))
        self.analysisDialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def tabWidgetForWorkdirPath(self, workdir: str) -> RepoWidget | RepoStub | None:
        widget: RepoWidget | RepoStub
        for widget in self.tabs.widgets():
            assert isinstance(widget, RepoWidget | RepoStub)
            with suppress(FileNotFoundError):  # may be raised if workdir cannot be accessed
                if os.path.samefile(workdir, widget.workdir):
                    return widget
        return None

    def setWindowTitle(self, title: str) -> None:
        if APP_DEBUG:
            chain = ["DEBUG", str(os.getpid()), QT_BINDING]
            if APP_TESTMODE:
                chain.append("TESTMODE")
            if APP_NOTHREADS:
                chain.append("NOTHREADS")
            title = f"{title} ({' '.join(chain)})"

        super().setWindowTitle(title)

    def onTabCurrentWidgetChanged(self):
        self.mainToolBar.updateNavButtons()  # Kill back/forward arrows
        self.statusBar2.clearMessage()
        self.fillWorkspaceMenu()

        widget = self.tabs.currentWidget()

        # Switch to welcome widget if zero tabs
        if not widget:
            self.mainToolBar.setRepoScopedActionsVisible(False)
            self.welcomeStack.setCurrentWidget(self.welcomeWidget)
            self.setWindowTitle(APP_DISPLAY_NAME)
            return

        self.mainToolBar.setRepoScopedActionsVisible(True)
        self.welcomeStack.setCurrentWidget(self.tabs)  # Exit welcome widget
        self.setWindowTitle(widget.windowTitle())

        # If it's a RepoStub, load it if needed
        if not isinstance(widget, RepoWidget):
            assert isinstance(widget, RepoStub)
            if not widget.isPriming() and widget.willAutoLoad():
                widget.loadNow()
            return

        # We know it's a RepoWidget beyond this point
        assert isinstance(widget, RepoWidget)

        # Update back/forward buttons
        self.onRepoHistoryChanged(widget)

        widget.restoreSplitterStates()

        # Refresh the repo
        widget.refreshRepo()

    def generateTabContextMenu(self, i: int) -> QMenu:
        assert 0 <= i < self.tabs.count()

        widget: RepoWidget | RepoStub = self.tabs.widget(i)
        menu = QMenu(self)
        menu.setObjectName("MWRepoTabContextMenu")

        anyOtherLoadedTabs = any(tab is not widget and isinstance(tab, RepoWidget)
                                 for tab in self.tabs.widgets())

        ActionDef.addToQMenu(
            menu,
            ActionDef(_("Close Tab"), lambda: self.closeTab(i), shortcuts=QKeySequence.StandardKey.Close),
            ActionDef(_("Close Other Tabs"), lambda: self.closeOtherTabs(i), enabled=self.tabs.count() > 1),
            ActionDef(_("Unload Other Tabs"), lambda: self.unloadOtherTabs(i), enabled=self.tabs.count() > 1 and anyOtherLoadedTabs),
            ActionDef.SEPARATOR,
            *self.repolessActions(widget.workdir),
            ActionDef.SEPARATOR,
            ActionDef(_("Configure Tabs…"), lambda: GFApplication.instance().openPrefsDialog("tabCloseButton")),
        )

        return menu

    def onTabContextMenu(self, globalPoint: QPoint, i: int) -> None:
        if i < 0:  # Right mouse button released outside tabs
            return

        menu = self.generateTabContextMenu(i)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(globalPoint)

    def onTabMiddleClicked(self, i: int) -> None:
        self.onTabSpecialClick(i, "middle")

    def onTabDoubleClicked(self, i: int) -> None:
        self.onTabSpecialClick(i, "double")

    def onTabSpecialClick(self, i: int, click: Literal["middle", "double"]) -> None:
        if i < 0:
            return

        if click == "double":
            action = settings.prefs.doubleClickTabBar
        elif click == "middle":
            action = settings.prefs.middleClickTabBar
        else:
            raise NotImplementedError(f"unknown special click kind '{click}'")

        widget: RepoWidget | RepoStub = self.tabs.widget(i)

        if action == TabBarClick.Nothing:
            pass
        elif action == TabBarClick.Folder:
            openFolder(widget.workdir)
        elif action == TabBarClick.Close:
            self.closeTab(i)
        elif action == TabBarClick.Terminal:
            ToolProcess.startTerminal(self, widget.workdir)
        else:
            raise NotImplementedError(f"unknown special click action '{action}'")

    # -------------------------------------------------------------------------
    # Repo loading

    def openRepo(self, path: str, exactMatch=True) -> RepoWidget | RepoStub | None:
        try:
            rw = self._openRepo(path, exactMatch=exactMatch)
        except BaseException as exc:
            excMessageBox(
                exc,
                _("Open repository"),
                _("Couldn’t open the repository at {0}.", bquo(path)),
                parent=self,
                icon='warning')
            return None

        self.saveSession()

        # Return a concrete RepoWidget instead of a RepoStub if loading is already completed
        # (mostly for single-threaded unit tests that expect a deterministic chain of events).
        if RepoTaskRunner.ForceSerial:
            rw2 = self.tabWidgetForWorkdirPath(rw.workdir)
            if isinstance(rw2, RepoWidget):
                rw = rw2
            else:
                assert not APP_TESTMODE, "the RepoWidget isn't ready yet"

        return rw

    def _resolveWorkdir(self, path: str, exactMatch) -> tuple[str, RepoWidget | RepoStub | None]:
        # Make sure the path exists
        if not os.path.exists(path):
            raise FileNotFoundError(_("There’s nothing at this path."))

        # Resolve the workdir
        if not exactMatch:
            with RepoContext(path) as repo:
                if repo.is_bare:
                    raise NotImplementedError(_("Sorry, {app} doesn’t support bare repositories.", app=qAppName()))
                path = repo.workdir

        # Scan for an existing tab for this repo
        existingWidget = self.tabWidgetForWorkdirPath(path)
        if existingWidget is not None:
            return existingWidget.workdir, existingWidget

        # There's no widget for this workdir but it's a valid repo
        return path, None

    def _openRepo(self, path: str, foreground=True, tabIndex=-1, exactMatch=True, locator=NavLocator.Empty
                  ) -> RepoWidget | RepoStub:
        path, existingWidget = self._resolveWorkdir(path, exactMatch)

        # First check that we don't have a tab for this repo already
        if existingWidget is not None:
            existingWidget.overridePendingLocator(locator)
            self.tabs.setCurrentWidget(existingWidget)
            return existingWidget

        # Create a RepoStub
        stub = RepoStub(parent=self, workdir=path, locator=locator)

        # Create a tab
        with QSignalBlockerContext(self.tabs):
            title = escamp(stub.getTitle())
            tabIndex = self.tabs.insertTab(tabIndex, stub, title)
            self.tabs.setTabTooltip(tabIndex, compactPath(path))
            if foreground:
                self.tabs.setCurrentIndex(tabIndex)
        self.refreshAllTabTexts()

        # We've got at least one tab now, so switch away from WelcomeWidget
        assert self.tabs.count() > 0
        self.welcomeStack.setCurrentWidget(self.tabs)

        # Load repo now
        if foreground:
            self.setWindowTitle(stub.windowTitle())
            stub.loadNow()

        return stub

    def installRepoWidget(self, rw: RepoWidget, tabIndex: int) -> None:
        repoStub = self.tabs.widget(tabIndex)
        assert tabIndex >= 0, "stub to replace isn't in tabs"
        assert isinstance(repoStub, RepoStub), "yanked widget isn't RepoStub"

        rw.nameChange.connect(self.onRepoNameChanged)
        rw.statusChanged.connect(self.refreshAllTabTexts)
        rw.requestAttention.connect(lambda: self.onRepoRequestsAttention(rw))
        rw.openRepo.connect(lambda path, locator: self.openRepoNextTo(rw, path, locator))
        rw.openPrefs.connect(GFApplication.instance().openPrefsDialog)
        rw.mustReplaceWithStub.connect(lambda stub: self.replaceRepoWidgetWithStub(rw, stub))

        rw.statusMessage.connect(self.statusBar2.showMessage)
        rw.busyMessage.connect(self.statusBar2.showBusyMessage)
        rw.clearStatus.connect(self.statusBar2.clearMessage)

        rw.historyChanged.connect(lambda: self.onRepoHistoryChanged(rw))
        rw.windowTitleChanged.connect(lambda: self.onRepoWindowTitleChanged(rw))

        self.tabs.swapWidget(tabIndex, rw)
        self.refreshAllTabTexts()

        repoStub.setParent(None)  # tabs don't deparent the widget
        repoStub.deleteLater()

    def replaceRepoWidgetWithStub(self, oldWidget: RepoWidget, stub: RepoStub) -> None:
        tabIndex = self.tabs.indexOf(oldWidget)
        assert tabIndex >= 0, "RepoWidget to replace isn't in tabs"
        self.tabs.swapWidget(tabIndex, stub)
        self.refreshAllTabTexts()

        oldWidget.setParent(None)  # tabs don't deparent the widget
        oldWidget.close()  # will call cleanup
        oldWidget.deleteLater()

    # -------------------------------------------------------------------------

    def onRegainForeground(self) -> None:
        if QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            return
        if not settings.prefs.autoRefresh:
            return
        with suppress(NoRepoWidgetError):
            self.currentRepoWidget().refreshRepo()

    def openWorkdirs(self) -> set[str]:
        """Workdirs of every open tab, loaded or not."""
        return {os.path.normpath(w.workdir) for w in self.tabs.widgets() if w.workdir}

    def onRepoNameChanged(self) -> None:
        self.refreshAllTabTexts()
        self.fillRecentMenu()

    def onRepoWindowTitleChanged(self, rw: RepoWidget) -> None:
        if rw.isVisible():
            self.setWindowTitle(rw.windowTitle())


    def onRepoHistoryChanged(self, rw: RepoWidget) -> None:
        if rw.isVisible():
            self.mainToolBar.updateNavButtons(rw.navHistory.canGoBack(), rw.navHistory.canGoForward())

    def onRepoRequestsAttention(self, rw: RepoWidget) -> None:
        i = self.tabs.indexOf(rw)
        self.tabs.requestAttention(i)

    # -------------------------------------------------------------------------
    # View menu

    def toggleStatusBar(self) -> None:
        GFApplication.applyPrefs(showStatusBar=not settings.prefs.showStatusBar)

    def toggleMenuBar(self) -> None:
        GFApplication.applyPrefs(showMenuBar=not settings.prefs.showMenuBar)

    def selectUncommittedChanges(self) -> None:
        self.currentRepoWidget().jump(NavLocator.inWorkdir())

    def selectHead(self) -> None:
        self.currentRepoWidget().jump(NavLocator.inRef("HEAD"))

    def focusSidebar(self) -> None:
        self.currentRepoWidget().sidebar.setFocus()

    def focusGraph(self) -> None:
        self.currentRepoWidget().graphView.setFocus()

    def focusFiles(self) -> None:
        rw = self.currentRepoWidget()
        context = rw.navLocator.context
        if context == NavContext.COMMITTED:
            rw.committedFiles.setFocus()
        else:
            target = rw.stagedFiles if context == NavContext.STAGED else rw.dirtyFiles
            fallback = rw.dirtyFiles if context == NavContext.STAGED else rw.stagedFiles
            if not target.isEmpty() or fallback.isEmpty():
                target.setFocus()
            else:
                fallback.setFocus()

    def focusDiff(self) -> None:
        rw = self.currentRepoWidget()
        if rw.specialDiffView.isVisibleTo(rw):
            rw.specialDiffView.setFocus()
        elif rw.conflictView.isVisibleTo(rw):
            rw.conflictView.setFocus()
        else:
            rw.diffView.setFocus()

    def nextFile(self) -> None:
        self.currentRepoWidget().diffArea.selectNextFile(True)

    def previousFile(self) -> None:
        self.currentRepoWidget().diffArea.selectNextFile(False)

    def blameFile(self) -> None:
        self.currentRepoWidget().blameFile()

    # -------------------------------------------------------------------------
    # Help menu

    def openRescueFolder(self) -> None:
        trash = Trash.instance()
        if trash.exists():
            openFolder(str(trash.trashDir))
        else:
            showInformation(
                self,
                _("Open trash folder"),
                _("There’s no trash folder. Perhaps you haven’t discarded a change with {0} yet.", qAppName()))

    def clearRescueFolder(self) -> None:
        trash = Trash.instance()
        sizeOnDisk, patchCount = trash.size()

        if patchCount <= 0:
            showInformation(
                self,
                _("Clear trash folder"),
                _("There are no discarded changes to delete."))
            return

        humanSize = self.locale().formattedDataSize(sizeOnDisk)

        askPrompt = paragraphs(
            _n("Do you want to permanently delete <b>{n}</b> discarded patch?",
               "Do you want to permanently delete <b>{n}</b> discarded patches?", patchCount),
            _("This will free up {0} on disk.", escape(humanSize)),
            _("This cannot be undone!")
        )

        askConfirmation(
            parent=self,
            title=_("Clear trash folder"),
            text=askPrompt,
            callback=lambda: trash.clear(),
            okButtonText=_("Delete permanently"),
            okButtonIcon=stockIcon("SP_DialogDiscardButton"))

    # -------------------------------------------------------------------------
    # File menu callbacks

    def newRepo(self) -> None:
        runner = RepoTaskRunner(self)
        runner.ready.connect(runner.deleteLater)
        NewRepo.invoke(runner, self.openRepo)

    def cloneDialog(self, initialUrl: str = "") -> None:
        dlg = CloneDialog(initialUrl, self)
        dlg.cloneSuccessful.connect(lambda path: self.openRepo(path, exactMatch=True))
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()

    def openDialog(self) -> None:
        qfd = PersistentFileDialog.openDirectory(self, "NewRepo", _("Open repository"))
        qfd.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # don't leak dialog
        qfd.fileSelected.connect(lambda path: self.openRepo(path, exactMatch=False))
        qfd.show()

    # -------------------------------------------------------------------------
    # Tab management

    def closeCurrentTab(self) -> None:
        if self.tabs.count() == 0:  # don't attempt to close if no tabs are open
            QApplication.beep()
            return

        self.closeTab(self.tabs.currentIndex())

    def closeTab(self, index: int, finalTab: bool = True) -> None:
        widget = self.tabs.widget(index)

        # Remove the tab BEFORE cleaning up the widget
        # to prevent any interaction with it while it's wrapping up.
        self.tabs.removeTab(index)
        self.refreshAllTabTexts()

        # Clean up the widget
        widget.close()  # will call RepoWidget.cleanup()
        widget.deleteLater()  # help out GC (for PySide6)
        del widget

        if finalTab:
            self.saveSession()
            gc.collect()

    def closeOtherTabs(self, index: int) -> None:
        # First, set this tab as active so an active tab that gets closed doesn't trigger other tabs to load.
        self.tabs.setCurrentIndex(index)

        # Now close all tabs in reverse order but skip the index we want to keep.
        start = self.tabs.count()-1
        final = 1 if index == 0 else 0
        for i in range(start, -1, -1):
            if i != index:
                self.closeTab(i, i == final)

    def unloadOtherTabs(self, index: int = -1) -> None:
        if index < 0:
            index = self.tabs.currentIndex()

        # First, set this tab as active so an active tab that gets closed doesn't trigger other tabs to load.
        self.tabs.setCurrentIndex(index)

        # Now unload all tabs but skip the index we want to keep.
        numUnloaded = 0
        for i in range(self.tabs.count()):
            rw = self.tabs.widget(i)
            if i == index or not isinstance(rw, RepoWidget):
                continue
            with QSignalBlockerContext(rw):
                stub = rw.replaceWithStub()
            stub.disableAutoLoad()
            self.replaceRepoWidgetWithStub(rw, stub)
            del rw
            numUnloaded += 1

        self.statusBar2.showMessage(_n("{n} background tab unloaded.", "{n} background tabs unloaded.", numUnloaded))
        gc.collect()

    def closeAllTabs(self) -> None:
        start = self.tabs.count() - 1
        with QSignalBlockerContext(self.tabs):  # Don't let awaken unloaded tabs
            for i in range(start, -1, -1):  # Close tabs in reverse order
                self.closeTab(i, i == 0)

        self.onTabCurrentWidgetChanged()

    def reloadAllTabs(self) -> None:
        self.unloadOtherTabs()
        rw = self.currentRepoWidget()
        rw.replaceWithStub()

    def refreshAllTabTexts(self) -> None:
        widgets = list(self.tabs.widgets())
        baseTitles = [widget.getTitle() for widget in widgets]
        newTitles = baseTitles[:]

        groupsByTitle: dict[str, list[int]] = {}
        for i, title in enumerate(baseTitles):
            groupsByTitle.setdefault(title, []).append(i)

        for group in groupsByTitle.values():
            if len(group) <= 1:
                continue
            # Only disambiguate default (basename) titles; custom nicknames are kept as-is.
            defaultIndices = [
                i for i in group
                if not settings.history.getRepoNickname(widgets[i].workdir, strict=True)]
            if len(defaultIndices) <= 1:
                continue
            workdirs = [widgets[i].workdir for i in defaultIndices]
            disambiguatedTitles = disambiguateTabTitlesByPath(workdirs)
            for idx, title in zip(defaultIndices, disambiguatedTitles, strict=True):
                newTitles[idx] = title

        self.refreshRepoButton()

        for i, (title, widget) in enumerate(zip(newTitles, widgets, strict=True)):
            self.tabs.setTabText(i, escamp(title))
            # The tab name stays the name; what's outstanding rides on the icon,
            # so it can't widen tabs or confuse name disambiguation.
            # An unloaded stub has read nothing, so it claims nothing.
            if isinstance(widget, RepoWidget):
                self.tabs.setTabStatusIcon(i, widget.statusIconKey())
                self.tabs.setTabTooltip(i, widget.statusTooltip())

        # Toggle toolbar's borderless property (for custom theme)
        borderlessToolBar = self.tabs.count() >= 2 or not self.tabs.tabs.autoHide()
        toggleQssProperty(self.mainToolBar, "borderless", borderlessToolBar)

    def openRepoNextTo(self, rw, path: str, locator: NavLocator = NavLocator.Empty):
        index = self.tabs.indexOf(rw)
        if index >= 0:
            index += 1
        return self._openRepo(path, tabIndex=index, exactMatch=True, locator=locator)

    def nextTab(self) -> None:
        if self.tabs.count() == 0:
            QApplication.beep()
            return
        index = self.tabs.currentIndex()
        index += 1
        index %= self.tabs.count()
        self.tabs.setCurrentIndex(index)

    def previousTab(self) -> None:
        if self.tabs.count() == 0:
            QApplication.beep()
            return
        index = self.tabs.currentIndex()
        index += self.tabs.count() - 1
        index %= self.tabs.count()
        self.tabs.setCurrentIndex(index)

    # -------------------------------------------------------------------------
    # Session management

    def restoreSession(self, session: settings.Session, sloppyPaths: list[str] | None = None) -> None:
        # Note: window geometry, despite being part of the session file, is
        # restored in application.py to avoid flashing a window with incorrect
        # dimensions on boot

        RepoWidget.sharedSplitterSizes = copy.deepcopy(session.splitterSizes)

        # Stop here if there are no tabs to load
        if not session.tabs:
            return

        errors = []

        # We might not be able to load all tabs, so we may have to adjust the active tab index.
        activeTab = -1
        successfulRepos = []

        # Lazy-loading: prepare all tabs, but don't load the repos (foreground=False).
        for i, path in enumerate(session.tabs):
            sloppy = sloppyPaths is not None and path in sloppyPaths

            try:
                newRepoWidget = self._openRepo(path, exactMatch=not sloppy, foreground=False)
            except (GitError, OSError, NotImplementedError) as exc:
                # GitError: most errors thrown by pygit2
                # OSError: e.g. permission denied
                # NotImplementedError: e.g. shallow/bare repos
                errors.append((path, exc))
                continue

            assert isinstance(newRepoWidget, RepoWidget | RepoStub)

            # If we were passed a "sloppy" path from the command line, remember the root path.
            if sloppy:
                path = newRepoWidget.workdir

            successfulRepos.append(path)

            if i == session.activeTabIndex:
                # Heads up: MainWindow._openRepo may return an existing RepoWidget that matches the
                # given path. So, we're not necessarily the last tab, e.g. if the user passes
                # duplicate paths on the CLI.
                activeTab = self.tabs.indexOf(newRepoWidget)

        # If we failed to load anything, tell the user about it
        if errors:
            self._reportSessionErrors(errors)

        # Update history (don't write it yet - onTabCurrentWidgetChanged will do it below)
        for path in reversed(successfulRepos):
            settings.history.addRepo(path)
        self.fillRecentMenu()

        # Fall back to tab #0 if desired tab couldn't be restored (otherwise welcome page will stick around)
        if activeTab < 0 and len(successfulRepos) >= 1:
            activeTab = 0

        # Set current tab and load its repo.
        if activeTab >= 0:
            self.tabs.setCurrentIndex(activeTab)
            self.onTabCurrentWidgetChanged()  # needed to trigger loading on tab #0

    def _reportSessionErrors(self, errors: Sequence[tuple[str, BaseException]]) -> None:
        numErrors = len(errors)
        text = _n("The session couldn’t be restored fully because a repository failed to load:",
                  "The session couldn’t be restored fully because {n} repositories failed to load:", numErrors)
        qmb = asyncMessageBox(self, 'warning', _("Restore session"), text)
        addULToMessageBox(qmb, [f"<b>{compactPath(path)}</b><br>{exc}" for path, exc in errors])
        qmb.show()

    def saveSession(self, writeNow=False) -> None:
        if writeNow:
            # Only on the way out. saveSession also runs every time a tab opens
            # or closes, and a workspace shouldn't absorb every repo you glance at.
            self.rememberCurrentWorkspace()
        session = settings.Session()
        session.windowGeometry = self.saveGeometry().data()
        session.splitterSizes = RepoWidget.sharedSplitterSizes.copy()
        session.tabs = [widget.workdir for widget in self.tabs.widgets()]
        session.activeTabIndex = self.tabs.currentIndex()
        session.setDirty()
        if writeNow:
            session.write()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not GFApplication.instance().mountManager.checkOnClose(self, self.close):
            event.setAccepted(False)
            return

        # A scan running in the background must not outlive the window
        self.welcomeWidget.stopScan()

        # Save session before closing all tabs.
        self.saveSession(writeNow=True)

        # Close all tabs so RepoWidgets release all their resources.
        # Important so unit tests wind down properly!
        self.closeAllTabs()

        super().closeEvent(event)

    # -------------------------------------------------------------------------
    # Drag and drop

    def getDropOutcomeFromLocalFilePath(self, path: str) -> tuple[DropAction, str]:
        if path.endswith(".patch"):
            return DropAction.Patch, path

        try:
            workdir, existingWidget = self._resolveWorkdir(path, exactMatch=False)
        except Exception as exc:
            if isinstance(exc, GitError) and str(exc).startswith("Repository not found"):
                return DropAction.Deny, _("{0} isn’t in a Git repo", tquoe(Path(path).name))
            else:  # pragma: no cover
                logger.exception("in drop outcome: _resolveWorkdir failed")
                return DropAction.Deny, str(exc)

        if existingWidget is not None and existingWidget.isVisible() and Path(path).is_file():
            return DropAction.Blame, path

        return DropAction.Open, workdir

    def getDropOutcomeFromMimeData(self, mime: QMimeData) -> tuple[DropAction, str]:
        if mime.hasUrls():
            try:
                url: QUrl = mime.urls()[0]
            except IndexError:
                return DropAction.Deny, ""

            if url.isLocalFile():
                path = url.toLocalFile()
                return self.getDropOutcomeFromLocalFilePath(path)
            else:
                return DropAction.Clone, url.toString()

        elif mime.hasText():
            text = mime.text()
            text = text.strip()
            if os.path.isabs(text) and os.path.exists(text):
                return self.getDropOutcomeFromLocalFilePath(text)
            elif text.startswith(("ssh://", "git+ssh://", "https://", "http://")):
                return DropAction.Clone, text
            elif re.match(r"^[a-zA-Z0-9-_.]+@.+:.+", text):
                return DropAction.Clone, text
            else:
                return DropAction.Deny, ""

        return DropAction.Deny, ""

    def handleDrop(self, action: DropAction, data: str) -> None:
        if action == DropAction.Deny:
            pass
        elif action == DropAction.Clone:
            self.cloneDialog(data)
        elif action == DropAction.Blame:
            rw = self.currentRepoWidget()
            path = Path(data)
            path = path.relative_to(rw.workdir)  # May raise ValueError('X is not in the subpath of Y')
            pathStr = path.as_posix()  # WINDOWS: Convert to forward slashes to match internal git representation
            rw.blameFile(pathStr)
        elif action == DropAction.Open:
            self.openRepo(data, exactMatch=True)
        elif action == DropAction.Patch:
            tasks.ApplyPatchFile.invoke(self, data)
        else:
            warnings.warn(f"Unsupported drag-and-drop outcome {action}")  # type: ignore[unreachable]

    # -------------------------------------------------------------------------
    # Prefs

    def refreshPrefs(self) -> None:
        # The Settings dialog can change the theme too; keep the switch honest
        self.refreshThemeButton()
        self.mainToolBar.applyCompact(settings.prefs.compactUi)
        self.statusBar2.setVisible(settings.prefs.showStatusBar)
        self.statusBar2.enableMemoryIndicator(APP_DEBUG)
        self.mainToolBar.setVisible(settings.prefs.showToolBar)
        self.showStatusBarAction.setChecked(settings.prefs.showStatusBar)
        self.showMenuBarAction.setChecked(settings.prefs.showMenuBar)

    def onApplyPrefs(self, changedKeys: set[str]) -> None:
        if "homeMascot" in changedKeys:
            self.welcomeWidget.mascot.applyPrefs()

        if "showMenuBar" in changedKeys and not settings.prefs.showMenuBar:
            self.showMenuBarHiddenWarning()

        if PrefEffects.RebuildMenu & changedKeys:
            self.fillGlobalMenuBar()

        if PrefEffects.RestartApp & changedKeys:
            showInformation(
                self,
                _("Apply Settings"),
                _("You may need to restart {app} for the new settings to take effect fully.", app=qAppName()))
        elif PrefEffects.ReloadRepo & changedKeys and self.tabs.count() != 0:
            qmb = asyncMessageBox(
                self,
                "question",
                _("Apply Settings"),
                _("The new settings won’t take effect fully until you reload the current repositories."),
                buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            qmb.button(QMessageBox.StandardButton.Ok).setText(_("&Reload"))
            qmb.button(QMessageBox.StandardButton.Cancel).setText(_("&Not Now"))
            qmb.accepted.connect(self.reloadAllTabs)
            qmb.show()

        # If any changed setting matches autoReload, schedule a forced refresh
        # of the current diff in all loaded RepoWidgets.
        if PrefEffects.ReloadDiff & changedKeys:
            # Nuke cached syntax highlighting
            LexJobCache.clear()

            for rw in self.tabs.widgets():
                if not isinstance(rw, RepoWidget):
                    continue
                locator = rw.taskRunner.pendingEpilog.jumpTo or rw.navLocator
                locator = locator.withExtraFlags(NavFlags.ForceDiff | NavFlags.ForceRecreateDocument)
                rw.taskRunner.pendingEpilog.jumpTo = locator
                rw.refreshRepo()

    # -------------------------------------------------------------------------
    # Dispatch commands to detached windows

    def dispatchCloseCommand(self) -> None:
        if self.isActiveWindow():
            self.closeCurrentTab()
            return

        # This is for macOS. Systems without a global main menu (i.e. anything but macOS)
        # take a different path to intercept keyboard shortcuts.
        try:
            CodeView.currentDetachedCodeView().window().close()
        except KeyError:
            QApplication.beep()

    def dispatchSearchCommand(self, op: SearchBar.Op = SearchBar.Op.Start) -> None:
        if self.isActiveWindow() and self.currentRepoWidget():
            self.currentRepoWidget().dispatchSearchCommand(op)
            return

        # This is for macOS. Systems without a global main menu (i.e. anything but macOS)
        # take a different path to intercept keyboard shortcuts.
        try:
            CodeView.currentDetachedCodeView().searchBar.popUp(op)
        except KeyError:
            QApplication.beep()

    # -------------------------------------------------------------------------
    # User commands

    def parseUserCommands(self) -> None:
        self.userCommands = list(UserCommand.parseCommandBlock(settings.prefs.commands))

    def contextualUserCommands(self, *placeholderTokens: UserCommand.Token) -> list[ActionDef]:
        tokenSet = set(placeholderTokens)
        actions: list[ActionDef] = []
        for command in self.userCommands:
            if not command.matchesContext(tokenSet):
                continue
            if not actions:
                actions.append(ActionDef.SEPARATOR)
            actions.append(ActionDef(
                _("(Command) {0}", command.menuTitle()),
                lambda c=command: self.currentRepoWidget().executeUserCommand(c),
                "prefs-usercommands",
                tip=command.menuToolTip(),
                shortcuts=command.shortcut,
            ))
        return actions

    # -------------------------------------------------------------------------
    # Repository-less actions (actions that only need a path to the workdir;
    # full-blown RepoWidget not required)

    def repolessActions(self, workdir: str | Callable[[], str]) -> list[ActionDef]:
        superprojectLabel = _("Open Superproject")
        superprojectEnabled = True
        superproject = None

        if isinstance(workdir, str):
            def workdirProxy():
                return workdir
            superproject = settings.history.getRepoSuperproject(workdir)
            superprojectEnabled = bool(superproject)
            if superprojectEnabled:
                superprojectName = settings.history.getRepoTabName(superproject)
                superprojectLabel = _("Open Superproject {0}", lquo(superprojectName))
        else:
            workdirProxy = workdir
        assert callable(workdirProxy)

        return [
            ActionDef(
                _("&Open Repo Folder"),
                lambda: openFolder(workdirProxy()),
                icon="reveal",
                shortcuts=GlobalShortcuts.openRepoFolder,
                tip=_("Open this repo’s working directory in the system’s file manager"),
            ),

            ActionDef(
                _("Open &Terminal"),
                lambda: ToolProcess.startTerminal(self, workdirProxy()),
                icon="terminal",
                shortcuts=GlobalShortcuts.openTerminal,
                tip=_("Open a terminal in the repo’s working directory"),
            ),

            ActionDef(
                _("Op&en Repo in {0}", getExternalEditorName()),
                lambda: self.openRepoInEditor(workdirProxy()),
                icon="prefs-diff",
                shortcuts=GlobalShortcuts.NO_SHORTCUT,
                tip=_("Open this repo’s working directory in {0}", getExternalEditorName()),
            ),

            ActionDef(
                _("Cop&y Repo Path"),
                lambda: self.repolessCopyPath(workdirProxy()),
                tip=_("Copy the absolute path to this repo’s working directory to the clipboard"),
            ),

            ActionDef(
                superprojectLabel,
                lambda: self.repolessOpenSuperproject(workdirProxy(), superproject),
                enabled=superprojectEnabled,
            ),

            ActionDef(
                _("Re&name…"),
                lambda: self.repolessSetNickname(workdirProxy()),
                icon="rename",
            ),
        ]

    def openRepoInEditor(self, workdir: str) -> None:
        if settings.prefs.externalEditor == "":
            setUpToolCommand(self, "externalEditor")
            return

        ToolProcess.startTextEditor(self, workdir)

    def repolessSetNickname(self, workdir: str) -> None:
        defaultName = Path(workdir).name
        oldNickname = settings.history.getRepoNickname(workdir, strict=True)

        title = _("Nickname for {0}", tquoe(defaultName))
        label = _("Enter or clear nickname for this repository:")
        leaveBlank = _("Leave blank to refer to this repo as {0}", tquoe(defaultName))
        hint = "<p>" + _p(  # Sync with ui_reposettingsdialog.py to keep existing translation
            "RepoSettingsDialog",
            "This nickname will appear within {app} in tab names, menus, etc. "
            "It does not change the actual name of the repo’s directory. "
            "Leave blank to clear the nickname.",
            app=qAppName())

        tid = TextInputDialog(self, title, label, subtitle=escamp(compactPath(workdir)), hint=hint)
        tid.lineEdit.setClearButtonEnabled(True)
        tid.lineEdit.setPlaceholderText(leaveBlank)
        tid.lineEdit.setText(oldNickname)
        tid.lineEdit.selectAll()
        tid.textAccepted.connect(lambda nick: self._repolessSetNicknameImpl(workdir, nick))
        tid.show()

    def _repolessSetNicknameImpl(self, workdir: str, nick: str) -> None:
        settings.history.setRepoNickname(workdir, nick)
        settings.history.setDirty()
        tabWidget = self.tabWidgetForWorkdirPath(workdir)
        if isinstance(tabWidget, RepoWidget):
            # Percolate to sidebar, etc.
            tabWidget.nameChange.emit()
        else:
            # RepoStub
            self.onRepoNameChanged()

    def repolessCopyPath(self, workdir: str) -> None:
        QApplication.clipboard().setText(workdir)
        self.statusBar2.showMessage(clipboardStatusMessage(workdir))

    def repolessOpenSuperproject(self, workdir: str, superproject: str | None = None) -> None:
        if superproject is None:
            superproject = settings.history.getRepoSuperproject(workdir)

        if not superproject:
            showInformation(self, _("Open Superproject"), _("This repository does not have a superproject."))
            return

        submoduleTab = self.tabWidgetForWorkdirPath(workdir)  # may be None
        self.openRepoNextTo(submoduleTab, superproject)
