# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
import shlex

import pytest

from gitfourchette.forms.gitflowinitdialog import GitFlowInitDialog
from gitfourchette.forms.quicklaunch import QuickLaunch
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from .util import *

FLOW_KEYS = {
    "gitflow.branch.master": "master",
    "gitflow.branch.develop": "develop",
    "gitflow.prefix.feature": "feature/",
    "gitflow.prefix.bugfix": "bugfix/",
    "gitflow.prefix.release": "release/",
    "gitflow.prefix.hotfix": "hotfix/",
    "gitflow.prefix.support": "support/",
    "gitflow.prefix.versiontag": "",
}
"""What 'git flow init -d' writes to a repo whose production branch is master (besides gitflow.path.hooks)."""


def initFlowByCli(wd: str, createDevelop: bool = True):
    """Set up Git Flow exactly as 'git flow init -d' does (AVH edition), without needing git-flow."""
    script = [f"git config {key} {shlex.quote(value)}" for key, value in FLOW_KEYS.items()]
    script.append(f"git config gitflow.path.hooks {shlex.quote(wd + '.git/hooks')}")
    if createDevelop:
        script.append("git branch --no-track develop master")
    shell("\n".join(script), wd)


def flowMenu(mainWindow) -> QMenu:
    """Repo > Git Flow, filled as it is when it opens."""
    menu = mainWindow.gitFlowMenu
    menu.aboutToShow.emit()
    return menu


def flowMenuTitles(mainWindow) -> list[str]:
    return [stripAccelerators(a.text()) for a in flowMenu(mainWindow).actions() if not a.isSeparator()]


def localConfigFlowKeys(wd: str) -> dict[str, str]:
    config = GitConfig(f"{wd}.git/config")
    return {entry.name: entry.value for entry in config if entry.name.startswith("gitflow.")}


def clickOk(dlg: QDialog, buttonBox: QDialogButtonBox):
    okButton = buttonBox.button(QDialogButtonBox.StandardButton.Ok)
    assert okButton.isEnabled()
    okButton.click()


def openInitDialog(mainWindow, rw) -> GitFlowInitDialog:
    triggerMenuAction(flowMenu(mainWindow), "initialize git flow")
    return findQDialog(rw, "initialize git flow", GitFlowInitDialog)


def openPalette(mainWindow) -> QuickLaunch:
    triggerMenuAction(mainWindow.menuBar(), "view/quick launch")
    palettes = [p for p in mainWindow.findChildren(QuickLaunch) if p.isVisible()]
    assert len(palettes) == 1
    return palettes[0]


def paletteQuery(palette: QuickLaunch, text: str) -> list[str]:
    palette.lineEdit.clear()
    QTest.keyClicks(palette.lineEdit, text)
    return palette.visibleTitles()


# -----------------------------------------------------------------------------
# Porcelain

def testGitFlowConfigFromCliFormat(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    with RepoContext(wd) as repo:
        assert repo.gitflow_config() == GitFlowConfig(master="master", develop="develop")


@pytest.mark.parametrize("scenario", ["nokeys", "noprefix", "samebranch", "developonremote"])
def testGitFlowNotInitialized(tempDir, mainWindow, scenario):
    wd = unpackRepo(tempDir)
    if scenario == "noprefix":
        shell("git config gitflow.branch.master master && git config gitflow.branch.develop develop"
              " && git branch develop", wd)
    elif scenario == "samebranch":
        initFlowByCli(wd)
        shell("git config gitflow.branch.develop master", wd)
    elif scenario == "developonremote":
        # A fresh clone of a Git Flow repo: git-flow itself doesn't consider it initialized
        initFlowByCli(wd, createDevelop=False)
        shell("git update-ref refs/remotes/origin/develop master", wd)

    with RepoContext(wd) as repo:
        assert repo.gitflow_config() is None


def testGitFlowEmptyPrefixSwitchesKindOff(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git config gitflow.prefix.hotfix ''", wd)
    with RepoContext(wd) as repo:
        cfg = repo.gitflow_config()
        assert cfg.prefix(GitFlowKind.HOTFIX) == ""
        assert cfg.prefix(GitFlowKind.FEATURE) == "feature/"
        assert cfg.classify("hotfix/1.0.1") is None


def testGitFlowMissingPrefixUsesDefault(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git config --unset gitflow.prefix.release && git config gitflow.prefix.feature feat-", wd)
    with RepoContext(wd) as repo:
        cfg = repo.gitflow_config()
        assert cfg.release == "release/"
        assert cfg.feature == "feat-"
        assert cfg.classify("feat-login") == (GitFlowKind.FEATURE, "login")


def testGitFlowWriteConfigIsLocal(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    globalConfigPath = GitConfigHelper.path_for_level(GitConfigLevel.GLOBAL)
    globalConfigBefore = readTextFile(globalConfigPath)

    with RepoContext(wd) as repo:
        repo.gitflow_write_config(GitFlowConfig(master="master", develop="dev", versiontag="v"))

    assert localConfigFlowKeys(wd) == FLOW_KEYS | {"gitflow.branch.develop": "dev", "gitflow.prefix.versiontag": "v"}
    assert readTextFile(globalConfigPath) == globalConfigBefore


def testGitFlowClassify():
    cfg = GitFlowConfig(master="main", develop="feature/develop", feature="feature/", release="feature/rel/")
    assert cfg.classify("feature/login") == (GitFlowKind.FEATURE, "login")
    assert cfg.classify("feature/login/deep") == (GitFlowKind.FEATURE, "login/deep")
    assert cfg.classify("feature/rel/2.0") == (GitFlowKind.RELEASE, "2.0")  # longest prefix wins
    assert cfg.classify("hotfix/2.0.1") == (GitFlowKind.HOTFIX, "2.0.1")
    assert cfg.classify("feature/") is None
    assert cfg.classify("main") is None
    assert cfg.classify("feature/develop") is None
    assert cfg.classify("bugfix/crash") is None
    assert cfg.classify("support/1.x") is None
    assert cfg.classify("topic") is None
    assert cfg.branch_name(GitFlowKind.HOTFIX, "2.0.1") == "hotfix/2.0.1"
    assert GitFlowConfig(master="m", develop="d", versiontag="v").tag_name("1.0") == "v1.0"


def testGitFlowForgetBranchScrubsSection(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.gitflow_set_branch_base("feature/x", "develop")
        repo.gitflow_set_branch_base("feature/x.y", "other")
        assert repo.gitflow_branch_base("feature/x") == "develop"

        repo.gitflow_forget_branch("feature/x")

        assert repo.gitflow_branch_base("feature/x") == ""
        assert repo.gitflow_branch_base("feature/x.y") == "other"

    configText = readTextFile(f"{wd}.git/config")
    assert '[gitflow "branch.feature/x"]' not in configText
    assert '[gitflow "branch.feature/x.y"]' in configText


def testGitFlowMergeCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git checkout -q -b release/1.0
        git commit -q --allow-empty -m 'bump version'
        git checkout -q master
        git merge -q --no-ff --no-edit release/1.0
        git commit -q --allow-empty -m 'later on master'
        git checkout -q -b ff-target master
        git commit -q --allow-empty -m 'on ff-target'
        git checkout -q master
    """, wd)

    with RepoContext(wd) as repo:
        tip = repo.branches.local["release/1.0"].target
        master = repo.branches.local["master"].target
        mergeCommit = repo.peel_commit(master).parent_ids[0]
        assert repo.peel_commit(mergeCommit).parent_ids[1] == tip
        assert repo.gitflow_merge_commit(tip, master) == mergeCommit

        # Fast-forwarded by hand: the branch tip itself
        shell("git checkout -q -b ffmaster release/1.0 && git commit -q --allow-empty -m more", wd)
        assert repo.gitflow_merge_commit(tip, repo.branches.local["ffmaster"].target) == tip

        # Not merged at all
        unmerged = repo.branches.local["ff-target"].target
        assert repo.gitflow_merge_commit(unmerged, master) is None


def testGitFlowTagMerges(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git checkout -q -b release/1.0
        git commit -q --allow-empty -m 'bump version'
        git checkout -q master
        git merge -q --no-ff --no-edit release/1.0
        git tag -a -m 'Release 1.0' 1.0
        git tag lightweight-elsewhere master~1
    """, wd)
    with RepoContext(wd) as repo:
        tip = repo.branches.local["release/1.0"].target
        assert repo.gitflow_tag_merges("1.0", tip)
        assert not repo.gitflow_tag_merges("lightweight-elsewhere", tip)
        assert not repo.gitflow_tag_merges("no-such-tag", tip)


def testIsAncestorAndCompareWithRemote(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch equal origin/master
        git update-ref refs/remotes/origin/equal origin/master
        git branch ahead master
        git update-ref refs/remotes/origin/ahead origin/master
        git branch behind origin/master
        git update-ref refs/remotes/origin/behind master
        git checkout -q -b diverged origin/master
        git commit -q --allow-empty -m 'local only'
        git update-ref refs/remotes/origin/diverged master
        git checkout -q master
        git branch lonely
    """, wd)

    with RepoContext(wd) as repo:
        assert repo.compare_branch_with_remote("equal", "origin") == BranchComparison.EQUAL
        assert repo.compare_branch_with_remote("ahead", "origin") == BranchComparison.AHEAD
        assert repo.compare_branch_with_remote("behind", "origin") == BranchComparison.BEHIND
        assert repo.compare_branch_with_remote("diverged", "origin") == BranchComparison.DIVERGED
        assert repo.compare_branch_with_remote("lonely", "origin") == BranchComparison.NO_REMOTE

        master = repo.branches.local["master"].target
        originMaster = repo.branches.remote["origin/master"].target
        assert repo.is_ancestor(originMaster, master)
        assert repo.is_ancestor(master, master)
        assert not repo.is_ancestor(master, originMaster)


# -----------------------------------------------------------------------------
# Nothing changes for repos that don't use Git Flow

def testNonFlowRepoShowsOnlyInitialize(tempDir, mainWindow):
    # On Home, there's nothing to initialize
    menu = flowMenu(mainWindow)
    assert [(stripAccelerators(a.text()), a.isEnabled()) for a in menu.actions()] == [("Initialize Git Flow…", False)]

    wd = unpackRepo(tempDir)
    shell("git branch feature/x", wd)
    rw = mainWindow.openRepo(wd)

    assert findMenuAction(mainWindow.menuBar(), "repo/git flow").menu() is mainWindow.gitFlowMenu
    assert flowMenuTitles(mainWindow) == ["Initialize Git Flow…"]

    # The repo header in the sidebar has the same menu
    headerMenu = rw.sidebar.makeNodeMenu(rw.sidebar.findNodeByKind(SidebarItem.WorkdirHeader))
    assert findMenuAction(headerMenu, "git flow").menu() is mainWindow.gitFlowMenu
    headerMenu.close()

    # No Finish on a branch that merely looks like a feature, no Start on its folder
    branchMenu = rw.sidebar.makeNodeMenu(rw.sidebar.findNodeByRef("refs/heads/feature/x"))
    assert not any("finish" in a.text().lower() for a in branchMenu.actions())
    branchMenu.close()
    folderNode = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.RefFolder and n.data == "refs/heads/feature")
    folderMenu = rw.sidebar.makeNodeMenu(folderNode)
    assert not any("start" in a.text().lower() for a in folderMenu.actions())
    folderMenu.close()

    # Quick Launch doesn't bring it up on its first screen, only when asked
    palette = openPalette(mainWindow)
    assert not any("Git Flow" in title for title in palette.visibleTitles())
    assert paletteQuery(palette, "flow") == ["Git Flow › Initialize Git Flow…"]
    palette.close()

    # Nothing was written
    assert localConfigFlowKeys(wd) == {}


# -----------------------------------------------------------------------------
# Initialize

def testInitCreatesDevelopAndSwitches(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    dlg = openInitDialog(mainWindow, rw)
    ui = dlg.ui
    assert ui.masterComboBox.currentText() == "master"
    assert ui.developComboBox.currentText() == "develop"
    assert [e.text() for e in (ui.featureEdit, ui.releaseEdit, ui.hotfixEdit, ui.supportEdit, ui.versionTagEdit)] \
           == ["feature/", "release/", "hotfix/", "support/", ""]
    assert ui.developInfoLabel.isVisibleTo(dlg)
    assert ui.developInfoLabel.text() == "“develop” doesn’t exist yet. It will be created from “master”."
    assert ui.switchCheckBox.isEnabled()
    assert ui.switchCheckBox.isChecked()
    clickOk(dlg, ui.buttonBox)

    repo = rw.repo
    assert repo.branches.local["develop"].target == repo.branches.local["master"].target
    assert repo.branches.local["develop"].upstream is None
    assert repo.head_branch_shorthand == "develop"
    assert localConfigFlowKeys(wd) == FLOW_KEYS
    assert repo.gitflow_config() == GitFlowConfig(master="master", develop="develop")
    assert "Initialize Git Flow…" not in flowMenuTitles(mainWindow)
    assert re.search(r"git flow is set up.+master.+develop", mainWindow.statusBar().currentMessage(), re.IGNORECASE)


def testInitWithExistingDevelop(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git branch develop master~2", wd)
    rw = mainWindow.openRepo(wd)
    developTip = rw.repo.branches.local["develop"].target

    dlg = openInitDialog(mainWindow, rw)
    assert dlg.ui.developComboBox.currentText() == "develop"
    assert not dlg.ui.developInfoLabel.isVisibleTo(dlg)
    assert not dlg.ui.switchCheckBox.isEnabled()
    clickOk(dlg, dlg.ui.buttonBox)

    assert rw.repo.head_branch_shorthand == "master"
    assert rw.repo.branches.local["develop"].target == developTip
    assert rw.repo.gitflow_config() is not None


def testInitDevelopFromOriginDevelop(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git update-ref refs/remotes/origin/develop master~1", wd)
    rw = mainWindow.openRepo(wd)

    dlg = openInitDialog(mainWindow, rw)
    assert dlg.ui.developInfoLabel.text() == "“develop” doesn’t exist yet. It will be created from “origin/develop”."
    clickOk(dlg, dlg.ui.buttonBox)

    develop = rw.repo.branches.local["develop"]
    assert develop.upstream.shorthand == "origin/develop"
    assert develop.target == rw.repo.branches.remote["origin/develop"].target
    assert rw.repo.head_branch_shorthand == "develop"


@pytest.mark.parametrize("staged", [False, True])
def testInitRefusesDirtyTree(tempDir, mainWindow, staged):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}master.txt", "changed\n")
    if staged:
        shell("git add master.txt", wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "initialize git flow")
    acceptQMessageBox(rw, "uncommitted changes to tracked files")
    with pytest.raises(KeyError):
        findQDialog(rw, "initialize git flow")
    assert localConfigFlowKeys(wd) == {}


def testInitAllowsUntrackedFiles(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}untracked.txt", "hello\n")
    rw = mainWindow.openRepo(wd)

    dlg = openInitDialog(mainWindow, rw)
    clickOk(dlg, dlg.ui.buttonBox)
    assert rw.repo.gitflow_config() is not None
    assert readTextFile(f"{wd}untracked.txt") == "hello\n"


def testInitRefusedDuringMerge(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    shell("git merge --no-commit --no-ff pep8-fixes", wd)  # merges cleanly, but isn't committed
    rw = mainWindow.openRepo(wd)
    assert rw.repo.state() == RepositoryState.MERGE

    triggerMenuAction(flowMenu(mainWindow), "initialize git flow")
    acceptQMessageBox(rw, "a merge is in progress")
    assert localConfigFlowKeys(wd) == {}


def testInitWritesEmptyVersionTagKey(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    dlg = openInitDialog(mainWindow, rw)
    clickOk(dlg, dlg.ui.buttonBox)

    # Present with an empty value, as after 'git flow init -d' ('git config --get' fails on a missing key)
    shell("git config --local --get gitflow.prefix.versiontag", wd)
    assert localConfigFlowKeys(wd)["gitflow.prefix.versiontag"] == ""


def testInitOnCloneWithConfigButNoLocalDevelop(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd, createDevelop=False)
    shell("git config gitflow.prefix.feature feat/ && git update-ref refs/remotes/origin/develop master~1", wd)
    rw = mainWindow.openRepo(wd)

    assert flowMenuTitles(mainWindow) == ["Initialize Git Flow…"]
    dlg = openInitDialog(mainWindow, rw)
    assert dlg.ui.featureEdit.text() == "feat/"
    assert dlg.ui.developComboBox.currentText() == "develop"
    assert "origin/develop" in dlg.ui.developInfoLabel.text()
    clickOk(dlg, dlg.ui.buttonBox)

    assert rw.repo.branches.local["develop"].upstream.shorthand == "origin/develop"
    assert rw.repo.gitflow_config().feature == "feat/"


def testInitDialogValidation(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    dlg = openInitDialog(mainWindow, rw)
    ui = dlg.ui
    okButton = ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
    assert okButton.isEnabled()

    def check(edit: QLineEdit, badText: str):
        goodText = edit.text()
        edit.setText(badText)
        assert not okButton.isEnabled(), f"accepted {badText!r}"
        edit.setText(goodText)
        assert okButton.isEnabled()

    check(ui.developComboBox.lineEdit(), "master")  # same branch twice
    check(ui.masterComboBox.lineEdit(), "no-such-branch")
    check(ui.developComboBox.lineEdit(), "bad..name")
    check(ui.featureEdit, "")
    check(ui.releaseEdit, "feature/")  # duplicate
    check(ui.hotfixEdit, "feature/sub/")  # one inside another
    check(ui.supportEdit, "bugfix/")  # clashes with the prefix the dialog doesn't show
    check(ui.releaseEdit, "rel~")
    check(ui.versionTagEdit, "v..")

    # A new development branch name is fine: it gets created
    ui.developComboBox.setEditText("integration")
    assert okButton.isEnabled()
    assert ui.developInfoLabel.isVisibleTo(dlg)
    dlg.reject()


def testCliInitializedRepoIsRecognized(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    mainWindow.openRepo(wd)
    assert "Initialize Git Flow…" not in flowMenuTitles(mainWindow)
