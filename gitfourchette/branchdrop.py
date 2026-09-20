# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Dragging a branch onto another ref, in the sidebar or in the graph.

Both views send the same payload and open the same menu when it lands, so the
gesture means the same thing wherever you make it. The drop asks what it should
do instead of deciding for you: a merge and a reset start from the identical
gesture, and picking the wrong one is the kind of mistake that takes an
afternoon to undo.
"""

from __future__ import annotations

from dataclasses import dataclass

from gitfourchette.localization import *
from gitfourchette.porcelain import Oid, RefPrefix
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.tasks import CherrypickCommit, FastForwardBranch, MergeBranch, NewBranchFromCommit, ResetHead
from gitfourchette.tasks.taskbook import TaskBook
from gitfourchette.toolbox import ActionDef, lquoe, shortHash

BRANCH_MIME_TYPE = "application/x-gitfourchette-branch"

DRAGGABLE_PREFIXES = (RefPrefix.HEADS, RefPrefix.REMOTES)
"""Only branches travel: a tag isn't something you can merge from or advance."""


@dataclass(frozen=True)
class BranchDropTarget:
    """Where a dragged branch landed: a local branch, or a bare commit."""

    oid: Oid
    ref: str = ""

    @property
    def name(self) -> str:
        return RefPrefix.split(self.ref)[1] if self.ref else shortHash(self.oid)

    @property
    def isLocalBranch(self) -> bool:
        return self.ref.startswith(RefPrefix.HEADS)


def branchDragMimeData(ref: str) -> QMimeData:
    mime = QMimeData()
    mime.setData(BRANCH_MIME_TYPE, ref.encode())
    return mime


def draggedBranch(mime: QMimeData) -> str:
    """The ref a drag is carrying, or an empty string if it carries something else."""
    if not mime.hasFormat(BRANCH_MIME_TYPE):
        return ""
    return bytes(mime.data(BRANCH_MIME_TYPE)).decode("utf-8", errors="replace")


def isBranchDrag(event: QDropEvent, repoModel: RepoModel) -> bool:
    """
    True if this drag started on a branch in the same repo, wherever in the
    window it started: the sidebar and the graph take each other's drags.
    """
    if repoModel is None or not event.mimeData().hasFormat(BRANCH_MIME_TYPE):
        return False
    return getattr(event.source(), "repoModel", None) is repoModel


def branchDropHint(source: str, target: BranchDropTarget) -> str:
    """What the status bar says while a branch hovers over a drop target."""
    return _("Drop {0} on {1} to pick an operation", RefPrefix.split(source)[1], target.name)


def branchDropActions(
        invoker: QWidget,
        repoModel: RepoModel,
        source: str,
        target: BranchDropTarget,
) -> list[ActionDef]:
    """
    Everything the drop of `source` onto `target` could mean. An operation that
    doesn't apply here stays in the menu, disabled, and says why: a menu whose
    items come and go teaches nothing about what the gesture can do.
    """

    sourceTip = repoModel.refs[source]
    sourceDisplay = lquoe(RefPrefix.split(source)[1])
    targetDisplay = lquoe(target.name)

    homeBranch = repoModel.homeBranch
    isHomeBranch = bool(homeBranch) and target.ref == RefPrefix.HEADS + homeBranch

    # Merge: the destination has to be a branch that can take the commit
    mergeWhyNot = "" if target.isLocalBranch else _("Drop on a local branch to merge into it.")

    # Cherry-pick: the commit lands in the working directory, so the only
    # target it can honour is the branch you're already standing on
    if isHomeBranch:
        cherrypickWhyNot = ""
    elif target.isLocalBranch:
        cherrypickWhyNot = _("Check out {0} to cherry-pick onto it.", targetDisplay)
    else:
        cherrypickWhyNot = _("Drop on the checked-out branch to cherry-pick onto it.")

    # Reset: git only ever moves the branch you're standing on
    if not homeBranch:
        resetWhyNot = _("Check out a branch to reset it.")
    elif not isHomeBranch:
        resetWhyNot = _("Only the checked-out branch can be reset. Drop on {0} instead.", lquoe(homeBranch))
    else:
        resetWhyNot = ""

    # Fast-forward: only along the track the branch already follows
    if not target.isLocalBranch:
        forwardWhyNot = _("Drop on a local branch to fast-forward it.")
    elif RefPrefix.REMOTES + repoModel.upstreams.get(target.name, "") != source:
        forwardWhyNot = _("{0} doesn’t track {1}.", targetDisplay, sourceDisplay)
    else:
        forwardWhyNot = ""

    return [
        _dropAction(
            MergeBranch, mergeWhyNot,
            _("&Merge {0} into {1}…", sourceDisplay, targetDisplay),
            lambda: MergeBranch.invoke(invoker, source, destination=target.ref)),

        _dropAction(
            CherrypickCommit, cherrypickWhyNot,
            _("Cherry-&pick {0}…", lquoe(shortHash(sourceTip))),
            lambda: CherrypickCommit.invoke(invoker, sourceTip)),

        ActionDef.SEPARATOR,

        _dropAction(
            ResetHead, resetWhyNot,
            _("&Reset {0} to {1}…", targetDisplay, sourceDisplay),
            lambda: ResetHead.invoke(invoker, sourceTip)),

        _dropAction(
            FastForwardBranch, forwardWhyNot,
            _("&Fast-forward {0} to {1}…", targetDisplay, sourceDisplay),
            lambda: FastForwardBranch.invoke(invoker, target.name)),

        ActionDef.SEPARATOR,

        _dropAction(
            NewBranchFromCommit, "",
            _("New &Branch Here…"),
            lambda: NewBranchFromCommit.invoke(invoker, target.oid)),
    ]


def openBranchDropMenu(
        invoker: QWidget,
        repoModel: RepoModel,
        source: str,
        target: BranchDropTarget,
        globalPos: QPoint,
) -> QMenu:
    """Ask what the drop means, under the pointer that made it."""
    actions = branchDropActions(invoker, repoModel, source, target)
    menu = ActionDef.makeQMenu(invoker, actions)
    menu.setObjectName("BranchDropMenu")
    menu.setToolTipsVisible(True)  # so a disabled operation can say why
    menu.aboutToHide.connect(menu.deleteLater)
    menu.popup(globalPos)
    return menu


def _dropAction(taskClass, whyNot: str, caption: str, callback) -> ActionDef:
    """One operation in the drop menu, named and iconed as the task book has it."""
    return ActionDef(
        caption,
        callback=callback,
        icon=TaskBook.icons.get(taskClass, ""),
        tip=whyNot or TaskBook.tips.get(taskClass, ""),
        enabled=not whyNot,
        objectName=taskClass.__name__)
