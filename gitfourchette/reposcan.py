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
from collections.abc import Callable

from gitfourchette.localization import *
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

    Repos are reported by their real path, symlinks resolved, however the root
    that led to them was spelled. That is the name libgit2 gives a workdir, so
    it's the name the recent list, the tabs and the nicknames already use: a
    root reached through a symlink (a linked folder, or /var and /tmp on macOS)
    must not list a repo twice under two names. Symlinks *inside* a root are
    still never followed.

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
        found.append(real)
        if onFound is not None:
            onFound(real)
        return  # don't descend into a repo

    for entry in entries:
        if isCancelled():
            return
        if not entry.is_dir(follow_symlinks=False):
            continue
        if entry.name.startswith(".") or entry.name in SKIP_DIRS:
            continue
        _walk(entry.path, depth + 1, maxDepth, found, seen, isCancelled, onFound)


README_NAMES = ("README.md", "README.markdown", "README.rst", "README.txt", "README")


def findReadme(repoPath: str) -> str:
    """
    Path of this repo’s README, whatever it chose to call it.

    This lists the repo's folder, which can take any amount of time: behind a
    macOS privacy prompt, on a network volume, on a disk that has to spin up.
    So the UI thread must never call this for a whole list of repos. The
    scanner does it on its own thread and reports it as RepoInfo.hasReadme.
    """
    try:
        entries = {e.name.casefold(): e for e in os.scandir(repoPath) if e.is_file()}
    except OSError:
        return ""
    for name in README_NAMES:
        entry = entries.get(name.casefold())
        if entry is not None:
            return entry.path
    return ""


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
    hasReadme: bool | None = None
    """
    Whether the workdir has a README, as the scanner found it. None when
    nothing has looked, as in a cache written before the scanner did: that
    must not count as having none.
    """

    def asDict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def fromDict(d: dict) -> "RepoInfo":
        fields = {f.name for f in dataclasses.fields(RepoInfo)}
        return RepoInfo(**{k: v for k, v in d.items() if k in fields})

    @property
    def needsAttention(self) -> bool:
        return self.dirty or self.ahead > 0 or self.behind > 0


def inspectRepo(path: str, isCancelled: Callable[[], bool] | None = None) -> RepoInfo:
    """
    Report what's outstanding in a repo: uncommitted work, unpushed commits.

    Never raises: a repo that can't be read is reported as unreadable rather
    than taking the whole scan down with it.

    This asks a git process rather than libgit2. pygit2 holds Python's global
    lock for the whole of a status call - seconds, on a big checkout - and the
    UI thread can't run a line of Python until it lets go, so the whole window
    froze while Home was scanning. A child process holds no lock of ours, can
    be stopped halfway through (`isCancelled`), and is quicker besides.
    """
    from gitfourchette.gitdriver import GitDriver

    info = RepoInfo(path=path)
    try:
        stdout = GitDriver.runSync(
            # A repo set up with core.fsmonitor=true (Scalar does it, so do
            # some monorepo setups) would have 'git status' start a file-watching
            # daemon that stays up for good: one per repo on the machine.
            # (Before git 2.36 the value names a hook: 'false' then runs and
            # fails, which git takes as "no idea what changed". Same result.)
            "-c", "core.fsmonitor=false",
            # Never write to the index behind the owner's back, as a plain
            # 'git status' would to refresh it
            "--no-optional-locks",
            "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=normal",
            directory=path, strict=True, isCancelled=isCancelled)
        _readStatus(info, stdout)
    except (ChildProcessError, OSError, ValueError):
        info = RepoInfo(path=path, unreadable=True)

    return info


def _readStatus(info: RepoInfo, stdout: str):
    """Fill in `info` from the output of 'git status --porcelain=v2 --branch -z'."""
    unborn = False
    detached = False
    comparedWithUpstream = False

    records = iter(stdout.split("\0"))
    for record in records:
        if not record:
            continue

        if record.startswith("# "):
            key, _sep, value = record[2:].partition(" ")
            if key == "branch.oid":
                unborn = value == "(initial)"
            elif key == "branch.head":
                detached = value == "(detached)"
                info.branch = "" if detached else value
            elif key == "branch.ab":
                # Missing when there's no upstream, or when it's gone from the remote
                ahead, behind = value.split()
                info.ahead, info.behind = int(ahead), -int(behind)
                comparedWithUpstream = True
            continue

        info.changedFiles += 1
        if record.startswith("2 "):
            next(records, None)  # a rename's original path comes as a record of its own

    info.dirty = info.changedFiles > 0
    if unborn:
        info.branch = ""
        info.noUpstream = True
    elif not detached:
        info.noUpstream = not comparedWithUpstream


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


def fetchRepo(path: str, isCancelled: Callable[[], bool] | None = None) -> bool:
    """
    Bring a repo's remote-tracking branches up to date, without asking anything.

    This runs unattended over every repo on the machine, so it must never stop
    to ask for a passphrase or a password: one that would ask is skipped (and
    reported as not fetched) rather than left hanging with nobody watching.

    `isCancelled` stops the fetch halfway, except on Windows (see below).
    """
    from gitfourchette.gitdriver import GitDriver

    if WINDOWS:
        # A fetch writes refs under lock files. Elsewhere, git is stopped with
        # SIGTERM and deletes them on its way out; on Windows it is killed
        # outright, and a lock file left behind makes every later fetch of
        # this repo fail until someone deletes it by hand. So there, a
        # cancelled scan waits for the fetch in flight to finish instead.
        isCancelled = None

    try:
        GitDriver.runSync(
            # Keep credential prompts of every kind out of an unattended run
            "-c", "core.askPass=", "-c", "credential.helper=",
            "fetch", "--all", "--prune", "--quiet",
            directory=path, strict=True, timeoutMsec=FETCH_TIMEOUT_MSEC, isCancelled=isCancelled,
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
    has outstanding costs a 'git status' apiece, so it fills in afterwards.

    Whether a repo has a README is looked up here too, as soon as the repo is
    found, so that Home never lists a repo's folder on the UI thread. Home also
    lists the `recentPaths`, wherever they are; those the walk doesn't reach
    (outside the roots, in a hidden folder) are reported with their README and
    nothing else, as before: they are neither fetched nor inspected.
    """

    progress = Signal(list)
    "Everything known so far, emitted repeatedly while the scan runs."

    activity = Signal(str)
    "What the scan is busy with, for the status line. Empty when it's just walking."

    resultsReady = Signal(list)
    "The complete list, with every repo the walk found inspected. Emitted once, unless cancelled."

    BatchSize = 8

    def __init__(self, roots: list[str], maxDepth: int, fetch: bool = False, parent=None,
                 recentPaths: list[str] | None = None):
        super().__init__(parent)
        self.roots = roots
        self.maxDepth = maxDepth
        self.fetch = fetch
        self.recentPaths = list(recentPaths or [])
        self.fetchFailures: list[str] = []
        self._cancelled = False

    def cancel(self):
        """
        Ask the scan to stop. It does so within a fraction of a second, even
        in the middle of a repo, so waiting for the thread afterwards is cheap.
        (Except for a fetch on Windows, which runs to its end: see fetchRepo.)
        """
        self._cancelled = True

    def isCancelled(self) -> bool:
        return self._cancelled

    def run(self):
        infos: list[RepoInfo] = []
        found: set[str] = set()

        # Looked up first, so the recent repos the walk hasn't reached yet (or
        # never will) have their README known from the very first batch
        recent: list[RepoInfo] = []
        for path in self.recentPaths:
            if self._cancelled:
                return
            recent.append(RepoInfo(path=path, hasReadme=bool(findReadme(path))))

        def everything() -> list[RepoInfo]:
            return infos + [info for info in recent if info.path not in found]

        def onFound(path: str):
            found.add(path)
            infos.append(RepoInfo(path=path, hasReadme=bool(findReadme(path))))
            if len(infos) % RepoScanner.BatchSize == 0:
                self.progress.emit(everything())

        findRepos(self.roots, self.maxDepth, lambda: self._cancelled, onFound)
        if self._cancelled:
            return
        self.progress.emit(everything())

        if self.fetch:
            self._fetchAll(infos)
            if self._cancelled:
                return

        for i, info in enumerate(infos):
            if self._cancelled:
                return
            inspected = inspectRepo(info.path, self.isCancelled)
            inspected.hasReadme = info.hasReadme  # 'git status' doesn't say
            infos[i] = inspected
            if (i + 1) % RepoScanner.BatchSize == 0:
                self.progress.emit(everything())

        if not self._cancelled:
            self.activity.emit("")
            self.resultsReady.emit(everything())

    def _fetchAll(self, infos: list[RepoInfo]):
        """Ask every remote what it has, so 'behind' means something."""
        for i, info in enumerate(infos):
            if self._cancelled:
                return
            self.activity.emit(_("Fetching {0} ({1} of {2})…", os.path.basename(info.path),
                                 i + 1, len(infos)))
            if not fetchRepo(info.path, self.isCancelled):
                self.fetchFailures.append(info.path)


def defaultScanRoots() -> list[str]:
    """
    Where to look when the user hasn't said otherwise: the whole home folder.

    Guessing at ~/Documents, ~/Projects and friends misses repos kept anywhere
    else, and people keep them anywhere. The pruning above makes the full walk
    cheap enough that there's no reason to guess.
    """
    return [os.path.expanduser("~")]
