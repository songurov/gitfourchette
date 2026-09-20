# Git feature coverage

A maintained inventory of which Git features GitFourchette exposes, where in the code, and what is
missing. For contributors deciding what to build next, and for reviewers checking a claim about the
product. Not a user manual.

Every row was re-checked against the working tree at the time of writing (branch
`feature/workspaces`, `APP_VERSION = "1.11.0"` in `gitfourchette/appconsts.py:16`). Anchors are
`file:line` into `gitfourchette/`. Companions in this folder, maintained separately:
[roadmap](roadmap.md), [rejected decisions](decisions-rejected.md),
[ADR 0001](adr/0001-desktop-stack.md).

## How this file is maintained

Regenerate this file whenever a task is added, removed or renamed. Start from:

```sh
grep -rn "class .*(RepoTask)" gitfourchette/tasks/
```

That returned 83 direct `RepoTask` subclasses at the time of writing. Then:

1. Find the Git command behind each new task. Writes call real `git` through `flowCallGit`
   (`grep -rn flowCallGit gitfourchette/ | wc -l` → 90, of which 89 are call sites and one is
   the definition at `repotask.py:514`); reads usually go through pygit2.
2. Add or update the row, with `Exposed` set to `yes`, `partial` or `no`.
3. `partial` needs a concrete limitation in `Notes`. "No `-m`" is one; "could be better" is not.
4. Confirm every anchor with `grep -n` first. Do not copy anchors from older reports.
5. Anything deliberately not being built goes in [rejected decisions](decisions-rejected.md) with its
   reason, not here as a gap.

`Where` names the code that runs the command, not the menu item.

## Architecture in one paragraph

GitFourchette is a hybrid client. Writes and porcelain go through `git` launched as a `QProcess`
(89 `flowCallGit` call sites). Reading — graph, refs, blobs, index — goes through libgit2 via pygit2:
`porcelain.py:843` declares `class Repo(_VanillaRepository)`, 63 modules import from `porcelain`, and
the graph is walked by libgit2 (`repomodel.py:496`). That split explains most of the tables: a
command line is cheap, a repository format libgit2 cannot parse is not ours to fix.

## Local basics

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| `git status` | yes | `jumptasks.py:53-58`, `stashtasks.py:81`, `reposcan.py:183` | `--porcelain=v2 -z`; untracked files `all` in the repo view, `normal` in the scanner. Parsed by `parseGitStatus` (`gitdriver/parsers.py:77`), with `--no-optional-locks` when the index must not be written |
| `git add` | yes | `indextasks.py:77`, `:377`, `:452`, `:667` | Path list is never chunked (see ARG_MAX row) |
| Partial staging (hunks, lines) | yes | `ApplyPatch` `indextasks.py:296`, apply at `:328` | Through libgit2 `repo.apply`, not `git apply --cached`; needs `refresh_index()` first (`:326`) |
| `git reset <paths>` | yes | `indextasks.py:248` | |
| `git commit` | yes | `committasks.py:221-233` | `--gpg-sign`/`--no-gpg-sign`, `--no-verify`, `--signoff`, `--allow-empty`, `--no-edit`, `--message=`, plus `GIT_AUTHOR_*`/`GIT_COMMITTER_*` in the environment |
| `git commit --amend` | yes | `committasks.py:228`, class at `:246` | Adds `--reset-author` when needed (`:229`) |
| `git restore` | yes | `indextasks.py:376`, `:814`, `stashtasks.py:143` | Ours/theirs, and returning a file to HEAD |
| `git clean` | yes | `indextasks.py:197`, `:204`, `stashtasks.py:138` | |
| `git rm` | partial | `indextasks.py:381`, `submoduletasks.py:115` | Never `--cached` (the two `--cached` hits are `git diff`), so a tracked file cannot leave the index while staying on disk |
| `git mv` | no | — | `grep -rn '"mv"' gitfourchette/` → 0 |
| `git update-index` | no | — | greps to 0; no "temporarily ignore this file" |
| `git diff` (display) | yes | `buildDiffCommand` `gitdriver.py:353-397`, 8 call sites | Omits `--no-ext-diff`, `--no-textconv`, `--no-color`; those appear only on the assistant path (`diffarea.py:891`, `aichatdialog.py:906`, `:909`, `:912`). A user's `diff.external` changes what the diff panes show |
| `git apply` (patch file) | yes | built at `indextasks.py:708-713`, dry run `:716`, real `:739` | `--numstat -z --check` and a file list before applying. Good pattern |
| `git init` | yes | `newrepotasks.py:61` | No `--initial-branch` |
| `git clone` | partial | `clonedialog.py:315-325` | Has `--progress`, `--recurse-submodules`, `--shallow-submodules`, `--depth`, `--no-single-branch --no-tags`. No `--filter`, `--branch`, `--bare`, `--mirror`, `--bundle-uri` |

## Branching

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| Create / rename / delete branch | yes | `branchtasks.py:266`, `:89`, `:199` | Deletion via libgit2 `delete_local_branch` (`:220`) |
| `git checkout <branch>` | yes | `branchtasks.py:79-84` | `--progress --no-guess [--recurse-submodules]` |
| `git checkout --detach` | yes | `committasks.py:446-451` | |
| `git checkout -m` (dirty switch) | no | `branchtasks.py:79-84` | Built without `-m`; `grep -rn '"-m"' gitfourchette/` returns three hits, all `python -m` in `exttools/toolcommands.py` |
| Upstream / tracking | yes | `branchtasks.py:395`, `pushdialog.py:369` | Ahead/behind from `for-each-ref --format=%(refname:short) %(upstream:track)` (`loadtasks.py:91`, `jumptasks.py:814`) |
| `git merge` | partial | `branchtasks.py:649-657`, fast-forward `:520`, Git Flow `gitflowtasks.py:164` | `--no-commit --no-edit --progress --verbose [--no-ff\|--ff-only]`. No `--squash` (greps to 0), no `-s`, no `-X ours/theirs`, no message control |
| `merge`/`cherry-pick`/`revert --abort` | yes | `indextasks.py:936`, `:941`, `:946` | `AbortMerge` picks the command from `repo.state()` |
| `--continue` on any operation | no | — | One hit repo-wide: the sample user command at `trtables.py:719` |
| `git rebase`, any form | no | — | `grep -rn '"rebase"'` → one comment at `gitflowtasks.py:379`; `grep -rn 'class .*Rebase'` → 0. An in-progress rebase is recognised (`gitflowtasks.py:64`) and blocks other work |
| `git cherry-pick` | partial | `committasks.py:631`, signature at `:623` | One commit, `--no-commit`. No range, no `-m`, no `--continue/--skip` |
| `git revert` | partial | `committasks.py:577`, signature at `:566` | No `-m`, so a merge commit cannot be reverted from the UI |
| `git reset --soft/--mixed/--hard` | yes | `branchtasks.py:437-441` | Optional `--recurse-submodules`; no `--keep` |
| `git reflog` | no | — | `grep -rin reflog gitfourchette/` → 0 |
| Recovering a lost commit | partial | `RecallCommit` `branchtasks.py:675` | Asks the user to type the hash — exactly what the reflog would supply |

## History

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| Commit graph | yes | `repomodel.py:496`, renderer in `graph/` | libgit2 walker |
| History filtering | partial | `CommitQuery.matchesCommit` `commitquery.py:143` | Client-side over commits already walked: author time, author name/email, message substring. No pathspec, regex or pickaxe |
| `git log -- <path>` | partial | `misctasks.py:464-471` | `--icase-pathspecs log --all --format=%H --show-pulls -- <pathspec>`. Marks commits; does not narrow the graph |
| `git blame` | yes | `blametasks.py:397-403` | `blame --porcelain <rev> -S <revs-file> -- <path>`; rev list from `log --show-pulls --parents --topo-order` (`:141`), upper bound from `merge-base --is-ancestor` (`:71-76`). No `--diff-algorithm` (greps to 0) |
| `git log -L` | no | — | greps to 0; available in the installed git |
| `git show` | partial | `indextasks.py:485` | One use: `show --cc --name-only --format=`, split on newlines, with no `-z` and no `core.quotepath` anywhere (greps to 0). Verified: `git show --name-only --format= HEAD` prints `"\304\203sta.txt"` by default and `ăsta.txt` under `-c core.quotepath=false` |
| `git bisect` | no | — | Only the state is displayed (`trtables.py:283`, `gitflowtasks.py:69-70`) |
| `git notes` | no | — | All ten case-insensitive hits are the English word |
| `git describe` | no | — | Three hits, all prose. No "which release contains this commit" badge |
| `git range-diff` | no | — | greps to 0 |
| `git merge-tree` | no | — | greps to 0. Would be the honest engine for a merge preview |
| `git last-modified` | no | — | greps to 0; present in the installed git |
| `git format-patch` / `git am` | no | — | All five export paths (`exporttasks.py:50`, `:74`, `:86`, `:98`, `:126`) call `buildDiffCommand`, so exported patches carry no mailbox header |

## Remote

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| `git fetch` | yes | `nettasks.py:174-180`, `:204-210`, `:249` | `--prune --progress [--porcelain --verbose] [--all \| --no-all -- <remote>]`, with a real fallback below git 2.41 (`:183`) |
| `git push` | yes | `pushdialog.py:364-372`, `nettasks.py:82`, `:147`, `:350` | The dialog shows the exact command first. Force uses `--force-with-lease`; a bare `--force` never reaches `push` |
| `push --delete` | yes | `nettasks.py:82-89` | |
| `push --atomic` | yes | `nettasks.py:147-155`, `:350` | |
| `git pull` | partial | `nettasks.py:314-319` | `git pull` is never invoked; the action is fetch plus merge. `pull.ff` is honoured, `pull.rebase` is never read, so `pull.rebase=true` behaves differently here than in a terminal |
| `git remote` add/rename/set-url/remove | yes | `remotetasks.py:44`, `:87-92`, `:95-100`, `:119-123` | |
| Git remote groups on push | no | `nettasks.py:336-350` | `PushRefspecs` accepts `"*"` and loops over `self.repo.remotes` in Python (`:349`), one `git push` per remote; Git's own remote groups are not used |
| Credentials | partial | `forms/askpassdialog.py` | `git credential` is never called; the scanner correctly disables helpers for unattended runs (`reposcan.py:337`) |
| Network progress | yes | `parseProgress` `gitdriver.py:207` | Parses the `(n/m)` fraction from stderr |

## Advanced and history rewriting

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| Create stash | yes | `stashtasks.py:125` → `porcelain.py:1478-1502` | libgit2 `self.stash(...)` at `porcelain.py:1493`; the workdir is then cleaned with real `git` so smudge filters apply (`stashtasks.py:138`, `:143`) |
| Stash pop / apply | yes | `stashtasks.py:189` | CLI, with the index resolved from the stash commit id (`find_stash_index`, `porcelain.py:1504`) |
| Stash drop | yes | `stashtasks.py:231` | |
| `--index` on pop, `stash.index` | no | — | Never passed; the config key exists in the installed git |
| `worktree add/remove/lock/unlock/prune` | yes | `worktreetasks.py:76`, `:118`, `:131`, `:154`, `:169`, `:202` | Five task classes on a shared `_WorktreeTask` base (`:24`); broader coverage than most competitors |
| `git worktree list --porcelain` | no | `porcelain.py:950-1025` | Metadata is read by hand from `$GIT_COMMON_DIR/worktrees`, including `HEAD` as plain text (`:998`). Verified: under reftable that file reads `ref: refs/heads/.invalid` while `git symbolic-ref HEAD` reports `refs/heads/main`. Separately, `_dirname(_normpath(dotgit))` at `:989` never joins a relative `gitdir` pointer against the common dir |
| `worktree move` / `repair` | no | — | greps to 0; a manually moved worktree stays broken |
| `submodule add/deinit/update/absorbgitdirs` | yes | `submoduletasks.py:77`, `:80`, `:112`, `nettasks.py:325`, `:332`, `indextasks.py:205` | |
| `submodule sync/set-url/set-branch/foreach` | no | — | Each greps to 0. No resync when a URL changes in `.gitmodules` |
| Git Flow | yes | `gitflowtasks.py`, 10 classes, 574 lines | Real preconditions: `requireNoOperationInProgress` (`:46`), `requireNotBehindRemote` (`:102`), `flowRequireCleanTree` (`:120-129`) |
| `git archive` / `git bundle` | no | — | `grep -rn '"archive"' gitfourchette/` → 0 (the only `archive` string is a URL in `theme.qss`); every `bundle` hit is a macOS app bundle or an unrelated link bundle |
| `git replay` / `git backfill` / `git rerere` | no | — | Each greps to 0 |
| Editing Git config from the UI | partial | `misctasks.py:46-53` | Writes exactly two keys, `user.name` and `user.email`, through `repo.config`. Everything else opens `.git/config` in a text editor (`repowidget.py:572-574`) |

## Monorepo and performance

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| commit-graph | no | — | greps to 0. Never written, never refreshed. See "Free performance wins" for what this is actually worth |
| sparse-checkout / sparse-index | no | — | greps to 0. libgit2 opens such a repo but raises on the index, which is touched at `indextasks.py:285`, `:456`, `:927`, `stashtasks.py:192`, `porcelain.py:1035` |
| FSMonitor | no (disabled) | `reposcan.py:174-179` | The only mention sets `core.fsmonitor=false` for the unattended scanner, correctly and with a documented reason. Never enabled for the open repository |
| Partial clone / promisor | no | — | greps to 0. As git 2.54 writes it, libgit2 opens the repo and reads the index, then raises `KeyError` on any blob left behind the promisor; only a config carrying `extensions.partialClone` is refused at open. Nothing here fetches on demand |
| `git maintenance` / `gc` / `fsck` / `repack` | no | — | `gc`, `fsck` and `repack` grep to 0; the only `maintenance` hit is an unrelated UI string (`forms/analysisview.py:421`). The only measurement is `count-objects -v` (`reposcan.py:258`), used to show a size |
| `cat-file --batch` | partial | `indextasks.py:852` | One one-shot invocation, not a persistent `--batch` process |
| `git repo info` / `git refs list` | no | — | Both grep to 0, and both exist in the installed git |
| Path-list chunking (ARG_MAX) | no | `indextasks.py:77`, `:197`, `:248`, `:376-381` | `grep -rinE 'chunk\|ARG_MAX\|xargs' gitfourchette/tasks/` → 0 |

## Security and signing

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| Sign a commit (GPG) | yes | `committasks.py:224-225`; config read at `:185-190` | Reads `commit.gpgSign` and `user.signingKey` |
| Verify a commit signature | yes | `misctasks.py:212`, `:347` | `verify-commit --raw` |
| `--signoff` | yes | `committasks.py:227` | |
| Annotated tags | no | `committasks.py:509` | `raise NotImplementedError("annotated tags not supported yet")`; only lightweight tags are created (`:512-517`). Git Flow already does it right: `tag --annotate --message=` at `gitflowtasks.py:498` |
| Signed tags (`tag -s`), `verify-tag` | no | — | Both grep to 0 |

## LFS, hooks, conflicts

| Feature | Exposed | Where | Notes |
|---|---|---|---|
| Hooks | yes, implicitly | — | They run because commits go through real `git`; `--no-verify` is a UI toggle (`diffarea.py:484-487`, `committasks.py:226`) |
| Hook detection | partial | `committasks.py:193-196` | Looks for `hooks/pre-commit` and `hooks/commit-msg` as files under `$GIT_DIR`. `core.hooksPath` is never read (greps to 0), so relocated hooks are invisible to this check |
| LFS pointer reading | yes | `gitdriver/lfspointer.py`, `jumptasks.py:78` | `check-attr -z filter`, with a correct fallback when `.gitattributes` has unstaged changes |
| LFS smudge on demand | yes | `loadtasks.py:484` | |
| LFS real diff, not pointer diff | yes | `buildDiffCommandLFS` `gitdriver.py:399-422` | Passes an empty `--git-dir=` so LFS filters do not apply |
| `git lfs track/untrack/push/pull/status/locks/migrate` | no | — | Only two `git lfs` invocations exist: `loadtasks.py:484` and `gitdriver.py:133` |
| Own conflict editor | yes | `mergeview/` (`mergeeditor.py` 414 lines, `conflictparser.py` 177, `mergeinspector.py` 79); tasks at `indextasks.py:349`, `:419`, `:468`, `:562` | Work in progress on this branch |
| `conflict-marker-size` from `.gitattributes` | no | `mergeview/conflictparser.py:17-21` | `MARKER_SIZE = 7` is hardcoded and used as a fixed offset at `:138`, `:147`, `:149` |
| `git merge-file --diff3` | yes | `indextasks.py:520` | |

## Repository formats libgit2 cannot open

The hardest ceiling in the product, and not one we can raise. Verified against pygit2 1.20.1 /
libgit2 1.9.7 by creating throwaway repositories and calling `pygit2.Repository(path)`:

| Repository | `pygit2.Repository()` | Installed `git` 2.54.0 |
|---|---|---|
| `git init --ref-format=reftable` | `GitError: unsupported extension name extensions.refstorage` | works |
| `git init --object-format=sha256` | `InvalidError: unknown object format 'sha256'` | works |
| `core.repositoryformatversion=1` + `extensions.partialClone=origin` (set by hand) | `GitError: unsupported extension name extensions.partialclone` | works |
| `sparse-checkout init --sparse-index` | opens, then `GitError: unsupported mandatory extension: 'sdir'` on `repo.index` | works |
| `clone --filter=blob:none` as git 2.54 writes it (`remote.<name>.promisor`, no `extensions` key) | opens, index reads; `KeyError` on a blob left behind the promisor | works |

Read the last two rows together before quoting either. Current git records a partial clone as
`remote.<name>.promisor` and does not write `extensions.partialClone`, so a partial clone made today
**does** open under libgit2 — only a config carrying that extension key is refused. What breaks is
the object lookup afterwards, not the open.

The repository is opened at `loadtasks.py:75`, so the raw libgit2 message reaches the user. Meanwhile
the Home scanner runs on the CLI and lists such repositories happily: its command from
`reposcan.py:183`, run against the reftable repository, returned `# branch.oid (initial)` and
`# branch.head main`. The two halves of the application disagree about which repositories exist. No
test covers these formats: `grep -rin "reftable|sha256|sparse|partialclone" test/` matches only SSH
fingerprints, an LFS object hash and a GPG key-preference line (`test/data/gpgkeys/alice.txt`).

## Git version floor and ceiling

No minimum Git version is declared or checked. `pyproject.toml` pins `requires-python >= 3.12` and
`pygit2 >= 1.14.1` and says nothing about `git`; `GitDriver.validateGitPath` (`gitdriver.py:76-92`)
accepts any binary whose `--version` output starts with `git version`.

The real floor comes from options passed unconditionally: `-c core.abbrev=no` at five sites
(`committasks.py:222`, `misctasks.py:465`, `gitdriver.py:324`, `:361`, `:413`) requires Git 2.31.
Below that, every diff and commit fails behind a generic dialog.

The ceiling is self-imposed: three version gates in the whole codebase — `gitdriver.py:150`
(`>= (2, 41)`, guarding `fetch --porcelain`, with a real degraded path at `nettasks.py:183`),
`gitdriver.py:163` (`>= (2, 39)`), and `diffview/specialdiff.py:148` (`< (2, 37)`, the wording of a
CRLF warning). Nothing newer than 2.41 is used anywhere.

## Biggest gaps

Ordered by how often a working developer hits them. Effort is a size (S/M/L/XL), not a date.

| # | Gap | Evidence | Effort |
|---|---|---|---|
| 1 | No rebase at all | `grep '"rebase"'` → one comment; `grep 'class .*Rebase'` → 0 | L for plain rebase plus `--continue/--abort/--skip` on existing `RepoTask` plumbing; the conflict UI already exists in `mergeview/`. Interactive plan editing is a separate, larger bet |
| 2 | No reflog: no safety net after `reset --hard`, a deleted branch or a bad amend | `grep -rin reflog` → 0; `RecallCommit` (`branchtasks.py:675`) asks for the hash | S. Read-only, parseable, fits the existing graph UI. Best value per unit of effort here |
| 3 | History filtering is message/author/date only, and client-side | `commitquery.py:143` | M. Pickaxe and `--grep` are cheap on the CLI, but the result must narrow the graph, which touches `repomodel`. Warning: `blametasks.py:401` already passes `-S`, where it means `git blame`'s revs-file, not the pickaxe |
| 4 | Cherry-pick and revert take one commit, no `-m`, no `--continue` | `committasks.py:566`, `:623` take a single `Oid`; `:577`, `:631` pass no `-m` | S-M. A merge commit currently cannot be reverted from the UI |
| 5 | Annotated tags raise `NotImplementedError` | `committasks.py:509` | S. The correct call already exists at `gitflowtasks.py:498` |
| 6 | Git config is barely editable: two keys | `misctasks.py:46-53`; the rest opens an editor (`repowidget.py:572-574`) | M for an editor covering the keys that change behaviour: `merge.tool`, `core.autocrlf`, `push.default`, `pull.rebase`, `diff.algorithm` |
| 7 | No declared or checked minimum Git version, although the code needs 2.31 | `gitdriver.py:76-92`; `core.abbrev=no` at five sites | S. A constant, a startup check, one line in `pyproject.toml` |
| 8 | Modern repositories fail with a raw libgit2 message, or die on first index or object access | The probes above | S for an honest message; real support is out of our hands. `git repo info --all` reports `references.format` and `object.format`, so the format is knowable before `Repo()` |
| 9 | `git merge` has no options | `branchtasks.py:649-657`; `--squash` greps to 0 | S. The command is centralised; the work is mostly dialog |
| 10 | Exported patches have no mailbox header | `exporttasks.py:50`, `:74`, `:86`, `:98`, `:126` | S. `git format-patch` has nearly the same call shape as today's `git diff` |

## Free performance wins

"Free" means the work already exists in Git. Each item carries an honest note about libgit2.

### commit-graph

Never written (greps to 0). libgit2 ships a commit-graph reader and the revwalk consumes it
(`src/libgit2/commit_graph.c`, called from `commit_list.c:184` in the libgit2 1.9.0 source tree), so
we would only need the file to exist. Two caveats, both checked:

- libgit2 opens exactly one path, `objects/info/commit-graph` (`commit_graph.c:365`); it does not
  read the split chain under `objects/info/commit-graphs/`. `git maintenance run --task=commit-graph`
  writes that split chain, so the obvious command is the wrong one for us. `git commit-graph write
  --reachable` writes the monolithic file libgit2 can use.
- At this repository's size the win is not measurable. Method: mirror-clone this repository, write
  `objects/info/commit-graph` with `git commit-graph write --reachable`, then time a pygit2 walk
  (`TOPOLOGICAL|TIME`, from HEAD, 3,005 commits — 3,023 is the count across all refs), best of five,
  with the file present and with it renamed away. Both runs came out at 21.3 ms. The win is claimed
  for larger histories and has not been measured here. Do not sell it as a speedup before measuring
  it where it shows.

Effort: S. Value: unproven at our scale.

### `git maintenance is-needed`

Never called (the only `maintenance` hit in the sources is an unrelated UI string,
`forms/analysisview.py:421`); the only repository measurement is `count-objects -v` (`reposcan.py:258`),
used to display a size. `git maintenance is-needed` exists in the installed git, exits 0 when
maintenance is recommended and 1 otherwise, and exits 0 here — enough for a repository-health
indicator that asks Git instead of guessing from loose-object counts. Honest note: nothing here
depends on libgit2, so this one is genuinely unblocked. Effort: S.

### FSMonitor for the open repository

Status refresh runs `git status --porcelain=v2 -z --untracked-files=all` (`jumptasks.py:53-58`) on
every workdir-affecting task. The only fsmonitor mention disables it (`reposcan.py:174-179`) — correct
for the scanner, where a daemon per scanned repository is not an acceptable side effect of listing
repositories. For the open repository the trade goes the other way.

Honest note: this is a Git-side daemon that libgit2 does not participate in, so everything read
through libgit2 gains nothing — only the CLI `git status` path benefits. Any implementation must
keep the scanner's `core.fsmonitor=false` intact. Effort: S-M.

### Persistent `cat-file --batch`

Today there is one one-shot invocation (`indextasks.py:852`); a long-lived `git cat-file --batch`
would serve object reads without a process per file.

Honest note, and it decides the item: blobs are already read through libgit2, which is fast and does
not fork, so the gain is not raw speed. The gain would be removing libgit2 from the object-reading
path — which is what actually blocks SHA-256 and partial-clone repositories. That makes this an
architectural decision, not an optimisation, and it should be argued as one. Effort: M, and larger
if treated as the first step away from libgit2.

## Out of scope for this file

Items considered and deliberately not planned — writing our own reftable parser, replacing the
Qt/pygit2 stack, worktree states Git cannot confirm — are recorded with their reasons in
[rejected decisions](decisions-rejected.md). They are not gaps and must not reappear above.
