# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
from collections.abc import Iterable

from gitfourchette import settings
from gitfourchette import tasks
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook
from gitfourchette.themes import ToolbarLayout, activeTheme
from gitfourchette.toolbox import *


@dataclasses.dataclass
class ToolbarArrangement:
    """The main toolbar's buttons in one ToolbarLayout."""

    actions: list[QAction]
    "Everything on the bar, in order, separators and spacers included."

    repoScoped: list[QAction]
    "What needs a repo, hidden on Home."

    homeOnly: list[QAction]
    "What stands in for the repo buttons on Home."

    icons: dict[QAction, str]
    "Icons that this layout draws differently from another one."


class RepoSummaryBox(QFrame):
    """
    The middle of the Centered toolbar: the repo in front of you, in bold, over
    the branch it's on. The branch opens the branch menu. On Home, it names
    the workspace instead.
    """

    Width = 300
    Height = 40
    CompactHeight = 24

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("GFRepoBox")

        self.nameLabel = QElidedLabel(self)
        self.nameLabel.setObjectName("GFRepoBoxName")
        self.nameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nameLabel.setElideMode(Qt.TextElideMode.ElideMiddle)

        self.branchButton = QToolButton(self)
        self.branchButton.setObjectName("GFRepoBoxBranch")
        self.branchButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.branchButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.branchButton.setIconSize(QSize(12, 12))
        self.branchButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.branchButton.setToolTip(_("Switch to branch"))

        layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(1)
        layout.addWidget(self.nameLabel)
        layout.addWidget(self.branchButton, 0, Qt.AlignmentFlag.AlignHCenter)

        self.setCompact(False)

    def setCompact(self, compact: bool):
        """Name and branch side by side in compact mode, where the bar is one line high."""
        layout = self.layout()
        assert isinstance(layout, QBoxLayout)
        if compact:
            layout.setDirection(QBoxLayout.Direction.LeftToRight)
            self.setFixedSize(RepoSummaryBox.Width, RepoSummaryBox.CompactHeight)
        else:
            layout.setDirection(QBoxLayout.Direction.TopToBottom)
            self.setFixedSize(RepoSummaryBox.Width, RepoSummaryBox.Height)

    def setSummary(self, title: str, branch: str = "", tip: str = ""):
        self.nameLabel.setText(title)
        # Leave the name room to breathe: a long branch is cut in the middle
        metrics = QFontMetrics(self.branchButton.font())
        self.branchButton.setText(metrics.elidedText(branch, Qt.TextElideMode.ElideMiddle, RepoSummaryBox.Width - 60))
        self.branchButton.setVisible(bool(branch))
        self.setToolTip(tip)


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
        self.repoOpen = False
        self.arrangementName = ""
        self.repoButton: QToolButton | None = None
        self.repoSummary = ("", "", False)
        "Repo name, branch name, and whether HEAD is detached (see setRepoSummary)."
        self.workspaceName = ""

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.onCustomContextMenuRequested)

        self.visibilityChanged.connect(self.onVisibilityChanged)
        self.toolButtonStyleChanged.connect(self.onToolButtonStyleChanged)
        self.iconSizeChanged.connect(self.onIconSizeChanged)

        # The bar shows the same actions as the menus, minus their shortcuts:
        # the menu's copy owns the key, or both would claim it.
        def toolbarAction(actionDef: ActionDef) -> QAction:
            action = actionDef.toQAction(self)
            action.setShortcut("")
            return action

        def taskAction(taskClass) -> QAction:
            return toolbarAction(TaskBook.toolbarAction(self, taskClass))

        # MainWindow connects this one to View > Show Sidebar, which owns the key
        self.sidebarAction = toolbarAction(ActionDef(
            _p("toolbar", "Sidebar"), icon="sidebar-left",
            shortcuts=GlobalShortcuts.toggleSidebar,
            tip=_("Show or hide the sidebar")))

        self.backAction = taskAction(tasks.JumpBack)
        self.forwardAction = taskAction(tasks.JumpForward)

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

        self.workdirAction = taskAction(tasks.JumpToUncommittedChanges)
        self.headAction = taskAction(tasks.JumpToHEAD)

        self.stashAction = taskAction(tasks.NewStash)
        self.branchAction = taskAction(tasks.NewBranchFromHead)
        self.fetchAction = taskAction(tasks.FetchRemotes)
        self.pullAction = taskAction(tasks.PullBranch)
        self.pushAction = taskAction(tasks.PushBranch)

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

        # The same, as a box of its own in the middle of the Centered layout
        self.repoBox = RepoSummaryBox(self)
        self.repoBoxAction = QWidgetAction(self)
        self.repoBoxAction.setDefaultWidget(self.repoBox)

        self.themeAction = ActionDef(
            _("Theme"), icon="theme-dark",
        ).toQAction(self)
        self.themeMenu = QMenu(self)
        self.themeMenu.setObjectName("MainToolBarThemeMenu")
        self.themeMenu.aboutToShow.connect(self.fillThemeMenu)
        self.themeAction.setMenu(self.themeMenu)

        self.settingsAction = toolbarAction(ActionDef(
            _("Settings"), self.openPrefs, icon="git-settings",
            shortcuts=QKeySequence.StandardKey.Preferences,
            tip=_("Configure {app}", app=qAppName())))

        self.arrangements = {
            ToolbarLayout.Classic: self.classicArrangement(),
            ToolbarLayout.Centered: self.centeredArrangement(),
        }

        # Keeps the Centered layout's box in the middle of the bar (see centerRepoBox)
        self.centeringTimer = QTimer(self)
        self.centeringTimer.setSingleShot(True)
        self.centeringTimer.setInterval(0)
        self.centeringTimer.timeout.connect(self.centerRepoBox)

        # The workspace button has no action of its own: clicking it opens the list.
        self.setWorkspaceName("")

        # No repo is open until one is: start with the repo-only buttons hidden,
        # since onTabCurrentWidgetChanged doesn't fire on a tab-less launch.
        self.applyCompact(settings.prefs.compactUi)

        self.updateNavButtons()

    def separatorAction(self) -> QAction:
        action = QAction(self)
        action.setSeparator(True)
        return action

    def spacerAction(self, width: int = 0) -> QWidgetAction:
        """Room between two groups: all there is to spare, or a fixed width."""
        spacer = QWidget()
        if width:
            spacer.setFixedWidth(width)
        else:
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        action = QWidgetAction(self)
        action.setDefaultWidget(spacer)
        return action

    def classicArrangement(self) -> ToolbarArrangement:
        homeSeparator = self.separatorAction()
        homeOnly = [self.openRepoAction, self.cloneRepoAction, self.newRepoAction,
                    homeSeparator, self.quickLaunchAction]
        leftSpacer = self.spacerAction()

        actions = [
            *homeOnly,
            self.backAction,
            self.forwardAction,
            self.workdirAction,
            self.headAction,
            self.separatorAction(),

            self.stashAction,
            self.branchAction,
            self.separatorAction(),
            self.fetchAction,
            self.pullAction,
            self.pushAction,
            leftSpacer,

            self.repoAction,
            self.spacerAction(),

            self.openInAction,
            self.themeAction,
            self.workspaceAction,

            self.separatorAction(),
            self.settingsAction,
        ]

        # Everything up to the spacer needs a repo - the nav arrows, the jump
        # buttons, stash/branch/fetch/pull/push - and so does "Open In". Taken
        # as a slice of the bar so separators travel with them and none is left
        # stranded. The spacer itself stays, so the right-hand group keeps its
        # place instead of sliding left on Home.
        repoScoped = [a for a in actions[:actions.index(leftSpacer)] if a not in homeOnly]
        repoScoped += [self.openInAction, self.repoAction]

        icons = {
            self.quickLaunchAction: "edit-find",
            self.openInAction: "terminal",
            self.stashAction: TaskBook.icons[tasks.NewStash],
            self.workdirAction: TaskBook.icons[tasks.JumpToUncommittedChanges],
            self.headAction: TaskBook.icons[tasks.JumpToHEAD],
        }
        return ToolbarArrangement(actions, repoScoped, homeOnly, icons)

    def centeredArrangement(self) -> ToolbarArrangement:
        """
        Where you go first (the sidebar, Quick Launch), then what you do to the
        repo (fetch, pull, push, stash), with the repo in the middle of the bar.
        Back, forward and Settings aren't on the bar: they have their menu
        items, keys and mouse buttons.
        """
        # Sized by centerRepoBox, so the box sits in the middle of the bar
        # whatever the widths of the groups on either side of it
        self.boxLeftSpacer = self.spacerAction(1)
        self.boxRightSpacer = self.spacerAction()
        sidebarGap = self.spacerAction(12)
        syncGap = self.spacerAction(14)
        stashGap = self.spacerAction(14)
        syncSeparators = [self.separatorAction(), self.separatorAction()]
        homeOnly = [self.openRepoAction, self.cloneRepoAction, self.newRepoAction]

        actions = [
            self.spacerAction(6),
            self.sidebarAction,
            sidebarGap,
            self.quickLaunchAction,
            *homeOnly,
            syncGap,
            self.fetchAction,
            syncSeparators[0],
            self.pullAction,
            syncSeparators[1],
            self.pushAction,
            stashGap,
            self.stashAction,
            self.boxLeftSpacer,

            self.repoBoxAction,
            self.branchAction,
            self.boxRightSpacer,

            # Until the sidebar has rows that go to the working directory and
            # to HEAD, these two wait on the right, out of the way of the
            # buttons that act on the repo.
            self.workdirAction,
            self.headAction,
            self.openInAction,
            self.themeAction,
            self.workspaceAction,
            self.spacerAction(6),
        ]

        repoScoped = [
            self.sidebarAction, sidebarGap, syncGap,
            self.fetchAction, *syncSeparators, self.pullAction, self.pushAction, stashGap,
            self.stashAction,
            self.branchAction,
            self.workdirAction, self.headAction,
            self.openInAction,
        ]

        icons = {
            self.quickLaunchAction: "quick-launch",
            self.openInAction: "open-in",
            self.stashAction: "git-stash",
            self.workdirAction: "sidebar-local-changes",
            self.headAction: "sidebar-all-commits",
        }
        return ToolbarArrangement(actions, repoScoped, homeOnly, icons)

    @property
    def homeActions(self) -> list[QAction]:
        return self.arrangements[self.arrangementName].homeOnly

    @property
    def repoScopedActions(self) -> list[QAction]:
        return self.arrangements[self.arrangementName].repoScoped

    def arrange(self, name: str):
        """Lay the bar out in a ToolbarLayout, if it isn't already."""
        if name == self.arrangementName:
            return

        arrangement = self.arrangements[name]
        self.arrangementName = name

        # The bar makes a new button for each action added back
        self.clear()
        for action, iconId in arrangement.icons.items():
            action.setProperty(ActionDef.IconProperty, iconId)
            action.setIcon(stockIcon(iconId, self.iconColorTable))
        self.addActions(arrangement.actions)

        for action in self.themeAction, self.openInAction, self.workspaceAction:
            button = self.widgetForAction(action)
            assert isinstance(button, QToolButton)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # Classic only: the Centered layout has the box instead
        repoButton = self.widgetForAction(self.repoAction)
        if isinstance(repoButton, QToolButton):
            repoButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            repoButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            repoButton.setObjectName("GFToolbarRepoButton")
        self.repoButton = repoButton

        sidebarButton = self.widgetForAction(self.sidebarAction)
        if sidebarButton is not None:
            sidebarButton.setObjectName("GFToolbarSidebarButton")

        self.setToolButtonStyle(self.toolButtonStyle())
        self.setRepoScopedActionsVisible(self.repoOpen)

    def centerRepoBox(self):
        """
        Put the Centered layout's box in the middle of the bar, as a title
        would be, rather than halfway between the groups on either side of it,
        which aren't the same width. The spacer on its left takes up the
        difference; the one on its right stretches as usual.

        Worked out from the items' widths rather than from where the bar last
        put them, which may be out of date while it lays itself out again.
        """
        if self.arrangementName != ToolbarLayout.Centered:
            return
        leftSpacer = self.widgetForAction(self.boxLeftSpacer)
        if leftSpacer is None:
            return

        layout = self.layout()
        margins = layout.contentsMargins()
        spacing = layout.spacing()

        def itemWidth(action: QAction) -> int:
            widget = self.widgetForAction(action)
            if widget is None or not action.isVisible():
                return 0
            hint = widget.sizeHint().width()
            return min(max(hint, widget.minimumWidth()), widget.maximumWidth()) + spacing

        actions = self.actions()
        spacerIndex = actions.index(self.boxLeftSpacer)
        leftOfBox = margins.left() + sum(itemWidth(a) for a in actions[:spacerIndex])
        fixedWidths = sum(itemWidth(a) for a in actions if a not in (self.boxLeftSpacer, self.boxRightSpacer))

        width = self.width() // 2 - RepoSummaryBox.Width // 2 - spacing - leftOfBox
        # Never at the expense of the buttons: the bar would push them into its overflow menu
        room = self.width() - margins.left() - margins.right() - fixedWidths - 2 * spacing - 8
        width = max(8, min(width, room))
        if width != leftSpacer.minimumWidth():
            leftSpacer.setFixedWidth(width)
            # The bar keeps its items' sizes: have it take the new width into account now
            layout.invalidate()
            layout.activate()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.centeringTimer.start()

    def event(self, event: QEvent) -> bool:
        # Something on the bar changed size (a label, a hidden button)
        if event.type() == QEvent.Type.LayoutRequest:
            self.centeringTimer.start()
        return super().event(event)

    def setRepoScopedActionsVisible(self, visible: bool):
        """
        Hide what needs a repo when there isn't one.

        On Home there is nothing to stash, no branch to push and no folder to
        reveal; offering them is an invitation to click something that can't work.
        """
        self.repoOpen = visible
        for action in self.repoScopedActions:
            action.setVisible(visible)
        for action in self.homeActions:
            action.setVisible(not visible)
        self.refreshRepoBox()

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

    def setRepoSummary(self, repoName: str, branchName: str, dirty: bool, detached: bool = False):
        """Say which repo is in front of you, and what it's checked out on."""
        self.repoSummary = (repoName, branchName, detached)
        self.refreshRepoBox()

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

    def refreshRepoBox(self):
        """
        The box names the repo and its branch. The tab already shows whether
        there's uncommitted work, so the box doesn't star the name. On Home, it
        names the workspace; an unloaded tab has nothing to say yet.
        """
        repoName, branchName, detached = self.repoSummary
        if not repoName:
            title = "" if self.repoOpen else (self.workspaceName or _("Home"))
            self.repoBox.setSummary(title)
            return
        if detached:
            branchName = _("Detached HEAD")
        tip = _("{0} on {1}", repoName, branchName) if branchName else repoName
        self.repoBox.setSummary(repoName, branchName, tip)

    def setRepoMenu(self, menu: QMenu):
        """The branch menu, opened by the repo button or by the box's branch."""
        self.repoAction.setMenu(menu)
        self.repoBox.branchButton.setMenu(menu)

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
        self.arrange(theme.toolbarLayout if theme else ToolbarLayout.Classic)
        toggleQssProperty(self, "compact", compact)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if compact
                                else Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        size = 14 if compact else (theme.toolbarIconSize if theme else 22)
        self.setIconSize(QSize(size, size))
        # The middle block keeps its text in both shapes: it's the label, not a button
        if self.repoButton is not None:
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

        # The box: the repo's name in bold at the normal size, the branch at the labels' size
        nameFont = QApplication.font()
        nameFont.setBold(True)
        self.repoBox.nameLabel.setFont(nameFont)
        self.repoBox.branchButton.setFont(labelFont)
        self.repoBox.branchButton.setIcon(stockIcon("git-branch"))
        self.repoBox.setCompact(compact)
        self.refreshRepoBox()

    def setDarkTheme(self, dark: bool):
        """Show which way the theme is set, right on the button."""
        self.darkTheme = dark
        iconId = "theme-dark" if dark else "theme-light"
        self.themeAction.setProperty(ActionDef.IconProperty, iconId)
        self.themeAction.setIcon(stockIcon(iconId, self.iconColorTable))
        self.themeAction.setToolTip(_("Dark theme") if dark else _("Light theme"))

    def setWorkspaceName(self, name: str):
        """Show which workspace is active - or that none is - right on the button."""
        self.workspaceName = name
        self.refreshRepoBox()
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

        iconOnly = []

        # Hide back/forward button text with ToolButtonTextBesideIcon
        if style != Qt.ToolButtonStyle.ToolButtonTextOnly:
            iconOnly += [self.backAction, self.forwardAction]

        if style == Qt.ToolButtonStyle.ToolButtonTextBesideIcon:
            iconOnly += [self.headAction, self.workdirAction, self.settingsAction, self.sidebarAction]

        # The sidebar toggle has no label, like the window buttons it sits next
        # to. Under the icons, a blank one keeps its icon on the same line as
        # its neighbors' icons; with text only, it needs its name.
        self.sidebarAction.setIconText(" " if style == Qt.ToolButtonStyle.ToolButtonTextUnderIcon else "")

        for action in iconOnly:
            button = self.widgetForAction(action)
            if isinstance(button, QToolButton):  # it may not be on the bar in this layout
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

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
