# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Translated tables of enums, exception names, preference keys.
"""

from __future__ import annotations

import os
import re
import textwrap
from enum import Enum
from collections.abc import Callable

from gitfourchette.appconsts import *
from gitfourchette.localization import *

_userCommandsGuideUrl = "https://gitfourchette.org/guide/commands"


def retranslate(newLanguageCode: str):
    """Flush cached translations."""
    # Bump table cookie value, forcing _getTable to regenerate all tables.
    global _tableCookieValue
    _tableCookieValue = newLanguageCode


def enum(enumValue: Enum) -> str:
    """Translate an enum value."""
    table = _getTable(_enumTable)
    try:
        return table[type(enumValue)][enumValue]
    except KeyError:
        return enumValue.name


def exceptionName(exc: BaseException) -> str:
    """Translate an exception name."""
    table = _getTable(_exceptionNameTable)
    name = type(exc).__name__
    return table.get(name, name)


def prefKey(key: str, default: str | None = None) -> str:
    """Translate a PrefsFile field."""
    table = _getTable(_prefKeyTable)
    try:
        return table[key]
    except KeyError:
        return str(key) if default is None else default


def prefKeyNoDefault(key: str) -> str:
    """Translate a PrefsFile field (return empty string if no translation
    available)."""
    return prefKey(key, "")


# -------------------------------------------------------------------------
# Table caching
# -------------------------------------------------------------------------

_tableAttr = "_cachedLocalizationTable"
_tableCookieKey = "_TrTablesLanguageCheck"
_tableCookieValue = ""


def _getTable[T: dict](initializer: Callable[[], T]) -> T:
    # See if we've stashed a table in this initializer's attributes previously
    table: T | None = getattr(initializer, _tableAttr, None)

    # No table, or table cookie is stale?
    if table is None or table[_tableCookieKey] != _tableCookieValue:
        # Generate the table
        table = initializer()

        # Set fresh cookie
        table[_tableCookieKey] = _tableCookieValue

        # Stash the table inside the initializer
        setattr(initializer, _tableAttr, table)

    assert table is not None
    return table


# -------------------------------------------------------------------------
# Table initializers
# -------------------------------------------------------------------------

def _exceptionNameTable() -> dict[str, str]:
    return {
        "ConnectionRefusedError": _("Connection refused"),
        "FileNotFoundError": _("File not found"),
        "GitError": _("Git error"),
        "InterruptedError": _("Operation interrupted"),
        "NotImplementedError": _("Unsupported feature"),
        "PermissionError": _("Permission denied"),
    }


def _enumTable() -> dict[type[Enum], dict[Enum, str]]:
    from gitfourchette.gitdriver import GitConflictSides, GitStatus
    from gitfourchette.nav import NavContext
    from gitfourchette.porcelain import FileMode, NameValidationError, RepositoryState
    from gitfourchette.toolbox import toLengthVariants
    from gitfourchette.sidebar.sidebarmodel import SidebarItem
    from gitfourchette.settings import (
        WhitespaceMode,
        CommitFormPlacement,
        FileListClick,
        GraphLaneWidth,
        GraphPreset,
        GraphRefBoxWidth,
        GraphRowHeight,
        GraphRowLayout,
        QtApiNames,
        RefSort,
        TabBarClick,
    )
    from gitfourchette.themes import ThemeAccent, ThemeVariant
    from gitfourchette.toolbox import PatchPurpose, PathDisplayStyle, AuthorDisplayStyle
    from gitfourchette.repomodel import GpgStatus

    NVERule = NameValidationError.Rule

    table: dict[type[Enum], dict[Enum, str]] = {}

    table[AuthorDisplayStyle] = {
        AuthorDisplayStyle.FullName: _("Full name"),
        AuthorDisplayStyle.FirstName: _("First name"),
        AuthorDisplayStyle.LastName: _("Last name"),
        AuthorDisplayStyle.Initials: _("Initials"),
        AuthorDisplayStyle.FullEmail: _("Full email"),
        AuthorDisplayStyle.EmailUserName: _("Abbreviated email"),
    }

    table[FileListClick] = {
        FileListClick.Nothing: _("Do nothing"),
        FileListClick.Stage: _("Stage/unstage file"),
        FileListClick.Blame: _("Blame file"),
        FileListClick.Edit: _("Open file in external editor"),
        FileListClick.DiffTool: _("Open file in external diff tool"),
        FileListClick.Folder: _("Show file in folder"),
    }

    table[FileMode] = {
        FileMode.UNREADABLE: _p("FileMode", "deleted"),
        FileMode.BLOB: _p("FileMode", "regular file"),
        FileMode.BLOB_EXECUTABLE: _p("FileMode", "executable file"),
        FileMode.LINK: _p("FileMode", "symbolic link"),
        FileMode.TREE: _p("FileMode", "subtree"),
        FileMode.COMMIT: _p("FileMode", "subtree commit"),
    }

    table[GitConflictSides] = {
        GitConflictSides.BothDeleted: _p("ConflictSides", "deleted by both sides"),
        GitConflictSides.AddedByUs: _p("ConflictSides", "added by us"),
        GitConflictSides.DeletedByThem: _p("ConflictSides", "deleted by them"),
        GitConflictSides.AddedByThem: _p("ConflictSides", "added by them"),
        GitConflictSides.DeletedByUs: _p("ConflictSides", "deleted by us"),
        GitConflictSides.BothAdded: _p("ConflictSides", "added by both sides"),
        GitConflictSides.BothModified: _p("ConflictSides", "modified by both sides"),
    }

    table[GitStatus] = {
        GitStatus.Added: _p("FileStatus", "added"),
        GitStatus.Copied: _p("FileStatus", "copied"),
        GitStatus.Deleted: _p("FileStatus", "deleted"),
        GitStatus.Ignored: _p("FileStatus", "ignored"),
        GitStatus.Modified: _p("FileStatus", "modified"),
        GitStatus.Renamed: _p("FileStatus", "renamed"),
        GitStatus.TypeChanged: _p("FileStatus", "file type changed"),
        GitStatus.Unmerged: _p("FileStatus", "merge conflict"),
        GitStatus.Unknown: _p("FileStatus", "unreadable"),
        GitStatus.Untracked: _p("FileStatus", "untracked"),
    }

    table[GpgStatus] = {
        GpgStatus.Unsigned: _("Not signed"),
        GpgStatus.Pending: _("Signature not verified yet"),
        GpgStatus.CantCheck: _("Unable to verify signature"),
        GpgStatus.MissingKey: _("Can’t verify signature; Key not in your keyring"),
        GpgStatus.GoodTrusted: _("Good signature; Key trusted"),
        GpgStatus.GoodUntrusted: _("Good signature; Key not fully trusted"),
        GpgStatus.ExpiredSig: _("Good signature; Signature expired"),
        GpgStatus.ExpiredKey: _("Good signature; Key expired"),
        GpgStatus.RevokedKey: _("Good signature; Key revoked"),
        GpgStatus.Bad: _("Bad signature"),
        GpgStatus.ProcessError: _("Failed to start verification process"),
    }

    table[GraphPreset] = {
        GraphPreset.Compact: _p("graph look", "Compact"),
        GraphPreset.Comfortable: _p("graph look", "Comfortable"),
        GraphPreset.Vivid: _p("graph look", "Vivid"),
        GraphPreset.Custom: _p("graph look", "Custom"),
    }

    table[GraphLaneWidth] = {
        GraphLaneWidth.Slim: _p("graph lanes", "Slim"),
        GraphLaneWidth.Medium: _p("graph lanes", "Medium"),
        GraphLaneWidth.Wide: _p("graph lanes", "Wide"),
    }

    table[GraphRefBoxWidth] = {
        GraphRefBoxWidth.IconsOnly: _("Icons only"),
        GraphRefBoxWidth.Standard: _("Shorten long names"),
        GraphRefBoxWidth.Wide: _("Full names"),
    }

    table[CommitFormPlacement] = {
        CommitFormPlacement.FilesPanel: _("In the files panel"),
        CommitFormPlacement.BottomBar: _("Along the bottom"),
    }

    table[GraphRowLayout] = {
        GraphRowLayout.HashFirst: _("Hash first"),
        GraphRowLayout.GraphFirst: _("Graph first"),
    }

    table[GraphRowHeight] = {
        GraphRowHeight.Cramped: _p("row spacing", "Cramped"),
        GraphRowHeight.Tight: _p("row spacing", "Tight"),
        GraphRowHeight.Relaxed: _p("row spacing", "Relaxed"),
        GraphRowHeight.Roomy: _p("row spacing", "Roomy"),
        GraphRowHeight.Spacious: _p("row spacing", "Spacious"),
    }

    table[NavContext] = {
        NavContext.EMPTY: _p("NavContext", "Empty"),
        NavContext.UNSTAGED: _p("NavContext", "Unstaged"),
        NavContext.STAGED: _p("NavContext", "Staged"),
        NavContext.COMMITTED: _p("NavContext", "Committed"),
    }

    table[NVERule] = {
        NVERule.ILLEGAL_NAME: _("Illegal name."),
        NVERule.ILLEGAL_SUFFIX: _("Illegal suffix."),
        NVERule.ILLEGAL_PREFIX: _("Illegal prefix."),
        NVERule.CONTAINS_ILLEGAL_SEQ: _("Contains illegal character sequence."),
        NVERule.CONTAINS_ILLEGAL_CHAR: _("Contains illegal character."),
        NVERule.CANNOT_BE_EMPTY: _("Cannot be empty."),
        NVERule.NOT_WINDOWS_FRIENDLY: _("This name is discouraged for compatibility with Windows."),
        NVERule.NAME_TAKEN_BY_REF: _("This name is already taken."),
        NVERule.NAME_TAKEN_BY_FOLDER: _("This name is already taken by a folder."),
        NVERule.NOT_A_FOLDER: _("The folder in this path clashes with an existing ref that isn’t a folder."),
    }

    table[PatchPurpose] = {
        PatchPurpose.Stage: _p("PatchPurpose", "Stage"),
        PatchPurpose.Unstage: _p("PatchPurpose", "Unstage"),
        PatchPurpose.Discard: _p("PatchPurpose", "Discard"),
        PatchPurpose.Lines | PatchPurpose.Stage: _p("PatchPurpose", "Stage lines"),
        PatchPurpose.Lines | PatchPurpose.Unstage: _p("PatchPurpose", "Unstage lines"),
        PatchPurpose.Lines | PatchPurpose.Discard: _p("PatchPurpose", "Discard lines"),
        PatchPurpose.Hunk | PatchPurpose.Stage: _p("PatchPurpose", "Stage hunk"),
        PatchPurpose.Hunk | PatchPurpose.Unstage: _p("PatchPurpose", "Unstage hunk"),
        PatchPurpose.Hunk | PatchPurpose.Discard: _p("PatchPurpose", "Discard hunk"),
        PatchPurpose.File | PatchPurpose.Stage: _p("PatchPurpose", "Stage file"),
        PatchPurpose.File | PatchPurpose.Unstage: _p("PatchPurpose", "Unstage file"),
        PatchPurpose.File | PatchPurpose.Discard: _p("PatchPurpose", "Discard file"),
    }

    table[PathDisplayStyle] = {
        PathDisplayStyle.FullPaths: _("Full paths"),
        PathDisplayStyle.AbbreviateDirs: _("Abbreviate directories"),
        PathDisplayStyle.FileNameOnly: _("Filename only"),
        PathDisplayStyle.FileNameFirst: _("Filename first"),
    }

    table[QtApiNames] = {
        QtApiNames.Automatic: _p("Qt binding", "Automatic (recommended)"),
        QtApiNames.PySide6: "PySide6",
        QtApiNames.PyQt6: "PyQt6",
        QtApiNames.PyQt5: "PyQt5"
    }

    table[RefSort] = {
        RefSort.TimeDesc: _p("sort refs by date of latest commit, descending", "Date, newest first"),
        RefSort.TimeAsc: _p("sort refs by date of latest commit, ascending", "Date, oldest first"),
        RefSort.AlphaAsc: _p("sort refs alphabetically, ascending", "Name, A-Z"),
        RefSort.AlphaDesc: _p("sort refs alphabetically, descending", "Name, Z-A"),
        RefSort.UseGlobalPref: "",
    }

    table[RepositoryState] = {
        RepositoryState.NONE: _p("RepositoryState", "None"),
        RepositoryState.MERGE: _p("RepositoryState", "Merging"),
        RepositoryState.REVERT: _p("RepositoryState", "Reverting"),
        RepositoryState.REVERT_SEQUENCE: _p("RepositoryState", "Reverting (sequence)"),
        RepositoryState.CHERRYPICK: _p("RepositoryState", "Cherry-picking"),
        RepositoryState.CHERRYPICK_SEQUENCE: _p("RepositoryState", "Cherry-picking (sequence)"),
        RepositoryState.BISECT: _p("RepositoryState", "Bisecting"),
        RepositoryState.REBASE: _p("RepositoryState", "Rebasing"),
        RepositoryState.REBASE_INTERACTIVE: _p("RepositoryState", "Rebasing (interactive)"),
        RepositoryState.REBASE_MERGE: _p("RepositoryState", "Rebasing (merging)"),
        RepositoryState.APPLY_MAILBOX: "Apply Mailbox",  # intentionally untranslated
        RepositoryState.APPLY_MAILBOX_OR_REBASE: "Apply Mailbox or Rebase",  # intentionally untranslated
    }

    table[SidebarItem] = {
        SidebarItem.UncommittedChanges: toLengthVariants(_p("SidebarModel", "Local Changes|Changes")),
        SidebarItem.AllCommits: _p("SidebarModel", "All Commits"),
        SidebarItem.LocalBranchesHeader: _p("SidebarModel", "Branches"),
        SidebarItem.StashesHeader: _p("SidebarModel", "Stashes"),
        SidebarItem.RemotesHeader: _p("SidebarModel", "Remotes"),
        SidebarItem.TagsHeader: _p("SidebarModel", "Tags"),
        SidebarItem.SubmodulesHeader: _p("SidebarModel", "Submodules"),
        SidebarItem.WorktreesHeader: _p("SidebarModel", "Worktrees"),
        SidebarItem.LocalBranch: _p("SidebarModel", "Local branch"),
        SidebarItem.DetachedHead: _p("SidebarModel", "Detached HEAD"),
        SidebarItem.UnbornHead: _p("SidebarModel", "Unborn HEAD"),
        SidebarItem.RemoteBranch: _p("SidebarModel", "Remote branch"),
        SidebarItem.Stash: _p("SidebarModel", "Stash"),
        SidebarItem.Remote: _p("SidebarModel", "Remote"),
        SidebarItem.Tag: _p("SidebarModel", "Tag"),
        SidebarItem.Submodule: _p("SidebarModel", "Submodules"),
        SidebarItem.Worktree: _p("SidebarModel", "Worktree"),
        SidebarItem.Spacer: "---",
    }

    table[TabBarClick] = {
        TabBarClick.Nothing: _("Do nothing"),
        TabBarClick.Folder: _("Open repo folder"),
        TabBarClick.Terminal: _("Open repo in terminal"),
        TabBarClick.Close: _("Close tab"),
    }

    table[ThemeAccent] = {
        ThemeAccent.Blue: _("Blue"),
        ThemeAccent.Cyan: _("Cyan"),
        ThemeAccent.Green: _("Green"),
        ThemeAccent.Yellow: _("Yellow"),
        ThemeAccent.Orange: _("Orange"),
        ThemeAccent.Red: _("Red"),
        ThemeAccent.Pink: _("Pink"),
        ThemeAccent.Gray: _("Gray"),
        ThemeAccent.Indigo: _("Indigo"),
        ThemeAccent.Purple: _("Purple"),
    }

    table[ThemeVariant] = {
        ThemeVariant.Modern: _("{app} Modern", app=APP_DISPLAY_NAME),
        ThemeVariant.Neutral: _("{app} Neutral", app=APP_DISPLAY_NAME),
    }

    table[WhitespaceMode] = {
        WhitespaceMode.Strict: _("Do not ignore whitespace changes"),
        WhitespaceMode.IgnoreAll: _("Ignore all whitespace changes"),
        WhitespaceMode.IgnoreChange: _("Ignore length changes in existing whitespace"),
        WhitespaceMode.IgnoreCrAtEol: _("Ignore line ending changes only ({0})", "LF ↔ CRLF"),
    }

    return table


def _prefKeyTable() -> dict[str, str]:
    from gitfourchette.toolbox.textutils import paragraphs, tquo, escape, stripAccelerators
    from gitfourchette.exttools.usercommand import UserCommand

    sshAuthSock = os.environ.get("SSH_AUTH_SOCK", "")
    if sshAuthSock:
        sshAuthSockHelp = paragraphs(
            _("Note: Per {k}, your system is providing an ssh-agent ({v}). "
              "It’s recommended to use this one."),
            _("If your system’s agent isn’t saving any passphrases, "
              "make sure you’ve enabled {c} in your SSH configuration."))
    else:
        sshAuthSockHelp = _("Note: Per {k}, no ssh-agent seems to be running on your system.")
    sshAuthSockHelp = "<blockquote>" + sshAuthSockHelp.format(
        k="SSH_AUTH_SOCK", v=escape(sshAuthSock), c="AddKeysToAgent")

    return {
        # Panes
        "general": _p("Prefs", "General"),
        "diff": _p("Prefs", "Diff"),
        "history": _p("Prefs", "History"),
        "commit": _p("Prefs", "Commit"),
        "git": _p("Prefs", "Git"),
        "integration": _p("Prefs", "Integration"),
        "userCommands": _p("Prefs", "Commands"),
        "advanced": _p("Prefs", "Advanced"),

        # Sections
        "appearance": _p("Prefs", "Appearance"),
        "repositories": _p("Prefs", "Repositories"),
        "tabs": _p("Prefs", "Tabs"),
        "backgroundActivity": _p("Prefs", "Background Activity"),
        "homePage": _p("Prefs", "Home Page"),
        "diffView": _p("Prefs", "Diff View"),
        "content": _p("Prefs", "Content"),
        "largeFiles": _p("Prefs", "Large Files and Images"),
        "sorting": _p("Prefs", "Sorting"),
        "graphLook": _p("Prefs", "Graph Look"),
        "graph": _p("Prefs", "Graph"),
        "commitRows": _p("Prefs", "Commit Rows"),
        "signatures": _p("Prefs", "Signatures"),
        "commitForm": _p("Prefs", "Commit Form"),
        "fileLists": _p("Prefs", "File Lists"),
        "gitExecutable": _p("Prefs", "Git Executable"),
        "ssh": _p("Prefs", "SSH"),
        "externalTools": _p("Prefs", "External Tools"),
        "codeHosting": _p("Prefs", "Code Hosting"),
        "mergeRequestAudit": _p("Prefs", "Merge Request Audit"),
        "review": _p("Prefs", "Code Review"),
        "assistantPrices": _p("Prefs", "What the Assistant Charges"),
        "trash": _p("Prefs", "Trash"),
        "interface": _p("Prefs", "Interface"),
        "troubleshooting": _p("Prefs", "Troubleshooting"),

        # General
        "qtStyle": _("Appearance"),
        "compactFolders": _("Compact folders"),
        "compactFolders_help": _("In the file tree, a folder that holds nothing but one other folder "
                                 "shares its line, as in “src/ui”."),
        # Same words as the toolbar's menu, which offers the same choice
        "compactUi": _("Density"),
        "compactUi_false": stripAccelerators(_("&Normal")),
        "compactUi_true": stripAccelerators(_("&Compact")),
        "compactUi_help": _("Smaller text and icon-only toolbar buttons"),
        "language": _("Language"),
        "showToolBar": _("Show toolbar"),
        "showSidebar": _("Show sidebar"),
        "showStatusBar": _("Show status bar"),
        "showMenuBar": _("Show menu bar"),
        "showMenuBar_help": _("When the menu bar is hidden, press the Alt key to show it again."),
        "maxRecentRepos": _("Recent repositories"),
        "tabCloseButton": _("Show close buttons on tabs"),
        "expandingTabs": _("Stretch tabs to fill the tab bar"),
        "autoHideTabs": _("Hide the tab bar when only one repository is open"),
        "doubleClickTabBar": _("Double-click a tab"),
        "middleClickTabBar": _("Middle-click a tab"),
        "autoFetchMinutes": _("Fetch remotes automatically every # minutes"),
        "autoRefresh": _("Refresh when {app} becomes active", app=APP_DISPLAY_NAME),
        "autoRefresh_note": _("When this is off, press {key} to see changes made outside the app.", key="F5"),
        "autoRefresh_help": paragraphs(
            _("When you return to {app} from another application, it automatically "
              "scans for changes in the working directory and local branches. "
              "This keeps the interface in sync with the state of your repo on disk."),
            _("If you turn this off, you will need to hit {key} to "
              "perform this refresh manually.", key="F5"),
            "<b>" + _("We strongly recommend to keep this setting enabled.") + "</b>"),
        "homeMascot": _("Show the dinosaur on the Home page"),
        "homeMascot_help": _("A little dinosaur walks across the welcome text, fetching eggs for its nest. "
                             "It only moves while the Home page is on screen."),
        "homeMascotFollowsCursor": _("Follow the pointer with its eyes"),

        # Diff
        "font": _("Font"),
        "syntaxHighlighting": _("Syntax highlighting"),
        "lineColors": _("Line colors"),
        "colorblind_false": _("Red and green"),
        "colorblind_true": _("Teal and orange (colorblind-friendly)"),
        "colorblind_help": _("Background colors for deleted (-) and added (+) lines."),
        "tabSpaces": _("Tab width # spaces"),
        "context": _("Context"),
        "contextLines": _("Show up to # context lines"),
        "contextLines_help": _("Amount of unmodified lines to show around red or green lines in a diff."),
        "wholeFileDiff": _("Show whole file"),
        "wholeFileDiff_help": _("Show the entire file instead of just the lines around each change."),
        "diffLayout": _("Layout"),
        "sideBySideDiff": _("Side-by-side diff"),
        "sideBySideDiff_false": _("Unified"),
        "sideBySideDiff_true": _("Side by side"),
        "whitespaceMode": _("Whitespace changes"),
        "whitespaceMode_note": _("Only changes what the diff shows."),
        "whitespaceMode_help": paragraphs(
            _("How whitespace changes are shown in diffs."),
            _("This setting only affects how diffs are displayed. "
              "Operations that handle patches (export, apply, revert, etc.) still honor all whitespace changes.")),
        "wordWrap": _("Wrap long lines"),
        "showWhitespace": _("Show whitespace characters"),
        "showStrayCRs": _("Highlight Windows line endings (CRLF)"),
        "middleClickStageLines": _("Middle-click stages or unstages the selected lines"),
        "largeFileThresholdKB": _("Load diffs up to # KB"),
        "imageFileThresholdKB": _("Load images up to # KB"),
        "renderSvg": _("SVG files"),
        "renderSvg_true": _("Show as image"),
        "renderSvg_false": _("Show as text"),

        # History
        "chronologicalOrder": _("Sort commits"),
        "chronologicalOrder_true": _("By date"),
        "chronologicalOrder_false": _("Topologically"),
        "chronologicalOrder_help": paragraphs(
            _("<b>Chronological mode</b> lets you stay on top of the latest activity in the repository. "
              "The most recent commits always show up at the top of the graph. "
              "However, the graph can get messy when multiple branches receive commits in the same timeframe."),
            _("<b>Topological mode</b> makes the graph easier to read. It attempts to present sequences of "
              "commits within a branch in a linear fashion. Since this is not a strictly chronological "
              "mode, you may have to do more scrolling to see the latest changes in various branches."),
        ),
        "refSort": _("Sort branches and tags"),
        "refSort_note": _("Changing this resets the order you picked in each repository."),
        "refSort_help": paragraphs(
            _("The default sorting mode for local branches, remote branches, and tags in the sidebar."),
            _("You can fine-tune this setting in each repo by right-clicking Branches, Remotes, or Tags "
              "in the sidebar. (Note that changing the default setting here will clear per-repo tweaks.)")),
        "graphRowLayout": _("Row layout"),
        "graphRowLayout_help": paragraphs(
            _("<b>Hash first</b> is the classic layout: every row opens with the commit hash, "
              "and the branch labels sit between the graph and the commit message."),
            _("<b>Graph first</b> gives the graph a column of its own, so commit messages "
              "line up no matter how busy the graph is on any given row. Branch labels lead the "
              "message column, and the hash moves to the right, next to the author."),
        ),
        "graphPreset": _("Look"),
        "graphPreset_note": _("A look sets the row spacing, the lanes, the branch labels, the avatars "
                              "and the row backgrounds. Nothing else moves, and you can tune any of "
                              "them afterwards."),
        "graphRowHeight": _("Row spacing"),
        "graphLaneWidth": _("Lanes"),
        "graphLaneWidth_note": _("Wider lanes are drawn thicker, with bigger commit dots. "
                                 "The graph never gets less room than three lanes."),
        "flattenLanes": _("Avoid gaps between branches"),
        "alternatingRowColors": _("Alternate row backgrounds"),
        "maxCommits": _("Load up to # commits"),
        "maxCommits_help": _("Set to 0 to always load the full commit history."),
        "refBoxMaxWidth": _("Branch labels"),
        "refBoxMaxWidth_help": _("You can always hover over an indicator to display the full name of the ref."),
        "authorDisplayStyle": _("Author"),
        "metadataNearMessage": _("Keep author and date next to the message"),
        "metadataNearMessage_help": _(
            "In a wide window, the author, hash and date line up a little way past the commit "
            "messages instead of at the far right, so that a row reads in one sweep."),
        "showAvatars": _("Show author avatars"),
        "showAvatars_help": paragraphs(
            _("A chip with the author’s initials, colored from their email address, "
              "so that the same person always looks the same in the history."),
            _("Your own commits get a gray chip, so that other people’s stand out, "
              "and a run of commits by one author shows their color once."),
        ),
        "fadeRepeatedAvatars": _("Fade the chip in a run of commits by one author"),
        "fadeRepeatedAvatars_help": _(
            "A run of commits by the same person shows their chip once at full strength, "
            "so a change of author catches the eye. Turn it off for a face on every row."),
        "downloadAvatars": _("Download pictures from GitHub and Gravatar"),
        "downloadAvatars_note": _("Sends authors’ email addresses to these services."),
        "downloadAvatars_help": _(
            "Look up each author’s picture on GitHub or Gravatar. This sends their email "
            "address to a third party, so it is off until you ask for it. Without it, "
            "authors get a chip with their initials, computed on your machine."),
        "shortTimeFormat": _("Date format"),
        "shortTimeFormat_help": _timeFormatGuide(),
        "shortHashChars": _("Hash length # characters"),
        "authorDiffAsterisk": _("Mark rebased, amended or re-committed commits with *"),
        "authorDiffAsterisk_help": paragraphs(
            _("The commit history displays information about a commit’s <b>author</b>—"
              "their name and the date at which they made the commit. But in some cases, a commit "
              "might have been revised by someone else than the original author—"
              "this person is called the <b>committer</b>."),
            _("If you tick this option, an asterisk (*) will appear after the author’s name "
              "and/or date if they differ from the committer’s for any given commit."),
            _("Note that you can always hover over the author’s name or date to obtain "
              "detailed information about the author and the committer."),
        ),
        "verifyGpgOnTheFly": _("Verify signatures as commits scroll into view"),
        "verifyGpgOnTheFly_note": _("Can slow down scrolling in large repositories."),
        "verifyGpgOnTheFly_help": _(
            "As commits scroll into view, call {0} automatically to verify their signatures. "
            "The verification status is materialized by a seal icon next to the author’s name:", tquo("git verify-commit")
        ) + _gpgStatusReferenceTable() + "<br>" + _("(No seal = Commit isn’t signed)"),

        # Commit
        "commitFormPlacement": _("Commit form"),
        "recentCommitMessages": _("Recent messages"),
        "recentCommitMessages_note": _("Offered in the commit message box."),
        "fileTreeView": _("Show files as"),
        "fileTreeView_true": _("Tree"),
        "fileTreeView_false": _("List"),
        "pathDisplayStyle": _("Paths"),
        "doubleClickFileList": _("Double-click a file"),
        "middleClickFileList": _("Middle-click a file"),

        # Git
        "gitPath": "Git",
        "lfsAware": _("Show LFS file contents instead of pointers"),
        "lfsAware_note": _("When this is off, diffs show the pointer text stored in Git."),
        "lfsAware_help": paragraphs(
            _("Tick this to display the real contents from LFS files."),
            _("Untick to display the raw text in LFS pointers."),
        ),
        "ownSshAgent": _("SSH agent"),
        "ownSshAgent_false": _("Use the system agent"),
        "ownSshAgent_true": _("Let {app} start its own", app=APP_DISPLAY_NAME),
        "ownSshAgent_note": _("System agent detected.") if sshAuthSock else _("No system agent detected."),
        "ownSshAgent_help": paragraphs(
            _("“ssh-agent” can save your SSH credentials so you don’t have to retype the same passphrase over and over. "
              "Some Linux distributions set up an ssh-agent for you."),
            _("You can also have {app} start its own instance of ssh-agent "
              "for the duration of your session and have it remember passphrases."),
            sshAuthSockHelp,
        ),
        "ownAskpass": _("Ask for SSH passphrases in {app}", app=APP_DISPLAY_NAME),
        "ownAskpass_help": paragraphs(
            _("Tick this to have OpenSSH use {app} to ask for passphrases."),
            _("Untick this if you’ve set up another program in the {0} environment variable (such as {1}).", tquo("SSH_ASKPASS"), tquo("ksshaskpass"))),

        # Integration
        "externalEditor": _("Text editor"),
        "terminal": _("Terminal"),
        "terminal_help": paragraphs(
            _("Argument placeholders:"),
            _tokenReferenceTable({"$COMMAND": _("Command to execute after launching the terminal")}),
            _("The {0} placeholder is mandatory. It is automatically substituted for a wrapper script that "
              "enters your working directory and optionally starts one of your Custom Commands.",
              "$COMMAND")),
        "externalDiff": _("Diff tool"),
        "externalDiff_help":
            "<p style='white-space: pre'>" + _("Argument placeholders:") + "\n" + _tokenReferenceTable({
                "$L": _("Old / Left"),
                "$R": _("New / Right"),
            }),
        "externalMerge": _("Merge tool"),
        "externalMerge_help":
            "<p style='white-space: pre'>" + _("Argument placeholders:") + "\n" + _tokenReferenceTable({
                "$B": _("Ancestor / Base / Center"),
                "$L": _("Ours / Local / Left"),
                "$R": _("Theirs / Remote / Right"),
                "$M": _("Merged / Output / Result"),
            }),

        # Commands
        "userCommands_guide": _userCommandsGuide(),
        "commands": "",
        "confirmCommands": _("Ask before running a command"),
        "confirmCommands_help": _(
            "If you untick this, you can still force a prompt to appear for "
            "specific commands by prepending them with {0}. For example: {1}",
            tquo(f"<tt>{UserCommand.AlwaysConfirmPrefix}</tt>"),
            "<pre>?git stash</pre>"),

        # Advanced
        "maxTrashFiles": _("Keep up to # discarded changes"),
        "maxTrashFiles_note": _("When you discard changes, {app} keeps a copy in a trash folder, "
                                "so you can get them back.", app=APP_DISPLAY_NAME),
        "maxTrashFileKB": _("Skip changes larger than # KB"),
        "condensedFonts": _("Condense long names before truncating them"),
        "condensedFonts_help": "<p>" + _(
            "When a branch name or author name is too long to fit in its allotted space, "
            "condense the font before truncating the text."),
        "animations": _("Animate the sidebar"),
        "smoothScroll": _("Smooth scrolling"),
        "reviewPriceInput": _("Input tokens, per million"),
        "reviewPriceOutput": _("Output tokens, per million"),
        "reviewPriceInput_help": _("Used to price a review when the assistant reports only tokens. "
                                   "Claude’s CLI reports the cost itself, and then these are ignored."),
        "auditEnabled": _("Review open merge requests automatically"),
        "auditEnabled_note": _("Reviews every open merge request of the chosen projects, again whenever "
                               "its author pushes. Comments are posted under your own name."),
        "auditRepos": _("Projects to audit…"),
        "auditIntervalMinutes": _("Check every # minutes"),
        "auditSkipDrafts": _("Skip drafts"),
        "auditSkipCiReviewed": _("Skip what the pipeline already reviewed"),
        "manageForgeAccounts": _("Code Hosting Accounts…"),
        "manageForgeAccounts_note": _("An access token lets {app} post review comments on your merge requests. "
                                      "Tokens are kept in a file only you can read."),
        "resetDontShowAgain": _("Show Skipped Messages Again"),
        "verbosity": _("Log level"),
        "forceQtApi": _("Qt binding"),
        "forceQtApi_help": paragraphs(
            _("After restarting, {app} will use this Qt binding if available."),
            _("You can also pass the name of a Qt binding via the “QT_API” environment variable."),
        ),
        "pygmentsPlugins": _("Load third-party Pygments plugins"),
        "pygmentsPlugins_help": "<p>" + _("Let {app} load third-party Pygments plugins installed on your system. "
                                          "These plugins extend syntax highlighting with new languages "
                                          "and color schemes. <b>May incur significant slowdowns.</b>"),
    }


def _timeFormatGuide() -> str:
    from gitfourchette.qt import QLocale, QDateTime, QDate, QTime

    locale = QLocale()
    firstDay = QDateTime(QDate(2000, 1, 1), QTime(0, 0))
    lastDay = QDateTime(QDate(2099, 12, 31), QTime(23, 59, 59))
    monday = QDateTime(QDate(2024, 12, 23), QTime(12, 0))
    sunday = QDateTime(QDate(2024, 12, 29), QTime(12, 0))

    def row(fmt: str, caption="", date1: QDateTime | None = firstDay, date2=lastDay):
        sample = ""
        if date1 is not None:
            f1 = locale.toString(date1, fmt)
            f2 = locale.toString(date2, fmt)
            sample = f1 + "–" + f2
            if caption:
                sample = f", {sample}"
        return f"\n<code>{fmt:>4} </code> {caption}{sample}"

    return (
            "<html style='white-space: pre'>"
            + _p("date/time formats", "Available formats:")
            + "<p>"
            + row("yy", _("year"))
            + row("yyyy", _("year") + f", {QDate.currentDate().year()}", None)
            + "</p><p>"
            + row("M", _("month"))
            + row("MM", _("month"))
            + row("MMM")
            + row("MMMM")
            + "</p><p>"
            + row("d", _("day"))
            + row("dd", _("day"))
            + row("ddd", "", monday, sunday)
            + row("dddd", "", monday, sunday)
            + "</p><p>"
            + row("h", _("hour") + ", 0–23/1–12", None)
            + row("hh", _("hour") + ", 00–23/01–12", None)
            + row("mm", _("minute"))
            + row("ss", _("second"))
            + "</p><p>"
            + row("a")
            + row("A")
            + "</p>")


def _gpgStatusReferenceTable() -> str:
    from gitfourchette.repomodel import GpgStatus

    return _tokenReferenceTable({
        GpgStatus.Pending.iconHtml(): _("Verification pending"),
        GpgStatus.CantCheck.iconHtml(): _("Verification failed (e.g. missing key)"),
        GpgStatus.GoodTrusted.iconHtml(): _("Good signature; Key trusted"),
        GpgStatus.GoodUntrusted.iconHtml(): _("Good signature; Key not fully trusted"),
        GpgStatus.ExpiredSig.iconHtml(): _("Good signature; Key or signature expired"),
        GpgStatus.Bad.iconHtml(): _("Key revoked or bad signature"),
    })


def _tokenReferenceTable(table) -> str:
    markup = "<table>"
    for token, caption in table.items():
        markup += f"<tr><td><b>{token} </b></td><td> {caption}</td></tr>\n"
    markup += "</table>"
    return markup


def _userCommandsGuide() -> str:
    from gitfourchette.toolbox.textutils import paragraphs, linkify, stripAccelerators, tquo
    from gitfourchette.exttools.usercommand import UserCommand

    def cmdName(s: str):
        s = re.sub(r"&(.)", r"<u>&amp;\1</u>", s)
        return f"<com># {s}</com>"

    markup = textwrap.dedent("""\
    <style>
    body {background-color: palette(window); }
    pre { font-size: small; white-space: pre-wrap; margin: 0px; margin-left: 16px; }
    com { color: gray; font-style: italic; }
    tok { font-weight: bold; }
    </style><body>""")
    markup += paragraphs(_("Feel free to copy the sample below and paste it into the text box. "
                           "Your commands then appear in {menu} in the menu bar.",
                           menu=tquo(stripAccelerators(_("&Commands")))))
    markup += textwrap.dedent(f"""\
    <pre>
    git rebase -i <tok>$COMMIT</tok>   {cmdName(_("&Interactive Rebase"))}
    git rebase --continue   {cmdName(_("&Continue Rebase"))}
    <tok>?</tok> git rebase --abort    {cmdName(_("&Abort Rebase"))}
    git diff <tok>$COMMIT</tok> HEAD   {cmdName(_("Diff Commit With &HEAD"))}
    </pre>""")
    markup += paragraphs(_("You may use the following placeholders in your commands:"))
    markup += _tokenReferenceTable(UserCommand.tokenHelpTable())
    markup += paragraphs(linkify(_("For advanced usage tips, please visit [the user’s guide]."
                                   ), _userCommandsGuideUrl))
    return markup
