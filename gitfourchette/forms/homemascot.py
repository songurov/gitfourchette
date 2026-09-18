# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
A little pixel-art character that lives on the Home splash page.

It stands on the logo and tips its hat to you: takes it off, holds it to its
chest with a bow, puts it back on. Then it jumps onto "Welcome to", walks along
it and jumps onto the end of the app's name, where a table holds a croissant.
It eats it in four bites, turns around and walks back home. A fresh croissant
is waiting by the next round - forever, but only while the splash page is on
screen. It takes its time: about twenty seconds a round.

It stands on the glyphs themselves, not on the labels' boxes: the logo and the
welcome text are rendered offscreen and scanned for their first opaque row, so
the ground follows the font, the theme and the window size.
"""

import dataclasses
import math

from gitfourchette.qt import *

# The character is put together from parts, so the hat and the hand can move
# on their own. Coordinates are sprite pixels on a CANVAS_W x CANVAS_H canvas,
# facing right; facing left mirrors the whole canvas. The body is centered, so
# turning around doesn't shift it. The feet touch the bottom row.
CANVAS_W, CANVAS_H = 16, 15

HAT_ON_HEAD = (4, 3)
HAT_LIFTED = (5, 0)
HAT_AT_CHEST = (8, 8)

_BODY = [(x, y) for x in range(5, 11) for y in range(6, 13)]
_BACK_ARM = {"rest": [(3, 9), (4, 9)], "up": [(3, 8), (4, 8)]}
_FRONT_ARM = {
    "rest": [(11, 9), (12, 9)],
    "up": [(11, 8), (12, 8)],
    "reachHat": [(11, 8), (12, 7), (12, 6)],
    "lift": [(11, 8), (12, 7), (12, 6), (12, 5), (12, 4), (12, 3)],
    "hold": [(11, 9), (12, 10)],
    "reachTable": [(11, 9), (12, 9), (13, 9), (14, 9), (15, 9)],
    "mouth": [(11, 9), (12, 8)],
}
_LEGS = {
    "stand": [(5, 13), (6, 13), (9, 13), (10, 13), (5, 14), (6, 14), (9, 14), (10, 14)],
    "stride": [(4, 13), (5, 13), (10, 13), (11, 13), (3, 14), (4, 14), (11, 14), (12, 14)],
    "tuck": [(5, 13), (6, 13), (9, 13), (10, 13), (6, 14), (9, 14)],
}
# The croissant in hand, bitten from the side of the mouth: (pixel, color key)
_HELD_CROISSANT = [((13, 7), "C"), ((14, 7), "C"),
                   ((12, 8), "C"), ((13, 8), "C"), ((14, 8), "C"), ((15, 8), "C"),
                   ((12, 9), "c"), ((15, 9), "c")]
BITES = 4

# The table, with a croissant on it. French: a proper crescent, golden, flaky.
TABLE_W, TABLE_H = 12, 7
_TABLE = (
    "............",
    "............",
    "............",
    "TTTTTTTTTTTT",
    "tttttttttttt",
    ".t........t.",
    ".t........t.",
)
_TABLE_CROISSANT = (
    "....cCCc....",
    "...cCcCcC...",
    "..cC....Cc..",
)

_COLORS = {
    "H": QColor("#70767d"),  # hat
    "B": QColor("#4a8ec2"),  # body
    "E": QColor("#16324a"),  # eyes
    "C": QColor("#e3a548"),  # croissant, golden
    "c": QColor("#b06f28"),  # croissant, browned edges
    "T": QColor("#a8733c"),  # table top
    "t": QColor("#7b5028"),  # table edge and legs
}

PIXEL = 3
"""Screen pixels per sprite pixel."""

WALK_SPEED = 22.0
"""Pixels per second: an unhurried stroll."""

JUMP_MS = 900
STEP_MS = 260
"""How long each leg position lasts while walking."""
TURN_MS = 800

GREET_MS = 3200
"""Hat off, a bow with the hat to the chest, hat back on."""

EAT_MS = 4400
EAT_TAKE_AT = 1000
"""When the croissant leaves the table for the hand."""
EAT_BITE_MS = 600

FRAME_MS = 50
"""20 fps is plenty for pixel art, and keeps an idle Home cheap."""


@dataclasses.dataclass(frozen=True)
class Pose:
    legs: str = "stand"
    arm: str = "rest"
    hat: tuple[int, int] = HAT_ON_HEAD
    eyesDown: bool = False
    held: int | None = None
    """Bites left of the croissant in hand, or None."""

    def pixels(self) -> dict[tuple[int, int], str]:
        """Sprite pixel -> color key, facing right. Later parts are drawn over earlier ones."""
        pixels = {}
        for xy in _BODY:
            pixels[xy] = "B"
        eyeRow = 8 if self.eyesDown else 7
        pixels[(7, eyeRow)] = pixels[(9, eyeRow)] = "E"
        for xy in _BACK_ARM["up" if self.arm == "up" else "rest"]:
            pixels[xy] = "B"
        for xy in _LEGS[self.legs]:
            pixels[xy] = "B"
        hx, hy = self.hat
        for x in range(hx + 2, hx + 6):
            pixels[(x, hy)] = pixels[(x, hy + 1)] = "H"
        for x in range(hx, hx + 8):
            pixels[(x, hy + 2)] = "H"
        # The hand goes over the hat it's holding
        for xy in _FRONT_ARM[self.arm]:
            pixels[xy] = "B"
        if self.held:
            eaten = BITES - self.held
            for (x, y), color in _HELD_CROISSANT:
                if x - 12 >= eaten:
                    pixels[(x, y)] = color
        return pixels


STAND = Pose()


def paintPixels(widget: QWidget, pixels: dict[tuple[int, int], str], mirror: bool, width: int):
    painter = QPainter(widget)
    for (x, y), key in pixels.items():
        if mirror:
            x = width - 1 - x
        painter.fillRect(x * PIXEL, y * PIXEL, PIXEL, PIXEL, _COLORS[key])
    painter.end()


def gridPixels(rows) -> dict[tuple[int, int], str]:
    return {(x, y): key for y, row in enumerate(rows) for x, key in enumerate(row) if key != "."}


@dataclasses.dataclass(frozen=True)
class Surface:
    """Something to stand on: an x range at the height of its topmost opaque pixel."""
    left: float
    right: float
    top: float


@dataclasses.dataclass(frozen=True)
class Segment:
    kind: str  # "greet", "walk", "jump", "eat", "turn"
    start: QPointF
    end: QPointF
    duration: float  # ms
    facing: int  # +1 right, -1 left; for "turn", the direction it ends up facing


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


class MascotTable(QWidget):
    """The table at the end of the walk, and the croissant on it."""

    def __init__(self, stage: QWidget):
        super().__init__(stage)
        self.setObjectName("HomeMascotTable")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(TABLE_W * PIXEL, TABLE_H * PIXEL)
        self.hasCroissant = True
        self.hide()

    def setCroissant(self, present: bool):
        if present != self.hasCroissant:
            self.hasCroissant = present
            self.update()

    def paintEvent(self, event: QPaintEvent):
        pixels = gridPixels(_TABLE)
        if self.hasCroissant:
            pixels.update(gridPixels(_TABLE_CROISSANT))
        paintPixels(self, pixels, False, TABLE_W)


class HomeMascot(QWidget):
    def __init__(self, stage: QWidget, logo: QLabel, welcome: QLabel):
        super().__init__(stage)
        self.setObjectName("HomeMascot")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(CANVAS_W * PIXEL, CANVAS_H * PIXEL)

        self.stage = stage
        self.logo = logo
        self.welcome = welcome
        self.table = MascotTable(stage)

        self.segments: list[Segment] = []
        self.elapsed = 0.0
        self.pose = STAND
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

    def tableRect(self, nameLine: Surface) -> QRectF:
        """Right at the end of the name, standing on its letters."""
        width, height = TABLE_W * PIXEL, TABLE_H * PIXEL
        return QRectF(nameLine.right - width, nameLine.top - height, width, height)

    def plan(self) -> list[Segment]:
        """Hat tip on the logo → "Welcome to" → the croissant at the end of the name, and back."""
        found = self.surfaces()
        if found is None:
            return []
        logo, welcomeLine, nameLine = found
        body = 3 * PIXEL  # half the body's width: keep both feet on the ledge

        def on(surface: Surface, x: float) -> QPointF:
            return QPointF(max(surface.left + body, min(surface.right - body, x)), surface.top)

        start = on(logo, logo.left + body * 2)
        welcomeFrom = on(welcomeLine, welcomeLine.left + body * 2)
        welcomeTo = on(welcomeLine, welcomeLine.right - body * 2)
        # Close enough to the table for the outstretched hand to reach the croissant
        table = self.tableRect(nameLine)
        atTable = on(nameLine, table.left() - 6 * PIXEL)
        # Landing on "…chette", a few steps before the table
        nameFrom = on(nameLine, min(nameLine.right - 0.45 * (nameLine.right - nameLine.left),
                                    atTable.x() - 4 * PIXEL))

        def walk(a: QPointF, b: QPointF) -> Segment:
            return Segment("walk", a, b, 1000 * abs(b.x() - a.x()) / WALK_SPEED, 1 if b.x() >= a.x() else -1)

        def jump(a: QPointF, b: QPointF) -> Segment:
            return Segment("jump", a, b, JUMP_MS, 1 if b.x() >= a.x() else -1)

        return [
            Segment("greet", start, start, GREET_MS, 1),
            jump(start, welcomeFrom),
            walk(welcomeFrom, welcomeTo),
            jump(welcomeTo, nameFrom),
            walk(nameFrom, atTable),
            Segment("eat", atTable, atTable, EAT_MS, 1),
            Segment("turn", atTable, atTable, TURN_MS, -1),
            walk(atTable, nameFrom),
            jump(nameFrom, welcomeTo),
            walk(welcomeTo, welcomeFrom),
            jump(welcomeFrom, start),
            Segment("turn", start, start, TURN_MS, 1),
        ]

    def cycleDuration(self) -> float:
        return sum(s.duration for s in self.segments)

    def segmentStart(self, kind: str) -> float:
        """When the first segment of this kind begins, in cycle time."""
        t = 0.0
        for segment in self.segments:
            if segment.kind == kind:
                return t
            t += segment.duration
        raise KeyError(kind)

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
        if self.segments:
            _logo, _welcome, nameLine = self.surfaces()
            self.table.setGeometry(self.tableRect(nameLine).toRect())
            self.table.show()
            self.raise_()  # in front of the table, not behind it
        else:
            self.table.hide()

    @staticmethod
    def greetPose(t: float) -> Pose:
        if t < 450:
            return Pose(arm="reachHat")
        if t < 1000:
            return Pose(arm="lift", hat=HAT_LIFTED)
        if t < 2400:
            return Pose(arm="hold", hat=HAT_AT_CHEST, eyesDown=True)  # the bow
        if t < 2900:
            return Pose(arm="lift", hat=HAT_LIFTED)
        return Pose(arm="reachHat")

    @staticmethod
    def eatPose(t: float) -> Pose:
        if t < 500:
            return STAND
        if t < EAT_TAKE_AT:
            return Pose(arm="reachTable")
        bitesTaken = int((t - EAT_TAKE_AT) // EAT_BITE_MS) - 1  # hold it a moment first
        left = BITES - max(0, bitesTaken)
        if left > 0:
            return Pose(arm="mouth", held=left)
        return STAND  # all gone; a moment to savor it

    def advance(self, ms: float):
        """Move `ms` further along the round. The timer calls it; so can tests."""
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
        self.feet = QPointF(a)
        self.facing = segment.facing

        if segment.kind == "greet":
            self.pose = self.greetPose(t)
        elif segment.kind == "eat":
            self.pose = self.eatPose(t)
        elif segment.kind == "turn":
            # Look the way it came for a moment, then turn
            self.facing = segment.facing if progress >= 0.5 else -segment.facing
            self.pose = STAND
        elif segment.kind == "walk":
            self.pose = Pose(legs="stride") if int(t // STEP_MS) % 2 else STAND
            self.feet = a + (b - a) * progress
        else:
            self.pose = Pose(legs="tuck", arm="up")
            # Straight line between the two ledges, lifted by an arc that clears the higher one
            lift = 20 + max(0.0, a.y() - b.y())
            x = a.x() + (b.x() - a.x()) * progress
            y = a.y() + (b.y() - a.y()) * progress - 4 * lift * progress * (1 - progress)
            self.feet = QPointF(x, y)

        # The croissant leaves the table when it's taken, and a fresh one is
        # there by the time the next round starts
        self.table.setCroissant(self.elapsed < self.segmentStart("eat") + EAT_TAKE_AT)

        self.move(math.floor(self.feet.x() - self.width() / 2), math.floor(self.feet.y()) - self.height())
        if not self.isVisible():
            self.show()
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
        paintPixels(self, self.pose.pixels(), self.facing < 0, CANVAS_W)
