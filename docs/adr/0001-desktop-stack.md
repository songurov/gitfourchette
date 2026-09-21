# ADR 0001 — Desktop stack: stay on PyQt6 for now

An architecture decision record for anyone deciding what GitFourchette is written in: maintainers,
contributors sizing a change, and reviewers of any future rewrite proposal. It records why the
proposal to rewrite the desktop application in Rust + Flutter was declined, what would have to
become true for that to change, and which problems no rewrite would solve.

## Status

Accepted. Scope: the desktop application's UI toolkit and Git engine. It decides no feature and no
sequencing (see [roadmap](../roadmap.md)); ideas rejected here are recorded with their evidence
in [rejected decisions](../decisions-rejected.md). Effort sizes: **S** ≤ 3 days, **M** = 1–2 weeks.
No calendar commitments are made.

## Context

The product strategy asks for a local-first control centre for parallel development: worktrees as
first-class environments, agent sessions attached to them, an MCP surface, a device mesh, and
eventually a mobile control surface. Four competing stack proposals were put to a review panel. None
cleared the bar, and no reviewer passed any variant that introduced Rust. One was a full rewrite in
Rust + Flutter; another was a Rust core with two front ends. This ADR answers that question only.

### What the codebase actually is

Measured on this working tree, on the `feature/workspaces` branch:

| Fact | Value | How it was measured |
|---|---|---|
| Application source | 238 files, 60,055 lines | `find gitfourchette -name '*.py' \| wc -l`; `-exec cat {} + \| wc -l` |
| Test source | 70 files, 32,274 lines | same, over `test/` |
| Test functions | 1,124 | `grep -hcE "^\s*def test" test/*.py` summed |
| …taking the `mainWindow` fixture | 968 (86%) | `grep -hcE "^\s*def test.*mainWindow" test/*.py` summed |
| Git writes through the `git` binary | 89 call sites | `grep -rn flowCallGit gitfourchette/ --include='*.py'` (90 hits, one is the definition at `tasks/repotask.py:514`) |
| Python floor | `>= 3.12` | `pyproject.toml:19` |
| Git bindings | pygit2 1.20.1 / libgit2 1.9.7 | `.venv/bin/python -c "import pygit2; print(pygit2.__version__, pygit2.LIBGIT2_VERSION)"` |

The client is **hybrid**: writes and porcelain go through the `git` binary launched as a `QProcess`;
reads (graph, refs, blobs, index) go through libgit2.

### The facts that decide

**1. The seam a new core would plug into does not exist.** `gitfourchette/porcelain.py:843` is
`class Repo(_VanillaRepository)` — a subclass of `pygit2.Repository`, documented as a "drop-in
replacement". 63 modules import from `porcelain`, and `Oid` alone appears on 215 lines outside it.
Those are not data; they are lazy handles over libgit2 memory, traversed directly from UI code.
A core behind RPC or behind PyO3 cannot preserve that semantics without either a round trip per
attribute access or a DTO layer across exactly the modules every proposal promised not to touch.
Changing the core, in any language, is a rewrite of the object model.
*Verified with:* `sed -n '843p' gitfourchette/porcelain.py`; `grep -rl "porcelain import"
gitfourchette/ --include='*.py'` → 63; `grep -rw Oid gitfourchette/ --include='*.py' | grep -v
'^gitfourchette/porcelain.py'` → 215 lines (`grep -row`, counting occurrences rather than lines,
→ 228).

**2. The test suite is not an oracle for a new core.** 968 of 1,124 test functions take the
`mainWindow` fixture, and `test/conftest.py:21` imports `GFApplication` at module level. This is a
Qt GUI suite: it cannot validate the Git semantics of a Rust core — a silent false negative in a
merge does not fail a test that draws a sidebar — and it does not survive the removal of Qt.
The one portable oracle is the graph tests: `test_graphplayback.py`, `test_graphsplicer.py`,
`test_graphtrickle.py`, `test_graphtricklestabilization.py` — 1,145 lines, 8 test functions that
pytest expands to 155 cases, with zero references to Qt, `qtbot` or `mainWindow` in the files
themselves (`grep -cE "PyQt|PySide|qtbot|mainWindow"` → 0 on each).

**3. On capabilities, Rust is a downgrade today.** In the gitoxide tree at `a0e284c`:
`gix-protocol/src` contains `fetch` and `handshake` and no push module; `gix-rebase` is
`version = "0.0.0"` with a one-line `lib.rs`; there is no `gix-reftable` crate. Meanwhile libgit2
`main` at `0551dfd` already contains `src/libgit2/refdb_reftable.c` (1,897 lines) and lists
`"refstorage"` in `builtin_extensions[]` at `src/libgit2/repository.c:1924` — reftable arrives
through a wheel bump, not a rewrite. `git2-rs` is the same libgit2, so it inherits the same ceiling.

**4. Flutter desktop is unproven for the layer this product leans on hardest.** The editing and
diff surface is three `QPlainTextEdit` subclasses (`codeview/codeview.py:29`,
`mergeview/mergeeditor.py:27`, `forms/commitarea.py:49`) plus the gutter that paints beside them
(`CodeGutter`, a `QWidget`, at `codeview/codegutter.py:16`), 26 `.ui` files, 25 files that paint
with `QPainter`, 14 `.po` translations and 968 GUI tests. The stack review found no published,
reproducible benchmark for a 100k-line monospace diff view in Flutter desktop, in either direction.
That absence is not evidence of failure; it is why the question is settled by a spike with a
threshold, not by assertion.

**5. Native mobile is blocked by licence, not by toolkit.** The project is GPL-3.0 (`LICENSE`, with
headers of the form `Copyright (C) 2026 Iliyas Jorio … distributed under the GNU GPL v3`).
270 tracked files carry that copyright line; **zero** carry one for this fork's author — the name
appears in four tracked files (a credits entry, a release-notes contributor line and two tests) and
in one untracked local build script
(`git grep -l "Copyright.*Iliyas Jorio" | wc -l` → 270; the same grep for Songurov → 0;
`git grep -l Songurov | wc -l` → 4). See [ADR 0004](0004-fork-relationship.md) for the file list.
The app id is `org.gitfourchette.gitfourchette` (`appconsts.py:20`) and the About box links
`https://ko-fi.com/jorio` (`forms/aboutdialog.py:24`). Relicensing is not in this fork's power.

**6. Fork position.** `origin/master == upstream/master == 5a019e8e`; all 161 local commits sit on
`feature/workspaces`, by a single author, across four days; there are no own tags; upstream is
active. `git ls-tree -d --name-only upstream/master` shows no `docs/`, which is why this document
lives where it does: it cannot conflict on rebase.

## Decision

1. **No rewrite.** The desktop application stays on PyQt6/PySide6 with pygit2 for reads and the
   `git` binary for writes. This is not a deferral of a rewrite that is otherwise agreed; it is a
   decision that the rewrite as proposed was not justified by the evidence presented.

2. **If Rust ever enters, it enters at the graph pipeline first, and nowhere else.** Not in
   `porcelain.py`, not on the write path, not on the read path as a whole. The one candidate is
   walk + weave behind an **array-shaped PyO3 boundary**: batches of `(oid_bytes, [parent_oid_bytes])`
   in, row and lane arrays out, no pygit2 type at the boundary. Three properties make it the only
   defensible first cut: it is the only component with a portable oracle (fact 2); `CommitTraits`
   at `gitfourchette/graph/graph.py:21` is a `Protocol`, so a plain dataclass satisfies it without
   touching pygit2; and the data crosses once in bulk, the only shape in which the crossing tax does
   not eat the gain.

3. **Flutter is not adopted on the desktop.** Mobile is not a toolkit question until the licence
   question in fact 5 has an answer.

## Consequences

**Four Git formats stay out of reach in every scenario, including a rewrite.** Measured against
libgit2 1.9.7 with repositories created by git 2.54.0:

| Repository format | Behaviour under libgit2 1.9.7 |
|---|---|
| reftable (`git init --ref-format=reftable`) | Does not open: `GitError: unsupported extension name extensions.refstorage` |
| SHA-256 (`git init --object-format=sha256`) | Does not open: `InvalidError: unknown object format 'sha256'` |
| sparse-index (`sparse-checkout init --cone --sparse-index`) | Opens; the first `repo.index` access raises `GitError: unsupported mandatory extension: 'sdir'` |
| partial clone (`clone --filter=blob:none`) | Opens, and the index reads; a blob left behind the promisor remote raises `KeyError` on lookup |

The first two are hard stops before a `Repo` object exists, so "fall back to the Git CLI for
unsupported operations" does not apply at that level — there is no object to fall back from. None is
fixed by changing language: `git2-rs` is the same libgit2, gitoxide has no reftable crate, and
sparse-index and partial clone have no complete implementation outside the git CLI in any language.
What the project controls is honesty: detect the format before opening, and say so inline. That is
**S–M**, and it belongs on the roadmap regardless of this ADR.

**Accepted costs.** The GIL, Python start-up time and packaging weight stay. The repository scan
stays serial until someone changes it: `grep -rE "QThreadPool|QMutex|threading\.Lock"` over
`gitfourchette/` returns zero hits. But `inspectRepo` (`reposcan.py:156`) already runs
`git status --porcelain=v2` as a **child process** (`reposcan.py:173`), and its docstring at
`:163-167` says this was done precisely because pygit2 holds the global lock for the duration of a
status call. Whatever the scan costs today, that cost is serialisation, not the GIL — which is why
the spike below starts by trying to fix it in Python.

**Capabilities no rewrite is needed to unlock.** `Repository.rebase_init` exists in pygit2 1.20.1 —
a method on `Repository`, not a module-level function, as is `Repository.merge_commits`, the
in-memory conflict-prediction primitive. Rebase is absent here for product reasons, not binding ones.

**One gap this ADR exposes and does not close.** No minimum git version is declared or checked
anywhere: `validateGitPath` (`gitdriver/gitdriver.py:76`) accepts any binary that answers
`git version`. The highest gated feature is `fetch --porcelain` at 2.41 (`gitdriver.py:146-150`),
with further gates at 2.39 (`:163`) and below 2.37 (`diffview/specialdiff.py:148`), while
`-c core.abbrev=no` is used ungated (e.g. `gitdriver.py:324`). Declaring a floor is **S**.

## Spike

Three tracks, thresholds written before the measurement, to replace three assumptions with three
re-runnable numbers.

**Track A — the null hypothesis (no Rust). Effort S.** Put a `QThreadPool` over `inspectRepo` and
measure serial versus parallel scanning of the real repository set, p50 and p95 over five runs.
A timing harness exists but is not wired to the scan: `toolbox/benchmark.py` provides a `Benchmark`
context manager and a `@benchmark` decorator that log elapsed milliseconds and RSS at logging level
5, and `reposcan.py` uses neither. There is no recorded baseline; the track must wire the harness to
the scan and produce one before the threshold means anything. **Threshold: if parallel Python
reaches ≥ 4× serial, the "Rust for scanning" argument is dead and is deleted from every document.**

**Track B — the narrow Rust boundary. Effort M.** Build `gfgraph`, a standalone PyO3 module
(maturin, wheel into the existing `.venv`), array in and array out, with zero pygit2 types at the
boundary; port the graph build loop and weaver line by line. **Thresholds, all four required:**
(a) end-to-end walk + weave ≥ 2× the current Python baseline, *including* the PyO3 crossing;
(b) crossing tax ≤ 15% of the gross gain; (c) the four graph test files pass unmodified;
(d) peak resident memory no higher than today. If (a) or (b) fails, the Rust question closes for a
year with the numbers attached. If (c) fails, there is no oracle even for the most favourable
component, and therefore none for a core.

**Track C — falsifying Flutter. Effort S.** One Flutter desktop page: a virtualised 100,000-line
monospace diff viewer with text selection, search and a gutter. Not an application — a spike, on
Linux and macOS. **Thresholds, all four required:** open under 500 ms; 60 fps sustained scroll with
selection and search working; a screen reader reads the commit list and the diff; no renderer
regression reproduced on the target GPUs. Any failure removes Flutter from the desktop plan.

The spike settles the stack question and nothing else. It does not unblock reftable, SHA-256,
partial clone or sparse-index in any outcome, and its write-up must say so explicitly.

## Revisit criteria

**Toward "yes, Rust" (and still not Flutter).**
Track B passes all four thresholds — then the graph moves to Rust as a PyO3 module under an
unmodified Qt UI, and nothing else moves. Or: a second funded maintainer appears, the only criterion
that matters for any plan longer than a year; today one author holds all 161 commits. Or: gitoxide
ships push, rebase and reftable and promotes the core crates past initial development — today
`gix-protocol/src` has no push module, `gix-rebase` is `0.0.0` with a one-line `lib.rs`, and no
`gix-reftable` crate exists.

**Toward "yes, Flutter."**
The accessibility defects that make the toolkit unusable with a screen reader on Linux are closed
and shipped on stable; someone publishes a reproducible 100k-line diff benchmark for Flutter
desktop; and a serious Git client in Flutter acquires real traction. All three, not one.

**Toward "no, never" — in which case this plan gets shorter, not longer.**
libgit2 releases reftable and pygit2 exposes it: the implementation already exists in libgit2 `main`
(fact 3), so what is missing is a release, not code, and its arrival removes the last serious
technical argument for a new core. Or: the licence gate closes negative — a request to the upstream
copyright holder for a relicensable derivative is refused — closing native mobile whatever the
toolkit.

**Toward "this ADR is also wrong."**
Two consecutive quarters with no visible release: then the plan, whatever it is, has eaten the
product. Or: the first rebase onto an upstream release costs more than a few days, at which point
"assumed fork versus contribution" becomes an explicit decision rather than something discovered.
161 commits are rebasable today; several hundred will not be.

**Not a revisit criterion:** someone else shipping a Rust + Flutter Git client with traction. If the
thesis is demonstrated, it will be demonstrated on someone else's budget, and a protocol boundary
lets this project consume such a client rather than race it.
