# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms import homepitchscene as ps
from gitfourchette.forms.homepitchscene import PitchScene
from .util import *


def stillScene(mainWindow) -> PitchScene:
    mascot = mainWindow.welcomeWidget.mascot
    waitUntilTrue(lambda: mascot.isVisible())
    mascot.timer.stop()
    mascot.elapsed = 0.0
    mascot.advance(0)
    return mainWindow.welcomeWidget.pitchScene


def at(scene: PitchScene, t: float):
    scene.elapsed = 0.0
    scene.advance(t)


def colorsIn(widget: QWidget) -> set[str]:
    image = widget.grab().toImage()
    return {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}


def testLandmarksAndFlagsStandAtEachEndOfThePitch(mainWindow):
    scene = stillScene(mainWindow)
    pitch = mainWindow.welcomeWidget.mascot.pitch.geometry()
    ground = round(scene.ground)

    for sprite in scene.eiffel, scene.arch, scene.franceFlag, scene.moldovaFlag:
        assert sprite.isVisible(), sprite.objectName()
        assert sprite.geometry().bottom() + 1 == ground, sprite.objectName()
        assert pitch.left() <= sprite.geometry().left() and sprite.geometry().right() <= pitch.right()

    # France on the left, Moldova on the right, each flag beside its landmark
    assert scene.franceFlag.x() < scene.eiffel.x() < pitch.center().x()
    assert pitch.center().x() < scene.arch.x() < scene.moldovaFlag.x()


def testTheFlagsAreTheRightFlags(mainWindow):
    scene = stillScene(mainWindow)

    def names(*keys):
        return {ps._PALETTE[k].name() for k in keys}

    assert names("fB", "fW", "fR") <= colorsIn(scene.franceFlag)
    assert names("mb", "my", "mr", "mm") <= colorsIn(scene.moldovaFlag)  # with the coat of arms


def testEachLeavesFromHisLandmark(mainWindow):
    scene = stillScene(mainWindow)
    at(scene, 100)
    napoleon, stephen = scene.napoleon.sprite, scene.stephen.sprite
    # Napoleon from under the tower, Stephen from the arch's passage
    assert scene.eiffel.geometry().left() < napoleon.geometry().center().x() < scene.eiffel.geometry().right()
    passage = scene.arch.x() + ps.ARCH_PASSAGE_X * ps.PIXEL
    assert abs(stephen.geometry().center().x() - passage) <= ps.PIXEL
    # Facing each other, both on the ground
    assert (napoleon.facing, stephen.facing) == (1, -1)
    assert napoleon.geometry().bottom() + 1 == round(scene.ground) == stephen.geometry().bottom() + 1
    # ...and in front of their landmarks
    widgets = [w for w in napoleon.parent().children() if isinstance(w, QWidget)]
    assert widgets.index(napoleon) > widgets.index(scene.eiffel)
    assert widgets.index(stephen) > widgets.index(scene.arch)


def testTheyMeetInTheMiddleAndShakeHands(mainWindow):
    scene = stillScene(mainWindow)
    napoleon, stephen = scene.napoleon.sprite, scene.stephen.sprite
    shakeStart = ps.WAIT_MS + scene.walkMs()

    at(scene, ps.WAIT_MS + scene.walkMs() / 2)
    assert napoleon.x() > scene.napoleon.home - napoleon.width()

    positions = []
    for t in range(0, ps.SHAKE_MS, ps.SHAKE_STEP_MS):
        at(scene, shakeStart + t + 10)
        positions.append(napoleon.shaking)
        # Toe to toe, right in the middle between their two homes
        assert napoleon.geometry().right() + 1 == stephen.geometry().left()
        middle = (scene.napoleon.home + scene.stephen.home) / 2
        assert abs(napoleon.geometry().right() + 1 - middle) <= 1
        assert (napoleon.facing, stephen.facing) == (1, -1)
    # The hands go up and down
    assert set(positions) == {True, False}
    assert stephen.shaking is not None


def testStephenHoldsHisCrossInTheOtherHandToShake(mainWindow):
    scene = stillScene(mainWindow)
    stephen = scene.stephen.sprite
    at(scene, 100)
    assert all(stephen.pixels()[xy] == "x" for xy in ps._CROSS_FRONT)
    at(scene, ps.WAIT_MS + scene.walkMs() + 10)
    assert all(stephen.pixels()[xy] == "x" for xy in ps._CROSS_BACK)
    assert stephen.pixels()[ps._HANDSHAKE[True][-1]] == "f"  # the hand, held out


def testLegsMoveWhileWalking(mainWindow):
    scene = stillScene(mainWindow)
    strides = set()
    for step in range(4):
        at(scene, ps.WAIT_MS + 10 + step * ps.STEP_MS)
        strides.add(scene.napoleon.sprite.stride)
    assert strides == {True, False}


def testThenTheyWalkBackHome(mainWindow):
    scene = stillScene(mainWindow)
    napoleon, stephen = scene.napoleon.sprite, scene.stephen.sprite
    backStart = ps.WAIT_MS + scene.walkMs() + ps.SHAKE_MS + ps.TURN_MS
    at(scene, backStart + scene.walkMs() / 2)
    assert (napoleon.facing, stephen.facing) == (-1, 1)  # backs to each other
    at(scene, backStart + scene.walkMs() - 1)
    assert abs(napoleon.geometry().center().x() - scene.napoleon.home) <= 2
    assert abs(stephen.geometry().center().x() - scene.stephen.home) <= 2
    # Turning round at home, ready for the next round
    at(scene, scene.cycleDuration() - 1)
    assert (napoleon.facing, stephen.facing) == (1, -1)


def testTheFlagsFlutter(mainWindow):
    scene = stillScene(mainWindow)
    at(scene, 0)
    first = scene.franceFlag.grab().toImage()
    at(scene, 400)
    assert scene.franceFlag.grab().toImage() != first


def testItMovesOnTheMascotsClock(mainWindow):
    """One timer for the whole page: the mascot's ticks drive the scene too."""
    scene = stillScene(mainWindow)
    before = scene.elapsed
    mainWindow.welcomeWidget.mascot.advance(1234)
    assert abs(scene.elapsed - (before + 1234)) < 1


def testNothingTakesAClick(mainWindow):
    scene = stillScene(mainWindow)
    for sprite in scene.sprites():
        assert sprite.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), sprite.objectName()
