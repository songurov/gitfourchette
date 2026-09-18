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
import datetime
import os
from collections import Counter, defaultdict

from gitfourchette.localization import *
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
    changedFiles: int = 0
    "Number of paths changed in the worktree or index."
    ahead: int = 0
    "Commits on the current branch that the remote hasn't got."
    behind: int = 0
    "Commits the remote has that we haven't. Only as fresh as the last fetch."
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
        return self.dirty or self.ahead > 0 or self.behind > 0


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
        status = repo.status(untracked_files="normal", ignored=False)
        info.changedFiles = len(status)
        info.dirty = bool(status)

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
                info.ahead, info.behind = repo.ahead_behind(branch.target, upstream.target)
    except (GitError, OSError, KeyError, ValueError):
        info.unreadable = True
    finally:
        repo.free()

    return info


@dataclasses.dataclass
class RepoDetails:
    """Information used by the selected-repository header and Statistics tab."""

    path: str
    sizeBytes: int = 0
    commitCount: int = 0
    initialCommitTime: int = 0
    lastCommitTime: int = 0
    remotes: list[str] = dataclasses.field(default_factory=list)
    localBranches: int = 0
    tags: int = 0
    months: list[str] = dataclasses.field(default_factory=list)
    monthlyContributors: dict[str, dict[str, int]] = dataclasses.field(default_factory=dict)
    contributors: list[tuple[str, int]] = dataclasses.field(default_factory=list)


def inspectRepoDetails(path: str, monthLimit: int = 12) -> RepoDetails:
    """
    Read the heavier facts shown only after a repository is selected.

    Git does the history walk in its own optimized code. Keeping this out of
    the background scan makes Home cheap even when it knows hundreds of repos.
    """
    from gitfourchette.gitdriver import GitDriver

    details = RepoDetails(path)

    try:
        sizeText = GitDriver.runSync("count-objects", "-v", directory=path, strict=True)
        sizes = {}
        for line in sizeText.splitlines():
            key, separator, value = line.partition(": ")
            if separator and value.isdigit():
                sizes[key] = int(value)
        details.sizeBytes = 1024 * (sizes.get("size", 0) + sizes.get("size-pack", 0))

        details.remotes = GitDriver.runSync("remote", directory=path, strict=True).splitlines()
        refs = GitDriver.runSync(
            "for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags",
            directory=path, strict=True).splitlines()
        details.localBranches = sum(ref.startswith("refs/heads/") for ref in refs)
        details.tags = sum(ref.startswith("refs/tags/") for ref in refs)

        logText = GitDriver.runSync(
            "log", "--format=%at%x09%aN%x09%aE", "HEAD", directory=path, strict=True)
    except (ChildProcessError, OSError, ValueError):
        return details

    commits = []
    contributorCounts: Counter[str] = Counter()
    byMonth: dict[str, Counter[str]] = defaultdict(Counter)
    for line in logText.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        timestampText, name, email = fields
        try:
            timestamp = int(timestampText)
        except ValueError:
            continue
        contributor = name.strip() or email.strip() or _("Unknown")
        month = datetime.datetime.fromtimestamp(timestamp, datetime.UTC).strftime("%Y-%m")
        commits.append(timestamp)
        contributorCounts[contributor] += 1
        byMonth[month][contributor] += 1

    details.commitCount = len(commits)
    if commits:
        details.initialCommitTime = min(commits)
        details.lastCommitTime = max(commits)

    allMonths = sorted(byMonth)
    details.months = allMonths[-monthLimit:]
    details.monthlyContributors = {
        month: dict(byMonth[month]) for month in details.months
    }
    details.contributors = contributorCounts.most_common()
    return details


FETCH_TIMEOUT_MSEC = 60_000
"""A repo that can't be reached in a minute shouldn't hold up the other thirteen."""


def fetchRepo(path: str) -> bool:
    """
    Bring a repo's remote-tracking branches up to date, without asking anything.

    This runs unattended over every repo on the machine, so it must never stop
    to ask for a passphrase or a password: one that would ask is skipped (and
    reported as not fetched) rather than left hanging with nobody watching.
    """
    from gitfourchette.gitdriver import GitDriver

    try:
        GitDriver.runSync(
            # Keep credential prompts of every kind out of an unattended run
            "-c", "core.askPass=", "-c", "credential.helper=",
            "fetch", "--all", "--prune", "--quiet",
            directory=path, strict=True, timeoutMsec=FETCH_TIMEOUT_MSEC,
            env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "",
                 "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"})
    except (ChildProcessError, OSError):
        return False
    return True


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

    activity = Signal(str)
    "What the scan is busy with, for the status line. Empty when it's just walking."

    resultsReady = Signal(list)
    "The complete, inspected list. Emitted once, unless cancelled."

    BatchSize = 8

    def __init__(self, roots: list[str], maxDepth: int, fetch: bool = False, parent=None):
        super().__init__(parent)
        self.roots = roots
        self.maxDepth = maxDepth
        self.fetch = fetch
        self.fetchFailures: list[str] = []
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

        if self.fetch:
            self._fetchAll(infos)
            if self._cancelled:
                return

        for i, info in enumerate(infos):
            if self._cancelled:
                return
            infos[i] = inspectRepo(info.path)
            if (i + 1) % RepoScanner.BatchSize == 0:
                self.progress.emit(list(infos))

        if not self._cancelled:
            self.activity.emit("")
            self.resultsReady.emit(infos)

    def _fetchAll(self, infos: list[RepoInfo]):
        """Ask every remote what it has, so 'behind' means something."""
        for i, info in enumerate(infos):
            if self._cancelled:
                return
            self.activity.emit(_("Fetching {0} ({1} of {2})…", os.path.basename(info.path),
                                 i + 1, len(infos)))
            if not fetchRepo(info.path):
                self.fetchFailures.append(info.path)


def defaultScanRoots() -> list[str]:
    """
    Where to look when the user hasn't said otherwise: the whole home folder.

    Guessing at ~/Documents, ~/Projects and friends misses repos kept anywhere
    else, and people keep them anywhere. The pruning above makes the full walk
    cheap enough that there's no reason to guess.
    """
    return [os.path.expanduser("~")]
