# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import ast
import os
import re
import shlex
import shutil
from pathlib import Path

import pytest

from gitfourchette import tasks
from gitfourchette.forms.gitflowinitdialog import GitFlowInitDialog
from gitfourchette.forms.quicklaunch import QuickLaunch
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from .test_prefs import assertTranslatedInForkLanguages
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

    # The repo header in the sidebar offers the same items, in a menu of its own:
    # on macOS a native menu hangs under one parent item only, so borrowing the
    # menu bar's could take it off Repo > Git Flow
    headerMenu = rw.sidebar.makeNodeMenu(rw.sidebar.findNodeByKind(SidebarItem.WorkdirHeader))
    headerFlowMenu = findMenuAction(headerMenu, "git flow").menu()
    assert headerFlowMenu is not mainWindow.gitFlowMenu
    assert [stripAccelerators(a.text()) for a in headerFlowMenu.actions()] == ["Initialize Git Flow…"]
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
    assert flowMenuTitles(mainWindow) == ["Start Feature…", "Start Release…", "Start Hotfix…"]
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
    assert flowMenuTitles(mainWindow) == ["Start Feature…", "Start Release…", "Start Hotfix…"]


def testKindWithEmptyPrefixIsNotOffered(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git config gitflow.prefix.hotfix ''", wd)
    mainWindow.openRepo(wd)
    assert flowMenuTitles(mainWindow) == ["Start Feature…", "Start Release…"]


# -----------------------------------------------------------------------------
# Start

def startDialog(rw, kind: str) -> TextInputDialog:
    return findQDialog(rw, f"start {kind}", TextInputDialog)


@pytest.mark.parametrize("method", ["repomenu", "sidebarfolder", "quicklaunch"])
def testStartFeature(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git branch feature/existing develop", wd)
    rw = mainWindow.openRepo(wd)

    if method == "repomenu":
        triggerMenuAction(flowMenu(mainWindow), "start feature")
    elif method == "sidebarfolder":
        folderNode = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.RefFolder and n.data == "refs/heads/feature")
        menu = rw.sidebar.makeNodeMenu(folderNode)
        assert [stripAccelerators(a.text()) for a in menu.actions()][:1] == ["Start Feature…"]
        triggerMenuAction(menu, "start feature")
    elif method == "quicklaunch":
        palette = openPalette(mainWindow)
        assert paletteQuery(palette, "start feature") == ["Git Flow › Start Feature…"]
        QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)

    dlg = startDialog(rw, "feature")
    findChildWithText(dlg, r"^starts from .develop.\. the branch name begins with .feature/.\.$", QLabel)
    assert not dlg.okButton.isEnabled()  # no name yet
    dlg.lineEdit.setText("login page")
    assert dlg.lineEdit.text() == "login-page"
    clickOk(dlg, dlg.buttonBox)

    repo = rw.repo
    assert repo.head_branch_shorthand == "feature/login-page"
    assert repo.branches.local["feature/login-page"].target == repo.branches.local["develop"].target
    assert repo.gitflow_branch_base("feature/login-page") == "develop"
    assert re.search(r"feature/login-page.+started from.+develop", mainWindow.statusBar().currentMessage(), re.IGNORECASE)


def testStartReleaseAndHotfixBases(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git checkout -q develop && git commit -q --allow-empty -m 'next release work' && git checkout -q master", wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    triggerMenuAction(flowMenu(mainWindow), "start release")
    dlg = startDialog(rw, "release")
    dlg.lineEdit.setText("1.0")
    clickOk(dlg, dlg.buttonBox)
    assert repo.head_branch_shorthand == "release/1.0"
    assert repo.branches.local["release/1.0"].target == repo.branches.local["develop"].target
    assert repo.gitflow_branch_base("release/1.0") == "develop"

    triggerMenuAction(flowMenu(mainWindow), "start hotfix")
    dlg = startDialog(rw, "hotfix")
    dlg.lineEdit.setText("0.9.1")
    clickOk(dlg, dlg.buttonBox)
    assert repo.head_branch_shorthand == "hotfix/0.9.1"
    assert repo.branches.local["hotfix/0.9.1"].target == repo.branches.local["master"].target
    assert repo.gitflow_branch_base("hotfix/0.9.1") == "master"


def testStartReleaseRefusesSecondRelease(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git branch release/1.0 develop", wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start release")
    acceptQMessageBox(rw, "release branch .release/1.0. is still open")
    with pytest.raises(KeyError):
        startDialog(rw, "release")


@pytest.mark.parametrize("multi", [False, True])
def testStartHotfixMultiHotfixAllowed(tempDir, mainWindow, multi):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git branch hotfix/1.0.1 master", wd)
    if multi:
        shell("git config gitflow.multi-hotfix true", wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start hotfix")
    if not multi:
        acceptQMessageBox(rw, "hotfix branch .hotfix/1.0.1. is still open")
        return
    dlg = startDialog(rw, "hotfix")
    dlg.lineEdit.setText("1.0.2")
    clickOk(dlg, dlg.buttonBox)
    assert rw.repo.head_branch_shorthand == "hotfix/1.0.2"


def testStartReleaseTagExists(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git config gitflow.prefix.versiontag v && git tag v1.0 master", wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start release")
    dlg = startDialog(rw, "release")
    dlg.lineEdit.setText("1.0")
    assert not dlg.okButton.isEnabled()
    assert dlg.validator.inputs[0].error == "Tag “v1.0” already exists."
    dlg.lineEdit.setText("1.0.")  # a valid branch name, but not a valid tag
    assert not dlg.okButton.isEnabled()
    dlg.lineEdit.setText("1.1")
    assert dlg.okButton.isEnabled()
    dlg.reject()


def testStartReleaseRefusesDirtyTree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    writeFile(f"{wd}master.txt", "changed\n")
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start release")
    acceptQMessageBox(rw, "uncommitted changes to tracked files")
    assert "release/1.0" not in rw.repo.branches.local


def testStartReleaseAllowDirty(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git config gitflow.allowdirty true", wd)
    writeFile(f"{wd}master.txt", "changed\n")
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start release")
    dlg = startDialog(rw, "release")
    dlg.lineEdit.setText("1.0")
    clickOk(dlg, dlg.buttonBox)
    assert rw.repo.head_branch_shorthand == "release/1.0"
    assert readTextFile(f"{wd}master.txt") == "changed\n"


def testStartFeatureCarriesDirtyChanges(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git checkout -q develop", wd)
    writeFile(f"{wd}master.txt", "work in progress\n")
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start feature")
    dlg = startDialog(rw, "feature")
    dlg.lineEdit.setText("wip")
    clickOk(dlg, dlg.buttonBox)
    assert rw.repo.head_branch_shorthand == "feature/wip"
    assert readTextFile(f"{wd}master.txt") == "work in progress\n"


@pytest.mark.parametrize("state", ["behind", "diverged"])
def testStartRefusesWhenBaseBehindRemote(tempDir, mainWindow, state):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    if state == "behind":
        shell("git update-ref refs/remotes/origin/develop master && git branch -f develop master~1", wd)
    else:
        shell("""
            git checkout -q develop
            git commit -q --allow-empty -m 'pushed by someone else'
            git update-ref refs/remotes/origin/develop HEAD
            git reset -q --hard HEAD~1
            git commit -q --allow-empty -m 'local work'
            git checkout -q master
        """, wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start feature")
    if state == "behind":
        acceptQMessageBox(rw, "develop. is behind .origin/develop.+fast-forward it")
    else:
        acceptQMessageBox(rw, "develop. and .origin/develop. have diverged")
    with pytest.raises(KeyError):
        startDialog(rw, "feature")


@pytest.mark.parametrize("confirm", [False, True])
def testStartFromDangerousDetachedHeadAsks(tempDir, mainWindow, confirm):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git switch -q --detach master && git commit -q --allow-empty -m 'lost commit'", wd)
    rw = mainWindow.openRepo(wd)
    assert rw.repoModel.dangerouslyDetachedHead()

    triggerMenuAction(flowMenu(mainWindow), "start feature")
    dlg = startDialog(rw, "feature")
    dlg.lineEdit.setText("x")
    clickOk(dlg, dlg.buttonBox)

    if confirm:
        acceptQMessageBox(rw, "lose track of this commit.+feature/x")
        assert rw.repo.head_branch_shorthand == "feature/x"
    else:
        rejectQMessageBox(rw, "lose track of this commit.+feature/x")
        assert "feature/x" not in rw.repo.branches.local
        assert rw.repo.head_is_detached


def testStartRefusedDuringResolvedMerge(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    initFlowByCli(wd)
    shell("git merge --no-commit --no-ff pep8-fixes", wd)  # no conflicts, just not committed yet
    rw = mainWindow.openRepo(wd)
    assert rw.repo.state() == RepositoryState.MERGE
    assert not rw.repo.any_conflicts
    mergeHead = readTextFile(f"{wd}.git/MERGE_HEAD")

    triggerMenuAction(flowMenu(mainWindow), "start feature")
    acceptQMessageBox(rw, "a merge is in progress.+commit to conclude the merge, or abort it")
    assert not any(b.startswith("feature/") for b in rw.repo.branches.local)
    assert rw.repo.head_branch_shorthand == "master"
    assert readTextFile(f"{wd}.git/MERGE_HEAD") == mergeHead


def testStartValidatorRejectsRemoteBranchName(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git update-ref refs/remotes/origin/feature/x master", wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start feature")
    dlg = startDialog(rw, "feature")
    dlg.lineEdit.setText("x")
    assert not dlg.okButton.isEnabled()
    assert dlg.validator.inputs[0].error == "“feature/x” already exists on “origin”."
    dlg.reject()


def testStartFeatureDoesNotTrackBase(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git config branch.autoSetupMerge always", wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "start feature")
    dlg = startDialog(rw, "feature")
    dlg.lineEdit.setText("x")
    clickOk(dlg, dlg.buttonBox)
    assert rw.repo.head_branch_shorthand == "feature/x"
    assert rw.repo.branches.local["feature/x"].upstream is None


def testQuickLaunchGitFlowEntriesFollowRepo(tempDir, mainWindow):
    flowWd = unpackRepo(tempDir, renameTo="flow")
    plainWd = unpackRepo(tempDir, renameTo="plain")
    initFlowByCli(flowWd)
    mainWindow.openRepo(plainWd)
    flowRw = mainWindow.openRepo(flowWd)

    palette = openPalette(mainWindow)
    assert "Git Flow › Start Feature…" in palette.visibleTitles()
    assert paletteQuery(palette, "start feature") == ["Git Flow › Start Feature…"]
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    startDialog(flowRw, "feature").reject()

    mainWindow.tabs.setCurrentIndex(0)
    palette = openPalette(mainWindow)
    assert not any("Git Flow" in title for title in palette.visibleTitles())
    assert paletteQuery(palette, "start feature") == []
    palette.close()


# -----------------------------------------------------------------------------
# Finish feature

def makeFeature(wd: str, name: str = "x", base: str = "develop", checkout: bool = True):
    """A feature branch with one commit of its own, started from `base` the way git-flow does."""
    shell(f"""
        git checkout -q -b feature/{name} {base}
        echo {name} > {name}.txt
        git add {name}.txt
        git commit -q -m 'feature {name}'
        git config gitflow.branch.feature/{name}.base {base}
        {"" if checkout else f"git checkout -q {base}"}
    """, wd)


def makeConflictingFeature(wd: str):
    """feature/x and develop both change shared.txt, differently. HEAD on develop."""
    shell("""
        git checkout -q -b feature/x develop
        echo 'feature side' > shared.txt
        git add shared.txt
        git commit -q -m 'feature side'
        git config gitflow.branch.feature/x.base develop
        git checkout -q develop
        echo 'develop side' > shared.txt
        git add shared.txt
        git commit -q -m 'develop side'
    """, wd)


def countMerges(repo: Repo, branch: str) -> int:
    walker = repo.walk(repo.branches.local[branch].target)
    walker.simplify_first_parent()
    return sum(1 for commit in walker if len(commit.parent_ids) > 1)


def finishFromSidebar(rw, branch: str, pattern: str):
    menu = rw.sidebar.makeNodeMenu(rw.sidebar.findNodeByRef(RefPrefix.HEADS + branch))
    triggerMenuAction(menu, pattern)


def confirmFinish(rw, pattern: str, delete: bool = True):
    qmb = findQMessageBox(rw, pattern)
    assert qmb.checkBox().isChecked()  # deleting is the default, as in git-flow
    qmb.checkBox().setChecked(delete)
    qmb.accept()


@pytest.mark.parametrize("method", ["sidebar", "repomenu"])
@pytest.mark.parametrize("delete", [True, False])
def testFinishFeature(tempDir, mainWindow, method, delete):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    featureTip = repo.branches.local["feature/x"].target
    assert repo.head_branch_shorthand == "feature/x"

    if method == "sidebar":
        finishFromSidebar(rw, "feature/x", "finish feature .x.")
    else:
        assert "Finish Feature “x”…" in flowMenuTitles(mainWindow)
        triggerMenuAction(flowMenu(mainWindow), "finish feature .x.")

    qmb = findQMessageBox(rw, "merge .feature/x. into .develop.")
    assert qmb.checkBox().text() == "Delete local branch “feature/x” afterwards"
    confirmFinish(rw, "merge .feature/x. into .develop.", delete)

    # A merge commit, even for a single-commit feature
    mergeCommit = repo.peel_commit(repo.branches.local["develop"].target)
    assert mergeCommit.parent_ids[1] == featureTip
    assert mergeCommit.message.startswith("Merge branch 'feature/x' into develop")
    assert repo.head_branch_shorthand == "develop"

    assert ("feature/x" in repo.branches.local) == (not delete)
    assert repo.gitflow_branch_base("feature/x") == ("" if delete else "develop")
    config = readTextFile(f"{wd}.git/config")
    if delete:
        assert '"branch.feature/x"' not in config
    else:
        assert '"branch.feature/x"' in config
    assert re.search(r"feature/x.+finished", mainWindow.statusBar().currentMessage(), re.IGNORECASE)


def testFinishFeatureNotOnBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd)
    shell("git checkout -q master", wd)
    rw = mainWindow.openRepo(wd)
    featureTip = rw.repo.branches.local["feature/x"].target

    # Not the current branch: only the sidebar offers it
    assert not any(t.startswith("Finish") for t in flowMenuTitles(mainWindow))
    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")

    assert rw.repo.head_branch_shorthand == "develop"
    assert rw.repo.peel_commit(rw.repo.head_commit_id).parent_ids[1] == featureTip
    assert "feature/x" not in rw.repo.branches.local


def testFinishFeatureIntoRecordedBase(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git branch other master~1", wd)
    makeFeature(wd, base="other")
    rw = mainWindow.openRepo(wd)
    developBefore = rw.repo.branches.local["develop"].target
    featureTip = rw.repo.branches.local["feature/x"].target

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .other.")

    assert rw.repo.head_branch_shorthand == "other"
    assert rw.repo.peel_commit(rw.repo.branches.local["other"].target).parent_ids[1] == featureTip
    assert rw.repo.branches.local["develop"].target == developBefore


def testFinishFeatureConflictThenResume(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeConflictingFeature(wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    mergesBefore = countMerges(repo, "develop")

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")

    # Stopped in the usual merge state, saying how to pick up from here
    acceptQMessageBox(rw, r"merging .feature/x. into .develop. caused conflicts.+choose finish feature .x.… again")
    assert repo.state() == RepositoryState.MERGE
    assert repo.any_conflicts
    assert rw.mergeBanner.isVisible()
    assert rw.repoModel.prefs.draftCommitMessage.startswith("Merge branch 'feature/x' into develop")

    # Finishing again right away is refused: conflicts first, then the merge itself
    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    acceptQMessageBox(rw, "fix merge conflicts before")
    shell("git checkout --theirs shared.txt && git add shared.txt", wd)
    rw.refreshRepo()
    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    acceptQMessageBox(rw, "a merge is in progress")
    assert repo.state() == RepositoryState.MERGE

    # Conclude the merge with the message git prepared
    rw.diffArea.commitButton.click()
    commitDialog = findQDialog(rw, "commit")
    assert commitDialog.getFullMessage().startswith("Merge branch 'feature/x' into develop")
    commitDialog.accept()
    assert repo.state() == RepositoryState.NONE
    assert countMerges(repo, "develop") == mergesBefore + 1

    # One click away: the merge that just got committed is the feature's
    assert "Finish Feature “x”…" in flowMenuTitles(mainWindow)
    triggerMenuAction(flowMenu(mainWindow), "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")

    assert countMerges(repo, "develop") == mergesBefore + 1  # no second merge
    assert "feature/x" not in repo.branches.local
    assert repo.head_branch_shorthand == "develop"
    assert repo.gitflow_branch_base("feature/x") == ""


def testFinishFeatureAbortedMergeRetries(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeConflictingFeature(wd)
    rw = mainWindow.openRepo(wd)
    developTip = rw.repo.branches.local["develop"].target

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")
    acceptQMessageBox(rw, "caused conflicts")

    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "abort.+merge")
    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.branches.local["develop"].target == developTip

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")
    acceptQMessageBox(rw, "caused conflicts")
    assert rw.repo.state() == RepositoryState.MERGE
    assert "feature/x" in rw.repo.branches.local


def refsSnapshot(repo: Repo) -> dict[str, Oid]:
    return {name: repo.references[name].target for name in repo.listall_references()}


def testFinishRefusesDirtyTree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd)
    writeFile(f"{wd}master.txt", "changed\n")
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    acceptQMessageBox(rw, "uncommitted changes to tracked files")
    assert refsSnapshot(rw.repo) == refsBefore
    assert rw.repo.head_branch_shorthand == "feature/x"


def testFinishRefusesDetachedHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd)
    shell("git checkout -q --detach master", wd)
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    acceptQMessageBox(rw, "detached HEAD")
    assert refsSnapshot(rw.repo) == refsBefore


def testFinishRefusesWhenCheckedOutInOtherWorktree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd)
    worktreePath = os.path.normpath(f"{wd}/../elsewhere")
    shell(f"git worktree add -q {shlex.quote(worktreePath)} develop", wd)
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    acceptQMessageBox(rw, "develop. is checked out in another worktree")
    assert refsSnapshot(rw.repo) == refsBefore


def testFinishFeatureAheadOfItsUpstreamIsDeleted(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd)
    barePath = os.path.normpath(f"{wd}/../remote.git")
    shell(f"""
        git init -q --bare {shlex.quote(barePath)}
        git remote set-url origin {shlex.quote(barePath)}
        git push -q -u origin feature/x
        git commit -q --allow-empty -m 'not pushed yet'
    """, wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    pushedTip = repo.branches.remote["origin/feature/x"].target
    featureTip = repo.branches.local["feature/x"].target
    assert repo.compare_branch_with_remote("feature/x", "origin") == BranchComparison.AHEAD

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")

    # 'git branch -d' would refuse here: the branch is ahead of its upstream
    assert repo.peel_commit(repo.branches.local["develop"].target).parent_ids[1] == featureTip
    assert "feature/x" not in repo.branches.local
    # The remote branch is kept, and so is the base that git-flow would need to finish it from there
    assert repo.branches.remote["origin/feature/x"].target == pushedTip
    assert repo.gitflow_branch_base("feature/x") == "develop"
    assert re.search(r"feature/x.+finished.+feature/x.+is still on .origin", mainWindow.statusBar().currentMessage(),
                     re.IGNORECASE)


def testFinishStoppedByHookIsNotCalledAConflict(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd, checkout=False)
    shell("git commit -q --allow-empty -m 'develop moves on'", wd)  # so the merge isn't a no-op
    hookPath = f"{wd}.git/hooks/pre-merge-commit"
    writeFile(hookPath, "#!/bin/sh\necho 'merges need a ticket number' >&2\nexit 1\n")
    os.chmod(hookPath, 0o755)
    rw = mainWindow.openRepo(wd)

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")
    qmb = findQMessageBox(rw, "git stopped before committing the merge of .feature/x. into .develop.")
    assert "caused conflicts" not in qmb.text()
    assert "merges need a ticket number" in qmb.detailedText()
    qmb.accept()
    assert rw.repo.state() == RepositoryState.MERGE
    assert not rw.repo.any_conflicts
    assert "feature/x" in rw.repo.branches.local


def testFinishFeatureCheckoutFailureLeavesRepoAsItWas(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("""
        git checkout -q develop
        echo tracked > blocker.txt
        git add blocker.txt
        git commit -q -m 'blocker on develop'
    """, wd)
    makeFeature(wd, base="develop~1")
    shell("git config gitflow.branch.feature/x.base develop", wd)
    writeFile(f"{wd}blocker.txt", "untracked on feature/x\n")
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")
    qmb = findQMessageBox(rw, "untracked working tree files would be overwritten")
    assert "already done" not in qmb.text().lower()
    qmb.accept()
    assert refsSnapshot(rw.repo) == refsBefore
    assert rw.repo.head_branch_shorthand == "feature/x"


def testContinueFinishingMenuIgnoresStaleMergedBranches(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeFeature(wd, "old", checkout=False)
    shell("""
        git merge -q --no-ff --no-edit feature/old
        git commit -q --allow-empty -m 'develop moves on'
        git branch feature/new develop
    """, wd)
    makeConflictingFeature(wd)
    rw = mainWindow.openRepo(wd)
    assert rw.repo.head_branch_shorthand == "develop"

    startItems = ["Start Feature…", "Start Release…", "Start Hotfix…"]
    assert flowMenuTitles(mainWindow) == startItems

    finishFromSidebar(rw, "feature/x", "finish feature .x.")
    confirmFinish(rw, "merge .feature/x. into .develop.")
    acceptQMessageBox(rw, "caused conflicts")
    shell("git checkout --theirs shared.txt && git add shared.txt && git commit -q --no-edit", wd)
    rw.refreshRepo()

    assert flowMenuTitles(mainWindow) == startItems + ["Finish Feature “x”…"]


def testStartAndFinishRefusedDuringRebase(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeConflictingFeature(wd)
    shell("""
        git checkout -q feature/x
        git rebase develop || true
        git checkout --theirs shared.txt
        git add shared.txt
    """, wd)
    rw = mainWindow.openRepo(wd)
    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE  # what libgit2 calls git's default rebase
    assert not rw.repo.any_conflicts

    triggerMenuAction(flowMenu(mainWindow), "start feature")
    acceptQMessageBox(rw, "a rebase is in progress.+conclude or abort it")

    tasks.GitFlowFinishFeature.invoke(rw, "feature/x")
    acceptQMessageBox(rw, "a rebase is in progress.+conclude or abort it")
    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE  # what libgit2 calls git's default rebase


# -----------------------------------------------------------------------------
# Finish release / hotfix

def makeRelease(wd: str, version: str = "1.0", kind: str = "release", base: str = "develop"):
    """A release (or hotfix) branch with a version bump of its own, checked out."""
    shell(f"""
        git checkout -q -b {kind}/{version} {base}
        echo {version} > VERSION
        git add VERSION
        git commit -q -m 'Bump version to {version}'
        git config gitflow.branch.{kind}/{version}.base {base}
    """, wd)


def finishDialog(rw, kind: str = "release") -> TextInputDialog:
    return findQDialog(rw, f"finish {kind}", TextInputDialog)


def deleteCheckBoxOf(dlg: TextInputDialog) -> QCheckBox:
    return dlg.findChild(QCheckBox)


def tagNames(repo: Repo) -> list[str]:
    return sorted(repo.listall_tags())


def testFinishRelease(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeRelease(wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    releaseTip = repo.branches.local["release/1.0"].target
    tagsBefore = tagNames(repo)

    assert "Finish Release “1.0”…" in flowMenuTitles(mainWindow)
    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    dlg = finishDialog(rw)
    findChildWithText(dlg, r"release/1\.0. will be merged into .master., tagged .1\.0., and merged back into .develop.", QLabel)
    findChildWithText(dlg, r"message for tag .1\.0.:", QLabel)
    assert dlg.lineEdit.text() == "1.0"  # git-flow's default message
    assert deleteCheckBoxOf(dlg).text() == "Delete local branch “release/1.0” afterwards"
    assert deleteCheckBoxOf(dlg).isChecked()
    dlg.lineEdit.setText("")
    assert not dlg.okButton.isEnabled()
    dlg.lineEdit.setText("Release 1.0: faster checkout")
    clickOk(dlg, dlg.buttonBox)

    # Merged into master, with a merge commit
    masterMerge = repo.peel_commit(repo.branches.local["master"].target)
    assert masterMerge.parent_ids[1] == releaseTip

    # Tagged there, with an annotated tag
    tagObject = repo[repo.references["refs/tags/1.0"].target]
    assert isinstance(tagObject, Tag)
    assert tagObject.message == "Release 1.0: faster checkout\n"
    assert tagObject.peel(Commit).id == masterMerge.id
    assert tagNames(repo) == sorted(tagsBefore + ["1.0"])

    # The tag merged back into develop
    developMerge = repo.peel_commit(repo.branches.local["develop"].target)
    assert developMerge.parent_ids[1] == masterMerge.id
    assert developMerge.message.startswith("Merge tag '1.0' into develop")

    assert "release/1.0" not in repo.branches.local
    assert repo.head_branch_shorthand == "develop"
    assert re.search(r"release/1\.0.+finished.+tag .1\.0. created", mainWindow.statusBar().currentMessage(), re.IGNORECASE)


def testFinishReleaseVersionTagPrefix(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git config gitflow.prefix.versiontag v", wd)
    makeRelease(wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    dlg = finishDialog(rw)
    assert dlg.lineEdit.text() == "v1.0"
    clickOk(dlg, dlg.buttonBox)

    assert "v1.0" in rw.repo.listall_tags()
    assert "1.0" not in rw.repo.listall_tags()
    assert rw.repo.gitflow_tag_merges("v1.0", rw.repo.peel_commit(rw.repo.branches.local["master"].target).parent_ids[1])


def testFinishHotfix(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git checkout -q develop && git commit -q --allow-empty -m 'next release work'", wd)
    makeRelease(wd, "0.9.1", kind="hotfix", base="master")
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    hotfixTip = repo.branches.local["hotfix/0.9.1"].target

    finishFromSidebar(rw, "hotfix/0.9.1", "finish hotfix .0.9.1.")
    dlg = finishDialog(rw, "hotfix")
    clickOk(dlg, dlg.buttonBox)

    masterMerge = repo.peel_commit(repo.branches.local["master"].target)
    assert masterMerge.parent_ids[1] == hotfixTip
    assert repo.commit_id_from_tag_name("0.9.1") == masterMerge.id
    assert repo.get_tag_message("0.9.1") == "0.9.1"
    developMerge = repo.peel_commit(repo.branches.local["develop"].target)
    assert developMerge.parent_ids[1] == masterMerge.id
    assert "hotfix/0.9.1" not in repo.branches.local
    assert repo.head_branch_shorthand == "develop"


def testFinishReleaseConflictOnMasterThenResume(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeRelease(wd)
    shell("""
        git checkout -q master
        echo 'hotfixed on master' > VERSION
        git add VERSION
        git commit -q -m 'hotfix straight on master'
        git checkout -q release/1.0
    """, wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    masterMergesBefore = countMerges(repo, "master")
    developMergesBefore = countMerges(repo, "develop")

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)
    qmb = findQMessageBox(rw, r"merging .release/1\.0. into .master. caused conflicts.+finish release .1\.0.… again")
    assert "already done" not in qmb.text().lower()  # nothing was done before that
    qmb.accept()
    assert repo.state() == RepositoryState.MERGE
    assert "1.0" not in repo.listall_tags()

    shell("git checkout --theirs VERSION && git add VERSION && git commit -q --no-edit", wd)
    rw.refreshRepo()
    assert repo.head_branch_shorthand == "master"

    # Picks up with the tag and the back-merge only
    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    dlg = finishDialog(rw)
    assert dlg.lineEdit.isEnabled()  # no tag yet
    clickOk(dlg, dlg.buttonBox)

    assert countMerges(repo, "master") == masterMergesBefore + 1
    assert countMerges(repo, "develop") == developMergesBefore + 1
    assert repo.commit_id_from_tag_name("1.0") == repo.branches.local["master"].target
    assert "release/1.0" not in repo.branches.local


def makeReleaseThatConflictsOnBackmerge(wd: str):
    makeRelease(wd)
    shell("""
        git checkout -q develop
        echo 'develop moved on' > VERSION
        git add VERSION
        git commit -q -m 'develop changes VERSION too'
        git checkout -q release/1.0
    """, wd)


def testFinishReleaseConflictOnBackmergeThenResume(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeReleaseThatConflictsOnBackmerge(wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    masterMergesBefore = countMerges(repo, "master")

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    dlg = finishDialog(rw)
    dlg.lineEdit.setText("Release 1.0")
    clickOk(dlg, dlg.buttonBox)

    acceptQMessageBox(rw, r"merging .1\.0. into .develop. caused conflicts.+"
                          r"already done: merged into .master., tagged .1\.0.\.")
    assert repo.state() == RepositoryState.MERGE
    assert repo.head_branch_shorthand == "develop"
    assert rw.repoModel.prefs.draftCommitMessage.startswith("Merge tag '1.0' into develop")
    tagTarget = repo.commit_id_from_tag_name("1.0")

    shell("git checkout --theirs VERSION && git add VERSION && git commit -q --no-edit", wd)
    rw.refreshRepo()

    # The back-merge is committed: HEAD merges the tag, so Finish is offered again
    assert "Finish Release “1.0”…" in flowMenuTitles(mainWindow)
    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    dlg = finishDialog(rw)
    assert not dlg.lineEdit.isEnabled()
    assert dlg.lineEdit.text() == "Release 1.0"
    findChildWithText(dlg, r"tag .1\.0. already exists and will be kept", QLabel)
    clickOk(dlg, dlg.buttonBox)

    assert countMerges(repo, "master") == masterMergesBefore + 1
    assert repo.commit_id_from_tag_name("1.0") == tagTarget
    assert "release/1.0" not in repo.branches.local
    assert repo.head_branch_shorthand == "develop"


def testFinishReleaseCheckoutFailureMidwayReportsDoneSteps(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeRelease(wd)
    shell("""
        git checkout -q develop
        echo tracked > blocker.txt
        git add blocker.txt
        git commit -q -m 'blocker on develop'
        git checkout -q release/1.0
    """, wd)
    writeFile(f"{wd}blocker.txt", "untracked here\n")
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    masterMergesBefore = countMerges(repo, "master")

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)
    acceptQMessageBox(rw, r"already done: merged into .master., tagged .1\.0.\..+untracked working tree files would be overwritten")
    assert countMerges(repo, "master") == masterMergesBefore + 1
    assert "release/1.0" in repo.branches.local

    os.unlink(f"{wd}blocker.txt")
    rw.refreshRepo()
    finishFromSidebar(rw, "release/1.0", "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)

    assert countMerges(repo, "master") == masterMergesBefore + 1  # merged into master once in all
    assert repo.is_ancestor(repo.commit_id_from_tag_name("1.0"), repo.branches.local["develop"].target)
    assert "release/1.0" not in repo.branches.local


def testFinishReleaseTagClash(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeRelease(wd)
    shell("git tag 1.0 master~1", wd)
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    acceptQMessageBox(rw, r"tag .1\.0. already exists and doesn.t point to a merge of .release/1\.0.+delete or rename that tag")
    assert refsSnapshot(rw.repo) == refsBefore
    assert rw.repo.head_branch_shorthand == "release/1.0"


def testFinishReleaseTagsTheMergeNotMastersTip(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeRelease(wd)
    shell("""
        git checkout -q master
        echo 'hotfixed on master' > VERSION
        git add VERSION
        git commit -q -m 'hotfix straight on master'
        git checkout -q release/1.0
    """, wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)
    acceptQMessageBox(rw, "caused conflicts")
    shell("""
        git checkout --theirs VERSION && git add VERSION && git commit -q --no-edit
        git commit -q --allow-empty -m 'something else on master, after the merge'
    """, wd)
    rw.refreshRepo()
    mergeCommit = repo.peel_commit(repo.branches.local["master"].target).parent_ids[0]

    finishFromSidebar(rw, "release/1.0", "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)

    assert repo.commit_id_from_tag_name("1.0") == mergeCommit
    assert repo.gitflow_tag_merges("1.0", repo.peel_commit(mergeCommit).parent_ids[1])
    assert "release/1.0" not in repo.branches.local


def testFinishReleaseAlreadyInMasterIsNotLockedOutByItsOwnTag(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeRelease(wd)
    shell("git checkout -q master && git merge -q --ff-only release/1.0 && git checkout -q release/1.0", wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    releaseTip = repo.branches.local["release/1.0"].target

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    dlg = finishDialog(rw)
    deleteCheckBoxOf(dlg).setChecked(False)
    clickOk(dlg, dlg.buttonBox)
    assert repo.commit_id_from_tag_name("1.0") == releaseTip  # no merge commit to tag: the tip itself
    assert repo.branches.local["master"].target == releaseTip
    assert "release/1.0" in repo.branches.local

    finishFromSidebar(rw, "release/1.0", "finish release .1.0.")
    dlg = finishDialog(rw)
    assert not dlg.lineEdit.isEnabled()
    deleteCheckBoxOf(dlg).setChecked(False)
    clickOk(dlg, dlg.buttonBox)
    assert re.search(r"nothing left to do: .release/1\.0. is already finished",
                     mainWindow.statusBar().currentMessage(), re.IGNORECASE)


def testFinishReleaseNewCommitAfterTagIsRefused(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeReleaseThatConflictsOnBackmerge(wd)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)
    acceptQMessageBox(rw, "caused conflicts")
    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "abort.+merge")
    assert rw.repo.state() == RepositoryState.NONE

    # The tag was made for the release as it was then: don't tag or merge a newer state under that version
    shell("git checkout -q release/1.0 && git commit -q --allow-empty -m 'one more fix'", wd)
    rw.refreshRepo()
    refsBefore = refsSnapshot(rw.repo)
    finishFromSidebar(rw, "release/1.0", "finish release .1.0.")
    acceptQMessageBox(rw, r"tag .1\.0. already exists and doesn.t point to a merge of .release/1\.0.")
    assert refsSnapshot(rw.repo) == refsBefore


def testFinishHotfixWithoutCommitsRefused(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git branch hotfix/0.9.1 master && git config gitflow.branch.hotfix/0.9.1.base master", wd)
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    finishFromSidebar(rw, "hotfix/0.9.1", "finish hotfix .0.9.1.")
    acceptQMessageBox(rw, r"hotfix/0\.9\.1. has no commits of its own.+commit the fix on it first")
    assert refsSnapshot(rw.repo) == refsBefore
    assert "0.9.1" not in rw.repo.listall_tags()


def testFinishHotfixWithoutCommonAncestorRefused(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("""
        git checkout -q --orphan hotfix/0.9.1
        git commit -q --allow-empty -m 'unrelated history'
        git checkout -q master
    """, wd)
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    finishFromSidebar(rw, "hotfix/0.9.1", "finish hotfix .0.9.1.")
    acceptQMessageBox(rw, r"hotfix/0\.9\.1. has no common ancestor with .master.")
    assert refsSnapshot(rw.repo) == refsBefore


def testFinishReleaseKeepBranchThenFinishAgain(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    makeRelease(wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    dlg = finishDialog(rw)
    deleteCheckBoxOf(dlg).setChecked(False)
    clickOk(dlg, dlg.buttonBox)
    assert "release/1.0" in repo.branches.local
    assert repo.gitflow_branch_base("release/1.0") == "develop"
    refsAfterFirstRun = refsSnapshot(repo)

    finishFromSidebar(rw, "release/1.0", "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)

    # Only the branch went: no new merge, no new tag
    del refsAfterFirstRun["refs/heads/release/1.0"]
    assert refsSnapshot(repo) == refsAfterFirstRun
    assert repo.gitflow_branch_base("release/1.0") == ""


def testFinishReleaseStartedFromOtherBase(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    initFlowByCli(wd)
    shell("git branch support/1.x master", wd)
    makeRelease(wd, base="support/1.x")
    rw = mainWindow.openRepo(wd)
    refsBefore = refsSnapshot(rw.repo)

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    acceptQMessageBox(rw, r"release/1\.0. was started from .support/1\.x., not from .develop.+git-flow command line tools")
    assert refsSnapshot(rw.repo) == refsBefore


# -----------------------------------------------------------------------------
# Working with the git-flow command line tools

requiresGitFlowCli = pytest.mark.skipif(
    not shutil.which("git-flow"),
    reason="Requires the git-flow command line tools (AVH edition)")


@requiresGitFlowCli
def testCliFinishesWhatWeStarted(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    clickOk(openInitDialog(mainWindow, rw), findQDialog(rw, "initialize git flow", GitFlowInitDialog).ui.buttonBox)
    for kind, name in [("feature", "login"), ("release", "2.0")]:
        triggerMenuAction(flowMenu(mainWindow), f"start {kind}")
        dlg = startDialog(rw, kind)
        dlg.lineEdit.setText(name)
        clickOk(dlg, dlg.buttonBox)

    shell("""
        export GIT_MERGE_AUTOEDIT=no
        git checkout -q feature/login
        echo login > login.txt
        git add login.txt
        git commit -q -m 'Log in'
        git flow feature finish login
        git checkout -q release/2.0
        echo 2.0 > VERSION
        git add VERSION
        git commit -q -m 'Bump version to 2.0'
        git flow release finish -m 'Release 2.0' 2.0
    """, wd)

    with RepoContext(wd) as repo:
        assert not any(b.startswith(("feature/", "release/")) for b in repo.branches.local)
        develop = repo.branches.local["develop"].target
        assert repo.is_ancestor(repo.commit_id_from_tag_name("2.0"), develop)
        assert repo.get_tag_message("2.0") == "Release 2.0"
        assert repo.gitflow_tag_merges("2.0", repo.peel_commit(repo.commit_id_from_tag_name("2.0")).parent_ids[1])
        assert "login.txt" in repo.peel_tree(develop)
        assert "VERSION" in repo.peel_tree(repo.branches.local["master"].target)


@requiresGitFlowCli
def testWeFinishWhatCliStarted(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch develop  # in a repo with branches, 'git flow init -d' won't create it
        git flow init -d
        git flow feature start search
        echo search > search.txt
        git add search.txt
        git commit -q -m 'Search'
        git checkout -q develop
        git flow release start 1.0
        echo 1.0 > VERSION
        git add VERSION
        git commit -q -m 'Bump version to 1.0'
    """, wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    assert flowMenuTitles(mainWindow) == ["Start Feature…", "Start Release…", "Start Hotfix…", "Finish Release “1.0”…"]

    triggerMenuAction(flowMenu(mainWindow), "finish release .1.0.")
    clickOk(finishDialog(rw), finishDialog(rw).buttonBox)
    finishFromSidebar(rw, "feature/search", "finish feature .search.")
    confirmFinish(rw, "merge .feature/search. into .develop.")

    assert not any(b.startswith(("feature/", "release/")) for b in repo.branches.local)
    assert repo.gitflow_tag_merges("1.0", repo.peel_commit(repo.commit_id_from_tag_name("1.0")).parent_ids[1])
    assert repo.is_ancestor(repo.commit_id_from_tag_name("1.0"), repo.branches.local["develop"].target)
    assert "search.txt" in repo.peel_tree(repo.branches.local["develop"].target)
    # What git-flow recorded is gone along with the branches
    assert not any(e.name.startswith("gitflow.branch.") and e.name.endswith(".base")
                   for e in GitConfig(f"{wd}.git/config"))

    # And git-flow still sees a repo it can work with
    shell("git flow feature start next && git flow feature list", wd)


# -----------------------------------------------------------------------------
# Localization

GITFLOW_SOURCES = ["tasks/gitflowtasks.py", "forms/gitflowinitdialog.py", "forms/ui_gitflowinitdialog.py"]

GITFLOW_STRINGS_ELSEWHERE = [
    "&Git Flow",  # repowidget.py
    # taskbook.py
    "Initialize Git Flow", "Start feature", "Start release", "Start hotfix",
    "Finish feature", "Finish release", "Finish hotfix",
    "Set up the Git Flow branches and prefixes in this repo",
    "Branch off the development branch to work on a feature",
    "Branch off the development branch to prepare a release",
    "Branch off the production branch to fix a release",
    "Merge this feature into the development branch",
    "Merge into production, tag the version, merge back into development",
]


def gitFlowMsgids() -> list[tuple[str, str]]:
    """(context, msgid) of every string that the Git Flow code passes to _() or _p()."""
    import gitfourchette
    srcDir = Path(gitfourchette.__file__).parent
    msgids = [("", msgid) for msgid in GITFLOW_STRINGS_ELSEWHERE]
    for source in GITFLOW_SOURCES:
        tree = ast.parse((srcDir / source).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "_p")):
                continue
            strings = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
            if node.func.id == "_p":
                msgids.append((strings[0], strings[1]))
            else:
                msgids.append(("", strings[0]))
    return list(dict.fromkeys(msgids))


def testGitFlowIsTranslatedInForkLanguages(qapp):
    msgids = gitFlowMsgids()
    assert len(msgids) > 80  # the extraction found the code's strings

    for context, msgid in msgids:
        assertTranslatedInForkLanguages(msgid, context=context)

    # The template carries them too, for upstream's translators
    template = Path(QFile("assets:lang/gitfourchette.pot").fileName()).read_text(encoding="utf-8")
    for context, msgid in msgids:
        entry = f'msgid "{msgid}"'
        if context:
            entry = f'msgctxt "{context}"\n' + entry
        assert entry in template, f"not in the .pot: {msgid!r}"

