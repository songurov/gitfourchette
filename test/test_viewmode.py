# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
The sidebar's two nav rows and the views behind them: Local Changes, which
gives the whole window to the working directory, and All Commits, the graph
over the diff that every repo has always opened in.
"""

import os

from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.nav import NavLocator
from gitfourchette.repoprefs import ViewMode
from gitfourchette.repowidget import RepoWidget
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from .test_prefs import assertTranslatedInForkLanguages
from .util import *


def navRow(rw: RepoWidget, kind: SidebarItem):
    """Click one of the nav rows, as a user would - mouse and all."""
    sb = rw.sidebar
    index = sb.nodeToFilterIndex(sb.findNodeByKind(kind))
    sb.scrollTo(index)
    QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, sb.visualRect(index).center())
    QTest.qWait(0)


def openRepoWithRoom(tempDir, mainWindow, **kwargs) -> RepoWidget:
    mainWindow.resize(1200, 800)  # so the splitters have room to have sizes at all
    rw = mainWindow.openRepo(unpackRepo(tempDir, **kwargs))
    QTest.qWait(0)
    return rw


def testRepoOpensInAllCommits(tempDir, mainWindow):
    """Nobody who ignores the new rows sees anything new."""
    rw = openRepoWithRoom(tempDir, mainWindow)
    assert rw.viewMode == ViewMode.AllCommits
    assert rw.graphContainer.isVisible()
    assert rw.diffArea.contextHeader.isVisible()


def testNavRowsSayLocalChangesAndAllCommits(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    sb = rw.sidebar

    def rowText(kind):
        return sb.nodeToFilterIndex(sb.findNodeByKind(kind)).data(Qt.ItemDataRole.DisplayRole)

    assert rowText(SidebarItem.UncommittedChanges).startswith("Local Changes")
    assert rowText(SidebarItem.AllCommits) == "All Commits"

    assertTranslatedInForkLanguages("Local Changes|Changes", "All Commits", context="SidebarModel")


def testLocalChangesRowPutsTheGraphAway(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    writeFile(f"{rw.workdir}/a/a1.txt", "a1\nmodified\n")

    navRow(rw, SidebarItem.UncommittedChanges)

    assert rw.viewMode == ViewMode.LocalChanges
    assert rw.graphContainer.isHidden()
    assert rw.diffArea.contextHeader.isHidden()

    # Everything the working directory needs is still on screen
    assert rw.diffArea.isVisible()
    assert rw.dirtyFiles.isVisible()
    assert rw.stagedFiles.isVisible()
    assert rw.navLocator.context.isWorkdir()


def testAllCommitsRowBringsTheGraphBack(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    navRow(rw, SidebarItem.UncommittedChanges)
    assert rw.graphContainer.isHidden()

    navRow(rw, SidebarItem.AllCommits)

    assert rw.viewMode == ViewMode.AllCommits
    assert rw.graphContainer.isVisible()
    assert rw.diffArea.contextHeader.isVisible()
    # The row lands you on HEAD, which is where the history starts reading
    assert rw.navLocator.commit == rw.repo.head_commit_id


def testSwitchingModesKeepsSplitterSizes(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    rw.centralSplitter.moveSplitter(rw.centralSplitter.sizes()[0] + 40, 1)
    QTest.qWait(0)
    sizes = rw.centralSplitter.sizes()
    assert sizes[0] > 0

    navRow(rw, SidebarItem.UncommittedChanges)
    navRow(rw, SidebarItem.AllCommits)

    assert rw.centralSplitter.sizes() == sizes

    # And the other way around: a tab that opens in Local Changes and leaves it
    navRow(rw, SidebarItem.UncommittedChanges)
    wd = rw.workdir
    mainWindow.closeTab(0)
    rw = mainWindow.openRepo(wd)
    QTest.qWait(0)
    assert rw.viewMode == ViewMode.LocalChanges

    navRow(rw, SidebarItem.AllCommits)
    assert rw.centralSplitter.sizes() == sizes


def testTheRowYouPickedStaysLit(tempDir, mainWindow):
    """
    A row is supposed to say which view you are in. Handing the selection to
    whichever branch sits on HEAD would leave both rows dark instead.
    """
    rw = openRepoWithRoom(tempDir, mainWindow)
    sb = rw.sidebar

    navRow(rw, SidebarItem.AllCommits)
    assert sb.selectedNode().kind == SidebarItem.AllCommits

    navRow(rw, SidebarItem.UncommittedChanges)
    assert sb.selectedNode().kind == SidebarItem.UncommittedChanges

    # The shortcuts and the View menu light the same rows
    triggerMenuAction(mainWindow.menuBar(), "view/head")
    assert sb.selectedNode().kind == SidebarItem.AllCommits

    triggerMenuAction(mainWindow.menuBar(), "view/working directory")
    assert sb.selectedNode().kind == SidebarItem.UncommittedChanges

    # But picking a commit yourself still points at the ref that's on it
    triggerMenuAction(mainWindow.menuBar(), "view/head")
    rw.jump(NavLocator.inCommit(rw.repo.head_commit_id))
    assert sb.selectedNode().data == "refs/heads/master"


def testTheLitRowSurvivesARefresh(tempDir, mainWindow):
    """A repo refresh re-jumps to where you are; don't let it steal the row."""
    rw = openRepoWithRoom(tempDir, mainWindow)
    navRow(rw, SidebarItem.AllCommits)

    rw.refreshRepo()
    rw.taskRunner.joinWorkerThread()
    QTest.qWait(0)

    assert rw.sidebar.selectedNode().kind == SidebarItem.AllCommits


def testMaximizeStillWorksInAllCommits(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    header = rw.diffArea.contextHeader

    rw.maximizeDiffArea()
    assert rw.isDiffAreaMaximized()
    assert header.maximizeButton.isChecked()

    # A trip through Local Changes doesn't undo it
    navRow(rw, SidebarItem.UncommittedChanges)
    navRow(rw, SidebarItem.AllCommits)
    assert rw.isDiffAreaMaximized()
    assert header.maximizeButton.isChecked()

    rw.maximizeDiffArea()
    assert not rw.isDiffAreaMaximized()
    assert rw.centralSplitter.sizes()[0] > 0


def testJumpToACommitComesBackToAllCommits(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    navRow(rw, SidebarItem.UncommittedChanges)
    assert rw.viewMode == ViewMode.LocalChanges

    oid = Oid(hex="6db9c2ebf75590eef973081736730a9ea169a0c4")
    rw.jump(NavLocator.inCommit(oid))
    rw.taskRunner.joinWorkerThread()

    assert rw.navLocator.commit == oid
    assert rw.viewMode == ViewMode.AllCommits
    assert rw.graphContainer.isVisible()
    assert rw.diffArea.contextHeader.isVisible()


def testJumpToABranchComesBackToAllCommits(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    navRow(rw, SidebarItem.UncommittedChanges)
    assert rw.graphContainer.isHidden()

    rw.sidebar.selectNode(rw.sidebar.findNodeByRef("refs/heads/no-parent"))
    QTest.qWait(0)

    assert rw.viewMode == ViewMode.AllCommits
    assert rw.graphContainer.isVisible()


def testJumpToTheWorkingDirectoryKeepsTheMode(tempDir, mainWindow):
    """Staging a file, or Ctrl+G, shouldn't rearrange the window under you."""
    rw = openRepoWithRoom(tempDir, mainWindow)
    writeFile(f"{rw.workdir}/a/a1.txt", "a1\nmodified\n")

    # In All Commits, going to the working directory leaves the graph alone
    triggerMenuAction(mainWindow.menuBar(), "view/working directory")
    assert rw.viewMode == ViewMode.AllCommits
    assert rw.graphContainer.isVisible()

    navRow(rw, SidebarItem.UncommittedChanges)
    assert rw.viewMode == ViewMode.LocalChanges

    # And in Local Changes it doesn't drag the graph back in
    triggerMenuAction(mainWindow.menuBar(), "view/working directory")
    assert rw.viewMode == ViewMode.LocalChanges
    assert rw.graphContainer.isHidden()


def testGoToHeadComesBackToAllCommits(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    navRow(rw, SidebarItem.UncommittedChanges)
    assert rw.graphContainer.isHidden()

    triggerMenuAction(mainWindow.menuBar(), "view/head")

    assert rw.viewMode == ViewMode.AllCommits
    assert rw.graphContainer.isVisible()
    assert rw.navLocator.commit == rw.repo.head_commit_id


def testModeSurvivesClosingAndReopeningTheTab(tempDir, mainWindow):
    rw = openRepoWithRoom(tempDir, mainWindow)
    wd = rw.workdir
    navRow(rw, SidebarItem.UncommittedChanges)
    assert rw.viewMode == ViewMode.LocalChanges

    mainWindow.closeTab(0)
    rw = mainWindow.openRepo(wd)
    QTest.qWait(0)

    assert rw.viewMode == ViewMode.LocalChanges
    assert rw.graphContainer.isHidden()
    assert rw.diffArea.contextHeader.isHidden()


def testEachTabKeepsItsOwnMode(tempDir, mainWindow):
    rw1 = openRepoWithRoom(tempDir, mainWindow, renameTo="repo1")
    rw2 = openRepoWithRoom(tempDir, mainWindow, renameTo="repo2")

    navRow(rw2, SidebarItem.UncommittedChanges)
    assert rw2.graphContainer.isHidden()

    mainWindow.tabs.setCurrentIndex(0)
    QTest.qWait(0)
    assert rw1.viewMode == ViewMode.AllCommits
    assert rw1.graphContainer.isVisible()

    mainWindow.tabs.setCurrentIndex(1)
    QTest.qWait(0)
    assert rw2.viewMode == ViewMode.LocalChanges
    assert rw2.graphContainer.isHidden()


def testFindFallsBackToTheFileListInLocalChanges(tempDir, mainWindow):
    """Ctrl+F can't pop up the graph's search bar when the graph is gone."""
    rw = openRepoWithRoom(tempDir, mainWindow)
    rw.setViewMode(ViewMode.LocalChanges)  # not via the sidebar, which would take the focus
    QTest.qWait(0)

    rw.dispatchSearchCommand(SearchBar.Op.Start)

    assert not rw.graphView.searchBar.isVisible()
    assert rw.diffArea.dirtyFiles.searchBar.isVisible()
    rw.diffArea.dirtyFiles.searchBar.hide()


def testAllCommitsRowInAnEmptyRepo(tempDir, mainWindow):
    """There is no HEAD to go to yet; the row still picks the view."""
    mainWindow.resize(1200, 800)
    triggerMenuAction(mainWindow.menuBar(), "file/new repo")
    path = os.path.realpath(tempDir.name + "/emptyrepo")
    os.makedirs(path)
    acceptQFileDialog(mainWindow, "new repo", path)
    rw = mainWindow.currentRepoWidget()
    QTest.qWait(0)

    navRow(rw, SidebarItem.UncommittedChanges)
    assert rw.graphContainer.isHidden()

    navRow(rw, SidebarItem.AllCommits)
    assert rw.viewMode == ViewMode.AllCommits
    assert rw.graphContainer.isVisible()
    assert rw.navLocator.context.isWorkdir()  # nothing to jump to, so we stay put
