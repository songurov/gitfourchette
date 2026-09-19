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
