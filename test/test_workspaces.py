# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import shutil

from gitfourchette import settings
from gitfourchette.forms.workspacedialog import WorkspaceDialog
from gitfourchette.repowidget import RepoWidget
from gitfourchette.toolbox.qtabwidget2 import QTabWidget2
from .util import *

WORKSPACE_MENU = "file/workspace"


def openTwoRepos(tempDir, mainWindow):
    a = unpackRepo(tempDir, renameTo="alpha")
    b = unpackRepo(tempDir, renameTo="bravo")
    mainWindow.openRepo(a)
    mainWindow.openRepo(b)
    return os.path.normpath(a), os.path.normpath(b)


def saveWorkspace(mainWindow, name: str):
    """Create a workspace holding the repos that are open right now."""
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")
    dlg.ui.nameEdit.setText(name)
    tickRepos(dlg, mainWindow.openTabPaths())
    assert dlg.acceptButton.isEnabled()
    dlg.accept()


def tickRepos(dlg: WorkspaceDialog, paths: list[str], checked: bool = True):
    wanted = set(paths)
    for i in range(dlg.ui.repoList.count()):
        item = dlg.ui.repoList.item(i)
        if item.data(WorkspaceDialog.PathRole) in wanted:
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)


def menuTexts(mainWindow) -> list[str]:
    menu = findMenuAction(mainWindow.menuBar(), WORKSPACE_MENU).menu()
    return [stripAccelerators(a.text()) for a in menu.actions()]


def testNoWorkspacesYet(tempDir, mainWindow):
    assert [] == settings.history.workspaceNames()
    assert "" == settings.history.currentWorkspace

    # Creating one is always available: the picker lists known repos, so a
    # workspace can be assembled without opening anything first.
    action = findMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    assert action.isEnabled()


def testSaveTabsAsWorkspace(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "client work")

    history = settings.history
    assert ["client work"] == history.workspaceNames()
    assert "client work" == history.currentWorkspace

    workspace = history.getWorkspace("client work")
    assert [a, b] == workspace["repos"]
    assert 1 == workspace["activeIndex"]  # bravo was opened last

    # It shows up in the menu, ticked
    action = findMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/client work")
    assert action.isChecked()


def testWorkspaceNameMustBeFreeAndNonEmpty(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "taken")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    tickRepos(dlg, mainWindow.openTabPaths())
    dlg.ui.nameEdit.setText("taken")
    assert not dlg.acceptButton.isEnabled()
    dlg.ui.nameEdit.setText("   ")
    assert not dlg.acceptButton.isEnabled()
    dlg.ui.nameEdit.setText("free")
    assert dlg.acceptButton.isEnabled()
    dlg.reject()


def testSwitchWorkspaceReplacesTabs(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "two repos")

    mainWindow.closeAllTabs()
    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)
    saveWorkspace(mainWindow, "just one")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/two repos")

    assert "two repos" == settings.history.currentWorkspace
    assert [a, b] == [os.path.normpath(w.workdir) for w in mainWindow.tabs.widgets()]
    assert 1 == mainWindow.tabs.currentIndex()


def testSwitchingAwayKeepsTheCurationOfTheWorkspaceYouLeave(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "first")
    mainWindow.closeAllTabs()
    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)
    saveWorkspace(mainWindow, "second")

    # Go back to 'first' and add a repo to it
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/first")
    mainWindow.openRepo(c)
    assert 3 == mainWindow.tabs.count()

    # Leaving 'first' remembers what's open in it, without being asked
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/second")
    assert [a, b, c] == settings.history.getWorkspace("first")["repos"]
    assert [c] == settings.history.getWorkspace("second")["repos"]


def testSwitchingToTheCurrentWorkspaceDoesNothing(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "here")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/here")
    assert [a, b] == [os.path.normpath(w.workdir) for w in mainWindow.tabs.widgets()]


def testRenameWorkspace(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "old name")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/edit")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "edit workspace")
    dlg.ui.nameEdit.setText("new name")
    dlg.accept()

    assert ["new name"] == settings.history.workspaceNames()
    assert "new name" == settings.history.currentWorkspace
    assert findMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new name").isChecked()


def testRenameRejectsATakenName(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "one")
    mainWindow.closeAllTabs()
    mainWindow.openRepo(unpackRepo(tempDir, renameTo="charlie"))
    saveWorkspace(mainWindow, "two")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/edit")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "edit workspace")
    dlg.ui.nameEdit.setText("one")
    assert not dlg.acceptButton.isEnabled()
    dlg.ui.nameEdit.setText("two")  # its own name is fine
    assert dlg.acceptButton.isEnabled()
    dlg.reject()


def testDeleteWorkspaceKeepsTabsOpen(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "doomed")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/delete")
    acceptQMessageBox(mainWindow, r"really delete workspace")

    assert [] == settings.history.workspaceNames()
    assert "" == settings.history.currentWorkspace
    # The repos stay where they are, and so do the tabs
    assert [a, b] == [os.path.normpath(w.workdir) for w in mainWindow.tabs.widgets()]


def testRenameAndDeleteOnlyExistWhenAWorkspaceIsCurrent(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    texts = " ".join(menuTexts(mainWindow)).lower()
    assert "edit" not in texts
    assert "delete" not in texts

    saveWorkspace(mainWindow, "now there is one")
    texts = " ".join(menuTexts(mainWindow)).lower()
    assert "edit" in texts
    assert "delete" in texts


def testWorkspaceWithMissingRepo(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "will break")
    mainWindow.closeAllTabs()

    # Pull one of the repos out from under the workspace
    shutil.rmtree(b)
    settings.history.setCurrentWorkspace("")
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/will break")
    acceptQMessageBox(mainWindow, r"couldn.t be restored fully")

    # The surviving repo still opens
    assert [a] == [os.path.normpath(w.workdir) for w in mainWindow.tabs.widgets()]


def testQuittingRemembersTheCurrentWorkspace(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "daily")

    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)
    # Opening a repo alone must not absorb it into the workspace...
    assert [a, b] == settings.history.getWorkspace("daily")["repos"]

    # ...but quitting with it open does
    mainWindow.saveSession(writeNow=True)
    assert [a, b, c] == settings.history.getWorkspace("daily")["repos"]


def testLegacyHistoryWithoutWorkspaces(tempDir, mainWindow):
    # A history.json written before workspaces existed must load unchanged
    history = settings.History()
    history.load()
    assert [] == history.workspaces
    assert "" == history.currentWorkspace


def testToolbarButtonShowsWhichWorkspaceIsActive(tempDir, mainWindow):
    toolbar = mainWindow.mainToolBar

    # Nothing saved yet: you're on Home, and the button says so
    assert "Home" == toolbar.workspaceAction.text()
    assert "Home" in toolbar.workspaceAction.toolTip()

    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "client work")
    assert "client work" == toolbar.workspaceAction.text()
    assert "client work" in toolbar.workspaceAction.toolTip()

    # Switching swaps the label
    mainWindow.closeAllTabs()
    mainWindow.openRepo(unpackRepo(tempDir, renameTo="charlie"))
    saveWorkspace(mainWindow, "side project")
    assert "side project" == toolbar.workspaceAction.text()

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/client work")
    assert "client work" == toolbar.workspaceAction.text()

    # Deleting the last one drops you back to Home
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/delete")
    acceptQMessageBox(mainWindow, r"really delete workspace")
    assert "Home" == toolbar.workspaceAction.text()


def testToolbarButtonOpensTheSameMenu(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "shared menu")

    menu = mainWindow.mainToolBar.workspaceAction.menu()
    assert menu is mainWindow.workspaceMenu
    assert "shared menu" in " ".join(stripAccelerators(a.text()) for a in menu.actions())


def testQuittingWithNoTabsDoesntEmptyTheWorkspace(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "keepme")

    # Closing everything is a transient state, not "this workspace is empty now"
    mainWindow.closeAllTabs()
    mainWindow.saveSession(writeNow=True)

    assert [a, b] == settings.history.getWorkspace("keepme")["repos"]


def testCreatingAWorkspaceReplacesTheOpenTabs(tempDir, mainWindow):
    a, _b = openTwoRepos(tempDir, mainWindow)
    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")
    dlg.ui.nameEdit.setText("two of three")
    tickRepos(dlg, [a, c])
    dlg.accept()

    # A workspace is what you see: bravo was left out, so its tab goes away
    assert [a, c] == mainWindow.openTabPaths()


def testEditingAWorkspaceReplacesTheOpenTabs(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "trimmed")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/edit")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "edit workspace")
    tickRepos(dlg, [b], checked=False)
    dlg.accept()

    assert [a] == mainWindow.openTabPaths()


def testHomeIsAlwaysThereAndClosesEverything(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "somewhere")
    assert [a, b] == mainWindow.openTabPaths()

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/home")
    assert "" == settings.history.currentWorkspace
    assert [] == mainWindow.openTabPaths()
    assert "Home" == mainWindow.mainToolBar.workspaceAction.text()

    # Home can't be edited or deleted - those actions only exist for a real one
    texts = " ".join(menuTexts(mainWindow)).lower()
    assert "home" in texts
    assert "edit" not in texts
    assert "delete" not in texts

    # And it's still there to go back to
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/somewhere")
    assert [a, b] == mainWindow.openTabPaths()


def testWorkspaceCanBeBuiltWithoutOpeningItsRepos(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    mainWindow.closeAllTabs()

    # Nothing is open, but both repos are known, so they can still be picked
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")
    assert [] == dlg.checkedPaths()
    assert not dlg.acceptButton.isEnabled()  # a name alone isn't enough

    dlg.ui.nameEdit.setText("assembled")
    assert not dlg.acceptButton.isEnabled()  # still no repo picked
    tickRepos(dlg, [a, b])
    assert dlg.acceptButton.isEnabled()
    dlg.accept()

    # With no tabs to seed the order, the list is most-recently-opened first
    assert [b, a] == settings.history.getWorkspace("assembled")["repos"]


def testRenamingAWorkspaceThatIsGone(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "real")

    # Nothing happens, and nothing is renamed
    settings.history.renameWorkspace("never existed", "whatever")
    assert ["real"] == settings.history.workspaceNames()
    assert "real" == settings.history.currentWorkspace


def testPickerFiltersAsYouType(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    def visiblePaths():
        return [dlg.ui.repoList.item(i).data(WorkspaceDialog.PathRole)
                for i in range(dlg.ui.repoList.count())
                if not dlg.ui.repoList.item(i).isHidden()]

    assert {a, b, c} == set(visiblePaths())
    tickRepos(dlg, [a, b, c])

    dlg.ui.filterEdit.setText("brav")
    assert [b] == visiblePaths()

    # Filtering hides rows, it doesn't untick them
    assert {a, b, c} == set(dlg.checkedPaths())

    dlg.ui.filterEdit.setText("")
    assert {a, b, c} == set(visiblePaths())
    dlg.reject()


def testPickerKeepsTabOrderAndListsKnownRepos(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)
    mainWindow.closeTab(2)  # charlie is known but no longer open

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    allPaths = [dlg.ui.repoList.item(i).data(WorkspaceDialog.PathRole)
                for i in range(dlg.ui.repoList.count())]
    assert [a, b] == allPaths[:2]   # open tabs first, in tab order
    assert c in allPaths            # closed-but-known repos are offered too
    assert [] == dlg.checkedPaths()  # nothing is chosen for you

    tickRepos(dlg, [a, b, c])
    dlg.ui.nameEdit.setText("everything")
    dlg.accept()

    assert [a, b, c] == settings.history.getWorkspace("everything")["repos"]


def testEditWorkspaceChangesMembership(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "trim me")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/edit")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "edit workspace")
    assert "trim me" == dlg.ui.nameEdit.text()
    assert [a, b] == dlg.checkedPaths()

    tickRepos(dlg, [b], checked=False)
    dlg.accept()

    assert [a] == settings.history.getWorkspace("trim me")["repos"]
    assert "trim me" == settings.history.currentWorkspace


def testEditCannotEmptyAWorkspace(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    saveWorkspace(mainWindow, "not empty")

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/edit")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "edit workspace")
    tickRepos(dlg, [a, b], checked=False)
    assert not dlg.acceptButton.isEnabled()
    dlg.reject()

    assert [a, b] == settings.history.getWorkspace("not empty")["repos"]


def testDoubleClickTogglesARepoInThePicker(tempDir, mainWindow):
    _a, b = openTwoRepos(tempDir, mainWindow)

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    item = dlg.ui.repoList.item(0)
    assert Qt.CheckState.Unchecked == item.checkState()
    dlg.ui.repoList.itemActivated.emit(item)
    assert Qt.CheckState.Checked == item.checkState()
    assert [_a] == dlg.checkedPaths()
    dlg.ui.repoList.itemActivated.emit(item)
    assert [] == dlg.checkedPaths()
    assert b  # bravo is offered but untouched
    dlg.reject()


def testNewWorkspaceStartsEmpty(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    # Open tabs are listed first for convenience, but choosing is the user's job
    assert [] == dlg.checkedPaths()
    dlg.ui.nameEdit.setText("mine")
    assert not dlg.acceptButton.isEnabled()
    dlg.reject()


def testSelectAllAndDeselectAll(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    dlg.ui.selectAllButton.click()
    assert {a, b, c} == set(dlg.checkedPaths())

    dlg.ui.deselectAllButton.click()
    assert [] == dlg.checkedPaths()
    assert not dlg.acceptButton.isEnabled()
    dlg.reject()


def testSelectAllOnlyTouchesWhatTheFilterShows(tempDir, mainWindow):
    a, b = openTwoRepos(tempDir, mainWindow)
    c = os.path.normpath(unpackRepo(tempDir, renameTo="charlie"))
    mainWindow.openRepo(c)

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    dlg.ui.filterEdit.setText("charlie")
    dlg.ui.selectAllButton.click()
    assert [c] == dlg.checkedPaths()

    # Clearing the filter doesn't disturb what was already ticked
    dlg.ui.filterEdit.setText("")
    assert [c] == dlg.checkedPaths()

    # ...and deselecting under a filter leaves the rest alone
    dlg.ui.selectAllButton.click()
    dlg.ui.filterEdit.setText("alpha")
    dlg.ui.deselectAllButton.click()
    assert {b, c} == set(dlg.checkedPaths())
    assert a not in dlg.checkedPaths()
    dlg.reject()


def testHomeClosesTabsEvenWithoutAWorkspace(tempDir, mainWindow):
    # The common case: some repos open, no workspace ever saved. Home is still
    # "nothing open", so clicking it must close them.
    openTwoRepos(tempDir, mainWindow)
    assert "" == settings.history.currentWorkspace
    assert 2 == len(mainWindow.openTabPaths())

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/home")

    assert [] == mainWindow.openTabPaths()
    assert "" == settings.history.currentWorkspace


def testTabShowsUncommittedAndUnpushedSeparately(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    tabs = mainWindow.tabs

    # The fixture's master already sits ahead of origin/master - exactly the
    # state a working-directory count alone would hide from you.
    assert 2 == rw.unpushedCommitCount()
    assert "git-status-unpushed" == rw.statusIconKey()
    assert "git-status-unpushed" == tabs.tabStatusIcon(0)
    assert "not pushed" in rw.statusTooltip()

    # Uncommitted work is a different problem, so it gets a different mark
    writeFile(f"{wd}/newfile.txt", "work in progress")
    rw.refreshRepo()
    assert "git-status-dirty-unpushed" == rw.statusIconKey()
    assert "git-status-dirty-unpushed" == tabs.tabStatusIcon(0)
    assert "uncommitted change" in rw.statusTooltip()

    # Committing clears the dirty mark but not the unpushed one: done locally
    # is not the same as sent, and the tab keeps saying so.
    with RepoContext(wd) as repo:
        repo.index.add_all()
        repo.index.write()
        repo.create_commit_on_head("local only", TEST_SIGNATURE, TEST_SIGNATURE)
    rw.refreshRepo()

    assert "git-status-unpushed" == rw.statusIconKey()
    assert 3 == rw.unpushedCommitCount()
    assert "git-status-unpushed" == tabs.tabStatusIcon(0)


def testCleanAndPushedRepoWearsNoMark(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    # Line master up with its upstream so there is genuinely nothing outstanding
    shell("git reset --hard origin/master", wd)
    rw = mainWindow.openRepo(wd)
    rw.refreshRepo()

    assert "" == rw.statusIconKey()
    assert "" == mainWindow.tabs.tabStatusIcon(0)
    assert "Nothing outstanding" in rw.statusTooltip()


def testUnloadedTabWearsNoMark(tempDir, mainWindow):
    a = unpackRepo(tempDir, renameTo="alpha")
    b = unpackRepo(tempDir, renameTo="bravo")
    writeFile(f"{b}/newfile.txt", "work in progress")

    # Restoring a session leaves the inactive tabs as unloaded stubs
    session = settings.Session()
    session.tabs = [os.path.normpath(a), os.path.normpath(b)]
    session.activeTabIndex = 0
    mainWindow.restoreSession(session)

    assert not isinstance(mainWindow.tabs.widget(1), RepoWidget), "expected an unloaded stub"
    # A stub has read nothing, so it must not claim anything
    assert "" == mainWindow.tabs.tabStatusIcon(1)


def testAttentionTakesTheIconSlotThenGivesItBack(tempDir, mainWindow):
    a = unpackRepo(tempDir, renameTo="alpha")
    b = unpackRepo(tempDir, renameTo="bravo")
    mainWindow.openRepo(a)
    rwB = mainWindow.openRepo(b)
    mainWindow.tabs.setCurrentIndex(0)
    assert "git-status-unpushed" == mainWindow.tabs.tabStatusIcon(1)

    # A tab shouting for attention borrows the one icon slot...
    mainWindow.tabs.requestAttention(1)
    assert "true" == rwB.property(QTabWidget2.UrgentPropertyName)

    # ...and hands it back when you go look, without losing what it was saying
    mainWindow.tabs.setCurrentIndex(1)
    assert not rwB.property(QTabWidget2.UrgentPropertyName)
    assert "git-status-unpushed" == mainWindow.tabs.tabStatusIcon(1)


def testClickingHomeWhileAlreadyThereDoesNothing(tempDir, mainWindow):
    assert "" == settings.history.currentWorkspace
    assert [] == mainWindow.openTabPaths()

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/home")

    assert [] == mainWindow.openTabPaths()
    assert "Home" == mainWindow.mainToolBar.workspaceAction.text()


def testPickerOffersReposFoundOnDiskNotJustOpenedOnes(tempDir, mainWindow):
    a, _b = openTwoRepos(tempDir, mainWindow)
    onDisk = os.path.normpath(unpackRepo(tempDir, renameTo="never-opened"))

    # Pretend the Home scan found a repo we've never opened
    settings.history.scannedRepos = [{"path": onDisk}]

    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    offered = [dlg.ui.repoList.item(i).data(WorkspaceDialog.PathRole)
               for i in range(dlg.ui.repoList.count())]
    assert onDisk in offered, "a repo found on disk must be offered too"
    assert a == offered[0], "open tabs still come first"

    tickRepos(dlg, [onDisk])
    dlg.ui.nameEdit.setText("from disk")
    dlg.accept()
    assert [onDisk] == settings.history.getWorkspace("from disk")["repos"]


def testPickerButtonsAreNotSqueezedIntoEllipses(tempDir, mainWindow):
    openTwoRepos(tempDir, mainWindow)
    triggerMenuAction(mainWindow.menuBar(), f"{WORKSPACE_MENU}/new workspace")
    dlg: WorkspaceDialog = findQDialog(mainWindow, "new workspace")

    for button in (dlg.ui.selectAllButton, dlg.ui.deselectAllButton):
        assert button.width() >= button.sizeHint().width(), \
            f"{button.text()!r} is clipped"
    dlg.reject()
