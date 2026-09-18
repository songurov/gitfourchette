# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
A little pixel-art character that lives on the Home splash page.

It stands on the logo, jumps onto "Welcome to", walks along it, jumps onto the
end of the app's name, turns around, and comes back the same way - forever,
but only while the splash page is on screen.

It stands on the glyphs themselves, not on the labels' boxes: the logo and the
welcome text are rendered offscreen and scanned for their first opaque row, so
the ground follows the font, the theme and the window size.
"""

import dataclasses
import math

from gitfourchette.qt import *

# One character per pixel, facing right. '.' is transparent.
_STAND = (
    "....HHHH....",
    "....HHHH....",
    "..HHHHHHHH..",
    "...BBBBBB...",
    "...BBEBEB...",
    "...BBBBBB...",
    ".BBBBBBBBBB.",
    "...BBBBBB...",
    "...BBBBBB...",
    "...BBBBBB...",
    "...BB..BB...",
    "...BB..BB...",
)
_STRIDE = (*_STAND[:10], "..BB....BB..", ".BB......BB.")
_JUMP = (
    *_STAND[:5],
    ".BBBBBBBBBB.",  # arms up
    "...BBBBBB...",
    "...BBBBBB...",
    "...BBBBBB...",
    "...BB..BB...",
    "....B..B....",  # legs tucked
    "............",
)
_COLORS = {
    "H": QColor("#70767d"),  # hat
    "B": QColor("#4a8ec2"),  # body
    "E": QColor("#16324a"),  # eyes
}

PIXEL = 3
"""Screen pixels per sprite pixel."""

WALK_SPEED = 42.0
"""Pixels per second."""

JUMP_MS = 560
IDLE_MS = 900
STEP_MS = 150
"""How long each leg position lasts while walking."""

FRAME_MS = 50
"""20 fps is plenty for pixel art, and keeps an idle Home cheap."""


@dataclasses.dataclass(frozen=True)
class Surface:
    """Something to stand on: an x range at the height of its topmost opaque pixel."""
    left: float
    right: float
    top: float


@dataclasses.dataclass(frozen=True)
class Segment:
    kind: str  # "idle", "walk", "jump"
    start: QPointF
    end: QPointF
    duration: float  # ms
    facing: int  # +1 right, -1 left; for "idle", the direction it ends up facing


def inkRows(image: QImage) -> list[tuple[int, int, int]]:
    """For every row with an opaque pixel: (y, leftmost x, rightmost x), in device pixels."""
    rows = []
    for y in range(image.height()):
        left = right = -1
        for x in range(image.width()):
            if (image.pixel(x, y) >> 24) & 0xFF > 64:
                if left < 0:
                    left = x
                right = x
        if left >= 0:
            rows.append((y, left, right))
    return rows


def renderAlpha(widget: QWidget) -> QImage:
    """The widget's own pixels on a transparent background."""
    dpr = widget.devicePixelRatioF()
    image = QImage(QSize(max(1, round(widget.width() * dpr)), max(1, round(widget.height() * dpr))),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    return image


def lineSurfaces(image: QImage, origin: QPointF, dpr: float) -> list[Surface]:
    """One Surface per line of text, split wherever a blank row separates the ink."""
    surfaces = []
    group: list[tuple[int, int, int]] = []
    for row in [*inkRows(image), None]:
        if row is not None and (not group or row[0] == group[-1][0] + 1):
            group.append(row)
            continue
        if group:
            surfaces.append(Surface(
                origin.x() + min(r[1] for r in group) / dpr,
                origin.x() + (max(r[2] for r in group) + 1) / dpr,
                origin.y() + group[0][0] / dpr))
        group = [row] if row is not None else []
    return surfaces


class HomeMascot(QWidget):
    def __init__(self, stage: QWidget, logo: QLabel, welcome: QLabel):
        super().__init__(stage)
        self.setObjectName("HomeMascot")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(len(_STAND[0]) * PIXEL, len(_STAND) * PIXEL)

        self.stage = stage
        self.logo = logo
        self.welcome = welcome

        self.segments: list[Segment] = []
        self.elapsed = 0.0
        self.sprite = _STAND
        self.facing = 1
        self.feet = QPointF()
        self.geometryKey = None

        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(lambda: self.advance(FRAME_MS))

        # It lives on the splash page only: follow it in and out of view
        stage.installEventFilter(self)
        self.hide()

    # -------------------------------------------------------------------------
    # Where to go

    def surfaces(self) -> tuple[Surface, Surface, Surface] | None:
        """The logo's top, then the two lines of the welcome text, in stage coordinates."""
        if self.logo.width() <= 1 or self.welcome.width() <= 1:
            return None

        logoImage = renderAlpha(self.logo)
        logoRows = inkRows(logoImage)
        if not logoRows:
            return None
        dpr = logoImage.devicePixelRatio()
        logoOrigin = QPointF(self.logo.mapTo(self.stage, QPoint(0, 0)))
        # The logo's top edge: its first few opaque rows, so a stray antialiased
        # pixel doesn't make the ledge one pixel wide
        top = logoRows[: max(1, round(2 * dpr))]
        logo = Surface(logoOrigin.x() + min(r[1] for r in top) / dpr,
                       logoOrigin.x() + (max(r[2] for r in top) + 1) / dpr,
                       logoOrigin.y() + logoRows[0][0] / dpr)

        welcomeImage = renderAlpha(self.welcome)
        lines = lineSurfaces(welcomeImage, QPointF(self.welcome.mapTo(self.stage, QPoint(0, 0))),
                             welcomeImage.devicePixelRatio())
        if len(lines) < 2:
            return None
        return logo, lines[0], lines[-1]

    def plan(self) -> list[Segment]:
        """Logo → "Welcome to" → the end of the app name, and back."""
        found = self.surfaces()
        if found is None:
            return []
        logo, welcomeLine, nameLine = found
        half = self.width() / 2

        def on(surface: Surface, x: float) -> QPointF:
            # Keep both feet on the ledge
            x = max(surface.left + half * 0.6, min(surface.right - half * 0.6, x))
            return QPointF(x, surface.top)

        start = on(logo, logo.left + half)
        welcomeFrom = on(welcomeLine, welcomeLine.left + half)
        welcomeTo = on(welcomeLine, welcomeLine.right - half)
        # "…chette": the last stretch of the name
        nameFrom = on(nameLine, nameLine.right - 0.3 * (nameLine.right - nameLine.left))
        nameTo = on(nameLine, nameLine.right - half)

        def walk(a: QPointF, b: QPointF) -> Segment:
            return Segment("walk", a, b, 1000 * abs(b.x() - a.x()) / WALK_SPEED, 1 if b.x() >= a.x() else -1)

        def jump(a: QPointF, b: QPointF) -> Segment:
            return Segment("jump", a, b, JUMP_MS, 1 if b.x() >= a.x() else -1)

        return [
            Segment("idle", start, start, IDLE_MS, 1),
            jump(start, welcomeFrom),
            walk(welcomeFrom, welcomeTo),
            jump(welcomeTo, nameFrom),
            walk(nameFrom, nameTo),
            Segment("idle", nameTo, nameTo, IDLE_MS, -1),  # turns around
            walk(nameTo, nameFrom),
            jump(nameFrom, welcomeTo),
            walk(welcomeTo, welcomeFrom),
            jump(welcomeFrom, start),
        ]

    def cycleDuration(self) -> float:
        return sum(s.duration for s in self.segments)

    # -------------------------------------------------------------------------
    # Moving

    def replanIfNeeded(self):
        key = (self.logo.geometry(), self.welcome.geometry(), self.welcome.text(),
               self.logo.mapTo(self.stage, QPoint(0, 0)), self.welcome.mapTo(self.stage, QPoint(0, 0)))
        if key == self.geometryKey:
            return
        self.geometryKey = key
        self.segments = self.plan()
        self.elapsed = 0.0

    def advance(self, ms: float):
        """Move `ms` further along the cycle. The timer calls it; so can tests."""
        self.replanIfNeeded()
        if not self.segments:
            self.hide()
            return

        self.elapsed = (self.elapsed + ms) % self.cycleDuration()
        t = self.elapsed
        for segment in self.segments:
            if t < segment.duration:
                break
            t -= segment.duration
        progress = t / segment.duration if segment.duration else 1.0
        a, b = segment.start, segment.end

        if segment.kind == "idle":
            # Look the way it came for a moment, then turn
            self.facing = segment.facing if progress >= 0.5 else -segment.facing
            self.sprite = _STAND
            self.feet = QPointF(a)
        elif segment.kind == "walk":
            self.facing = segment.facing
            self.sprite = _STRIDE if int(t // STEP_MS) % 2 else _STAND
            self.feet = a + (b - a) * progress
        else:
            self.facing = segment.facing
            self.sprite = _JUMP
            # Straight line between the two ledges, lifted by an arc that clears the higher one
            lift = 24 + max(0.0, a.y() - b.y())
            x = a.x() + (b.x() - a.x()) * progress
            y = a.y() + (b.y() - a.y()) * progress - 4 * lift * progress * (1 - progress)
            self.feet = QPointF(x, y)

        self.move(math.floor(self.feet.x() - self.width() / 2), math.floor(self.feet.y()) - self.height())
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def appear(self):
        self.advance(0)

    def isAnimating(self) -> bool:
        return self.timer.isActive()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.stage:
            if event.type() == QEvent.Type.Show:
                self.timer.start()
                # After the layout has placed the labels it stands on
                QTimer.singleShot(0, self.appear)
            elif event.type() == QEvent.Type.Hide:
                self.timer.stop()
        return super().eventFilter(watched, event)

    # -------------------------------------------------------------------------
    # Drawing

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        for row, line in enumerate(self.sprite):
            if self.facing < 0:
                line = line[::-1]
            for col, char in enumerate(line):
                color = _COLORS.get(char)
                if color is not None:
                    painter.fillRect(col * PIXEL, row * PIXEL, PIXEL, PIXEL, color)
        painter.end()
