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

    control: str = "auto"
    "'auto' picks a control from the pref's type; 'radio' shows a choice as radio buttons."

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
    "trtables key of the pane's name; also the stem of its 'prefs-<id>' icon."

    sections: tuple[Section, ...] = ()

    def rows(self):
        for section in self.sections:
            yield from section.rows


def _pane(paneId: str, *sections: Section | Row) -> Pane:
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
    return Pane(paneId, tuple(grouped))


def _section(title: str, *rows: Row) -> Section:
    return Section(title, tuple(rows))


PANES: list[Pane] = [
    _pane(
        "general",
        Row("language"),
        Row("qtStyle"),
        Row("pathDisplayStyle"),
        Row("fileTreeView", control="radio"),
        Row("commitFormPlacement", control="radio"),
        Row("recentCommitMessages"),
        Row("refSort"),
        Row("showToolBar"),
        Row("showStatusBar"),
        Row("showMenuBar", notOn="macos"),  # The menu bar is always there on macOS
        Row("compactUi", control="radio"),
        Row("homeMascot"),
        Row("homeMascotFollowsCursor", parent="homeMascot"),
    ),
    _pane(
        "diff",
        Row("font", alsoKeys=("fontSize",)),
        Row("syntaxHighlighting"),
        Row("colorblind"),
        Row("contextLines", parent="!wholeFileDiff"),
        Row("wholeFileDiff"),
        Row("sideBySideDiff"),
        Row("tabSpaces"),
        Row("largeFileThresholdKB"),
        Row("wordWrap"),
        Row("showStrayCRs"),
        Row("showWhitespace"),
        Row("whitespaceMode"),
    ),
    _pane(
        "imageDiff",
        Row("imageFileThresholdKB"),
        Row("renderSvg", control="radio"),
    ),
    _pane(
        "graph",
        Row("chronologicalOrder", control="radio"),
        Row("graphRowLayout"),
        Row("graphRowHeight"),
        Row("refBoxMaxWidth"),
        Row("authorDisplayStyle"),
        Row("showAvatars"),
        Row("downloadAvatars"),
        Row("shortTimeFormat"),
        Row("maxCommits"),
        Row("authorDiffAsterisk"),
        Row("verifyGpgOnTheFly"),
        Row("alternatingRowColors"),
    ),
    _pane(
        "git",
        Row("gitPath"),
        Row("ownSshAgent", control="radio"),
        Row("ownAskpass"),
        Row("lfsAware"),
    ),
    _pane(
        "external",
        _section("", Row("externalEditor"), Row("terminal")),
        _section("", Row("externalDiff"), Row("externalMerge")),
    ),
    _pane(
        "userCommands",
        Row("commands"),
        Row("confirmCommands"),
    ),
    _pane(
        "tabs",
        Row("tabCloseButton"),
        Row("expandingTabs"),
        Row("autoHideTabs"),
    ),
    _pane(
        "mouseShortcuts",
        _section("tabBarClicks", Row("doubleClickTabBar"), Row("middleClickTabBar")),
        _section("fileListClicks", Row("doubleClickFileList"), Row("middleClickFileList")),
        _section("diffViewClicks", Row("middleClickStageLines")),
    ),
    _pane(
        "trash",
        Row("maxTrashFiles"),
        Row("maxTrashFileKB"),
    ),
    _pane(
        "advanced",
        Row("maxRecentRepos"),
        Row("shortHashChars"),
        Row("autoRefresh"),
        Row("autoFetchMinutes", toggle="autoFetch"),
        Row("flattenLanes"),
        Row("animations"),
        Row("condensedFonts"),
        Row("pygmentsPlugins", notOn="frozen"),  # Depends on system Python packages outside our sandbox
        Row("verbosity"),
        Row("forceQtApi", notOn="frozen"),  # Frozen builds come with their own Qt binding
        Row("resetDontShowAgain"),
    ),
]
"The pages of the Settings window, in order."


HIDDEN: dict[str, str] = {
    "smoothScroll": "rarely wanted off; kept for the few who need it",
    "toolBarButtonStyle": "set where it's seen: the toolbar's context menu",
    "toolBarIconSize": "set where it's seen: the toolbar's context menu",
    "defaultCloneLocation": "remembered by the Clone dialog",
    "dontShowAgain": "internal list; resetDontShowAgain clears it",
    "donatePrompt": "internal counter",
    "refSortClearTimestamp": "internal state written when refSort changes",
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
