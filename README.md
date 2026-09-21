# GitFourchette <a href="https://flathub.org/apps/org.gitfourchette.gitfourchette"><img height=42 alt="Get it on Flathub" src="https://flathub.org/api/badge?svg&locale=en" align=right><img src="gitfourchette/assets/icons/gitfourchette.png" alt="GitFourchette" height=42 align=right></a>

The comfortable Git UI for Linux.

- A comfortable way to explore and understand your Git repositories
- Powerful tools to stage code, create commits, and manage branches
- Snappy and intuitive Qt UI designed to fit in snugly with KDE Plasma

Learn more on GitFourchette’s homepage at [gitfourchette.org](https://gitfourchette.org).

![Screenshot of GitFourchette running under KDE Plasma 6](https://gitfourchette.org/_static/appstream/packshot-shadow-light.png)

## File tree

The file panels show paths as a collapsible directory tree by default. Choose
**File display** in Settings to switch between tree and flat list view; the
choice applies to Unstaged, Staged, and commit changes. Selecting a file in
either view still opens its diff. Folder rows only expand or collapse; file
actions apply to files.

## Reuse a commit summary

The commit and amend dialogs offer an editable drop-down of recent commit
summaries from the current repository. Pick an earlier summary and edit it, or
type a new one. The list contains up to 10 distinct summaries by default;
change **Recent commit messages** in preferences to adjust the limit (0 hides
the suggestions).

## Ask AI about commits

Select one or more commits and right-click **Ask AI…** (the first menu item).
It is enabled when `codex` or `claude` is available on your `PATH`. Sign in to
the CLI beforehand; GitFourchette uses its existing authentication.

Choose Codex or Claude and ask questions about the selected commits. The chat
includes their commit messages and patches, and keeps previous questions and
answers while the dialog is open. It starts with the CLI's configured default
model. Use `/model` to choose a model, `/model MODEL_NAME` to enter one, or
`/model default` to restore the CLI default. The last provider and model choice
are remembered. Send with **Ctrl+Enter**, and use **Stop** to cancel a request.

Five preset buttons prepare editable prompts: **Code review**, **Find bugs**,
**Performance**, **Security**, and **Summary**. You can also send `/review`,
`/bugs`, `/performance`, `/security`, or `/summary`, optionally followed by
additional instructions.

For questions such as “What did Alice do in the last two days?”, change the
chat scope to **Developer activity**, choose an author (or type part of their
name/email), set **Last 2 days**, and click **Load commits**. Review the matching
commits, then use a preset or ask your own question. The search uses commit dates
across local and remote-tracking branches already present in the repository;
it does not fetch. Changing scope, author, or period starts a new conversation.

You can also right-click a local or remote branch to open **Ask AI about branch…**
or any of the five presets directly. Select a base branch and **Load branch**:
the review uses the aggregate changes from the common ancestor to the selected
branch tip, without checking out either branch. Changing the base starts a new chat.

Choose the **Response language** (Romanian by default; custom languages are also
accepted). This preference is remembered and applies to all presets and questions.
**Include project rules and skills** adds `AGENTS.md`, `AGENTS.override.md`,
`CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md`, Claude/Cursor rules, and
`SKILL.md` files under `.claude/skills`, `.agents/skills`, and `.codex/skills`.
Rules in affected subdirectories are included too. Tracked guidance is read from
the reviewed revision; additional local guidance is labeled separately. **View
rules** shows the included text and any files omitted due to size limits. Rules
are used as review criteria; skill scripts are not automatically executed.

By default the assistant only reads: Codex runs in its read-only sandbox, and
Claude is given read-only file tools. Tick **Let it change files** to also let it
edit files in the working directory when you ask it to. Even then it never
commits, stages or pushes—whatever it changes shows up as your uncommitted work,
to keep or throw away. Large diffs are capped at 180 KB and marked as truncated.
No requests are sent until you submit a question. Codex integration uses its
documented
[non-interactive JSONL interface](https://learn.chatgpt.com/docs/non-interactive-mode).

## Drag a branch onto another

Drag a branch by its chip in the history, or by its row in the sidebar, and
drop it on any other branch or commit. The row you are over is outlined and
the status line names both ends of the gesture.

The drop opens a menu at the pointer instead of deciding for you: **Merge**
the dragged branch into the one you dropped on, **Cherry-pick** its tip,
**Reset** the branch you dropped on to it, **Fast-forward** it, or start a
**New branch** at that commit. Operations that don't apply to these two refs
stay in the menu, disabled, and their tooltip says why — a branch that isn't
checked out can't be reset or cherry-picked onto, a branch that doesn't track
the dragged remote branch can't be fast-forwarded.

The target is the branch of the row you drop on, or the commit itself if the
row carries none — a branch you have hidden draws no chip, so it is never the
target. Dropping a branch on itself does nothing. Drags cross between the two
views: a chip can be dropped in the sidebar and a sidebar branch in the
history.

## Workspaces

A workspace is a named set of repositories—**Work**, **Home**, **Client A**. Use
the **Workspace** menu to create, edit, delete or switch between them; switching
closes the current tabs and reopens the workspace's repositories. **Home** is the
empty workspace: it shows the repository browser instead of tabs. Workspaces also
appear in Quick Launch, so you can jump to one by typing its name.

## Worktrees

A worktree checks out another branch of the same repository in a separate folder,
so you can work on two branches at once without stashing. Right-click **Worktrees**
in the sidebar to add one, or use **New worktree** from the repository menu.
Worktrees can be locked and unlocked to protect them from removal, removed
(folder and registration together), and pruned when their folders are gone.
A worktree that another tab has open is protected from removal and pruning.

## Documentation

- [GitFourchette's website](https://gitfourchette.org) ([source code](https://github.com/jorio/gitfourchette.org))
  - [How to install or run from source](https://gitfourchette.org/install.html)
  - [User’s Guide](https://gitfourchette.org/guide)
  - [Limitations](https://gitfourchette.org/limitations.html)
- [Changelog](CHANGELOG.md)
- [Project documentation](docs/) — architecture, roadmap and design decisions
  for this fork
- [Localization guide](https://gitfourchette.org/localization.html)

## Install

- **Recommended: Get the [Flatpak](https://flathub.org/apps/org.gitfourchette.gitfourchette):**
   ```sh
   flatpak install flathub org.gitfourchette.gitfourchette
   ```

- Or, get a standalone AppImage from the [releases](https://github.com/jorio/gitfourchette/releases).

- Or, see [how to install or run from source](https://gitfourchette.org/install.html).

## About the project

I started out writing GitFourchette in my spare time to scratch my itch for a Git UI I’d feel cozy in. After plenty of “dogfooding it” to develop my other projects, I’m finally taking the plunge and releasing it publicly—maybe it’ll become your favorite Git client too.

## Translations welcome

Feel free to [localize GitFourchette for your language on Weblate](https://hosted.weblate.org/projects/gitfourchette/gitfourchette)—it's quick and easy, no need to set up any development tools. See also our [localization guide](https://gitfourchette.org/localization.html).

## Donate 🩷

GitFourchette is free—both as in beer and as in freedom. But if it helped you get work done, feel free to [buy me a coffee](https://ko-fi.com/jorio)! Any contribution will encourage the continuation of the project. Thank you!

## License

GitFourchette © 2026 Iliyas Jorio.
Distributed under the terms of the [GNU General Public License v3](LICENSE).
