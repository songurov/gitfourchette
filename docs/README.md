# Documentation

Working documentation for this fork of [GitFourchette](https://github.com/jorio/gitfourchette).
It describes the client as it actually is, what is planned for it, and which ideas were examined
and turned down — each claim anchored to a `file:line` in the tree and each number accompanied by
the command that produced it.

This folder is for contributors, reviewers and anyone sizing a change: someone deciding what to
build next, someone checking whether a claim about the product is true, or someone reviewing a
proposal to rewrite, rename or detach it. It is not a user manual and not release notes. Those live
in the repository root: `README.md` and `CHANGELOG.md`, both of which upstream owns.

`docs/` exists only in this fork. Upstream's tree has six root directories and has never had a
`docs/` directory, so everything here is a pure addition at rebase time and cannot conflict:

```sh
git ls-tree -d --name-only upstream/master   # .github .idea .vscode gitfourchette pkg test
git log --all --diff-filter=A -- 'docs/*'    # nothing
```

## What is here

| Document | Kind | One line |
|---|---|---|
| [vision.md](vision.md) | Product | What the product is, where it is going, and the rules it holds itself to. No schedule. |
| [roadmap.md](roadmap.md) | Plan | Five dependency-ordered stages, each with deliverables, code anchors, effort sizes and exit criteria. |
| [architecture.md](architecture.md) | Descriptive | How the client is put together today: the hybrid Git access, the task model, the graph engine, the UI layers, the known limits. |
| [git-coverage.md](git-coverage.md) | Inventory | Which Git features are exposed, where, and what is missing — plus the version floor and the repository formats libgit2 cannot open. |
| [ux-guidelines.md](ux-guidelines.md) | Design | Where the current look comes from, what is kept, what is replaced and why, and the accessibility and localization debt. |
| [decisions-rejected.md](decisions-rejected.md) | Memory | Proposals that were wrong, mechanisms that would have regressed, ideas off-philosophy, things deferred, and claims that failed verification. |
| [adr/0001-desktop-stack.md](adr/0001-desktop-stack.md) | ADR | Stay on PyQt6 and pygit2; why the Rust + Flutter rewrite was declined, and the spike that would reopen it. |
| [adr/0002-worktree-control-center.md](adr/0002-worktree-control-center.md) | ADR | A dockable, workspace-scoped panel over N worktrees, with a dual-engine conflict radar and four displayable states. |
| [adr/0003-agentic-mode.md](adr/0003-agentic-mode.md) | ADR | Agent sessions attached to worktrees; why two of our own CLI flags make continuity impossible today. |
| [adr/0004-fork-relationship.md](adr/0004-fork-relationship.md) | ADR | Stay synchronized with upstream, send opinion-free fixes back, leave name and identity untouched. |

Two conventions run through all of it. **Effort is a size, never a date** — S is up to about three
days, M one to two weeks, L three to six weeks, XL two to four months. And **an idea that is not
being built is recorded with its reason**, in `decisions-rejected.md`, rather than dropped
silently; `roadmap.md` keeps a short "Out of scope for now" list that points there.

## Reading order

For a contributor who has just cloned the tree:

1. **[architecture.md](architecture.md)** — start here. Nothing else makes sense until you know
   that the client is hybrid: reads go through libgit2 via pygit2 (`porcelain.py:843` is
   `class Repo(_VanillaRepository)`, imported by 63 modules), writes and porcelain go through the
   real `git` binary as a `QProcess` (89 `flowCallGit` call sites). Read at least "Hybrid Git
   access" and "The task model" before touching any code.
2. **[vision.md](vision.md)** — what the product is for, and the fourteen principles the code
   already follows. Read this before proposing a feature.
3. **[roadmap.md](roadmap.md)** — where the work sits in sequence, and what blocks what. Its
   "How to read this" section explains the ordering rule.
4. **[git-coverage.md](git-coverage.md)** — consult it when your change touches a Git command,
   to find out whether it is already exposed and where. It is a reference, not a read-through.
5. **[decisions-rejected.md](decisions-rejected.md)** — read this *before* proposing anything.
   It is the cheapest document in the folder: it exists so an idea that cost a day to disprove
   does not cost another day in six months.
6. **The ADRs**, in whatever order the work requires. [0001](adr/0001-desktop-stack.md) settles the
   stack, [0004](adr/0004-fork-relationship.md) settles what goes upstream, and those two constrain
   everything else. [0002](adr/0002-worktree-control-center.md) and
   [0003](adr/0003-agentic-mode.md) are feature-specific: read them when you work on that feature.
7. **[ux-guidelines.md](ux-guidelines.md)** — required reading before touching `themes.py`, a
   stylesheet, a delegate or a pixel test. Skippable otherwise.

If you are reviewing a proposal rather than writing code, the short path is
`decisions-rejected.md` first, then the relevant ADR, then the anchors.

## How these documents are maintained

**The standing rule.** Every claim about the code carries a `file:line`, and every number carries
the command that produced it. Anchors drift. Before quoting one, re-run the command; if it no
longer matches, fix the anchor or drop the claim. Do not copy anchors out of older reports —
several of the entries in section 5 of `decisions-rejected.md` exist because someone did.

**When each file changes:**

| Document | Updated when |
|---|---|
| `vision.md` | Rarely — a pillar is added, dropped or redefined. Shipping a feature that was listed as a plan moves it into "What GitFourchette is today". |
| `roadmap.md` | A stage's deliverable lands, is dropped, or moves between stages; an exit criterion is met. Sizes are re-estimated when the anchor they rest on changes. |
| `architecture.md` | The code changes. It is purely descriptive, so it is wrong the moment the tree moves. Re-check it whenever a module named in it is restructured. |
| `git-coverage.md` | A task is added, removed or renamed. Its "How this file is maintained" section gives the regeneration procedure, starting from `grep -rn "class .*(RepoTask)" gitfourchette/tasks/`. |
| `ux-guidelines.md` | A theme token, a stylesheet rule, a delegate constant or a translation catalogue changes. The localization table is regenerated, not edited by hand. |
| `decisions-rejected.md` | An idea is turned down, or a claim fails verification. Entries are appended; an entry is removed only when the fact it rests on has changed, and then the roadmap gains the item. |
| `adr/*.md` | Never rewritten. See below. |

**ADRs are not edited to reflect new opinions.** An ADR is a record of a decision taken at a point
in time, with the evidence that was available then. When the decision changes, the old record keeps
its text and gains a superseding note; a new ADR is written with the next number and states which
one it supersedes.

- Status values: **Proposed**, **Accepted**, **Superseded by ADR NNNN**, **Deprecated**.
- Changing a status is the only edit made to a decided ADR's body. Correcting a factual error —
  a wrong line number, a miscounted file — is a correction, not a change of decision, and is made
  in place.
- Each ADR names its scope in the "Status" section, so it is clear what it does *not* decide.
  Sequencing is never decided in an ADR; it belongs in `roadmap.md`.
- Every ADR carries a "How the claims above were checked" block or per-fact commands. A new ADR
  without one is incomplete.

Current numbering: 0001 desktop stack, 0002 worktree control center, 0003 agentic mode, 0004
relationship with upstream. The next ADR is 0005.

**Two rules specific to this fork.** First, nothing here proposes renaming, relicensing or
rebranding the product: the name, the application identifier, the packaging metadata and the
donation link are upstream's, and `adr/0004-fork-relationship.md` records that as a decision.
Second, anything that would otherwise be written into the root `README.md` — which upstream owns —
is written here and linked from there in a single line, so the rebase surface stays at zero.

## Consistency checks

Run these before sending a documentation change.

```sh
# Every relative link resolves (file and, where present, heading anchor).
# 84 relative links across the eleven documents at the time of writing.
grep -rhoE '\]\([^)#][^)]*\)' docs/ | tr -d '()' | sed 's/^]//' | sort -u

# The headline measurements. Re-run, do not trust the text.
find gitfourchette -name '*.py' -not -path '*__pycache__*' | wc -l          # 238 files
find gitfourchette -name '*.py' -not -path '*__pycache__*' -exec cat {} + | wc -l   # 60055
find test -name '*.py' -not -path '*__pycache__*' | wc -l                   # 70 files
grep -rn 'flowCallGit(' gitfourchette/ | wc -l    # 90 hits = 89 call sites + the definition
grep -rn 'class .*(RepoTask)' gitfourchette/tasks/ | wc -l                  # 83
grep -rl 'porcelain import\|import porcelain' gitfourchette/ | wc -l        # 63
git grep -l 'Copyright (C).*Iliyas Jorio' | wc -l                           # 269
```

Note that three near-identical copyright counts appear across these documents and all three are
correct, because the greps differ: `git grep -l "Copyright (C).*Iliyas Jorio"` returns 269,
`git grep -l "Copyright.*Iliyas Jorio"` returns 270, and `git grep -l "Iliyas Jorio"` returns 279.
Quote the command with the number, never the number alone.
