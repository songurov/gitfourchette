# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Iterable

from gitfourchette import settings
from gitfourchette import tasks
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook
from gitfourchette.themes import activeTheme
from gitfourchette.toolbox import *


class MainToolBar(QToolBar):
    openPrefs = Signal()
    setDarkThemeRequested = Signal(bool)
    setCompactRequested = Signal(bool)
    pull = Signal()
    push = Signal()

    backAction: QAction
    forwardAction: QAction
    openInAction: QAction
    repoAction: QAction
    workspaceAction: QAction
    themeAction: QAction

    def __init__(self, parent: QWidget):
        super().__init__(englishTitleCase(_("Show toolbar")), parent)

        self.setObjectName("GFToolbar")
        self.setMovable(False)

        self.userCommandActions: list[QAction] = []
        self.darkTheme = False
        self.iconColorTable = ""

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.onCustomContextMenuRequested)

        self.visibilityChanged.connect(self.onVisibilityChanged)
        self.toolButtonStyleChanged.connect(self.onToolButtonStyleChanged)
        self.iconSizeChanged.connect(self.onIconSizeChanged)

        self.backAction = TaskBook.toolbarAction(self, tasks.JumpBack).toQAction(self)
        self.forwardAction = TaskBook.toolbarAction(self, tasks.JumpForward).toQAction(self)

        # Home has no repo in front of you, so the repo buttons step aside. These
        # take their place: the ways into a repo. MainWindow connects them.
        self.openRepoAction = ActionDef(
            _p("toolbar", "Open"), icon="folder-open",
            tip=_("Open a Git repo on your machine")).toQAction(self)
        self.cloneRepoAction = ActionDef(
            _p("toolbar", "Clone"), icon="folder-download",
            tip=_("Download a Git repo and open it")).toQAction(self)
        self.newRepoAction = ActionDef(
            _p("toolbar", "New"), icon="folder-new",
            tip=_("Create an empty Git repo")).toQAction(self)
        self.quickLaunchAction = ActionDef(
            _p("toolbar", "Quick Launch"), icon="edit-find",
            tip=_("Type a few letters of any command, repo or workspace, and press Enter")).toQAction(self)
        homeSeparator = QAction(self)
        homeSeparator.setSeparator(True)
        self.homeActions = [self.openRepoAction, self.cloneRepoAction, self.newRepoAction,
                            homeSeparator, self.quickLaunchAction]

        self.workdirAction = TaskBook.toolbarAction(self, tasks.JumpToUncommittedChanges).toQAction(self)
        self.headAction = TaskBook.toolbarAction(self, tasks.JumpToHEAD).toQAction(self)

        # One button for every "take this repo somewhere else": the file
        # manager, a terminal, an editor. Its menu is filled by MainWindow,
        # which is the one that knows which repo is in front of you.
        self.openInAction = ActionDef(
            _("Open In"), icon="terminal",
            tip=_("Open this repo in a terminal, a file manager or an editor")
        ).toQAction(self)

        self.workspaceAction = ActionDef(
            _("Workspace"), icon="git-workspace",
            tip=_("Switch between named sets of repos")
        ).toQAction(self)

        # Look and feel in one place: light vs dark, and how much room the
        # toolbar takes. Both are a click away instead of buried in Settings.
        # The middle of the bar says where you are: which repo, on which branch.
        # Clicking it switches branches, since that's what you'd want next.
        self.repoAction = ActionDef(
            "", icon="git-branch",
            tip=_("Current repo and branch")
        ).toQAction(self)

        self.themeAction = ActionDef(
            _("Theme"), icon="theme-dark",
        ).toQAction(self)
        self.themeMenu = QMenu(self)
        self.themeMenu.setObjectName("MainToolBarThemeMenu")
        self.themeMenu.aboutToShow.connect(self.fillThemeMenu)
        self.themeAction.setMenu(self.themeMenu)

        self.settingsAction = ActionDef(
            _("Settings"), self.openPrefs, icon="git-settings",
            shortcuts=QKeySequence.StandardKey.Preferences,
            tip=_("Configure {app}", app=qAppName())
        ).toQAction(self)

        defs = [
            *self.homeActions,
            self.backAction,
            self.forwardAction,
            self.workdirAction,
            self.headAction,
            ActionDef.SEPARATOR,

            TaskBook.toolbarAction(self, tasks.NewStash),
            TaskBook.toolbarAction(self, tasks.NewBranchFromHead),
            ActionDef.SEPARATOR,
            TaskBook.toolbarAction(self, tasks.FetchRemotes),
            TaskBook.toolbarAction(self, tasks.PullBranch),
            TaskBook.toolbarAction(self, tasks.PushBranch),
            ActionDef.SPACER,

            self.repoAction,
            ActionDef.SPACER,

            self.openInAction,
            self.themeAction,
            self.workspaceAction,

            ActionDef.SEPARATOR,
            self.settingsAction,
        ]
        ActionDef.addToQToolBar(self, *defs)

        # Everything up to the spacer needs a repo - the nav arrows, the jump
        # buttons, stash/branch/fetch/pull/push - and so does "Open In". Taken
        # as a slice of the bar so separators travel with them and none is left
        # stranded. The spacer itself stays, so the right-hand group keeps its
        # place instead of sliding left on Home.
        allActions = self.actions()
        spacerIndex = next(i for i, a in enumerate(allActions) if isinstance(a, QWidgetAction))
        self.repoScopedActions = [a for a in allActions[:spacerIndex] if a not in self.homeActions]
        self.repoScopedActions += [self.openInAction, self.repoAction]

        repoButton = self.widgetForAction(self.repoAction)
        assert isinstance(repoButton, QToolButton)
        repoButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        repoButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        repoButton.setObjectName("GFToolbarRepoButton")
        self.repoButton = repoButton

        themeButton = self.widgetForAction(self.themeAction)
        assert isinstance(themeButton, QToolButton)
        themeButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        openInButton = self.widgetForAction(self.openInAction)
        assert isinstance(openInButton, QToolButton)
        openInButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # The workspace button has no action of its own: clicking it opens the list.
        workspaceButton = self.widgetForAction(self.workspaceAction)
        assert isinstance(workspaceButton, QToolButton)
        workspaceButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setWorkspaceName("")

        # No repo is open until one is: start with the repo-only buttons hidden,
        # since onTabCurrentWidgetChanged doesn't fire on a tab-less launch.
        self.setRepoScopedActionsVisible(False)

        self.applyCompact(settings.prefs.compactUi)

        self.updateNavButtons()

    def setRepoScopedActionsVisible(self, visible: bool):
        """
        Hide what needs a repo when there isn't one.

        On Home there is nothing to stash, no branch to push and no folder to
        reveal; offering them is an invitation to click something that can't work.
        """
        for action in self.repoScopedActions:
            action.setVisible(visible)
        for action in self.homeActions:
            action.setVisible(not visible)

    def fillThemeMenu(self):
        dark = self.darkTheme
        compact = settings.prefs.compactUi

        actions = [
            ActionDef(_("&Light"), lambda: self.setDarkThemeRequested.emit(False),
                      icon="theme-light", checkState=1 if not dark else -1,
                      radioGroup="mode"),
            ActionDef(_("&Dark"), lambda: self.setDarkThemeRequested.emit(True),
                      icon="theme-dark", checkState=1 if dark else -1,
                      radioGroup="mode"),
            ActionDef.SEPARATOR,
            ActionDef(_("&Normal"), lambda: self.setCompactRequested.emit(False),
                      checkState=1 if not compact else -1, radioGroup="density",
                      tip=_("Show button labels in the toolbar")),
            ActionDef(_("&Compact"), lambda: self.setCompactRequested.emit(True),
                      checkState=1 if compact else -1, radioGroup="density",
                      tip=_("Smaller text and icon-only toolbar buttons")),
        ]

        self.themeMenu.clear()
        ActionDef.addToQMenu(self.themeMenu, *actions)

    def setRepoSummary(self, repoName: str, branchName: str, dirty: bool):
        """Say which repo is in front of you, and what it's checked out on."""
        star = "*" if dirty else ""
        if not repoName:
            self.repoAction.setText("")
            self.repoAction.setToolTip("")
            return
        # Two lines when there's room for them, one when the bar is tight
        separator = " — " if settings.prefs.compactUi else "\n"
        self.repoAction.setText(f"{repoName}{star}{separator}{branchName}")
        self.repoAction.setToolTip(
            _("{0} on {1}", repoName, branchName) if branchName else repoName)

    def applyCompact(self, compact: bool):
        """
        Two shapes for the same bar, in the theme's proportions.

        Normal stacks a larger icon over its label, which is what a toolbar you
        look at all day wants. Compact drops the labels and shrinks the icons,
        to match the smaller type everywhere else.

        The theme sizes the icons of the normal shape, and may shrink the labels
        and give the icons a color of their own: Neutral draws small bright
        icons over short dim labels.
        """
        theme = activeTheme()
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if compact
                                else Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        size = 14 if compact else (theme.toolbarIconSize if theme else 22)
        self.setIconSize(QSize(size, size))
        # The middle block keeps its text in both shapes: it's the label, not a button
        self.repoButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # Each button gets its font directly: under a style sheet, a font set on
        # the toolbar doesn't reach its buttons. QFont() follows the app's again.
        labelFont = QFont()
        pointDrop = theme.toolbarLabelDrop if theme else 0
        if pointDrop:
            labelFont = QApplication.font()
            labelFont.setPointSizeF(max(6.0, labelFont.pointSizeF() - pointDrop))

        iconColor = theme.toolbarIconColor if theme else ""
        self.iconColorTable = f"gray={iconColor}" if iconColor else ""

        for action in self.actions():
            button = self.widgetForAction(action)
            if isinstance(button, QToolButton) and button is not self.repoButton:
                button.setFont(labelFont)
            iconId = action.property(ActionDef.IconProperty)
            if iconId:
                action.setIcon(stockIcon(iconId, self.iconColorTable))

    def setDarkTheme(self, dark: bool):
        """Show which way the theme is set, right on the button."""
        self.darkTheme = dark
        iconId = "theme-dark" if dark else "theme-light"
        self.themeAction.setProperty(ActionDef.IconProperty, iconId)
        self.themeAction.setIcon(stockIcon(iconId, self.iconColorTable))
        self.themeAction.setToolTip(_("Dark theme") if dark else _("Light theme"))

    def setWorkspaceName(self, name: str):
        """Show which workspace is active - or that none is - right on the button."""
        if name:
            self.workspaceAction.setText(elide(name, ems=14))
            self.workspaceAction.setToolTip(_("Workspace: {0}", name))
        else:
            self.workspaceAction.setText(_("Home"))
            self.workspaceAction.setToolTip(_("Home: every repo on this machine"))

    def setToolButtonStyle(self, style: Qt.ToolButtonStyle):
        # Resolve style
        if style == Qt.ToolButtonStyle.ToolButtonFollowStyle:
            styleHint = QApplication.style().styleHint(QStyle.StyleHint.SH_ToolButtonStyle)
            style = Qt.ToolButtonStyle(styleHint)

        super().setToolButtonStyle(style)

        # Hide back/forward button text with ToolButtonTextBesideIcon
        if style != Qt.ToolButtonStyle.ToolButtonTextOnly:
            for navAction in (self.backAction, self.forwardAction):
                navButton = self.widgetForAction(navAction)
                assert isinstance(navButton, QToolButton)
                navButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        if style == Qt.ToolButtonStyle.ToolButtonTextBesideIcon:
            for navAction in (self.headAction, self.workdirAction, self.settingsAction):
                navButton = self.widgetForAction(navAction)
                assert isinstance(navButton, QToolButton)
                navButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

    def onCustomContextMenuRequested(self, localPoint: QPoint):
        globalPoint = self.mapToGlobal(localPoint)

        def textPositionAction(name, style):
            return ActionDef(name,
                             callback=lambda: self.setToolButtonStyle(style),
                             checkState=1 if self.toolButtonStyle() == style else -1,
                             radioGroup="TextPosition")

        def iconSizeAction(name, size):
            return ActionDef(name,
                             callback=lambda: self.setIconSize(QSize(size, size)),
                             checkState=1 if self.iconSize().width() == size else -1,
                             radioGroup="IconSize")

        menu = ActionDef.makeQMenu(self, [
            self.toggleViewAction(),

            ActionDef.SEPARATOR,

            ActionDef(
                _("Text Position"),
                submenu=[
                    textPositionAction(_("Icons Only"), Qt.ToolButtonStyle.ToolButtonIconOnly),
                    textPositionAction(_("Text Only"), Qt.ToolButtonStyle.ToolButtonTextOnly),
                    textPositionAction(_("Text Alongside Icons"), Qt.ToolButtonStyle.ToolButtonTextBesideIcon),
                    textPositionAction(_("Text Under Icons"), Qt.ToolButtonStyle.ToolButtonTextUnderIcon),
                ]
            ),

            ActionDef(
                _("Icon Size"),
                submenu=[
                    iconSizeAction(_("Small"), 16),
                    iconSizeAction(_("Medium"), 20),
                    iconSizeAction(_("Large"), 24),
                    iconSizeAction(_("Huge"), 32),
                ]
            ),
        ])

        menu.popup(globalPoint)

    def onVisibilityChanged(self, visible: bool):
        # self.window().setUnifiedTitleAndToolBarOnMac(visible)
        if visible == settings.prefs.showToolBar:
            return
        settings.prefs.showToolBar = visible
        settings.prefs.setDirty()

    def onToolButtonStyleChanged(self, style: Qt.ToolButtonStyle):
        if style == settings.prefs.toolBarButtonStyle:
            return
        settings.prefs.toolBarButtonStyle = style
        settings.prefs.setDirty()

    def onIconSizeChanged(self, size: QSize):
        w = size.width()
        if w == settings.prefs.toolBarIconSize:
            return
        settings.prefs.toolBarIconSize = w
        settings.prefs.setDirty()

    def updateNavButtons(self, back: bool = False, forward: bool = False):
        self.backAction.setEnabled(back)
        self.forwardAction.setEnabled(forward)

    def setUserCommandActions(self, newActions: Iterable[QAction]):
        """User commands are another way of taking a repo somewhere, so they
        live under the same button, below a separator."""
        self.userCommandActions = list(newActions)
