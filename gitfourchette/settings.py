# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import enum
import logging
import os
from collections.abc import Iterator
from contextlib import suppress
from typing import Any, TypedDict, ClassVar

from gitfourchette import colors
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.exttools.toolpresets import ToolPresets
from gitfourchette.localization import *
from gitfourchette.prefsfile import PrefsFile
from gitfourchette.qt import *
from gitfourchette.syntax import PygmentsPresets, ColorScheme
from gitfourchette.toolbox.benchmark import BENCHMARK_LOGGING_LEVEL
from gitfourchette.toolbox.gitutils import COMPACT_DATE_FORMAT, AuthorDisplayStyle
from gitfourchette.toolbox.pathutils import PathDisplayStyle
from gitfourchette.toolbox.textutils import englishTitleCase

logger = logging.getLogger(__name__)


SHORT_DATE_PRESETS = {
    "Compact": COMPACT_DATE_FORMAT,
    "ISO": "yyyy-MM-dd HH:mm",
    "Universal 1": "dd MMM yyyy HH:mm",
    "Universal 2": "ddd dd MMM yyyy HH:mm",
    "European 1": "dd/MM/yy HH:mm",
    "European 2": "dd.MM.yy HH:mm",
    "American": "M/d/yy h:mm ap",
}

SHORT_DATE_DEFAULT_PRESET = next(iter(SHORT_DATE_PRESETS.values()))


class RefSort(enum.IntEnum):
    TimeDesc = 0
    TimeAsc = 1
    AlphaAsc = 2
    AlphaDesc = 3
    UseGlobalPref = -1


class GraphRowHeight(enum.IntEnum):
    Cramped = 80
    Tight = 100
    Relaxed = 130
    Roomy = 150
    Spacious = 175


class GraphPreset(enum.StrEnum):
    """A named starting point for the way the history is drawn."""

    Compact = "compact"
    Comfortable = "comfortable"
    Vivid = "vivid"
    Custom = "custom"


class GraphLaneWidth(enum.IntEnum):
    """Room between two lanes of the graph, in pixels at 1x."""

    Slim = 10
    Medium = 15
    Wide = 20


class GraphRefBoxWidth(enum.IntEnum):
    IconsOnly = 0
    Standard = 120
    Wide = 1000


GRAPH_PRESET_KEYS = (
    "graphRowHeight",
    "graphLaneWidth",
    "refBoxMaxWidth",
    "showAvatars",
    "fadeRepeatedAvatars",
    "alternatingRowColors",
)
"""The settings a graph preset writes. Everything else about the history —
the row layout, the sorting, the date format, how many commits to load — is
left exactly where the user put it."""

GRAPH_PRESETS: dict["GraphPreset", dict[str, Any]] = {
    # What the app has always drawn, spelled out rather than implied, so that
    # picking it again is a way back and not a guess.
    GraphPreset.Compact: {
        "graphRowHeight": GraphRowHeight.Relaxed,
        "graphLaneWidth": GraphLaneWidth.Slim,
        "refBoxMaxWidth": GraphRefBoxWidth.Standard,
        "showAvatars": True,
        "fadeRepeatedAvatars": True,
        "alternatingRowColors": True,
    },

    # Room to breathe: a lane you can follow across a merge, and rows your
    # eye doesn't have to aim at.
    GraphPreset.Comfortable: {
        "graphRowHeight": GraphRowHeight.Roomy,
        "graphLaneWidth": GraphLaneWidth.Medium,
        "refBoxMaxWidth": GraphRefBoxWidth.Standard,
        "showAvatars": True,
        "fadeRepeatedAvatars": True,
        "alternatingRowColors": True,
    },

    # The graph as the headline: thick lanes, big dots, branch names in full,
    # a face on every row, and no banding competing with the lane colors.
    GraphPreset.Vivid: {
        "graphRowHeight": GraphRowHeight.Spacious,
        "graphLaneWidth": GraphLaneWidth.Wide,
        "refBoxMaxWidth": GraphRefBoxWidth.Wide,
        "showAvatars": True,
        "fadeRepeatedAvatars": False,
        "alternatingRowColors": False,
    },

    # Whatever the user has made of it. Writes nothing.
    GraphPreset.Custom: {},
}
"""What each named look sets. A preset is a starting point: it writes these
keys and stops, and the first hand-tuned one moves the look to Custom."""


def graphPresetOf(values: dict[str, Any]) -> "GraphPreset":
    """
    The look a set of graph settings adds up to, read off the settings
    themselves rather than off whatever was picked last. A graph nobody has
    tuned still matches the table it came from; one that has been tuned
    matches none of them, and that is what Custom means.
    """
    for preset, table in GRAPH_PRESETS.items():
        if table and all(values[key] == value for key, value in table.items()):
            return preset
    return GraphPreset.Custom


class GraphRowLayout(enum.IntEnum):
    HashFirst = 0
    """Classic layout: hash, graph, ref indicators, then the commit message."""

    GraphFirst = 1
    """The graph opens the row in a column of its own, so commit messages start
    at the same x however busy the graph gets. Ref indicators lead the message
    column, and the hash moves next to the author on the right."""


class QtApiNames(enum.StrEnum):
    Automatic = ""
    PyQt6 = "pyqt6"
    PySide6 = "pyside6"
    PyQt5 = "pyqt5"


class LoggingLevel(enum.IntEnum):
    Benchmark = BENCHMARK_LOGGING_LEVEL
    Debug = logging.DEBUG
    Info = logging.INFO
    Warning = logging.WARNING


class FileListClick(enum.StrEnum):
    Nothing = ""
    Stage = "stage"
    Blame = "blame"
    Edit = "edit"
    DiffTool = "difftool"
    Folder = "folder"


class CommitFormPlacement(enum.StrEnum):
    FilesPanel = "files-panel"
    BottomBar = "bottom-bar"


class MergeLayout(enum.StrEnum):
    """How the merge editor arranges the two versions and the result."""

    SideBySide = "side-by-side"
    """Our version and theirs next to each other, the result underneath."""

    Stacked = "stacked"
    """Our version above theirs, the result underneath: full-width lines,
    and a change of side is a step down rather than a step across."""

    OneColumn = "one-column"
    """One column: each conflict shows our version over theirs, in place,
    with the file's unchanged text running through them."""


class TabBarClick(enum.StrEnum):
    Nothing = ""
    Close = "close"
    Folder = "folder"
    Terminal = "terminal"


class WhitespaceMode(enum.StrEnum):
    """How `git diff` treats line endings and whitespace when showing patches."""

    Strict = ""
    IgnoreAll = "ignore-all-space"
    IgnoreChange = "ignore-space-change"
    IgnoreCrAtEol = "ignore-cr-at-eol"


WHOLE_FILE_CONTEXT = 1_000_000
"""Context lines meaning 'as much as there is'. git clamps to the file's length."""

CONTEXT_LINES_RANGE = (1, 32)
"""How many context lines Settings and the diff toolbar offer. Not 0: staging or
discarding individual lines is flaky without any context around them."""

COMPACT_POINT_DROP = 1.0
"""How much smaller compact mode runs. One point is the difference between
'roomy' and 'a screenful', without becoming unreadable."""


@dataclasses.dataclass
class Prefs(PrefsFile):
    """
    The user's settings. Where each field appears in the Settings window,
    or why it doesn't, is up to prefsschema.py.
    """

    _filename = "prefs.json"

    language                    : str                   = ""
    qtStyle                     : str                   = ""
    pathDisplayStyle            : PathDisplayStyle      = PathDisplayStyle.FullPaths
    fileTreeView                : bool                  = True
    compactFolders              : bool                  = True
    """In the file tree, a folder that holds nothing but one other folder
    shares its line with it ("src/ui"): fewer rows to read past."""
    commitFormPlacement         : CommitFormPlacement   = CommitFormPlacement.BottomBar
    recentCommitMessages        : int                   = 10
    refSort                     : RefSort               = RefSort.TimeDesc
    showToolBar                 : bool                  = True
    showStatusBar               : bool                  = True
    showMenuBar                 : bool                  = True
    compactUi                   : bool                  = False
    homeMascot                  : bool                  = True
    """The little dinosaur that fetches eggs on the Home page."""
    homeMascotFollowsCursor     : bool                  = True

    font                        : str                   = ""
    fontSize                    : int                   = 0
    syntaxHighlighting          : str                   = PygmentsPresets.Automatic
    colorblind                  : bool                  = False
    contextLines                : int                   = 3
    wholeFileDiff               : bool                  = False
    sideBySideDiff              : bool                  = False
    tabSpaces                   : int                   = 4
    largeFileThresholdKB        : int                   = 500
    wordWrap                    : bool                  = False
    showStrayCRs                : bool                  = True
    showWhitespace              : bool                  = False
    whitespaceMode              : WhitespaceMode        = WhitespaceMode.Strict

    imageFileThresholdKB        : int                   = 5000
    renderSvg                   : bool                  = True
    """An SVG is a picture; show it as one. The toolbar toggle is right there
    for the times you want to read the markup."""

    chronologicalOrder          : bool                  = True
    graphRowLayout              : GraphRowLayout        = GraphRowLayout.GraphFirst
    """Messages that all start at the same x stay readable however busy the
    graph gets, and nothing is reserved for refs that most rows don't have."""
    metadataNearMessage         : bool                  = False
    """In a wide window, author, hash and date sit a set distance past the
    commit messages instead of at the far right, 900 px away from them."""
    graphPreset                 : GraphPreset           = GraphPreset.Compact
    """Which named look the graph is on (see GRAPH_PRESETS). Tuning one of the
    settings a preset writes moves this to Custom: a preset is where a look
    starts, never a lock on what follows. It records what the settings say, so
    Settings reads it back from them (graphPresetOf) rather than trusting it —
    a graph tuned before there were looks, or by hand-editing the file, is not
    whatever this happens to hold."""
    graphRowHeight              : GraphRowHeight        = GraphRowHeight.Relaxed
    graphLaneWidth              : GraphLaneWidth        = GraphLaneWidth.Slim
    """How far apart the graph's lanes sit, which also sets how thick they are
    drawn and how big the commit dots get. The lane column never falls below
    three lanes of this width, so the shape of the history is always readable."""
    refBoxMaxWidth              : GraphRefBoxWidth      = GraphRefBoxWidth.Standard
    authorDisplayStyle          : AuthorDisplayStyle    = AuthorDisplayStyle.FullName
    showAvatars                 : bool                  = True
    fadeRepeatedAvatars         : bool                  = True
    """A run of commits by one author shows their chip once at full strength.
    Turn it off for a face on every row."""
    downloadAvatars             : bool                  = False
    shortTimeFormat             : str                   = SHORT_DATE_DEFAULT_PRESET
    maxCommits                  : int                   = 10000
    authorDiffAsterisk          : bool                  = True
    verifyGpgOnTheFly           : bool                  = False
    alternatingRowColors        : bool                  = True
    """Bands carry the eye from a commit message to its author and date across the row."""

    gitPath                     : str                   = ToolPresets.defaultGit()
    ownSshAgent                 : bool                  = False
    ownAskpass                  : bool                  = True
    lfsAware                    : bool                  = True

    externalEditor              : str                   = ""
    terminal                    : str                   = ToolPresets.DefaultTerminalCommand
    externalDiff                : str                   = ToolPresets.DefaultDiffCommand
    externalMerge               : str                   = ToolPresets.DefaultMergeCommand

    commands                    : str                   = ""
    confirmCommands             : bool                  = True

    mergeEditorLayout           : MergeLayout           = MergeLayout.SideBySide
    """How the merge editor lays itself out. Set in its own header, where the
    arrangement is what you are looking at."""

    tabCloseButton              : bool                  = True
    expandingTabs               : bool                  = True
    autoHideTabs                : bool                  = False

    doubleClickTabBar           : TabBarClick           = TabBarClick.Folder
    middleClickTabBar           : TabBarClick           = TabBarClick.Close
    doubleClickFileList         : FileListClick         = FileListClick.Stage
    """Staging is what you do with a file in the working directory nine times out
    of ten, and a double-click that does nothing is a dead gesture."""
    middleClickFileList         : FileListClick         = FileListClick.Stage
    middleClickStageLines       : bool                  = True

    maxTrashFiles               : int                   = 250
    maxTrashFileKB              : int                   = 1000

    maxRecentRepos              : int                   = 20
    shortHashChars              : int                   = 7
    autoRefresh                 : bool                  = True
    autoFetchMinutes            : int                   = 5
    flattenLanes                : bool                  = True
    animations                  : bool                  = True
    condensedFonts              : bool                  = True
    pygmentsPlugins             : bool                  = False
    verbosity                   : LoggingLevel          = LoggingLevel.Debug if APP_TESTMODE else LoggingLevel.Warning
    forceQtApi                  : QtApiNames            = QtApiNames.Automatic
    manageForgeAccounts         : bool                  = False
    """Not a setting: the Settings row for it is a button that opens the code
    hosting accounts. The tokens themselves live in forge.json, which only the
    owner can read - never in this file."""
    resetDontShowAgain          : bool                  = False
    """Shown as a button that brings back every message the user asked not to see again."""

    autoFetch                   : bool                  = False
    smoothScroll                : bool                  = True
    toolBarButtonStyle          : Qt.ToolButtonStyle    = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    toolBarIconSize             : int                   = 16
    showSidebar                 : bool                  = True
    """View > Show Sidebar, for every repo tab at once."""
    defaultCloneLocation        : str                   = ""
    dontShowAgain               : list[str]             = dataclasses.field(default_factory=list)
    donatePrompt                : int                   = 0
    refSortClearTimestamp       : int                   = 0
    migrations                  : list[str]             = dataclasses.field(default_factory=list)
    """One-time changes (see Prefs.migrate) already made to these prefs."""

    def load(self) -> bool:
        loaded = super().load()
        # The diff toolbar used to offer 0 context lines; bring such a value back in range
        low, high = CONTEXT_LINES_RANGE
        self.contextLines = min(max(self.contextLines, low), high)
        self.migrate(fresh=not loaded)
        return loaded

    def migrate(self, fresh: bool):
        """
        Make one-time changes to prefs written by an earlier build.

        Each change runs once: its name is added to `migrations`, which is saved
        with the rest, so a choice made afterwards (say, going back to Modern)
        is never undone. Fresh prefs have nothing to change, so they start out
        with every name in; if nothing else ever gets saved, the next launch is
        fresh again, which comes to the same.
        """
        for name, change in [("neutralTheme", self._moveBuiltInThemeToDefaultLook)]:
            if name in self.migrations:
                continue
            if not fresh:
                change()
                self.setDirty()
            self.migrations.append(name)

    def _moveBuiltInThemeToDefaultLook(self):
        """
        The built-in theme's default look became Neutral. Someone who had the
        built-in theme (then Modern, the only look) moves to Neutral once, in the
        same mode and with the same accent. A native Qt style stays: it was
        picked on purpose. An empty qtStyle ("System default") needs no change,
        since it now stands for Neutral anyway.
        """
        from gitfourchette.themes import DEFAULT_VARIANT, ThemeName, ThemeVariant, formatStyle, parseStyle
        engine, mode, accent, variant = parseStyle(self.qtStyle)
        if engine == ThemeName.BuiltIn and variant == ThemeVariant.Modern:
            self.qtStyle = formatStyle(engine, mode, accent, DEFAULT_VARIANT)

    @property
    def listViewScrollMode(self) -> QAbstractItemView.ScrollMode:
        if self.smoothScroll:
            return QAbstractItemView.ScrollMode.ScrollPerPixel
        else:
            return QAbstractItemView.ScrollMode.ScrollPerItem

    def resolveDefaultCloneLocation(self):
        if self.defaultCloneLocation:
            return self.defaultCloneLocation

        path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if path:
            return os.path.normpath(path)
        return os.path.expanduser("~")

    def effectiveContextLines(self) -> int:
        """
        How much unchanged code to show around a change.

        Whole-file mode is just an enormous amount of context: git stops at the
        ends of the file, so there's no separate code path for it.
        """
        return WHOLE_FILE_CONTEXT if self.wholeFileDiff else self.contextLines

    def monoFont(self):
        monoFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if self.font:
            monoFont.fromString(self.font)
        if self.fontSize > 0:
            monoFont.setPointSize(self.fontSize)
        elif self.compactUi:
            # Compact means compact everywhere, code included - but never at the
            # cost of an explicit size the user asked for.
            monoFont.setPointSizeF(max(6.0, monoFont.pointSizeF() - COMPACT_POINT_DROP))
        return monoFont

    def isSyntaxHighlightingEnabled(self):
        return self.syntaxHighlighting != PygmentsPresets.Off

    def syntaxHighlightingScheme(self):
        return ColorScheme.resolve(self.syntaxHighlighting)

    def addDelColors(self):
        if self.colorblind:
            return colors.teal, colors.orange
        else:
            return colors.olive, colors.red

    def addDelColorsStyleTag(self):
        green, red = self.addDelColors()
        return ("<style>"
                f"del {{ color: {red.name()}; text-decoration: none; }} "
                f"add {{ color: {green.name()}; }}"
                "</style>")

    def isGitSandboxed(self):
        return self.gitPath.startswith(ToolCommands.FlatpakSandboxedCommandPrefix)


class PrefEffects:
    RebuildMenu: ClassVar = {
        "language",
        "commands",
        "confirmCommands",
        "externalEditor"
    }
    "Pref keys that trigger a rebuild of the main menu."

    ReloadDiff: ClassVar = {
        "showStrayCRs",
        "colorblind",
        "largeFileThresholdKB",
        "imageFileThresholdKB",
        "contextLines",
        "wholeFileDiff",
        "whitespaceMode",
        "maxCommits",
        "renderSvg",
        "lfsAware",
        "syntaxHighlighting",
    }
    "Pref keys that trigger a reload of the current diff."

    ReloadRepo: ClassVar = {
        "chronologicalOrder",
        "maxCommits",
        "refSort",
    }
    "Pref keys that fully take effect after a repo reload."

    RestartApp: ClassVar = {
        "language",
        "forceQtApi",
        "pygmentsPlugins",
    }
    "Pref keys that fully take effect after an app restart."


@dataclasses.dataclass
class History(PrefsFile):
    aiProvider: str = "codex"
    aiModels: dict[str, str] = dataclasses.field(default_factory=dict)
    aiLanguage: str = "English"
    aiCommitDetail: str = "deep"
    aiSetupExpanded: bool = False
    aiAllowEdits: bool = False
    "Whether the AI chat shows the strip that picks the assistant, model, language and rules."
    reviewDimensions: list[str] = dataclasses.field(default_factory=list)
    """Which dimensions the merge-request review looked at last time (see
    aireview.DIMENSIONS). Empty until the first review, which starts from
    the defaults."""
    _filename = "history.json"

    class JsonRepo(TypedDict, total=False):
        seq: int
        length: int
        nickname: str
        superproject: str

    class JsonWorkspace(TypedDict, total=False):
        name: str
        repos: list[str]
        activeIndex: int

    repos: dict[str, JsonRepo] = dataclasses.field(default_factory=dict)
    cloneHistory: list[str] = dataclasses.field(default_factory=list)
    fileDialogPaths: dict[str, str] = dataclasses.field(default_factory=dict)
    startups: int = 0
    workspaces: list[JsonWorkspace] = dataclasses.field(default_factory=list)
    currentWorkspace: str = ""
    scanRoots: list[str] = dataclasses.field(default_factory=list)
    "Folders searched for repos on the Home page. Empty means 'pick sensible defaults'."
    scannedRepos: list[str] = dataclasses.field(default_factory=list)
    "Cache of the last scan, so Home has something to show before the next one finishes."

    _maxSeq = -1

    def addRepo(self, path: str):
        path = os.path.normpath(path)
        repo = self.getRepo(path)
        repo['seq'] = self.drawSequenceNumber()
        return repo

    def getRepo(self, path: str) -> JsonRepo:
        path = os.path.normpath(path)
        try:
            repo = self.repos[path]
        except KeyError:
            repo = History.JsonRepo()
            self.repos[path] = repo
        return repo

    def peekRepoNickname(self, path: str) -> str:
        """
        Nickname of a repo we may never have opened.

        Unlike getRepoNickname, this doesn't register the path: merely showing
        a repo in a list must not add it to the recent-repos history.
        """
        path = os.path.normpath(path)
        entry = self.repos.get(path)
        return (entry or {}).get("nickname", "") or os.path.basename(path)

    def getRepoNickname(self, path: str, strict: bool = False) -> str:
        repo = self.getRepo(path)
        path = os.path.normpath(path)
        return repo.get("nickname", "" if strict else os.path.basename(path))

    def setRepoNickname(self, path: str, nickname: str):
        repo = self.getRepo(path)
        nickname = nickname.strip()
        if nickname:
            repo['nickname'] = nickname
        else:
            repo.pop('nickname', None)

    def getRepoNumCommits(self, path: str) -> int:
        repo = self.getRepo(path)
        return repo.get('length', 0)

    def setRepoNumCommits(self, path: str, commitCount: int):
        repo = self.getRepo(path)
        if commitCount > 0:
            repo['length'] = commitCount
        else:
            repo.pop('length', None)

    def getRepoSuperproject(self, path: str) -> str:
        repo = self.getRepo(path)
        return repo.get('superproject', "")

    def setRepoSuperproject(self, path: str, superprojectPath: str):
        repo = self.getRepo(path)
        if superprojectPath:
            repo['superproject'] = superprojectPath
        else:
            repo.pop('superproject', None)

    def workspaceNames(self) -> list[str]:
        return [w.get("name", "") for w in self.workspaces]

    def getWorkspace(self, name: str) -> JsonWorkspace | None:
        return next((w for w in self.workspaces if w.get("name", "") == name), None)

    def setWorkspace(self, name: str, repos: list[str], activeIndex: int = 0):
        """Create or overwrite a workspace. Paths are normalized, order is kept."""
        assert name
        repos = [os.path.normpath(p) for p in repos]
        activeIndex = max(0, min(activeIndex, len(repos) - 1)) if repos else 0
        workspace = self.getWorkspace(name)
        if workspace is None:
            workspace = History.JsonWorkspace(name=name)
            self.workspaces.append(workspace)
        workspace["repos"] = repos
        workspace["activeIndex"] = activeIndex
        self.setDirty()
        return workspace

    def deleteWorkspace(self, name: str):
        self.workspaces = [w for w in self.workspaces if w.get("name", "") != name]
        if self.currentWorkspace == name:
            self.currentWorkspace = ""
        self.setDirty()

    def renameWorkspace(self, oldName: str, newName: str):
        assert newName
        workspace = self.getWorkspace(oldName)
        if workspace is None:
            return
        workspace["name"] = newName
        if self.currentWorkspace == oldName:
            self.currentWorkspace = newName
        self.setDirty()

    def setCurrentWorkspace(self, name: str):
        if self.currentWorkspace != name:
            self.currentWorkspace = name
            self.setDirty()

    def getRepoTabName(self, path: str) -> str:
        name = self.getRepoNickname(path)

        seen = {path}
        while path:
            path = self.getRepoSuperproject(path)
            if path:
                if path in seen:
                    logger.warning(f"Circular superproject in {self._filename}! {path}")
                    return name
                seen.add(path)
                superprojectName = self.getRepoNickname(path)
                name = f"{superprojectName}: {name}"

        return name

    def removeRepo(self, path: str):
        path = os.path.normpath(path)
        self.repos.pop(path, None)
        self.invalidateSequenceNumber()

    def clearRepoHistory(self):
        self.repos.clear()
        self.invalidateSequenceNumber()

    def getRecentRepoPaths(self, n: int, newestFirst=True) -> Iterator[str]:
        sortedPaths = (path for path, _ in
                       sorted(self.repos.items(), key=lambda i: i[1].get('seq', -1), reverse=newestFirst))

        return (path for path, _ in zip(sortedPaths, range(n), strict=False))

    def write(self, force=False):
        self.trim()
        super().write(force)

    def trim(self):
        n = prefs.maxRecentRepos

        if len(self.repos) > n:
            # Recreate self.repos with only the n most recent paths
            topPaths = self.getRecentRepoPaths(n)
            self.repos = {path: self.repos[path] for path in topPaths}

        if len(self.cloneHistory) > n:
            self.cloneHistory = self.cloneHistory[-n:]

    def addCloneUrl(self, url):
        with suppress(ValueError):
            self.cloneHistory.remove(url)
        # Insert most recent cloned URL first
        self.cloneHistory.insert(0, url)

    def clearCloneHistory(self):
        self.cloneHistory.clear()

    def drawSequenceNumber(self, increment=1):
        if self._maxSeq < 0 and self.repos:
            self._maxSeq = max(r.get('seq', -1) for r in self.repos.values())
        self._maxSeq += increment
        return self._maxSeq

    def invalidateSequenceNumber(self):
        self._maxSeq = -1


LAYOUT_CHANGES: dict[int, tuple[str, ...]] = {
    # Neutral's layout: a sidebar 296 px wide, and file lists 360 px wide
    # that give most of their height to the unstaged files
    1: ("Split_Side", "Split_DiffArea", "Split_Staging"),
}
"""
The splitters whose default sizes Neutral changed, by version of its layout.
Sizes saved under an earlier version are dropped once, the first time the app
shows Neutral, so that its defaults show; every other pane keeps the size it
was given. The other looks' defaults didn't change: they keep all sizes.
"""

LAYOUT_VERSION = max(LAYOUT_CHANGES)


def layoutChangesSince(version: int) -> set[str]:
    """The splitters whose defaults changed in the versions of Neutral's layout after `version`."""
    return {name for v, names in LAYOUT_CHANGES.items() if v > version for name in names}


@dataclasses.dataclass
class Session(PrefsFile):
    _filename = "session.json"

    tabs                        : list[str]             = dataclasses.field(default_factory=list)
    activeTabIndex              : int                   = -1
    windowGeometry              : bytes                 = b""
    splitterSizes               : dict[str, list[int]]  = dataclasses.field(default_factory=dict)
    layoutVersion               : int                   = 0
    """The version of Neutral's layout (LAYOUT_CHANGES) that splitterSizes have
    caught up with; 0 until the app has shown Neutral with them."""
    prefsPane                   : str                   = ""
    "The Settings pane shown last, so that Settings opens on it again."


# Initialize default prefs and history.
# The app should load the user's prefs with prefs.load() and history.load().
prefs = Prefs()
history = History()


def qtIsNativeMacosStyle():  # pragma: no cover
    if not MACOS:
        return False
    return prefs.qtStyle.lower() == "macos"


def getExternalEditorName():
    genericName = englishTitleCase(_("External editor"))
    return ToolPresets.getCommandName(prefs.externalEditor, genericName, ToolPresets.Editors)


def getDiffToolName():
    genericName = englishTitleCase(_("Diff tool"))
    return ToolPresets.getCommandName(prefs.externalDiff, genericName, ToolPresets.DiffTools)


def getMergeToolName():
    genericName = englishTitleCase(_("Merge tool"))
    return ToolPresets.getCommandName(prefs.externalMerge, genericName, ToolPresets.MergeTools)
