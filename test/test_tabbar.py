# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.forms.repostub import RepoStub
from gitfourchette.repowidget import RepoWidget
from gitfourchette.settings import TabBarClick
from .test_prefs import assertTranslatedInForkLanguages
from .util import *

NEUTRAL_DARK_STYLE = "gitfourchette-builtin,dark,neutral"
Left = QTabBar.ButtonPosition.LeftSide
Right = QTabBar.ButtonPosition.RightSide


@pytest.fixture
def neutralTheme(mainWindow):
    """Pill tabs, as the Neutral theme draws them."""
    GFApplication.applyPrefs(qtStyle=NEUTRAL_DARK_STYLE)
    yield
    GFApplication.applyPrefs(qtStyle="")


def hoverTab(tabBar: QTabBar, index: int):
    QTest.mouseMove(tabBar, tabBar.tabRect(index).center())
    QTest.qWait(0)


@pytest.mark.parametrize("pills", [False, True], ids=["usual", "pills"])
def testTabOverflow(tempDir, mainWindow, request, pills):
    if pills:
        request.getfixturevalue("neutralTheme")
    numRepos = 10
    tabWidget = mainWindow.tabs
    tabBar = mainWindow.tabs.tabs

    for i in range(numRepos):
        wd = unpackRepo(tempDir, renameTo=f"RepoCopy{i:04}")
        mainWindow.openRepo(wd)
        QTest.qWait(1)

        if i <= 2:  # assume no overflow when there are few repos
            assert not tabWidget.overflowGradient.isVisible()
            assert not tabWidget.overflowButton.isVisible()

    mainWindow.resize(640, 480)  # make sure it's narrow enough for overflow
    QTest.qWait(1)

    assert tabWidget.currentIndex() == numRepos - 1
    assert tabWidget.overflowGradient.isVisible()
    assert tabWidget.overflowButton.isVisible()

    # Scroll
    assert not tabBar.visibleRegion().contains(tabBar.tabRect(0))
    assert tabBar.visibleRegion().contains(tabBar.tabRect(numRepos-1))
    for _dummy in range(16):
        postMouseWheelEvent(tabBar, 120)
        QTest.qWait(0)
    assert tabBar.visibleRegion().contains(tabBar.tabRect(0))
    assert not tabBar.visibleRegion().contains(tabBar.tabRect(numRepos-1))

    # Test overflow menu
    mainWindow.tabs.overflowButton.click()
    menu: QMenu = mainWindow.findChild(QMenu, "QTW2OverflowMenu")
    triggerMenuAction(menu, "RepoCopy0002")
    menu.close()
    assert mainWindow.tabs.currentIndex() == 2

    if pills:
        # The "+" stays in reach, right of the overflow button, and the track keeps its height
        assert tabWidget.newTabButton.isVisible()
        assert tabWidget.newTabButton.geometry().left() > tabWidget.overflowButton.geometry().right()
        assert tabWidget.tabScrollArea.height() == 28


def testTabOverflowSingleTab(tempDir, mainWindow):
    from gitfourchette import settings

    wd = unpackRepo(tempDir)
    settings.history.setRepoNickname(wd, "ridiculously_long_" * 16)

    mainWindow.resize(640, 480)  # make sure it's narrow enough for overflow

    mainWindow.openRepo(wd)
    QTest.qWait(1)
    assert not mainWindow.tabs.overflowButton.isVisible()

    GFApplication.applyPrefs(autoHideTabs=True)
    QTest.qWait(1)
    assert not mainWindow.tabs.overflowButton.isVisible()


@pytest.mark.parametrize("click", ["middle", "double"])
@pytest.mark.parametrize("action", TabBarClick)
def testTabSpecialClick(tempDir, mainWindow, click, action):
    GFApplication.applyPrefs(**{f"{click}ClickTabBar": action})

    if action == "terminal":
        editorPath = getTestDataPath("editor-shim.py")
        scratchPath = f"{tempDir.name}/scratch file.txt"
        GFApplication.applyPrefs(terminal=f'"{editorPath}" "{scratchPath}" "hello world" $COMMAND')

    wd0 = unpackRepo(tempDir, renameTo="repo0")
    wd1 = unpackRepo(tempDir, renameTo="repo1")

    mainWindow._openRepo(wd0, foreground=True)  # RepoWidget
    mainWindow._openRepo(wd1, foreground=False)  # RepoStub
    assert isinstance(mainWindow.tabs.widget(0), RepoWidget)
    assert isinstance(mainWindow.tabs.widget(1), RepoStub)

    tabBar = mainWindow.tabs.tabs
    assert tabBar.count() == 2

    for tabIndex in range(tabBar.count() - 1, -1, -1):
        tab = mainWindow.tabs.widget(tabIndex)
        pos = tabBar.tabRect(tabIndex).center()
        wd = tab.workdir

        with MockDesktopServicesContext() as services:
            mouseSpecialClick(tabBar, click, pos=pos)
            QTest.qWait(0)

        assert bool(services.urls) == (action == "folder")

        if action == TabBarClick.Nothing:
            pass
        elif action == TabBarClick.Close:
            assert not any(Path(wd).samefile(tab.workdir) for tab in mainWindow.tabs.widgets())
        elif action == TabBarClick.Folder:
            assert Path(wd).samefile(services.lastUrlAsLocalFile())
        elif action == TabBarClick.Terminal:
            waitForFile(scratchPath)
            scratchText = readTextFile(scratchPath, unlink=True)
            assert "hello world" in scratchText
            assert "terminal" in scratchText
        else:
            raise NotImplementedError(f"unknown action {action}")

    assert tabBar.count() == (0 if action == "close" else 2)


def testCloseLastTabAfterResizingWindow(tempDir, mainWindow):
    # Closing the last tab brings back the home page. If the window was resized
    # in the meantime, the home mascot renders the welcome text again to plan
    # its walk. Rendering delivers the pending resize events of every widget in
    # the window - including those of the closed RepoWidget, which lingers until
    # its deferred deletion, long after it has let go of its diff gutter.
    assert settings.prefs.homeMascot

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    # Nothing to diff in a clean worktree: the diff view has never been shown or resized
    assert rw.diffView.testAttribute(Qt.WidgetAttribute.WA_PendingResizeEvent)

    mainWindow.resize(mainWindow.width() + 200, mainWindow.height() + 100)
    QTest.qWait(0)

    mainWindow.closeCurrentTab()
    QTest.qWait(0)  # the home page comes back here
    assert mainWindow.tabs.count() == 0

    errorBoxes = [box.text() for box in mainWindow.findChildren(QMessageBox) if box.isVisible()]
    assert not errorBoxes, "the closed repo must not raise an exception while the home page comes back"


# -----------------------------------------------------------------------------
# Pill tabs (the Neutral theme)


def testNeutralTabsArePillsWithTheStatusAtTheRightEnd(tempDir, mainWindow, neutralTheme):
    from gitfourchette.toolbox.qtabwidget2 import QTabBar2Badge, QTabBar2CloseButton
    from gitfourchette.themes import NEUTRAL_DARK

    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)
    tabWidget = mainWindow.tabs
    tabBar = tabWidget.tabs
    assert "git-status-unpushed" == tabWidget.tabStatusIcon(0)  # the fixture is ahead of its upstream

    assert tabBar.pillMode
    # The status moves out of the icon slot, into a badge at the right end of the tab
    assert tabBar.tabIcon(0).isNull()
    badge = tabBar.tabButton(0, Right)
    assert isinstance(badge, QTabBar2Badge)
    assert badge.iconKey == "git-status-unpushed"
    assert badge.isVisible()
    assert badge.geometry().left() > tabBar.tabRect(0).center().x()
    # Qt's close button would sit where the badge is; ours is at the left end, out of sight until hovered
    assert not tabBar.tabsClosable()
    closeButton = tabBar.tabButton(0, Left)
    assert isinstance(closeButton, QTabBar2CloseButton)
    assert closeButton.geometry().right() < tabBar.tabRect(0).center().x()
    assert not closeButton.isVisible()

    # The track and its pill, measured on the reference: 28 px and 24 px tall
    assert tabBar.height() == 28
    assert tabBar.tabRect(0).height() == 28
    # Tab names two points smaller than the rest of the text, with a line under the strip
    assert tabBar.font().pointSizeF() == QApplication.font().pointSizeF() - NEUTRAL_DARK.tabLabelDrop
    assert tabWidget.topWidget.lineColor.name() == NEUTRAL_DARK.border
    assert tabWidget.topWidget.height() == 28 + 8

    # Modern keeps the tabs it always had: the status in the icon slot, Qt's close button
    GFApplication.applyPrefs(qtStyle="gitfourchette-builtin,dark")
    assert not tabBar.pillMode
    assert tabBar.tabsClosable()
    assert not tabBar.tabIcon(0).isNull()
    assert not isinstance(tabBar.tabButton(0, Right), QTabBar2Badge)
    assert not isinstance(tabBar.tabButton(0, Left), QTabBar2CloseButton)
    assert tabBar.font().pointSizeF() == QApplication.font().pointSizeF()
    assert not tabWidget.topWidget.lineColor.isValid()
    assert not tabWidget.newTabButton.isVisible()

    # And back
    GFApplication.applyPrefs(qtStyle=NEUTRAL_DARK_STYLE)
    assert tabBar.tabIcon(0).isNull()
    assert tabBar.tabBadge(0) == "git-status-unpushed"


def testPillTabNamesStaySmallerWhenTheStyleSheetIsReapplied(tempDir, mainWindow, neutralTheme):
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)
    tabBar = mainWindow.tabs.tabs
    smaller = QApplication.font().pointSizeF() - 2
    assert tabBar.font().pointSizeF() == smaller

    # Restyling puts back the font the tabs had when they were first styled
    GFApplication.applyPrefs(expandingTabs=False)
    assert tabBar.font().pointSizeF() == smaller
    GFApplication.applyPrefs(expandingTabs=True)
    assert tabBar.font().pointSizeF() == smaller

    # Compact mode shrinks everything; the tab names stay two points under that
    GFApplication.applyPrefs(compactUi=True)
    try:
        assert tabBar.font().pointSizeF() == QApplication.font().pointSizeF() - 2
        assert tabBar.font().pointSizeF() < smaller
    finally:
        GFApplication.applyPrefs(compactUi=False)


def testPillTabCloseButtonShowsUnderThePointerAndCloses(tempDir, mainWindow, neutralTheme):
    wd0 = unpackRepo(tempDir, renameTo="repo0")
    wd1 = unpackRepo(tempDir, renameTo="repo1")
    mainWindow.openRepo(wd0)
    mainWindow.openRepo(wd1)
    tabBar = mainWindow.tabs.tabs
    assert mainWindow.tabs.currentIndex() == 1

    # Not even on the current tab, until the pointer comes
    assert not tabBar.tabButton(0, Left).isVisible()
    assert not tabBar.tabButton(1, Left).isVisible()

    hoverTab(tabBar, 0)
    assert tabBar.hoveredIndex == 0
    assert tabBar.tabButton(0, Left).isVisible()
    assert not tabBar.tabButton(1, Left).isVisible()

    hoverTab(tabBar, 1)
    assert not tabBar.tabButton(0, Left).isVisible()
    assert tabBar.tabButton(1, Left).isVisible()

    assert tabBar.tabButton(1, Left).toolTip() == "Close tab"
    assertTranslatedInForkLanguages("Close tab")

    # Leaving the tabs puts it away
    QTest.mouseMove(mainWindow.tabs.stacked, QPoint(10, 10))
    QTest.qWait(0)
    assert tabBar.hoveredIndex == -1
    assert not tabBar.tabButton(1, Left).isVisible()

    # Clicking it closes that tab, even the one that isn't current
    hoverTab(tabBar, 0)
    QTest.mouseClick(tabBar.tabButton(0, Left), Qt.MouseButton.LeftButton)
    assert mainWindow.tabs.count() == 1
    assert os.path.samefile(mainWindow.tabs.widget(0).workdir, wd1)


def testPillTabCloseButtonHonorsThePref(tempDir, mainWindow, neutralTheme):
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)
    tabBar = mainWindow.tabs.tabs

    GFApplication.applyPrefs(tabCloseButton=False)
    try:
        hoverTab(tabBar, 0)
        assert tabBar.hoveredIndex == 0
        assert not tabBar.tabButton(0, Left).isVisible()
        assert not tabBar.tabsClosable()  # and Qt's own doesn't come back either
    finally:
        GFApplication.applyPrefs(tabCloseButton=True)

    hoverTab(tabBar, 0)
    assert tabBar.tabButton(0, Left).isVisible()


@pytest.mark.parametrize("click", ["middle", "double"])
def testPillTabsStillCloseOnClick(tempDir, mainWindow, neutralTheme, click):
    GFApplication.applyPrefs(**{f"{click}ClickTabBar": TabBarClick.Close})
    mainWindow.openRepo(unpackRepo(tempDir, renameTo="repo0"))
    mainWindow.openRepo(unpackRepo(tempDir, renameTo="repo1"))
    tabBar = mainWindow.tabs.tabs
    mouseSpecialClick(tabBar, click, pos=tabBar.tabRect(0).center())
    QTest.qWait(0)
    assert mainWindow.tabs.count() == 1


def testPillTabBadgeFollowsItsTab(tempDir, mainWindow, neutralTheme):
    clean = unpackRepo(tempDir, renameTo="clean")
    shell("git reset --hard origin/master", clean)
    ahead = unpackRepo(tempDir, renameTo="ahead")
    mainWindow.openRepo(clean)
    mainWindow.openRepo(ahead)
    tabWidget = mainWindow.tabs
    tabBar = tabWidget.tabs
    assert [tabBar.tabBadge(0), tabBar.tabBadge(1)] == ["", "git-status-unpushed"]

    # Dragging a tab around takes its badge along
    start, end = tabBar.tabRect(1).center(), tabBar.tabRect(0).center()
    QTest.mousePress(tabBar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 11):
        QTest.mouseMove(tabBar, start + (end - start) * step / 10)
        QTest.qWait(10)
    QTest.mouseRelease(tabBar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    waitUntilTrue(lambda: tabBar.tabBadge(0) == "git-status-unpushed")
    assert tabBar.tabBadge(1) == ""
    assert os.path.samefile(tabWidget.widget(0).workdir, ahead)
    waitUntilTrue(lambda: tabBar.tabRect(0).contains(tabBar.tabButton(0, Right).geometry()))
    assert tabBar.tabButton(0, Right).isVisible()

    # A tab asking for attention says so in its badge, and gives it back when you look
    tabWidget.setCurrentIndex(1)
    tabWidget.requestAttention(0)
    assert tabBar.tabBadge(0) == "urgent-tab"
    assert tabBar.tabIcon(0).isNull()
    tabWidget.setCurrentIndex(0)
    assert tabBar.tabBadge(0) == "git-status-unpushed"

    # A new status lands in the badge too
    writeFile(f"{ahead}/newfile.txt", "work in progress")
    mainWindow.currentRepoWidget().refreshRepo()
    assert tabBar.tabBadge(0) == "git-status-dirty-unpushed"


def testPillTabSeparatorsSkipTheLitTabs(tempDir, mainWindow, neutralTheme):
    from gitfourchette.themes import NEUTRAL_DARK
    for i in range(4):
        mainWindow.openRepo(unpackRepo(tempDir, renameTo=f"repo{i}"))
    tabWidget = mainWindow.tabs
    tabBar = tabWidget.tabs
    tabWidget.setCurrentIndex(1)
    QTest.mouseMove(tabWidget.stacked, QPoint(10, 10))
    QTest.qWait(0)

    def separators():
        image = tabBar.grab().toImage()
        y = tabBar.height() // 2
        return [i for i in range(1, tabBar.count())
                if image.pixelColor(tabBar.tabRect(i).left(), y).name() == NEUTRAL_DARK.tabSeparator]

    # Only between two tabs that are neither current nor under the pointer
    assert separators() == [3]
    hoverTab(tabBar, 3)
    assert separators() == []
    tabWidget.setCurrentIndex(0)
    hoverTab(tabBar, 0)
    assert separators() == [2, 3]


# -----------------------------------------------------------------------------
# The round "+" after pill tabs

def openNewTabMenuAction(mainWindow, pattern: str):
    tabWidget = mainWindow.tabs
    tabWidget.newTabButton.click()
    menu = tabWidget.newTabMenu
    assert menu.isVisible()
    triggerMenuAction(menu, pattern)
    menu.close()


def testNewTabButtonFollowsTheTrack(tempDir, mainWindow, neutralTheme):
    mainWindow.openRepo(unpackRepo(tempDir, renameTo="first"))
    tabWidget = mainWindow.tabs
    button = tabWidget.newTabButton
    assert button.isVisible()
    assert button.size() == QSize(28, 28)  # as tall as the track, and round
    assert button.geometry().left() > tabWidget.tabScrollArea.geometry().right()
    assert button.geometry().top() == tabWidget.tabScrollArea.geometry().top()

    # Nothing of the sort with the usual tabs
    GFApplication.applyPrefs(qtStyle="gitfourchette-builtin,dark")
    assert not button.isVisible()
    waitUntilTrue(lambda: tabWidget.topWidget.height() == tabWidget.tabs.height())
    GFApplication.applyPrefs(qtStyle=NEUTRAL_DARK_STYLE)
    assert button.isVisible()

    # A lone tab that autoHideTabs hides takes the "+" and the band's room along
    GFApplication.applyPrefs(autoHideTabs=True)
    assert not tabWidget.tabs.isVisibleTo(tabWidget)
    assert not button.isVisible()
    waitUntilTrue(lambda: tabWidget.topWidget.height() == 0)
    mainWindow.openRepo(unpackRepo(tempDir, renameTo="second"))
    assert button.isVisible()
    waitUntilTrue(lambda: tabWidget.topWidget.height() == 28 + 8)


def testNewTabButtonMenu(tempDir, mainWindow, neutralTheme):
    mainWindow.openRepo(unpackRepo(tempDir))
    tabWidget = mainWindow.tabs
    tabWidget.newTabButton.click()
    menu = tabWidget.newTabMenu
    assert menu.isVisible()
    texts = [stripAccelerators(a.text()) for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Open Repository…", "Clone Repository…", "New Repository…",
                     "Open Recent", "Workspace", "Home"]
    # The same lists as the File menu's
    assert findMenuAction(menu, "open recent").menu() is mainWindow.recentMenu
    assert findMenuAction(menu, "workspace").menu() is mainWindow.workspaceMenu
    menu.close()
    assert tabWidget.newTabButton.toolTip() == "Open, clone or create a repository"
    assertTranslatedInForkLanguages("Open, clone or create a repository")

    openNewTabMenuAction(mainWindow, "clone repository")
    dlg = findQDialog(mainWindow, "clone")
    assert dlg.ui.urlEdit.currentText() == ""
    dlg.reject()


def testNewTabButtonOpensCreatesAndGoesHome(tempDir, mainWindow, neutralTheme):
    mainWindow.openRepo(unpackRepo(tempDir, renameTo="first"))
    other = unpackRepo(tempDir, renameTo="other")

    openNewTabMenuAction(mainWindow, "open repository")
    acceptQFileDialog(mainWindow, "open", other)
    assert mainWindow.tabs.count() == 2
    assert os.path.samefile(other, mainWindow.currentRepoWidget().workdir)

    fresh = os.path.realpath(tempDir.name + "/fresh")
    os.makedirs(fresh)
    openNewTabMenuAction(mainWindow, "new repository")
    acceptQFileDialog(mainWindow, "new repo", fresh)
    assert mainWindow.tabs.count() == 3
    assert fresh == os.path.normpath(mainWindow.currentRepoWidget().repo.workdir)

    # Home is Home: every tab closes
    openNewTabMenuAction(mainWindow, "home")
    assert mainWindow.tabs.count() == 0
