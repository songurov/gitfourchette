# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Where each setting appears in the Settings window.

This module is data only: PrefsDialog walks PANES to build its pages. Every
field of Prefs is either shown by exactly one Row, or listed in HIDDEN with the
reason why it isn't shown.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Row:
    key: str
    "The Prefs field this row edits."

    alsoKeys: tuple[str, ...] = ()
    "Other Prefs fields that this row's control edits too (e.g. the font's size)."

    toggle: str = ""
    "A bool pref shown as a checkbox leading the row, which enables the rest of the row."

    parent: str = ""
    """
    A bool pref that this row depends on. The row is disabled (not hidden)
    while the parent is off, and keeps its own value. Prefix with "!" for a row
    that only makes sense while the parent is off.
    """

    label: str = ""
    "trtables key of the row's caption, if it isn't the pref's own (which other places use too)."

    control: str = "auto"
    """
    'auto' picks a control from the pref's type; 'radio' shows a choice as
    radio buttons; 'context' is the context lines' own row.
    """

    note: str = ""
    "trtables key of secondary text shown under the control."

    notOn: str = ""
    "Hide the row on this platform: 'macos', or 'frozen' (packaged builds)."


@dataclasses.dataclass(frozen=True)
class Section:
    title: str = ""
    "trtables key of the section's title, or empty for an untitled group of rows."

    rows: tuple[Row, ...] = ()


@dataclasses.dataclass(frozen=True)
class Pane:
    id: str
    "trtables key of the pane's name."

    icon: str
    "Stock icon of the pane in the switcher."

    sections: tuple[Section, ...] = ()

    wide: bool = False
    "No label column: the rows take the pane's whole width (e.g. a text editor)."

    def rows(self):
        for section in self.sections:
            yield from section.rows


def _pane(paneId: str, icon: str, *sections: Section | Row, wide: bool = False) -> Pane:
    """A pane; bare rows at the start form an untitled first section."""
    grouped: list[Section] = []
    looseRows: list[Row] = []
    for item in sections:
        if isinstance(item, Row):
            looseRows.append(item)
            continue
        if looseRows:
            grouped.append(Section(rows=tuple(looseRows)))
            looseRows = []
        grouped.append(item)
    if looseRows:
        grouped.append(Section(rows=tuple(looseRows)))
    return Pane(paneId, icon, tuple(grouped), wide)


def _section(title: str, *rows: Row) -> Section:
    return Section(title, tuple(rows))


PANES: list[Pane] = [
    _pane(
        "general", "prefs-general",
        _section(
            "appearance",
            Row("qtStyle"),
            Row("compactUi", control="radio", note="compactUi_help"),
            Row("language"),
            # Also in the View menu; kept here so that a hidden menu bar can always come back
            Row("showToolBar"),
            Row("showSidebar"),
            Row("showStatusBar"),
            Row("showMenuBar", notOn="macos"),  # The menu bar is always there on macOS
        ),
        _section(
            "repositories",
            Row("maxRecentRepos"),
        ),
        _section(
            "tabs",
            Row("tabCloseButton"),
            Row("expandingTabs"),
            Row("autoHideTabs"),
            Row("doubleClickTabBar"),
            Row("middleClickTabBar"),
        ),
        _section(
            "backgroundActivity",
            Row("autoFetchMinutes", toggle="autoFetch"),
            Row("autoRefresh", note="autoRefresh_note"),
        ),
        _section(
            "homePage",
            Row("homeMascot"),
            Row("homeMascotFollowsCursor", parent="homeMascot"),
        ),
    ),
    _pane(
        "diff", "prefs-diff",
        _section(
            "diffView",
            Row("font", alsoKeys=("fontSize",)),
            Row("syntaxHighlighting"),
            Row("colorblind", label="lineColors", control="radio"),
            Row("tabSpaces"),
        ),
        _section(
            "content",
            Row("contextLines", alsoKeys=("wholeFileDiff",), label="context", control="context"),
            Row("sideBySideDiff", label="diffLayout", control="radio"),
            Row("whitespaceMode", note="whitespaceMode_note"),
            Row("wordWrap"),
            Row("showWhitespace"),
            Row("showStrayCRs"),
            Row("middleClickStageLines"),
        ),
        _section(
            "largeFiles",
            Row("largeFileThresholdKB"),
            Row("imageFileThresholdKB"),
            Row("renderSvg", control="radio"),
        ),
    ),
    _pane(
        "history", "prefs-graph",
        _section(
            "sorting",
            Row("chronologicalOrder", control="radio"),
            Row("refSort", note="refSort_note"),
        ),
        _section(
            "graphLook",
            Row("graphRowHeight"),
            Row("graphLaneWidth", note="graphLaneWidth_note"),
        ),
        _section(
            "graph",
            Row("graphRowLayout", control="radio"),
            Row("metadataNearMessage"),
            Row("flattenLanes"),
            Row("alternatingRowColors"),
            Row("maxCommits"),
        ),
        _section(
            "commitRows",
            Row("refBoxMaxWidth"),
            Row("authorDisplayStyle"),
            Row("showAvatars"),
            Row("downloadAvatars", parent="showAvatars", note="downloadAvatars_note"),
            Row("shortTimeFormat"),
            Row("shortHashChars"),
        ),
        _section(
            "signatures",
            Row("authorDiffAsterisk"),
            Row("verifyGpgOnTheFly", note="verifyGpgOnTheFly_note"),
        ),
    ),
    _pane(
        "commit", "prefs-commit",
        _section(
            "commitForm",
            Row("commitFormPlacement", control="radio"),
            Row("recentCommitMessages", note="recentCommitMessages_note"),
        ),
        _section(
            "fileLists",
            Row("fileTreeView", control="radio"),
            Row("compactFolders"),
            Row("pathDisplayStyle"),
            Row("doubleClickFileList"),
            Row("middleClickFileList"),
        ),
    ),
    _pane(
        "git", "prefs-git",
        _section(
            "gitExecutable",
            Row("gitPath"),
            Row("lfsAware", note="lfsAware_note"),
        ),
        _section(
            "ssh",
            Row("ownSshAgent", control="radio", note="ownSshAgent_note"),
            Row("ownAskpass"),
        ),
    ),
    _pane(
        "integration", "prefs-external",
        _section(
            "externalTools",
            Row("externalEditor"),
            Row("terminal"),
            Row("externalDiff"),
            Row("externalMerge"),
        ),
    ),
    _pane(
        "userCommands", "prefs-usercommands",
        Row("commands"),
        Row("confirmCommands"),
        wide=True,
    ),
    _pane(
        "advanced", "prefs-advanced",
        _section(
            "trash",
            Row("maxTrashFiles", note="maxTrashFiles_note"),
            Row("maxTrashFileKB"),
        ),
        _section(
            "interface",
            Row("condensedFonts"),
            Row("animations"),
            Row("smoothScroll"),
            Row("resetDontShowAgain"),
        ),
        _section(
            "troubleshooting",
            Row("verbosity"),
            Row("forceQtApi", notOn="frozen"),  # Frozen builds come with their own Qt binding
            Row("pygmentsPlugins", notOn="frozen"),  # Depends on system Python packages outside our sandbox
        ),
    ),
]
"The pages of the Settings window, in order."


HIDDEN: dict[str, str] = {
    "toolBarButtonStyle": "set where it's seen: the toolbar's context menu",
    "toolBarIconSize": "set where it's seen: the toolbar's context menu",
    "defaultCloneLocation": "remembered by the Clone dialog",
    "dontShowAgain": "internal list; resetDontShowAgain clears it",
    "donatePrompt": "internal counter",
    "refSortClearTimestamp": "internal state written when refSort changes",
    "migrations": "internal record of one-time preference migrations already done",
}
"Prefs fields that Settings doesn't show, and why."


def rowKeys(row: Row) -> tuple[str, ...]:
    """Every Prefs field that a row edits."""
    return (row.key, *row.alsoKeys, *((row.toggle,) if row.toggle else ()))


def findPane(key: str) -> int:
    """Index of the pane showing this Prefs field, or -1."""
    for i, pane in enumerate(PANES):
        for row in pane.rows():
            if key in rowKeys(row):
                return i
    return -1
