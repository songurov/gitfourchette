# ADR 0004 — Relationship with upstream

An architecture decision record for anyone deciding whether a change belongs in this fork or in
`jorio/gitfourchette`: maintainers, contributors sizing a change, and reviewers of any proposal to
rename, relicense or detach the project. It records what this fork is today, what goes back
upstream, what does not, and the point at which the arrangement is reconsidered.

## Status

Accepted. Scope: the relationship between this repository and upstream. It decides no feature and
no sequencing (see [roadmap](../roadmap.md)); the stack question is settled in
[ADR 0001](0001-desktop-stack.md). Ideas rejected here are recorded with their evidence in
[rejected decisions](../decisions-rejected.md). Effort sizes: **S** ≤ 3 days, **M** = 1–2 weeks.
No calendar commitments are made.

## Context

### What this fork is

Measured on this working tree on 2026-09-20:

| Fact | Value | How it was measured |
|---|---|---|
| Remotes | `origin` = songurov/gitfourchette, `upstream` = jorio/gitfourchette, push **DISABLED** | `git remote -v` |
| Fork point | `master` = `origin/master` = `upstream/master` = `5a019e8e`, bit-identical | `git rev-parse master origin/master upstream/master` |
| Own work | 161 commits on `feature/workspaces`, 0 behind upstream; 11 more on the local-only `release/songurov-edition` | `git rev-list --left-right --count upstream/master...feature/workspaces`; `git rev-list --count feature/workspaces..release/songurov-edition` |
| Spread | 4 days: 12 / 32 / 78 / 39 on 17–20 Sep 2026 | `git log --format=%ad --date=short upstream/master..feature/workspaces \| sort \| uniq -c` |
| Authors | 1 | `git log --format='%an' upstream/master..feature/workspaces \| sort -u` |
| Own tags | 0 of 18; every tag is an ancestor of `upstream/master` | `git tag`; `git merge-base --is-ancestor <tag> upstream/master` per tag |
| Upstream activity | 75 commits in 6 months, 574 in 12; last commit 2026-08-22 | `git rev-list --count --since='6 months ago' upstream/master` |
| Licence | GPL-3.0 (`LICENSE` at the root) | `README.md:129-132` |

Two consequences follow directly. First, **nothing has ever shipped from this fork** — no tag, no
release, and `master` still points at upstream's commit. Second, **upstream is alive**: a
maintainer landing 75 commits in six months is one whose tree will move under this branch.

### What diverges, and where

`git diff --shortstat upstream/master..feature/workspaces` reports 272 files changed, 56,612
insertions and 8,757 deletions. By status (`git diff --name-status`): 124 added, 144 modified,
3 deleted, 1 renamed.

The 144 modified files are the bulk of the rebase exposure — 3 deletions and 1 rename, all icons,
are the rest. Three numbers size it:

- **78 of those 144** were also touched upstream within the last six months.
- **61 of upstream's 75** commits in that window touch at least one of them — 81%.
- **137 of this fork's 161** commits touch at least one file that exists at `upstream/master`;
  only 24 are confined to files the fork created.

Upstream's tree has six root directories — `.github`, `.idea`, `.vscode`, `gitfourchette`, `pkg`,
`test` — and has never had a `docs/` directory
(`git log --all --diff-filter=A -- 'docs/*'` returns nothing).

### What upstream owns

269 files outside `docs/` carry a `Copyright (C) … Iliyas Jorio` header, 205 of them among the 238
Python files under `gitfourchette/`. **No file carries a Songurov copyright header.** The name
appears in five files, none of them as a copyright claim: a credits entry
(`gitfourchette/assets/lang/credits.json:45`), a contributor line
(`gitfourchette/assets/whatsnew.json:21`), two tests (`test/test_credits.py:21` and
`test/test_graphview.py:966`), and a code-signing identity in `build-app.sh:18`.

Application identity is likewise untouched: `git diff upstream/master..feature/workspaces --
gitfourchette/appconsts.py` is **empty**, so `APP_VERSION = "1.11.0"` and
`APP_IDENTIFIER = "org.gitfourchette.gitfourchette"` are upstream's; `pkg/` — which holds
`pkg/flatpak/org.gitfourchette.gitfourchette.{png,desktop,metainfo.xml}` — is unchanged; and
`forms/aboutdialog.py:24` still reads `DONATE_URL = "https://ko-fi.com/jorio"`. What *has* diverged
visually is the glyph set: the fork touches 99 paths under `gitfourchette/assets/icons/` — 62
added, 33 of upstream's 121 icons modified, 3 deleted, 1 renamed.

## Decision

**1. Stay synchronized with upstream for as long as synchronizing is cheap.** The branch is
currently based on upstream's tip, so the debt today is zero. It is re-measured at every upstream
push, not assumed.

**2. Send correctness fixes that carry no product opinion upstream as pull requests.** Each of the
following was re-checked against `upstream/master`, not against a report:

| Fix | Anchor here | Anchor upstream | Why it is opinion-free |
|---|---|---|---|
| `parseGitDiffRawZ` uses `match.end()` with no `None` guard | `gitdriver/parsers.py:201-202` | same lines | Any line the regex misses becomes an `AttributeError`, not an error message |
| Annotated tags raise `NotImplementedError` | `tasks/committasks.py:509` | `:435` | The command is `git tag -m`; no UI opinion is involved |
| `git diff` is built without `--no-ext-diff` / `--no-textconv` | `gitdriver/gitdriver.py:317`, `:354` | `:292`, `:329` | A user's `diff.external` or textconv config silently corrupts machine-parsed patch output. `git grep -n no-ext-diff upstream/master -- gitfourchette/` returns nothing |
| Unbounded path lists are splatted into `argv` | `tasks/indextasks.py:77, 197, 199, 248, 376, 377, 381` | identical lines | Large selections exceed `ARG_MAX`; chunking changes no behaviour |
| `libgit2_version_at_least` has no callers | `porcelain.py:280` | `:278` | Dead code; `git grep` over `upstream/master` finds only the definition |

**Two items proposed for this list were struck after checking.** The relative-worktree-path bug
(`porcelain.py:989`, `:1024`) cannot be sent upstream: the entire worktree-reading layer is
fork-authored. `git ls-tree upstream/master gitfourchette/tasks/` contains no `worktreetasks.py`,
and upstream's `porcelain.py` has no `WorktreeInfo` and no `_read_worktree`. Likewise
`conflict-marker-size` versus the hardcoded `MARKER_SIZE = 7`
(`mergeview/conflictparser.py:17`): `gitfourchette/mergeview/` does not exist upstream. Both remain
fork bugs to fix here; neither is an upstream contribution. A third, making tooltips visible in
`ActionDef.makeQMenu` (here `toolbox/actiondef.py:181`, upstream `:172`), is deliberately kept off
the list — it changes visible behaviour, so it is a product opinion, not a correctness fix.

**3. The name, the application identifier, the packaging metadata and the donation link stay
upstream's, and are not touched.** Renaming was considered and rejected; the reasoning and its
evidence live in [rejected decisions](../decisions-rejected.md). It is not revisited here.

**4. Documentation is written under `docs/`.** The directory is chosen precisely because upstream
has never had one: every file added there is a pure addition at rebase time and can never conflict.
Anything that would otherwise be written into `README.md` — which upstream does own — is written
here instead and linked from there in a single line.

**5. Alternatives considered.** Detaching entirely and rebuilding the workspace layer as a separate
process next to any repository is a real option; it is recorded in
[rejected decisions](../decisions-rejected.md) and reopened only at the revisit gate below, not
here.

## Consequences

**The rebase tax grows with every large feature, and it is already concentrated.** The zones that
will pay it are the ones the worktree control centre must edit
(see [ADR 0002](0002-worktree-control-center.md)):

| File | Upstream commits, 12 mo | Upstream commits, 6 mo | Lines changed by this fork |
|---|---|---|---|
| `tasks/loadtasks.py` | 64 | 4 | 12 |
| `mainwindow.py` | 33 | 2 | 758 |
| `porcelain.py` | 33 | 2 | 419 |
| `repowidget.py` | 33 | 3 | 190 |
| `sidebar/sidebar.py` | 18 | 3 | 255 |
| `repomodel.py` | 17 | 0 | 172 |
| `sidebar/sidebarmodel.py` | 13 | 2 | 129 |
| `gitdriver/gitdriver.py` | 27 | 2 | 33 |

`reposcan.py` does not exist upstream and costs nothing. The translation catalogue is the second
payer: the fork has rewritten `assets/lang/gitfourchette.pot` and three `.po` files, and upstream
touched `assets/lang/` in 15 commits in six months.

**Accepted costs.** Every accepted upstream PR must then be un-applied locally or absorbed as a
no-op hunk. The five fixes above are all in files this fork has also modified, so they will return
as conflicts, not as clean fast-forwards — that is the price of contributing rather than diverging,
and it is accepted deliberately.

**Gained.** The fork keeps receiving upstream's bug fixes, its packaging and its CI for free, and
the GPL-3.0 obligations stay simple because nothing about authorship or identity is contested.

## Revisit criteria

This decision is reopened when any one of these is true, and not before:

- **A single sync costs more than one working day (size S).** Measured, not estimated:
  `git worktree add <tmp> -b probe/rebase feature/workspaces`, then
  `git -C <tmp> rebase upstream/master`, counting the commits that stop and the files that
  conflict. A cheap predictor can be run first:
  `git rev-list --count <old-tip>..upstream/master -- $(git diff --name-only --diff-filter=M <old-tip>..feature/workspaces)`.
  Today both are zero, because the branch already sits on upstream's tip.
- **All five pull requests above are declined or unanswered across two upstream releases.** That is
  evidence that the contribution channel is closed, which changes the arithmetic of item 2.
- **A planned feature requires restructuring a file upstream rewrites often** — the live example is
  `tasks/loadtasks.py`, 64 upstream commits in twelve months against 12 fork lines.
- **Upstream stops** — no commit for six months. The sync loop then has nothing to sync, and the
  question becomes maintainership, not branding.

## How the claims above were checked

```
git remote -v ; git rev-parse master origin/master upstream/master
git rev-list --left-right --count upstream/master...feature/workspaces          # 0 161
git log --format=%ad --date=short upstream/master..feature/workspaces | sort | uniq -c
git rev-list --count --since='6 months ago' upstream/master                     # 75
git diff --shortstat upstream/master..feature/workspaces                        # 272 files
git diff --name-status upstream/master..feature/workspaces | cut -f1 | sort | uniq -c
git ls-tree -d --name-only upstream/master                                      # no docs/
grep -rl 'Copyright (C).*Iliyas Jorio' . --exclude-dir=.git --exclude-dir=docs | wc -l   # 269
git diff upstream/master..feature/workspaces -- gitfourchette/appconsts.py      # empty
git show upstream/master:gitfourchette/tasks/committasks.py | grep -n annotated
git show upstream/master:gitfourchette/gitdriver/parsers.py | grep -n 'match.end()'
git grep -n no-ext-diff upstream/master -- gitfourchette/                       # no hits
git ls-tree upstream/master gitfourchette/tasks/                                # no worktreetasks.py
```

The per-file churn table was produced by running
`git rev-list --count --since='12 months ago' upstream/master -- <file>` and
`git diff --numstat upstream/master..feature/workspaces -- <file>` for each row.
