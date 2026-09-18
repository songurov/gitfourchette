# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
A little pixel-art dinosaur that lives on the Home splash page - a nod to
Nanosaur, and to the author who brought it back.

It stands on the logo and tips its beret to you: off, held to its chest with a
bow, back on. Then it jumps onto "Welcome to", walks along it and jumps onto
the end of the app's name, where a table holds a croissant. It toasts the
croissant with a breath of fire, eats it in four bites, and throws a boule down
to the pétanque pitch at the bottom of the page. The boule lands, rolls and
stops by the jack. Then the dinosaur walks back home, and a fresh croissant
waits for the next round - forever, but only while the splash page is on
screen. It takes its time: about half a minute a round.

It stands on the glyphs themselves, not on the labels' boxes: the logo and the
welcome text are rendered offscreen and scanned for their first opaque row, so
the ground follows the font, the theme and the window size.
"""

import dataclasses
import math

from gitfourchette.qt import *

PIXEL = 2
"""Screen pixels per sprite pixel, for everything in the scene."""

# The dinosaur is put together from parts, so the beret and the hand can move
# on their own. Coordinates are sprite pixels on a CANVAS_W x CANVAS_H canvas,
# facing right; facing left mirrors the whole canvas. The legs are centered, so
# turning around doesn't shift it. The feet touch the bottom row. The top three
# rows are headroom for the beret.
CANVAS_W, CANVAS_H = 20, 21

_BODY = (
    "....................",
    "....................",
    "....................",
    "....................",
    "....................",
    "....................",
    "............OOOOO...",
    "...........OOOOOOO..",
    "...........OOOOOOOO.",
    "...........OOOOOOOOO",
    "...........OOOOOOOO.",
    "...........OOOOOOOO.",
    ".........SOOOOO.....",
    "........SOOOOOOO....",
    ".......SOOOOYYOO....",
    ".....SSOOOOOYYOO....",
    "...SSOOOOOOOYYOO....",
    ".OOO...OOOOOOO......",
)
_EYE_OPEN = {(13, 7): "W", (14, 7): "W", (13, 8): "W", (14, 8): "K"}
_EYE_CLOSED = {(13, 8): "o", (14, 8): "o"}
_MOUTH_OPEN = {(14, 10): "K", (15, 10): "T", (16, 10): "K", (17, 10): "T", (18, 10): "K"}

BERET_ON_HEAD = (11, 3)
BERET_LIFTED = (12, 0)
BERET_AT_CHEST = (13, 12)

_ARM = {
    "rest": [(15, 14), (16, 14), (16, 15)],
    "grab": [(15, 14), (16, 13), (17, 12)],
    "hold": [(15, 15), (16, 15)],
    "reachTable": [(15, 14), (16, 14), (17, 14), (18, 14), (19, 14)],
    "mouth": [(15, 14), (16, 13)],
    "windup": [(15, 14), (15, 13), (15, 12)],
    "release": [(15, 14), (16, 13), (17, 12), (18, 11)],
    "up": [(15, 13), (16, 12)],
}
_LEGS = {
    "stand": {(6, 18): "O", (7, 18): "O", (11, 18): "O", (12, 18): "O",
              (6, 19): "O", (7, 19): "O", (11, 19): "O", (12, 19): "O",
              (6, 20): "o", (7, 20): "o", (8, 20): "o", (11, 20): "o", (12, 20): "o", (13, 20): "o"},
    "stride": {(5, 18): "O", (6, 18): "O", (12, 18): "O", (13, 18): "O",
               (4, 19): "O", (5, 19): "O", (13, 19): "O", (14, 19): "O",
               (3, 20): "o", (4, 20): "o", (5, 20): "o", (13, 20): "o", (14, 20): "o", (15, 20): "o"},
    "tuck": {(6, 18): "O", (7, 18): "O", (11, 18): "O", (12, 18): "O",
             (6, 19): "o", (7, 19): "o", (8, 19): "o", (11, 19): "o", (12, 19): "o", (13, 19): "o"},
}
# The croissant in hand, bitten from the mouth's side: (pixel, color key)
_HELD_CROISSANT = [((17, 11), "C"), ((18, 11), "C"),
                   ((16, 12), "C"), ((17, 12), "C"), ((18, 12), "C"), ((19, 12), "C"),
                   ((16, 13), "c"), ((19, 13), "c")]
BITES = 4

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

FIRE_W, FIRE_H = 14, 5
_FIRE = (
    ("YYFFFrr.......",
     ".YYFFFFrr.r...",
     "YYYYFFFFrrr...",
     ".YYFFFFrr..r..",
     "YYFFFrr.......",),
    ("YFFFrr..r.....",
     "YYYFFFFrr.....",
     "YYYFFFFFrrr.r.",
     "YYFFFFrrr.....",
     ".YFFrr........",),
)

BOULE_W = 5
_BOULE = (
    ".GGG.",
    "GgGGG",
    "GGGGG",
    "GGGGd",
    ".GdG.",
)
PITCH_W, PITCH_H = 160, 5
"""The pétanque pitch at the bottom of the page, in sprite pixels."""

_COLORS = {
    "O": QColor("#f2a23a"),  # dino
    "o": QColor("#b8621c"),  # dino shading, feet, arm
    "Y": QColor("#ffd978"),  # belly
    "S": QColor("#2a93ad"),  # spikes
    "W": QColor("#ffffff"),  # eye
    "K": QColor("#1b1b1b"),  # pupil, mouth
    "T": QColor("#f4f4f4"),  # teeth
    "R": QColor("#c8373a"),  # beret: red, so it reads on dark and light themes alike
    "C": QColor("#e3a548"),  # croissant, golden
    "c": QColor("#b06f28"),  # croissant, browned edges
    "D": QColor("#b9782a"),  # croissant, toasted
    "d": QColor("#7a4416"),  # croissant, toasted edges
    "T_": QColor("#a8733c"),  # table top
    "t": QColor("#7b5028"),  # table edge and legs
    "Y_": QColor("#ffe45c"),  # fire, hottest
    "F": QColor("#ff8a1c"),  # fire
    "r": QColor("#e0401c"),  # fire tips
    "G": QColor("#aab2bb"),  # boule
    "g": QColor("#eef2f5"),  # boule highlight
    "d_": QColor("#6f7780"),  # boule shadow
    "J": QColor("#e2572a"),  # jack
    "P": QColor("#b59866"),  # pitch, sand
    "p": QColor("#8f7446"),  # pitch, pebbles
}
# Grids share letters across sprites; each sprite maps its letters to colors
_TABLE_KEYS = {"T": "T_", "t": "t", "C": "C", "c": "c"}
_FIRE_KEYS = {"Y": "Y_", "F": "F", "r": "r"}
_BOULE_KEYS = {"G": "G", "g": "g", "d": "d_"}

WALK_SPEED = 22.0
"""Pixels per second: an unhurried stroll."""

JUMP_MS = 900
STEP_MS = 260
"""How long each leg position lasts while walking."""
TURN_MS = 800
GREET_MS = 3600
"""Beret off, held to the chest with a bow, back on."""

# At the table, in ms from arriving
FIRE_AT, FIRE_END = 400, 2000
TOASTED_AT = 1000
TAKE_AT = 2500
BITES_AT = 3100
BITE_MS = 600
WINDUP_AT = BITES_AT + BITES * BITE_MS + 400
THROW_AT = WINDUP_AT + 400
FLIGHT_MS = 1400
ROLL_MS = 1200
CHEER_AT = THROW_AT + FLIGHT_MS + ROLL_MS
TABLE_MS = CHEER_AT + 600

FRAME_MS = 50
"""20 fps is plenty for pixel art, and keeps an idle Home cheap."""


@dataclasses.dataclass(frozen=True)
class Pose:
    legs: str = "stand"
    arm: str = "rest"
    beret: tuple[int, int] = BERET_ON_HEAD
    eyesClosed: bool = False
    mouthOpen: bool = False
    held: int | None = None
    """Bites left of the croissant in hand, or None."""

    def pixels(self) -> dict[tuple[int, int], str]:
        """Sprite pixel -> color key, facing right. Later parts are drawn over earlier ones."""
        pixels = gridPixels(_BODY)
        pixels.update(_EYE_CLOSED if self.eyesClosed else _EYE_OPEN)
        if self.mouthOpen:
            pixels.update(_MOUTH_OPEN)
        pixels.update(_LEGS[self.legs])
        bx, by = self.beret
        pixels[(bx + 3, by)] = "R"
        for x in range(bx + 1, bx + 6):
            pixels[(x, by + 1)] = "R"
        for x in range(bx, bx + 7):
            pixels[(x, by + 2)] = "R"
        # The hand goes over what it's holding
        for xy in _ARM[self.arm]:
            pixels[xy] = "o"
        if self.held:
            eaten = BITES - self.held
            for (x, y), color in _HELD_CROISSANT:
                if x - 16 >= eaten:
                    pixels[(x, y)] = color
        return {xy: key for xy, key in pixels.items() if 0 <= xy[0] < CANVAS_W and 0 <= xy[1] < CANVAS_H}


STAND = Pose()


def gridPixels(rows, keys: dict[str, str] | None = None) -> dict[tuple[int, int], str]:
    return {(x, y): (keys[key] if keys else key)
            for y, row in enumerate(rows) for x, key in enumerate(row) if key != "."}


def paintPixels(widget: QWidget, pixels: dict[tuple[int, int], str], mirror: bool = False, width: int = 0):
    painter = QPainter(widget)
    for (x, y), key in pixels.items():
        if mirror:
            x = width - 1 - x
        painter.fillRect(x * PIXEL, y * PIXEL, PIXEL, PIXEL, _COLORS[key])
    painter.end()


class _Sprite(QWidget):
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


class MascotTable(_Sprite):
    """The table at the end of the walk, and the croissant on it."""

    def __init__(self, stage: QWidget):
        super().__init__(stage, "HomeMascotTable", TABLE_W, TABLE_H)
        self.hasCroissant = True
        self.toasted = False

    def setCroissant(self, present: bool, toasted: bool):
        if (present, toasted) != (self.hasCroissant, self.toasted):
            self.hasCroissant, self.toasted = present, toasted
            self.update()

    def paintEvent(self, event: QPaintEvent):
        pixels = gridPixels(_TABLE, _TABLE_KEYS)
        if self.hasCroissant:
            keys = {"C": "D", "c": "d"} if self.toasted else {"C": "C", "c": "c"}
            pixels.update(gridPixels(_TABLE_CROISSANT, keys))
        paintPixels(self, pixels)


class MascotFire(_Sprite):
    """A breath of fire, flickering, that grows out of the mouth."""

    def __init__(self, stage: QWidget):
        super().__init__(stage, "HomeMascotFire", FIRE_W, FIRE_H)
        self.frame = 0
        self.length = FIRE_W
        self.facing = 1

    def paintEvent(self, event: QPaintEvent):
        pixels = {xy: key for xy, key in gridPixels(_FIRE[self.frame % 2], _FIRE_KEYS).items()
                  if xy[0] < self.length}
        paintPixels(self, pixels, self.facing < 0, FIRE_W)


class MascotBoule(_Sprite):
    def __init__(self, stage: QWidget):
        super().__init__(stage, "HomeMascotBoule", BOULE_W, BOULE_W)

    def paintEvent(self, event: QPaintEvent):
        paintPixels(self, gridPixels(_BOULE, _BOULE_KEYS))


class MascotPitch(_Sprite):
    """The pétanque pitch at the bottom of the page: sand, pebbles, and the jack."""

    JACK_AT = 0.72
    """Where the jack sits along the pitch."""

    def __init__(self, stage: QWidget):
        super().__init__(stage, "HomeMascotPitch", PITCH_W, PITCH_H + 2)

    def groundTop(self) -> float:
        """Where boules rest, in stage coordinates."""
        return self.y() + 2 * PIXEL

    def jackX(self) -> float:
        return self.x() + self.JACK_AT * self.width()

    def paintEvent(self, event: QPaintEvent):
        pixels = {}
        for x in range(PITCH_W):
            for y in range(2, PITCH_H + 2):
                # A fixed scatter of pebbles, so the sand doesn't shimmer
                pixels[(x, y)] = "p" if (x * 7 + y * 13) % 11 == 0 else "P"
        jack = round(self.JACK_AT * PITCH_W)
        for x in range(jack - 1, jack + 2):
            for y in range(0, 2):
                pixels[(x, y)] = "J"
        paintPixels(self, pixels)


@dataclasses.dataclass(frozen=True)
class Surface:
    """Something to stand on: an x range at the height of its topmost opaque pixel."""
    left: float
    right: float
    top: float


@dataclasses.dataclass(frozen=True)
class Segment:
    kind: str  # "greet", "walk", "jump", "table", "turn"
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
        self.pitch = MascotPitch(stage)
        self.table = MascotTable(stage)
        self.fire = MascotFire(stage)
        self.boule = MascotBoule(stage)
        self.throwFrom = QPointF()
        self.throwDirection = 1
        self.landAt = QPointF()
        self.restAt = QPointF()

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

    def pitchRect(self) -> QRectF:
        """Centered at the bottom of the page."""
        width, height = PITCH_W * PIXEL, (PITCH_H + 2) * PIXEL
        return QRectF((self.stage.width() - width) / 2, self.stage.height() - height - 24, width, height)

    def plan(self) -> list[Segment]:
        """Beret on the logo → "Welcome to" → the croissant at the end of the name, and back."""
        found = self.surfaces()
        if found is None:
            return []
        logo, welcomeLine, nameLine = found
        body = 4 * PIXEL  # half the legs' span: keep both feet on the ledge

        def on(surface: Surface, x: float) -> QPointF:
            return QPointF(max(surface.left + body, min(surface.right - body, x)), surface.top)

        start = on(logo, logo.left + body * 2)
        welcomeFrom = on(welcomeLine, welcomeLine.left + body * 2)
        welcomeTo = on(welcomeLine, welcomeLine.right - body * 2)
        # Close enough that the fire reaches the croissant and the hand reaches the table
        table = self.tableRect(nameLine)
        atTable = on(nameLine, table.left() - (CANVAS_W // 2 + 1) * PIXEL)
        # Landing on "…chette", a few steps before the table
        nameFrom = on(nameLine, min(nameLine.right - 0.45 * (nameLine.right - nameLine.left),
                                    atTable.x() - 6 * PIXEL))

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
            Segment("table", atTable, atTable, TABLE_MS, 1),
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
        key = (self.stage.size(), self.logo.geometry(), self.welcome.geometry(), self.welcome.text(),
               self.logo.mapTo(self.stage, QPoint(0, 0)), self.welcome.mapTo(self.stage, QPoint(0, 0)))
        if key == self.geometryKey:
            return
        self.geometryKey = key
        self.segments = self.plan()
        self.elapsed = 0.0
        if not self.segments:
            for prop in self.pitch, self.table, self.fire, self.boule:
                prop.hide()
            return

        _logo, _welcome, nameLine = self.surfaces()
        self.table.setGeometry(self.tableRect(nameLine).toRect())
        self.pitch.setGeometry(self.pitchRect().toRect())
        self.table.show()
        self.pitch.show()

        # The throw: facing the jack, a lob that lands short of it and rolls on
        # in the same direction, stopping right by it
        atTable = self.segments[5].start
        jackX = self.pitch.jackX()
        self.throwDirection = 1 if jackX >= atTable.x() else -1
        self.throwFrom = QPointF(atTable.x() + self.throwDirection * 8 * PIXEL, atTable.y() - 12 * PIXEL)
        roll = min(0.25 * self.pitch.width(), max(10.0, 0.6 * abs(jackX - self.throwFrom.x())))
        ground = self.pitch.groundTop()
        self.landAt = QPointF(jackX - self.throwDirection * roll, ground)
        self.restAt = QPointF(jackX - self.throwDirection * 5 * PIXEL, ground)  # bien pointé

        # Back to front: the dinosaur walks in front of everything
        for prop in self.pitch, self.table, self.boule, self.fire:
            prop.raise_()
        self.raise_()

    @staticmethod
    def greetPose(t: float) -> Pose:
        if t < 500:
            return Pose(arm="grab")
        if t < 1000:
            return Pose(arm="grab", beret=BERET_LIFTED)
        if t < 1500:
            return Pose(arm="hold", beret=BERET_AT_CHEST)
        if t < 2700:
            return Pose(arm="hold", beret=BERET_AT_CHEST, eyesClosed=True)  # the bow
        if t < 3200:
            return Pose(arm="grab", beret=BERET_LIFTED)
        return STAND

    @staticmethod
    def tablePose(t: float) -> Pose:
        if FIRE_AT <= t < FIRE_END:
            return Pose(mouthOpen=True)
        if FIRE_END <= t < TAKE_AT:
            return Pose(arm="reachTable")
        if TAKE_AT <= t < WINDUP_AT:
            bitesTaken = int((t - BITES_AT) // BITE_MS) + 1 if t >= BITES_AT else 0
            left = BITES - bitesTaken
            if left > 0:
                return Pose(arm="mouth", held=left, mouthOpen=bitesTaken > 0)
            return STAND  # all gone; a moment to savor it
        if WINDUP_AT <= t < THROW_AT:
            return Pose(arm="windup")
        if THROW_AT <= t < THROW_AT + 300:
            return Pose(arm="release")
        if CHEER_AT <= t < TABLE_MS:
            return Pose(legs="tuck", arm="up")  # bien pointé!
        return STAND

    def boulePosition(self, t: float) -> QPointF | None:
        """Where the boule is at time t of the table segment, or None before the throw."""
        if t < THROW_AT:
            return None
        if t < THROW_AT + FLIGHT_MS:
            # A lob: it rises above the hand first, then falls onto the sand.
            # The longer the fall, the higher the arc has to be for that.
            progress = (t - THROW_AT) / FLIGHT_MS
            a, b = self.throwFrom, self.landAt
            lift = 60 + 0.25 * max(0.0, b.y() - a.y())
            x = a.x() + (b.x() - a.x()) * progress
            y = a.y() + (b.y() - a.y()) * progress - 4 * lift * progress * (1 - progress)
            return QPointF(x, y)
        progress = min(1.0, (t - THROW_AT - FLIGHT_MS) / ROLL_MS)
        eased = 1 - (1 - progress) ** 2  # the sand slows it down
        return self.landAt + (self.restAt - self.landAt) * eased

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
        tableTime = self.elapsed - self.segmentStart("table")  # < 0 before the table

        if segment.kind == "greet":
            self.pose = self.greetPose(t)
        elif segment.kind == "table":
            self.pose = self.tablePose(t)
            if t >= WINDUP_AT:
                self.facing = self.throwDirection  # face the jack to throw
            if t >= CHEER_AT:
                hop = math.sin(math.pi * (t - CHEER_AT) / (TABLE_MS - CHEER_AT))
                self.feet = QPointF(a.x(), a.y() - 3 * PIXEL * hop)
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

        self.move(math.floor(self.feet.x() - self.width() / 2), math.floor(self.feet.y()) - self.height())

        # The croissant gets toasted by the fire, then taken; a fresh one waits
        # by the time the next round starts
        self.table.setCroissant(tableTime < TAKE_AT, tableTime >= TOASTED_AT)

        breathing = segment.kind == "table" and FIRE_AT <= t < FIRE_END
        self.fire.setShown(breathing)
        if breathing:
            self.fire.frame = int(t // 100)
            self.fire.length = min(FIRE_W, max(3, round(FIRE_W * (t - FIRE_AT) / 300)))
            self.fire.facing = self.facing
            mouthX = self.feet.x() + self.facing * (CANVAS_W / 2) * PIXEL
            self.fire.move(math.floor(mouthX if self.facing > 0 else mouthX - self.fire.width()),
                           math.floor(self.feet.y() - (CANVAS_H - 8) * PIXEL))
            self.fire.update()

        boule = self.boulePosition(tableTime) if tableTime >= 0 else None
        self.boule.setShown(boule is not None)
        if boule is not None:
            size = self.boule.width()
            self.boule.move(math.floor(boule.x() - size / 2), math.floor(boule.y()) - size)

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
