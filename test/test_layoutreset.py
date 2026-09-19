# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

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
