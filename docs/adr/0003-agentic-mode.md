# ADR 0003 — Agentic mode built on worktrees

This is an architecture decision record for GitFourchette (`APP_VERSION = "1.11.0"`,
`gitfourchette/appconsts.py:16`). It records why agentic mode is anchored to the existing
worktree model, what the AI-chat code can and cannot do today, and which changes must land
before any of it. It is written for whoever implements or reviews the agentic pillar of the product
[vision](../vision.md). Every code reference below was re-checked against the working tree
before being written down; the commands used are listed at the end.

- **Status:** accepted as direction, not implemented.
- **Scope:** the session/process model only. Not the UI layout, not the provider list,
  not the mesh.

## Context

### What is being asked for

The agentic pillar asks for: task → worktree → agent; visible session state and current
operation; changed files, commands, tests and checkpoints streamed into the Git UI; pause,
resume, stop and redirect; approval gates before destructive Git operations; handoff to another
agent; and several agents in parallel with ownership visible. The session detail list adds
transcript, files modified, checkpoints created, tests executed and their results, permissions
granted, and cost/token/runtime metadata.

### What the code already has

There is a working single-turn process adapter, and it is the easy half.

| Capability | Where |
|---|---|
| Provider discovery (`codex`, `claude`) | `gitfourchette/exttools/aichat.py:41` |
| Argument construction per provider | `aichat.py:60` |
| JSONL stream reduction to visible text | `aichat.py:113`, `aichat.py:124` |
| Process start, stdout/stderr wiring | `forms/aichatdialog.py:946` |
| Line-by-line stream consumption | `aichatdialog.py:970`, `aichatdialog.py:987` |
| Stop, including the process group | `aichatdialog.py:1070`–`:1076` (`os.killpg`) |
| Elapsed-time clock | `aichatdialog.py:185` |
| Read-only vs. editing contract text | `aichat.py:161`, `aichat.py:165`, `aichat.py:173` |
| Tests around the adapter | `test/test_aichat.py` (36 `def test` lines) |

### What the code does not have

The conversation is a plain list created in `aichatdialog.py:257` and never serialized: there is
no `json.dump`, `write_text` or `save` of it anywhere in that file. The dialog is created with
`WA_DeleteOnClose` and `WindowModality.WindowModal` (`aichatdialog.py:238-239`), so closing it
destroys the conversation, and while an agent runs the rest of the window is unusable. Continuity
across turns is achieved by replaying: the whole prior conversation is serialized back into the
next prompt (`aichat.py:177`, which ends with `json.dumps(messages, ensure_ascii=False)`).

There is no session or agent domain object. The only class named `Session` is the
window-session preferences file (`settings.py:611`) — a different thing, but the name is taken.
There is no filesystem watcher anywhere in the package (`QFileSystemWatcher` has zero hits), so
"stream changed files into the Git UI" has no substrate today. Process ownership is not
centralized either: `aichatdialog.py:946` and `diffarea.py:894` are two hand-copied versions of
the same `QProcess` wiring, down to the same `closeWriteChannel()` call
(`aichatdialog.py:963`, `diffarea.py:905`).

### The central point: the flags make continuity impossible by construction

This is the finding that drives the decision, and it is not a missing feature — it is an
instruction we send ourselves.

- **codex** is invoked with `--ephemeral` (`aichat.py:70`). The vendor documents that flag as
  "Run without persisting session files to disk". The same CLI ships `codex exec resume` ("Resume
  a previous session by id or pick the most recent with `--last`") and `codex exec fork`.
- **claude** is invoked with `--no-session-persistence` (`aichat.py:75`). The vendor documents
  that flag as "Disable session persistence - sessions will not be saved to disk and cannot be
  resumed (only works with `--print`)". The same CLI ships `-r, --resume` and `--fork-session`.

Resume, redirect and handoff are therefore not blocked by the providers. They are blocked by two
of our own arguments. No amount of UI work on top of the current invocation can produce them.

### The second half: what claude is allowed to run

`aichat.py:76` passes `--tools` with the value chosen at `aichat.py:72`:
`Read,Grep,Glob,Edit,Write` (or `Read,Grep,Glob` when editing is off). The vendor documents
`--tools` as "Specify the list of available tools from the built-in set" — it is the exhaustive
list, and `Bash` is not in it. The claude provider, as invoked, cannot run a command, therefore
cannot run a test.

That has a direct consequence for the session-detail requirement "tests executed and their
results": for this provider the field is structurally always empty. Meanwhile the prompt we send
says "Do not claim tests were run unless you actually ran them" (`aichat.py:190-191`) — correct
instruction, impossible outcome. The providers are asymmetric here: codex receives
`--sandbox read-only` or `workspace-write` (`aichat.py:68-69`), documented as "the sandbox policy to
use when executing model-generated shell commands", so codex does have a shell. A session-detail
surface must therefore be able to say "this provider cannot run tests" rather than show an empty
list.

### The approval surface today

One checkbox, read before the run starts: `editsCheck` (`aichatdialog.py:375`), persisted as
`settings.history.aiAllowEdits` (`settings.py:395`), read at `aichatdialog.py:929` and `:941`.
codex additionally receives `-c approval_policy="never"` (`aichat.py:70`). There is exactly one
decision point, it happens before the process exists, and nothing can be asked during the run
because stdin is closed immediately after the prompt is written.

## Decision

**Agentic mode is built on the worktree model. It does not get a parallel isolation mechanism.**

1. **The worktree is the unit of isolation; the session is an actor inside it.** The model
   already exists: `porcelain.py:950` (`listall_worktrees`) plus the five tasks in
   `tasks/worktreetasks.py` (`NewWorktree`, `RemoveWorktree`, `LockWorktree`, `UnlockWorktree`,
   `PruneWorktrees`). Nothing new is invented for isolation.

2. **A session is a persistent object attached to a worktree, stored where the worktree already
   stores state.** `RepoPrefs` writes `gitfourchette.json` into `repo.path`
   (`repoprefs.py:22`, `repoprefs.py:45`). Verified empirically: for a linked worktree, pygit2
   reports `path = <main>/.git/worktrees/<name>/` while `workdir` is the worktree itself. The
   per-worktree side-file therefore already exists as a mechanism, and it lives under `.git`,
   so a persisted transcript is never accidentally committed. The object must not be called
   `Session` (name taken, `settings.py:611`).

3. **The application owns the process, and that is why it can report state.** The honest contract
   for states like "running tests" is that the application starts the command itself. States we
   cannot source are not displayed. Per-worktree Git state is genuinely available: verified
   empirically that a conflicted linked worktree reports `Repository.state() == 1` with
   `MERGE_HEAD` under `.git/worktrees/<name>/` while the main worktree reports `0`.

4. **Checkpoints are made by the application, not by the agent. The agent's sandbox is not
   widened to let it write `.git`.** The application already owns Git writes: `flowCallGit` is
   defined at `tasks/repotask.py:514` and called from 89 places. A checkpoint made by the app is
   attributable and auditable; a checkpoint made inside a widened sandbox gives back exactly the
   attack surface the sandbox exists to remove.

5. **The two continuity flags are removed and replaced by application-generated identity.**
   `--ephemeral` and `--no-session-persistence` go; the session id becomes something the
   application holds and hands back on resume. This is the cheapest item in the whole pillar and
   it gates three requirements at once (resume, redirect, handoff). Cross-provider handoff is
   re-summarization, not replay, and the product must say so in words.

6. **`Bash` is added to the claude tool list only together with a per-operation approval gate**,
   never before it. Today the guarantee "it will not touch Git" is free only because the provider
   has no shell. Removing that accident without replacing it with a gate is a regression.

## Prerequisites

These are not part of agentic mode; agentic mode cannot start without them.

| # | Prerequisite | Why it blocks | Size |
|---|---|---|---|
| P1 | Remove `WindowModal` and `WA_DeleteOnClose` (`aichatdialog.py:238-239`); the surface becomes a panel, not a dialog | A session that outlives its window cannot be owned by a window that deletes itself, and a modal window makes "agents run in parallel" a contradiction | S–M |
| P2 | Coalesce the stream and cache rendered messages | `render()` calls `chat.setHtml(transcriptHtml(self.messages, …))` (`aichatdialog.py:780-796`) and is called once per consumed JSONL line (`aichatdialog.py:999`). Typed tool events multiply the event rate; the panel becomes the bottleneck before the agent does | S |
| P3 | One owner for agent processes instead of two copies (`aichatdialog.py:946`, `diffarea.py:894`) | Parallel sessions cannot be tracked by a pattern that is duplicated per call site | S |

## Consequences

**Accepted costs.** Persisted transcripts are a new privacy surface and need an explicit
retention and clear-history decision; they live under `.git`, not in the worktree. Removing the
two flags means vendor session files start existing on disk — a user-visible change that belongs
in the release notes. Parallel sessions make the absence of cross-tab invalidation visible: two
worktrees of one repository share `$GIT_COMMON_DIR`, and a change made under one is not reflected
in the other today.

**Gained.** Resume, redirect and handoff become possible at all. Per-worktree session state is
storable in a mechanism that already exists and is already tested. Checkpoints are attributable
to the application, which is what makes an audit trail meaningful later.

**Deliberately not decided here.** Whether to widen any agent sandbox (no), whether to write our
own agent process supervisor (no), and anything from the mesh and mobile sections. Those belong
in [rejected decisions](../decisions-rejected.md) with their reasons, not in this record.
Sequencing belongs in the [roadmap](../roadmap.md); the stack question is settled in
[ADR 0001](0001-desktop-stack.md).

## How the claims above were checked

```
grep -n -- '--ephemeral\|--no-session-persistence\|"--tools"\|approval_policy' gitfourchette/exttools/aichat.py
grep -n 'WindowModal\|WA_DeleteOnClose\|closeWriteChannel\|killpg\|QProcess' gitfourchette/forms/aichatdialog.py
grep -n 'self.messages\|json.dump\|write_text' gitfourchette/forms/aichatdialog.py
grep -rn 'QFileSystemWatcher\|class .*Session' --include='*.py' gitfourchette/
grep -rn 'flowCallGit(' --include='*.py' gitfourchette/ | grep -v 'def flowCallGit' | wc -l   # 89
codex exec --help ; claude --help        # flag semantics quoted above, codex 0.150.1, claude 2.1.278
```

The per-worktree facts were checked by creating a throwaway repository with a linked worktree,
reading `Repository.path` / `.workdir` for both, and forcing a conflicting merge in the linked
worktree only (pygit2 1.20.1, libgit2 1.9.7).
