# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Built-in themes that (almost) don't depend on the desktop environment's style.

A theme is a bunch of color tokens that feed both a QPalette and theme.qss.
"""

from __future__ import annotations

import dataclasses
import enum
from contextlib import suppress
from pathlib import Path
from string import Template
from typing import NamedTuple

from gitfourchette.qt import *
from gitfourchette.toolbox import mixColors, relativeLuminance, contrastRatio


class ThemeName(enum.StrEnum):
    """
    Our built-in themes. These share the Prefs.qtStyle namespace with the
    native Qt style names (Breeze, Fusion, Windows...), so their values must
    not collide with anything QStyleFactory may return.
    """
    BuiltIn = "gitfourchette-builtin"


class ThemeVariant(enum.StrEnum):
    """
    Looks of the built-in theme, as a token in Prefs.qtStyle
    ("gitfourchette-builtin,dark,neutral"). Modern has no token of its own, so
    every qtStyle string written before variants existed still reads as Modern.
    """
    Modern = ""
    Neutral = "neutral"


DEFAULT_VARIANT = ThemeVariant.Neutral
"""
The look this build starts in. Prefs written before it had variants move to it
once (see Prefs.migrate); after that, Modern stays available in Settings.
"""


class ThemeAccent(enum.StrEnum):
    Blue = "#3daee9"
    Cyan = "#00d3b8"
    Green = "#3dd425"
    Yellow = "#e8cb2d"
    Orange = "#e9643a"
    Red = "#e93d58"
    Pink = "#e93a9a"
    Gray = "#686b6f"
    Indigo = "#926ee4"
    Purple = "#b875dc"


class StyleParts(NamedTuple):
    """A Prefs.qtStyle string, taken apart by parseStyle."""
    engine: str
    mode: str = ""
    accent: str = ""
    variant: str = ThemeVariant.Modern


def parseStyle(styleName: str) -> StyleParts:
    """
    Split a Prefs.qtStyle string into (engine, mode, accent, variant).

    The engine is "" (system default), ThemeName.BuiltIn or a Qt style name.
    Only the built-in theme has a mode ("light", "dark", or "" to follow the
    system), an accent ("#rrggbb", or "" for the system's accent) and a variant
    (a ThemeVariant), e.g. "gitfourchette-builtin,dark,neutral,#e93d58". When a
    token repeats, the last one wins; a token nobody knows is ignored.

    Every reader and writer of qtStyle goes through this pair, so a value
    written in one place reads back the same everywhere else.
    """
    tokens = [t for t in styleName.split(",") if t]
    if not tokens:
        return StyleParts("")
    engine, rest = tokens[0], tokens[1:]
    modes = [t for t in rest if t in ("light", "dark")]
    accents = [t for t in rest if t.startswith("#")]
    variants = [t for t in rest if t in ThemeVariant]
    return StyleParts(engine,
                      modes[-1] if modes else "",
                      accents[-1] if accents else "",
                      ThemeVariant(variants[-1]) if variants else ThemeVariant.Modern)


def formatStyle(engine: str, mode: str = "", accent: str = "", variant: str = ThemeVariant.Modern) -> str:
    """The Prefs.qtStyle string for parseStyle's parts; the inverse of parseStyle."""
    if engine != ThemeName.BuiltIn:
        return engine
    return ",".join(t for t in (engine, mode, variant, accent) if t)


DEFAULT_BUILTIN_STYLE = formatStyle(ThemeName.BuiltIn, variant=DEFAULT_VARIANT)
"The built-in theme in the default look, light or dark as the system is."


def isDarkStyle(styleName: str) -> bool:
    """
    Whether this style string asks for a dark palette.

    A built-in theme carries its mode as a token ("gitfourchette-builtin,dark").
    Without one, or with any other Qt style, the system decides.
    """
    mode = parseStyle(styleName).mode
    if mode:
        return mode == "dark"
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # pragma: no cover - Qt < 6.5
        return False


def pinnedColorScheme(styleName: str) -> Qt.ColorScheme:
    """
    The color scheme that this style string pins the app to.

    Only the built-in theme carries a mode ("gitfourchette-builtin,dark").
    Anything else, including the built-in theme without a mode, follows the
    system, which Qt spells ColorScheme.Unknown.
    """
    engine, mode, _accent, _variant = parseStyle(styleName)
    if engine != ThemeName.BuiltIn:
        return Qt.ColorScheme.Unknown
    if mode == "dark":
        return Qt.ColorScheme.Dark
    if mode == "light":
        return Qt.ColorScheme.Light
    return Qt.ColorScheme.Unknown


def systemPrefersHighContrast() -> bool:
    """Whether the system asks for more contrast (e.g. Increase Contrast on macOS)."""
    try:
        preference = QGuiApplication.styleHints().accessibility().contrastPreference()
    except AttributeError:  # pragma: no cover - Qt < 6.10
        return False
    return preference == Qt.ContrastPreference.HighContrast


def withThemeMode(styleName: str, dark: bool) -> str:
    """
    Return `styleName` pinned to light or dark.

    Only the built-in theme has a mode to set, so asking a native Qt style to
    go dark switches to the built-in theme, in its default look - which is the
    honest reading of "make it dark" when the current style has no say in the
    matter. The accent and the variant stay: Neutral Light becomes Neutral
    Dark, not Modern Dark.
    """
    mode = "dark" if dark else "light"
    engine, _mode, accent, variant = parseStyle(styleName)

    if engine != ThemeName.BuiltIn:
        return formatStyle(ThemeName.BuiltIn, mode, variant=DEFAULT_VARIANT)

    return formatStyle(engine, mode, accent, variant)


@dataclasses.dataclass
class ThemeColors:
    bg: str
    surface: str
    altRow: str
    border: str
    text: str
    hover: str
    selInactive: str
    button: str
    scrollHandle: str
    tooltipBg: str
    tooltipText: str
    danger: str = "red"

    accent: str = ThemeAccent.Blue
    highContrast: bool = False
    "The system asks for more contrast: outlines get stronger and secondary text stops being dimmed."
    variant: str = ThemeVariant.Modern
    outerRadius: int = 7
    innerRadius: int = round(outerRadius * .75)

    # Metrics. The defaults are the Modern look's, which theme.qss used to spell out.
    buttonPadding: str = "5px 14px"
    toolButtonPadding: str = "3px 7px"
    fieldPadding: str = "4px 6px"
    tabPadding: str = "6px 12px"
    toolbarPadding: str = "4px 6px"
    toolbarBorderWidth: int = 1
    "Line under the main toolbar, in pixels."
    toolbarIconSize: int = 22
    "Main toolbar icons when the labels show (compact mode has its own size)."
    toolbarLabelDrop: float = 0
    "How many points smaller than the rest of the text the main toolbar's labels are."
    pillRadius: int = 7
    "Roundness of the tabs' pills (Neutral only)."
    sidebarRowHeight: str = "1.25em"
    fileRowHeight: str = "1.15em"
    scrollHandleMargin: str = "3px"
    "Room on each side of a scroll bar's handle, across the bar."

    # Colors that only some variants set; "" means derived from the colors above.
    fieldBg: str = ""
    "Inside of text fields and combo boxes."
    fieldBorder: str = ""
    "Outline of text fields and combo boxes."
    splitterHandle: str = ""
    "The line between panes that can be resized."
    panelHeader: str = ""
    "Background of panel headers, e.g. the strip naming what the lower half shows."
    tabTrack: str = ""
    tabTrackEdge: str = ""
    tabPill: str = ""
    "The current tab's pill (Neutral only)."
    tabPillEdge: str = ""
    tabActiveText: str = ""

    iconSet: str = ""
    "Subfolder of assets:icons whose redraws replace the icons of the same name."
    toolbarIconColor: str = ""
    "Main toolbar icons, if not the usual icon color. The labels under them use textDim."

    # Code and diffs, with the automatic syntax scheme only: a Pygments preset
    # picked in Settings keeps its own colors. "" keeps the preset's background
    # and mixes added/deleted lines from it.
    codeBg: str = ""
    diffAdd: str = ""
    diffDel: str = ""
    diffFiller: str = ""
    "Rows of a side-by-side diff that have no counterpart on the other side."
    diffHunkFg: str = ""
    "Hunk headers (@@ -1,3 +1,5 @@); \"\" draws them in blue italics."
    gutterText: str = ""
    "Line numbers next to the code, which then sit on its background; \"\" dims the text color."

    # All tokens below are inferred automatically. Do not define manually!
    onAccent: str = "white"
    defaultButton: str = "#f0f"
    defaultButtonHover: str = "#f0f"
    buttonHover: str = "#f0f"
    buttonPressed: str = "#f0f"
    tooltipBorder: str = "#f0f"
    textDim: str = "#f0f"
    textFaint: str = "#f0f"
    controlBorder: str = "#f0f"
    inputDisabled: str = "#f0f"
    light: str = "#f0f"
    midlight: str = "#f0f"
    mid: str = "#f0f"
    dark: str = "#f0f"
    shadow: str = "#f0f"

    # Engine-specific rounded rects
    menuRadius: int = outerRadius
    comboBoxMenuRadius: int = outerRadius

    # Engine-specific tokens. Meant to be prepended to a rule, e.g.:
    #     ${fusionOnly}QLabel {color: red}  /* red text only in Fusion */
    # The token is replaced with an empty string if the engine matches,
    # otherwise it's replaced with garbage so that the rule is ignored.
    fusionOnly: str = ""
    # Same idea for rules that only the Neutral variant has.
    neutralOnly: str = ""

    def __post_init__(self):
        """
        Derive intermediate colors automatically.
        """
        def mix(a: str, b: str, r=.5):
            return mixColors(QColor(a), QColor(b), r).name()

        def readableMix(ratio: float, minContrast: float) -> str:
            """
            The dimmest mix of text into surface, starting at `ratio`, that stands out
            from both the window and the surface by at least `minContrast`:1.
            """
            while True:
                color = mix(self.text, self.surface, ratio)
                if ratio <= 0 or all(contrastRatio(QColor(color), QColor(ground)) >= minContrast
                                     for ground in (self.bg, self.surface)):
                    return color
                ratio = round(ratio - .05, 2)

        # Determine whether 'onAccent' should be white or black.
        isDarkTheme = QColor(self.text).lightness() > QColor(self.surface).lightness()
        accentLuminance = relativeLuminance(QColor(self.accent))
        luminanceThreshold = .24 if isDarkTheme else .45

        # Menus, combobox lists, tooltips cannot be rounded with Fusion.
        # Breeze can round these, but draws menu shadows at a hardcoded radius,
        # which looks ugly if our radius is larger.
        engine = self.bestStyleEngine()
        maxMenuRadius = 7 if engine == "breeze" else 0

        self.defaultButton      = mix(self.button, self.accent, .25)
        self.defaultButtonHover = mix(self.button, self.accent, .33)
        self.buttonHover        = mix(self.button, self.text, .04)
        self.buttonPressed      = mix(self.button, self.accent, .66)
        self.tooltipBorder      = mix(self.tooltipText, self.tooltipBg, .8)
        # Secondary text still reads at 4.5:1 (WCAG AA); with more contrast asked for, it isn't dimmed at all.
        self.textDim            = self.text if self.highContrast else readableMix(.4, 4.5)
        self.textFaint          = mix(self.text, self.surface, .7)
        # Outline of checkboxes, radio buttons and fields: 3:1 against what's around it (WCAG
        # non-text contrast), 4.5:1 with more contrast asked for.
        self.controlBorder      = readableMix(.6, 4.5 if self.highContrast else 3.0)
        self.inputDisabled      = mix(self.bg, self.surface, .5)
        self.onAccent           = "white" if accentLuminance < luminanceThreshold else "black"

        # Colors a variant may leave out
        self.fieldBg            = self.fieldBg or self.surface
        self.fieldBorder        = self.fieldBorder or self.border
        self.splitterHandle     = self.splitterHandle or self.textFaint
        self.panelHeader        = self.panelHeader or mix(self.bg, self.text, .07)
        self.tabTrack           = self.tabTrack or mix(self.bg, self.text, .08)
        self.tabTrackEdge       = self.tabTrackEdge or self.border
        self.tabPill            = self.tabPill or self.button
        self.tabPillEdge        = self.tabPillEdge or self.border
        self.tabActiveText      = self.tabActiveText or self.text

        self.fusionOnly         = "" if engine == "fusion" else "___IGNORE"
        self.neutralOnly        = "" if self.variant == ThemeVariant.Neutral else "___IGNORE"
        self.menuRadius         = min(maxMenuRadius, self.outerRadius)
        self.comboBoxMenuRadius = min(maxMenuRadius, self.outerRadius)

        # Old-school 3D bevel/shadow colors. Derive from button.
        # Practically unused in Breeze, very rarely in Fusion, mostly in Windows.
        self.light              = QColor(self.button).lighter(200).name()
        self.midlight           = QColor(self.button).lighter(150).name()
        self.mid                = QColor(self.button).darker(150).name()
        self.dark               = QColor(self.button).darker(200).name()
        self.shadow             = QColor(self.button).darker(20).name()

    @classmethod
    def resolveTheme(cls, styleName: str, accent: QColor | None = None) -> ThemeColors | None:
        """
        Return the color tokens for one of our themes, or None if the input
        couldn't be parsed (e.g. if the given name is for a native Qt style).

        The input string must follow this format: "styleID,lightOrDark,variant,#accentHex"
        Example: "gitfourchette-builtin,dark,neutral,#ff00ff"

        Omit lightOrDark and/or #accentHex to infer colors from system palette.
        Omit the variant for the Modern look.
        The system's contrast preference (Increase Contrast on macOS) is honored too.
        """

        engine, _mode, accentToken, variant = parseStyle(styleName)

        if engine != ThemeName.BuiltIn:
            return None

        dark = isDarkStyle(styleName)
        if accentToken:
            accent = QColor(accentToken)

        light, darkTheme = BUILTIN_THEMES[variant]
        theme = darkTheme if dark else light
        if accent is not None:
            theme = dataclasses.replace(theme, accent=accent.name())
        if systemPrefersHighContrast():
            theme = dataclasses.replace(theme, highContrast=True)

        return theme

    @classmethod
    def bestStyleEngine(cls) -> str:
        """
        Return the name of the Qt style engine upon which to base custom themes,
        as a lowercase string. Favor "breeze", if available, for better-looking
        menus (with drop shadows and rounded corners) that "fusion" cannot do.
        """
        hasBreeze = any(key.lower() == "breeze" for key in QStyleFactory.keys())  # noqa: SIM118
        return "breeze" if hasBreeze else "fusion"

    def buildStyleSheet(self) -> str:
        templatePath = Path(QFile("assets:style/theme.qss").fileName())
        templateText = templatePath.read_text(encoding="utf-8")
        replacements = dataclasses.asdict(self)
        qss = Template(templateText).substitute(replacements)
        return qss

    def buildPalette(self) -> QPalette:
        Role = QPalette.ColorRole

        normal = {
            Role.Window: self.bg,
            Role.WindowText: self.text,
            Role.Base: self.surface,
            Role.AlternateBase: self.altRow,
            Role.Text: self.text,
            Role.Button: self.button,
            Role.ButtonText: self.text,
            Role.BrightText: self.danger,
            Role.Highlight: self.accent,
            Role.HighlightedText: self.onAccent,
            Role.ToolTipBase: self.tooltipBg,
            Role.ToolTipText: self.tooltipText,
            Role.PlaceholderText: self.textFaint,
            Role.Link: self.accent,
            Role.LinkVisited: self.accent,
            Role.Light: self.light,
            Role.Midlight: self.midlight,
            Role.Mid: self.mid,
            Role.Dark: self.dark,
            Role.Shadow: self.shadow,
        }

        inactive = {
            Role.Highlight: self.selInactive,
            Role.HighlightedText: self.text,
        }

        disabled = {
            Role.WindowText: self.textFaint,
            Role.Text: self.textFaint,
            Role.ButtonText: self.textFaint,
            Role.Highlight: self.selInactive,
            Role.HighlightedText: self.textDim,
            Role.Base: self.inputDisabled,
            Role.Link: self.textDim,
        }

        with suppress(AttributeError):  # Qt 6.6+
            normal[Role.Accent] = self.accent

        palette = QPalette()

        for role, color in normal.items():
            palette.setColor(role, QColor(color))
        for role, color in inactive.items():
            palette.setColor(QPalette.ColorGroup.Inactive, role, QColor(color))
        for role, color in disabled.items():
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))

        return palette


MODERN_DARK = ThemeColors(
    bg                = "#23262c",
    surface           = "#1b1e23",
    altRow            = "#1f2228",
    border            = "#444b55",
    text              = "#d7dbe1",
    hover             = "#12ffffff",
    selInactive       = "#343a44",
    button            = "#2c3138",
    scrollHandle      = "#2affffff",
    tooltipBg         = "#2f343c",
    tooltipText       = "#e4e7ec",
    danger            = "#ff6b60",
)

MODERN_LIGHT = ThemeColors(
    bg                = "#eef0f3",
    surface           = "#ffffff",
    altRow            = "#f7f8fa",
    border            = "#d2d6dd",
    text              = "#1f2329",
    hover             = "#10000000",
    selInactive       = "#dde1e8",
    button            = "#ffffff",
    scrollHandle      = "#38000000",
    tooltipBg         = "#2f343c",
    tooltipText       = "#f0f2f5",
    danger            = "#d92b1f",
)

# Neutral: flat grays with no blue in them, a denser layout and pill-shaped
# tabs. The dark colors were measured on a reference screenshot; the light
# ones are derived from them in the same ratios, not measured.
NEUTRAL_DARK = ThemeColors(
    variant            = ThemeVariant.Neutral,
    bg                 = "#242424",
    surface            = "#1c1c1c",
    altRow             = "#202020",
    border             = "#393939",
    text               = "#dedede",
    hover              = "#0fffffff",
    selInactive        = "#3d3d3d",
    button             = "#3e3e3e",
    scrollHandle       = "#669e9e9e",
    tooltipBg          = "#2e2e2e",
    tooltipText        = "#e2e2e2",
    danger             = "#ff6b60",
    outerRadius        = 5,
    innerRadius        = 5,
    pillRadius         = 12,
    buttonPadding      = "3px 12px",
    toolButtonPadding  = "2px 6px",
    fieldPadding       = "2px 6px",
    tabPadding         = "4px 12px",
    toolbarPadding     = "2px 8px",
    toolbarBorderWidth = 0,
    toolbarIconSize    = 16,
    toolbarLabelDrop   = 2,
    sidebarRowHeight   = "1.5em",
    fileRowHeight      = "1.4em",
    scrollHandleMargin = "2px",
    fieldBg            = "#242424",
    fieldBorder        = "#4a4a4a",
    splitterHandle     = "#393939",
    panelHeader        = "#2e2e2e",
    tabTrack           = "#363636",
    tabTrackEdge       = "#464646",
    tabPill            = "#3e3e3e",
    tabPillEdge        = "#646464",
    tabActiveText      = "#ebebeb",
    iconSet            = "neutral",
    toolbarIconColor   = "#e9e9e9",
    codeBg             = "#242424",
    diffAdd            = "#2f5138",
    diffDel            = "#5b3737",
    diffFiller         = "#3a3a3a",
    diffHunkFg         = "#8a8a8a",
    gutterText         = "#8b8b8b",
)

NEUTRAL_LIGHT = ThemeColors(
    variant            = ThemeVariant.Neutral,
    bg                 = "#f5f5f5",
    surface            = "#ffffff",
    altRow             = "#fafafa",
    border             = "#dcdcdc",
    text               = "#1f1f1f",
    hover              = "#10000000",
    selInactive        = "#dcdcdc",
    button             = "#ffffff",
    scrollHandle       = "#4d000000",
    tooltipBg          = "#2e2e2e",
    tooltipText        = "#f0f0f0",
    danger             = "#d92b1f",
    outerRadius        = 5,
    innerRadius        = 5,
    pillRadius         = 12,
    buttonPadding      = "3px 12px",
    toolButtonPadding  = "2px 6px",
    fieldPadding       = "2px 6px",
    tabPadding         = "4px 12px",
    toolbarPadding     = "2px 8px",
    toolbarBorderWidth = 0,
    toolbarIconSize    = 16,
    toolbarLabelDrop   = 2,
    sidebarRowHeight   = "1.5em",
    fileRowHeight      = "1.4em",
    scrollHandleMargin = "2px",
    fieldBorder        = "#c8c8c8",
    splitterHandle     = "#dcdcdc",
    panelHeader        = "#ededed",
    tabTrack           = "#e4e4e4",
    tabTrackEdge       = "#d0d0d0",
    tabPill            = "#ffffff",
    tabPillEdge        = "#c8c8c8",
    tabActiveText      = "#1f1f1f",
    iconSet            = "neutral",
    toolbarIconColor   = "#3a3a3a",
    codeBg             = "#f5f5f5",
    diffAdd            = "#dcf2e0",
    diffDel            = "#fbe1e1",
    diffFiller         = "#eeeeee",
    diffHunkFg         = "#8a8a8a",
    gutterText         = "#9a9a9a",
)

BUILTIN_THEMES: dict[str, tuple[ThemeColors, ThemeColors]] = {
    ThemeVariant.Modern: (MODERN_LIGHT, MODERN_DARK),
    ThemeVariant.Neutral: (NEUTRAL_LIGHT, NEUTRAL_DARK),
}
"(light, dark) for each variant of the built-in theme"


_activeTheme: ThemeColors | None = None


def activeTheme() -> ThemeColors | None:
    """The built-in theme's tokens as the app last applied them; None under a native Qt style."""
    return _activeTheme


def setActiveTheme(theme: ThemeColors | None):
    global _activeTheme
    _activeTheme = theme
