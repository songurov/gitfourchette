# ADR 0002 — Worktree control center and conflict radar

An architecture decision record for contributors to this fork. It records how a simultaneous view
over N worktrees — status, file overlap, conflict prediction — should be built on the code that
exists today, and which parts of the idea were cut. Every code reference was re-checked against the
working tree at `6258f3e0`; where a number appears, so does the command that produced it.

## Status

Proposed. Scope is this fork's `feature/workspaces` line. `docs/` does not exist in
`upstream/master` (`git ls-tree -d --name-only upstream/master`), so this file cannot conflict on
rebase.

## Context

### What already exists

**Worktree lifecycle.** `gitfourchette/tasks/worktreetasks.py` (204 lines) defines `NewWorktree`
(:48), `RemoveWorktree` (:90), `LockWorktree` (:136), `UnlockWorktree` (:163) and `PruneWorktrees`
(:173). Between them they invoke exactly five git subcommands — `worktree add`, `remove`, `lock`,
`unlock`, `prune` (`grep -rn '"worktree", "' gitfourchette/`). `git worktree move`, `repair` and
`list` are never invoked. `test/test_tasks_worktree.py` holds 42 test functions
(`grep -c '^def test'`). Lifecycle is not the gap.

**Enumeration.** `Repo.listall_worktrees` (`porcelain.py:950`) calls pygit2's `list_worktrees()`
(`:979`), then reads `.git/worktrees/<name>/gitdir`, `HEAD` and `locked` as plain text.

**A status engine already exists, already off the UI thread.** `reposcan.inspectRepo`
(`reposcan.py:156`) reports uncommitted work and unpushed commits for one repository path by running
`git -c core.fsmonitor=false --no-optional-locks status --porcelain=v2 --branch -z
--untracked-files=normal` in a child process. Its docstring gives the reason: a pygit2 status call
holds Python's global lock for its whole duration, so the window froze while Home was scanning.
`RepoScanner` (`reposcan.py:347`) is a `QThread` that reports in batches and can be cancelled
mid-repo. A linked worktree is just another repository path, so this engine already answers most of
a worktree row.

**Conflicted state is already per-worktree.** Verified: a merge conflict started inside a linked
worktree yields `RepositoryState.MERGE` when `Repo(<linked workdir>)` is opened, and
`RepositoryState.NONE` for the main worktree of the same repository — libgit2 resolves the state
files against `.git/worktrees/<name>/`. The value is already consumed by `RepoWidget.refreshBanner`
(`repowidget.py:714`).

**Pairwise comparison plumbing exists.** `NavLocator.commitDiffAB()` (`nav.py:259`) already drives
A/B diff through `graphview.py:345-347` and `jumptasks.py:490`.

### What does not exist

- No conflict prediction: `grep -rn 'merge-tree\|merge_commits' gitfourchette/` returns zero hits.
- Ahead/behind is computed only against upstream. Both places that fill it run
  `git for-each-ref --format=%(refname:short) %(upstream:track) refs/heads`
  (`loadtasks.py:90-91`, `jumptasks.py:812-814`). Arbitrary worktree pairs have no source today.
- No push-based liveness: `grep -rn QFileSystemWatcher gitfourchette/` returns zero hits.
- No process introspection: `psutil` is an optional extra (`memory-indicator`,
  `pyproject.toml:54`), not a dependency.

## Decision

### 1. A dockable panel scoped to a workspace

It is **not** a third page in the main `QStackedWidget`. `mainwindow.py:90` creates `welcomeStack`,
and `:114-115` add exactly two widgets to it, the welcome screen and the tab bar; its pages are
mutually exclusive by construction, so a third page could never be on screen next to the open
repositories — which is the entire point of the feature.

It follows the `AnalysisDialog` pattern instead (`forms/analysisview.py:259`), which already has
the shape we need: `_startJob` (`:323`) creates one `QThread` per job, moves an `AnalysisWorker`
(`:105`) onto it, tags each result so stale ones can be dropped, and refuses to start threads once
`closing` is set; each collector opens its own `Repo(path)` on the worker thread (`:126`, `:191`,
`:223`) rather than sharing the UI thread's handle.

It does **not** run through `RepoTask`. `RepoTaskRunner` holds `_currentTask`
(`tasks/repotask.py:804`) plus `_pendingTask` (`:807`, documented there as "Task that is queued to
run after `_currentTask`") — a queue of depth one. Probing N worktrees through it would serialise
the probes and evict the user's own pending action.

### 2. Conflict radar is commit-level only, with a dual engine

The panel predicts whether merging worktree A's tip into worktree B's tip would conflict. It does
not attempt to predict conflicts over uncommitted work in the first version.

- **Primary engine:** `git merge-tree --write-tree <a> <b>`, gated on the git version.
- **Fallback:** `Repository.merge_commits(ours, theirs)` — a method on the repository object,
  not a module-level function — whose result must be **labelled approximate in the UI**.

Measured here on `master..feature/workspaces` (161 commits apart, 614 index entries), 10 runs each
timed with `time.perf_counter` around `subprocess.run` and around the pygit2 call:

```
git merge-tree --write-tree master feature/workspaces
  exit 0;  min 7.5 ms   median 7.8 ms   max 9.0 ms   (includes process spawn)

pygit2.Repository.merge_commits(master, feature/workspaces)
           min 18.7 ms  median 18.9 ms  max 22.3 ms
```

Both are fast enough to run on selection change behind a debounce and an `(oidA, oidB)` cache.
Neither touches an index or a working directory.

The fallback must be labelled because the engines disagree: libgit2's merge is not git's `ort`.
Reproduced in a scratch repository where branch `ren` renames `a/` to `b/` and branch `addfile`
adds `a/new.txt`: `git merge-tree --write-tree ren addfile` exits 1 with `CONFLICT (file location)`,
while `Repository.merge_commits` on the same pair returns an index whose `.conflicts` is `None`. A
radar that produces silent false negatives without saying so is worse than no radar.

Version gating is an existing pattern, not a new one: `supportsFetchPorcelain` requires 2.41
(`gitdriver/gitdriver.py:150`) and `supportsDashDashBeforePositionalArgs` requires 2.39 (`:163`),
both reading `GitDriver.gitVersionTuple()` (`:123`). No minimum git version is declared or checked
anywhere, and some newer switches are used ungated — `-c core.abbrev=no` at five call sites
(`gitdriver/gitdriver.py:324`, `:361`, `:413`, `tasks/committasks.py:222`,
`tasks/misctasks.py:465`). Declaring and testing a minimum belongs to the
[roadmap](../roadmap.md), not here.

### 3. Only four worktree states are displayed

| State          | Source                                                                |
|----------------|-----------------------------------------------------------------------|
| `conflicted`   | `repo.state() != RepositoryState.NONE`, per-worktree (verified above)  |
| `dirty`        | the `git status --porcelain=v2` already run by `inspectRepo`           |
| `review-ready` | clean working tree and ahead > 0 — a heuristic, labelled as one        |
| `idle`         | the default when none of the above holds                               |

`running tests` and `waiting` are **not** displayed. Neither has any source in Git. Detecting a
foreign test process would make `psutil` a hard dependency and infer intent from a process tree;
`waiting` is meaningless without an actor that reports it. Both are recorded in
[rejected decisions](../decisions-rejected.md) with that reasoning. The only honest route to them is
that the application starts the command itself and therefore owns the process.

### 4. Overlap detection is a path-set intersection

For each pair of worktrees, intersect the path sets of `diff(merge_base, tip)`, plus the paths
`git status` already reports for uncommitted work. A noise rule is required before this is shown on
a monorepo: a file every worktree touches carries no signal.

## Consequences

- The panel is read-mostly. Every mutation it offers routes back through `RepoTask`, so
  confirmation dialogs, `TaskEffects` invalidation and the test harness keep working unchanged.
- Rows are stale between refreshes. With no `QFileSystemWatcher` anywhere, "live status" means
  "refreshed on demand and on foreground", and the UI must not imply otherwise.
- One `Repo` per worktree is opened on a worker thread — a real cost at large N, which is why the
  budget below is stated in milliseconds.
- A dual engine means two behaviours in the field; the approximate label has to reach the result
  itself, not just a settings screen.
- Two tabs on two worktrees of one repository share `$GIT_COMMON_DIR/refs`, and a ref moved in one
  is never signalled to the other: a tab only catches up when it becomes current
  (`mainwindow.py:1122`) or when the window regains foreground with `autoRefresh` on (`:1306`),
  because `onTaskRunnerReady` holds back a refresh while the widget is not visible
  (`repowidget.py:680`). A panel showing N worktrees at once is exactly the case those two hooks
  don't cover, so cross-tab invalidation becomes part of this work rather than a follow-up.

**Acceptance budget:** N worktrees shown with correct status without blocking the UI thread beyond
100 ms; the radar predicts a real conflict on a test repository and does not reproduce the
directory-rename false negative when git is new enough; below that version the result is visibly
labelled approximate; no displayed state is one Git cannot confirm.

## Prerequisite: the relative worktree path bug

`listall_worktrees` computes a worktree's workdir as `_dirname(_normpath(dotgit))`
(`porcelain.py:989`), never joining it with the administrative directory it came from. When
`.git/worktrees/<name>/gitdir` holds a relative path — which is what `git worktree add
--relative-paths` writes — the result stays relative, and
`prunable=bool(name) and not _isdir(path)` (`porcelain.py:1024`) then resolves it against the
process's current directory.

Reproduced: a worktree created with `--relative-paths` comes back from `listall_worktrees` as
`path='../../../../wt'`, `prunable=True`, while `git worktree list --porcelain` reports it healthy
at its absolute path. Two consequences follow. `sidebarmodel.py:525-526` turns `prunable` into the
warning "Worktree folder is missing." on a healthy worktree. And the "already open in another tab"
guards at `worktreetasks.py:101` and `:185` compare `os.path.normpath(worktree.path)` against
`MainWindow.openWorkdirs()`, which returns normalised **absolute** workdirs
(`mainwindow.py:1314-1316`) — so on such a repository the guard can never match, and
`RemoveWorktree` loses its protection against deleting a worktree out from under an open tab.

`grep -rn 'relative-paths\|useRelativePaths' gitfourchette/ test/` returns zero hits: the case is
neither handled nor tested. Joining against the administrative directory before normalising, and
computing `prunable` on the absolute path, is a small change and a hard prerequisite — a control
center that flags healthy worktrees as missing is worse than the sidebar it replaces. Moving the
read onto `git worktree list --porcelain -z` would also supply the real prune and lock reasons.

## Open questions

- The monorepo noise rule for overlap: a ratio of worktrees touching a path, a depth heuristic, or
  a user-editable ignore list. Needs a real monorepo to calibrate against.
- The real value of N, which nobody has measured. The panel is sized for an unknown.
- Whether arbitrary-pair ahead/behind should use pygit2's `Repository.ahead_behind` (a method, not
  a module function; already called at `porcelain.py:1804`) or `git rev-list --left-right --count`.
  `jumptasks.py:808-809` records that `ahead_behind` is slower than `for-each-ref` in complex
  graphs — evidence for the CLI, but not for the pairwise case.

## Effort

Panel shell and worktree rows on the existing scan engine **M**; conflict radar MVP with both
engines, cache and debounce **M**; relative-path fix and its tests **S**; cross-tab ref
invalidation **M**; overlap detection with a calibrated noise rule **M**.

## Related

- [Product vision](../vision.md) — why parallel work is the pillar this serves.
- [ADR 0001](0001-desktop-stack.md) — why this is built on PyQt6 and pygit2.
- [Roadmap](../roadmap.md) — where this sits in sequence.
- [Rejected decisions](../decisions-rejected.md) — `running tests`, `waiting` and the third
  stacked page, with their reasons.
