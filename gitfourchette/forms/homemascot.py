# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
A little pixel-art dinosaur that lives on the Home splash page - a nod to
Nanosaur, and to the author who brought it back.

It has a nest on the logo. It tips its beret to you, then jumps onto "Welcome
to" and walks along it; meanwhile an egg falls from the sky onto the end of
the app's name. The dinosaur picks it up, carries it home and lays it in the
nest. Once the nest holds three eggs, they hatch at the start of the next
round, and the nest starts over - forever, but only while the splash page is
on screen. It takes its time: at least 25 seconds a round. How far it walks
follows the text, so when the text is short - a narrow font, a short
translation - it rests at home before the next round rather than hurrying.

It stands on the glyphs themselves, not on the labels' boxes: the logo and the
welcome text are rendered offscreen and scanned for their first opaque row, so
the ground follows the font, the theme and the window size.
"""

import dataclasses
import math

from gitfourchette import settings
from gitfourchette.forms.pixelart import PIXEL, PixelSprite, Pixels, gridPixels, paintPixels
from gitfourchette.qt import *

# The dinosaur is put together from parts, so the beret, the hand and the egg
# can move on their own. Coordinates are sprite pixels on a CANVAS_W x CANVAS_H
# canvas, facing right; facing left mirrors the whole canvas. The legs are
# centered, so turning around doesn't shift it. The feet touch the bottom row.
# The top three rows are headroom for the beret.
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
_EYE = [(13, 7), (14, 7), (13, 8), (14, 8)]
_EYE_CLOSED = {(13, 8): "o", (14, 8): "o"}
LOOK_AHEAD = (1, 1)
"""Where the pupil sits in the 2x2 eye when there's nothing to look at: front, low."""

BERET_ON_HEAD = (11, 3)
BERET_LIFTED = (12, 0)
BERET_AT_CHEST = (13, 12)

_ARM = {
    "rest": [(15, 14), (16, 14), (16, 15)],
    "grab": [(15, 14), (16, 13), (17, 12)],
    "hold": [(15, 15), (16, 15)],
    "reachDown": [(15, 14), (16, 15), (17, 16), (18, 17)],
    "carry": [(15, 14), (16, 15)],
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

EGG_W, EGG_H = 4, 5
_EGG = (
    ".VV.",
    "VVsV",
    "VsVV",
    "VVVV",
    ".VV.",
)
_HATCHED = (
    ".OO.",  # a baby's head,
    "OKOO",  # peeking out
    "V.VV",  # of a cracked shell
    "VVVV",
    ".VV.",
)
_CARRIED_EGG_AT = (16, 12)
"""Where the egg sits in the dinosaur's arms, on its canvas."""

NEST_CAPACITY = 3
NEST_W, NEST_H = 14, 6
_NEST = (
    "n.nn.n.nn.n.nn",
    "nnnnnnnnnnnnnn",
    ".nnnnnnnnnnnn.",
)
_NEST_SLOTS = [1, 5, 9]
"""Where the eggs sit in the nest, left to right."""

_COLORS = {
    "O": QColor("#f2a23a"),  # dino
    "o": QColor("#b8621c"),  # dino shading, feet, arm
    "Y": QColor("#ffd978"),  # belly
    "S": QColor("#2a93ad"),  # spikes
    "W": QColor("#ffffff"),  # eye
    "K": QColor("#1b1b1b"),  # pupil
    "R": QColor("#c8373a"),  # beret: red, so it reads on dark and light themes alike
    "V": QColor("#f3ead2"),  # egg shell
    "s": QColor("#2a93ad"),  # egg spots: same teal as the spikes
    "n": QColor("#8a6236"),  # nest twigs
}

WALK_SPEED = 22.0
"""Pixels per second: an unhurried stroll."""

JUMP_MS = 900
STEP_MS = 260
"""How long each leg position lasts while walking."""
TURN_MS = 800
GREET_MS = 3600
"""Beret off, held to the chest with a bow, back on."""
PICK_MS = 1400
PLACE_MS = 1400
LET_GO_AT = 800
"""When the egg leaves the hands, while picking it up or laying it."""
FALL_MS = 1800
BOUNCE_MS = 300
MIN_ROUND_MS = 25_000
"""The shortest a round may take, however short the text it walks along."""

FRAME_MS = 50
"""20 fps is plenty for pixel art, and keeps an idle Home cheap."""


@dataclasses.dataclass(frozen=True)
class Pose:
    legs: str = "stand"
    arm: str = "rest"
    beret: tuple[int, int] = BERET_ON_HEAD
    eyesClosed: bool = False
    carrying: bool = False
    look: tuple[int, int] = LOOK_AHEAD
    """The pupil in the 2x2 eye: (0 back / 1 front, 0 up / 1 down), facing right."""

    def pixels(self) -> Pixels:
        """Sprite pixel -> color key, facing right. Later parts are drawn over earlier ones."""
        pixels = gridPixels(_BODY)
        if self.eyesClosed:
            pixels.update(_EYE_CLOSED)
        else:
            for xy in _EYE:
                pixels[xy] = "W"
            pixels[(_EYE[0][0] + self.look[0], _EYE[0][1] + self.look[1])] = "K"
        pixels.update(_LEGS[self.legs])
        bx, by = self.beret
        pixels[(bx + 3, by)] = "R"
        for x in range(bx + 1, bx + 6):
            pixels[(x, by + 1)] = "R"
        for x in range(bx, bx + 7):
            pixels[(x, by + 2)] = "R"
        if self.carrying:
            ex, ey = _CARRIED_EGG_AT
            for (x, y), key in gridPixels(_EGG).items():
                pixels[(ex + x, ey + y)] = key
        # The hand goes over what it's holding
        for xy in _ARM[self.arm]:
            pixels[xy] = "o"
        return {xy: key for xy, key in pixels.items() if 0 <= xy[0] < CANVAS_W and 0 <= xy[1] < CANVAS_H}


STAND = Pose()


class FallingEgg(PixelSprite):
    def __init__(self, stage: QWidget):
        super().__init__(stage, "HomeMascotEgg", EGG_W, EGG_H)

    def paintEvent(self, event: QPaintEvent):
        paintPixels(self, gridPixels(_EGG), _COLORS)


class Nest(PixelSprite):
    """On the logo: twigs, and the eggs brought home so far."""

    def __init__(self, stage: QWidget):
        super().__init__(stage, "HomeMascotNest", NEST_W, NEST_H)
        self.eggs = 0
        self.hatched = False
        self.wobble = 0

    def setEggs(self, count: int, hatched: bool = False, wobble: int = 0):
        if (count, hatched, wobble) != (self.eggs, self.hatched, self.wobble):
            self.eggs, self.hatched, self.wobble = count, hatched, wobble
            self.update()

    def pixels(self) -> Pixels:
        pixels = {}
        egg = gridPixels(_HATCHED if self.hatched else _EGG)
        for slot in _NEST_SLOTS[:self.eggs]:
            for (x, y), key in egg.items():
                pixels[(slot + x + self.wobble, y)] = key
        # The twigs go in front, so the eggs sit in the nest, not on it
        for (x, y), key in gridPixels(_NEST).items():
            pixels[(x, y + NEST_H - len(_NEST))] = key
        return {xy: key for xy, key in pixels.items() if 0 <= xy[0] < NEST_W}

    def paintEvent(self, event: QPaintEvent):
        paintPixels(self, self.pixels(), _COLORS)


@dataclasses.dataclass(frozen=True)
class Surface:
    """Something to stand on: an x range at the height of its topmost opaque pixel."""
    left: float
    right: float
    top: float


@dataclasses.dataclass(frozen=True)
class Segment:
    kind: str  # "greet", "walk", "jump", "pick", "place", "turn", "rest"
    start: QPointF
    end: QPointF
    duration: float  # ms
    facing: int  # +1 right, -1 left; for "turn", the direction it ends up facing
    carrying: bool = False


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


def renderAlpha(label: QLabel) -> QImage:
    """
    The label's own pixels on a transparent background.

    What gets drawn is a detached copy of the label, not the label itself:
    QWidget.render() on a widget that is on screen first delivers every pending
    move and resize event in the whole window. That reaches into the repo tabs,
    including one that is being torn down - closing the last tab brings Home
    back before Qt has deleted that tab.
    """
    copy = QLabel()
    copy.setScreen(label.screen())  # same DPI, so the text comes out the same size
    copy.setObjectName(label.objectName())
    copy.setFont(label.font())
    copy.setPalette(label.palette())
    copy.setLayoutDirection(label.layoutDirection())
    copy.setFrameStyle(label.frameStyle())
    copy.setLineWidth(label.lineWidth())
    copy.setMidLineWidth(label.midLineWidth())
    copy.setContentsMargins(label.contentsMargins())
    copy.setMargin(label.margin())
    copy.setIndent(label.indent())
    copy.setAlignment(label.alignment())
    copy.setWordWrap(label.wordWrap())
    copy.setScaledContents(label.hasScaledContents())
    copy.setTextFormat(label.textFormat())
    pixmap = label.pixmap()
    if pixmap.isNull():
        copy.setText(label.text())
    else:
        copy.setPixmap(pixmap)
    copy.resize(label.size())

    dpr = label.devicePixelRatioF()
    image = QImage(QSize(max(1, round(label.width() * dpr)), max(1, round(label.height() * dpr))),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    copy.render(image, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
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
        self.nest = Nest(stage)
        self.egg = FallingEgg(stage)
        self.eggSpot = QPointF()
        """Where the egg lands: on the end of the app's name."""

        self.segments: list[Segment] = []
        self.elapsed = 0.0
        self.rounds = 0
        """Rounds completed: how many eggs have been brought home, hatchings included."""
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

    def cursorPos(self) -> QPoint | None:
        """The mouse pointer on the stage, or None when it's elsewhere.
        (On Wayland, Qt only knows where the pointer is while it's over our windows.)"""
        pos = self.stage.mapFromGlobal(QCursor.pos())
        return pos if self.stage.rect().contains(pos) else None

    def enabled(self) -> bool:
        return settings.prefs.homeMascot

    def applyPrefs(self):
        """The Settings switch: a disabled mascot takes its nest and egg with it, and stops ticking."""
        if not self.enabled():
            self.timer.stop()
            for widget in self, self.nest, self.egg:
                widget.hide()
            return
        if self.stage.isVisible():
            self.timer.start()
            self.geometryKey = None  # the nest was hidden: place everything again
            self.advance(0)

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

    def nestRect(self, logo: Surface, home: QPointF) -> QRectF:
        """On the logo, just behind where the dinosaur stands."""
        width, height = NEST_W * PIXEL, NEST_H * PIXEL
        right = home.x() - 5 * PIXEL
        return QRectF(right - width, logo.top - height, width, height)

    def plan(self) -> list[Segment]:
        """Beret on the logo → "Welcome to" → the egg at the end of the name, and back home with it."""
        found = self.surfaces()
        if found is None:
            return []
        logo, welcomeLine, nameLine = found
        body = 4 * PIXEL  # half the legs' span: keep both feet on the ledge

        def on(surface: Surface, x: float) -> QPointF:
            return QPointF(max(surface.left + body, min(surface.right - body, x)), surface.top)

        # Home is the right end of the logo's top, leaving the left end to the nest
        home = on(logo, logo.right - body)
        welcomeFrom = on(welcomeLine, welcomeLine.left + body * 2)
        welcomeTo = on(welcomeLine, welcomeLine.right - body * 2)
        self.eggSpot = QPointF(nameLine.right - 3 * PIXEL, nameLine.top)
        # Close enough for the arms to reach down to the egg
        atEgg = on(nameLine, self.eggSpot.x() - 9 * PIXEL)
        # Landing on "…chette", a few steps before the egg
        nameFrom = on(nameLine, min(nameLine.right - 0.45 * (nameLine.right - nameLine.left),
                                    atEgg.x() - 6 * PIXEL))

        def walk(a: QPointF, b: QPointF, carrying=False) -> Segment:
            return Segment("walk", a, b, 1000 * abs(b.x() - a.x()) / WALK_SPEED, 1 if b.x() >= a.x() else -1, carrying)

        def jump(a: QPointF, b: QPointF, carrying=False) -> Segment:
            return Segment("jump", a, b, JUMP_MS, 1 if b.x() >= a.x() else -1, carrying)

        segments = [
            Segment("greet", home, home, GREET_MS, 1),
            jump(home, welcomeFrom),
            walk(welcomeFrom, welcomeTo),
            jump(welcomeTo, nameFrom),
            walk(nameFrom, atEgg),
            Segment("pick", atEgg, atEgg, PICK_MS, 1),
            Segment("turn", atEgg, atEgg, TURN_MS, -1, carrying=True),
            walk(atEgg, nameFrom, carrying=True),
            jump(nameFrom, welcomeTo, carrying=True),
            walk(welcomeTo, welcomeFrom, carrying=True),
            jump(welcomeFrom, home, carrying=True),
            Segment("place", home, home, PLACE_MS, -1, carrying=True),
            Segment("turn", home, home, TURN_MS, 1),
        ]
        # Whatever the walks leave of the round, it spends at home, by its nest
        busy = sum(s.duration for s in segments)
        segments.append(Segment("rest", home, home, max(0.0, MIN_ROUND_MS - busy), 1))
        return segments

    def cycleDuration(self) -> float:
        return sum(s.duration for s in self.segments)

    def segmentStart(self, kind: str, nth: int = 0) -> float:
        """When the nth segment of this kind begins, in round time."""
        t = 0.0
        for segment in self.segments:
            if segment.kind == kind:
                if nth == 0:
                    return t
                nth -= 1
            t += segment.duration
        raise KeyError(kind)

    def fallStart(self) -> float:
        """The egg starts falling as the dinosaur sets off along "Welcome to"."""
        return self.segmentStart("walk")

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
            self.nest.hide()
            self.egg.hide()
            return

        logo, _welcome, _name = self.surfaces()
        self.nest.setGeometry(self.nestRect(logo, self.segments[0].start).toRect())
        self.nest.show()

        # Back to front: the dinosaur walks in front of everything
        self.nest.raise_()
        self.egg.raise_()
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
    def handsPose(t: float, carryingBefore: bool) -> Pose:
        """Bending down to pick the egg up (or to lay it), then straightening up."""
        carrying = carryingBefore if t < LET_GO_AT else not carryingBefore
        if t < LET_GO_AT + 300:
            return Pose(arm="reachDown", carrying=carrying)
        return Pose(arm="carry" if carrying else "rest", carrying=carrying)

    def eggPosition(self, t: float) -> QPointF | None:
        """Where the loose egg is at round time t: falling, bouncing, or lying there. None when held or not yet."""
        start = self.fallStart()
        pickedUp = self.segmentStart("pick") + LET_GO_AT
        if t < start or t >= pickedUp:
            return None
        ground = self.eggSpot.y()
        if t < start + FALL_MS:
            progress = (t - start) / FALL_MS
            return QPointF(self.eggSpot.x(), ground * progress * progress)  # gravity
        if t < start + FALL_MS + BOUNCE_MS:
            progress = (t - start - FALL_MS) / BOUNCE_MS
            return QPointF(self.eggSpot.x(), ground - 4 * PIXEL * math.sin(math.pi * progress))
        return QPointF(self.eggSpot)

    def nestState(self, t: float) -> tuple[int, bool, int]:
        """Eggs in the nest at round time t: (count, hatched, wobble)."""
        before = self.rounds % NEST_CAPACITY
        if before == 0 and self.rounds > 0 and t < GREET_MS:
            # A full nest hatches while the dinosaur greets you: the eggs
            # wobble, then crack open; the babies are gone by the time it leaves
            if t < GREET_MS / 2:
                return NEST_CAPACITY, False, int(t // 150) % 2
            return NEST_CAPACITY, True, 0
        laid = t >= self.segmentStart("place") + LET_GO_AT
        return before + laid, False, 0

    def advance(self, ms: float):
        """Move `ms` further along. The timer calls it; so can tests."""
        self.replanIfNeeded()
        if not self.segments:
            self.hide()
            return

        total = self.elapsed + ms
        cycle = self.cycleDuration()
        self.rounds += int(total // cycle)
        self.elapsed = total % cycle
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
        elif segment.kind == "rest":
            self.pose = STAND
        elif segment.kind == "pick":
            self.pose = self.handsPose(t, carryingBefore=False)
        elif segment.kind == "place":
            self.pose = self.handsPose(t, carryingBefore=True)
        elif segment.kind == "turn":
            # Look the way it came for a moment, then turn
            self.facing = segment.facing if progress >= 0.5 else -segment.facing
            self.pose = Pose(arm="carry" if segment.carrying else "rest", carrying=segment.carrying)
        elif segment.kind == "walk":
            self.pose = Pose(legs="stride" if int(t // STEP_MS) % 2 else "stand",
                             arm="carry" if segment.carrying else "rest", carrying=segment.carrying)
            self.feet = a + (b - a) * progress
        else:
            self.pose = Pose(legs="tuck", arm="carry" if segment.carrying else "up", carrying=segment.carrying)
            # Straight line between the two ledges, lifted by an arc that clears the higher one
            lift = 20 + max(0.0, a.y() - b.y())
            x = a.x() + (b.x() - a.x()) * progress
            y = a.y() + (b.y() - a.y()) * progress - 4 * lift * progress * (1 - progress)
            self.feet = QPointF(x, y)

        self.move(math.floor(self.feet.x() - self.width() / 2), math.floor(self.feet.y()) - self.height())

        egg = self.eggPosition(self.elapsed)
        self.egg.setShown(egg is not None)
        if egg is not None:
            self.egg.standOn(egg.x(), egg.y())

        self.nest.setEggs(*self.nestState(self.elapsed))

        if settings.prefs.homeMascotFollowsCursor and not self.pose.eyesClosed:
            look = self.lookAt(self.cursorPos())
            if look != self.pose.look:
                self.pose = dataclasses.replace(self.pose, look=look)

        if not self.isVisible():
            self.show()
        self.update()

    def lookAt(self, target: QPoint | None) -> tuple[int, int]:
        """Which corner of the eye the pupil goes to, to look at `target`."""
        if target is None:
            return LOOK_AHEAD
        ex, ey = _EYE[3]  # the eye's center is the top-left corner of its last pixel
        eyeX = self.x() + (ex if self.facing > 0 else CANVAS_W - ex) * PIXEL
        eyeY = self.y() + ey * PIXEL
        front = (target.x() - eyeX) * self.facing >= 0
        down = target.y() >= eyeY
        return int(front), int(down)

    def appear(self):
        if self.enabled():
            self.advance(0)

    def isAnimating(self) -> bool:
        return self.timer.isActive()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.stage:
            if event.type() == QEvent.Type.Show and self.enabled():
                self.timer.start()
                # After the layout has placed the labels it stands on
                QTimer.singleShot(0, self.appear)
            elif event.type() == QEvent.Type.Hide:
                self.timer.stop()
        return super().eventFilter(watched, event)

    # -------------------------------------------------------------------------
    # Drawing

    def paintEvent(self, event: QPaintEvent):
        paintPixels(self, self.pose.pixels(), _COLORS, self.facing < 0, CANVAS_W)
