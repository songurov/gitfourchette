# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
WCAG contrast floors of the built-in theme, computed from its tokens.

Outlines of controls (checkboxes, radio buttons, fields): 3:1 against what's
around them, 4.5:1 when the system asks for more contrast. Secondary text:
4.5:1. Titles: 7:1.
"""

import dataclasses

import pytest

from gitfourchette import themes
from gitfourchette.themes import MODERN_DARK, MODERN_LIGHT, ThemeColors, ThemeName
from gitfourchette.toolbox import contrastRatio
from .util import *

THEMES = {"dark": MODERN_DARK, "light": MODERN_LIGHT}


def ratio(color1: str | QColor, color2: str | QColor) -> float:
    return contrastRatio(QColor(color1), QColor(color2))


@pytest.mark.parametrize("highContrast", [False, True], ids=["standard", "highContrast"])
@pytest.mark.parametrize("themeName", THEMES)
def testThemeTokensMeetContrastFloors(themeName, highContrast):
    theme = dataclasses.replace(THEMES[themeName], highContrast=highContrast)
    borderFloor = 4.5 if highContrast else 3.0

    for ground in (theme.bg, theme.surface):
        assert ratio(theme.controlBorder, ground) >= borderFloor
        assert ratio(theme.textDim, ground) >= 4.5
        assert ratio(theme.text, ground) >= 7.0


def testMoreContrastRemovesDimming():
    for theme in THEMES.values():
        stronger = dataclasses.replace(theme, highContrast=True)
        assert stronger.textDim == stronger.text
        assert ratio(stronger.controlBorder, theme.bg) > ratio(theme.controlBorder, theme.bg)


def testDarkSecondaryTextIsUnchanged():
    # It already read at 4.68:1; only the light theme's (3.71:1) had to darken
    assert MODERN_DARK.textDim == "#8c8f95"


def testThemeFollowsTheSystemContrastPreference(monkeypatch):
    styleName = f"{ThemeName.BuiltIn},dark"
    assert not ThemeColors.resolveTheme(styleName).highContrast

    monkeypatch.setattr(themes, "systemPrefersHighContrast", lambda: True)
    theme = ThemeColors.resolveTheme(styleName)
    assert theme.highContrast
    assert ratio(theme.controlBorder, theme.bg) >= 4.5


@pytest.mark.parametrize("themeName", THEMES)
def testUncheckedBoxOutlineIsVisible(mainWindow, themeName):
    styleName = f"{ThemeName.BuiltIn},{themeName}"
    GFApplication.applyPrefs(qtStyle=styleName)
    try:
        theme = ThemeColors.resolveTheme(styleName)
        dialog = QDialog(mainWindow)
        checkBox = QCheckBox("Unchecked", dialog)
        dialog.show()
        QTest.qWait(0)

        option = QStyleOptionButton()
        option.initFrom(checkBox)
        indicator = checkBox.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, checkBox)
        indicator.translate(checkBox.pos())
        image = dialog.grab().toImage()
        outline = image.pixelColor(indicator.left(), indicator.center().y())
        dialog.close()

        assert ratio(outline, theme.bg) >= 3.0
    finally:
        GFApplication.applyPrefs(qtStyle="")
