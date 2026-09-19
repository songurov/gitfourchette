# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import json
from pathlib import Path

import pytest

from gitfourchette import settings
from gitfourchette.repowidget import RepoWidget
from .test_prefs import assertTranslatedInForkLanguages
from .util import *

NEUTRAL_DARK_STYLE = "gitfourchette-builtin,dark,neutral"
MODERN_DARK_STYLE = "gitfourchette-builtin,dark"

# Splitters a user can drag while looking at the working directory
VISIBLE_SPLITTERS = ["Split_Side", "Split_Central", "Split_DiffArea", "Split_Staging"]


def splitterSizes(rw: RepoWidget) -> dict[str, list[int]]:
    return {s.objectName(): s.sizes() for s in rw.splittersToSave if s.objectName() in VISIBLE_SPLITTERS}


def dragEverySplitter(rw: RepoWidget):
    """Move each visible splitter's handle 40 px, as a user would, so the session remembers it."""
    for splitter in rw.splittersToSave:
        if splitter.objectName() not in VISIBLE_SPLITTERS:
            continue
        splitter.moveSplitter(splitter.sizes()[0] + 40, 1)
        QTest.qWait(0)  # let the panes inside it settle before dragging the next one


def assertSizesClose(actual: dict[str, list[int]], expected: dict[str, list[int]]):
    assert actual.keys() == expected.keys()
    for name, sizes in expected.items():
        assert all(abs(a - e) <= 1 for a, e in zip(actual[name], sizes, strict=True)), \
            f"{name}: {actual[name]} != {sizes}"


@pytest.fixture
def restoreTheme():
    yield
    GFApplication.applyPrefs(qtStyle="")


@pytest.mark.parametrize("style", [
    # The default style leaves the split between unstaged and staged files to Qt
    "",
    # Neutral sizes it itself, 70/30 with the commit form out of the file lists
    NEUTRAL_DARK_STYLE,
])
def testResetLayoutGivesEveryPaneItsDefaultSize(tempDir, mainWindow, restoreTheme, style):
    if style:
        GFApplication.applyPrefs(qtStyle=style, commitFormPlacement=settings.CommitFormPlacement.BottomBar)
    mainWindow.resize(1400, 900)
    rw1 = mainWindow.openRepo(unpackRepo(tempDir, renameTo="repo1"))
    rw2 = mainWindow.openRepo(unpackRepo(tempDir, renameTo="repo2"))
    defaults = splitterSizes(rw2)

    dragEverySplitter(rw2)
    moved = splitterSizes(rw2)
    for name in VISIBLE_SPLITTERS:
        assert moved[name] != defaults[name], f"{name} didn't move"
        assert RepoWidget.sharedSplitterSizes[name] == moved[name]

    # The other tab takes on the dragged sizes as it comes up
    mainWindow.tabs.setCurrentIndex(mainWindow.tabs.indexOf(rw1))
    assertSizesClose(splitterSizes(rw1), moved)

    triggerMenuAction(mainWindow.menuBar(), "view/reset layout")

    # Every tab is back to the sizes a new tab starts with, the one in the background included
    assertSizesClose(splitterSizes(rw1), defaults)
    mainWindow.tabs.setCurrentIndex(mainWindow.tabs.indexOf(rw2))
    assertSizesClose(splitterSizes(rw2), defaults)
    assert not RepoWidget.sharedSplitterSizes


def testResetLayoutForgetsTheSizesInTheSession(tempDir, mainWindow):
    mainWindow.resize(1400, 900)
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    defaults = splitterSizes(rw)
    dragEverySplitter(rw)

    mainWindow.saveSession(writeNow=True)
    session = settings.Session()
    session.load()
    assert set(VISIBLE_SPLITTERS) <= session.splitterSizes.keys()

    triggerMenuAction(mainWindow.menuBar(), "view/reset layout")
    mainWindow.saveSession(writeNow=True)
    session = settings.Session()
    session.load()
    assert not session.splitterSizes

    # A tab reopened after that starts out with the default sizes
    mainWindow.closeAllTabs()
    rw = mainWindow.openRepo(wd)
    assertSizesClose(splitterSizes(rw), defaults)


def testResetLayoutWorksWithoutARepo(mainWindow):
    RepoWidget.sharedSplitterSizes["Split_Side"] = [400, 1000]
    action = findMenuAction(mainWindow.menuBar(), "view/reset layout")
    assert action.isEnabled()
    action.trigger()
    assert not RepoWidget.sharedSplitterSizes


def testResetLayoutIsTranslated(qapp):
    assertTranslatedInForkLanguages("Reset &Layout", "Give every pane its default size again")


def sidebarWidth(rw: RepoWidget) -> int:
    return rw.sideSplitter.sizes()[0]


def fileListsWidth(rw: RepoWidget) -> int:
    return rw.findChild(QSplitter, "Split_DiffArea").sizes()[0]


def unstagedShare(rw: RepoWidget) -> float:
    unstaged, staged = rw.findChild(QSplitter, "Split_Staging").sizes()
    return unstaged / (unstaged + staged)


def savedLayoutVersion(window) -> int:
    """Save the session and read back the layout version it was saved under."""
    window.saveSession(writeNow=True)
    path = Path(settings.Session().getParentDir()) / settings.Session._filename
    return json.loads(path.read_text(encoding="utf-8")).get("layoutVersion", 0)


def openWithCommitFormUnderTheDiff(tempDir, mainWindow, style, name="repo") -> RepoWidget:
    # With the commit form out of the file lists, their width is the theme's alone
    GFApplication.applyPrefs(qtStyle=style, commitFormPlacement=settings.CommitFormPlacement.BottomBar)
    mainWindow.resize(1400, 900)
    rw = mainWindow.openRepo(unpackRepo(tempDir, renameTo=name))
    QTest.qWait(0)
    return rw


@pytest.mark.parametrize(["style", "width"], [(NEUTRAL_DARK_STYLE, 296), (MODERN_DARK_STYLE, 220), ("", 220)])
def testSidebarStartsAtTheThemesWidth(tempDir, mainWindow, restoreTheme, style, width):
    mainWindow.resize(1400, 900)
    GFApplication.applyPrefs(qtStyle=style)
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    assert rw.sidebar.parentWidget().width() == width
    assert sidebarWidth(rw) == width


def testSwitchingToNeutralBringsItsLayoutOnce(tempDir, mainWindow, restoreTheme):
    rw = openWithCommitFormUnderTheDiff(tempDir, mainWindow, MODERN_DARK_STYLE)
    assert (sidebarWidth(rw), fileListsWidth(rw)) == (220, 260)
    assert savedLayoutVersion(mainWindow) == 0

    # The first time Neutral shows, the panes it sizes take on its sizes
    GFApplication.applyPrefs(qtStyle=NEUTRAL_DARK_STYLE)
    QTest.qWait(0)
    assert (sidebarWidth(rw), fileListsWidth(rw)) == (296, 360)
    assert unstagedShare(rw) == pytest.approx(.7, abs=.01)
    assert savedLayoutVersion(mainWindow) == settings.LAYOUT_VERSION

    # Only that once: a size picked afterwards stays, in either look
    rw.sideSplitter.moveSplitter(250, 1)
    GFApplication.applyPrefs(qtStyle=MODERN_DARK_STYLE)
    assert sidebarWidth(rw) == 250
    GFApplication.applyPrefs(qtStyle=NEUTRAL_DARK_STYLE)
    assert sidebarWidth(rw) == 250


def testResetLayoutFollowsTheCurrentTheme(tempDir, mainWindow, restoreTheme):
    rw = openWithCommitFormUnderTheDiff(tempDir, mainWindow, NEUTRAL_DARK_STYLE)
    assert (sidebarWidth(rw), fileListsWidth(rw)) == (296, 360)

    # Switching looks leaves the sizes alone...
    GFApplication.applyPrefs(qtStyle=MODERN_DARK_STYLE)
    assert (sidebarWidth(rw), fileListsWidth(rw)) == (296, 360)

    # ...until the layout is reset: then the current look's sizes, as in a new tab
    triggerMenuAction(mainWindow.menuBar(), "view/reset layout")
    QTest.qWait(0)
    assert (sidebarWidth(rw), fileListsWidth(rw)) == (220, 260)
    modernShare = unstagedShare(rw)
    newTab = mainWindow.openRepo(unpackRepo(tempDir, renameTo="other"))
    QTest.qWait(0)
    assert modernShare == pytest.approx(unstagedShare(newTab), abs=.01)
    mainWindow.tabs.setCurrentIndex(mainWindow.tabs.indexOf(rw))

    GFApplication.applyPrefs(qtStyle=NEUTRAL_DARK_STYLE)
    assert (sidebarWidth(rw), fileListsWidth(rw)) == (220, 260)
    triggerMenuAction(mainWindow.menuBar(), "view/reset layout")
    QTest.qWait(0)
    assert (sidebarWidth(rw), fileListsWidth(rw)) == (296, 360)
    assert unstagedShare(rw) == pytest.approx(.7, abs=.01)


def relaunch(window, prefs: dict, sessionChanges: dict, deleteWindow=False):
    """
    Quit, edit the prefs and the session the way an earlier build or run left
    them, and launch again. Returns the new MainWindow. Pass deleteWindow for a
    window that relaunch made; the fixture's own goes to closeRelaunched.
    """
    app = GFApplication.instance()
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    window.close()  # saves the session, geometry included
    app.endSession(clearTempDir=False)
    app.mainWindow = None
    if deleteWindow:
        gone = []
        window.destroyed.connect(lambda: gone.append(True))
        window.deleteLater()
        waitUntilTrue(lambda: gone)
    QTest.qWait(0)

    configDir = Path(settings.Session().getParentDir())
    sessionPath = configDir / settings.Session._filename
    session = json.loads(sessionPath.read_text(encoding="utf-8"))
    session.update(sessionChanges)
    session = {k: v for k, v in session.items() if v is not None}
    sessionPath.write_text(json.dumps(session), encoding="utf-8")
    (configDir / settings.Prefs._filename).write_text(json.dumps(prefs), encoding="utf-8")

    app.beginSession()
    return waitUntilTrue(lambda: app.mainWindow)


def closeRelaunched(originalWindow):
    app = GFApplication.instance()
    app.mainWindow.close()
    app.mainWindow.deleteLater()
    waitUntilTrue(lambda: not app.mainWindow)
    app.mainWindow = originalWindow  # let the fixture delete it


# Sizes saved by a build from before Neutral's layout. A relaunched window
# can't be larger than the offscreen screen (800 x 600), hence the small sizes.
OLD_SIZES = {
    "Split_Side": [250, 548],
    "Split_Central": [300, 500],
    "Split_DiffArea": [500, 548],
    "Split_Staging": [150, 250],
    "Split_CommitTab": [100, 200],
}

# "migrations" says the prefs already moved to Neutral once, so Modern stays Modern
NEUTRAL_PREFS = {"qtStyle": NEUTRAL_DARK_STYLE, "migrations": ["neutralTheme"]}
MODERN_PREFS = {"qtStyle": MODERN_DARK_STYLE, "migrations": ["neutralTheme"]}


@pytest.mark.parametrize(["prefs", "layoutVersion", "keptSizes", "savedVersion"], [
    # A session from before, opened in Neutral: the panes Neutral sizes take on its
    # sizes; the graph over the diff and the rest keep what you made of them
    (NEUTRAL_PREFS, None, ["Split_Central", "Split_CommitTab"], 1),
    # Already caught up: the sizes are the user's own
    (NEUTRAL_PREFS, 1, list(OLD_SIZES), 1),
    # Modern's defaults didn't change: the sizes stay, and the catching up waits for Neutral
    (MODERN_PREFS, None, list(OLD_SIZES), 0),
])
def testOldSessionOpensWithNeutralsLayoutOnce(tempDir, mainWindow, prefs, layoutVersion, keptSizes, savedVersion):
    wd = unpackRepo(tempDir)
    mainWindow.resize(1400, 900)
    mainWindow.openRepo(wd)

    newWindow = relaunch(mainWindow, prefs, {"splitterSizes": OLD_SIZES, "layoutVersion": layoutVersion})
    try:
        rw = waitForRepoWidget(newWindow)
        assert sorted(RepoWidget.sharedSplitterSizes) == sorted(keptSizes)
        for name in keptSizes:
            assert RepoWidget.sharedSplitterSizes[name] == OLD_SIZES[name]
        assert sidebarWidth(rw) == (250 if "Split_Side" in keptSizes else 296)
        assert savedLayoutVersion(newWindow) == savedVersion
    finally:
        closeRelaunched(mainWindow)


def testModernSessionTakesNeutralsLayoutWhenItFirstLaunchesInNeutral(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.resize(1400, 900)
    mainWindow.openRepo(wd)

    modernWindow = relaunch(mainWindow, MODERN_PREFS, {"splitterSizes": OLD_SIZES, "layoutVersion": None})
    try:
        assert sidebarWidth(waitForRepoWidget(modernWindow)) == 250

        # Quit in Modern, pick Neutral, launch again: the session as Modern left it
        neutralWindow = relaunch(modernWindow, NEUTRAL_PREFS, {}, deleteWindow=True)
        assert sidebarWidth(waitForRepoWidget(neutralWindow)) == 296
        assert sorted(RepoWidget.sharedSplitterSizes) == ["Split_Central", "Split_CommitTab"]
    finally:
        closeRelaunched(mainWindow)


def testTheOwnersSessionMovesWithHisPrefs(tempDir, mainWindow):
    """
    prefs.json and session.json as this build's owner had them: the prefs move
    from Modern to Neutral at the same launch, and the layout with them.
    """
    wd = unpackRepo(tempDir, renameTo="repo")
    mainWindow.resize(1400, 900)
    mainWindow.openRepo(wd)

    prefs = {"qtStyle": MODERN_DARK_STYLE, "commitFormPlacement": "bottom-bar", "_version": "1.11.0"}
    sizes = {"Split_Side": [220, 1179], "Split_Central": [420, 380], "Split_DiffArea": [586, 813]}
    newWindow = relaunch(mainWindow, prefs, {"splitterSizes": sizes, "layoutVersion": None})
    try:
        rw = waitForRepoWidget(newWindow)
        assert settings.prefs.qtStyle == NEUTRAL_DARK_STYLE
        assert sidebarWidth(rw) == 296
        assert RepoWidget.sharedSplitterSizes == {"Split_Central": [420, 380]}

        # His file lists are those of a new tab in Neutral
        # (not 360 px wide in a window the size of the offscreen screen)
        newTab = newWindow.openRepo(unpackRepo(tempDir, renameTo="other"))
        QTest.qWait(0)
        assert fileListsWidth(rw) == fileListsWidth(newTab)
        assert unstagedShare(rw) == pytest.approx(unstagedShare(newTab), abs=.01)
    finally:
        closeRelaunched(mainWindow)
