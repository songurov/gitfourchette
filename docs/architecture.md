# Architecture

This document describes how GitFourchette is put together as it stands today, for a contributor
who has just cloned the tree and needs a map before touching anything. It is descriptive only:
it records what the code does, not what anyone would like it to do. Proposals live in
[roadmap](roadmap.md) — its [Out of scope for now](roadmap.md#out-of-scope-for-now) section names
what is deliberately unplanned — and ideas that were examined and turned down are recorded with
their evidence in [rejected decisions](decisions-rejected.md).

Every file:line reference below was re-checked against the working tree while writing this;
where a number appears, the command that produced it is given.

## Shape of the tree

| What | Measured | Command |
| --- | --- | --- |
| Application code | 238 files, 60,055 lines | `find gitfourchette -name "*.py" -not -path "*__pycache__*"`, piped to `wc -l` for the file count and to `-exec cat {} + \| wc -l` for the lines |
| Tests | 70 files, 32,274 lines, 1,122 test functions | same, over `test/`; functions via `grep -rE "^def test" test/ \| wc -l` |
| Version | `APP_VERSION = "1.11.0"` | `gitfourchette/appconsts.py:16` |
| Runtime floor | Python >= 3.12, pygit2 >= 1.14.1, Pygments >= 2.12 | `pyproject.toml:19-23` |
| Qt | PyQt6 preferred, PySide6 and PyQt5 also wired | `gitfourchette/qt.py:88-106` |
| Licence | GPL-3.0; 269 tracked files carry the upstream author's header | `git grep -l "Copyright (C).*Iliyas Jorio"` piped to `wc -l` |

`gitfourchette/qt.py` is a single import shim that re-exports one of three bindings, so no other
module names a binding directly. Application code imports `from gitfourchette.qt import *`.

## Hybrid Git access

GitFourchette does not have one Git backend. It has three, and which one is used depends on the
operation rather than on the module.

**1. The `git` binary, launched as a `QProcess`.** This carries the porcelain: staging, commit,
checkout, merge, cherry-pick, revert, clean, restore, stash, fetch, push, submodule
update, tag creation and deletion, worktree commands, blame, and every diff the user actually
reads. (Rebase is not in that list: nothing in the tree ever runs `git rebase`. The code only
recognises a rebase already in progress and refuses to act — `tasks/gitflowtasks.py:62-64`.) The entry
point is `RepoTask.flowCallGit` (`gitfourchette/tasks/repotask.py:514`), which builds a `GitDriver`
— a `QProcess` subclass — through `createGitProcess` (`:526`) and then waits on it without blocking
the UI thread.

There are 89 call sites, spread over 15 task modules
(`grep -rn "flowCallGit" gitfourchette/ | grep -v "def flowCallGit" | wc -l`). The heaviest are
`tasks/indextasks.py` (19), `tasks/committasks.py` (9) and `tasks/nettasks.py` (8).

`createGitProcess` is where the process environment is assembled: `LC_ALL=C.UTF-8` to force English
output for parsing, the askpass helper, the internal ssh-agent, a per-repository custom SSH key
folded into `GIT_SSH_COMMAND`, and a Flatpak `TMPDIR` fix-up.

**2. libgit2, through pygit2.** This carries the reads that feed the model: the commit walk that
builds the graph (`repomodel.py:496`, `self.repo.walk(None, sorting)`), the ref table, remotes,
upstreams, stashes, submodules, object lookups and the index. A residue of small writes is still
done this way rather than through the CLI — branches via `create_branch_from_commit`
(`porcelain.py:1151`), `rename_local_branch` (`:1123`) and `delete_local_branch` (`:1131`);
config via `set_remote_skipfetchall` (`:1227`); repository state via pygit2's inherited
`state_cleanup` (called at `porcelain.py:1299`, `tasks/committasks.py:596`, `:658`) — so
"writes go through the CLI" is a tendency, not an invariant.

**3. Direct reads of Git's on-disk layout.** Where libgit2 exposes less than the UI needs, the code
reads `$GIT_COMMON_DIR` itself. `Repo.listall_worktrees` (`porcelain.py:950`) says so plainly:

> The metadata is read straight from `$GIT_COMMON_DIR/worktrees` rather than through pygit2's
> worktree API, which exposes neither the ref checked out in a worktree nor its lock state.

### Why the scanner uses subprocesses

The repository scanner that fills the Home screen is the clearest statement of the trade-off in the
codebase. `inspectRepo` (`gitfourchette/reposcan.py:156`) explains, at `:163-167`:

> This asks a git process rather than libgit2. pygit2 holds Python's global lock for the whole of a
> status call - seconds, on a big checkout - and the UI thread can't run a line of Python until it
> lets go, so the whole window froze while Home was scanning. A child process holds no lock of ours,
> can be stopped halfway through (`isCancelled`), and is quicker besides.

Three properties fall out of that, and they are the reason the CLI won the porcelain generally:
a child process does not hold the GIL, it can be killed mid-flight, and it is quicker besides.
`inspectRepo` accordingly shells out to
`git -c core.fsmonitor=false --no-optional-locks status --porcelain=v2 --branch -z --untracked-files=normal`
(`reposcan.py:173-184`) — with two comments in the argument list explaining that `core.fsmonitor`
is disabled so a scan never leaves a file-watching daemon behind per repository, and that
`--no-optional-locks` keeps the scan from writing to someone's index behind their back.

The walk itself is in `findRepos` (`reposcan.py:34`), which prunes on a fixed skip list
(`SKIP_DIRS`, `:26`) and stops descending as soon as it finds a repo.

## The task model

Everything that changes a repository is a `RepoTask` (`tasks/repotask.py:199`). There are 83
direct subclasses under `gitfourchette/tasks/`
(`grep -rn "^class .*(RepoTask)" gitfourchette/tasks/*.py | wc -l`).

A task's body is `flow()` (`:317`), a generator. It yields `FlowControlToken` objects (`:120`)
to move itself between threads and to wait for things. The helpers it yields from are the API a
contributor actually writes against:

| Helper | Anchor | Effect |
| --- | --- | --- |
| `flowEnterWorkerThread` / `flowEnterUiThread` | `:371` / `:382` | switch threads mid-coroutine |
| `flowSubtask` | `:393` | run another task's flow inline, sharing the task stack |
| `flowStartProcess` | `:486` | await a `QProcess`, with stdin and auto-fail handling |
| `flowCallGit` | `:514` | the above, for a `git` invocation |
| `flowDialog` / `flowConfirm` / `flowFileDialog` | `:600` / `:652` / `:643` | await the user |

The flow always begins on the UI thread. Work moved off it runs in a single `FlowWorkerThread`
(`:148`), a `QThread` that advances the generator once and emits the resulting token back.

Two declarative hooks surround the body. `TaskPrereqs` (`:81`) is an `IntFlag` — `NoUnborn`,
`NoDetached`, `NoConflicts`, `NoCherrypick`, `NoStagedChanges` — checked by `checkPrereqs` (`:746`)
before the flow starts, so a task states its preconditions instead of re-testing them. `TaskEffects`
(`:90`) is the mirror image: `Workdir`, `Refs`, `Remotes`, `Head`, `Upstreams`, accumulated into
`TaskEpilog.effects` (`:182`) as the task runs. `RepoWidget` drains them when the runner goes idle
and invokes `RefreshRepo` with exactly the flags that were raised (`repowidget.py:683-685`), so a
task never refreshes the UI itself.

`RepoTaskRunner` (`:775`) owns the schedule. It is not mono-task and not a general queue: it holds
`_currentTask` (`:804`) and `_pendingTask` (`:807`, documented as "Task that is queued to run after
`_currentTask`") — a queue of one. A new task either starts immediately, kills the running one when
`canKill` or `isFreelyInterruptible` allows it, or takes the single pending slot, displacing whatever
was there (`:913-927`, and the discard path at `:1173-1179`).

Destructive workdir operations back up what they are about to destroy into a `Trash`
(`gitfourchette/trash.py:22`), a directory under the app cache. It offers `backupFile` (`:127`),
`backupPatch` (`:144`) and `backupTree` (`:149`), a `size` (`:176`) and a `clear` (`:190`), gated on
`Trash.enabled()` (`:57`) and raising `Trash.BackupSkipped` (`:32`) when a file is too big or
unreadable. Note what is not there: there is no restore method. Recovery means finding the file in
the trash directory by hand.

## Repository model

`gitfourchette/porcelain.py` is the seam between the application and libgit2. Its centre is one
line, `porcelain.py:843`:

```python
class Repo(_VanillaRepository):
```

`_VanillaRepository` is `pygit2.Repository`, aliased at import (`porcelain.py:56`). `Repo` is a
subclass, not a wrapper: it inherits the whole pygit2 surface and adds 85 methods and properties of
its own over lines 843-2060, in a 2,082-line module. 63 modules import from it
(`grep -rl "porcelain import\|import porcelain" gitfourchette/ | wc -l`).

This matters for any future change of core. Because `Repo` *is* a `pygit2.Repository`, every caller
may use inherited pygit2 members without those uses appearing anywhere in `porcelain.py`, and the
`Oid`, `Commit`, `Tree`, `Blob`, `Branch` and enum types that pygit2 returns are re-exported from
`porcelain` (`:36-92`) and flow through the whole application. Replacing libgit2 is therefore not a
matter of rewriting one module; the inherited surface would have to be enumerated across all 63
importers first.

`RepoModel` (`gitfourchette/repomodel.py:152`) is the per-repository application state built on top
of `Repo`: the commit sequence, the graph, `refs` and `refsAt`, mergeheads, stashes, submodules,
worktrees, remotes, upstreams, ahead/behind counts, and the sets of foreign and unpushed commits.
It keeps its `Walker` alive between refreshes (`:155-157`) so a refresh does not restart from
scratch.

## The graph engine

`gitfourchette/graph/` is 1,907 lines across eight modules and has no Qt dependency; painting lives
in `graphview/`.

A `Graph` (`graph/graph.py:609`) is a linked list of `Arc`s (`:252`) — each arc spans two commits in
a lane — plus junctions (`:235`), chain handles (`:173`), and a list of keyframes. `GraphWeaver`
(`graph/graphweaver.py:16`) is the incremental builder: `newCommit(oid, parents)` resolves the arcs
that earlier children left open, assigns a lane, and opens arcs for the parents.

Two problems shape the design.

**Row numbers must survive a refresh.** New commits appear at the top and push everything down.
`BatchRow` (`graph/graph.py:44`) stores a row as a batch number plus an offset within that batch, so
a refresh adjusts one integer per batch instead of renumbering tens of thousands of rows. Batch
offsets live in a process-wide `BatchRow.BatchManager` (`:65`) shared by every repository open in the
application; a `Graph` releases its own batches in `freeOwnBatches` (`:643`).

**Random access must not mean replaying from the top.** Every `KF_INTERVAL = 5000` commits
(`graph/graph.py:30`) the builder seals a `Frame` (`:356`) as a keyframe. Asking for row *n* finds
the nearest keyframe at or before it (`getBestKeyframeID`, `:684`), copies it into a `PlaybackState`
(`:541`) and replays forward from there.

**Refresh is a splice, not a rebuild.** `GraphSplicer` (`graph/graphsplicer.py:29`) weaves the new
top of history while replaying the old graph, looking for an equilibrium — the row where old and new
agree again. Past that point the old arcs are reused with a row offset. It is driven by
`GraphSpliceLoop` (`graph/graphbuilder.py:173`), used from `RepoModel.syncTopOfGraph`
(`repomodel.py:556`); the cold path uses `GraphBuildLoop` (`graph/graphbuilder.py:96`) from
`PrimeRepo` (`tasks/loadtasks.py:164`). `GraphTrickle` (`graph/graphtrickle.py:16`) rides along the
same walk to propagate the hidden/foreign/local flags down through parents.

## UI layers

`RepoWidget` (`gitfourchette/repowidget.py:42`) is one open repository: it owns the `RepoModel`, the
`RepoTaskRunner`, a `NavLocator` and a `NavHistory` (`gitfourchette/nav.py:91`, `:336`). Its layout
is two nested splitters (`:118-163`): a horizontal one separating the sidebar from everything else,
and a vertical one splitting the commit log from the diff area.

- **Sidebar** (`sidebar/sidebar.py:38`, a `QTreeView`) — refs, worktrees, remotes, tags, stashes and
  submodules. Its rows come from a flat enum, `SidebarItem` (`sidebar/sidebarmodel.py:39`), with the
  section order declared as data in `SidebarLayout` (`:62`).
- **GraphView** (`graphview/graphview.py:28`, a `QListView`) over `CommitLogModel`
  (`graphview/commitlogmodel.py:50`). The lanes are drawn by `graphview/graphpaint.py`, which reads
  the `Frame` for a row and paints arcs at `LANE_WIDTH = 10` and `LANE_THICKNESS = 2` (`:19-20`).
- **DiffArea** (`gitfourchette/diffarea.py:56`) — two tabs, `CommitTab` and `ChangesTab` (`:57-58`).
  The commit tab pairs a detail view with `commitPatchView` (`:133`); the changes tab holds the
  staged/unstaged file lists from `filelists/`.
- **CodeView** (`codeview/codeview.py:29`) is the shared `QPlainTextEdit` base for text panes.
  `DiffView` (`diffview/diffview.py:38`) and `BlameTextEdit` (`blameview/blametextedit.py:17`) both
  derive from it, so gutters, search and selection behave the same in a diff and in a blame.
  Syntax colouring is Pygments, run in chunks by `LexJob` (`syntax/lexjob.py:24`).
- **mergeview/** — `MergeEditor` and `MergeInspector` (`mergeview/mergeeditor.py:48`,
  `mergeview/mergeinspector.py:19`) sit on top of `conflictparser.py`, which is deliberately Qt-free
  (`:7-10`) and turns a conflicted file into `MergeRegion`s. Conflict markers are fixed at
  `MARKER_SIZE = 7` (`:17`).

## Known limits

**Repository formats libgit2 1.9.7 cannot open.** Measured on this machine with pygit2 1.20.1 /
libgit2 1.9.7, by calling `pygit2.Repository(path)` on prepared repositories and then touching
`repo.index`:

| Format | Result |
| --- | --- |
| reftable (`extensions.refstorage`) | open fails: `unsupported extension name extensions.refstorage` |
| SHA-256 | open fails: `unknown object format 'sha256'` |
| any config carrying `extensions.partialClone` | open fails: `unsupported extension name extensions.partialclone` |
| sparse index | opens; first `repo.index` access fails: `unsupported mandatory extension: 'sdir'` |
| partial clone as git 2.54 writes it (`remote.<name>.promisor`) | opens, index reads; a blob left behind the promisor raises `KeyError` on lookup |

The first three are refused before a `Repo` object exists, so such a repository cannot be loaded at
all. The last two fail later instead, which is worse to reason about: the repository appears to
load and breaks on first use. The two partial-clone rows are not a contradiction — they are two
different configs. Current git records a partial clone as `remote.<name>.promisor` and does **not**
write `extensions.partialClone`, so a partial clone made today opens; only a config that carries
that extension key is refused. Both were reproduced here: `git clone --filter=blob:none` against a
source with `uploadpack.allowfilter=true` opened under pygit2 and read its index, while looking up a
blob that `git rev-list --objects --all --missing=print` reports as missing raised `KeyError`.

**The minimum Git version is not declared anywhere.** `pyproject.toml` pins Python, pygit2 and
Pygments (`:19-23`) and says nothing about `git`; nothing in the tree checks a floor at startup.
What exists instead are three feature gates, and they only guard the upper end:

| Gate | Anchor | Test |
| --- | --- | --- |
| `fetch --porcelain` | `gitdriver/gitdriver.py:146-150` | `gitVersionTuple() >= (2, 41)` |
| `--` before positional-only args | `gitdriver/gitdriver.py:153-163` | `gitVersionTuple() >= (2, 39)` |
| CRLF warning wording | `diffview/specialdiff.py:148` | `gitVersionTuple() < (2, 37)` |

The comments around those gates name the distribution versions the author had in mind: Ubuntu 22.04
(git 2.34.1), Debian 12 and macOS 15 (git 2.39.5). Below 2.37 nothing is gated at all, and the
effective floor is then set by the oldest construct used unconditionally — `-c core.abbrev=no`,
invoked without any version check at `gitdriver/gitdriver.py:324`, `:361`, `:413`,
`tasks/committasks.py:222` and `tasks/misctasks.py:465`. The `no` value for `core.abbrev` is
reported to have arrived in Git 2.31; that date could not be re-verified here, because the git on
this machine is 2.54.0. What *is* verified is that the floor is undeclared, unchecked and untested.

**`RepoTaskRunner` queues one task.** Starting a third task while two are outstanding silently
discards the pending one (`tasks/repotask.py:1173-1179`). This is by design, but it means a task
must not assume it will run just because it was invoked.

**`Trash` has no restore path.** See above.

## Further reading

This file is descriptive. Everything forward-looking lives next to it:

- [vision](vision.md) — where the product is meant to go.
- [roadmap](roadmap.md) — planned work, with effort sizes; its last section names what is
  deliberately unplanned.
- [rejected decisions](decisions-rejected.md) — ideas examined and turned down, with the evidence.
- [git coverage](git-coverage.md) — which Git features are implemented, and how.
- [UX guidelines](ux-guidelines.md) — the visual and interaction rules.
- [ADR 0001](adr/0001-desktop-stack.md) — the desktop stack decision.
- [ADR 0002](adr/0002-worktree-control-center.md) — the worktree control center.
- [ADR 0003](adr/0003-agentic-mode.md) — agentic mode.
- [ADR 0004](adr/0004-fork-relationship.md) — the relationship with upstream.
