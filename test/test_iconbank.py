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
