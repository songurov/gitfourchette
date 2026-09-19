# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pathlib
import re

from .util import *


# Use mainWindow fixture to make sure the temp icon cache is properly reset
@pytest.mark.skipif(QT5, reason="Qt 5: can't specify devicePixelRatio in QIcon.pixmap()")
def testStockIconImgTagDpr(mainWindow):
    from gitfourchette.toolbox import iconbank

    def extractSrc(imgTag):
        return re.search(r"<img src='([^']+)'", imgTag).group(1)

    pixmap = QPixmap()

    # DPR=1 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=1)
    src = extractSrc(tag)
    assert src.startswith("assets:icons/")
    pixmap.load(src)
    assert pixmap.size() == QSize(16, 16)
    srcDpr1 = src

    # DPR=1 cache hit
    tag = iconbank.stockIconImgTag("git-head", dpr=1)
    src = extractSrc(tag)
    assert src == srcDpr1

    # DPR=2 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=2)
    src = extractSrc(tag)
    srcDpr2 = src
    assert src.startswith(qTempDir())
    pixmap.load(src)
    assert pixmap.size() == QSize(32, 32)

    # DPR=2 cache hit
    tag = iconbank.stockIconImgTag("git-head", dpr=2)
    src = extractSrc(tag)
    assert src == srcDpr2

    # DPR=1.5 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=1.5)
    src = extractSrc(tag)
    pixmap.load(src)
    assert pixmap.size() == QSize(24, 24)


def _rendered(icon: QIcon) -> QImage:
    return icon.pixmap(16, 16).toImage()


def testTaskIconsAreAllOurOwn(mainWindow):
    """Every task that shows an icon must have one of ours to show."""

    from gitfourchette.tasks.taskbook import TaskBook
    from gitfourchette.toolbox import stockIcon

    assert TaskBook.icons, "expecting the task book to name some icons"
    for taskClass, iconId in TaskBook.icons.items():
        assert not stockIcon(iconId).isNull(), f"{taskClass.__name__} wants a missing icon {iconId!r}"


def _iconNamesInTheCode() -> dict[str, str]:
    """
    Icon names the code spells out: the first argument of stockIcon() and
    stockIconImgTag(), and whatever is assigned to a variable or keyword named
    like an icon (icon=, buttonIcon=, iconKey = ...). Returns {name: where}.
    """

    import typing
    from gitfourchette.toolbox.messageboxes import MessageBoxIconName

    call = re.compile(r"""\bstockIcon(?:ImgTag)?\(\s*["']([^"'{}]+)["']""")
    assignment = re.compile(r"""\b(\w+)\s*(?::\s*[\w.\[\]| ]+)?=\s*["']([^"'{}]*)["']""")
    iconVariable = re.compile(r"icon|iconName|iconKey|_Icon[A-Z]\w*|\w*[a-z]Icon(?:Name|Key)?")
    # Message boxes take their icon by one of these names, not from our icon bank
    messageBoxIcons = set(typing.get_args(MessageBoxIconName))

    sourceDir = pathlib.Path(__file__).parents[1] / "gitfourchette"
    names = {}
    for path in sorted(sourceDir.rglob("*.py")):
        for lineNumber, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            where = f"{path.relative_to(sourceDir)}:{lineNumber}"
            for name in call.findall(line):
                names.setdefault(name, where)
            for variable, name in assignment.findall(line):
                if iconVariable.fullmatch(variable) and name and name not in messageBoxIcons:
                    names.setdefault(name, where)
    return names


def testEveryIconNamedInTheCodeExists(mainWindow):
    """
    stockIcon() only notices a missing icon when the code asking for it runs,
    and some of those paths (a menu, an error page) no test ever opens. Every
    name spelled out in the code must lead to an icon of ours or a Qt one.
    """

    from gitfourchette.toolbox import stockIcon
    from gitfourchette.toolbox.appstyle import AppStyle

    # Qt's standard icons come from the style. The app always wraps its style
    # in AppStyle, but offscreen tests keep the bare boot style, so ask
    # AppStyle directly, as the app would.
    appStyle = AppStyle("fusion")

    def resolve(name: str) -> QIcon:
        if name.startswith("SP_"):
            return appStyle.standardIcon(getattr(QStyle.StandardPixmap, name))
        return stockIcon(name)

    names = _iconNamesInTheCode()
    # If the scan quietly stopped matching, this test would pass on nothing
    assert len(names) > 80
    assert names.keys() >= {"git-fetch", "view-hidden", "SP_TrashIcon", "achtung", "magnifying-glass-wait"}

    missing = []
    for name, where in names.items():
        try:
            icon = resolve(name)
        except AssertionError:  # APP_TESTMODE: "no icon of our own"
            missing.append(f"{name} ({where})")
            continue
        if icon.isNull():
            missing.append(f"{name} ({where})")
    assert not missing


def testForeignIconNamesNeverReachTheDesktopTheme(mainWindow):
    """
    The app still calls some icons by their freedesktop names. Left to the
    desktop's icon theme, those come out in somebody else's style - usually
    full color, next to our flat line art.
    """

    from gitfourchette.toolbox import stockIcon

    assert _rendered(stockIcon("vcs-branch")) == _rendered(stockIcon("git-branch"))
    assert _rendered(stockIcon("user-identity")) == _rendered(stockIcon("git-identity"))
    assert _rendered(stockIcon("application-exit")) == _rendered(stockIcon("exit"))
    assert _rendered(stockIcon("SP_TrashIcon")) == _rendered(stockIcon("trash"))

    # A name we have no answer for fails here, rather than in a screenshot
    with pytest.raises(AssertionError):
        stockIcon("document-new")


def testEverySemanticIconUsesTheMonochromePalette():
    """Action and status icons must not quietly bring back hardcoded hues."""

    iconDir = pathlib.Path(__file__).parents[1] / "gitfourchette/assets/icons"
    semanticIcons = [
        "achtung", "git-discard", "git-discard-lines", "git-head-detached",
        "git-stage", "git-stage-lines", "git-unstage", "git-unstage-lines",
        "go-newer", "go-older", "gpg-verify-bad", "gpg-verify-cantcheck",
        "gpg-verify-expired", "gpg-verify-good-trusted", "gpg-verify-good-untrusted",
        "input-validated", "sigkill", "urgent-tab",
        # Not the status tiles: they're colored on purpose, see testStatusTilesAreColored
    ]
    hardcodedColor = re.compile(
        r"#[0-9a-f]{3,8}|(?:fill|stroke)(?:=|:)['\"]?(?:red|green|orange|yellow|blue|purple)",
        re.IGNORECASE)
    for iconName in semanticIcons:
        svg = (iconDir / f"{iconName}.svg").read_text()
        assert not hardcodedColor.search(svg), iconName


def testStatusIconGeneratorReproducesCommittedIcons():
    """
    `update_resources.py -u` rewrites the status tiles. If its template drifts
    from the icons in the repo, running it silently reverts their design.
    """

    import importlib.util

    rootDir = pathlib.Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location("update_resources", rootDir / "update_resources.py")
    updateResources = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updateResources)

    iconDir = rootDir / "gitfourchette/assets/icons"
    for status, (glyph, color) in updateResources.STATUS_ICONS.items():
        svg = (iconDir / f"status_{status.lower()}.svg").read_text()
        assert updateResources.statusIconSvg(glyph, color) == svg, status


def _statusIcons():
    import importlib.util
    rootDir = pathlib.Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location("update_resources", rootDir / "update_resources.py")
    updateResources = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updateResources)
    return updateResources.STATUS_ICONS


def _contrastWithWhite(color: str) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    qc = QColor(color)
    luminance = 0.2126 * channel(qc.red()) + 0.7152 * channel(qc.green()) + 0.0722 * channel(qc.blue())
    return 1.05 / (luminance + 0.05)


def testStatusTilesAreColored():
    """
    A file list is scanned by hue first: every status gets its own color, and
    the white glyph on it stays legible (WCAG 3:1, bold text).
    """
    icons = _statusIcons()
    colors = [color.lower() for _glyph, color in icons.values()]
    assert len(set(colors)) == len(colors), "two statuses share a color"
    for status, (_glyph, color) in icons.items():
        assert _contrastWithWhite(color) >= 3.0, (status, color)


def testStatusTilesLookTheSameOnDarkThemes(mainWindow):
    """The glyph must not be swapped to black by the dark variants: the tile brings its own background."""
    from gitfourchette.toolbox import iconbank
    from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine

    def render(iconId: str) -> QImage:
        return iconbank.stockIcon(iconId).pixmap(32, 32).toImage()

    colors = RecolorSvgIconEngine.IconColors
    before = colors.preferDarkVariants
    try:
        colors.preferDarkVariants = False
        light = render("status_m")
        colors.preferDarkVariants = True
        iconbank._stockIconCache.clear()
        dark = render("status_m")
    finally:
        colors.preferDarkVariants = before
        iconbank._stockIconCache.clear()
    assert light == dark
    # A corner of the tile, clear of the glyph, shows the tile's own color
    corner = light.pixelColor(5, 28)
    assert corner.name() == QColor(_statusIcons()["M"][1]).name()


# -----------------------------------------------------------------------------
# Line icons for the neutral look

_iconDir = pathlib.Path(__file__).parents[1] / "gitfourchette/assets/icons"

# New icons drawn for the neutral look. Nothing else draws these names.
NEW_LINE_ICONS = [
    "ai-sparkle", "close-small", "commit-history", "diff-side-by-side", "doc", "eye-files",
    "filter", "folder-filled", "git-folder-open", "more-circle", "open-in", "quick-launch",
    "sidebar-all-commits", "sidebar-left", "sidebar-local-changes", "view-list-tree",
]

# The neutral look's redraws of icons that keep their current drawing in every
# other look. Each lives in icons/neutral/ under the name of the icon it redraws.
NEUTRAL_REDRAWS = [
    "chevron-down", "chevron-right", "chevron-up", "git-fetch", "git-pull", "git-push",
    "git-stash", "git-workspace", "theme-dark", "theme-light",
]

LINE_ICONS = NEW_LINE_ICONS + [f"neutral/{name}" for name in NEUTRAL_REDRAWS]


def testLineIconsAreDrawnForRecoloring():
    """
    The line icons share a 16x16 grid and one stroke weight, and bring no color
    of their own: only `gray`, which RecolorSvgIconEngine replaces with the
    palette's icon color (or a caller's). So they follow the dark and light
    themes, and colorblind mode, which only changes the diff's line colors,
    can't make two of them look alike.
    """

    from xml.etree import ElementTree

    for iconId in LINE_ICONS:
        svg = (_iconDir / f"{iconId}.svg").read_text("utf-8")

        # The engine slips an opacity group in after the first '>' and fills in
        # the colors with str.format_map: nothing may come before <svg>, and no braces.
        assert svg.startswith("<svg "), iconId
        assert not set("{}") & set(svg), iconId

        root = ElementTree.fromstring(svg)
        assert root.tag == "{http://www.w3.org/2000/svg}svg", iconId
        assert root.get("viewBox") == "0 0 16 16", iconId

        # One weight, set once for the whole icon (see testLineIconsKeepTheirShapeAt1x)
        assert root.get("stroke-width") == "1.01", iconId
        elements = list(root.iter())
        assert not [e.tag for e in elements[1:] if e.get("stroke-width")], iconId

        # Colors only through the attributes the engine rewrites
        assert "#" not in svg, iconId
        assert not [e.tag for e in elements if e.get("style")], iconId
        colors = {e.get(attribute) for e in elements for attribute in ("fill", "stroke")} - {None}
        assert colors == {"gray", "none"}, iconId


def testNeutralRedrawsHaveTheNameOfAnExistingIcon():
    """
    A file in icons/neutral/ redraws the icon of the same name for the neutral
    look. One without a counterpart would be a new icon filed in the wrong place.
    """

    from xml.etree import ElementTree

    assert sorted(p.name for p in (_iconDir / "neutral").iterdir()) == sorted(f"{n}.svg" for n in NEUTRAL_REDRAWS)
    for name in NEUTRAL_REDRAWS:
        assert (_iconDir / f"{name}.svg").is_file(), name
    for name in NEW_LINE_ICONS:
        assert not (_iconDir / "neutral" / f"{name}.svg").exists(), name

    # chevron-right joins chevron-up/down in every other look: painted in place
    # of chevron-down when a node collapses, it must weigh the same
    def strokeWidth(iconId):
        return ElementTree.parse(_iconDir / f"{iconId}.svg").getroot().get("stroke-width")
    assert strokeWidth("chevron-right") == strokeWidth("chevron-down")


def testLineIconsFollowThePalette(mainWindow):
    from gitfourchette.toolbox import iconbank
    from gitfourchette.toolbox.qtutils import mixColors
    from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine

    iconColors = RecolorSvgIconEngine.IconColors

    def usePalette(background: str, foreground: str):
        iconColors.background = QColor(background)
        iconColors.foreground = QColor(foreground)
        iconColors.highlight = QColor("#ffffff")
        iconColors.mainColor = mixColors(iconColors.background, iconColors.foreground, .58)
        iconColors.initialized = True
        iconbank._stockIconCache.clear()
        QPixmapCache.clear()

    def strayColors(iconId: str, expected: QColor, colorTable="", mode=QIcon.Mode.Normal) -> list[str]:
        icon = iconbank.stockIcon(iconId, colorTable)
        image = icon.pixmap(QSize(32, 32), mode).toImage().convertToFormat(QImage.Format.Format_ARGB32)
        drawn = [image.pixelColor(x, y) for y in range(image.height()) for x in range(image.width())]
        drawn = [c for c in drawn if c.alpha() >= 128]  # un-premultiplied colors are exact enough there
        assert len(drawn) >= 20, f"{iconId} draws nothing"
        return [c.name() for c in drawn
                if max(abs(c.red() - expected.red()), abs(c.green() - expected.green()),
                       abs(c.blue() - expected.blue())) > 3]

    accent = QColor("#3bb7e6")
    try:
        for background, foreground in [("#262626", "#e6e6e6"), ("#f4f4f4", "#1c1c1c")]:
            usePalette(background, foreground)
            for iconId in LINE_ICONS:
                assert not strayColors(iconId, iconColors.mainColor), iconId
                assert not strayColors(iconId, iconColors.highlight, mode=QIcon.Mode.Selected), iconId
                assert not strayColors(iconId, accent, colorTable=f"gray={accent.name()}"), iconId
    finally:
        iconbank.clearStockIconCache()  # also makes the engine re-read the real palette
        QPixmapCache.clear()


def testLineIconsKeepTheirShapeAt1x(mainWindow):
    """
    Qt draws a pen no wider than one device pixel with its cosmetic stroker,
    which renders 45-degree lines lopsided: one arm of a chevron comes out
    crisp, the other smeared across two pixels. That's why the line icons are
    stroked 1.01 wide, not 1: at 16 px on a 1x screen, they go through Qt's
    regular stroker instead. A symmetric drawing must render symmetric.
    """

    from gitfourchette.toolbox import stockIcon

    def alpha(iconId: str) -> list[list[int]]:
        image = stockIcon(iconId).pixmap(QSize(16, 16)).toImage()
        assert image.size() == QSize(16, 16)  # 1x
        return [[image.pixelColor(x, y).alpha() for x in range(16)] for y in range(16)]

    # These are drawn around the center of pixel (8, 8), so pixel 16-i mirrors pixel i
    def leftRight(a):
        return [[row[16 - x] if x > 0 else 0 for x in range(16)] for row in a]

    def topBottom(a):
        return [a[16 - y] if y > 0 else [0] * 16 for y in range(16)]

    for iconId in ["neutral/chevron-down", "neutral/chevron-up", "close-small"]:
        assert alpha(iconId) == leftRight(alpha(iconId)), iconId
    for iconId in ["neutral/chevron-right", "close-small"]:
        assert alpha(iconId) == topBottom(alpha(iconId)), iconId


def testThemeIconSetReplacesTheIconsItRedraws(mainWindow):
    from gitfourchette.themes import ThemeName
    from gitfourchette.toolbox import iconbank
    from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine

    assert "/neutral/" not in iconbank.stockIconPath("git-fetch")

    GFApplication.applyPrefs(qtStyle=f"{ThemeName.BuiltIn},dark,neutral")
    try:
        redraw = iconbank.stockIconPath("git-fetch")
        assert redraw.endswith("/neutral/git-fetch.svg")
        assert _rendered(iconbank.stockIcon("git-fetch")) == _rendered(QIcon(RecolorSvgIconEngine(redraw)))
        # An icon the set doesn't redraw is still found at the top level
        assert iconbank.stockIconPath("git-branch").endswith("/icons/git-branch.svg")
    finally:
        GFApplication.applyPrefs(qtStyle="")

    assert "/neutral/" not in iconbank.stockIconPath("git-fetch")
