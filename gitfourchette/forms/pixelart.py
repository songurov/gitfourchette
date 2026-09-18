# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""The few pieces the Home page's pixel-art scene is drawn with."""

from gitfourchette.qt import *

PIXEL = 2
"""Screen pixels per sprite pixel, for everything in the scene."""

Pixels = dict[tuple[int, int], str]
"""Sprite pixel -> color key."""


def gridPixels(rows, keys: dict[str, str] | None = None) -> Pixels:
    """A grid of one character per pixel ('.' is transparent), optionally renaming the keys."""
    return {(x, y): (keys[key] if keys else key)
            for y, row in enumerate(rows) for x, key in enumerate(row) if key != "."}


def paintPixels(widget: QWidget, pixels: Pixels, palette: dict[str, QColor], mirror: bool = False, width: int = 0):
    painter = QPainter(widget)
    for (x, y), key in pixels.items():
        if mirror:
            x = width - 1 - x
        painter.fillRect(x * PIXEL, y * PIXEL, PIXEL, PIXEL, palette[key])
    painter.end()


class PixelSprite(QWidget):
    """A pixel-art widget that never takes a click."""

    def __init__(self, stage: QWidget, name: str, width: int, height: int):
        super().__init__(stage)
        self.setObjectName(name)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(width * PIXEL, height * PIXEL)
        self.hide()

    def setShown(self, shown: bool):
        if shown != self.isVisible():
            self.setVisible(shown)

    def standOn(self, centerX: float, groundY: float):
        """Place it so its bottom row rests on groundY, centered on centerX."""
        self.move(round(centerX - self.width() / 2), round(groundY) - self.height())
