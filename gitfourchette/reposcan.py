# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Find the Git repos that live on this machine.

Walking a home directory is cheap only if you prune aggressively, so this
stops descending as soon as it finds a repo, skips hidden folders, and skips
the dependency and build directories that make a naive walk take minutes.
"""

import dataclasses
import os

from gitfourchette.porcelain import GitError, Repo
from gitfourchette.qt import *

DEFAULT_MAX_DEPTH = 6

SKIP_DIRS = frozenset([
    "node_modules", "bin", "obj", "build", "dist", "target", "vendor",
    "__pycache__", "venv", "Library", "Applications", "snap", "flatpak",
    "site-packages", "Trash", "AppData",
])
"""Folders that never hold a repo worth listing, but do hold thousands of files."""


def findRepos(roots: list[str], maxDepth: int = DEFAULT_MAX_DEPTH,
              isCancelled=lambda: False, onFound=None) -> list[str]:
    """
    Return the workdirs of every Git repo under `roots`, deepest-first pruned.

    A repo's own subfolders aren't searched: a submodule is reached through its
    superproject, and a nested clone inside a checkout is nobody's project.

    `onFound` is called with each repo as it turns up, so a caller can show
    them while the walk is still going rather than after it ends.
    """
    found: list[str] = []
    seen: set[str] = set()

    for root in roots:
        root = os.path.normpath(os.path.expanduser(root))
        if not os.path.isdir(root):
            continue
        _walk(root, 0, maxDepth, found, seen, isCancelled, onFound)

    found.sort(key=lambda p: (os.path.dirname(p).casefold(), os.path.basename(p).casefold()))
    return found


def _walk(directory: str, depth: int, maxDepth: int, found: list[str],
          seen: set[str], isCancelled, onFound=None) -> None:
    if depth > maxDepth or isCancelled():
        return

    real = os.path.realpath(directory)
    if real in seen:  # symlink loop, or two roots that overlap
        return
    seen.add(real)

    try:
        entries = list(os.scandir(directory))
    except OSError:
        return  # unreadable folder: not an error, just not ours

    if any(e.name == ".git" for e in entries):
        found.append(directory)
        if onFound is not None:
            onFound(directory)
        return  # don't descend into a repo

    for entry in entries:
        if isCancelled():
            return
        if not entry.is_dir(follow_symlinks=False):
            continue
        if entry.name.startswith(".") or entry.name in SKIP_DIRS:
            continue
        _walk(entry.path, depth + 1, maxDepth, found, seen, isCancelled, onFound)


@dataclasses.dataclass
class RepoInfo:
    """What a repo looks like from the outside, without opening it in a tab."""

    path: str
    branch: str = ""
    dirty: bool = False
    "There are changes in the worktree or the index."
    ahead: int = 0
    "Commits on the current branch that the remote hasn't got."
    noUpstream: bool = False
    "The current branch isn't tracking anything, so nothing has been pushed."
    unreadable: bool = False

    def asDict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def fromDict(d: dict) -> "RepoInfo":
        fields = {f.name for f in dataclasses.fields(RepoInfo)}
        return RepoInfo(**{k: v for k, v in d.items() if k in fields})

    @property
    def needsAttention(self) -> bool:
        return self.dirty or self.ahead > 0


def inspectRepo(path: str) -> RepoInfo:
    """
    Report what's outstanding in a repo: uncommitted work, unpushed commits.

    Never raises: a repo that can't be read is reported as unreadable rather
    than taking the whole scan down with it.
    """
    info = RepoInfo(path=path)
    try:
        repo = Repo(path)
    except (GitError, OSError, ValueError):
        info.unreadable = True
        return info

    try:
        info.dirty = bool(repo.status(untracked_files="normal", ignored=False))

        if repo.head_is_unborn:
            info.noUpstream = True
            return info

        info.branch = repo.head_branch_shorthand if not repo.head_is_detached else ""
        if info.branch:
            branch = repo.branches.local[info.branch]
            upstream = branch.upstream
            if upstream is None:
                info.noUpstream = True
            else:
                info.ahead, _behind = repo.ahead_behind(branch.target, upstream.target)
    except (GitError, OSError, KeyError, ValueError):
        info.unreadable = True
    finally:
        repo.free()

    return info


class RepoScanner(QThread):
    """
    Finds the repos, then reports what each one has outstanding.

    Reports as it goes rather than at the end: on a big home folder the walk
    can take a while, and a list that stays empty until it finishes looks
    broken. Paths show up first because finding them is cheap; what each repo
    has outstanding costs a repo open apiece, so it fills in afterwards.
    """

    progress = Signal(list)
    "Everything known so far, emitted repeatedly while the scan runs."

    resultsReady = Signal(list)
    "The complete, inspected list. Emitted once, unless cancelled."

    BatchSize = 8

    def __init__(self, roots: list[str], maxDepth: int, parent=None):
        super().__init__(parent)
        self.roots = roots
        self.maxDepth = maxDepth
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        infos: list[RepoInfo] = []

        def onFound(path: str):
            infos.append(RepoInfo(path=path))
            if len(infos) % RepoScanner.BatchSize == 0:
                self.progress.emit(list(infos))

        findRepos(self.roots, self.maxDepth, lambda: self._cancelled, onFound)
        if self._cancelled:
            return
        self.progress.emit(list(infos))

        for i, info in enumerate(infos):
            if self._cancelled:
                return
            infos[i] = inspectRepo(info.path)
            if (i + 1) % RepoScanner.BatchSize == 0:
                self.progress.emit(list(infos))

        if not self._cancelled:
            self.resultsReady.emit(infos)


def defaultScanRoots() -> list[str]:
    """
    Where to look when the user hasn't said otherwise: the whole home folder.

    Guessing at ~/Documents, ~/Projects and friends misses repos kept anywhere
    else, and people keep them anywhere. The pruning above makes the full walk
    cheap enough that there's no reason to guess.
    """
    return [os.path.expanduser("~")]
