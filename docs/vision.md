# Product vision

This document states what this fork of GitFourchette is, what it is trying to become, and the rules
it holds itself to. It is written for anyone deciding what to build next — or deciding whether a
proposed feature belongs here at all. It contains no schedule; see the [roadmap](roadmap.md) for
sequencing and the [architecture notes](architecture.md) for how the pieces fit together. Ideas that
were considered and turned down live in [rejected decisions](decisions-rejected.md), with the reason.

`docs/` exists only in this fork. Upstream's tree has no `docs/` directory
(`git ls-tree -d --name-only upstream/master`), so these files cost nothing at rebase time.

## What GitFourchette is today

A desktop Git client for Linux first, built on Qt (PyQt6/PySide6) and Python 3.12 or newer
(`pyproject.toml:19`), at version 1.11.0 (`gitfourchette/appconsts.py:16`). It is a fork of
[jorio/gitfourchette](https://github.com/jorio/gitfourchette), distributed under the GPL-3.0
(`LICENSE`); the overwhelming majority of the source carries Iliyas Jorio's copyright. Everything in
this document is downstream work and inherits that license.

Mechanically, it is a **hybrid** client, and that is the single most important fact about it.
Reading goes through libgit2 via pygit2: `porcelain.Repo` is a subclass of `pygit2.Repository`
(`gitfourchette/porcelain.py:843`), and 63 modules import from `porcelain`. Writing and porcelain
operations go through the real `git` binary, launched as a child process — there are 89 `flowCallGit`
call sites across the codebase. Neither half is decorative: libgit2 gives cheap random access to the
object graph, and the git binary gives correctness on everything from `worktree prune` to
`push --atomic`.

What already ships, and therefore is not a plan:

- **Workspaces** — named sets of repositories, persisted and switchable
  (`gitfourchette/settings.py:490`), covered by 37 tests in `test/test_workspaces.py`.
- **Worktrees** — create, remove, lock, unlock, prune (`gitfourchette/tasks/worktreetasks.py`,
  classes at lines 48, 90, 136, 163, 173), reading the registry through
  `Repo.listall_worktrees` (`porcelain.py:950`); 42 tests in `test/test_tasks_worktree.py`.
- **A repository scanner** that inspects a folder without opening it in the UI
  (`gitfourchette/reposcan.py:156`), driving the Home browser.
- **An assistant over external CLIs** — `codex` and `claude`, discovered on `PATH`
  (`gitfourchette/exttools/aichat.py:41-45`). It can read, and optionally edit files in the working
  tree; it never commits, stages or pushes (`aichat.py:62-66`).

Size, for calibration: 238 Python files and 60,055 lines under `gitfourchette/`, plus 70 files and
32,274 lines under `test/`. The test suite is the most valuable asset here, and any proposal that
discards it is a proposal to start over.

## Where it is going

Toward a **control center for parallel development** — still a Git client, not an IDE, but one that
makes several simultaneous lines of work legible at a glance. Three commitments define the direction.

**Worktrees become first-class environments, not a sidebar node.** A worktree should report its
branch, HEAD, ahead/behind, dirty state and changed files without being opened, and the machinery to
do that already exists: `inspectRepo` (`reposcan.py:156`) runs
`status --porcelain=v2 --branch -z --untracked-files=normal` (`reposcan.py:183`) as a subprocess.
On top of that: overlap detection between worktrees, ahead/behind between arbitrary pairs rather than
only against upstream, fast compare, and conflict prediction before merge time.

**Agents become actors attached to worktrees.** The worktree stays the unit of isolation; an agent
session becomes an object with an owner, a state, a transcript and an audit trail. Today the
assistant is a conversation that lives and dies with one dialog, with no persistent session model;
that is the gap, and it is the interesting part of the work.

**One pane over N providers, with native Git semantics.** This is the narrow differentiator and it
should be stated narrowly. The vendors already ship background agents, worktree isolation and session
registries of their own. What none of them ships is a single surface that shows several providers'
work in Git's own vocabulary — diff, per-hunk stage and unstage, conflicts, cross-worktree overlap,
and checkpoints made by the application so they are attributable. Everything else in this vision is
in service of that.

## Principles

The first eight come from the strategy document. The rest are not aspirations: they are rules the
code already follows, written down so they survive the next contributor.

| # | Principle | What it means here |
|---|---|---|
| 1 | Git-first, not IDE-first | Editing code is someone else's job. We make Git legible. |
| 2 | Local-first by default | Cloud services are optional and additive; nothing requires an account. |
| 3 | No hidden destructive automation | Nothing irreversible happens without a confirmation the user can read. |
| 4 | Agent actions are attributable | Whatever an agent did must be visible as Git objects and as a log entry. |
| 5 | Worktree isolation for parallel autonomous work | Two agents never share a working directory. |
| 6 | Show relationships before conflicts get expensive | Overlap and conflict prediction are cheaper than conflict resolution. |
| 7 | Git is the source of truth | Application metadata augments history; it never becomes a second history. |
| 8 | Performance is a product feature | Latency regressions are defects, not trade-offs. |
| 9 | Back up before you destroy | Discarding files backs up each delta first (`tasks/indextasks.py:177-183` → `Trash.backupFile` / `backupPatch` / `backupTree`, `trash.py:127`, `:144`, `:149`). |
| 10 | `--force-with-lease`, never bare `--force` | The push refspec is built without a `+` prefix on purpose and force is expressed as an argument (`forms/pushdialog.py:361`, `:368`). No push call site passes `--force`. |
| 11 | Parse machine formats, not text written for humans | `--porcelain=v2`, `-z`, `--raw`, and `-c core.abbrev=no` so output does not depend on the user's config (`reposcan.py:183`, `gitdriver/gitdriver.py:324-325`, `tasks/jumptasks.py:56-57`). |
| 12 | Pin the locale; do not hope | Every git subprocess runs with `LC_ALL=C.UTF-8` (`tasks/repotask.py:549`, comment: "Force Git output in English"). |
| 13 | Ask a process to stop before killing it | Cancelling sends SIGTERM and only escalates to SIGKILL if the user insists a second time (`forms/statusform.py:117-129`, `exttools/toolcommands.py:460-471`). |
| 14 | Gate on capability, not assumption | Version-dependent flags sit behind explicit checks (`gitdriver.py:146-150` for `fetch --porcelain` ≥ 2.41, `:153-163` for `--` before positional args ≥ 2.39). |

Two of these are principles we do not yet apply uniformly, and saying so is part of holding them.
Principle 9 does not cover worktree removal: `git worktree remove --force`
(`tasks/worktreetasks.py:131`) deletes a folder with uncommitted work in it and takes no backup
first. Principle 14 has no floor: `validateGitPath` (`gitdriver/gitdriver.py:76-92`) only checks that
the command answers "git version", and no minimum-version constant exists anywhere in the tree. Both
are roadmap items, not restatements of the principle.

## What this is NOT

**Not an IDE.** No editor, no language servers, no build system. When a task needs an editor, we hand
it to the user's editor.

**Not a CI platform.** At most, some day, read-only pipeline state attached to a branch or commit.
Running pipelines, environment promotion and deployment gates are other products' problems.

**Not a cloud that holds your code.** Anything distributed has to work with the repository staying on
machines the user owns. A design that requires uploading a working tree is out of scope by
definition, not by priority.

**Not an implementation of Git's storage formats.** libgit2 1.9.7 cannot open a reftable repository —
verified here: `git init --ref-format=reftable` followed by `pygit2.Repository('.')` raises
`GitError: unsupported extension name extensions.refstorage`. The same hard ceiling applies to
SHA-256 (`unknown object format 'sha256'`). A sparse index and a partial clone are a softer case:
both open and then fail on first use — the index in one, a missing blob in the other. We do not
write a reftable parser; we detect what we cannot open and say so honestly. The
[architecture notes](architecture.md#known-limits) carry the measured table.

**Not a rewrite.** The language and toolkit question was asked and answered; see
[ADR 0001](adr/0001-desktop-stack.md) and [rejected decisions](decisions-rejected.md).

## Deferred pillars

Four pillars of the original strategy are deliberately not part of this vision's near work, and are
recorded with their reasons in [rejected decisions](decisions-rejected.md): the personal development
mesh of paired devices, the mobile control client that depends on it, CI/CD triggering and
environment promotion, and a local MCP server — the last one deferred rather than refused, because
exposing a data model to external agents before that model exists would lock in a shape we intend to
change. Stacked-branch awareness is deferred for a narrower reason: the operations that make a stack
useful are rebases, and no rebase support exists in the tree today.

---

*Counts above came from `find <dir> -name '*.py' | wc -l`, the same with
`-exec cat {} + | wc -l`, `grep -rn "flowCallGit(" gitfourchette/ | grep -v "def flowCallGit" | wc -l`
(the raw grep says 90: one hit is the definition at `tasks/repotask.py:514`), and
`grep -c "^def test" test/test_workspaces.py test/test_tasks_worktree.py`. They are a snapshot;
re-run them before quoting them.*
