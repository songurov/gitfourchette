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
