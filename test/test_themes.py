# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
The built-in theme's variants: Modern (the original look) and Neutral.
"""

import re

import pytest

from gitfourchette import settings
from gitfourchette.nav import NavLocator
from gitfourchette.themes import (
    MODERN_DARK, MODERN_LIGHT, NEUTRAL_DARK, NEUTRAL_LIGHT,
    ThemeColors, ThemeName, ThemeVariant, formatStyle, parseStyle, withThemeMode,
)
from .util import *

BUILTIN = str(ThemeName.BuiltIn)

ALL_THEMES = {
    "modernDark": MODERN_DARK,
    "modernLight": MODERN_LIGHT,
    "neutralDark": NEUTRAL_DARK,
    "neutralLight": NEUTRAL_LIGHT,
}


@pytest.mark.parametrize(["styleName", "expected"], [
    (f"{BUILTIN},dark", MODERN_DARK),
    (f"{BUILTIN},light", MODERN_LIGHT),
    (f"{BUILTIN},dark,neutral", NEUTRAL_DARK),
    (f"{BUILTIN},light,neutral", NEUTRAL_LIGHT),
    (f"{BUILTIN},neutral,dark", NEUTRAL_DARK),  # token order doesn't matter
    (f"{BUILTIN},dark,neutral,#e93d58", NEUTRAL_DARK),
    (f"{BUILTIN},dark,sepia", MODERN_DARK),  # an unknown variant is ignored
])
def testStyleStringPicksTheVariant(styleName, expected):
    theme = ThemeColors.resolveTheme(styleName)
    assert theme.variant == expected.variant
    assert theme.bg == expected.bg
    assert theme.surface == expected.surface


def testAccentAppliesOnTopOfTheVariant():
    theme = ThemeColors.resolveTheme(f"{BUILTIN},dark,neutral,#e93d58")
    assert theme.accent == "#e93d58"
    assert theme.bg == NEUTRAL_DARK.bg


def testVariantRoundTripsThroughTheParser():
    parts = parseStyle(f"{BUILTIN},light,neutral,#e93d58")
    assert parts == (BUILTIN, "light", "#e93d58", ThemeVariant.Neutral)
    assert formatStyle(*parts) == f"{BUILTIN},light,neutral,#e93d58"
    assert formatStyle(BUILTIN, "dark", variant=ThemeVariant.Neutral) == f"{BUILTIN},dark,neutral"
    # Modern has no token: strings written before variants existed are unchanged
    assert formatStyle(BUILTIN, "dark") == f"{BUILTIN},dark"
    assert parseStyle(f"{BUILTIN},dark").variant == ThemeVariant.Modern


def testLightDarkSwitchKeepsTheVariant():
    assert withThemeMode(f"{BUILTIN},light,neutral", True) == f"{BUILTIN},dark,neutral"
    assert withThemeMode(f"{BUILTIN},dark,neutral,#e93d58", False) == f"{BUILTIN},light,neutral,#e93d58"
    assert withThemeMode(f"{BUILTIN},neutral", True) == f"{BUILTIN},dark,neutral"
    assert withThemeMode(f"{BUILTIN},light", True) == f"{BUILTIN},dark"


@pytest.mark.parametrize("themeName", ALL_THEMES)
def testEveryThemeFillsEveryTokenOfTheStyleSheet(mainWindow, themeName):
    # Template.substitute raises KeyError if a ${token} has no field
    qss = ALL_THEMES[themeName].buildStyleSheet()
    assert "${" not in qss
    assert not re.search(r"#f0f(?![0-9a-f])", qss), "a derived token was left at its placeholder"


def testNeutralRulesOnlyApplyToNeutral(mainWindow):
    modern = MODERN_DARK.buildStyleSheet()
    neutral = NEUTRAL_DARK.buildStyleSheet()
    # The Neutral-only rules are there in both, but disarmed in Modern
    assert re.search(r"^___IGNOREQTabWidget2 QTabBar \{", modern, re.MULTILINE)
    assert re.search(r"^QTabWidget2 QTabBar \{", neutral, re.MULTILINE)
    assert not re.search(r"^___IGNOREQTabWidget2", neutral, re.MULTILINE)


@pytest.mark.parametrize("theme", [MODERN_DARK, MODERN_LIGHT], ids=["dark", "light"])
def testModernKeepsItsMetrics(mainWindow, theme):
    """These used to be spelled out in theme.qss; Modern must look exactly as it did."""
    qss = theme.buildStyleSheet()
    for rule in ["padding: 5px 14px;",  # QPushButton
                 "padding: 3px 7px;",  # QToolButton
                 "padding: 6px 12px;",  # QTabBar::tab
                 "border-bottom: 1px solid " + theme.border,  # QToolBar
                 "border: 1px solid " + theme.border,  # text fields
                 "Sidebar::item { height: 1.25em; }",
                 "margin: 1px 3px;",  # scroll bar handle
                 ]:
        assert rule in qss
    assert theme.outerRadius == 7
    assert theme.innerRadius == 5
    # Colors that Neutral sets on its own are Modern's usual ones
    assert theme.fieldBg == theme.surface
    assert theme.fieldBorder == theme.border
    assert theme.splitterHandle == theme.textFaint


def testNeutralTokens():
    # Measured on the reference screenshot (dark)
    assert (NEUTRAL_DARK.bg, NEUTRAL_DARK.surface, NEUTRAL_DARK.border) == ("#242424", "#1c1c1c", "#393939")
    assert NEUTRAL_DARK.selInactive == "#3d3d3d"
    # Derived tokens land close to the reference's secondary and placeholder text
    assert NEUTRAL_DARK.textDim == "#909090"  # reference: #919191
    assert NEUTRAL_DARK.textFaint == "#565656"  # reference: #535353
    for theme in NEUTRAL_DARK, NEUTRAL_LIGHT:
        assert theme.outerRadius == 5
        assert theme.toolbarBorderWidth == 0


@pytest.mark.parametrize("variant", ["", "neutral"])
def testVariantSwitchesLive(mainWindow, variant):
    styleName = formatStyle(BUILTIN, "dark", variant=variant)
    expected = NEUTRAL_DARK if variant else MODERN_DARK
    GFApplication.applyPrefs(qtStyle=styleName)
    try:
        assert QApplication.palette().color(QPalette.ColorRole.Window).name() == expected.bg
        assert QApplication.palette().color(QPalette.ColorRole.Base).name() == expected.surface
    finally:
        GFApplication.applyPrefs(qtStyle="")


def testToolbarThemeSwitchKeepsNeutral(mainWindow):
    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},light,neutral")
    try:
        toolbar = mainWindow.mainToolBar
        mainWindow.refreshThemeButton()
        toolbar.fillThemeMenu()
        triggerMenuAction(toolbar.themeMenu, "dark")
        assert settings.prefs.qtStyle == f"{BUILTIN},dark,neutral"
        assert QApplication.palette().color(QPalette.ColorRole.Window).name() == NEUTRAL_DARK.bg
    finally:
        GFApplication.applyPrefs(qtStyle="")


def _openDiff(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "On master\nOn master\nnew line\n")
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("master.txt"), check=True)
    return rw


def _diffColors(rw):
    from gitfourchette.diffview.diffdocument import DiffTextFormats
    document = rw.diffView.document()
    added = document.find("new line").block()
    hunk = document.firstBlock()
    assert hunk.text().startswith("@@")
    gutter = rw.diffView.gutter.grab().toImage()
    return {
        "bg": rw.diffView.palette().color(QPalette.ColorRole.Base).name(),
        "add": added.blockFormat().background().color().name(),
        "hunk": DiffTextFormats.hunkCF.foreground().color().name(),
        "hunkItalic": DiffTextFormats.hunkCF.fontItalic(),
        "gutterBg": gutter.pixelColor(2, 2).name(),
    }


def testNeutralDiffColorsWithTheAutomaticScheme(tempDir, mainWindow):
    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral", syntaxHighlighting="")
    try:
        rw = _openDiff(tempDir, mainWindow)
        assert _diffColors(rw) == {
            "bg": NEUTRAL_DARK.codeBg,
            "add": NEUTRAL_DARK.diffAdd,
            "hunk": NEUTRAL_DARK.diffHunkFg,
            "hunkItalic": False,
            "gutterBg": NEUTRAL_DARK.codeBg,  # the line numbers sit on the code's background
        }
    finally:
        GFApplication.applyPrefs(qtStyle="")


@pytest.mark.parametrize("prefs", [
    {"qtStyle": f"{BUILTIN},dark,neutral", "syntaxHighlighting": "stata-dark"},  # a preset, picked by name
    {"qtStyle": f"{BUILTIN},dark"},  # Modern
], ids=["preset", "modern"])
def testDiffColorsThatNeutralLeavesAlone(tempDir, mainWindow, prefs):
    import pygments.styles
    from gitfourchette.toolbox import mixColors
    GFApplication.applyPrefs(**prefs)
    try:
        rw = _openDiff(tempDir, mainWindow)
        presetBg = pygments.styles.get_style_by_name("stata-dark").background_color
        assert _diffColors(rw) == {
            "bg": presetBg,
            "add": mixColors(QColor(presetBg), QColor(0x55ff55), .35).name(),
            "hunk": QColor(0x1090ff).name(),  # colors.blue.lighter(125)
            "hunkItalic": True,
            "gutterBg": QApplication.palette().color(QPalette.ColorRole.Base).darker(105).name(),
        }
    finally:
        GFApplication.applyPrefs(qtStyle="", syntaxHighlighting="")


def testColorblindDiffColorsWinOverNeutral(tempDir, mainWindow):
    from gitfourchette import colors
    from gitfourchette.toolbox import mixColors
    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral", colorblind=True)
    try:
        rw = _openDiff(tempDir, mainWindow)
        assert _diffColors(rw)["add"] == mixColors(QColor(NEUTRAL_DARK.codeBg), colors.teal, .35).name()
    finally:
        GFApplication.applyPrefs(qtStyle="", colorblind=False)


def testNeutralSideBySideFillerRows(tempDir, mainWindow):
    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral")
    try:
        rw = _openDiff(tempDir, mainWindow)
        GFApplication.applyPrefs(sideBySideDiff=True)
        oldView = rw.diffArea.sideBySideDiffView.oldView
        # "new line" has nothing across from it: the old side shows a filler row
        backgrounds = set()
        block = oldView.document().firstBlock()
        while block.isValid():
            if not block.text():
                backgrounds.add(block.blockFormat().background().color().name())
            block = block.next()
        assert NEUTRAL_DARK.diffFiller in backgrounds
    finally:
        GFApplication.applyPrefs(qtStyle="", sideBySideDiff=False)


DUCK = "class Duck:\n    def quack(self):\n        return 'quack'\n\n    def waddle(self):\n        pass\n"
EDITED_DUCK = DUCK.replace("'quack'", "'honk'") + "\n    def fly(self):\n        return None"  # no newline at the end


def _openDuckDiff(tempDir, mainWindow, repoName="TestGitRepository"):
    """A diff with syntax, a changed line next to its old self, added lines and no newline at the end."""
    wd = unpackRepo(tempDir, renameTo=repoName)
    writeFile(f"{wd}/duck.py", DUCK)
    with RepoContext(wd) as repo:
        repo.index.add("duck.py")
        repo.index.write()
    writeFile(f"{wd}/duck.py", EDITED_DUCK)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("duck.py"), check=True)
    waitUntilTrue(lambda: rw.diffView.highlighter.newLexJob.lexingComplete, interval=0)
    QTest.qWait(0)  # let the highlighter catch up
    return rw


def _duckColors(diffView):
    """The colors in an open diff of the duck, as its document and its highlighter hold them."""
    document = diffView.document()

    def line(text) -> QTextBlock:
        block = document.find(text).block()
        assert block.isValid(), text
        return block

    def fragmentFormat(block, text) -> QTextCharFormat:
        return next(f.charFormat() for f in block.fragments() if text in f.text())

    def emphasis(block) -> str:
        brushes = [f.charFormat().background() for f in block.fragments()]
        return next(b.color().name() for b in brushes if b.style() != Qt.BrushStyle.NoBrush)

    def syntax(block, text) -> str:
        start = block.text().index(text)
        return next(r.format.foreground().color().name() for r in block.layout().formats() if r.start == start)

    hunk = document.firstBlock()
    assert hunk.text().startswith("@@")
    hunkFormat = fragmentFormat(hunk, "@@")
    trailerFormat = fragmentFormat(line("return None"), "<no newline")
    return {
        "background": diffView.palette().color(QPalette.ColorRole.Base).name(),
        "added": line("def fly").blockFormat().background().color().name(),
        "deleted": line("'quack'").blockFormat().background().color().name(),
        "emphasis": emphasis(line("'honk'")),
        "hunk": (hunkFormat.foreground().color().name(), hunkFormat.fontItalic()),
        "trailer": trailerFormat.foreground().color().name(),
        "keyword": syntax(line("def fly"), "def"),
        "string": syntax(line("'honk'"), "'honk'"),
    }


@pytest.mark.parametrize("variant", ["neutral", ""], ids=["neutral", "modern"])
def testThemeSwitchRepaintsTheOpenDiffs(tempDir, mainWindow, variant):
    """
    A diff that's open when the theme goes from dark to light (the toolbar's
    switch, or Settings) looks as if it had been opened in light, in every
    tab, and back again.
    """
    from gitfourchette.nav import NavFlags

    dark = formatStyle(BUILTIN, "dark", variant=variant)
    light = formatStyle(BUILTIN, "light", variant=variant)
    GFApplication.applyPrefs(qtStyle=dark, syntaxHighlighting="")
    try:
        otherTab = _openDuckDiff(tempDir, mainWindow, "OtherTab")
        rw = _openDuckDiff(tempDir, mainWindow)
        assert mainWindow.currentRepoWidget() is rw
        darkColors = _duckColors(rw.diffView)
        assert _duckColors(otherTab.diffView) == darkColors

        GFApplication.applyPrefs(qtStyle=light)
        lightColors = _duckColors(rw.diffView)
        assert _duckColors(otherTab.diffView) == lightColors
        changed = {key for key in darkColors if lightColors[key] != darkColors[key]}
        assert changed >= {"background", "added", "deleted", "emphasis", "trailer", "keyword", "string"}
        if variant:
            assert lightColors["background"] == NEUTRAL_LIGHT.codeBg
            assert lightColors["added"] == NEUTRAL_LIGHT.diffAdd
            assert lightColors["deleted"] == NEUTRAL_LIGHT.diffDel

        # Exactly what the diff looks like when it's opened in light
        rw.jump(NavLocator.inUnstaged("duck.py").withExtraFlags(NavFlags.ForceRecreateDocument), check=True)
        QTest.qWait(0)  # let the highlighter go over the new document
        assert rw.diffView.document() is not otherTab.diffView.document()
        assert _duckColors(rw.diffView) == lightColors

        GFApplication.applyPrefs(qtStyle=dark)
        assert _duckColors(rw.diffView) == darkColors
        assert _duckColors(otherTab.diffView) == darkColors
    finally:
        GFApplication.applyPrefs(qtStyle="")


def testOnlyANewLookRepaintsTheDiff(tempDir, mainWindow):
    tabSpaces = settings.prefs.tabSpaces
    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral", syntaxHighlighting="")
    try:
        rw = _openDuckDiff(tempDir, mainWindow)
        recolored = []
        rw.diffView.documentRecolored.connect(recolored.append)

        GFApplication.applyPrefs(tabSpaces=tabSpaces + 1)
        assert recolored == []

        undoSteps = rw.diffView.document().availableUndoSteps()
        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},light,neutral")
        assert recolored == [rw.diffView.currentDiffDocument]
        # Nobody undoes a diff's colors: repainting doesn't keep a step per line
        assert rw.diffView.document().availableUndoSteps() <= undoSteps
    finally:
        GFApplication.applyPrefs(qtStyle="", tabSpaces=tabSpaces)


def testDiffBuiltBeforeAThemeSwitchIsPaintedInTheNewTheme(tempDir, mainWindow):
    """A diff is built on a worker thread: the theme may change before it's shown."""
    from gitfourchette.diffview.diffdocument import DiffDocument

    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral", syntaxHighlighting="")
    try:
        rw = _openDuckDiff(tempDir, mainWindow)
        view = rw.diffView
        document = DiffDocument.fromPatch("@@ -1 +1 @@\n-old\n+new\n")

        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},light,neutral")
        view.replaceDocument(rw.repo, view.currentDelta, view.currentLocator, document)
        assert view.document().find("new").block().blockFormat().background().color().name() == NEUTRAL_LIGHT.diffAdd
    finally:
        GFApplication.applyPrefs(qtStyle="")


def testThemeSwitchRepaintsTheSideBySideDiff(tempDir, mainWindow):
    def rowColors(view: QPlainTextEdit) -> dict[str, str]:
        rows = {}
        block = view.document().firstBlock()
        while block.isValid():
            brush = block.blockFormat().background()
            key = block.text().split(maxsplit=2)[-1] if block.text() else f"filler{len(rows)}"
            rows[key] = brush.color().name() if brush.style() != Qt.BrushStyle.NoBrush else ""
            block = block.next()
        return rows

    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral", syntaxHighlighting="", sideBySideDiff=True)
    try:
        rw = _openDuckDiff(tempDir, mainWindow)
        side = rw.diffArea.sideBySideDiffView
        assert side.isVisible()
        oldView, newView = side.oldView, side.newView
        newView.verticalScrollBar().setValue(1)
        scroll = newView.verticalScrollBar().value()

        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},light,neutral")
        old, new = rowColors(oldView), rowColors(newView)
        assert old["return 'quack'"] == NEUTRAL_LIGHT.diffDel
        assert new["return 'honk'"] == NEUTRAL_LIGHT.diffAdd
        assert new["def fly(self):"] == NEUTRAL_LIGHT.diffAdd
        fillers = {color for key, color in old.items() if key.startswith("filler")}
        assert fillers == {NEUTRAL_LIGHT.diffFiller}
        assert newView.verticalScrollBar().value() == scroll  # painted in place

        # Modern has no filler color: filler rows lose Neutral's
        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},light")
        fillers = {color for key, color in rowColors(oldView).items() if key.startswith("filler")}
        assert fillers == {""}
    finally:
        GFApplication.applyPrefs(qtStyle="", sideBySideDiff=False)


def testThemeSwitchRedrawsTheSpecialDiffPage(tempDir, mainWindow):
    from gitfourchette.diffview.specialdiffview import secondaryTextColor

    def detailsColor(view) -> str:
        cursor = view.document().find("Renamed:")
        assert not cursor.isNull()
        return cursor.charFormat().foreground().color().name()

    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral", syntaxHighlighting="")
    try:
        wd = unpackRepo(tempDir)
        shell("git mv master.txt mastiff.txt", wd)
        rw = mainWindow.openRepo(wd)
        rw.jump(NavLocator.inStaged("mastiff.txt"), check=True)
        view = rw.specialDiffView
        assert view.isVisible()
        darkDetails = detailsColor(view)
        assert darkDetails == secondaryTextColor(*view.textColors()).name()

        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},light,neutral")
        assert detailsColor(view) == secondaryTextColor(*view.textColors()).name()
        assert detailsColor(view) != darkDetails
    finally:
        GFApplication.applyPrefs(qtStyle="")


def testThemeSwitchRedrawsTheImageDiff(tempDir, mainWindow):
    import shutil

    def frameColors(view) -> list[str]:
        colors = []
        for frame in view.document().rootFrame().childFrames():
            for cell in frame.childFrames():
                colors.append(cell.frameFormat().borderBrush().color().name())
        return colors

    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral")
    try:
        wd = unpackRepo(tempDir)
        shutil.copyfile(getTestDataPath("image1.png"), f"{wd}/image.png")
        with RepoContext(wd) as repo:
            repo.index.add("image.png")
            repo.index.write()
        shutil.copyfile(getTestDataPath("image2.png"), f"{wd}/image.png")
        rw = mainWindow.openRepo(wd)
        rw.jump(NavLocator.inUnstaged("image.png"), check=True)
        view = rw.specialDiffView
        assert view.isVisible()
        darkFrames = frameColors(view)
        assert darkFrames[-1] == QApplication.palette().color(QPalette.ColorRole.Mid).name()

        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},light,neutral")
        lightFrames = frameColors(view)
        assert lightFrames[-1] == QApplication.palette().color(QPalette.ColorRole.Mid).name()
        assert lightFrames[-1] != darkFrames[-1]
    finally:
        GFApplication.applyPrefs(qtStyle="")


def _toolbarLooks(mainWindow, iconId="git-settings"):
    from gitfourchette.toolbox import ActionDef
    toolbar = mainWindow.mainToolBar
    action = next(a for a in toolbar.actions() if a.property(ActionDef.IconProperty) == iconId)
    button: QToolButton = toolbar.widgetForAction(action)
    button.ensurePolished()
    image = action.icon().pixmap(16, 16).toImage()
    inked = [image.pixelColor(x, y) for x in range(16) for y in range(16) if image.pixelColor(x, y).alpha() == 255]
    return {
        "iconSize": toolbar.iconSize().width(),
        "labelPoints": button.font().pointSizeF(),
        "labelColor": button.palette().color(QPalette.ColorRole.ButtonText).name(),
        "iconColor": inked[0].name() if inked else "",
        "repoPoints": toolbar.repoButton.font().pointSizeF(),
    }


def testNeutralToolbarHasSmallBrightIconsOverShortDimLabels(mainWindow):
    from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine
    appPoints = QApplication.font().pointSizeF()

    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral", compactUi=False)
    try:
        assert _toolbarLooks(mainWindow) == {
            "iconSize": 16,
            "labelPoints": appPoints - 2,
            "labelColor": NEUTRAL_DARK.textDim,
            "iconColor": NEUTRAL_DARK.toolbarIconColor,
            "repoPoints": appPoints,  # the repo and branch aren't a label
        }
        # The button that shows the theme gets the same bright icon
        assert _toolbarLooks(mainWindow, "theme-dark")["iconColor"] == NEUTRAL_DARK.toolbarIconColor

        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark")
        assert _toolbarLooks(mainWindow) == {
            "iconSize": 22,
            "labelPoints": appPoints,
            "labelColor": MODERN_DARK.text,
            "iconColor": RecolorSvgIconEngine.IconColors.mainColor.name(),
            "repoPoints": appPoints,
        }
    finally:
        GFApplication.applyPrefs(qtStyle="")


class _PrefsFile:
    """A prefs.json of our own, written as an earlier build would have."""

    def __init__(self):
        from gitfourchette.settings import Prefs

        class OldPrefs(Prefs):
            _filename = "prefs-neutral-migration-test.json"

        self.prefsClass = OldPrefs
        self.path = Path(OldPrefs().getParentDir(), OldPrefs._filename)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self, content: dict | None):
        import json
        if content is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_text(json.dumps(content), encoding="utf-8")
        prefs = self.prefsClass()
        prefs.load()
        return prefs

    def written(self, prefs) -> dict:
        import json
        prefs.write()
        return json.loads(self.path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(["before", "after"], [
    (f"{BUILTIN},dark", f"{BUILTIN},dark,neutral"),  # the toolbar's Theme > Dark
    (f"{BUILTIN},light", f"{BUILTIN},light,neutral"),
    (f"{BUILTIN}", f"{BUILTIN},neutral"),  # System colors
    (f"{BUILTIN},light,#e93d58", f"{BUILTIN},light,neutral,#e93d58"),
    (f"{BUILTIN},dark,neutral", f"{BUILTIN},dark,neutral"),
    ("Fusion", "Fusion"),  # a native style was picked on purpose
    ("", ""),  # System default: that's Neutral already
])
def testEarlierPrefsMoveToNeutral(mainWindow, before, after):
    file = _PrefsFile()
    try:
        prefs = file.load({"qtStyle": before, "tabSpaces": 8})
        assert prefs.qtStyle == after
        assert prefs.tabSpaces == 8
        assert prefs.migrations == ["neutralTheme"]
    finally:
        file.path.unlink()


def testTheOwnersPrefsMoveToNeutralDarkOnlyOnce(mainWindow):
    file = _PrefsFile()
    try:
        # prefs.json as this build's owner had it before Neutral
        prefs = file.load({
            "qtStyle": "gitfourchette-builtin,dark",
            "commitFormPlacement": "bottom-bar",
            "toolBarButtonStyle": 3,
            "toolBarIconSize": 22,
            "_version": "1.11.0",
        })
        assert prefs.qtStyle == f"{BUILTIN},dark,neutral"
        assert prefs.commitFormPlacement == "bottom-bar"
        assert prefs.isDirty(), "the move must be saved"
        saved = file.written(prefs)
        assert saved["qtStyle"] == f"{BUILTIN},dark,neutral"
        assert saved["migrations"] == ["neutralTheme"]

        # Going back to Modern afterwards sticks
        prefs.qtStyle = f"{BUILTIN},dark"
        prefs.setDirty()
        saved = file.written(prefs)
        prefs = file.load(saved)
        assert prefs.qtStyle == f"{BUILTIN},dark"
        assert not prefs.isDirty()
    finally:
        file.path.unlink()


def testFreshPrefsStartInNeutralFollowingTheSystem(mainWindow, monkeypatch):
    from gitfourchette import application
    from gitfourchette.themes import pinnedColorScheme

    file = _PrefsFile()
    prefs = file.load(None)
    assert prefs.qtStyle == ""  # System default
    assert prefs.migrations == ["neutralTheme"]  # nothing to move, now or later
    assert not prefs.isDirty()

    # Offscreen tests keep the boot style; elsewhere, System default means Neutral
    assert GFApplication.defaultStyleName("fusion") == ""
    monkeypatch.setattr(application, "OFFSCREEN", False)
    monkeypatch.setattr(application, "KDE", False)
    styleName = GFApplication.defaultStyleName("macos")
    assert ThemeColors.resolveTheme(styleName).variant == ThemeVariant.Neutral
    assert pinnedColorScheme(styleName) == Qt.ColorScheme.Unknown, "light or dark as the system is"


def testToolbarDarkFromANativeStyleAdoptsNeutral():
    assert withThemeMode("", True) == f"{BUILTIN},dark,neutral"
    assert withThemeMode("Fusion", False) == f"{BUILTIN},light,neutral"
