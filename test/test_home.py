# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
import os
import pathlib

from gitfourchette import settings
from gitfourchette.forms.welcomewidget import WelcomeWidget
from gitfourchette.reposcan import (
    DEFAULT_MAX_DEPTH, RepoInfo, defaultScanRoots, fetchRepo, findRepos, inspectRepo,
    inspectRepoDetails)
from .util import *


def makeRepoAt(root: str, relativePath: str) -> str:
    parent = os.path.join(root, os.path.dirname(relativePath))
    os.makedirs(parent, exist_ok=True)
    return os.path.normpath(unpackRepo(parent, renameTo=os.path.basename(relativePath)))


def waitForScan(widget: WelcomeWidget):
    """The scanner's signal is queued, so finishing the thread isn't enough."""
    assert widget.scanner is not None
    assert widget.scanner.wait(10000), "repo scan didn't finish"
    QTest.qWait(1)  # let the queued resultsReady land on the UI thread


def treeLabels(widget: WelcomeWidget, onlyVisible: bool = False) -> list[str]:
    labels = []

    def walk(item):
        if onlyVisible and item.isHidden():
            return
        labels.append(item.text(0).split("  ")[0])
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(widget.repoTree.topLevelItemCount()):
        walk(widget.repoTree.topLevelItem(i))
    return labels


def findItem(widget: WelcomeWidget, path: str):
    stack = [widget.repoTree.topLevelItem(i) for i in range(widget.repoTree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.data(0, WelcomeWidget.PathRole) == path:
            return item
        stack += [item.child(i) for i in range(item.childCount())]
    raise KeyError(f"no tree item for {path}")


def leafPaths(widget: WelcomeWidget) -> list[str]:
    paths = []

    def walk(item):
        path = item.data(0, WelcomeWidget.PathRole)
        if path:
            paths.append(path)
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(widget.repoTree.topLevelItemCount()):
        walk(widget.repoTree.topLevelItem(i))
    return paths


# -----------------------------------------------------------------------------
# The scanner


def testScannerFindsReposAndStopsInsideThem(tempDir):
    root = tempDir.name
    a = makeRepoAt(root, "job/web/alpha")
    b = makeRepoAt(root, "my/bravo")
    # A clone sitting inside another repo's workdir belongs to nobody
    makeRepoAt(root, "job/web/alpha/vendored")

    found = findRepos([root])
    assert {a, b} == set(found)


def testScannerSkipsHiddenAndHeavyFolders(tempDir):
    root = tempDir.name
    visible = makeRepoAt(root, "src/visible")
    makeRepoAt(root, ".cache/hidden")
    makeRepoAt(root, "src/node_modules/dependency")

    assert [visible] == findRepos([root])


def testScannerRespectsMaxDepth(tempDir):
    root = tempDir.name
    deep = makeRepoAt(root, "a/b/c/d/deep")

    assert [deep] == findRepos([root], maxDepth=DEFAULT_MAX_DEPTH)
    assert [] == findRepos([root], maxDepth=2)


def testScannerSurvivesUnreadableFoldersAndMissingRoots(tempDir):
    root = tempDir.name
    good = makeRepoAt(root, "readable/good")

    locked = os.path.join(root, "locked")
    os.makedirs(locked)
    os.chmod(locked, 0o000)
    try:
        assert [good] == findRepos([root, os.path.join(root, "does-not-exist")])
    finally:
        os.chmod(locked, 0o755)


def testScannerIgnoresSymlinkedFolders(tempDir):
    root = tempDir.name
    repo = makeRepoAt(root, "real/repo")
    os.symlink(root, os.path.join(root, "real", "loop"))

    # Symlinked directories are never followed, so a loop can't even start
    assert [repo] == findRepos([root])


def testScannerVisitsOverlappingRootsOnlyOnce(tempDir):
    root = tempDir.name
    repo = makeRepoAt(root, "nested/deep/repo")

    # The second root lives inside the first; the repo must not be listed twice
    assert [repo] == findRepos([root, os.path.join(root, "nested")])


def testScannerCanBeCancelledBeforeItStarts(tempDir):
    root = tempDir.name
    makeRepoAt(root, "some/repo")
    assert [] == findRepos([root], isCancelled=lambda: True)


def testScannerCanBeCancelledPartWayThrough(tempDir):
    root = tempDir.name
    for name in ("a/one", "b/two", "c/three", "d/four"):
        makeRepoAt(root, name)

    calls = []

    def cancelAfterAWhile():
        calls.append(None)
        return len(calls) > 6

    found = findRepos([root], isCancelled=cancelAfterAWhile)
    assert len(found) < 4, "cancelling should cut the walk short"


def testDefaultScanRootsAreRealFolders():
    for root in defaultScanRoots():
        assert os.path.isdir(root)


# -----------------------------------------------------------------------------
# The Home page


def testHomeTreeMirrorsTheFolderStructure(tempDir, mainWindow):
    root = tempDir.name
    web = makeRepoAt(root, "job/web/vcrm-core")
    mobile = makeRepoAt(root, "job/mobile/prt")
    mine = makeRepoAt(root, "my/oss/gitfourchette")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)

    labels = treeLabels(welcome)
    assert ["Repositories", "job", "mobile", "prt", "web", "vcrm-core",
            "my", "oss", "gitfourchette"] == labels
    assert {web, mobile, mine} == set(leafPaths(welcome))


def testHomeHasASeparateRecentSection(tempDir, mainWindow):
    root = tempDir.name
    older = makeRepoAt(root, "work/older")
    newer = makeRepoAt(root, "work/newer")
    settings.history.addRepo(older)
    settings.history.addRepo(newer)

    welcome = mainWindow.welcomeWidget
    welcome.populate([inspectRepo(older), inspectRepo(newer)])

    recent = welcome.repoTree.topLevelItem(0)
    repositories = welcome.repoTree.topLevelItem(1)
    assert "Recent" == recent.text(0)
    assert "Repositories" == repositories.text(0)
    assert ["newer", "older"] == [
        recent.child(i).text(0).split("  ")[0] for i in range(recent.childCount())]
    assert 2 == leafPaths(welcome).count(older), "recent repos also stay in the full tree"


def testHomeTreeFilterKeepsTheFoldersOfWhatMatches(tempDir, mainWindow):
    root = tempDir.name
    makeRepoAt(root, "job/web/vcrm-core")
    makeRepoAt(root, "my/oss/gitfourchette")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)

    welcome.filterEdit.setText("vcrm")
    # The matching repo stays, and so do the folders that lead to it
    assert ["Repositories", "job", "web", "vcrm-core"] == treeLabels(
        welcome, onlyVisible=True)

    welcome.filterEdit.setText("")
    assert len(treeLabels(welcome, onlyVisible=True)) > 3


def testActivatingARepoOpensIt(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "one/first")
    makeRepoAt(root, "two/second")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)

    leaf = findItem(welcome, repo)
    assert repo == leaf.data(0, WelcomeWidget.PathRole)
    welcome.repoTree.itemActivated.emit(leaf, 0)

    assert [repo] == mainWindow.openTabPaths()


def testActivatingAFolderTogglesIt(tempDir, mainWindow):
    root = tempDir.name
    makeRepoAt(root, "group/inside")
    makeRepoAt(root, "other/elsewhere")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)

    folder = welcome.repoTree.topLevelItem(0)
    assert not folder.data(0, WelcomeWidget.PathRole), "expected a folder, not a repo"
    assert folder.isExpanded()
    welcome.repoTree.itemActivated.emit(folder, 0)
    assert not folder.isExpanded()
    # ...and no tab was opened by clicking a folder
    assert [] == mainWindow.openTabPaths()


def testScanResultsAreRememberedBetweenRuns(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "cached/repo")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)
    assert [repo] == [d["path"] for d in settings.history.scannedRepos]

    # A later start shows the cached tree immediately, before the scan finishes
    welcome.repoTree.clear()
    welcome.populate([RepoInfo.fromDict(d) for d in settings.history.scannedRepos])
    assert [repo] == leafPaths(welcome)


def testRepoThatVanishedIsFlagged(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "gone/repo")

    welcome = mainWindow.welcomeWidget
    welcome.populate([RepoInfo(path=repo),
                      RepoInfo(path=os.path.join(root, "gone", "never-existed"))])

    assert not findItem(welcome, repo).icon(0).isNull()
    missing = findItem(welcome, os.path.join(root, "gone", "never-existed"))
    assert not missing.icon(0).isNull()
    assert "never-existed" in missing.toolTip(0)


def testPickingAScanFolderRescans(tempDir, mainWindow):
    root = tempDir.name
    elsewhere = os.path.join(root, "elsewhere")
    repo = makeRepoAt(root, "elsewhere/found-here")

    welcome = mainWindow.welcomeWidget
    welcome.onScanRootPicked(elsewhere)
    waitForScan(welcome)

    assert [elsewhere] == settings.history.scanRoots
    assert [repo] == leafPaths(welcome)


def testHomeTreeIsEmptyWithoutRepos(tempDir, mainWindow):
    settings.history.scanRoots = [os.path.join(tempDir.name, "nothing-here")]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)

    assert 0 == welcome.repoTree.topLevelItemCount()
    assert [] == leafPaths(welcome)


def testStoppingAScanInFlight(tempDir, mainWindow):
    root = tempDir.name
    for name in ("a/one", "b/two", "c/three"):
        makeRepoAt(root, name)

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.rescan(force=True)
    # Cancelling must join the thread: a QThread destroyed while running aborts the process
    welcome.stopScan()
    assert not welcome.scanner.isRunning()

    # ...and a second stop on an idle scanner is harmless
    welcome.stopScan()


def testClosingTheHomePageStopsItsScan(tempDir, mainWindow):
    root = tempDir.name
    makeRepoAt(root, "some/repo")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.rescan(force=True)
    welcome.close()
    assert not welcome.scanner.isRunning()


def testRescanIsIgnoredWhileOneIsRunning(tempDir, mainWindow):
    root = tempDir.name
    makeRepoAt(root, "some/repo")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.rescan(force=True)
    first = welcome.scanner
    welcome.rescan()  # not forced: the one in flight stands
    assert first is welcome.scanner

    # Forcing while one is running cancels it and starts a fresh one
    welcome.rescan(force=True)
    assert first is not welcome.scanner
    assert not first.isRunning()
    waitForScan(welcome)


def testChoosingAScanFolderThroughTheDialog(tempDir, mainWindow):
    root = tempDir.name
    elsewhere = os.path.join(root, "picked")
    repo = makeRepoAt(root, "picked/inside")

    welcome = mainWindow.welcomeWidget
    welcome.fillFoldersMenu()
    triggerMenuAction(welcome.foldersMenu, "add folder")
    acceptQFileDialog(welcome, "folder to search", elsewhere)
    waitForScan(welcome)

    assert [elsewhere] == settings.history.scanRoots
    assert [repo] == leafPaths(welcome)


# -----------------------------------------------------------------------------
# What a repo has outstanding


def testInspectReportsUncommittedWork(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    assert not inspectRepo(wd).dirty

    writeFile(f"{wd}/newfile.txt", "work in progress")
    info = inspectRepo(wd)
    assert info.dirty
    assert 1 == info.changedFiles
    assert info.needsAttention
    assert "master" == info.branch


def testInspectRepoDetailsFeedsTheHomeHeaderAndStatistics(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    details = inspectRepoDetails(wd)

    assert details.sizeBytes > 0
    assert details.commitCount > 0
    assert details.initialCommitTime <= details.lastCommitTime
    assert "origin" in details.remotes
    assert details.localBranches > 0
    assert details.months
    assert sum(count for _name, count in details.contributors) == details.commitCount

    welcome = mainWindow.welcomeWidget
    welcome.populate([inspectRepo(wd)])
    welcome.repoTree.setCurrentItem(findItem(welcome, os.path.normpath(wd)))

    facts = welcome.repoFacts.text()
    assert "Repository size" in facts
    assert "Initial commit" in facts
    assert str(details.commitCount) in facts
    assert welcome.commitChart.months
    assert welcome.contributorTable.rowCount() == len(details.contributors)


def testInspectReportsUnpushedCommits(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    # The fixture's master already sits ahead of origin/master
    info = inspectRepo(wd)
    assert 2 == info.ahead
    assert not info.noUpstream
    assert info.needsAttention

    shell("git reset --hard origin/master", wd)
    info = inspectRepo(wd)
    assert 0 == info.ahead
    assert not info.needsAttention


def testInspectReportsABranchThatTracksNothing(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git switch -c orphaned", wd)

    info = inspectRepo(wd)
    assert info.noUpstream
    assert 0 == info.ahead
    assert "orphaned" == info.branch


def testInspectReportsAnUnbornRepo(tempDir, mainWindow):
    wd = os.path.join(tempDir.name, "brandnew")
    os.makedirs(wd)
    shell("git init -q .", wd)

    info = inspectRepo(wd)
    assert info.noUpstream
    assert "" == info.branch
    assert not info.unreadable


def testInspectReportsADetachedHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git switch -q --detach HEAD~1", wd)

    info = inspectRepo(wd)
    assert "" == info.branch
    assert 0 == info.ahead


def testInspectSurvivesSomethingThatIsNotARepo(tempDir, mainWindow):
    notARepo = os.path.join(tempDir.name, "just-a-folder")
    os.makedirs(notARepo)

    info = inspectRepo(notARepo)
    assert info.unreadable
    assert not info.needsAttention


def testScannerCanBeCancelledDuringInspection(tempDir, mainWindow):
    from gitfourchette.reposcan import RepoScanner

    root = tempDir.name
    makeRepoAt(root, "some/repo")

    scanner = RepoScanner([root], DEFAULT_MAX_DEPTH)
    received = []
    scanner.resultsReady.connect(received.append)
    scanner.cancel()
    scanner.run()  # synchronous: no signal must be emitted for a cancelled scan
    assert [] == received


def testTreeMarksWhatNeedsAttention(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/newfile.txt", "work in progress")

    welcome = mainWindow.welcomeWidget
    welcome.populate([inspectRepo(wd)])

    item = findItem(welcome, os.path.normpath(wd))
    assert "●" in item.text(0), "uncommitted work gets a dot"
    assert "↑2" in item.text(0), "unpushed commits get an arrow and a count"
    assert item.font(0).bold()

    tooltip = item.toolTip(0)
    assert "Uncommitted changes" in tooltip
    assert "commits not pushed" in tooltip
    assert "Branch: master" in tooltip


def testTreeSaysNothingAboutACleanRepo(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git reset --hard origin/master", wd)

    welcome = mainWindow.welcomeWidget
    welcome.populate([inspectRepo(wd)])

    item = findItem(welcome, os.path.normpath(wd))
    assert "●" not in item.text(0)
    assert "↑" not in item.text(0)
    assert not item.font(0).bold()
    assert "Nothing outstanding" in item.toolTip(0)


def testTreeFlagsAnUnreadableRepoAndAnUntrackedBranch(tempDir, mainWindow):
    notARepo = os.path.join(tempDir.name, "just-a-folder")
    os.makedirs(notARepo)
    wd = unpackRepo(tempDir)
    shell("git switch -c orphaned", wd)

    welcome = mainWindow.welcomeWidget
    welcome.populate([inspectRepo(notARepo), inspectRepo(wd)])

    assert "couldn" in findItem(welcome, notARepo).toolTip(0)
    assert "isn" in findItem(welcome, os.path.normpath(wd)).toolTip(0)


def testFoldersMenuListsAndRemovesRoots(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "kept/repo")
    other = os.path.join(root, "kept")

    welcome = mainWindow.welcomeWidget
    settings.history.scanRoots = [other]
    welcome.rescan(force=True)
    waitForScan(welcome)
    assert [repo] == leafPaths(welcome)

    welcome.fillFoldersMenu()
    triggerMenuAction(welcome.foldersMenu, "stop searching")
    waitForScan(welcome)

    assert [] == settings.history.scanRoots
    assert [] == leafPaths(welcome)


def testAddingASecondFolderKeepsTheFirst(tempDir, mainWindow):
    root = tempDir.name
    first = os.path.join(root, "one")
    second = os.path.join(root, "two")
    repoA = makeRepoAt(root, "one/alpha")
    repoB = makeRepoAt(root, "two/bravo")

    welcome = mainWindow.welcomeWidget
    welcome.onScanRootPicked(first)
    waitForScan(welcome)
    assert [repoA] == leafPaths(welcome)

    # Repos aren't all under one roof, so folders add up
    welcome.onScanRootPicked(second)
    waitForScan(welcome)
    assert [first, second] == settings.history.scanRoots
    assert {repoA, repoB} == set(leafPaths(welcome))

    # Adding one that's already there changes nothing
    welcome.onScanRootPicked(second)
    waitForScan(welcome)
    assert [first, second] == settings.history.scanRoots


def testShowingReposDoesntAddThemToRecents(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "seen/but-not-opened")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)
    assert [repo] == leafPaths(welcome)

    # Listing a repo is not opening it: Open Recent must stay the user's list
    assert repo not in settings.history.repos
    assert [] == list(settings.history.getRecentRepoPaths(50))


def testInspectSurvivesACorruptIndex(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    # A repo that opens fine but falls over when read must not take the scan down
    writeFile(f"{wd}/.git/index", "this is not an index file")

    info = inspectRepo(wd)
    assert info.unreadable
    assert not info.needsAttention


def testScannerReportsAsItGoes(tempDir, mainWindow):
    from gitfourchette.reposcan import RepoScanner

    root = tempDir.name
    # More than one batch, so progress has something to report mid-walk
    for i in range(RepoScanner.BatchSize * 2):
        makeRepoAt(root, f"group{i // 4}/repo{i}")

    scanner = RepoScanner([root], DEFAULT_MAX_DEPTH)
    batches = []
    scanner.progress.connect(lambda infos: batches.append(len(infos)))
    final = []
    scanner.resultsReady.connect(final.append)
    scanner.run()  # synchronous, so the signals land in order

    assert len(batches) > 1, "a long scan must report before it ends"
    assert batches == sorted(batches), "each report knows at least as much as the last"
    assert batches[0] < batches[-1], "the list grows as the scan runs"
    assert RepoScanner.BatchSize * 2 == len(final[0])


def testPathsArriveBeforeTheirState(tempDir, mainWindow):
    from gitfourchette.reposcan import RepoScanner

    root = tempDir.name
    for i in range(RepoScanner.BatchSize):
        makeRepoAt(root, f"g/repo{i}")

    scanner = RepoScanner([root], DEFAULT_MAX_DEPTH)
    snapshots = []
    scanner.progress.connect(lambda infos: snapshots.append([bool(i.branch) for i in infos]))
    scanner.run()

    # Finding a repo is cheap; reading it isn't. The first report has paths
    # with nothing read yet, the last one has everything filled in.
    assert not any(snapshots[0]), "the first report is paths only"
    assert all(snapshots[-1]), "by the end, every repo has been read"


def testHomePageScansWhenItBecomesVisible(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "found/onshow")
    settings.history.scanRoots = [root]

    welcome = mainWindow.welcomeWidget
    welcome.repoTree.clear()
    welcome.scanner = None

    # Showing the page is what starts the scan - that's the one path taken by
    # app start with no tabs, closing the last tab, and switching to Home alike
    welcome.showEvent(QShowEvent())
    assert welcome.scanner is not None
    waitForScan(welcome)
    assert [repo] == leafPaths(welcome)


def testStatusSaysSoWhileScanning(tempDir, mainWindow):
    root = tempDir.name
    makeRepoAt(root, "some/repo")
    welcome = mainWindow.welcomeWidget

    welcome.populate([RepoInfo(path=os.path.join(root, "some", "repo"))], scanning=True)
    assert "so far" in welcome.paneStatus.text()

    welcome.populate([RepoInfo(path=os.path.join(root, "some", "repo"))])
    assert "so far" not in welcome.paneStatus.text()


def testCancellingBetweenFindingAndReadingStopsEverything(tempDir, mainWindow):
    from gitfourchette.reposcan import RepoScanner

    root = tempDir.name
    makeRepoAt(root, "some/repo")

    scanner = RepoScanner([root], DEFAULT_MAX_DEPTH)
    emitted = []
    scanner.progress.connect(emitted.append)
    scanner.resultsReady.connect(emitted.append)
    # Cancel the moment the paths are in, before any repo is read
    scanner.progress.connect(lambda _infos: scanner.cancel())
    scanner.run()

    assert 1 == len(emitted), "nothing more must be reported after a cancel"


def repoScopedToolbarTexts(mainWindow) -> list[str]:
    return [stripAccelerators(a.text()) for a in mainWindow.mainToolBar.repoScopedActions
            if a.isVisible() and a.text()]


def testToolbarHidesRepoOnlyButtonsOnHome(tempDir, mainWindow):
    # Nothing is open, so there is nothing to stash, push or reveal
    assert [] == repoScopedToolbarTexts(mainWindow)

    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)
    visible = repoScopedToolbarTexts(mainWindow)
    assert "Stash" in visible
    assert "Push" in visible
    assert "Open In" in visible

    # Closing the last tab puts them away again
    mainWindow.closeAllTabs()
    assert [] == repoScopedToolbarTexts(mainWindow)


def testToolbarKeepsGlobalButtonsOnHome(tempDir, mainWindow):
    toolbar = mainWindow.mainToolBar
    # Theme, Workspace and Settings work with or without a repo
    assert toolbar.themeAction.isVisible()
    assert toolbar.workspaceAction.isVisible()
    assert toolbar.settingsAction.isVisible()
    # Opening a repo now lives on the Home page and in the File menu,
    # so the toolbar doesn't carry a second door to it
    assert not hasattr(toolbar, "recentAction")
    assert findMenuAction(mainWindow.menuBar(), "file/open repository")


def testTheRightHandGroupStaysPutOnHome(tempDir, mainWindow):
    toolbar = mainWindow.mainToolBar
    # The expanding spacer is not repo-scoped, so Theme/Workspace/Settings
    # don't slide across the bar when the repo buttons go away
    spacer = next(a for a in toolbar.actions() if isinstance(a, QWidgetAction))
    assert spacer.isVisible()
    assert spacer not in toolbar.repoScopedActions


def testNoSeparatorIsLeftStrandedOnHome(tempDir, mainWindow):
    toolbar = mainWindow.mainToolBar
    visible = [a for a in toolbar.actions() if a.isVisible()]
    # A separator with nothing before it, or two in a row, is a leftover
    assert not visible[0].isSeparator()
    assert not any(a.isSeparator() and b.isSeparator()
                   for a, b in itertools.pairwise(visible))


def testOpenInMenuOffersTheUsualDestinations(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)

    mainWindow.fillOpenInMenu()
    texts = " ".join(stripAccelerators(a.text()) for a in mainWindow.openInMenu.actions()).lower()

    assert "repo folder" in texts
    assert "terminal" in texts
    assert "copy repo path" in texts
    # One button instead of three: the menu is where the choice lives now
    assert mainWindow.mainToolBar.openInAction.menu() is mainWindow.openInMenu


def testThemeSwitchFlipsBetweenLightAndDark(tempDir, mainWindow):
    from gitfourchette.themes import ThemeName, isDarkStyle

    toolbar = mainWindow.mainToolBar
    settings.prefs.qtStyle = f"{ThemeName.BuiltIn},light"
    mainWindow.refreshThemeButton()
    assert "Light theme" == toolbar.themeAction.toolTip()

    toolbar.fillThemeMenu()
    triggerMenuAction(toolbar.themeMenu, "dark")
    assert isDarkStyle(settings.prefs.qtStyle)
    assert "Dark theme" == toolbar.themeAction.toolTip()

    toolbar.fillThemeMenu()
    triggerMenuAction(toolbar.themeMenu, "light")
    assert not isDarkStyle(settings.prefs.qtStyle)


def testThemeSwitchKeepsTheAccentColour(tempDir, mainWindow):
    from gitfourchette.themes import ThemeName

    settings.prefs.qtStyle = f"{ThemeName.BuiltIn},light,#e93d58"
    mainWindow.refreshThemeButton()
    mainWindow.mainToolBar.fillThemeMenu()
    triggerMenuAction(mainWindow.mainToolBar.themeMenu, "dark")

    assert "#e93d58" in settings.prefs.qtStyle, "flipping the mode must not lose the accent"
    assert "dark" in settings.prefs.qtStyle


def testThemeSwitchWorksFromANativeStyle(tempDir, mainWindow):
    from gitfourchette.themes import ThemeName, isDarkStyle

    # A native Qt style has no say in light vs dark, so asking for dark adopts
    # the built-in theme rather than silently doing nothing
    settings.prefs.qtStyle = "Fusion"
    mainWindow.refreshThemeButton()
    mainWindow.mainToolBar.setDarkTheme(False)
    mainWindow.mainToolBar.fillThemeMenu()
    triggerMenuAction(mainWindow.mainToolBar.themeMenu, "dark")

    assert settings.prefs.qtStyle.startswith(ThemeName.BuiltIn)
    assert isDarkStyle(settings.prefs.qtStyle)


def testThemeSwitchFollowsTheSettingsDialog(tempDir, mainWindow):
    from gitfourchette.themes import ThemeName

    settings.prefs.qtStyle = f"{ThemeName.BuiltIn},dark"
    # Changing the theme anywhere else must move the switch too
    mainWindow.refreshPrefs()
    assert "Dark theme" == mainWindow.mainToolBar.themeAction.toolTip()


def testOpenInMenuCarriesUserCommands(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)
    GFApplication.applyPrefs(commands="helloworld")
    QTest.qWait(0)

    mainWindow.fillOpenInMenu()
    texts = [stripAccelerators(a.text()) for a in mainWindow.openInMenu.actions()]
    assert "Open Repo Folder" in texts
    command = next(t for t in texts if t.startswith("helloworld"))
    # Destinations first, then a separator, then the user's own commands
    assert texts.index("Open Repo Folder") < texts.index(command)
    assert any(a.isSeparator() for a in mainWindow.openInMenu.actions())


def testThemeMenuOffersLightDarkAndDensity(tempDir, mainWindow):
    from gitfourchette.themes import ThemeName, isDarkStyle

    toolbar = mainWindow.mainToolBar
    settings.prefs.qtStyle = f"{ThemeName.BuiltIn},light"
    mainWindow.refreshThemeButton()
    GFApplication.applyPrefs(compactUi=False)

    toolbar.fillThemeMenu()
    assert findMenuAction(toolbar.themeMenu, "light").isChecked()
    assert not findMenuAction(toolbar.themeMenu, "dark").isChecked()
    assert findMenuAction(toolbar.themeMenu, "normal").isChecked()
    assert not findMenuAction(toolbar.themeMenu, "compact").isChecked()

    triggerMenuAction(toolbar.themeMenu, "dark")
    assert isDarkStyle(settings.prefs.qtStyle)
    toolbar.fillThemeMenu()
    assert findMenuAction(toolbar.themeMenu, "dark").isChecked()


def testCompactShrinksTheWholeInterface(tempDir, mainWindow):
    app = GFApplication.instance()
    toolbar = mainWindow.mainToolBar

    GFApplication.applyPrefs(compactUi=False)
    normalUiFont = app.font().pointSizeF()
    normalCodeFont = settings.prefs.monoFont().pointSizeF()
    normalIconSize = toolbar.iconSize().width()
    # Normal stacks a bigger icon over its label
    assert Qt.ToolButtonStyle.ToolButtonTextUnderIcon == toolbar.toolButtonStyle()

    toolbar.fillThemeMenu()
    triggerMenuAction(toolbar.themeMenu, "compact")

    # Not just the toolbar: the type shrinks everywhere, code included
    assert settings.prefs.compactUi
    assert Qt.ToolButtonStyle.ToolButtonIconOnly == toolbar.toolButtonStyle()
    assert toolbar.iconSize().width() < normalIconSize
    assert app.font().pointSizeF() < normalUiFont
    assert settings.prefs.monoFont().pointSizeF() < normalCodeFont

    toolbar.fillThemeMenu()
    triggerMenuAction(toolbar.themeMenu, "normal")
    assert not settings.prefs.compactUi
    assert Qt.ToolButtonStyle.ToolButtonTextUnderIcon == toolbar.toolButtonStyle()
    assert normalIconSize == toolbar.iconSize().width()
    assert normalUiFont == app.font().pointSizeF()
    assert normalCodeFont == settings.prefs.monoFont().pointSizeF()


def testAnExplicitCodeFontSizeWinsOverCompact(tempDir, mainWindow):
    # Compact shouldn't quietly override a size the user asked for
    settings.prefs.fontSize = 13
    GFApplication.applyPrefs(compactUi=True)
    assert 13 == settings.prefs.monoFont().pointSize()
    settings.prefs.fontSize = 0


def testSelectingARepoShowsItsReadme(tempDir, mainWindow):
    root = tempDir.name
    a = makeRepoAt(root, "g/withreadme")
    b = makeRepoAt(root, "g/withoutreadme")
    makeRepoAt(root, "other/elsewhere")  # so the tree actually has folder rows
    writeFile(f"{a}/README.md", "# Hello\n\nThis is **alpha**.\n")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)

    # Nothing picked yet: the usual splash
    assert welcome.ui.leftStack.currentWidget() is welcome.ui.splashPage

    welcome.repoTree.setCurrentItem(findItem(welcome, a))
    assert welcome.ui.leftStack.currentWidget() is welcome.ui.readmePage
    assert "withreadme" in welcome.readmeTitle.text()
    assert "This is alpha." in welcome.readmeView.toPlainText()

    # A repo without one still has a useful header and Statistics tab.
    welcome.repoTree.setCurrentItem(findItem(welcome, b))
    assert welcome.ui.leftStack.currentWidget() is welcome.ui.readmePage
    assert "withoutreadme" in welcome.readmeTitle.text()
    assert "no README" in welcome.readmeView.toPlainText()
    assert not welcome.showReadme(b)

    # Picking a folder goes back to the splash
    folder = welcome.repoTree.topLevelItem(0)
    assert not folder.data(0, WelcomeWidget.PathRole), "expected a folder row"
    welcome.repoTree.setCurrentItem(folder)
    assert welcome.ui.leftStack.currentWidget() is welcome.ui.splashPage


def testReadmeIsFoundWhateverItIsCalled(tempDir, mainWindow):
    root = tempDir.name
    welcome = mainWindow.welcomeWidget

    for name, body in [("README.md", "markdown"), ("readme.txt", "plain"),
                       ("README", "bare"), ("README.rst", "restructured")]:
        repo = makeRepoAt(root, f"named/{name.replace('.', '_')}")
        writeFile(os.path.join(repo, name), body)
        assert os.path.basename(welcome.findReadme(repo)) == name
        welcome.showReadme(repo)
        assert body in welcome.readmeView.toPlainText()


def testMarkdownIsRenderedButOtherFormatsAreNot(tempDir, mainWindow):
    root = tempDir.name
    welcome = mainWindow.welcomeWidget

    asMarkdown = makeRepoAt(root, "fmt/md")
    writeFile(f"{asMarkdown}/README.md", "# Title\n\n- one\n- two\n")
    welcome.showReadme(asMarkdown)
    # Rendered: the heading marker is gone from the visible text
    assert "Title" in welcome.readmeView.toPlainText()
    assert "# Title" not in welcome.readmeView.toPlainText()

    asText = makeRepoAt(root, "fmt/txt")
    writeFile(f"{asText}/README.txt", "# Not markdown\n")
    welcome.showReadme(asText)
    # Shown as written, because it isn't markdown
    assert "# Not markdown" in welcome.readmeView.toPlainText()


def testHugeReadmeIsNotLoaded(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "big/one")
    writeFile(f"{repo}/README.md", "x" * (WelcomeWidget.README_SIZE_LIMIT + 1))

    welcome = mainWindow.welcomeWidget
    welcome.showReadme(repo)
    assert "too large" in welcome.readmeView.toPlainText()


def testUnreadableReadmeSaysSo(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "locked/one")
    readme = os.path.join(repo, "README.md")
    writeFile(readme, "secret")
    os.chmod(readme, 0o000)

    welcome = mainWindow.welcomeWidget
    try:
        welcome.showReadme(repo)
        assert "read" in welcome.readmeView.toPlainText().casefold()
    finally:
        os.chmod(readme, 0o644)


def testReadmeOfAVanishedRepo(tempDir, mainWindow):
    welcome = mainWindow.welcomeWidget
    assert not welcome.showReadme(os.path.join(tempDir.name, "never-existed"))


def testReposWithoutAReadmeAreCountedAndFlagged(tempDir, mainWindow):
    root = tempDir.name
    withOne = makeRepoAt(root, "g/documented")
    makeRepoAt(root, "g/bare")
    makeRepoAt(root, "other/alsobare")
    writeFile(f"{withOne}/README.md", "# Documented")

    settings.history.scanRoots = [root]
    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)

    assert "2 without a README" in welcome.paneStatus.text()
    assert "No README" in findItem(welcome, os.path.join(root, "g", "bare")).toolTip(0)
    assert "No README" not in findItem(welcome, withOne).toolTip(0)


def testBrokenImagesAreLeftOutOfThePreview(tempDir, mainWindow):
    root = tempDir.name
    repo = makeRepoAt(root, "pics/repo")
    writeFile(f"{repo}/logo.png", "not really a png, but it exists")
    writeFile(f"{repo}/README.md",
              "# Title\n\n"
              "![build badge](https://example.com/badge.svg)\n"
              "![local logo](logo.png)\n"
              "![missing](nowhere.png)\n"
              '<img src="https://example.com/banner.png" width="600">\n\n'
              "Body text.\n")

    welcome = mainWindow.welcomeWidget
    assert welcome.showReadme(repo)

    cleaned = welcome.dropUnreachableImages(
        pathlib.Path(f"{repo}/README.md").read_text(), repo)
    # A remote badge would render as a broken-image icon, so only its alt text stays
    assert "![build badge]" not in cleaned
    assert "build badge" in cleaned
    assert "<img" not in cleaned
    # A missing local file is no better
    assert "nowhere.png" not in cleaned
    # ...but one that's actually there is left alone
    assert "![local logo](logo.png)" in cleaned

    assert "Body text." in welcome.readmeView.toPlainText()


def testToolbarSaysWhereYouAre(tempDir, mainWindow):
    toolbar = mainWindow.mainToolBar
    # Nothing open: the middle of the bar has nothing to say
    assert "" == toolbar.repoAction.text()

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert "TestGitRepository" in toolbar.repoAction.text()
    assert "master" in toolbar.repoAction.text()
    assert "*" not in toolbar.repoAction.text()

    # Uncommitted work earns a star, the way Fork marks it
    writeFile(f"{wd}/dirty.txt", "work in progress")
    rw.refreshRepo()
    assert "TestGitRepository*" in toolbar.repoAction.text()

    # Clicking it offers the branches to switch to
    mainWindow.fillRepoButtonMenu()
    assert findMenuAction(mainWindow.repoMenu2, "master").isChecked()
    assert not findMenuAction(mainWindow.repoMenu2, "no-parent").isChecked()
    assert findMenuAction(mainWindow.repoMenu2, "new local branch")

    mainWindow.closeAllTabs()
    assert "" == toolbar.repoAction.text()


def testToolbarRepoBlockSwitchesBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    mainWindow.fillRepoButtonMenu()
    triggerMenuAction(mainWindow.repoMenu2, "no-parent")
    acceptQMessageBox(rw, "switch to")

    assert "no-parent" == rw.repoModel.homeBranch
    assert "no-parent" in mainWindow.mainToolBar.repoAction.text()


def testToolbarSaysNothingForAnUnloadedTab(tempDir, mainWindow):
    from gitfourchette.repowidget import RepoWidget

    wd = unpackRepo(tempDir)
    # Open it without loading it: the tab is a stub that has read nothing yet
    stub = mainWindow._openRepo(wd, foreground=False)
    assert not isinstance(stub, RepoWidget)

    mainWindow.refreshRepoButton()
    # A stub knows neither the repo's name nor its branch, so the bar says nothing
    assert "" == mainWindow.mainToolBar.repoAction.text()


# -----------------------------------------------------------------------------
# Fetching every repo at once


def makeRepoWithARemoteThatMovedOn(tempDir, name: str) -> str:
    """A repo whose remote has a commit it hasn't heard about yet."""

    wd = makeRepoAt(tempDir.name, name)
    # The stock test repository points "origin" at a public GitHub fixture.
    # This scenario must stay offline and exercise only the local remote below.
    shell("git remote remove origin", wd)
    barePath = makeBareCopy(wd, addAsRemote="tracked", preFetch=True)

    # Commit onto the bare remote through a throwaway clone, then forget it
    scratch = os.path.join(tempDir.name, f"scratch-{name}")
    shell(f"git clone {shlex.quote(barePath)} {shlex.quote(scratch)}", tempDir.name)
    writeFile(f"{scratch}/newsfromafar.txt", "the remote moved on")
    shell("git add newsfromafar.txt && git commit -m 'news from afar' && git push", scratch)
    shutil.rmtree(scratch)

    return wd


def testFetchBringsInWhatTheRemoteHas(tempDir, mainWindow):
    """Without a fetch, a repo can't know the remote moved on."""

    wd = makeRepoWithARemoteThatMovedOn(tempDir, "quiet")
    assert 0 == inspectRepo(wd).behind, "nothing known before a fetch"

    assert fetchRepo(wd)
    info = inspectRepo(wd)
    assert 1 == info.behind
    assert info.needsAttention


def testFetchOfSomethingThatIsNotARepoFailsQuietly(tempDir, mainWindow):
    notARepo = os.path.join(tempDir.name, "just-a-folder")
    os.makedirs(notARepo)
    assert not fetchRepo(notARepo)
    assert not fetchRepo(os.path.join(tempDir.name, "never-existed"))


def testFetchAllButtonUpdatesTheWholeTree(tempDir, mainWindow):
    wd = makeRepoWithARemoteThatMovedOn(tempDir, "moved")
    settings.history.scanRoots = [tempDir.name]

    welcome = mainWindow.welcomeWidget
    welcome.refresh()
    waitForScan(welcome)
    assert "↓" not in findItem(welcome, wd).text(0), "no news until we ask for it"

    welcome.fetchAllButton.click()
    assert not welcome.fetchAllButton.isEnabled(), "no piling fetches on top of each other"
    waitForScan(welcome)

    item = findItem(welcome, wd)
    assert "↓1" in item.text(0), "a commit waiting on the remote gets an arrow and a count"
    assert item.font(0).bold()
    assert "waiting on the remote" in item.toolTip(0)
    assert welcome.fetchAllButton.isEnabled()


def testFetchAllSaysWhichReposItCouldntReach(tempDir, mainWindow):
    wd = makeRepoAt(tempDir.name, "unreachable")
    shell("git remote add nowhere /nonexistent/nothing.git", wd)
    settings.history.scanRoots = [tempDir.name]

    welcome = mainWindow.welcomeWidget
    welcome.fetchAllButton.click()
    waitForScan(welcome)

    assert welcome.scanner.fetchFailures == [wd]
    assert "couldn’t be fetched" in welcome.paneStatus.text()
    assert "unreachable" in welcome.paneStatus.toolTip()


def testFetchAllCanBeStoppedPartWayThrough(tempDir, mainWindow):
    makeRepoAt(tempDir.name, "one")
    makeRepoAt(tempDir.name, "two")
    settings.history.scanRoots = [tempDir.name]

    welcome = mainWindow.welcomeWidget
    welcome.fetchAllButton.click()
    welcome.stopScan()

    assert not welcome.scanner.isRunning()
    assert welcome.fetchAllButton.isEnabled(), "the button comes back when the fetch stops"
