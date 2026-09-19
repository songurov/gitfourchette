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
    assert barItems(toolbar) == ["Quick Launch", "Open", "Clone", "New", "Theme", "Home"]
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
    assert barItems(toolbar) == ["Quick Launch", "Open", "Clone", "New", "Theme", "Home"]


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
