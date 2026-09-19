# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

import pytest

from gitfourchette.forms.commitinfodialog import CommitInfoDialog
from gitfourchette.graph import GraphDiagram, MockOid
from gitfourchette.graphview import commitlogdelegate
from gitfourchette.graphview.commitlogdelegate import MAX_GRAPH_COLUMNS, MIN_GRAPH_COLUMNS, NARROW_WIDTH, XMARGIN
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.graphview.graphpaint import LANE_WIDTH, flattenLanes, getColor, getCommitBulletColumn
from gitfourchette.repomodel import UC_FAKEID, findUnpushedCommits
from gitfourchette.graphview.graphview import GraphView
from gitfourchette.nav import NavLocator
from gitfourchette.avatars import avatarColor, avatarInitials
from gitfourchette.settings import GraphRefBoxWidth, GraphRowLayout, Prefs
from gitfourchette.sidebar.sidebarmodel import SYMBOL_AHEAD
from gitfourchette.themes import ThemeName, formatStyle
from gitfourchette.tasks import QueryCommitsTouchingPath
from gitfourchette.toolbox import contrastRatio
from .util import *
from .test_prefs import assertTranslatedInForkLanguages


def testCommitSearch(tempDir, mainWindow):
    # Commits that contain "first" in their summary
    matchingCommits = [
        Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4"),
        Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"),
        Oid(hex="d31f5a60d406e831d056b8ac2538d515100c2df2"),
        Oid(hex="83d2f0431bcdc9c2fd2c17b828143be6ee4fbe80"),
        Oid(hex="2c349335b7f797072cf729c4f3bb0914ecb6dec9"),
        Oid(hex="ac7e7e44c1885efb472ad54a78327d66bfc4ecef"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    searchBar = rw.graphView.searchBar
    searchEdit = searchBar.lineEdit

    def getGraphRow():
        indexes = rw.graphView.selectedIndexes()
        assert len(indexes) == 1
        return indexes[0].row()

    assert not searchBar.isVisible()

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()

    QTest.keyClicks(searchEdit, "first")

    previousRow = -1
    for oid in matchingCommits:
        QTest.keySequence(searchEdit, "Return")
        QTest.qWait(0)  # Give event loop a breather (for code coverage in commitlogdelegate)
        assert oid == rw.graphView.currentCommitId

        assert getGraphRow() > previousRow  # go down
        previousRow = getGraphRow()

    # end of log
    QTest.keySequence(searchEdit, "Return")
    assert getGraphRow() < previousRow  # wrap around to top of graph
    previousRow = getGraphRow()

    # select last
    lastRow = rw.graphView.clFilter.rowCount() - 1
    rw.graphView.setCurrentIndex(rw.graphView.clFilter.index(lastRow, 0))
    previousRow = lastRow

    # now search backwards
    for oid in reversed(matchingCommits):
        QTest.keySequence(searchEdit, "Shift+Return")
        assert oid == rw.graphView.currentCommitId

        assert getGraphRow() < previousRow  # go up
        previousRow = getGraphRow()

    # top of log
    QTest.keySequence(searchEdit, "Shift+Return")
    assert getGraphRow() > previousRow
    previousRow = getGraphRow()

    # escape closes search bar
    QTest.keySequence(searchEdit, "Escape")
    assert not searchBar.isVisibleTo(rw)


@pytest.mark.parametrize("rawNeedle", [
    "master.txt",
    "MaSTeR.tXt",
    "master.*",
    "aste",  # test automatic wildcards
])
def testCommitFileSearchByPath(tempDir, mainWindow, rawNeedle):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    gv = rw.graphView
    searchBar = gv.searchBar
    filterState = rw.repoModel.commitPathspecFilter

    fullRows = gv.clFilter.rowCount()
    assert not searchBar.isVisible()

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()
    triggerMenuAction(searchBar.ui.providerChooser.menu(), "path")

    assert not filterState.isReady()
    QTest.keyClicks(searchBar.lineEdit, rawNeedle)
    waitUntilTrue(filterState.isReady)
    assert len(filterState.matchingIds) == 4

    searchBar.ui.filterCheckBox.setChecked(True)
    assert gv.clFilter.rowCount() == 4

    searchBar.ui.filterCheckBox.setChecked(False)
    assert gv.clFilter.rowCount() == fullRows

    # Enable filter again before closing the searchbar
    searchBar.ui.filterCheckBox.setChecked(True)
    assert gv.clFilter.rowCount() == 4

    # Close the searchbar; this should clear the filter too
    QTest.keySequence(rw.graphView, "Escape")
    assert not searchBar.isVisible()
    assert not filterState.isReady()  # filter invalidated
    assert gv.clFilter.rowCount() == fullRows


def testCommitFileSearchReevaluatedOnNewCommits(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    gv = rw.graphView
    searchBar = gv.searchBar
    filterState = rw.repoModel.commitPathspecFilter

    oldHeadId = rw.repo.head_commit_id

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()
    triggerMenuAction(searchBar.ui.providerChooser.menu(), "path")

    assert not filterState.isReady()
    QTest.keyClicks(searchBar.lineEdit, "c/c2-2.txt")
    waitUntilTrue(filterState.isReady)
    assert oldHeadId in filterState.matchingIds

    shell("git commit --amend -m 'amending, still deleting the file being searched for'", wd)
    rw.refreshRepo()
    newHeadId = rw.repo.head_commit_id
    assert oldHeadId != newHeadId
    assert oldHeadId not in filterState.matchingIds
    assert newHeadId in filterState.matchingIds


def testCommitFileSearchInterrupted(tempDir, mainWindow, taskThread):
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)
    gv = rw.graphView
    searchBar = gv.searchBar

    a1Locator = NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1")

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()
    triggerMenuAction(searchBar.ui.providerChooser.menu(), "path")

    def isShowingBusySearchIcon():
        return "magnifying-glass-wait" in searchBar.loupe.icon().name()

    def kickOffLongSearch():
        with DelayGitCommandContext(delay=30):
            assert not rw.taskRunner.isBusy()
            QTest.keyClicks(searchBar.lineEdit, "c/c2-2.txt")
            waitUntilTrue(rw.taskRunner.isBusy)
        assert isShowingBusySearchIcon()
        assert isinstance(rw.taskRunner.currentTask, QueryCommitsTouchingPath)

    # Kick off a long search for c/c2-2.txt
    kickOffLongSearch()
    assert rw.navLocator.context.isWorkdir()  # did not jump yet

    # Interrupt current query by initiating a new search and let it finish
    searchBar.lineEdit.selectAll()
    QTest.keyClicks(searchBar.lineEdit, "a/a1")
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert not isShowingBusySearchIcon()
    assert a1Locator.isSimilarEnoughTo(rw.navLocator)

    # Search for c/c2-2.txt again
    kickOffLongSearch()

    # Interrupt current query by clearing the text
    searchBar.lineEdit.clear()
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert not isShowingBusySearchIcon()
    assert a1Locator.isSimilarEnoughTo(rw.navLocator)

    # Search for c/c2-2.txt again
    kickOffLongSearch()

    # Interrupt current query by clearing the text
    searchBar.hideOrBeep()
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert not isShowingBusySearchIcon()
    assert a1Locator.isSimilarEnoughTo(rw.navLocator)


def testCommitFileSearchReevaluatedOnWorkdirChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rm = rw.repoModel
    gv = rw.graphView
    searchBar = gv.searchBar

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()
    triggerMenuAction(searchBar.ui.providerChooser.menu(), "path")

    QTest.keyClicks(searchBar.lineEdit, "SomeNewFile.txt")
    waitUntilTrue(rm.commitPathspecFilter.isReady)
    assert searchBar.isRed()

    writeFile(f"{wd}/SomeNewFile.txt", "hello")
    rw.refreshRepo()
    assert not searchBar.isRed()

    Path(f"{wd}/SomeNewFile.txt").unlink()
    rw.refreshRepo()
    assert searchBar.isRed()


def testCommitFileSearchJumpToFuzzyPath(tempDir, mainWindow):
    loc0 = NavLocator.inUnstaged("b/b2.txt")
    loc1 = NavLocator.inCommit(Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322"), "b/b2.txt")
    loc2 = NavLocator.inCommit(Oid(hex="c070ad8c08840c8116da865b2d65593a6bb9cd2a"), "a/a2.txt")

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/aaaafirst", "hello")
    writeFile(f"{wd}/b/b2.txt", "hello")

    rw = mainWindow.openRepo(wd)
    rm = rw.repoModel
    gv = rw.graphView
    searchBar = gv.searchBar

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()
    triggerMenuAction(searchBar.ui.providerChooser.menu(), "path")

    QTest.keyClicks(searchBar.lineEdit, "*[ab]2.txt")
    waitUntilTrue(rm.commitPathspecFilter.isReady)

    # TODO: When initiating a search, and the current commit matches, stay on the commit but jump to the file
    assert rw.navLocator.context.isWorkdir()
    searchBar.ui.forwardButton.click()
    searchBar.ui.backwardButton.click()
    assert loc0.isSimilarEnoughTo(rw.navLocator)

    searchBar.ui.forwardButton.click()
    assert loc1.isSimilarEnoughTo(rw.navLocator)

    searchBar.ui.forwardButton.click()
    searchBar.ui.forwardButton.click()
    assert loc2.isSimilarEnoughTo(rw.navLocator)


def testJumpToHiddenRows(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/unstaged.txt", "hello")
    rw = mainWindow.openRepo(wd)
    gv = rw.graphView
    searchBar = gv.searchBar
    filterState = rw.repoModel.commitPathspecFilter

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()
    triggerMenuAction(searchBar.ui.providerChooser.menu(), "path")

    QTest.keyClicks(searchBar.lineEdit, "wontmatch")
    assert searchBar.ui.filterCheckBox.isVisible()
    searchBar.ui.filterCheckBox.setChecked(True)

    waitUntilTrue(filterState.isReady)
    assert gv.clFilter.rowCount() == 0

    # These should not error out although all rows are hidden
    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1"), check=True)
    rw.jump(NavLocator.inUnstaged("unstaged.txt"), check=True)


def testCommitSearchByHash(tempDir, mainWindow):
    searchCommits = [
        Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4"),
        Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"),
        Oid(hex="d31f5a60d406e831d056b8ac2538d515100c2df2"),
        Oid(hex="83d2f0431bcdc9c2fd2c17b828143be6ee4fbe80"),
        Oid(hex="2c349335b7f797072cf729c4f3bb0914ecb6dec9"),
        Oid(hex="ac7e7e44c1885efb472ad54a78327d66bfc4ecef"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    searchBar = rw.graphView.searchBar
    # In this unit test, we're going to exercise the search bar's "debounce"
    # feature, i.e. start searching automatically when the user stops typing,
    # without hitting the Return key. In the real world, debouncing occurs a
    # fraction of a second after the last key press; make this instantaneous
    # for testing.
    assert searchBar.debounceTimer.interval() == 0, "debounce interval should be instantaneous for unit tests"
    searchBar.debounceTimer.setInterval(0)
    searchEdit = searchBar.lineEdit

    assert not searchBar.isVisibleTo(rw)
    QTest.qWait(0)
    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisibleTo(rw)

    for _j in range(2):  # first run in order, second run reversed
        for _i in range(2):  # do it twice to make it wrap around
            for oid in searchCommits:
                searchEdit.selectAll()
                QTest.keyClicks(searchEdit, str(oid)[:5])
                QTest.qWait(0)  # Don't press enter and let it auto-search (pulse timer)
                assert oid == rw.graphView.currentCommitId
        searchCommits.reverse()

    # Search for a bogus commit hash
    assert not searchBar.isRed()
    searchEdit.selectAll()
    QTest.keyClicks(searchEdit, "aaabbcc")
    QTest.qWait(0)
    assert searchBar.isRed()
    assert searchBar.provider._badStem == "aaabbcc"

    # Don't expand on a bad stem
    QTest.keyClicks(searchEdit, "def")
    assert searchBar.isRed()  # must not have changed
    QTest.qWait(0)
    assert searchBar.isRed()
    assert searchBar.provider._badStem == "aaabbcc"

    # The pulse won't show an error message on its own.
    # Hit enter to bring up an error.
    assert not QToolTip.isVisible()
    QTest.keyClick(searchEdit, Qt.Key.Key_Return)
    QTest.qWait(0)  # Mac compat
    dismissToolTip("no results")


def testCommitSearchByAuthor(tempDir, mainWindow):
    # "A U Thor" has authored a ton of commits in the test repo, so take the first couple few
    searchCommits = [
        Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b"),
        Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17"),
        Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    searchBar = rw.graphView.searchBar
    searchEdit = searchBar.lineEdit

    assert not searchBar.isVisibleTo(rw)
    QTest.qWait(0)
    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisibleTo(rw)
    QTest.keyClicks(searchEdit, "a u thor")

    for oid in searchCommits:
        QTest.keySequence(searchEdit, "Return")
        QTest.qWait(0)  # Give event loop a breather (for code coverage in commitlogdelegate)
        assert oid == rw.graphView.currentCommitId


@pytest.mark.parametrize("method", ["hotkey", "contextmenu"])
def testCommitInfo(tempDir, mainWindow, method):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1, "a/a1.txt"), check=True)

    if method == "hotkey":
        rw.graphView.setFocus()
        QTest.keyClick(rw.graphView, Qt.Key.Key_Space)
    elif method == "contextmenu":
        # Use Alt modifier to bring up debug info (for coverage)
        QTest.keyPress(rw.graphView, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
        triggerContextMenuAction(rw.graphView.viewport(), "get info")
    else:
        raise NotImplementedError(f"unknown method {method}")

    dlg = findQDialog(rw, "commit info.+83834a", t=CommitInfoDialog)
    assert findTextInWidget(dlg.summaryLabel, "Merge branch 'a' into c")
    assert findTextInWidget(dlg.summaryLabel, "A U Thor")
    assert findTextInWidget(dlg.summaryLabel, str(oid1))
    dlg.accept()


def testCommitInfoJumpToParent(tempDir, mainWindow):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1, "a/a1.txt"), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "get info")
    dlg = findQDialog(rw, "commit info.+83834a", t=CommitInfoDialog)
    label = dlg.summaryLabel
    assert findTextInWidget(dlg.summaryLabel, "Merge branch 'a' into c")

    # Click on a "parent" link; this should close the dialog and jump to another commit
    parentLink = re.search(r'<a href="(.*\S+)">6462e7d.+</a>', label.text(), re.I).group(1)
    label.linkActivated.emit(parentLink)
    assert rw.navLocator.commit == Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4")


def testUncommittedChangesGraphHotkeys(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inWorkdir())

    assert rw.graphView.currentRowKind == SpecialRow.UncommittedChanges

    QTest.keyClick(rw.graphView, Qt.Key.Key_Return)
    rejectQMessageBox(rw, "empty commit")

    QTest.keyClick(rw.graphView, Qt.Key.Key_Space)
    # The mainWindow fixture will catch any leaked dialogs,
    # so if nothing happens here, we're good.


@pytest.mark.parametrize("method", ["hotkey", "contextmenu"])
def testCopyCommitHash(tempDir, mainWindow, method):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1))

    if method == "hotkey":
        rw.graphView.setFocus()
        QTest.keySequence(rw.graphView, "Ctrl+C")
    elif method == "contextmenu":
        triggerContextMenuAction(rw.graphView.viewport(), "copy/sha$")
    else:
        raise NotImplementedError(f"unknown method {method}")

    QTest.qWait(1)
    expected = str(oid1)
    if method == "hotkey":
        expected += " Merge branch 'a' into c"
    assert QApplication.clipboard().text() == expected


@pytest.mark.parametrize("method", ["hotkey", "contextmenu"])
def testCopyCommitMessage(tempDir, mainWindow, method):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1))

    if method == "hotkey":
        rw.graphView.setFocus()
        QTest.keySequence(rw.graphView, "Ctrl+Shift+C")
    elif method == "contextmenu":
        triggerContextMenuAction(rw.graphView.viewport(), "copy/message")
    else:
        raise NotImplementedError(f"unknown method {method}")

    QTest.qWait(1)
    assert QApplication.clipboard().text() == "Merge branch 'a' into c"


def testRefSortFavorsHeadBranch(tempDir, mainWindow):
    masterId = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")

    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        headCommit = repo.head_commit
        assert headCommit.id == masterId
        shell("""
            git switch -c master-2
            git commit --amend -m 'should appear above master in graph'
        """, wd, authorSig=headCommit.author, committerSig=headCommit.committer)
        amendedId = repo.branches.local["master-2"].target
        assert repo[amendedId].author.time == headCommit.author.time
        assert repo[amendedId].committer.time == headCommit.committer.time

    rw = mainWindow.openRepo(wd)
    masterIndex = rw.graphView.getFilterIndexForCommit(masterId)
    amendedIndex = rw.graphView.getFilterIndexForCommit(amendedId)
    assert amendedIndex.row() < masterIndex.row()


# @pytest.mark.skipif(WAYLAND and not OFFSCREEN, reason="wayland blocks cursor control (note: offscreen is fine)")
@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
def testCommitToolTip(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # The hash column doubles as dead space for tooltips, so pin the layout that has one
    GFApplication.applyPrefs(graphRowLayout=GraphRowLayout.HashFirst)

    sig1 = TEST_SIGNATURE
    sig2 = Signature(sig1.name, sig1.email, sig1.time + 3600, sig1.offset)

    shell("git commit --amend -m 'fairly verbose commit message that should be elided in a narrow window'", wd)

    rw = mainWindow.openRepo(wd)
    row = 1

    mainWindow.resize(1500, 600)
    QTest.qWait(0)
    with pytest.raises(TimeoutError):
        qlvSummonToolTip(rw.graphView, row, x=16)

    QTest.qWait(100)
    toolTip = qlvSummonToolTip(rw.graphView, row)
    assert "should be elided" not in toolTip
    assert "a.u.thor@example.com" in toolTip

    mainWindow.resize(300, 600)
    QTest.qWait(0)
    toolTip = qlvSummonToolTip(rw.graphView, row)
    assert "should be elided" in toolTip
    assert "a.u.thor@example.com" in toolTip

    # Amend, committer and author are different
    shell("git commit --amend -m 'AMENDED 1'", wd, authorSig=None)
    rw.refreshRepo()
    toolTip = qlvSummonToolTip(rw.graphView, row)
    toolTip = stripHtml(toolTip)
    assert re.search("^A U Thor", toolTip)
    assert re.search("Committed by.+Test Person", toolTip)

    # Amend, committer and author are the same person, but they use different times
    longMessage = "AMENDED 2\n\nand while we're here, let's cover the code path that wraps very long commit messages in tooltips, yadda yadda, filler filler"
    shell(f"git commit --amend --reset-author -m {shlex.quote(longMessage)}",
          directory=wd, authorSig=sig1, committerSig=sig2)

    rw.refreshRepo()
    toolTip = qlvSummonToolTip(rw.graphView, row)
    toolTip = stripHtml(toolTip)
    assert longMessage in toolTip
    assert "(committed)" in toolTip
    assert "(authored)" in toolTip


def testUnknownRefPrefix(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell("""
        # Write unsupported ref to a commit within the graph
        git rev-parse HEAD > .git/refs/weird

        # Write unsupported ref to a commit outside the graph
        # (Create new commit then reset master to previous HEAD)
        git branch return-here
        echo 'hello world' > toto.txt
        git add toto.txt
        git commit -m 'this commit should not appear'
        git rev-parse HEAD > .git/refs/ghost
        git reset --hard return-here
    """, wd)

    visibleOid = readOidFile(f"{wd}/.git/refs/weird")
    ghostOid = readOidFile(f"{wd}/.git/refs/ghost")

    # Painting must not raise an exception
    # (either skip the unsupported ref or draw a refbox for it, but don't crash)
    rw = mainWindow.openRepo(wd)

    assert any(c and c.id == visibleOid for c in rw.repoModel.commitSequence)
    assert not any(c and c.id == ghostOid for c in rw.repoModel.commitSequence)

    # Ghost commit can still be reached
    rw.jump(NavLocator.inCommit(ghostOid))
    assert rw.navLocator.commit == ghostOid
    assert rw.diffArea.diffBanner.isVisible()
    assert re.search(r"n.t shown in the graph", rw.diffArea.diffBanner.label.text(), re.I)


def testCommitAmendedOutsideAppVanishesFromGraph(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert rw.navLocator.context.isWorkdir()

    oldHead = rw.repo.head_commit_id
    rw.jump(NavLocator.inCommit(oldHead, "c/c2-2.txt"), check=True)

    shell("git commit --amend -m 'amended'", wd)

    rw.refreshRepo()
    newHead = rw.repo.head_commit_id
    assert newHead != oldHead
    assert newHead == rw.navLocator.commit


def testRestoreHiddenBranchOnBoot(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git switch no-parent", wd)
    Path(f"{wd}/.git/{APP_SYSTEM_NAME}.json").write_text('{ "hidePatterns": ["refs/heads/master"] }')

    rw = mainWindow.openRepo(wd)

    hiddenOid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    with pytest.raises(GraphView.SelectCommitError, match="hidden branch"):
        rw.graphView.getFilterIndexForCommit(hiddenOid)

    visibleOid = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")
    assert rw.graphView.getFilterIndexForCommit(visibleOid)


def testCommitLogFilterUpdatesAfterRebase(tempDir, mainWindow):
    wd = f"{tempDir.name}/hello"
    Path(wd).mkdir()

    def date(i):
        return f"GIT_AUTHOR_DATE=2000-01-{i:02}T12:00:00+00:00 GIT_COMMITTER_DATE=2000-01-{i:02}T12:00+00:00"

    shell(f"""
        git init -b master .
        {date(1)} git commit --allow-empty -m 'root commit'

        git switch -c donthide
        {date(2)} git commit --allow-empty -m 'hello from donthide'
        {date(3)} git commit --allow-empty -m 'hello from donthide'

        git switch master
        {date(4)} git commit --allow-empty -m 'hello from master'
        git branch rebase

        {date(5)} git commit --allow-empty -m 'hello from master - this will be hidden post-rebase'
        git branch hidethis

        {date(6)} git commit --allow-empty -m 'hello from master'

        git switch rebase
        {date(7)} git commit --allow-empty -m 'hello from rebase'
        {date(8)} git commit --allow-empty -m 'hello from rebase'
        {date(9)} git commit --allow-empty -m 'hello from rebase'
        {date(10)} git commit --allow-empty -m 'hello from rebase'
        git rev-parse HEAD > .git/rebaseTip

        git switch master
        git branch -D rebase
    """, wd)

    rebaseTip = readOidFile(f"{wd}/.git/rebaseTip")

    Path(wd, f".git/{APP_SYSTEM_NAME}.json").write_text('{ "hidePatterns": ["refs/heads/hidethis"] }')
    rw = mainWindow.openRepo(wd)

    donthideTip = rw.repo.branches.local["donthide"].target
    hidethisTip = rw.repo.branches.local["hidethis"].target

    # Initially, the tip of hidethis is visible because it's part of master
    index = rw.graphView.getFilterIndexForCommit(hidethisTip)
    assert index.isValid()

    # Simulate a rebase
    rw.repo.reset(rebaseTip, ResetMode.HARD)
    rw.refreshRepo()

    # The tip of donthide must still exist
    index = rw.graphView.getFilterIndexForCommit(donthideTip)
    assert index.isValid()

    # Now, hidethis must be gone
    with pytest.raises(GraphView.SelectCommitError):
        rw.graphView.getFilterIndexForCommit(hidethisTip)


@pytest.mark.parametrize("swapSelectionOrder", [False, True])
def testCompare2Commits(tempDir, mainWindow, swapSelectionOrder):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid2 = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    if swapSelectionOrder:
        # A/B sides must be inferred from row positions, not the order in which
        # the selection was made.
        row1, row2 = row2, row1

    # Compare 6e1475 to ce112d
    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ControlModifier)

    assert qlvGetRowData(rw.committedFiles) == ["a/a1", "c/c2-2.txt"]
    assert findTextInWidget(rw.diffArea.contextHeader.mainLabel, r"comparing.+6e1475.+ce112d")
    assert findTextInWidget(rw.diffArea.diffHeader, r"6e1475.+ce112d")
    assert rw.diffView.isVisible()


@pytest.mark.parametrize("method", ["button", "graphcm"])
def testCompare2CommitsSwapAB(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid2 = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    # Compare 6e1475 to ce112d
    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ControlModifier)

    # Swap comparison
    if method == "button":
        swapButton = next(b for b in rw.diffArea.contextHeader.findChildren(QToolButton)
                          if findTextInWidget(b, r"swap a.b"))
        swapButton.click()
    elif method == "graphcm":
        triggerContextMenuAction(rw.graphView.viewport(), r"swap a.b")
    else:
        raise NotImplementedError(f"unsupported method {method}")

    assert qlvGetRowData(rw.committedFiles) == ["a/a1", "c/c2.txt"]
    assert findTextInWidget(rw.diffArea.contextHeader.mainLabel, r"comparing.+ce112d.+6e1475")
    assert findTextInWidget(rw.diffArea.diffHeader, r"ce112d.+6e1475")


def testCompare2CommitsNoChanges(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell("""
        echo 'c2\nc2' > c/c2.txt
        git add .
        git commit -m 'restore c/c2.txt'
    """, wd)

    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="932cd9212d0c00001fcd85e35581e213c25af673")
    oid2 = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    # Compare 6e1475 to ce112d
    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ControlModifier)

    assert qlvGetRowData(rw.committedFiles) == []
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, r"no changes from.+49322bb.+to.+932cd92")


def testSelect3PlusCommits(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid2 = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    # Select all commits between 6e1475 and ce112d
    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ShiftModifier)

    assert not rw.diffView.isVisible()
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "5 items selected")

    cm = summonContextMenu(rw.graphView.viewport())
    assert cm.actions()[0].text() == "Ask AI…"
    cm.close()


def testIllegalRowComparisons(tempDir, mainWindow):
    GFApplication.applyPrefs(maxCommits=5)

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForLocator(NavLocator.inSpecial(SpecialRow.TruncatedHistory)).row()

    for a, b in [(0, row1), (0, row2), (row1, row2)]:
        qlvClickNthRow(rw.graphView, a)
        qlvClickNthRow(rw.graphView, b, modifier=Qt.KeyboardModifier.ControlModifier)

        assert not rw.diffView.isVisible()
        assert rw.specialDiffView.isVisible()
        assert findTextInWidget(rw.specialDiffView, "selected items cannot be compared")

        cm = summonContextMenu(rw.graphView.viewport())
        assert cm.actions()[0].text().lower().startswith("no actions available")
        cm.close()


def testRestoreCurrentIndexAfterGraphSplicing(tempDir, mainWindow):
    # Check out 'no-parent' before opening the repo.
    # This will create a dotted line past 'master' in the graph.
    wd = unpackRepo(tempDir)
    shell("git checkout no-parent", wd)
    rw = mainWindow.openRepo(wd)

    # Select tip of 'master' branch
    qlvClickNthRow(rw.graphView, 1)
    assert rw.graphView.currentCommitId == rw.repo.branches.local["master"].target

    # Check out 'master'. The top of the graph will be rebuilt,
    # and the selected commit must remain consistent.
    shell("git checkout master", wd)
    rw.refreshRepo()
    assert rw.graphView.currentCommitId == rw.repo.branches.local["master"].target


def testDontScrollToSameCommitOnRefresh(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Create enough commits to get scroll bars
    commands = [f"git commit --allow-empty -m bogus{i}" for i in range(200)]
    shell("\n".join(commands), wd)

    rw = mainWindow.openRepo(wd)
    vsb = rw.graphView.verticalScrollBar()

    # Ensure we've got a scroll bar and we're looking at the workdir
    assert vsb.isVisible()
    assert vsb.sliderPosition() == 0
    assert rw.graphView.navLocator.context.isWorkdir()

    # Scroll down, then refresh. The scroll bar's position shouldn't change.
    vsb.setSliderPosition(1000)
    assert vsb.sliderPosition() == 1000
    rw.refreshRepo()
    assert vsb.sliderPosition() == 1000

    # Jump to top commit. This will scroll it into view.
    rw.jump(NavLocator.inCommit(rw.repo.head_commit_id), check=True)
    assert vsb.sliderPosition() < 1000

    # Scroll down, then refresh. The scroll bar's position shouldn't change.
    vsb.setSliderPosition(1000)
    rw.refreshRepo()
    assert vsb.sliderPosition() == 1000


def spyOnMessageColumn(graphView) -> list[tuple]:
    """Record (commit id, left edge) for every commit message painted from now on."""

    painted = []
    delegate = graphView.clDelegate
    realPaint = delegate._paintCommitMessage

    def spy(painter, rect, commit):
        painted.append((commit.id, rect.left()))
        return realPaint(painter, rect, commit)

    delegate._paintCommitMessage = spy
    return painted


def testGraphFirstLayoutAlignsCommitMessages(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.resize(800, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    refsAt = rw.repoModel.refsAt

    def messageLefts():
        """Left edge of the messages on rows that carry no ref indicators."""
        return {left for oid, left in painted if oid not in refsAt}

    # Classic layout: the graph indents each message a little differently
    GFApplication.applyPrefs(graphRowLayout=GraphRowLayout.HashFirst)
    QTest.qWait(0)
    painted = spyOnMessageColumn(graphView)
    graphView.viewport().repaint()
    assert len(messageLefts()) > 1, "classic layout is expected to indent messages"

    # Graph first: the graph gets a column of its own, so messages line up
    GFApplication.applyPrefs(graphRowLayout=GraphRowLayout.GraphFirst)
    QTest.qWait(0)
    painted = spyOnMessageColumn(graphView)
    graphView.viewport().repaint()  # may widen the reserved graph column
    painted.clear()
    graphView.viewport().repaint()
    lefts = messageLefts()
    assert len(painted) > 1, "expecting several rows on screen"
    assert len(lefts) == 1, f"messages should all start at the same x, got {sorted(lefts)}"


def testGraphFirstLayoutMovesHashNextToAuthor(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.resize(1400, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    # The graph must be roomy enough to keep its hash column, however wide the sidebar is
    assert graphView.viewport().width() - 2 * XMARGIN > NARROW_WIDTH[1]

    hashLefts = []
    delegate = graphView.clDelegate
    delegate._paintHash = lambda painter, rect, oid: hashLefts.append(rect.left())

    GFApplication.applyPrefs(graphRowLayout=GraphRowLayout.HashFirst)
    QTest.qWait(0)
    graphView.viewport().repaint()
    assert hashLefts, "the classic layout opens the row with the hash"
    assert max(hashLefts) < 100

    hashLefts.clear()
    GFApplication.applyPrefs(graphRowLayout=GraphRowLayout.GraphFirst)
    QTest.qWait(0)
    graphView.viewport().repaint()
    assert hashLefts, "the hash is still painted, just elsewhere"
    assert min(hashLefts) > graphView.viewport().width() // 2


def testNarrowWindowDropsHashColumn(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    GFApplication.applyPrefs(graphRowLayout=GraphRowLayout.GraphFirst)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView

    hashesPainted = []
    graphView.clDelegate._paintHash = lambda *args: hashesPainted.append(args)

    mainWindow.resize(600, 600)
    QTest.qWait(0)
    graphView.viewport().repaint()
    assert not hashesPainted, "a cramped window gives the room to the message"


def testGraphColumnStopsGrowingAtMaxWidth(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    GFApplication.applyPrefs(graphRowLayout=GraphRowLayout.GraphFirst)
    rw = mainWindow.openRepo(wd)
    delegate = rw.graphView.clDelegate

    delegate.reserveGraphColumns(MAX_GRAPH_COLUMNS + 10)
    assert delegate.graphColumns == MAX_GRAPH_COLUMNS

    # Never shrinks back, so the messages don't dance around while scrolling
    delegate.reserveGraphColumns(1)
    assert delegate.graphColumns == MAX_GRAPH_COLUMNS

    # ...but a repo reload starts over from a sane default
    delegate.invalidateMetrics()
    assert delegate.graphColumns == MIN_GRAPH_COLUMNS


def testAuthorAvatarInitials():
    def sig(name, email="someone@example.com"):
        return Signature(name, email)

    assert avatarInitials(sig("Fiodor Songurov")) == "FS"
    assert avatarInitials(sig("A U Thor")) == "AT"  # first and last word
    assert avatarInitials(sig("cher")) == "CH"
    assert avatarInitials(sig("jean-luc picard")) == "JP"
    assert avatarInitials(sig(".", "zoe@example.com")) == "ZO"  # nothing usable in the name


def testAuthorAvatarColorIsStablePerPerson():
    alice = Signature("Alice", "alice@example.com")
    aliceAgain = Signature("Alice Different Name", "ALICE@example.com")
    bob = Signature("Bob", "bob@example.com")

    assert avatarColor(alice) == avatarColor(aliceAgain), "the email keys the color, and case doesn't count"
    assert avatarColor(alice) != avatarColor(bob)


def testAuthorAvatarsTakeRoomFromTheAuthorColumn(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.resize(1000, 600)
    rw = mainWindow.openRepo(wd)
    delegate = rw.graphView.clDelegate

    GFApplication.applyPrefs(showAvatars=False)
    QTest.qWait(0)
    rw.graphView.viewport().repaint()
    withoutAvatars = delegate.authorMaxWidth

    GFApplication.applyPrefs(showAvatars=True)
    QTest.qWait(0)
    rw.graphView.viewport().repaint()
    assert delegate.authorMaxWidth > withoutAvatars


def testRefboxPaletteHasAHandPickedColorForEachTheme():
    from gitfourchette.graphview.commitlogdelegate import REFBOXES, RefBox

    localBranch = next(b for b in REFBOXES if b.prefix == RefPrefix.HEADS)
    fallback = QColor("#123456")

    assert localBranch.penColor(dark=False, fallback=fallback) == localBranch.color
    assert localBranch.penColor(dark=True, fallback=fallback) == localBranch.darkColor

    # A box without a dark variant is brightened, and one without any color
    # of its own just writes in the current pen color
    plain = RefBox("whatever", color=QColor("#204060"))
    assert plain.penColor(dark=True, fallback=fallback) == QColor("#204060").lighter(300)
    assert RefBox("whatever").penColor(dark=False, fallback=fallback) == fallback


def testDownloadedAvatarsReachTheHistory(tempDir, mainWindow, monkeypatch):
    """With downloads on, the history draws the picture we have for an author."""

    wd = unpackRepo(tempDir)
    mainWindow.resize(1000, 600)
    GFApplication.applyPrefs(showAvatars=True, downloadAvatars=True)
    rw = mainWindow.openRepo(wd)

    cache = GFApplication.instance().avatarCache
    cache.urlFor = lambda sig: ""  # no network in tests

    picture = QPixmap(64, 64)
    picture.fill(QColor("#ff8800"))
    cache.pixmaps["a.u.thor@example.com"] = picture

    pictures = []
    monkeypatch.setattr(
        "gitfourchette.graphview.commitlogdelegate.paintAvatar",
        lambda painter, rect, signature, pic=None: pictures.append(pic))

    rw.graphView.viewport().repaint()
    assert any(p is picture for p in pictures), "the author's picture should have been drawn"


def testCommitSearchByAuthorAndDate(tempDir, mainWindow):
    alice = Signature("Alice Liddell", "alice@example.com", 1600000000, 0)  # 2020-09-13
    bob = Signature("Bob Marley", "bob@example.com", 1700000000, 0)  # 2023-11-14

    wd = unpackRepo(tempDir)
    shell("echo hole > hole.txt && git add . && git commit -m 'Fix the rabbit hole'", wd, authorSig=alice)
    shell("echo birds > birds.txt && git add . && git commit -m 'Add three little birds'", wd, authorSig=bob)

    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    searchBar = graphView.searchBar

    aliceCommit = rw.repo.revparse_single("HEAD~1").id
    bobCommit = rw.repo.head_commit_id

    def search(term):
        searchBar.lineEdit.clear()
        QTest.keyClicks(searchBar.lineEdit, term)
        QTest.keySequence(searchBar.lineEdit, "Return")

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()

    search("author:alice")
    assert graphView.currentCommitId == aliceCommit

    search("by:bob")
    assert graphView.currentCommitId == bobCommit

    # A date on its own
    search("after:2023")
    assert graphView.currentCommitId == bobCommit

    search("before:2021")
    assert graphView.currentCommitId == aliceCommit

    # Author and date together
    search("author:bob after:2023")
    assert graphView.currentCommitId == bobCommit

    search("author:bob before:2021")
    assert searchBar.isRed(), "Bob committed nothing back then"

    # A date we can't read says so instead of quietly finding nothing
    search("after:whenever")
    assert searchBar.isRed()


def testFilterCommitLogByAuthor(tempDir, mainWindow):
    alice = Signature("Alice Liddell", "alice@example.com", 1600000000, 0)
    bob = Signature("Bob Marley", "bob@example.com", 1700000000, 0)

    wd = unpackRepo(tempDir)
    shell("echo hole > hole.txt && git add . && git commit -m 'Fix the rabbit hole'", wd, authorSig=alice)
    shell("echo birds > birds.txt && git add . && git commit -m 'Add three little birds'", wd, authorSig=bob)

    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    searchBar = graphView.searchBar
    fullRows = graphView.clFilter.rowCount()

    def visibleCommits():
        model = graphView.clFilter
        oids = (model.data(model.index(row, 0), CommitLogModel.Role.Oid) for row in range(model.rowCount()))
        return {oid for oid in oids if oid is not None and oid != UC_FAKEID}

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.ui.filterCheckBox.isVisible(), "the commit search can narrow the log down too"

    QTest.keyClicks(searchBar.lineEdit, "author:alice")
    searchBar.ui.filterCheckBox.setChecked(True)
    assert visibleCommits() == {rw.repo.revparse_single("HEAD~1").id}

    # Narrowing further leaves nothing but the working directory row
    QTest.keyClicks(searchBar.lineEdit, " after:2023")
    assert not visibleCommits()

    searchBar.ui.filterCheckBox.setChecked(False)
    assert graphView.clFilter.rowCount() == fullRows

    # Closing the search bar puts the log back
    searchBar.ui.filterCheckBox.setChecked(True)
    QTest.keySequence(graphView, "Escape")
    assert not searchBar.isVisible()
    assert graphView.clFilter.rowCount() == fullRows


# -----------------------------------------------------------------------------
# Commits that aren't on any remote yet


def unpushedIds(repo: Repo, *revs: str) -> set[Oid]:
    return {repo.revparse_single(rev).peel(Commit).id for rev in revs}


#   L3 ┯          main (local)
#   L2 ┿
#    M ┿─╮        merge commit
#   F1 │ ┿        feature branch
#   L1 ┿ │
#   R1 ┿─╯
#   R0 ┷
UNPUSHED_GRAPH = "L3:L2 L2:M M:L1,F1 F1:R1 L1:R1 R1:R0 R0"


@pytest.mark.parametrize(("localTips", "remoteTips", "expected"), [
    ("L3", "R1", "L3 L2 M F1 L1"),  # both parents of an unpushed merge are unpushed
    ("L3", "F1", "L3 L2 M L1"),  # the feature branch is on a remote, not the merge
    ("L3", "M", "L3 L2"),  # pushed up to the merge: its parents are on the remote too
    ("L3", "L3", ""),  # up to date
    ("L3 F1", "R0", "L3 L2 M F1 L1 R1"),  # the remote branch is behind
    ("F1", "R1", "F1"),  # a branch that was never pushed
    ("L3", "", ""),  # nothing to compare against
    ("", "R1", ""),  # no local branches
])
def testFindUnpushedCommits(localTips, remoteTips, expected):
    sequence, _heads = GraphDiagram.parseDefinition(UNPUSHED_GRAPH)
    unpushed = findUnpushedCommits(sequence, MockOid.encodeAll(localTips.split()), MockOid.encodeAll(remoteTips.split()))
    assert unpushed == set(MockOid.encodeAll(expected.split()))


def testFindUnpushedCommitsOnlyWalksTheDifference():
    sequence, _heads = GraphDiagram.parseDefinition(UNPUSHED_GRAPH)
    walked = []

    def walk():
        for commit in sequence:
            walked.append(commit.id)
            yield commit

    unpushed = findUnpushedCommits(walk(), MockOid.encodeAll(["L3"]), MockOid.encodeAll(["M"]))
    assert unpushed == set(MockOid.encodeAll(["L3", "L2"]))
    assert walked == MockOid.encodeAll(["L3", "L2", "M"]), "no need to look past the remote branch"


def testFindUnpushedCommitsInTruncatedHistory():
    sequence, _heads = GraphDiagram.parseDefinition(UNPUSHED_GRAPH)
    truncated = sequence[:3]  # L3 L2 M
    unpushed = findUnpushedCommits(truncated, MockOid.encodeAll(["L3"]), MockOid.encodeAll(["R1"]))
    assert unpushed == set(MockOid.encodeAll(["L3", "L2", "M"]))


def testUnpushedCommitsFollowRemoteBranches(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    # master is 2 commits ahead of origin/master; no-parent is up to date with origin/no-parent
    assert rw.repoModel.unpushedCommits == unpushedIds(repo, "master", "master~1")

    # A new local commit
    shell("git commit --allow-empty -m 'new local commit'", wd)
    rw.refreshRepo()
    assert rw.repoModel.unpushedCommits == unpushedIds(repo, "master", "master~1", "master~2")

    # Simulate a push: the remote-tracking branch catches up with master
    shell("git update-ref refs/remotes/origin/master master", wd)
    rw.refreshRepo()
    assert not rw.repoModel.unpushedCommits

    # A branch that was never pushed
    shell("git switch -c never-pushed origin/first-merge && git commit --allow-empty -m 'wip'", wd)
    rw.refreshRepo()
    assert rw.repoModel.unpushedCommits == unpushedIds(repo, "never-pushed")

    # A local merge commit that brings in a commit that was never pushed
    shell("git switch master && git merge --no-ff -m 'local merge' never-pushed", wd)
    rw.refreshRepo()
    assert rw.repoModel.unpushedCommits == unpushedIds(repo, "master", "never-pushed")

    # A local merge commit that only brings in commits that are on a remote already
    shell("""
        git switch -c other origin/first-merge
        git commit --allow-empty -m 'somebody else pushed this'
        git update-ref refs/remotes/origin/other HEAD
        git switch master
        git branch -D other never-pushed
        git reset --hard origin/master
        git merge --no-ff -m 'merge remote branch' origin/other
    """, wd)
    rw.refreshRepo()
    assert rw.repoModel.unpushedCommits == unpushedIds(repo, "master")


def testUnpushedCommitsOnDetachedHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git switch --detach origin/master", wd)
    rw = mainWindow.openRepo(wd)

    assert rw.repoModel.headIsDetached
    assert rw.repoModel.unpushedCommits == unpushedIds(rw.repo, "master", "master~1"), "HEAD is on the remote"

    shell("git commit --allow-empty -m 'made on a detached head'", wd)
    rw.refreshRepo()
    assert rw.repoModel.unpushedCommits == unpushedIds(rw.repo, "HEAD", "master", "master~1")


def testNoUnpushedCommitsWithoutRemoteBranches(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git remote remove origin", wd)
    rw = mainWindow.openRepo(wd)

    assert not any(ref.startswith(RefPrefix.REMOTES) for ref in rw.repoModel.refs)
    assert not rw.repoModel.unpushedCommits, "without remote branches, there's nothing to compare against"

    shell("git commit --allow-empty -m 'new local commit'", wd)
    rw.refreshRepo()
    assert not rw.repoModel.unpushedCommits


def spyOnGraphFrames(graphView, monkeypatch) -> dict[Oid, QRect]:
    """Record where the graph is painted on each row from now on."""
    painted = {}
    realPaint = commitlogdelegate.paintGraphFrame

    def spy(painter, rect, oid, *args, **kwargs):
        painted[oid] = QRect(rect)  # copy before paintGraphFrame modifies it
        return realPaint(painter, rect, oid, *args, **kwargs)

    monkeypatch.setattr(commitlogdelegate, "paintGraphFrame", spy)
    return painted


def bulletPoint(repoModel, oid: Oid, graphRect: QRect) -> tuple[QPoint, QColor]:
    """Center of a commit's bullet point (same math as paintGraphFrame) and its lane color."""
    frame = repoModel.graph.getCommitFrame(oid)
    lanes, numColumns = flattenLanes(frame, repoModel.hiddenCommits)
    column, _numColumns = getCommitBulletColumn(frame.homeLane(), numColumns, lanes)
    x = graphRect.left() + LANE_WIDTH // 2 + column * LANE_WIDTH
    y = (graphRect.top() + graphRect.top() + graphRect.height()) // 2
    return QPoint(x, y), getColor(frame.homeLane())


def colorDistance(a: QColor, b: QColor) -> int:
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()))


def grabAt1x(widget: QWidget) -> QImage:
    """Paint a widget into an image at 1x, whatever the screen's scale."""
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.setDevicePixelRatio(1)
    widget.render(image)
    return image


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("layout", [GraphRowLayout.GraphFirst, GraphRowLayout.HashFirst])
def testUnpushedCommitsHaveHollowBulletPoints(tempDir, mainWindow, monkeypatch, layout, theme):
    wd = unpackRepo(tempDir)
    GFApplication.applyPrefs(graphRowLayout=layout, qtStyle=formatStyle(ThemeName.BuiltIn, theme))
    mainWindow.resize(1200, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    repoModel = rw.repoModel
    repo = rw.repo

    unpushedOid = repo.revparse_single("master").id
    pushedOid = repo.revparse_single("origin/master").id
    assert unpushedOid in repoModel.unpushedCommits
    assert pushedOid not in repoModel.unpushedCommits

    painted = spyOnGraphFrames(graphView, monkeypatch)

    def sample(oid: Oid):
        """
        At 1x: the row's background, left of the graph; the pixels across
        the bullet point's middle, horizontally and vertically; the pixels
        where a ring's stroke goes, on either side; and the lane's color.
        """
        image = grabAt1x(graphView.viewport())
        center, laneColor = bulletPoint(repoModel, oid, painted[oid])
        x, y = center.x(), center.y()
        # The bullet point's center is a pixel corner: the 6 pixels from x-3
        # to x+2 are the ones inside a hole of radius 3.
        background = image.pixelColor(2, y)
        across = [image.pixelColor(x + d, y) for d in range(-3, 3)]
        down = [image.pixelColor(x, y + d) for d in range(-3, 3)]
        ring = [image.pixelColor(x + d, y) for d in (-5, -4, 3, 4)]
        return background, across, down, ring, laneColor

    def assertHollow(oid: Oid, holeColor: QColor):
        _background, across, down, ring, laneColor = sample(oid)
        assert all(colorDistance(p, laneColor) < 32 for p in ring), "the ring is in the lane's color"
        assert all(colorDistance(p, holeColor) < 32 for p in across), "a hole 6 px wide"
        assert all(colorDistance(p, holeColor) < 32 for p in down), "the lane's line doesn't show in the hole"

    # Commit that isn't on any remote: a ring in the lane color, around a
    # hole that shows the background and is wide enough to tell at 1x
    background, _across, _down, _ring, _laneColor = sample(unpushedOid)
    assertHollow(unpushedOid, holeColor=background)

    # Pushed commit: a solid dot
    _background, across, _down, _ring, laneColor = sample(pushedOid)
    assert all(colorDistance(p, laneColor) < 32 for p in across[1:5])

    # On a selected row, the hole keeps the color that outlines every line
    # and bullet point in the graph, so it stands out from the ring even if
    # the accent color is the lane's
    rw.jump(NavLocator.inCommit(unpushedOid))
    assert graphView.currentCommitId == unpushedOid
    base = graphView.palette().color(QPalette.ColorRole.Base)
    selected, _across, _down, _ring, laneColor = sample(unpushedOid)
    assert colorDistance(selected, base) > 32, "expecting a highlighted row"
    assertHollow(unpushedOid, holeColor=base)
    GFApplication.applyPrefs(qtStyle=formatStyle(ThemeName.BuiltIn, theme, laneColor.name()))
    selected, _across, _down, _ring, laneColor = sample(unpushedOid)
    assert colorDistance(selected, laneColor) < 32, "expecting a row highlighted in the lane's color"
    assertHollow(unpushedOid, holeColor=base)

    # Once the commits are pushed, the bullet point is solid again
    shell("git update-ref refs/remotes/origin/master master", wd)
    rw.refreshRepo()
    assert not repoModel.unpushedCommits
    _background, across, _down, _ring, laneColor = sample(unpushedOid)
    assert all(colorDistance(p, laneColor) < 32 for p in across[1:5])


def testNoHollowBulletPointsWithoutRemoteBranches(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    shell("git remote remove origin", wd)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView

    painted = spyOnGraphFrames(graphView, monkeypatch)
    graphView.viewport().repaint()
    image = graphView.viewport().grab().toImage()
    dpr = image.devicePixelRatio()

    oids = [c.id for c in rw.repoModel.commitSequence[1:4]]
    assert all(oid in painted for oid in oids), "expecting the top rows on screen"
    for oid in oids:
        center, laneColor = bulletPoint(rw.repoModel, oid, painted[oid])
        middle = image.pixelColor(int(center.x() * dpr), int(center.y() * dpr))
        assert colorDistance(middle, laneColor) < 32, f"{oid} should have a solid bullet point"


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with tooltips, but Qt 6 is fine")
@pytest.mark.parametrize("layout", [GraphRowLayout.GraphFirst, GraphRowLayout.HashFirst])
def testUnpushedCommitToolTip(tempDir, mainWindow, monkeypatch, layout):
    wd = unpackRepo(tempDir)
    GFApplication.applyPrefs(graphRowLayout=layout)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    repo = rw.repo

    painted = spyOnGraphFrames(graphView, monkeypatch)
    graphView.viewport().repaint()

    def rowOf(rev):
        oid = repo.revparse_single(rev).id
        index = graphView.getFilterIndexForCommit(oid)
        center, _laneColor = bulletPoint(rw.repoModel, oid, painted[oid])
        return index.row(), center.x()

    row, x = rowOf("master")
    toolTip = qlvSummonToolTip(graphView, row, x=x)
    assert re.search(r"isn.t on any remote yet", toolTip)

    row, x = rowOf("origin/master")
    with pytest.raises(TimeoutError):
        qlvSummonToolTip(graphView, row, x=x)


# -----------------------------------------------------------------------------
# How many commits a branch has to push, on its chip in the graph


def drawnText(graphView: GraphView, monkeypatch, oid: Oid) -> list[tuple[QRectF, str]]:
    """Repaint the graph, and return the text drawn on a commit's row and where."""
    rowRect = QRectF(graphView.visualRect(graphView.getFilterIndexForCommit(oid)))
    drawn = []
    realDrawText = QPainter.drawText

    def spy(painter, *args):
        where = args[0]
        if isinstance(where, QRect | QRectF):
            where = QRectF(where)
            if rowRect.contains(where.center()):
                drawn.append((where, next(a for a in reversed(args) if isinstance(a, str))))
        return realDrawText(painter, *args)

    with monkeypatch.context() as m:
        m.setattr(QPainter, "drawText", spy)
        graphView.viewport().repaint()

    return drawn


def aheadOnChip(graphView: GraphView, monkeypatch, oid: Oid) -> list[str]:
    """Counts of commits to push drawn on a commit's row."""
    return [text for _rect, text in drawnText(graphView, monkeypatch, oid) if text.startswith(SYMBOL_AHEAD)]


def testBranchChipSaysHowManyCommitsToPush(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    # Two branches that were never pushed: side has 1 commit, and solo has 1
    # of its own, side's, and the merge commit
    shell("""
        git switch --no-track -c side origin/first-merge
        git commit --allow-empty -m 'side 1'
        git switch --no-track -c solo origin/first-merge
        git commit --allow-empty -m 'solo 1'
        git merge --no-ff -m 'merge side into solo' side
        git switch master
    """, wd)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    repo = rw.repo
    repoModel = rw.repoModel

    def tip(branch):
        return repo.branches.local[branch].target

    # master is 2 commits ahead of its upstream, as the sidebar says
    assert repoModel.aheadBehind["master"] == (2, 0)
    assert repoModel.countUnpushed("master") == (2, "origin/master")
    assert aheadOnChip(graphView, monkeypatch, tip("master")) == [f"{SYMBOL_AHEAD}2"]

    # Without an upstream, the count is of the branch's commits that aren't
    # on any remote - not of every unpushed commit in the repo
    assert repoModel.countUnpushed("solo") == (3, "")
    assert repoModel.countUnpushed("side") == (1, "")
    assert aheadOnChip(graphView, monkeypatch, tip("solo")) == [f"{SYMBOL_AHEAD}3"]
    assert aheadOnChip(graphView, monkeypatch, tip("side")) == [f"{SYMBOL_AHEAD}1"]

    # An upstream that is gone counts as no upstream
    shell("git config branch.side.remote origin && git config branch.side.merge refs/heads/gone", wd)
    rw.refreshRepo()
    assert repoModel.upstreams["side"] == "origin/gone"
    assert repoModel.countUnpushed("side") == (1, "")

    # A branch that's up to date shows nothing extra
    shell("git update-ref refs/remotes/origin/master master", wd)
    rw.refreshRepo()
    assert repoModel.countUnpushed("master") == (0, "origin/master")
    assert aheadOnChip(graphView, monkeypatch, tip("master")) == []
    chipText = [text for _rect, text in drawnText(graphView, monkeypatch, tip("master")) if "master" in text]
    assert chipText == ["master"], "the name alone"

    # Once pushed somewhere, a branch without upstream has nothing to count
    shell("git update-ref refs/remotes/origin/solo solo", wd)
    rw.refreshRepo()
    assert repoModel.countUnpushed("solo") == (0, "")
    assert repoModel.countUnpushed("side") == (0, ""), "side was merged into solo"
    assert aheadOnChip(graphView, monkeypatch, tip("solo")) == []


def testBranchChipCountWithIconsOnly(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    GFApplication.applyPrefs(refBoxMaxWidth=GraphRefBoxWidth.IconsOnly)
    rw = mainWindow.openRepo(wd)
    oid = rw.repo.branches.local["master"].target
    drawn = [text for _rect, text in drawnText(rw.graphView, monkeypatch, oid) if "master" in text or text.startswith(SYMBOL_AHEAD)]
    assert drawn == [f"{SYMBOL_AHEAD}2"], "the name gives way to the icon, not the count"


def testNoCountOnBranchChipsWithoutRemoteBranches(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    shell("git remote remove origin && git commit --allow-empty -m 'new local commit'", wd)
    rw = mainWindow.openRepo(wd)
    oid = rw.repo.branches.local["master"].target
    assert rw.repoModel.countUnpushed("master") == (0, "")
    assert aheadOnChip(rw.graphView, monkeypatch, oid) == []


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with tooltips, but Qt 6 is fine")
def testBranchChipCountToolTip(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    shell("git switch --no-track -c never-pushed origin/first-merge && git commit --allow-empty -m 'wip' && git switch master", wd)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView

    def toolTipOnCount(branch):
        oid = rw.repo.branches.local[branch].target
        rect, _text = next((r, t) for r, t in drawnText(graphView, monkeypatch, oid) if t.startswith(SYMBOL_AHEAD))
        row = graphView.getFilterIndexForCommit(oid).row()
        return qlvSummonToolTip(graphView, row, x=int(rect.right()) - 2)

    toolTip = toolTipOnCount("master")
    assert "refs/heads/master" in toolTip
    assert "2 commits not pushed to origin/master" in toolTip

    toolTip = toolTipOnCount("never-pushed")
    assert "refs/heads/never-pushed" in toolTip
    assert "1 commit not pushed to any remote" in toolTip
    assertTranslatedInForkLanguages("{n} commit not pushed to any remote", plural="{n} commits not pushed to any remote")


# -----------------------------------------------------------------------------
# One bright column: the message leads, author, hash and date recede


@dataclasses.dataclass
class DrawnRun:
    rect: QRectF
    text: str
    color: QColor
    bold: bool


def pointerAway(graphView: GraphView):
    """Take the pointer off the graph (the row under it shows its details at full strength)."""
    leave = QHoverEvent(QEvent.Type.HoverLeave, QPointF(-1, -1), QPointF(-1, -1), QPointF(-1, -1))
    QApplication.sendEvent(graphView.viewport(), leave)


def drawnRuns(graphView: GraphView, monkeypatch, oid: Oid, keepHover=False) -> list[DrawnRun]:
    """Repaint the graph, and return the text drawn on a commit's row, where, in which color and weight."""
    if not keepHover:
        pointerAway(graphView)
    rowRect = QRectF(graphView.visualRect(graphView.getFilterIndexForCommit(oid)))
    drawn = []
    realDrawText = QPainter.drawText

    def spy(painter, *args):
        where = args[0]
        if isinstance(where, QRect | QRectF) and painter.device() is graphView.viewport():
            where = QRectF(where)
            if rowRect.contains(where.center()):
                text = next(a for a in reversed(args) if isinstance(a, str))
                drawn.append(DrawnRun(where, text, QColor(painter.pen().color()), painter.font().bold()))
        return realDrawText(painter, *args)

    with monkeypatch.context() as m:
        m.setattr(QPainter, "drawText", spy)
        graphView.viewport().repaint()

    return drawn


def rowParts(runs: list[DrawnRun], commit: Commit) -> dict[str, list[DrawnRun]]:
    """Sort a row's text into its message, author, hash and date."""
    summary = commit.message.splitlines()[0]
    hashText = str(commit.id)[:7]
    parts = {"message": [], "author": [], "hash": [], "date": []}
    for run in runs:
        if not run.text.strip():
            continue
        if run.text.startswith(summary[:10]):
            parts["message"].append(run)
        elif run.text.startswith(commit.author.name):
            parts["author"].append(run)
        elif len(run.text) == 1 and run.text in hashText and not parts["date"]:
            parts["hash"].append(run)
        elif parts["hash"]:
            parts["date"].append(run)
    return parts


def rowBackground(graphView: GraphView, row: int) -> QColor:
    """Color of a row's background, sampled in the gap between its message and its author."""
    image = grabAt1x(graphView.viewport())
    rect = graphView.visualRect(graphView.model().index(row, 0))
    return image.pixelColor(rect.left() + rect.width() * 2 // 3, rect.center().y())


@pytest.mark.parametrize("theme", ["light", "dark"])
def testAuthorHashAndDateRecedeBehindTheMessage(tempDir, mainWindow, monkeypatch, theme):
    wd = unpackRepo(tempDir)
    GFApplication.applyPrefs(qtStyle=formatStyle(ThemeName.BuiltIn, theme))
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    commit = rw.repo.revparse_single("master~1").peel(Commit)
    assert commit.id != rw.repoModel.headCommitId

    palette = graphView.palette()
    grounds = [palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.AlternateBase)]

    parts = rowParts(drawnRuns(graphView, monkeypatch, commit.id), commit)
    assert all(parts.values()), f"expecting every column on the row: {parts}"
    messageColor = parts["message"][0].color
    metaColors = {run.color.name() for key in ("author", "hash", "date") for run in parts[key]}
    assert len(metaColors) == 1, "author, hash and date share one secondary tone"
    metaColor = QColor(metaColors.pop())
    for ground in grounds:
        assert contrastRatio(metaColor, ground) >= 4.5, "secondary, but readable (WCAG AA)"
        assert contrastRatio(metaColor, ground) < contrastRatio(messageColor, ground) - 2, "dimmer than the message"

    # On the selected row, everything takes the selection's text color
    rw.jump(NavLocator.inCommit(commit.id))
    graphView.setFocus()
    parts = rowParts(drawnRuns(graphView, monkeypatch, commit.id), commit)
    highlightedText = palette.color(QPalette.ColorRole.HighlightedText)
    assert {run.color.name() for runs in parts.values() for run in runs} == {highlightedText.name()}


def testOnlyTheMessageIsBoldOnTheCheckedOutCommit(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    commit = rw.repo.head_commit

    parts = rowParts(drawnRuns(rw.graphView, monkeypatch, commit.id), commit)
    assert all(parts.values()), f"expecting every column on the row: {parts}"
    assert all(run.bold for run in parts["message"])
    assert not any(run.bold for key in ("author", "hash", "date") for run in parts[key])


def testSummaryIsNotFollowedByAnElisionMarker(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    shell("git commit --allow-empty -m 'Summary line' -m 'The body mentions a needle.'", wd)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    oid = rw.repo.head_commit_id

    messages = [run for run in drawnRuns(graphView, monkeypatch, oid) if run.text.startswith("Summary")]
    assert [run.text for run in messages] == ["Summary line"], "no ' […]' on every commit that has a body"

    # The body is still one hover away
    row = graphView.getFilterIndexForCommit(oid).row()
    x = int(messages[0].rect.center().x())
    assert "The body mentions a needle." in qlvSummonToolTip(graphView, row, x=x)

    # A search that only matches in the body still shows where the match went
    QTest.keySequence(mainWindow, "Ctrl+F")
    QTest.keyClicks(graphView.searchBar.lineEdit, "needle")
    messages = [run.text for run in drawnRuns(graphView, monkeypatch, oid) if run.text.startswith("Summary")]
    assert messages == ["Summary line […]"]


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with tooltips, but Qt 6 is fine")
def testDateAsteriskIsAnExplainedFootnote(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    rewritten = Signature(TEST_SIGNATURE.name, TEST_SIGNATURE.email, TEST_SIGNATURE.time + 3600, TEST_SIGNATURE.offset)
    shell("git commit --allow-empty -m 'Rebased commit'", wd, committerSig=rewritten)
    GFApplication.applyPrefs(authorDiffAsterisk=True)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    commit = rw.repo.head_commit
    graphView.setCurrentIndex(graphView.model().index(0, 0))  # keep the commit's row unselected

    parts = rowParts(drawnRuns(graphView, monkeypatch, commit.id), commit)
    dateRuns = parts["date"]
    assert [run.text for run in dateRuns][-1] == "*", "the asterisk is drawn on its own"
    assert not dateRuns[0].text.endswith("*")
    assert not any(run.bold for run in dateRuns), "regular weight, even on the checked-out commit"
    assert dateRuns[-1].color == parts["hash"][0].color, "in the secondary tone"

    # Hovering the date says what the asterisk means
    row = graphView.getFilterIndexForCommit(commit.id).row()
    toolTip = stripHtml(qlvSummonToolTip(graphView, row, x=int(dateRuns[0].rect.center().x())))
    assert re.search(r"^\* Rebased or amended .+ \(first written .+\)", toolTip)
    assert "Test Person" in toolTip, "followed by the author's details, as before"

    # A date without an asterisk explains nothing
    GFApplication.applyPrefs(authorDiffAsterisk=False)
    QTest.qWait(0)
    toolTip = stripHtml(qlvSummonToolTip(graphView, row, x=int(dateRuns[0].rect.center().x())))
    assert "Rebased" not in toolTip
    assert "Test Person" in toolTip

    assertTranslatedInForkLanguages("Rebased or amended {0} (first written {1})",
                                    "Mark rebased, amended or re-committed commits with *")


def testRowsAreBandedAndFollowThePointer(tempDir, mainWindow, monkeypatch):
    assert Prefs().alternatingRowColors, "banded rows by default"

    wd = unpackRepo(tempDir)
    GFApplication.applyPrefs(qtStyle=formatStyle(ThemeName.BuiltIn, "dark"))
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    assert graphView.alternatingRowColors()
    assert rowBackground(graphView, 3) != rowBackground(graphView, 4), "alternate rows"
    assert rowBackground(graphView, 3) == rowBackground(graphView, 5)

    # The row under the pointer is highlighted too (a plain mouse move, as the system sends it)
    plain = rowBackground(graphView, 5)
    pointAtRow(graphView, 5)
    assert rowBackground(graphView, 5) != plain

    # ...and brings its author, hash and date forward
    oid = graphView.model().index(5, 0).data(CommitLogModel.Role.Oid)
    parts = rowParts(drawnRuns(graphView, monkeypatch, oid, keepHover=True), rw.repo.peel_commit(oid))
    text = graphView.palette().color(QPalette.ColorRole.Text)
    assert parts["author"][0].color == text
    assert parts["date"][0].color == text


def pointAtRow(graphView: GraphView, row: int):
    """Move the mouse onto a row, from the row above it, with plain mouse moves."""
    viewport = graphView.viewport()
    QTest.mouseMove(viewport, graphView.visualRect(graphView.model().index(row - 1, 0)).center())
    QTest.qWait(0)
    QTest.mouseMove(viewport, graphView.visualRect(graphView.model().index(row, 0)).center())
    QTest.qWait(0)


def testPointedRowComesForwardInANativeStyle(tempDir, mainWindow, monkeypatch):
    # A native style, without the stylesheet that paints a hover band
    GFApplication.applyPrefs(qtStyle="Fusion")
    wd = unpackRepo(tempDir)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView

    oid = graphView.model().index(5, 0).data(CommitLogModel.Role.Oid)
    commit = rw.repo.peel_commit(oid)
    text = graphView.palette().color(QPalette.ColorRole.Text)
    assert rowParts(drawnRuns(graphView, monkeypatch, oid), commit)["author"][0].color != text

    pointAtRow(graphView, 5)
    parts = rowParts(drawnRuns(graphView, monkeypatch, oid, keepHover=True), commit)
    assert parts["author"][0].color == text, "the row under the pointer still shows who and when at full strength"
    assert parts["date"][0].color == text


def testUnpushedCuesSurviveTheQuieterGraph(tempDir, mainWindow, monkeypatch):
    """The owner's "not on any remote yet" cues: hollow rings, the ↑N chip, the ring's tooltip."""
    wd = unpackRepo(tempDir)
    mainWindow.resize(1500, 600)
    rw = mainWindow.openRepo(wd)
    graphView = rw.graphView
    repoModel = rw.repoModel
    oid = rw.repo.head_commit_id
    assert oid in repoModel.unpushedCommits

    painted = spyOnGraphFrames(graphView, monkeypatch)
    graphView.viewport().repaint()
    image = grabAt1x(graphView.viewport())
    center, laneColor = bulletPoint(repoModel, oid, painted[oid])
    hole = image.pixelColor(center.x(), center.y())
    ring = image.pixelColor(center.x() - 5, center.y())
    assert colorDistance(ring, laneColor) < 32, "a ring in the lane's color"
    assert colorDistance(hole, laneColor) > 64, "around a hole"

    assert aheadOnChip(graphView, monkeypatch, oid) == [f"{SYMBOL_AHEAD}2"]

    row = graphView.getFilterIndexForCommit(oid).row()
    assert qlvSummonToolTip(graphView, row, x=center.x()) == "This commit isn’t on any remote yet."
