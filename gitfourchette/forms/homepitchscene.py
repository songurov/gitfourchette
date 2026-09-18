# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
France and Moldova, shaking hands on the pétanque pitch at the bottom of Home.

The Eiffel Tower stands at one end of the pitch with the French flag, the
Triumphal Arch of Chișinău at the other with the Moldovan flag. Napoleon steps
out from under the tower, Stephen the Great out of the arch; they walk towards
each other, meet in the middle, shake hands, and walk back home. Then again.
"""

import dataclasses

from gitfourchette.forms.pixelart import PIXEL, PixelSprite, Pixels, gridPixels, paintPixels
from gitfourchette.qt import *

_EIFFEL = (
    ".......e.......",
    ".......e.......",
    ".......E.......",
    ".......E.......",
    "......EEE......",
    "......E.E......",
    "......EeE......",
    "......E.E......",
    "......EeE......",
    "......E.E......",
    "......EeE......",
    "......E.E......",
    "......EeE......",
    ".....EEEEE.....",
    ".....E.e.E.....",
    ".....Ee.eE.....",
    ".....E.e.E.....",
    "....EEe.eEE....",
    "....E.e.e.E....",
    "....Ee.e.eE....",
    "....E.e.e.E....",
    "...EEEEEEEEE...",
    "...eeeeeeeee...",
    "...EE.....EE...",
    "..EEe.....eEE..",
    "..EE.......EE..",
    "..Ee.......eE..",
    ".EE.........EE.",
    ".Ee.........eE.",
    ".EE.........EE.",
    "EEe.........eEE",
    "EE...........EE",
)

# The Triumphal Arch in Chișinău: attic with its lunette, cornice, pilasters, and
# the passage Stephen the Great walks out of
_ARCH = (
    "....AAAAAAAAAAAA....",
    "....AaaaKKKKaaaA....",
    "....AaaKKKKKKaaA....",
    "AAAAAAAAAAAAAAAAAAAA",
    "aaaaaaaaaaaaaaaaaaaa",
    ".AAAAAAAAAAAAAAAAAA.",
    ".AaAAaAAAAAAAAaAAaA.",
    ".AaAAaAAKKKKAAaAAaA.",
    ".AaAAaAKKKKKKAaAAaA.",
    *[".AaAAaAKKKKKKAaAAaA."] * 12,
    "AAAAAAAKKKKKKAAAAAAA",
)
ARCH_PASSAGE_X = 10
"""The middle of the passage, in the arch's pixels."""

FLAG_W, FLAG_H = 10, 16
_FRANCE = tuple("pBBBWWWRRR" for _ in range(6))
_MOLDOVA = (
    "pbbbyyyrrr",
    "pbbbyyyrrr",
    "pbbbymyrrr",
    "pbbbymyrrr",
    "pbbbyyyrrr",
    "pbbbyyyrrr",
)
_POLE = ("p.........",) * (FLAG_H - 6)

# Characters: 10 x 16, facing right, feet on the bottom row
WALKER_W, WALKER_H = 10, 16
_NAPOLEON = (
    "..NNNNNN..",
    ".NNNNNNNN.",
    "...ffff...",
    "...ffkf...",
    "..gBBBBg..",
    "..BBwwBB..",
    "..BBwwBB..",
    "..BBwwBB..",
    "..BBBBBB..",
    "..BBBBBB..",
    "...wwww...",
    "...wwww...",
)
_NAPOLEON_LEGS = {
    "stand": ("...w..w...", "...b..b...", "...b..b...", "..bb..bb.."),
    "stride": ("..w....w..", "..b....b..", ".b......b.", ".bb.....bb"),
}
_STEPHEN = (
    "...g.g.g..",
    "...ggggg..",
    "...hffff..",
    "...hffkf..",
    "...hhhhh..",
    "..MuuuuM..",
    ".MMuuuuMM.",
    ".MMuuuuMM.",
    ".MMuuuuMM.",
    ".MMuuuuMM.",
    ".MMMuuMMM.",
    ".MMMuuMMM.",
)
_STEPHEN_LEGS = {
    "stand": ("..MM..MM..", "...b..b...", "...b..b...", "..bb..bb.."),
    "stride": ("..MM..MM..", "..b....b..", ".b......b.", ".bb.....bb"),
}
# Stephen holds a cross, like his statue in Chișinău; in the other hand when shaking
_CROSS_FRONT = [(9, 1), (8, 2), (9, 2), (9, 3), (9, 4)]
_CROSS_BACK = [(0, 1), (0, 2), (1, 2), (0, 3), (0, 4)]
# The hand held out, level with the belt; shaking moves it up and down
_HANDSHAKE = {True: [(8, 7), (9, 7)], False: [(8, 8), (9, 8)]}

_PALETTE = {
    "E": QColor("#7d5e40"),  # Eiffel Tower, puddled iron
    "e": QColor("#5a432e"),
    "A": QColor("#dccca3"),  # Triumphal Arch, stone
    "a": QColor("#b3a07a"),
    "K": QColor("#2a2d33"),  # the passage, the lunette
    "p": QColor("#9aa0a6"),  # flagpole
    "fB": QColor("#0055a4"),  # France
    "fW": QColor("#ffffff"),
    "fR": QColor("#ef4135"),
    "mb": QColor("#0046ae"),  # Moldova
    "my": QColor("#ffd200"),
    "mr": QColor("#cc092f"),
    "mm": QColor("#8a5a22"),  # the coat of arms, at this size a hint of it
    "N": QColor("#1a1a1a"),  # bicorne
    "f": QColor("#f1c9a0"),  # skin
    "k": QColor("#1b1b1b"),  # eye
    "g": QColor("#e8c34a"),  # gold: epaulettes, crown
    "B": QColor("#22428f"),  # Napoleon's coat
    "w": QColor("#eeeeee"),  # waistcoat, breeches
    "b": QColor("#2e1f16"),  # boots
    "M": QColor("#9e1b22"),  # Stephen's mantle
    "u": QColor("#caa24e"),  # Stephen's tunic
    "h": QColor("#5a3b22"),  # hair, beard
    "x": QColor("#f0cf5a"),  # the cross
}
_FRANCE_KEYS = {"p": "p", "B": "fB", "W": "fW", "R": "fR"}
_MOLDOVA_KEYS = {"p": "p", "b": "mb", "y": "my", "r": "mr", "m": "mm"}

PITCH_EIFFEL_X = 12
PITCH_ARCH_X = -32
"""Where the landmarks stand along the pitch, in sprite pixels (negative: from the right end)."""

WALK_SPEED = 18.0
"""Pixels per second: two statesmen, taking their time."""
STEP_MS = 300
WAIT_MS = 1500
SHAKE_MS = 2400
SHAKE_STEP_MS = 300
TURN_MS = 600


class Landmark(PixelSprite):
    def __init__(self, stage: QWidget, name: str, rows, keys: dict[str, str] | None = None):
        super().__init__(stage, name, len(rows[0]), len(rows))
        self.pixels = gridPixels(rows, keys)

    def paintEvent(self, event: QPaintEvent):
        paintPixels(self, self.pixels, _PALETTE)


class Flag(PixelSprite):
    """A flag on its pole, fluttering: the free corners take turns."""

    def __init__(self, stage: QWidget, name: str, cloth, keys: dict[str, str]):
        super().__init__(stage, name, FLAG_W, FLAG_H)
        self.cloth = gridPixels((*cloth, *_POLE), keys)
        self.frame = 0

    def paintEvent(self, event: QPaintEvent):
        corner = (FLAG_W - 1, 0) if self.frame % 2 else (FLAG_W - 1, 5)
        pixels = {xy: key for xy, key in self.cloth.items() if xy != corner}
        paintPixels(self, pixels, _PALETTE)


@dataclasses.dataclass
class Walker:
    sprite: "WalkerSprite"
    home: float = 0.0
    meet: float = 0.0


class WalkerSprite(PixelSprite):
    def __init__(self, stage: QWidget, name: str, body, legs: dict, isStephen: bool):
        super().__init__(stage, name, WALKER_W, WALKER_H)
        self.body = body
        self.legs = legs
        self.isStephen = isStephen
        self.facing = 1
        self.stride = False
        self.shaking: bool | None = None
        """None, or the hand's position while shaking: True up, False down."""

    def pixels(self) -> Pixels:
        pixels = gridPixels((*self.body, *self.legs["stride" if self.stride else "stand"]))
        if self.shaking is not None:
            for xy in _HANDSHAKE[self.shaking]:
                pixels[xy] = "M" if self.isStephen else "B"
            pixels[_HANDSHAKE[self.shaking][-1]] = "f"
        if self.isStephen:
            for xy in (_CROSS_BACK if self.shaking is not None else _CROSS_FRONT):
                pixels[xy] = "x"
        return pixels

    def paintEvent(self, event: QPaintEvent):
        paintPixels(self, self.pixels(), _PALETTE, self.facing < 0, WALKER_W)


class PitchScene:
    """Everything on the pitch but the pitch itself, driven by the mascot's timer."""

    def __init__(self, stage: QWidget):
        self.eiffel = Landmark(stage, "HomeEiffelTower", _EIFFEL)
        self.arch = Landmark(stage, "HomeTriumphalArch", _ARCH)
        self.franceFlag = Flag(stage, "HomeFlagFrance", _FRANCE, _FRANCE_KEYS)
        self.moldovaFlag = Flag(stage, "HomeFlagMoldova", _MOLDOVA, _MOLDOVA_KEYS)
        self.napoleon = Walker(WalkerSprite(stage, "HomeNapoleon", _NAPOLEON, _NAPOLEON_LEGS, isStephen=False))
        self.stephen = Walker(WalkerSprite(stage, "HomeStephenTheGreat", _STEPHEN, _STEPHEN_LEGS, isStephen=True))
        self.ground = 0.0
        self.elapsed = 0.0

    def sprites(self) -> list[PixelSprite]:
        """Back to front."""
        return [self.eiffel, self.arch, self.franceFlag, self.moldovaFlag,
                self.napoleon.sprite, self.stephen.sprite]

    def layout(self, pitch: QRect, ground: float):
        """Landmarks at both ends, flags beside them, and where the two meet."""
        self.ground = ground
        left, right = pitch.left(), pitch.right() + 1
        eiffelX = left + (PITCH_EIFFEL_X + len(_EIFFEL[0]) / 2) * PIXEL
        archLeft = right + PITCH_ARCH_X * PIXEL
        archX = archLeft + len(_ARCH[0]) / 2 * PIXEL

        self.eiffel.standOn(eiffelX, ground)
        self.arch.standOn(archX, ground)
        self.franceFlag.standOn(left + (FLAG_W / 2 + 1) * PIXEL, ground)
        self.moldovaFlag.standOn(right - (FLAG_W / 2 + 1) * PIXEL, ground)

        # Napoleon comes out from under the tower, Stephen out of the arch's passage
        self.napoleon.home = eiffelX
        self.stephen.home = archLeft + ARCH_PASSAGE_X * PIXEL
        # Toe to toe in the middle: their outstretched hands meet
        middle = (self.napoleon.home + self.stephen.home) / 2
        half = WALKER_W / 2 * PIXEL
        self.napoleon.meet = middle - half
        self.stephen.meet = middle + half
        self.elapsed = 0.0
        for sprite in self.sprites():
            sprite.show()

    def walkMs(self) -> float:
        return 1000 * abs(self.napoleon.meet - self.napoleon.home) / WALK_SPEED

    def cycleDuration(self) -> float:
        return WAIT_MS + self.walkMs() + SHAKE_MS + TURN_MS + self.walkMs() + TURN_MS

    def phase(self, t: float) -> tuple[str, float]:
        """Which part of the round t falls in, and how far into it."""
        for name, duration in (("wait", WAIT_MS), ("walkOut", self.walkMs()), ("shake", SHAKE_MS),
                               ("turnBack", TURN_MS), ("walkBack", self.walkMs()), ("turnHome", TURN_MS)):
            if t < duration:
                return name, t
            t -= duration
        return "turnHome", TURN_MS

    def advance(self, ms: float):
        if not self.walkMs():
            return
        self.elapsed = (self.elapsed + ms) % self.cycleDuration()
        name, t = self.phase(self.elapsed)
        walkMs = self.walkMs()

        for walker, towardsMiddle in (self.napoleon, 1), (self.stephen, -1):
            sprite = walker.sprite
            sprite.stride = False
            sprite.shaking = None
            x = walker.home
            facing = towardsMiddle
            if name == "walkOut":
                x = walker.home + (walker.meet - walker.home) * t / walkMs
                sprite.stride = bool(int(t // STEP_MS) % 2)
            elif name == "shake":
                x = walker.meet
                sprite.shaking = int(t // SHAKE_STEP_MS) % 2 == 0
            elif name == "turnBack":
                x = walker.meet
                facing = towardsMiddle if t < TURN_MS / 2 else -towardsMiddle
            elif name == "walkBack":
                x = walker.meet + (walker.home - walker.meet) * t / walkMs
                facing = -towardsMiddle
                sprite.stride = bool(int(t // STEP_MS) % 2)
            elif name == "turnHome":
                facing = -towardsMiddle if t < TURN_MS / 2 else towardsMiddle
            sprite.facing = facing
            sprite.standOn(x, self.ground)
            sprite.update()

        flutter = int(self.elapsed // 400)
        for flag in self.franceFlag, self.moldovaFlag:
            if flag.frame != flutter:
                flag.frame = flutter
                flag.update()

    def hide(self):
        for sprite in self.sprites():
            sprite.hide()
