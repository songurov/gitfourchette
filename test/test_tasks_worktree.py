# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
import os
import shlex
import shutil

from gitfourchette.forms.newworktreedialog import NewWorktreeDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.sidebar.sidebarmodel import SidebarItem, SidebarModel
from gitfourchette.tasks import PruneWorktrees, RemoveWorktree
from gitfourchette.toolbox import stockIcon
from .util import *


def addWorktree(wd: str, name: str, *args: str, commitish: str = "") -> str:
    """Create a linked worktree next to the repo and return its path."""
    path = os.path.normpath(os.path.join(wd, "..", name))
    shell(f"git worktree add {' '.join(args)} {shlex.quote(path)} {commitish}".strip(), wd)
    return path


def worktreeNames(rw) -> list[str]:
    return [n.data for n in rw.sidebar.findNodesByKind(SidebarItem.Worktree)]


def testNoWorktreeSectionWithoutLinkedWorktrees(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    # A repo that doesn't use worktrees looks exactly as it did before this
    # feature existed: no header, no rows, nothing implying you're in one.
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.WorktreesHeader)
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Worktree)

    kinds = [n.kind for n in rw.sidebar.sidebarModel.rootNode.children]
    assert SidebarItem.WorktreesHeader not in kinds
    # and no leftover double spacer where the section used to be
    assert not any(a == b == SidebarItem.Spacer for a, b in itertools.pairwise(kinds))


def testWorktreeSectionAppearsWithTheFirstWorktree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.WorktreesHeader)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")
    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    dlg.ui.pathEdit.setText(os.path.normpath(os.path.join(wd, "..", "firstone")))
    dlg.accept()

    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.WorktreesHeader)
    # main worktree + the new one
    assert 2 == rw.sidebar.countNodesByKind(SidebarItem.Worktree)


def testLinkedWorktreesAppearInSidebar(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)

    # Main worktree has no name, linked ones are named after their folder
    assert ["", "sidejob"] == worktreeNames(rw)

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    assert "sidejob" == node.displayName

    worktrees = rw.repoModel.worktrees
    assert worktrees[0].is_main and worktrees[0].is_current
    assert not worktrees[1].is_main and not worktrees[1].is_current
    assert "refs/heads/sidejob" == worktrees[1].head


def testWorktreeWithDetachedHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "detachedjob", "--detach")

    rw = mainWindow.openRepo(wd)
    worktree = rw.repoModel.worktreeByName("detachedjob")
    assert worktree is not None
    assert "" == worktree.head
    assert worktree.head_id == rw.repo.head_commit_id

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "detachedjob")
    tooltip = rw.sidebar.nodeToFilterIndex(node).data(Qt.ItemDataRole.ToolTipRole)
    assert "Detached HEAD" in tooltip
    assert "Branch:" not in tooltip


def testNewWorktree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    newPath = os.path.normpath(os.path.join(wd, "..", "hotfixing"))
    dlg.ui.pathEdit.setText(newPath)
    # The branch name tracks the folder name until the user overrides it
    assert "hotfixing" == dlg.ui.newBranchEdit.text()
    dlg.accept()

    assert os.path.isdir(newPath)
    assert ["", "hotfixing"] == worktreeNames(rw)
    assert "hotfixing" in rw.repo.branches.local

    worktree = rw.repoModel.worktreeByName("hotfixing")
    assert "refs/heads/hotfixing" == worktree.head


def testNewWorktreeOnExistingBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    newPath = os.path.normpath(os.path.join(wd, "..", "onnostash"))
    dlg.ui.pathEdit.setText(newPath)
    dlg.ui.existingBranchRadio.setChecked(True)
    qcbSetIndex(dlg.ui.existingBranchComboBox, "no-parent")
    dlg.accept()

    worktree = rw.repoModel.worktreeByName("onnostash")
    assert "refs/heads/no-parent" == worktree.head


def testNewWorktreeRejectsCheckedOutBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    branches = [dlg.ui.existingBranchComboBox.itemText(i)
                for i in range(dlg.ui.existingBranchComboBox.count())]
    # 'master' is checked out in the main worktree, so git would refuse it
    assert "master" not in branches
    assert "no-parent" in branches
    dlg.reject()


def testNewWorktreeRejectsNonEmptyFolder(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    occupied = os.path.normpath(os.path.join(wd, "..", "occupied"))
    os.makedirs(occupied)
    writeFile(f"{occupied}/squatter.txt", "I was here first")

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    dlg.ui.pathEdit.setText(occupied)
    assert not dlg.acceptButton.isEnabled()

    dlg.ui.pathEdit.setText(os.path.normpath(os.path.join(wd, "..", "vacant")))
    assert dlg.acceptButton.isEnabled()
    dlg.reject()


def testOpenWorktreeInNewTab(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")
    writeFile(f"{worktreePath}/hello.txt", "hello")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"open worktree in new tab")

    rw2 = mainWindow.currentRepoWidget()
    assert rw2 is not rw
    assert os.path.normpath(rw2.repo.workdir) == worktreePath


def testCantOpenCurrentWorktree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and not n.data)
    menu = rw.sidebar.makeNodeMenu(node)
    assert not findMenuAction(menu, r"open worktree in new tab").isEnabled()
    # The main worktree can't be removed or locked either
    menuText = " ".join(a.text().lower() for a in menu.actions())
    assert "remove worktree" not in menuText
    assert "lock worktree" not in menuText


def testRemoveWorktree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"remove worktree")
    acceptQMessageBox(rw, r"really remove worktree")

    assert not os.path.exists(worktreePath)
    # That was the only linked worktree, so the section goes away with it
    assert [] == worktreeNames(rw)
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.WorktreesHeader)
    # Removing a worktree doesn't delete the branch it had checked out
    assert "sidejob" in rw.repo.branches.local


def testRemoveDirtyWorktreeNeedsForce(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")
    writeFile(f"{worktreePath}/a/a1.txt", "uncommitted work")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"remove worktree")
    acceptQMessageBox(rw, r"really remove worktree")
    acceptQMessageBox(rw, r"git refused to remove worktree")

    assert not os.path.exists(worktreePath)


def testLockAndUnlockWorktree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)

    def worktreeNode():
        return rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")

    triggerMenuAction(rw.sidebar.makeNodeMenu(worktreeNode()), r"lock worktree")
    dlg: TextInputDialog = findQDialog(rw, "lock worktree")
    dlg.lineEdit.setText("on a usb stick")
    dlg.accept()

    worktree = rw.repoModel.worktreeByName("sidejob")
    assert worktree.locked
    assert "on a usb stick" == worktree.lock_reason

    triggerMenuAction(rw.sidebar.makeNodeMenu(worktreeNode()), r"unlock worktree")
    assert not rw.repoModel.worktreeByName("sidejob").locked


def testPruneStaleWorktrees(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)

    # Blow the folder away behind git's back, which is exactly what 'prune' is for
    shutil.rmtree(worktreePath)
    rw.refreshRepo()

    worktree = rw.repoModel.worktreeByName("sidejob")
    assert worktree.prunable

    node = rw.sidebar.findNodeByKind(SidebarItem.WorktreesHeader)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"prune stale worktrees")
    acceptQMessageBox(rw, r"really forget 1 stale worktree")

    assert rw.repoModel.worktreeByName("sidejob") is None


def testPruneNothingToDo(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByKind(SidebarItem.WorktreesHeader)
    assert not findMenuAction(rw.sidebar.makeNodeMenu(node), r"prune stale worktrees").isEnabled()


def testWorktreeOfBareRepo(tempDir, mainWindow):
    referenceWd = unpackRepo(tempDir)
    barePath = makeBareCopy(referenceWd, "", False)

    worktreePath = f"{barePath}/MyCoolWorktree"
    shell(f"git worktree add {worktreePath}", barePath)

    rw = mainWindow.openRepo(worktreePath)

    # A bare repo has no main worktree, so only the linked one shows up
    assert ["MyCoolWorktree"] == worktreeNames(rw)
    assert rw.repoModel.worktrees[0].is_current


def testNewWorktreeDetached(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    dlg.ui.pathEdit.setText(os.path.normpath(os.path.join(wd, "..", "looking")))
    dlg.ui.detachedRadio.setChecked(True)
    dlg.accept()

    worktree = rw.repoModel.worktreeByName("looking")
    assert "" == worktree.head
    assert worktree.head_id == rw.repo.head_commit_id
    # A detached worktree doesn't leave a branch behind
    assert "looking" not in rw.repo.branches.local


def testNewWorktreeBrowseForLocation(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    dlg.ui.browseButton.click()
    picked = os.path.normpath(os.path.join(wd, "..", "browsed"))
    acceptQFileDialog(dlg, "new worktree location", picked)

    assert picked == dlg.absolutePath()
    assert "browsed" == dlg.ui.newBranchEdit.text()
    dlg.reject()


def testNewWorktreeEnablesCreateOnFirstPathEntry(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    assert not dlg.acceptButton.isEnabled()  # nothing typed yet

    # Typing a location is enough on its own: the branch name follows it.
    # Regression: the validator used to run against the still-empty branch
    # field and never re-run once the name was filled in behind its back.
    dlg.ui.pathEdit.setText(os.path.normpath(os.path.join(wd, "..", "straightaway")))
    assert "straightaway" == dlg.ui.newBranchEdit.text()
    assert dlg.acceptButton.isEnabled()

    dlg.accept()
    assert rw.repoModel.worktreeByName("straightaway") is not None


def testNewWorktreeKeepsHandTypedBranchName(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    dlg.ui.pathEdit.setText(os.path.normpath(os.path.join(wd, "..", "first")))
    assert "first" == dlg.ui.newBranchEdit.text()

    # Once the user types their own name, the folder name stops overwriting it
    QTest.keyClicks(dlg.ui.newBranchEdit.clear() or dlg.ui.newBranchEdit, "my-own-name")
    dlg.ui.pathEdit.setText(os.path.normpath(os.path.join(wd, "..", "second")))
    assert "my-own-name" == dlg.ui.newBranchEdit.text()
    dlg.reject()


def testNewWorktreeAcceptsRelativeLocation(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    # A bare folder name resolves next to the repo, which is where worktrees usually go
    dlg.ui.pathEdit.setText("nextdoor")
    assert os.path.normpath(os.path.join(wd, "..", "nextdoor")) == dlg.absolutePath()
    dlg.accept()

    assert rw.repoModel.worktreeByName("nextdoor") is not None


def testNewWorktreeRejectsFileAndMissingParent(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    squatterFile = os.path.normpath(os.path.join(wd, "..", "not-a-folder.txt"))
    writeFile(squatterFile, "I am a file")

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")
    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")

    dlg.ui.pathEdit.setText(squatterFile)
    assert not dlg.acceptButton.isEnabled()

    dlg.ui.pathEdit.setText(os.path.join(wd, "..", "no", "such", "parent"))
    assert not dlg.acceptButton.isEnabled()

    dlg.ui.pathEdit.setText("")
    assert not dlg.acceptButton.isEnabled()
    dlg.reject()


def testNewWorktreeWithEveryBranchTaken(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    # TestGitRepository has master (checked out here) and no-parent; take the last one
    addWorktree(wd, "parked", commitish="no-parent")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByKind(SidebarItem.WorktreesHeader)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    assert 0 == dlg.ui.existingBranchComboBox.count()
    assert not dlg.ui.existingBranchRadio.isEnabled()
    assert dlg.ui.newBranchRadio.isChecked()
    dlg.reject()


def testCantRemoveMainOrCurrentWorktree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    RemoveWorktree.invoke(rw, "")
    acceptQMessageBox(rw, r"main worktree can.t be removed")
    assert os.path.isdir(wd)

    rw2 = mainWindow.openRepo(worktreePath)
    RemoveWorktree.invoke(rw2, "sidejob")
    acceptQMessageBox(rw2, r"can.t remove the worktree you.re currently looking at")
    assert os.path.isdir(worktreePath)


def testRemoveVanishedWorktreeEntry(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    RemoveWorktree.invoke(rw, "neverexisted")
    acceptQMessageBox(rw, r"worktree is gone")


def testPruneWithNothingStale(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    PruneWorktrees.invoke(rw)
    acceptQMessageBox(rw, r"no stale worktrees to prune")


def testWorktreesSectionSitsAboveBranches(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "sidejob", "-b", "sidejob")
    rw = mainWindow.openRepo(wd)

    rootNode = rw.sidebar.sidebarModel.rootNode
    kinds = [n.kind for n in rootNode.children if n.kind != SidebarItem.Spacer]

    # Worktrees are working context, so they belong next to the workdir -
    # not at the bottom with the rarely-touched sections.
    assert kinds.index(SidebarItem.WorktreesHeader) == kinds.index(SidebarItem.UncommittedChanges) + 1
    assert kinds.index(SidebarItem.WorktreesHeader) < kinds.index(SidebarItem.LocalBranchesHeader)


def testWorktreeNodeTooltipAndIcon(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")
    shell(f"git worktree lock --reason 'on a usb stick' {shlex.quote(worktreePath)}", wd)

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    index = rw.sidebar.nodeToFilterIndex(node)

    tooltip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert "linked worktree" in tooltip
    assert "sidejob" in tooltip
    assert worktreePath in tooltip
    assert "on a usb stick" in tooltip

    assert "git-worktree" == index.data(SidebarModel.Role.IconKey)
    assert not stockIcon("git-worktree").isNull()

    mainNode = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and not n.data)
    mainIndex = rw.sidebar.nodeToFilterIndex(mainNode)
    # The main worktree is the repo itself, so it wears the workdir icon
    assert "git-workdir" == mainIndex.data(SidebarModel.Role.IconKey)
    mainTooltip = mainIndex.data(Qt.ItemDataRole.ToolTipRole)
    assert "main worktree" in mainTooltip
    assert "worktree you" in mainTooltip  # "this is the worktree you're looking at"


def testStaleWorktreeNodeWarns(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    shutil.rmtree(worktreePath)
    rw.refreshRepo()

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    index = rw.sidebar.nodeToFilterIndex(node)
    assert "achtung" == index.data(SidebarModel.Role.IconKey)
    assert "missing" in index.data(Qt.ItemDataRole.ToolTipRole)

    # A dead worktree can't be opened
    menu = rw.sidebar.makeNodeMenu(node)
    assert not findMenuAction(menu, r"open worktree in new tab").isEnabled()
    assert not findMenuAction(menu, r"open worktree.+folder").isEnabled()


@pytest.mark.parametrize("target", ["header", "worktree", "currentWorktree"])
def testWorktreeDoubleClick(tempDir, mainWindow, target):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")
    rw = mainWindow.openRepo(wd)

    if target == "header":
        node = rw.sidebar.findNodeByKind(SidebarItem.WorktreesHeader)
    elif target == "worktree":
        node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    else:
        node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and not n.data)

    index = rw.sidebar.nodeToFilterIndex(node)
    rect = rw.sidebar.visualRect(index)
    QTest.mouseDClick(rw.sidebar.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    if target == "header":
        dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
        dlg.reject()
    elif target == "worktree":
        assert os.path.normpath(mainWindow.currentRepoWidget().repo.workdir) == worktreePath
    else:
        # Double-clicking the worktree you're already in does nothing
        assert mainWindow.currentRepoWidget() is rw


def testOpenWorktreeFolder(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")

    with MockDesktopServicesContext() as mock:
        triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"open worktree.+folder")
        assert worktreePath == mock.urls[-1].toLocalFile().rstrip("/")


def testCopyWorktreePath(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Worktree and n.data == "sidejob")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"copy.+path")

    assert worktreePath == QApplication.clipboard().text()


def testWorktreeRegistryEntryWithoutGitdirIsIgnored(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    assert rw.repoModel.worktreeByName("sidejob") is not None

    # Half-deleted registry entry: the folder is still there, the 'gitdir'
    # pointer that says where the workdir lives isn't. Don't blow up on it.
    os.unlink(os.path.join(rw.repo.commondir, "worktrees", "sidejob", "gitdir"))
    rw.refreshRepo()

    assert rw.repoModel.worktreeByName("sidejob") is None
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Worktree)


def testNewWorktreeFromRepoMenu(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/new worktree")

    dlg: NewWorktreeDialog = findQDialog(rw, "new worktree")
    dlg.ui.pathEdit.setText(os.path.normpath(os.path.join(wd, "..", "frommenu")))
    dlg.accept()

    assert rw.repoModel.worktreeByName("frommenu") is not None
    assert "frommenu" in rw.repo.branches.local


def testWorktreeTabIsLabelledWithItsRepo(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    worktreePath = addWorktree(wd, "sidejob", "-b", "sidejob")

    rw = mainWindow.openRepo(wd)
    assert "TestGitRepository" == rw.getTitle()

    rw2 = mainWindow.openRepo(worktreePath)
    # A worktree tab says which repo it belongs to, the same way a submodule
    # tab does - otherwise it looks like a repo of its own.
    assert "TestGitRepository: sidejob" == rw2.getTitle()

    tabBar = mainWindow.tabs.tabs
    assert "TestGitRepository" == tabBar.tabText(0)
    assert "TestGitRepository: sidejob" == tabBar.tabText(1)


def testBareRepoWorktreeTabHasNoPrefix(tempDir, mainWindow):
    referenceWd = unpackRepo(tempDir)
    barePath = makeBareCopy(referenceWd, "", False)
    worktreePath = f"{barePath}/MyCoolWorktree"
    shell(f"git worktree add {worktreePath}", barePath)

    rw = mainWindow.openRepo(worktreePath)
    # A bare repo has no main worktree to name, so there's nothing to prefix with
    assert "MyCoolWorktree" == rw.getTitle()
