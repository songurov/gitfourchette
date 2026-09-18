# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os

import pytest

from gitfourchette import settings
from gitfourchette.forms.newbranchdialog import NewBranchDialog
from gitfourchette.forms.quicklaunch import QuickLaunch, QuickLaunchEntry
from gitfourchette.toolbox import compactPath
from .test_workspaces import openTwoRepos, saveWorkspace
from .util import *


def openPalette(mainWindow) -> QuickLaunch:
    triggerMenuAction(mainWindow.menuBar(), "view/quick launch")
    return findPalette(mainWindow)


def findPalette(mainWindow) -> QuickLaunch:
    palettes = [p for p in mainWindow.findChildren(QuickLaunch) if p.isVisible()]
    assert len(palettes) == 1
    return palettes[0]


def paletteIsOpen(mainWindow) -> bool:
    return any(p.isVisible() for p in mainWindow.findChildren(QuickLaunch))


def query(palette: QuickLaunch, text: str):
    palette.lineEdit.clear()
    QTest.keyClicks(palette.lineEdit, text)


def section(palette: QuickLaunch, title: str):
    return next(s for s in palette.sections if s.title == title)


@pytest.mark.parametrize("keys", ["Meta+P", "Ctrl+Shift+A"])
def testShortcutOpensQuickLaunch(tempDir, mainWindow, keys):
    mainWindow.openRepo(unpackRepo(tempDir))
    QTest.qWait(0)
    QTest.keySequence(mainWindow, keys)
    palette = findPalette(mainWindow)
    assert palette.focusWidget() is palette.lineEdit
    palette.close()


def testCommandsComeFromTheMenuBar(tempDir, mainWindow):
    mainWindow.openRepo(unpackRepo(tempDir))
    palette = openPalette(mainWindow)
    titles = palette.visibleTitles()

    # Tasks from the Repo menu, with their shortcut shown as the detail
    for title in ["Push Branch…", "Pull Remote Branch…", "Fetch Remote Branches", "New Local Branch…"]:
        assert title in titles
    push = next(e for e in section(palette, "Commands").entries if e.title == "Push Branch…")
    assert push.detail == QKeySequence("Ctrl+P").toString(QKeySequence.SequenceFormat.NativeText)

    # Items of a static submenu carry its name
    assert "Local Config Files › .gitignore" in titles

    # Commands are alphabetical, and mnemonics are gone
    commands = [e.title for e in section(palette, "Commands").entries]
    assert commands == sorted(commands, key=str.casefold)
    assert not any("&" in t for t in commands)

    # Not listed: the palette itself, and the menus filled on demand
    assert not any(t.startswith("Quick Launch") for t in titles)
    assert not any(t.startswith(("Open Recent", "Workspace ›", "Clear List")) for t in titles)

    # Section headers are shown but can't be run
    headers = [palette.model.item(r).text() for r in range(palette.model.rowCount())
               if r not in palette.runnableRows()]
    assert headers == ["Recent Repositories", "Workspaces", "Commands"]
    # ...and the first one is in view, not scrolled past by the initial selection
    assert palette.listView.verticalScrollBar().value() == 0
    palette.close()


def testRootMenuNameIsSearchable(tempDir, mainWindow):
    mainWindow.openRepo(unpackRepo(tempDir))
    palette = openPalette(mainWindow)
    # "Overview" lives in the Data menu; its title alone doesn't say "data"
    query(palette, "data overview")
    assert palette.visibleTitles() == ["Overview"]
    palette.close()


def testTypingFiltersAndEnterRunsTheCommand(tempDir, mainWindow):
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    palette = openPalette(mainWindow)

    query(palette, "new local")
    assert palette.visibleTitles()[0] == "New Local Branch…"
    assert palette.currentEntry().title == "New Local Branch…"

    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    assert not paletteIsOpen(mainWindow)

    dlg: NewBranchDialog = findQDialog(rw, "new branch")
    dlg.reject()


def testEveryTermMustMatch(tempDir, mainWindow):
    mainWindow.openRepo(unpackRepo(tempDir))
    palette = openPalette(mainWindow)

    query(palette, "branch push")
    assert palette.visibleTitles() == ["Push Branch…"]

    query(palette, "no such command anywhere")
    assert palette.visibleTitles() == []
    assert palette.currentEntry() is None
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)  # nothing to run: no-op
    assert paletteIsOpen(mainWindow)
    palette.close()


def testEscapeClosesWithoutRunning(tempDir, mainWindow):
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    palette = openPalette(mainWindow)
    query(palette, "new local")
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Escape)
    assert not paletteIsOpen(mainWindow)
    with pytest.raises(KeyError):
        findQDialog(rw, "new branch")


def testRecentRepoOpensInATab(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    mainWindow.closeTab(0)
    assert [b] == mainWindow.openTabPaths()

    palette = openPalette(mainWindow)
    query(palette, "alpha")
    entry = palette.currentEntry()
    assert entry.title == "alpha"
    assert entry.detail == compactPath(a)

    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    assert a in mainWindow.openTabPaths()
    assert a == os.path.normpath(mainWindow.currentRepoWidget().workdir)


def testRepoMatchesOnItsPathToo(tempDir, mainWindow):
    a, _b = openTwoRepos(tempDir, mainWindow)
    palette = openPalette(mainWindow)
    # A piece of the parent folder, which isn't in the repo's name
    query(palette, os.path.basename(os.path.dirname(a)))
    assert {"alpha", "bravo"} <= set(palette.visibleTitles())
    palette.close()


def testWorkspaceEntrySwitchesWorkspace(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "two repos")
    mainWindow.switchToWorkspace("")
    assert "" == settings.history.currentWorkspace

    palette = openPalette(mainWindow)
    query(palette, "two repos")
    assert palette.currentEntry().title == "two repos"
    assert palette.currentEntry().detail == "2 repos"

    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    assert "two repos" == settings.history.currentWorkspace
    assert [a, b] == mainWindow.openTabPaths()


def testArrowKeysSkipSectionHeaders(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "alpha team")

    palette = openPalette(mainWindow)
    query(palette, "alpha")
    # "alpha" (Recent Repositories), then "alpha team" (Workspaces): a header sits between them
    assert palette.visibleTitles() == ["alpha", "alpha team"]
    assert palette.currentEntry().title == "alpha"

    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Down)
    assert palette.currentEntry().title == "alpha team"
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Down)  # already last: stays
    assert palette.currentEntry().title == "alpha team"
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Up)
    assert palette.currentEntry().title == "alpha"
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Up)  # already first: stays
    assert palette.currentEntry().title == "alpha"
    palette.close()


def testCurrentWorkspaceIsMarked(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "mine")
    mainWindow.switchToWorkspace("mine")

    palette = openPalette(mainWindow)
    workspaces = {e.title: e.detail for e in section(palette, "Workspaces").entries}
    assert workspaces["mine"] == "current"
    assert workspaces["Home"] == ""
    palette.close()


def testRecentReposFirstThenHomeAndSwitchWorkspace(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "job")

    palette = openPalette(mainWindow)
    titles = palette.visibleTitles()
    # Newest repo first, then the two ways out, then the commands
    assert titles[:4] == ["bravo", "alpha", "Home", "Switch Workspace…"]
    assert palette.currentEntry().title == "bravo"
    assert "Push Branch…" in titles[4:]
    # Named workspaces wait for a search (Switch Workspace lists them)
    assert "job" not in titles
    query(palette, "job")
    assert palette.visibleTitles() == ["job"]
    palette.close()


def testHomeIsOneSearchAway(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "job")
    mainWindow.switchToWorkspace("job")

    palette = openPalette(mainWindow)
    query(palette, "home")
    assert palette.currentEntry().title == "Home"
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    assert not paletteIsOpen(mainWindow)
    assert "" == settings.history.currentWorkspace


def testSwitchWorkspaceDrillsDownAndBack(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "job")
    mainWindow.switchToWorkspace("")

    palette = openPalette(mainWindow)
    query(palette, "switch work")
    assert palette.currentEntry().title == "Switch Workspace…"
    assert palette.currentEntry().detail == "1 workspace"

    # Enter opens the list instead of closing the palette
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    assert paletteIsOpen(mainWindow)
    assert palette.lineEdit.text() == ""
    assert palette.lineEdit.placeholderText() == "Switch Workspace"
    assert palette.visibleTitles() == ["Home", "job"]

    # Backspace on an empty field goes back to everything (on Home: Home's commands)
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Backspace)
    assert "Open Repository…" in palette.visibleTitles()

    # ...and the list is searchable like the rest
    query(palette, "switch work")
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    query(palette, "jo")
    assert palette.visibleTitles() == ["job"]
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    assert not paletteIsOpen(mainWindow)
    assert "job" == settings.history.currentWorkspace
    assert [a, b] == mainWindow.openTabPaths()


def testBackspaceStillDeletesText(tempDir, mainWindow):
    mainWindow.openRepo(unpackRepo(tempDir))
    palette = openPalette(mainWindow)
    query(palette, "switch work")
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    QTest.keyClicks(palette.lineEdit, "ho")
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Backspace)  # not empty: a normal backspace
    assert palette.lineEdit.text() == "h"
    assert palette.lineEdit.placeholderText() == "Switch Workspace"
    palette.close()


def testScorePrefersTitlePrefixThenWordStart():
    def entry(title):
        return QuickLaunchEntry(title, lambda: None)

    assert entry("Push Branch…").score(["push"]) == 0
    assert entry("Force Push").score(["push"]) == 1
    assert entry("Autopush").score(["push"]) == 2
    assert entry("Something").score(["push"]) == -1
    # Detail and keywords can satisfy a term, but rank below any title hit
    assert QuickLaunchEntry("alpha", lambda: None, detail="~/code/alpha").score(["code"]) == 3


def testPaletteRenders(tempDir, mainWindow):
    """Not an assertion on pixels - it catches a delegate that throws while painting."""
    openTwoRepos(tempDir, mainWindow)
    palette = openPalette(mainWindow)
    image = palette.grab().toImage()
    assert not image.isNull()
    assert image.width() >= 420
    # Every runnable row has an icon (a blank one if need be), so titles line up
    for row in palette.runnableRows():
        assert not palette.model.item(row).icon().isNull()
    palette.close()


HOME_COMMANDS = {"Open Repository…", "Clone Repository…", "New Repository…", "Settings…", "Quit",
                 "Fetch All Repositories", "Rescan Repositories", "Open Trash…", "Show Toolbar"}
REPO_COMMANDS = {"Push Branch…", "Pull Remote Branch…", "New Local Branch…", "Stash Changes…", "Find…",
                 "Blame File…", "Overview", "Close Tab", "Apply Patch File…", "Refresh",
                 "Local Config Files › .gitignore", "Go to HEAD Commit"}


def testOnHomeOnlyWhatWorksWithoutARepo(mainWindow):
    """With no repo open, Push or Blame have nothing to act on: they're not offered."""
    palette = openPalette(mainWindow)
    commands = {e.title for e in section(palette, "Commands").entries}
    assert HOME_COMMANDS <= commands
    assert not (REPO_COMMANDS & commands)
    palette.close()


def testWithARepoEverythingButHomeChores(tempDir, mainWindow):
    mainWindow.openRepo(unpackRepo(tempDir))
    palette = openPalette(mainWindow)
    commands = {e.title for e in section(palette, "Commands").entries}
    assert REPO_COMMANDS <= commands
    assert "Open Repository…" in commands
    assert not ({"Fetch All Repositories", "Rescan Repositories"} & commands)
    palette.close()


def testHomeChoresRunOnTheHomePage(tempDir, mainWindow):
    from .test_home import waitForScan
    settings.history.scanRoots = [tempDir.name]
    welcome = mainWindow.welcomeWidget
    waitForScan(welcome)

    palette = openPalette(mainWindow)
    query(palette, "fetch all")
    assert palette.currentEntry().title == "Fetch All Repositories"
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    assert not welcome.fetchAllButton.isEnabled(), "the Home page's own Fetch All is running"
    waitForScan(welcome)
    assert welcome.fetchAllButton.isEnabled()


def testNewMenuItemsStayOffHomeUntilMarked():
    """Opt-in: an item nobody vouched for doesn't show up on Home by accident."""
    from gitfourchette.forms.quicklaunch import WORKS_WITHOUT_REPO, menuBarEntries
    bar = QMenuBar()
    menu = bar.addMenu("File")
    menu.addAction("Needs a repo")
    marked = menu.addAction("Works anywhere")
    marked.setProperty(WORKS_WITHOUT_REPO, True)

    assert [e.title for e in menuBarEntries(bar)] == ["Needs a repo", "Works anywhere"]
    assert [e.title for e in menuBarEntries(bar, withoutRepo=True)] == ["Works anywhere"]
    bar.deleteLater()
