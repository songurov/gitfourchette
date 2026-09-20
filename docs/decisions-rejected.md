# Evaluated and rejected

This file is the memory of what was already looked at and turned down. It exists so that an idea
which cost a day to disprove does not cost another day in six months. It is written for whoever
reads [vision](vision.md), [roadmap](roadmap.md) or [architecture](architecture.md) and thinks
"why isn't X in there" — X is probably below, with the reason and the evidence.

Every code reference was re-checked against the working tree at `6258f3e0` before it was written
down. Where a claim came from an earlier report and did not survive that check, the claim is
recorded as retired, not repeated. Section 5 exists for exactly that.

---

## 1. Already implemented — proposals that were wrong

These were proposed as gaps. They are not gaps. Each line names what exists and where.

| Proposal | What is actually there |
|---|---|
| "Give `DiffArea` a conflict page" | `ConflictView` (421 lines, `forms/conflictview.py`) is the third widget added to `diffStack`, behind a scroll area (`diffarea.py:1076-1085`), and is kept as `self.conflictView` (`:1114`) |
| "Write a diff3/zdiff3 conflict parser" | `mergeview/conflictparser.py` parses both. The base marker is defined (`:19`), the base label is captured (`:138`) and `sawBase` decides whether it is kept (`:148`); the docstring names both styles (`:87`). What is missing is *showing* the base, not parsing it |
| "Ship AI review of a branch before push" | The branch context menu already offers "Ask AI about branch…" plus every preset, including "Code review" (`sidebar/sidebar.py:608-612`, presets at `exttools/aichat.py:21-38`). Only the entry point from the push dialog is missing |
| "The graph context menu describes the last selection, not the row under the cursor" | The handler reads `self.navLocator` (`graphview/graphview.py:448`) on purpose. Re-pointing it at the row under the cursor would break the multi-selection menu asserted by `testSelect3PlusCommits` (`test/test_graphview.py:763-782`) |
| "Add checkout-by-name from the keyboard" | The sidebar embeds `SearchBar(self, SidebarSearch(self))` (`sidebar/sidebar.py:89`). Moving it into the palette is consolidation, not a new capability |
| "Build a shortcut cheat sheet" | Quick Launch walks the live menu bar and puts each action's shortcut in `detail`, formatted as `NativeText` (`forms/quicklaunch.py:124-125`) |
| "`InspectMergeResolution` is unreachable" | Every merge commit's detail panel carries a "See what was decided" link (`forms/commitdetailview.py:78-81`) |
| "Ref chips bypass the contrast gate" | `ChipStyle` is rebuilt from the live `QPalette` on each paint (`graphview/commitlogdelegate.py:405-413`) and chip ink goes through `readableOn` (`:882`, defined `:154`) |
| "`compactUi` is a radio button that drops one point" | The preference is labelled "Density", with Normal/Compact and its own help line (`trtables.py:401-404`) |
| "Home needs a Rescan button" | `welcomewidget.py:347-349` |
| "`ActivityButton` is inert" | It carries a menu wired to `aboutToShow` (`mainwindow.py:145-148`) and `fillActivityMenu` refills it from the live activity log (`:759-767`). It is read-only, which is a different complaint |

**Shortcuts that are not free.** Four proposals collided with bindings that already exist:
`Ctrl+K` is `UserCommand.LeaderKey` (`exttools/usercommand.py:30`); `Ctrl+Shift+P` is `PullBranch`
(`tasks/taskbook.py:200`); `Alt+3` and `Alt+4` focus the file list and the code view
(`mainwindow.py:408-409`); `Alt+C` collides with the "&Commands" menu mnemonic
(`mainwindow.py:276`).

## 2. Wrong mechanisms that would have caused regressions

The goal was sometimes right; the mechanism was not. These are recorded because the mechanism is
the part that gets re-proposed.

**`int(arc.chain.topRow)` as a lane's colour identity.** `BatchRow`'s own docstring says row
numbers move when a refresh pushes existing rows down (`graph/graph.py:44-57`), and
`ChainHandle.topRow` resolves through aliases while `setAliasOf` clears the stored row
(`graph.py:211-215`, `:224-231`). The colour is `rainbowBright[laneID % len(rainbowBright)]`
(`graphview/graphpaint.py:35-36`, eight entries at `colors.py:33-35`), so a key derived from
`topRow` would repaint branches in new colours after any fetch that adds commits. Use a monotonic
serial owned by the `ChainHandle` instead.

**The app's own Python module as `sequence.editor` for interactive rebase.** It does not survive
in a Flatpak, and `pkg/flatpak/` is a shipping target. Note the starting point: the tree has no
rebase code at all (`grep -rn "class .*Rebase" gitfourchette/` returns nothing) and no editor
plumbing of any kind (`core.editor`, `GIT_EDITOR`, `sequence.editor` all return nothing). The
mechanism to write, when rebase is written, is `-c sequence.editor=cp <todo-file>`.

**`rebase --continue` without `core.editor=true`.** Git opens an editor and the `QProcess` hangs
until something kills it. All 89 `flowCallGit` call sites run git as a child process; none of them
sets an editor today, so this has to be done deliberately at the rebase call site.

**`-c rerere.enabled=true` on the invocation.** That turns rerere on for the whole repository,
including work done outside this application, and it records resolutions the user never asked for.
There is no `rerere` reference anywhere in the tree today. If it is wanted, it is an explicit
preference, off by default, with text that says what it does.

**A switch that writes `core.fsmonitor` or `core.untrackedCache` into the user's config.** The
scanner argues the opposite case at the call site and passes `-c core.fsmonitor=false` per
invocation instead, precisely so that a `git status` never leaves a watcher daemon behind
(`reposcan.py:174-179`). Writing those keys changes git's behaviour for every other tool on the
machine. Read-only diagnostics in Get Info are fine; a write button is not.

**`--since` as a fallback for `--since-as-filter`** (`forms/aichatdialog.py:723`). They are not
equivalent: `--since` stops the traversal at the first older commit on each path, so the result is
silently short rather than filtered.

**A "one-line fix" that routes Ctrl+F to `patchView`.** No such attribute exists; the name is
`commitPatchView` (`diffarea.py:133`).

**A version gate on `git checkout --merge` derived from unverified release notes.** Replaced by an
unconditional backup into `Trash` before the operation, which does not depend on reading a
changelog correctly.

## 3. Rejected as off-philosophy or infeasible

**A rebrand: own brand token, own hicolor icon set.** The application icon in this fork is
byte-identical to upstream's (`git show upstream/master:gitfourchette/assets/icons/gitfourchette.png
| cmp - gitfourchette/assets/icons/gitfourchette.png` reports no difference). 279 tracked files
mention Iliyas Jorio; four mention Songurov, and none of those four is a copyright header — they are
`credits.json`, `whatsnew.json` and two tests. This is a GPL fork whose work is meant to go back
upstream. Renaming someone else's product is not a design decision available to it.

**Combined `--cc` diffs for merge commits.** The parser reads a single origin column
(`diffview/diffdocument.py:309`) and asserts it is a space when it is neither `+` nor `-` (`:348`).
A combined diff has two origin columns. Rewriting the parser also rewrites per-line staging, which
reads the same `LineData` objects. This is a project, not a feature.

**A global Ctrl+Z bound to undo on refs.** It would promise an atomic undo that Git does not have.
Everything touching the working directory goes through `Trash`; everything that moves a ref goes
through an explicit, named undo record.

**Worktree states "running tests" and "waiting".** Neither has any source in Git. Detecting foreign
processes would make `psutil` a hard dependency; today it is an optional extra
(`memory-indicator = ["psutil"]`, `pyproject.toml:54`) and it is unreliable on macOS. The only
honest contract is the one where the application starts the process itself and therefore knows its
state — which is where agentic mode arrives anyway (see [ADR 0003](adr/0003-agentic-mode.md)).

**Auto-expanding history as the user scrolls.** History is bounded by `maxCommits`, default 10000
(`settings.py:190`), and the graph saves a keyframe every `KF_INTERVAL` rows into a list with no
size cap (`graph/graphbuilder.py:157-160`, `graph/graph.py:671-681`). The only code that shortens
it is the splicer dropping keyframes that depend on rows above the equilibrium (`graph.py:773`,
called from `graphsplicer.py:168`), which a downward scroll never reaches. Without a cap on that
cache, an absent-minded scroll becomes a half-million-commit load.

**Our own reftable parser.** libgit2 1.9.7 refuses the repository outright: `git init
--ref-format=reftable` followed by `pygit2.Repository(path)` raises
`GitError: unsupported extension name extensions.refstorage` (re-run today). The answer is to
detect what cannot be opened and say so, and to upgrade the library when upstream libgit2 supports
it — not to reimplement Git's storage.

**Our own supervisor for agent processes.** The adapters already run as child processes under the
task runner; a second supervisor means owning process reaping, orphan cleanup and status
reconciliation twice.

**Widening the agent sandbox so the agent can commit.** Read-only analysis runs with
`--sandbox read-only` and `Read,Grep,Glob`; edit mode uses `workspace-write` with `Edit,Write` and
still no shell (`exttools/aichat.py:68-76`). Adding `.git` to the writable roots hands back the
attack surface the sandbox exists for — a planted hook runs outside it. The application makes the
checkpoint; that is also the only version in which the checkpoint is attributable.

**Blink and onion-skin modes for image diffs.** A timer that repaints is an effect, not a reading
aid. A static swipe is the version worth considering.

**A placeholder "Worktrees" row in the sidebar when there are none.** It contradicts a decision
already taken and commented in place: a repository that does not use worktrees should not be told
about them (`sidebar/sidebarmodel.py:386-388`).

**"Stacked branches with `--update-refs`" as a separate item.** It depends entirely on interactive
rebase and its deliverable is a checkbox plus a list in that dialog. It is an acceptance criterion
of that work, not a line of its own.

**Cherry-pick or revert of N commits as a signature extension.** Today the app runs
`cherry-pick --no-commit` for one commit and deliberately leaves the result in the working directory
for review (`tasks/committasks.py:631`, comment at `:642`). Applying N commits changes what the
feature promises, so it is a product decision to be taken in the open, not a parameter change.

## 4. Deferred with a reason

Not refused. Each line names the condition that would bring it back.

| Deferred | Why not now | What would reopen it |
|---|---|---|
| Personal Development Mesh | There is no session model to synchronise; it is created by agentic mode, not before it. Node identity, pairing and transport do not exist either | A session model in the tree, and a second machine that actually needs it |
| Mobile control client | Depends entirely on the mesh. Without nodes it is a commit viewer | The mesh exists and is used |
| CI/CD triggering and environment promotion | Read-only pipeline state on a branch or commit is the ceiling the [vision](vision.md) sets; triggering earns its value from a phone | The mesh and the mobile client ship |
| Home as a tab instead of a mode | The window swaps between the welcome widget and the tab bar inside one `QStackedWidget` (`mainwindow.py:90-116`), and 11 call sites read `tabs.widgets()`. A dockable, workspace-scoped panel gets most of the benefit without touching either | The panel ships and the absence still hurts |
| Interactive rebase with drag and drop | There is no rebase support of any kind to build on yet | Plain rebase plus `--continue/--abort/--skip` lands and the plan editor is the top request |
| A local MCP server | Exposing a data model to external agents before that model exists locks in a shape we intend to change | The worktree and session models have settled |

One correction worth carrying: the argument that the mesh is "impossible by construction because
workspace membership is stored as absolute paths" is false. `Settings.setWorkspace` calls
`os.path.normpath`, not `abspath` (`settings.py:493`); absoluteness comes from the caller. Portable
workspace metadata is a boundary conversion, and it is cheap. It is not the reason the mesh is
deferred — the missing session model is.

## 5. Claims that did not survive verification

These circulated in planning documents and are false or mis-anchored. They are listed so they do
not come back.

| Claim | Status |
|---|---|
| "`settings.py:492` absolutises paths, so portable metadata is impossible" | False. The line is `os.path.normpath`, at `settings.py:493`. Every argument built on it is void |
| "`pygit2.merge_commits()`" as a module function | False. `hasattr(pygit2, "merge_commits")` is `False`; `hasattr(pygit2.Repository, "merge_commits")` is `True` |
| "`RepoTaskRunner` is mono-task (`repotask.py:487-489`)" | False and mis-anchored. Those lines are asserts in `flowStartProcess`. The runner (`:775`) holds `_currentTask` (`:804`) and `_pendingTask` (`:807`, "Task that is queued to run after `_currentTask`"): a queue of one |
| "10.94 s to scan 48 repositories" | Unsourced. The only timing in the suite is three cancellation deadline checks (`test/test_home.py:700-702`, `:723-725`, `:850-852`). Nothing measures scanning N repositories, so the number cannot be reproduced |
| "`ActivityButton` is completely inert" | False; see section 1 |
| "`setToolTipsVisible(True)` is missing" / "54 tooltips missing" | Partly false and uncounted. The call appears in 10 places, including `mainwindow.py:285` and `sidebar/sidebar.py:627`. It is absent only from `ActionDef.makeQMenu` (`toolbox/actiondef.py:180-188`). Nobody counted 54 of anything |
| "`theme.qss` is broken in the index" | The index half is false: `git status --porcelain gitfourchette/assets/style/` is empty. The retirement of the rest was wrong, though — the braces do **not** balance at `6258f3e0`. `python3 -c "s=open('gitfourchette/assets/style/theme.qss').read(); print(s.count('{'), s.count('}'))"` prints `430 429`, and the rule opened at `theme.qss:934` is never closed before the next rule at `:937`. `test/test_themes.py:693-695` asserts that balance. This is a live defect to file, not a rejected proposal, and "398/398" must not be quoted either |
| "`base.qss:19-26` contains literal colours" | Mis-anchored. The literals are at `:16-19`, `:21-22` and `:27-28` |
| "`-S` is free for a pickaxe search" | False. `tasks/blametasks.py:401` already passes `-S` to `git blame`, where it means "use revisions from this file" |
| "`patchView`" | Wrong name; it is `commitPatchView` (`diffarea.py:133`) |
| "A guard on an invalid index at `graphview.py:447`" | Mis-anchored. `:447` is `actions = None`; the handler reads the locator at `:448` |

---

*Commands behind the numbers on this page:
`grep -rn "flowCallGit(" gitfourchette/ | wc -l` (90 hits: 89 call sites plus the definition at
`tasks/repotask.py:514`);
`grep -rn "setToolTipsVisible" gitfourchette/ | wc -l` (10);
`grep -rn "tabs.widgets()" gitfourchette/ | wc -l` (11);
`git grep -l "Iliyas Jorio" | wc -l` (279) and `git grep -l "Songurov" | wc -l` (4);
`git ls-tree -d --name-only upstream/master` (no `docs/`, so this file cannot conflict on rebase).
They are a snapshot of `6258f3e0`; re-run them before quoting them.*
