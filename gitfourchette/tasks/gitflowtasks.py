# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Git Flow: feature, release and hotfix branches, the way the git-flow command
line tools (AVH edition) do them, without needing those tools.

The settings live under the same config keys as git-flow's, so a repo set up
here works with git-flow, Fork and SourceTree, and the other way around.
"""

from typing import ClassVar

from gitfourchette import trtables
from gitfourchette.forms.gitflowinitdialog import GitFlowInitDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.branchtasks import flowConfirmLeavingDetachedHead
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskPrereqs, TaskEffects
from gitfourchette.toolbox import *


class GitFlowTask(RepoTask):
    """Checks and git steps shared by the Git Flow tasks."""

    def gitFlow(self) -> GitFlowConfig:
        cfg = self.repo.gitflow_config()
        if cfg is None:
            raise AbortTask(_("Git Flow isn’t set up in this repo."))
        return cfg

    def requireNoOperationInProgress(self):
        """
        Refuse to go on while a merge, rebase, etc. is in progress, even with
        every conflict resolved: a new branch would carry the pending merge.
        """
        state = self.repo.state()

        if state == RepositoryState.NONE:
            return

        if state == RepositoryState.MERGE:
            text = paragraphs(
                _("A merge is in progress."),
                _("Commit to conclude the merge, or abort it, then try again."))
            raise AbortTask(text)

        if state in (RepositoryState.REBASE, RepositoryState.REBASE_INTERACTIVE,
                     RepositoryState.REBASE_MERGE, RepositoryState.APPLY_MAILBOX_OR_REBASE):
            sentence = _("A rebase is in progress.")
        elif state in (RepositoryState.REVERT, RepositoryState.REVERT_SEQUENCE):
            sentence = _("A revert is in progress.")
        elif state in (RepositoryState.CHERRYPICK, RepositoryState.CHERRYPICK_SEQUENCE):
            sentence = _("A cherry-pick is in progress.")
        elif state == RepositoryState.BISECT:
            sentence = _("A bisect is in progress.")
        else:
            raise AbortTask(_(
                "The repo is currently in state {state}, which {app} doesn’t support yet. "
                "Use <code>git</code> on the command line to continue.",
                app=qAppName(), state=bquo(trtables.enum(state))))

        raise AbortTask(paragraphs(sentence, _("Conclude or abort it, then try again.")))

    def requireLocalBranch(self, branch: str):
        if branch not in self.repo.branches.local:
            raise AbortTask(_("There’s no local branch named {0}.", bquo(branch)))

    def requireNotBehindRemote(self, branch: str):
        """
        Refuse to build on a branch that is behind its namesake on the remote,
        as last fetched (this doesn't fetch). Being ahead is fine.
        """
        origin = self.repo.gitflow_origin()
        comparison = self.repo.compare_branch_with_remote(branch, origin)
        remoteBranch = f"{origin}/{branch}"

        if comparison == BranchComparison.BEHIND:
            raise AbortTask(paragraphs(
                _("{0} is behind {1}.", bquo(branch), bquo(remoteBranch)),
                _("Fast-forward it, then try again.")))
        elif comparison == BranchComparison.DIVERGED:
            raise AbortTask(paragraphs(
                _("{0} and {1} have diverged.", bquo(branch), bquo(remoteBranch)),
                _("Merge them, then try again.")))

    def flowRequireCleanTree(self, allowDirtyKey: str = ""):
        """
        Refuse to go on if tracked files have uncommitted changes, staged or
        not. Untracked files are fine, as in git-flow.
        """
        if allowDirtyKey and self.repo.gitflow_flag(allowDirtyKey):
            return

        for args in (["diff", "--quiet", "--ignore-submodules"],
                     ["diff", "--cached", "--quiet", "--ignore-submodules", "HEAD", "--"]):
            driver = yield from self.flowCallGit(*args, autoFail=False)
            exitCode = driver.exitCode()
            if exitCode == 1:
                raise AbortTask(paragraphs(
                    _("You have uncommitted changes to tracked files."),
                    _("Before performing this action, commit your changes or stash them.")))
            elif exitCode != 0:
                # Not "clean": git couldn't tell (e.g. corrupt index)
                raise AbortTask(driver.htmlErrorText())

    def flowCheckout(self, branch: str):
        """Switch to a local branch, unless it's already checked out."""
        if not self.repo.head_is_detached and self.repo.head_branch_shorthand == branch:
            return
        self.epilog.effects |= TaskEffects.Refs | TaskEffects.Head | TaskEffects.Workdir
        yield from self.flowCallGit("checkout", "--progress", "--no-guess", branch)


class GitFlowInit(GitFlowTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoConflicts

    def flow(self):
        repo = self.repo

        self.requireNoOperationInProgress()
        yield from self.flowRequireCleanTree()

        origin = repo.gitflow_origin()
        localBranches = repo.listall_branches(BranchType.LOCAL)
        remoteBranches = repo.listall_remote_branches().get(origin, [])

        dlg = GitFlowInitDialog(repo.gitflow_suggest_config(), localBranches, origin, remoteBranches,
                                parent=self.parentWidget())
        yield from self.flowDialog(dlg)
        cfg = dlg.config()
        switchToDevelop = dlg.switchToDevelop()
        dlg.deleteLater()

        # Create the development branch before writing the config, so that a
        # failure here leaves the repo without Git Flow rather than half set up
        createdDevelop = cfg.develop not in repo.branches.local
        if createdDevelop:
            self.epilog.effects |= TaskEffects.Refs | TaskEffects.Upstreams
            if cfg.develop in remoteBranches:
                yield from self.flowCallGit("branch", "--track", cfg.develop, f"{origin}/{cfg.develop}")
            else:
                yield from self.flowCallGit("branch", "--no-track", cfg.develop, cfg.master)

        yield from self.flowEnterWorkerThread()
        repo.gitflow_write_config(cfg)
        yield from self.flowEnterUiThread()

        if createdDevelop and switchToDevelop:
            yield from self.flowCheckout(cfg.develop)

        self.epilog.status = _("Git Flow is set up: {0} for releases, {1} for development.",
                               tquo(cfg.master), tquo(cfg.develop))


class GitFlowStart(GitFlowTask):
    """Branch off a feature, release or hotfix, and remember where it started from."""

    kind: ClassVar[GitFlowKind]

    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoConflicts | TaskPrereqs.NoCherrypick

    def flow(self, name: str = ""):
        repo = self.repo
        kind = self.kind
        cfg = self.gitFlow()
        prefix = cfg.prefix(kind)
        if not prefix:
            raise AbortTask(_("This repo’s Git Flow settings have no prefix for this kind of branch."))

        base = cfg.master if kind == GitFlowKind.HOTFIX else cfg.develop

        self.requireNoOperationInProgress()
        self.requireLocalBranch(base)

        localBranches = repo.listall_branches(BranchType.LOCAL)

        # One release at a time, and one hotfix unless gitflow.multi-hotfix says otherwise
        if kind == GitFlowKind.RELEASE or (kind == GitFlowKind.HOTFIX and not repo.gitflow_flag("gitflow.multi-hotfix")):
            openBranch = next((b for b in localBranches if b.startswith(prefix)), "")
            if openBranch and kind == GitFlowKind.RELEASE:
                raise AbortTask(_("Release branch {0} is still open. Finish it before you start another release.",
                                  bquo(openBranch)))
            elif openBranch:
                raise AbortTask(_("Hotfix branch {0} is still open. Finish it before you start another hotfix.",
                                  bquo(openBranch)))

        if kind != GitFlowKind.FEATURE:
            yield from self.flowRequireCleanTree("gitflow.allowdirty")

        self.requireNotBehindRemote(base)

        # Ask for the name
        origin = repo.gitflow_origin()
        remoteBranches = set(repo.listall_remote_branches().get(origin, []))
        tags = set(repo.listall_tags())
        nameTaken = _("This name is already taken by another local branch.")

        def validate(text: str) -> str:
            if not text:
                return nameValidationMessage(text, [])
            branch = prefix + text
            message = nameValidationMessage(branch, localBranches, nameTaken)
            if message:
                return message
            if branch in remoteBranches:
                return _("{0} already exists on {1}.", tquo(branch), tquo(origin))
            if kind != GitFlowKind.FEATURE:
                tag = cfg.tag_name(text)
                message = nameValidationMessage(tag, [])
                if message:
                    return message
                if tag in tags:
                    return _("Tag {0} already exists.", tquo(tag))
            return ""

        if kind == GitFlowKind.FEATURE:
            label = _("Feature name:")
        elif kind == GitFlowKind.RELEASE:
            label = _("Release version:")
        else:
            label = _("Hotfix version:")

        dlg = TextInputDialog(
            self.parentWidget(),
            self.name(),
            label,
            subtitle=_("Starts from {0}. The branch name begins with {1}.", tquo(base), tquo(prefix)))
        dlg.setText(name)
        dlg.setValidator(validate)
        dlg.validator.run(silenceEmptyWarnings=True)
        dlg.lineEdit.setValidator(ReplaceSpacesWithDashes())
        dlg.okButton.setText(_("Start"))

        yield from self.flowDialog(dlg)
        branch = prefix + dlg.lineEdit.text()
        dlg.deleteLater()

        if self.repoModel.dangerouslyDetachedHead():
            yield from flowConfirmLeavingDetachedHead(self, branch)

        # Create and check out in one go: if the checkout fails, there's no branch left behind.
        # --no-track: with branch.autoSetupMerge=always, the new branch would track the base.
        self.epilog.effects |= TaskEffects.Refs | TaskEffects.Head | TaskEffects.Workdir
        yield from self.flowCallGit("checkout", "--progress", "--no-track", "-b", branch, base)

        # Where to merge it back when it's finished (git-flow reads the same key)
        repo.gitflow_set_branch_base(branch, base)

        self.epilog.jumpTo = NavLocator.inRef(RefPrefix.HEADS + branch)
        self.epilog.status = _("Branch {0} started from {1}.", tquo(branch), tquo(base))


class GitFlowStartFeature(GitFlowStart):
    kind = GitFlowKind.FEATURE


class GitFlowStartRelease(GitFlowStart):
    kind = GitFlowKind.RELEASE


class GitFlowStartHotfix(GitFlowStart):
    kind = GitFlowKind.HOTFIX


START_TASKS: dict[GitFlowKind, type[GitFlowStart]] = {
    GitFlowKind.FEATURE: GitFlowStartFeature,
    GitFlowKind.RELEASE: GitFlowStartRelease,
    GitFlowKind.HOTFIX: GitFlowStartHotfix,
}
