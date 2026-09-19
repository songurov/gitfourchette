# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from gitfourchette.qt import *
from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine


logger = logging.getLogger(__name__)

_stockIconCache: dict[int, QIcon] = {}
_stockIconHtmlCache: dict[int, str] = {}

_iconSet = ""
"""
Subfolder of assets:icons whose drawings replace the top-level ones of the same
name, e.g. "neutral" for icons/neutral/git-fetch.svg. Empty: top-level icons only.
"""

# Override some icon IDs depending on desktop environment
_overrideIconIds: dict[str, str] = {}

_autoDarkVariants = {
    "achtung",
    "host-github",  # black on light, white on dark - same as GitHub's own mark
    "gpg-key-what",
    "urgent-tab",
    "git-lfs",
    "git-lfs-add",
    "git-lfs-remove",
    # Not the status tiles: they're filled with their own color, and their
    # white glyph must stay white on dark themes too.
}


def _iconOverrideTable() -> dict[str, str]:
    overrides = {
        "status_?": "status_a",  # Use Added icon for Untracked

        # Qt standard pixmaps can also come from the desktop theme. Keep the
        # trash action consistent with the rest of our line-art icon set.
        "SP_TrashIcon": "trash",

        # Freedesktop icon names, answered with our own icons. Left to the
        # desktop's icon theme, these come out in somebody else's style -
        # usually full color, next to our flat line art.
        "application-exit": "exit",
        "configure": "git-settings",
        "dialog-close": "close",
        "document-close": "close",
        "document-edit": "edit",
        "document-save-as": "save",
        "edit-clear-history": "trash",
        "edit-find": "magnifying-glass",
        "folder-open": "git-folder",
        "folder-open-recent": "folder-recent",
        "go-down-search": "chevron-down",
        "go-up-search": "chevron-up",
        "help-contents": "hint",
        "image-missing": "achtung",
        "information": "info",
        "internet-web-browser": "web",
        "ssh": "gpg-key",
        "user-identity": "git-identity",
        "vcs-branch": "git-branch",
        "vcs-branch-delete": "git-branch-delete",
        "vcs-diff": "git-change",
        "warning": "achtung",
    }

    assert QApplication.instance(), "need app instance to resolve 'assets:' icon paths"

    # Use native warning icon in all contexts on Mac & Windows
    if MACOS or WINDOWS:  # pragma: no cover
        overrides["achtung"] = "SP_MessageBoxWarning"

    # Elsewhere it's the other way round: AppStyle answers SP_MessageBoxWarning
    # with our own achtung, so no desktop gets to supply its own warning icon
    # (Ubuntu's, in particular, is a scary red one).

    return overrides


def stockIcon(iconId: str, colorTable="") -> QIcon:
    # Special cases
    if not _overrideIconIds:
        _overrideIconIds.update(_iconOverrideTable())
        assert _overrideIconIds, "expecting overrides to contain at least one entry"
    iconId = _overrideIconIds.get(iconId, iconId)

    if RecolorSvgIconEngine.IconColors.preferDarkVariants and iconId in _autoDarkVariants:
        assert not colorTable
        colorTable = "white=#000 black=#fff"

    # Compute cache key
    key = hash(iconId) ^ hash(colorTable)

    # Attempt to get cached icon
    try:
        return _stockIconCache[key]
    except KeyError:
        pass

    iconPath = stockIconPath(iconId)

    # Create QIcon
    if iconPath.endswith(".svg"):
        # Dynamic SVG icon
        engine = RecolorSvgIconEngine(iconPath, colorTable)
        icon = QIcon(engine)
    elif iconPath:
        # Bitmap file
        icon = QIcon(iconPath)
    elif iconId.startswith("SP_"):
        # Qt standard pixmaps (with "SP_" prefix)
        entry = getattr(QStyle.StandardPixmap, iconId)
        icon = QApplication.style().standardIcon(entry)
    else:
        # No icon of our own. Rather than let the desktop's icon theme answer
        # in its own style, show nothing - and fail loudly in the test suite,
        # so a missing icon is caught here instead of in a screenshot.
        assert not APP_TESTMODE, f"no icon of our own for {iconId!r}"
        logger.warning(f"No icon for {iconId}")
        icon = QIcon()

    assert iconPath.endswith(".svg") or not colorTable, f"can't remap colors in non-SVG icon! {iconId}"

    # Cache icon
    _stockIconCache[key] = icon
    return icon


def stockIconPath(iconId: str) -> str:
    """
    Path to our own drawing of an icon, or "" if there's none. The icon set's
    redraw comes first, if it has one.
    """
    folders = [f"{_iconSet}/", ""] if _iconSet else [""]
    for folder in folders:
        for ext in ".svg", ".png":
            file = QFile(f"assets:icons/{folder}{iconId}{ext}")
            if file.exists():
                return file.fileName()
    return ""


def setIconSet(name: str):
    """Prefer the drawings in assets:icons/<name>/ (see _iconSet)."""
    global _iconSet
    if name != _iconSet:
        _iconSet = name
        clearStockIconCache()


def stockIconImgTag(iconId: str, dpr: float = 0) -> str:
    # Qt's HTML subset renders <img> tags at devicePixelRatio=1. To avoid ugly
    # stretching beyond 1x, we'll pre-render the image at the desired dpr. This
    # makes most sense for SVG images which make up the bulk of our icon bank.
    if dpr == 0:
        # devicePixelRatio not specified, figure it out.
        app = QApplication.instance()
        try:
            # Use mainWindow's dpr
            window: QMainWindow = app.mainWindow  # type: ignore[attr-defined]
            dpr = window.devicePixelRatio()
        except AttributeError:
            # Too early, no window yet; fall back to highest dpr on the system.
            # Note: on Wayland, this may be higher than the actual dpr if
            # fractional scaling is enabled (e.g. this may return 2.0 if your
            # system is set up for 1.25 frac scaling)
            dpr = app.devicePixelRatio()  # type: ignore[attr-defined]  # incomplete stubs

    key = hash(iconId) ^ hash(dpr)

    try:
        return _stockIconHtmlCache[key]
    except KeyError:
        pass

    size = QSize(16, 16)

    if dpr == 1 or QT5:
        # Pre-rendering not necessary for dpr=1
        # (Qt 5: can't pass devicePixelRatio to QIcon.pixmap())
        src = f"assets:icons/{iconId}"
    else:
        # Pre-render at the given dpr into a temporary PNG file.
        icon = stockIcon(iconId)
        pixmap = icon.pixmap(size, dpr)
        fileName = f"i{int(dpr*100)}-{key & 0xFFFFFFFF:x}.png"
        src = f"{qTempDir()}/{fileName}"
        pixmap.save(src)

    tag = f"<img src='{src}' width={size.width()} height={size.height()} style='vertical-align: bottom;'/>"

    _stockIconHtmlCache[key] = tag
    return tag


def clearStockIconCache():
    _stockIconCache.clear()
    _stockIconHtmlCache.clear()

    # Force reevaluate color scheme
    RecolorSvgIconEngine.IconColors.initialized = False
