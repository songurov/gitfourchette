# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
The main toolbar in each of its layouts: Classic (Modern and the native
styles) and Centered (Neutral).
"""

import pytest

from gitfourchette import settings
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.themes import NEUTRAL_DARK, ThemeName
from gitfourchette.toolbox import ActionDef, stripAccelerators
from .util import *

NEUTRAL = f"{ThemeName.BuiltIn},dark,neutral"
MODERN = f"{ThemeName.BuiltIn},dark"


@pytest.fixture
def neutral(mainWindow):
    mainWindow.resize(1400, 800)  # room for the whole bar, box included
    GFApplication.applyPrefs(qtStyle=NEUTRAL, compactUi=False)
    yield
    GFApplication.applyPrefs(qtStyle="", compactUi=False)


def barItems(toolbar) -> list[str]:
    """What the bar shows, left to right: button names, "|" for a divider."""
    items = []
    for action in toolbar.actions():
        if not action.isVisible():
            continue
        if action.isSeparator():
            items.append("|")
        elif action is toolbar.repoBoxAction:
            items.append("<repo>")
        elif isinstance(action, QWidgetAction):
            continue  # a spacer
        elif action is toolbar.repoAction:
            items.append("<repo>")
        else:
            items.append(stripAccelerators(action.text()))
    return items


def testClassicLayoutIsUnchanged(tempDir, mainWindow):
    toolbar = mainWindow.mainToolBar
    mainWindow.openRepo(unpackRepo(tempDir))
    assert barItems(toolbar) == [
        "Back", "Forward", "Workdir", "HEAD", "|", "Stash", "Branch", "|", "Fetch", "Pull", "Push",
        "<repo>", "Open In", "Theme", "Home", "|", "Settings"]
    assert toolbar.widgetForAction(toolbar.sidebarAction) is None


def testNeutralPutsTheSyncButtonsFirstAndTheRepoInTheMiddle(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    mainWindow.openRepo(unpackRepo(tempDir))
    assert barItems(toolbar) == [
        "Sidebar", "Quick Launch", "Fetch", "|", "Pull", "|", "Push", "Stash",
        "<repo>", "Branch", "Workdir", "HEAD", "Open In", "Theme", "Home"]

    # Back, forward and Settings leave the bar, not the app
    for action in toolbar.backAction, toolbar.forwardAction, toolbar.settingsAction:
        assert toolbar.widgetForAction(action) is None
    assert findMenuAction(mainWindow.menuBar(), "view/navigate back")
    assert findMenuAction(mainWindow.menuBar(), "view/navigate forward")
    assert findMenuAction(mainWindow.menuBar(), "file/settings")

    # Back to Modern: the bar it always had
    GFApplication.applyPrefs(qtStyle=MODERN)
    assert barItems(toolbar)[:5] == ["Back", "Forward", "Workdir", "HEAD", "|"]
    assert toolbar.widgetForAction(toolbar.sidebarAction) is None
    assert toolbar.widgetForAction(toolbar.settingsAction) is not None


def testNeutralKeepsQuickLaunchOnHomeAndInARepo(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    # Home: the ways into a repo, after Quick Launch, which stays where it is
    assert barItems(toolbar) == ["Quick Launch", "Open", "Clone", "New", "<repo>", "Theme", "Home"]
    assert ["Open", "Clone", "New"] == [stripAccelerators(a.text()) for a in toolbar.homeActions if a.isVisible()]

    mainWindow.openRepo(unpackRepo(tempDir))
    assert barItems(toolbar)[:2] == ["Sidebar", "Quick Launch"]
    assert not any(a.isVisible() for a in toolbar.homeActions)

    toolbar.quickLaunchAction.trigger()
    from gitfourchette.forms.quicklaunch import QuickLaunch
    palettes = [p for p in mainWindow.findChildren(QuickLaunch) if p.isVisible()]
    assert len(palettes) == 1
    palettes[0].close()

    mainWindow.closeAllTabs()
    assert barItems(toolbar) == ["Quick Launch", "Open", "Clone", "New", "<repo>", "Theme", "Home"]


def testNeutralSidebarButtonHidesTheSidebar(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    QTest.qWait(0)
    button = toolbar.widgetForAction(toolbar.sidebarAction)
    assert button.isVisible()
    assert rw.sidebar.isVisible()
    # The menu item owns the key; the button's tooltip mentions it
    assert toolbar.sidebarAction.shortcut().isEmpty()
    shortcut = GlobalShortcuts.toggleSidebar[0].toString(QKeySequence.SequenceFormat.NativeText)
    assert shortcut in toolbar.sidebarAction.toolTip()

    button.click()
    assert not settings.prefs.showSidebar
    assert rw.sidebarContainer.isHidden()
    assert not findMenuAction(mainWindow.menuBar(), "view/show sidebar").isChecked()

    button.click()
    assert settings.prefs.showSidebar
    assert rw.sidebar.isVisible()


def testNeutralSidebarButtonsIconIsLevelWithTheOthers(tempDir, mainWindow, neutral):
    """It has no label, but its icon sits on the same line as the labelled buttons' icons."""
    toolbar = mainWindow.mainToolBar
    mainWindow.openRepo(unpackRepo(tempDir))
    sidebarButton = toolbar.widgetForAction(toolbar.sidebarAction)
    fetchButton = toolbar.widgetForAction(toolbar.fetchAction)
    assert "Sidebar" not in sidebarButton.text()
    assert sidebarButton.geometry().top() == fetchButton.geometry().top()
    assert sidebarButton.height() == fetchButton.height()

    # With text only, it says what it is
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    assert "Sidebar" == sidebarButton.text()


def testNeutralDrawsItsOwnToolbarIcons(tempDir, mainWindow, neutral):
    from gitfourchette.toolbox import iconbank

    toolbar = mainWindow.mainToolBar
    actions = [toolbar.quickLaunchAction, toolbar.openInAction, toolbar.stashAction,
               toolbar.workdirAction, toolbar.headAction]
    icons = [action.property(ActionDef.IconProperty) for action in actions]
    assert icons == ["quick-launch", "open-in", "git-stash", "sidebar-local-changes", "sidebar-all-commits"]
    assert iconbank.stockIconPath("git-stash").endswith("/neutral/git-stash.svg")

    GFApplication.applyPrefs(qtStyle=MODERN)
    icons = [action.property(ActionDef.IconProperty) for action in actions]
    assert icons == ["edit-find", "terminal", "git-stash-black", "git-workdir", "git-head"]


def testNeutralDividersAreLevelWithTheIcons(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    mainWindow.openRepo(unpackRepo(tempDir))
    QTest.qWait(0)

    fetchButton = toolbar.widgetForAction(toolbar.fetchAction)
    pullButton = toolbar.widgetForAction(toolbar.pullAction)
    image = toolbar.grab().toImage()
    ratio = image.devicePixelRatio()

    # The divider runs down the middle of the gap between Fetch and Pull
    x = (fetchButton.geometry().right() + pullButton.geometry().left()) // 2
    column = [image.pixelColor(int(x * ratio), int(y * ratio)).name() for y in range(toolbar.height())]
    drawn = [y for y, color in enumerate(column) if color == NEUTRAL_DARK.toolbarDivider]
    assert drawn, "no divider between Fetch and Pull"

    # From the top of the icons, and no further down than their bottom
    iconTop = fetchButton.geometry().top() + 3
    iconBottom = iconTop + toolbar.iconSize().height()
    assert iconTop - 2 <= drawn[0]
    assert drawn[-1] <= iconBottom
    assert drawn[-1] - drawn[0] >= 10


def testNeutralBoxNamesTheRepoAndItsBranch(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    box = toolbar.repoBox
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    QTest.qWait(0)

    assert toolbar.widgetForAction(toolbar.repoBoxAction) is box
    assert toolbar.widgetForAction(toolbar.repoAction) is None
    assert box.isVisible()
    assert (box.width(), box.height()) == (300, 40)
    assert "TestGitRepository" == box.nameLabel.text()
    assert box.nameLabel.font().bold()
    assert "master" == box.branchButton.text()
    assert "TestGitRepository on master" in box.toolTip()

    # The tab already shows uncommitted work: no star in the box
    writeFile(f"{wd}/dirty.txt", "work in progress")
    rw.refreshRepo()
    assert "TestGitRepository" == box.nameLabel.text()

    # The branch opens the branch menu
    assert box.branchButton.menu() is mainWindow.repoMenu2
    mainWindow.fillRepoButtonMenu()
    triggerMenuAction(mainWindow.repoMenu2, "no-parent")
    acceptQMessageBox(rw, "switch to")
    assert "no-parent" == box.branchButton.text()

    rw.repo.checkout_commit(rw.repo.head_commit_id)
    rw.refreshRepo()
    assert "Detached HEAD" == box.branchButton.text()


def testNeutralBoxNamesTheWorkspaceOnHome(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    box = toolbar.repoBox
    assert box.isVisible()
    assert "Home" == box.nameLabel.text()
    assert box.branchButton.isHidden()

    toolbar.setWorkspaceName("client work")
    assert "client work" == box.nameLabel.text()

    mainWindow.openRepo(unpackRepo(tempDir))
    assert "TestGitRepository" == box.nameLabel.text()
    assert not box.branchButton.isHidden()


def testNeutralBoxStaysInTheMiddleOfTheBar(tempDir, mainWindow, neutral):
    """The groups on either side of it differ in width; the box doesn't follow them."""
    toolbar = mainWindow.mainToolBar
    box = toolbar.repoBox

    def offCenter():
        QTest.qWait(50)  # the resize, then the spacer's new width
        center = box.mapTo(toolbar, box.rect().center()).x()
        return abs(center - toolbar.rect().center().x())

    mainWindow.resize(1400, 800)
    assert offCenter() <= 1

    mainWindow.openRepo(unpackRepo(tempDir))  # more buttons on the left than on Home
    assert offCenter() <= 1

    mainWindow.resize(1700, 800)
    assert offCenter() <= 1

    # A narrow window keeps every button on the bar rather than the box in the middle
    mainWindow.resize(1000, 800)
    QTest.qWait(50)
    stashButton = toolbar.widgetForAction(toolbar.stashAction)
    assert stashButton.isVisible()
    assert stashButton.geometry().right() < box.mapTo(toolbar, QPoint(0, 0)).x()


def testNeutralBoxIsOneLineInCompactMode(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    box = toolbar.repoBox
    mainWindow.openRepo(unpackRepo(tempDir))

    GFApplication.applyPrefs(compactUi=True)
    QTest.qWait(0)
    assert box.height() == 24
    assert box.nameLabel.geometry().center().y() == box.branchButton.geometry().center().y()
    assert box.nameLabel.geometry().right() < box.branchButton.geometry().left()

    GFApplication.applyPrefs(compactUi=False)
    QTest.qWait(0)
    assert box.height() == 40
    assert box.nameLabel.geometry().bottom() <= box.branchButton.geometry().top()


def testNeutralBoxBranchReadsOnTheBox(mainWindow, neutral):
    from gitfourchette.toolbox import contrastRatio
    branchColor = mainWindow.mainToolBar.repoBox.branchButton.palette().color(QPalette.ColorRole.ButtonText)
    assert branchColor.name() == NEUTRAL_DARK.repoBoxDim
    assert contrastRatio(branchColor, QColor(NEUTRAL_DARK.tabTrack)) >= 4.5


def testClassicLayoutHasNoBox(tempDir, mainWindow):
    toolbar = mainWindow.mainToolBar
    mainWindow.openRepo(unpackRepo(tempDir))
    assert toolbar.widgetForAction(toolbar.repoBoxAction) is None
    assert not toolbar.repoBox.isVisible()
    assert toolbar.repoButton is toolbar.widgetForAction(toolbar.repoAction)
    assert "TestGitRepository\nmaster" == toolbar.repoAction.text()


def testNeutralStashAndBranchAreSplitButtons(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    mainWindow.openRepo(unpackRepo(tempDir))
    split = QToolButton.ToolButtonPopupMode.MenuButtonPopup

    stashButton = toolbar.widgetForAction(toolbar.stashAction)
    branchButton = toolbar.widgetForAction(toolbar.branchAction)
    assert stashButton.popupMode() == split
    assert branchButton.popupMode() == split
    assert toolbar.stashAction.menu() is toolbar.stashMenu
    assert toolbar.branchAction.menu() is mainWindow.repoMenu2

    # Modern keeps plain buttons
    GFApplication.applyPrefs(qtStyle=MODERN)
    for action in toolbar.stashAction, toolbar.branchAction:
        assert toolbar.widgetForAction(action).popupMode() != split
        assert action.menu() is None

    # And back
    GFApplication.applyPrefs(qtStyle=NEUTRAL)
    assert toolbar.widgetForAction(toolbar.branchAction).popupMode() == split
    assert toolbar.branchAction.menu() is mainWindow.repoMenu2


def testNeutralStashButtonStillStashesOnClick(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/a/a1.txt", "work in progress")
    rw = mainWindow.openRepo(wd)
    QTest.qWait(0)

    toolbar.widgetForAction(toolbar.stashAction).click()
    dlg = findQDialog(rw, "new stash")
    dlg.reject()


def testNeutralStashMenuListsTheStashes(tempDir, mainWindow, neutral):
    from . import reposcenario

    toolbar = mainWindow.mainToolBar
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    writeFile(f"{wd}/a/a2.txt", "more")
    shell("git stash -m 'second one'", wd)
    rw = mainWindow.openRepo(wd)
    assert 2 == len(rw.repo.listall_stashes())

    mainWindow.fillStashMenu()
    menu = toolbar.stashMenu
    texts = [stripAccelerators(a.text()) for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Stash Changes…", "second one", "helloworld"]

    # Filling it again doesn't pile up submenus
    mainWindow.fillStashMenu()
    QTest.qWait(0)
    assert 2 == len([a for a in menu.actions() if a.menu()])

    triggerMenuAction(menu, "helloworld/apply")
    qmb = findQMessageBox(rw, "apply.*stash")
    qmb.checkBox().setChecked(True)  # and delete it
    qmb.accept()
    assert 1 == len(rw.repo.listall_stashes())
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt"]

    mainWindow.fillStashMenu()
    triggerMenuAction(menu, "second one/delete")
    acceptQMessageBox(rw, "really delete.+stash")
    assert 0 == len(rw.repo.listall_stashes())

    mainWindow.fillStashMenu()
    assert ["Stash Changes…"] == [stripAccelerators(a.text()) for a in menu.actions()]


def testNeutralBranchMenuSwitchesBranch(tempDir, mainWindow, neutral):
    toolbar = mainWindow.mainToolBar
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    menu = toolbar.branchAction.menu()
    menu.aboutToShow.emit()
    assert findMenuAction(menu, "master").isChecked()
    triggerMenuAction(menu, "no-parent")
    acceptQMessageBox(rw, "switch to")
    assert "no-parent" == rw.repoModel.homeBranch
