# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Worktree management tasks.

Worktrees are handled by calling vanilla git: libgit2 can create and prune
worktrees, but it won't check out a branch in one, which is the entire point.
"""

import os

from gitfourchette.forms.newworktreedialog import NewWorktreeDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *


class _WorktreeTask(RepoTask):
    def findWorktree(self, name: str) -> WorktreeInfo:
        worktree = self.repoModel.worktreeByName(name)
        if worktree is None:
            raise AbortTask(_("This worktree is gone. Refresh the repo and try again."))
        return worktree

    @staticmethod
    def worktreeLabel(worktree: WorktreeInfo) -> str:
        return os.path.basename(worktree.path) or worktree.name


class NewWorktree(_WorktreeTask):
    def flow(self):
        repo = self.repo

        # git refuses to check out a branch that's already in another worktree
        checkedOut = {w.head for w in self.repoModel.worktrees if w.head}
        localBranches = list(repo.branches.local)
        availableBranches = [b for b in localBranches if RefPrefix.HEADS + b not in checkedOut]

        # Default to a sibling of this workdir, which is where people
        # usually keep worktrees of the same repo.
        parentDir = os.path.dirname(os.path.normpath(repo.workdir))

        dlg = NewWorktreeDialog(
            parentDir=parentDir,
            availableBranches=availableBranches,
            reservedNames=localBranches,
            parent=self.parentWidget())
        yield from self.flowDialog(dlg)

        path = dlg.absolutePath()
        newBranch = dlg.newBranchName
        existingBranch = dlg.existingBranchName
        detached = dlg.detached
        dlg.deleteLater()

        self.epilog.effects |= TaskEffects.Refs

        args = ["worktree", "add"]
        if newBranch:
            args += ["-b", newBranch]
        elif detached:
            args += ["--detach"]
        args += ["--", path]
        if existingBranch:
            args += [existingBranch]

        yield from self.flowCallGit(*args)

        self.epilog.status = _("Worktree {0} created.", tquo(os.path.basename(path)))


class RemoveWorktree(_WorktreeTask):
    def flow(self, name: str):
        worktree = self.findWorktree(name)
        label = self.worktreeLabel(worktree)

        if worktree.is_main:
            raise AbortTask(_("The main worktree can’t be removed."))
        if worktree.is_current:
            raise AbortTask(paragraphs(
                _("You can’t remove the worktree you’re currently looking at."),
                _("Open another worktree of this repo first.")))

        yield from self.flowConfirm(
            text=paragraphs(
                _("Really remove worktree {0}?", bquo(label)),
                _("Its folder {0} will be deleted.", hquo(worktree.path)),
                _("Any uncommitted changes in it will be lost. This cannot be undone!")),
            buttonIcon="SP_DialogDiscardButton",
            verb=_("Remove"))

        self.epilog.effects |= TaskEffects.Refs

        driver = yield from self.flowCallGit(
            "worktree", "remove", "--", worktree.path, autoFail=False)

        if driver.exitCode() != 0:
            # git bails out if the worktree has uncommitted changes or untracked
            # files. Say so, and let the user insist.
            yield from self.flowConfirm(
                text=paragraphs(
                    _("Git refused to remove worktree {0}.", bquo(label)),
                    _("It probably contains uncommitted changes or untracked files."),
                    _("Force the removal and lose those changes?")),
                detailList=[driver.stderrScrollback().strip()],
                buttonIcon="SP_DialogDiscardButton",
                verb=_("Force remove"))
            yield from self.flowCallGit("worktree", "remove", "--force", "--", worktree.path)

        self.epilog.status = _("Worktree {0} removed.", tquo(label))


class LockWorktree(_WorktreeTask):
    def flow(self, name: str):
        worktree = self.findWorktree(name)
        label = self.worktreeLabel(worktree)

        dlg = TextInputDialog(
            self.parentWidget(),
            _("Lock worktree"),
            _("Why lock {0}?", bquo(label)),
            subtitle=_("Locking a worktree stops git from pruning it — useful if it "
                       "lives on a removable drive or a network share."))
        dlg.okButton.setText(_("Lock"))
        yield from self.flowDialog(dlg)
        reason = dlg.lineEdit.text().strip()
        dlg.deleteLater()

        self.epilog.effects |= TaskEffects.Refs

        args = ["worktree", "lock"]
        if reason:
            args += ["--reason", reason]
        args += ["--", worktree.path]
        yield from self.flowCallGit(*args)

        self.epilog.status = _("Worktree {0} locked.", tquo(label))


class UnlockWorktree(_WorktreeTask):
    def flow(self, name: str):
        worktree = self.findWorktree(name)
        label = self.worktreeLabel(worktree)

        self.epilog.effects |= TaskEffects.Refs
        yield from self.flowCallGit("worktree", "unlock", "--", worktree.path)
        self.epilog.status = _("Worktree {0} unlocked.", tquo(label))


class PruneWorktrees(_WorktreeTask):
    def flow(self):
        stale = [w for w in self.repoModel.worktrees if w.prunable and not w.locked]

        if not stale:
            raise AbortTask(_("There are no stale worktrees to prune."), icon="information")

        yield from self.flowConfirm(
            text=paragraphs(
                _n("Really forget {n} stale worktree?",
                   "Really forget {n} stale worktrees?", len(stale)),
                _("Their folders are gone, so git can drop their administrative files.")),
            detailList=[self.worktreeLabel(w) or w.name for w in stale],
            verb=_("Prune"))

        self.epilog.effects |= TaskEffects.Refs
        yield from self.flowCallGit("worktree", "prune")
        self.epilog.status = _n("{n} stale worktree pruned.",
                                "{n} stale worktrees pruned.", len(stale))
