# Roadmap

The staged plan of record for this fork of GitFourchette, for whoever picks up the next unit of
work. Each stage says what it is for, what it delivers, where the work lands in the code, and what
must be true before the next stage starts.

## How to read this

**The ordering rule.** Nothing in stage N+1 starts while anything in stage N blocks it. Stages are
dependency layers, not calendar quarters. Build the event stream of an agent session before the
assistant panel stops being a modal dialog, and the result is a rich panel in a frozen window.

**Sizes**, for one to two people, including tests and the translation budget (14 `.po` catalogues
under `gitfourchette/assets/lang/`): **S** up to about 3 days, **M** 1–2 weeks, **L** 3–6 weeks,
**XL** 2–4 months. No dates appear in this file, and none should be added.

**Sources.** `[strategy]` is the product strategy document, `[ux-audit]` the competitive UX review,
`[git-audit]` the Git coverage review.

**Anchors** point at the code a deliverable touches, not at a finished implementation. Paths are
relative to the repository root with `gitfourchette/` omitted; test paths keep their `test/` prefix.
Every anchor was re-checked against the working tree at `6258f3e0`; where an earlier report's anchor
did not match the code, it was corrected or the claim was dropped.

**What is not here.** Ideas that duplicate something already implemented, contradict the current
architecture, or failed adversarial review live in [decisions rejected](decisions-rejected.md),
with the reason and the evidence.

**Related.** [Vision](vision.md) sets the product rules, [architecture](architecture.md) describes
the client as it stands, [git coverage](git-coverage.md) inventories the Git surface, and
[UX guidelines](ux-guidelines.md) the interface rules. Standing decisions are in
[ADR 0001](adr/0001-desktop-stack.md), [0002](adr/0002-worktree-control-center.md),
[0003](adr/0003-agentic-mode.md) and [0004](adr/0004-fork-relationship.md).

## Baseline

Facts this plan rests on, each with the command that produced it.

- `find gitfourchette -name "*.py" -not -path "*__pycache__*" | wc -l` → 238 files; the same find
  piped through `cat | wc -l` → 60,055 lines. Over `test/` → 70 files, 32,274 lines. The test
  suite is the most expensive asset in the repository.
- The client is hybrid: reads go through libgit2 (`porcelain.py:843` is
  `class Repo(_VanillaRepository)`), writes through `git` as a child process
  (`grep -rn flowCallGit gitfourchette/ | wc -l` → 90).
- libgit2 1.9.7 cannot open some modern repository formats. Re-verified by creating throwaway
  repositories with `git init --ref-format=reftable` and `git init --object-format=sha256`, then
  calling `pygit2.Repository()` on each: the first raises
  `GitError: unsupported extension name extensions.refstorage`, the second
  `InvalidError: unknown object format 'sha256'`.
- Version handling is ad hoc. The oldest requirement is `-c core.abbrev=no`
  (`gitdriver/gitdriver.py:324`), the newest `fetch --porcelain`, gated at
  `gitdriver/gitdriver.py:150` with a source comment naming git 2.41. No minimum is declared.
- Fork posture: `master` equals `origin/master` equals `5a019e8e`; `git rev-list --count
  upstream/master..feature/workspaces` → 161; `git tag --contains master` is empty, so no tag
  covers this fork's work.

## Stage 1 — Truth, safety net, declared compatibility

**Objective:** the product stops describing itself inaccurately, stops losing work on any path,
and explains why a repository it cannot open is not opening.

| Deliverable | Source | Anchor | Size |
|---|---|---|---|
| Resolve a linked worktree's path against its administrative directory before normalising it, and compute `prunable` from the resolved path | [git-audit] [strategy] | `porcelain.py:989`, `:1024` | S |
| Read worktrees with `git worktree list --porcelain -z` instead of reconstructing the metadata by hand; the only subcommands used today are add, remove, lock, unlock, prune | [git-audit] | `porcelain.py:950-1024`, `tasks/worktreetasks.py:76-202` | M |
| `worktree move` and `worktree repair`, reusing the open-tab guard, surfaced on the sidebar warning that already exists for a missing worktree folder | [strategy] [ux-audit] | `tasks/worktreetasks.py:101`, `:185`; `sidebar/sidebarmodel.py:526`, `:892` | M |
| Trash becomes two-way: back up before `worktree remove --force` and before a conflict resolution is overwritten, drop "This cannot be undone!" where a copy is kept, and add restore. The class only writes today and nothing reads back | [ux-audit] [strategy] | `tasks/worktreetasks.py:111`, `:131`; `tasks/indextasks.py:450`; `trash.py:127`, `:144`, `:149` | M |
| Detect repository format before constructing `Repo()` and explain it inline through the stub's existing `disableAutoLoad(message=…)`; guard direct `repo.index` access for sparse-index; declare a minimum git version and print the real capability matrix in About | [git-audit] [strategy] | `tasks/loadtasks.py:75`, `:237`; `forms/repostub.py:96`; `tasks/indextasks.py:284-285`; `forms/aboutdialog.py:147-150` | M |
| Annotated tags: the working code already exists on the git-flow path | [git-audit] | `tasks/committasks.py:509` from `tasks/gitflowtasks.py:498` | S |
| Parser hardening: `parseGitDiffRawZ` checks its match for `None`, `conflict-marker-size` comes from `.gitattributes` instead of a constant, untested parsers get tests (only `parseGitStatus` is exercised), and path lists are chunked so a large selection cannot exceed `ARG_MAX` | [git-audit] | `gitdriver/parsers.py:201-202`; `mergeview/conflictparser.py:17`; `test/test_regexes.py:144`; `tasks/indextasks.py:77`, `:197` | S |
| Small honesty fixes: tooltips visible in menus built by `ActionDef.makeQMenu`, where ten other call sites already do this; no process dialog for read-only tasks, where the default broadcasts and all four overrides disable it; a confirmation before `closeAllTabs()` | [ux-audit] | `toolbox/actiondef.py:185-188`; `tasks/repotask.py:305-312` with `tasks/nettasks.py:194`, `:354`, `tasks/misctasks.py:419`, `tasks/blametasks.py:276`; `mainwindow.py:887` | S |
| A written decision on fork posture. The relative-path fix, move/repair and annotated tags carry no product opinion and are the natural upstream candidates | [strategy] | `master == origin/master == 5a019e8e` | S |

**Exit criteria.** A repository created with `git worktree add --relative-paths` opens, is not
reported prunable, and trips the open-in-another-tab guard. A reftable, SHA-256 or sparse-index
repository produces one inline explanation, not an error box on every switch. No path in the UI
destroys work more irreversibly than its terminal equivalent, checked on discard, `reset --hard`,
resolve and `worktree remove --force`. The README describes what the product does, and the suite
passes across all 60 `test_*.py` modules.

## Stage 2 — Context survives, the overview gets fast, recovery becomes visible

**Objective:** a reopened workspace shows where you were and what is happening in every repository,
and any operation that moves a ref can be undone.

| Deliverable | Source | Anchor | Size |
|---|---|---|---|
| `Session.tabs` becomes structured — path plus a coarse locator — reading the existing flat `list[str]` for compatibility, with URL parsing wrapped so a hand-edited `session.json` cannot break startup | [strategy] [ux-audit] | `settings.py:614`; `mainwindow.py:1618` | M |
| Per-repository layout: splitter sizes move out of the class variable shared by every `RepoWidget` into `RepoPrefs` | [strategy] [ux-audit] | `repowidget.py:43`; `repoprefs.py:42-47` | M |
| Unloaded tabs carry status from `inspectRepo` — branch, dirty, ahead, behind — turning a workspace switch from one informative tab and N blank ones into a real overview | [strategy] | `reposcan.py:156`; `mainwindow.py:1618` | M |
| Scan in parallel instead of the current serial loop; keep the previous `RepoInfo` while `scanning=True`; call `expandAll()` only on the first populate | [strategy] [ux-audit] | `reposcan.py:426-429`; `forms/welcomewidget.py:549`, `:616`, `:629` | M |
| Worktree-to-parent lineage in `History.JsonRepo`, so a linked worktree's `.git` file is not listed as an independent project; nested workspaces by `/` in the name, plus reordering | [strategy] | `reposcan.py:34`; `settings.py:399-408`, `:490` | M |
| Split `History` into device-local and portable parts. Workspace membership is normalised paths today — a boundary conversion, not a schema obstacle | [strategy] | `settings.py:493` | M |
| Cross-tab invalidation keyed on `$GIT_COMMON_DIR`: a task carrying `TaskEffects.Refs` marks every tab sharing a common directory stale | [strategy] | `tasks/repotask.py:90-115`; `mainwindow.py:1314` | M |
| Reflog-backed undo: an `UndoRecord` on the epilog of ref-moving tasks plus a recovered-work surface. `grep -rni reflog gitfourchette/` returns nothing, and the activity menu is read-only | [git-audit] [ux-audit] [strategy] | `mainwindow.py:759-767` | L |
| The in-progress banner becomes a cockpit: conflict counter plus Continue, Skip and Abort. Only abort is wired; `--continue` exists in the repository solely as help text | [ux-audit] [strategy] | `repowidget.py:740-768`; `tasks/indextasks.py:936-946`; `trtables.py:719` | M |
| Write the commit-graph in the background after clone and fetch; `grep -rn commit-graph gitfourchette/` returns nothing | [git-audit] | `reposcan.py` | S |
| Coalesce the assistant stream and cache rendered HTML per finished message; the transcript is re-rendered on every JSONL line today. A prerequisite for stage 4 | [ux-audit] | `forms/aichatdialog.py:987-999`; `forms/chattranscript.py:27` | S |

**Exit criteria.** Restarting the application and switching workspace reopens each repository at the
commit and file you left. A switched workspace shows status on every tab, not only the active one.
Scan duration is measured by a benchmark added to `test/`: all the timing in the suite today
measures cancellation latency (`test/test_home.py:700-702`, `:723-725`, `:850-852`), so the number
must be produced before it can be improved. Two tabs on two worktrees of one repository no longer
show contradictory refs. A `reset --hard` and a deleted branch can both be undone from the UI.

## Stage 3 — Worktree control centre, Conflict Radar MVP, basic rebase

**Objective:** the user sees every worktree at once, which ones overlap, and where a conflict is
forming, without opening any of them.

| Deliverable | Source | Anchor | Size |
|---|---|---|---|
| The control centre is a dockable panel scoped to the workspace, on the pattern that already runs work off the UI thread in its own `QThread` — not a third page in the central stack, which holds two | [strategy] | `forms/analysisview.py:259`, `:328`; `mainwindow.py:90-115` | L |
| One row per worktree: branch, HEAD, dirty, changed files, ahead/behind, aggregate diff statistics | [strategy] | `reposcan.py:156`; `sidebar/sidebardelegate.py:237-250` | M |
| Ahead/behind between arbitrary pairs of worktrees or branches; the only comparison today is against upstream | [strategy] | `porcelain.py:1804`; `tasks/loadtasks.py:89-92` | M |
| File-overlap detection, with a noise rule so a monorepo does not report the files everyone touches, and fast compare between two worktrees over the A-to-B plumbing that exists — a new entry point, not a new diff pipeline | [strategy] | `nav.py:259`; `tasks/jumptasks.py:490` | M |
| Conflict Radar MVP, strictly at commit level: `git merge-tree --write-tree` where the git version allows, otherwise `Repository.merge_commits` labelled in the UI as approximate. Cached per commit pair, debounced, off the UI thread | [strategy] | version gates at `gitdriver/gitdriver.py:150`, `:163`, `diffview/specialdiff.py:148` | L |
| Per-worktree status limited to what git can confirm: conflicted, review-ready, dirty, idle | [strategy] | `repowidget.py:714` | M |
| Stale and orphaned worktree detection with safe cleanup, using the real prunable reason rather than a directory existence check | [strategy] | `tasks/worktreetasks.py:173-202` | M |
| Basic rebase with `--continue`, `--abort` and `--skip`, driven by the stage-2 banner. `grep -rn 'class .*Rebase' gitfourchette/` returns nothing; the conflict UI already exists under `mergeview/` | [git-audit] [strategy] | `mergeview/` | L |
| Graph view: drag and drop (the sidebar already handles drops, the graph view has none), and lane colour keyed on the chain rather than on the lane index, which is freed and reused, so unrelated chains share a colour; `Frame.homeChain()` already exists | [ux-audit] | `sidebar/sidebar.py:995-1017`; `graphview/graphview.py:128`; `graphview/graphpaint.py:35-36`, `:135`; `graph/graphweaver.py:71`, `:112`; `graph/graph.py:433` | M |
| Map stderr to a diagnosis with suggested follow-up tasks, on the pattern already used for a rejected push | [ux-audit] | `tasks/nettasks.py:429-437` | M |

**Exit criteria.** The panel shows N worktrees with correct status without blocking the UI. The
radar predicts a real conflict on a test repository and, where the git version supports it, does not
miss a directory-rename conflict; below that version the result is visibly labelled approximate. A
simple rebase is carried through a conflict from the banner, with no terminal. No status shown is
one git cannot confirm. As a starting datum, `git merge-tree --write-tree master
feature/workspaces` here measured 0.01 s or less over five runs under `/usr/bin/time -p`:
the radar's cost is caching and debouncing, not the merge.

## Stage 4 — Agentic mode, phases 0 and 1

**Objective:** an agent session is a persistent object attached to a worktree: visible, stoppable,
non-blocking, unable to destroy work without a net.

| Deliverable | Source | Anchor | Size |
|---|---|---|---|
| The gate, and the first code written here: drop `WA_DeleteOnClose` and window modality, and mount the panel in the `RepoWidget` splitter — not as a third page in a stack that holds two, nor a third tab in a bar with two | [ux-audit] [strategy] | `forms/aichatdialog.py:238-239`; `diffarea.py:91-93`, `:99-101` | M |
| Drop `--ephemeral` and `--no-session-persistence`; adopt an application-generated session identifier | [strategy] | `exttools/aichat.py:70`, `:75` | S |
| A Task / Session / Agent domain model persisted per repository on the `RepoPrefs` pattern | [strategy] | `repoprefs.py:42-47` | M |
| A session manager beside the task runner, not inside it: the runner holds one running plus one pending task, a queue of depth one, and is the wrong home for a session lasting minutes. Wire it to the process infrastructure that exists and is duplicated ad hoc in the chat dialog | [strategy] | `tasks/repotask.py:804-808`; `toolbox/qprocessconnection.py`; `forms/statusform.py:74`; `forms/aichatdialog.py:950` | L |
| A typed event stream over the JSONL already on the wire — file changes, commands, checkpoints, tool calls, usage — and with it cost, tokens and runtime in the UI. The stream class reduces all of it to visible text today, by design | [strategy] | `exttools/aichat.py:113-114` | M |
| A debounced `QFileSystemWatcher` ignoring `.git` internals, plus system notifications when an agent needs input or a conflict appears. Both greps return nothing today, and without the watcher "stream changed files into the Git UI" is untrue | [strategy] | `grep QFileSystemWatcher`, `grep QSystemTrayIcon` → 0 | M |
| Checkpoints made by the application rather than the agent, on a private ref namespace, triggered by file-change events, plus a `Trash.backupTree()` snapshot before an agent starts with edit rights | [strategy] [ux-audit] | `trash.py:149`; `exttools/aichat.py:68-72` | M |
| Per-operation approval over a bidirectional channel; the current pattern writes the prompt then closes the write channel, so approvals cannot be answered | [strategy] | `forms/aichatdialog.py:963` | L |
| The third provider adapter written second, not last, so the session model does not mould itself to two CLIs | [strategy] | `exttools/aichat.py:60-86` | M |
| An assistant page in Preferences with a kill switch that hides the entry points; the privacy wording gains a second clause, since with edit rights the assistant writes as well as reads | [ux-audit] | `settings.py:388-396`; `exttools/aichat.py:68-72` | M |

**Exit criteria.** An agent runs for minutes without blocking any Git operation in any window or
tab. A session survives closing the panel and can be resumed. Every write by the agent appears in
the UI without a manual refresh, and every destructive operation it initiates passes an explicit
gate. Each session has an attributable checkpoint made by the application. The third provider works
without a new branch in the stream reducer.

## Stage 5 — MCP server, repository intelligence, stack decision gate

**Objective:** what was built internally becomes a controlled interface for external agents, and the
repository can explain its own health.

| Deliverable | Source | Anchor | Size |
|---|---|---|---|
| A local MCP server, read-only in its first version: repositories, branches, worktrees, status, diffs, logs, conflicts, and the overlap and radar data from stage 3 | [strategy] | consumes stages 2–4 | L |
| A capability and policy model — every write only through a declared capability, privileged ones behind approval, reusing the stage-4 gates — with a persistent audit log on the timeline's schema, not a second one | [strategy] | stage 4 gates; `tasks/repotask.py:182` | M |
| Branch intelligence — merged, stale, abandoned, remote-only, safe to delete — with the criteria displayed rather than implied | [strategy] | `repomodel.py`; `tasks/loadtasks.py:89-92` | M |
| Repository health check driven by git's own maintenance advice instead of a loose object count | [strategy] [git-audit] | `reposcan.py:258` | M |
| Operation preview generalised: the exact command and the count of affected files, the argument vector built by one pure function shared by task and dialog so the preview cannot drift | [strategy] [ux-audit] | `forms/statusform.py:74-84` | M |
| Stacked-branch awareness as a read-only visualisation, with explicit text that it does not restack | [strategy] | `repomodel.py` | M |
| A compatibility suite: reftable, SHA-256, sparse-index and partial-clone fixtures in `test/`, run against each git release, the matrix generated by tests | [strategy] [git-audit] | `test/` | M |
| The stack decision gate, in writing: either part of the engine is extracted as a native library called from Python, or the subject is closed | [strategy] | — | S |

**Exit criteria.** An external agent obtains through MCP exactly what the user sees in the control
centre, and no more. Every write through MCP appears in the audit log and passed a declared
capability. The compatibility matrix is generated by tests.

## Standing risks

The work to date is 161 commits by a single author on one branch, with no tag of its own: a bus
factor of one on a GPL-3.0 fork whose upstream push remote is disabled. Before stage 1 is scoped in
detail, measure the cost of rebasing those commits onto the next upstream release; that number, not
a preference, decides how much of stage 1 is offered upstream instead of carried. `docs/` does not
exist upstream, which is why this file lives here: it cannot collide on a rebase.

## Out of scope for now

Several ideas from the source documents are deliberately not planned here: a rewrite onto a
different language and UI toolkit, the peer-to-peer device mesh and the mobile client that depends
on it, workflow triggering and deployment, interactive drag-and-drop rebase, worktree states git
cannot confirm, widening the agent sandbox so agents can commit, a hand-written reftable parser, and
binding a global undo shortcut to operations that move refs. Each is recorded with its reason and
evidence in [decisions rejected](decisions-rejected.md). Nothing there is forbidden forever; it is
the list of things that need a new fact before they can be replanned.
