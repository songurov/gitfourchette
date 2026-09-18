# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms import homemascot as hm
from gitfourchette.forms.homemascot import HomeMascot
from .util import *


def stillMascot(mainWindow) -> HomeMascot:
    """The mascot with its timer off, so the test moves it by hand."""
    mascot = mainWindow.welcomeWidget.mascot
    waitUntilTrue(lambda: mascot.isVisible())
    mascot.timer.stop()
    at(mascot, 0)
    return mascot


def at(mascot: HomeMascot, t: float):
    """Put the mascot at time t of the round."""
    mascot.elapsed = 0.0
    mascot.advance(t)


def endOf(mascot: HomeMascot, index: int):
    at(mascot, sum(s.duration for s in mascot.segments[:index + 1]) - 1)


def atTable(mascot: HomeMascot, t: float):
    at(mascot, mascot.segmentStart("table") + t)


def stageRect(widget: QWidget, stage: QWidget) -> QRect:
    return QRect(widget.mapTo(stage, QPoint(0, 0)), widget.size())


def testStandsOnTheGlyphsNotOnTheLabels(mainWindow):
    mascot = stillMascot(mainWindow)
    welcome = mainWindow.welcomeWidget
    logo, welcomeLine, nameLine = mascot.surfaces()

    logoRect = stageRect(welcome.ui.logoLabel, welcome.ui.splashPage)
    textRect = stageRect(welcome.ui.welcomeLabel, welcome.ui.splashPage)
    # Inside the labels, but on the ink: the labels have room around their contents
    assert logoRect.left() <= logo.left < logo.right <= logoRect.right() + 1
    assert logoRect.top() <= logo.top
    assert textRect.top() < welcomeLine.top < nameLine.top < textRect.bottom()
    # "Welcome to" is shorter than the app's name, and both start at the same place
    assert welcomeLine.right < nameLine.right
    assert abs(welcomeLine.left - nameLine.left) < 4


def testWalksTheWholeRound(mainWindow):
    mascot = stillMascot(mainWindow)
    logo, welcomeLine, nameLine = mascot.surfaces()
    kinds = [s.kind for s in mascot.segments]
    assert kinds == ["greet", "jump", "walk", "jump", "walk", "table", "turn",
                     "walk", "jump", "walk", "jump", "turn"]

    at(mascot, 1)
    assert mascot.feet.y() == logo.top
    endOf(mascot, 1)
    assert abs(mascot.feet.y() - welcomeLine.top) < 1  # landed on "Welcome to"
    endOf(mascot, 2)
    assert mascot.facing == 1
    endOf(mascot, 3)
    assert abs(mascot.feet.y() - nameLine.top) < 1  # landed on the name
    endOf(mascot, 6)
    assert mascot.facing == -1  # turned around to go home
    endOf(mascot, 10)
    assert abs(mascot.feet.y() - logo.top) < 1  # home again
    assert logo.left <= mascot.feet.x() <= logo.right
    endOf(mascot, 11)
    assert mascot.facing == 1  # ready for the next round


def testTakesItsTime(mainWindow):
    """It was too busy: a round takes a while, and it strolls."""
    mascot = stillMascot(mainWindow)
    assert mascot.cycleDuration() >= 25_000
    assert hm.WALK_SPEED <= 25


def testTipsItsBeretBeforeSettingOff(mainWindow):
    mascot = stillMascot(mainWindow)
    start = QPointF(mascot.segments[0].start)

    at(mascot, 200)
    assert mascot.pose.beret == hm.BERET_ON_HEAD
    assert mascot.pose.arm == "grab"
    at(mascot, 800)
    assert mascot.pose.beret == hm.BERET_LIFTED
    at(mascot, 2000)  # the bow: beret to the chest, eyes closed
    assert mascot.pose.beret == hm.BERET_AT_CHEST
    assert mascot.pose.eyesClosed
    at(mascot, 3000)
    assert mascot.pose.beret == hm.BERET_LIFTED
    endOf(mascot, 0)
    assert mascot.pose.beret == hm.BERET_ON_HEAD
    assert not mascot.pose.eyesClosed
    # ...all without taking a step
    assert mascot.feet == start


def testToastsTheCroissantWithFireThenEatsIt(mainWindow):
    mascot = stillMascot(mainWindow)
    _logo, _welcomeLine, nameLine = mascot.surfaces()
    table = mascot.table.geometry()

    # The table stands on the end of the name, the dinosaur stops just before it
    assert table.bottom() + 1 == round(nameLine.top)
    assert abs(table.right() + 1 - nameLine.right) <= 1
    atTable(mascot, 0)
    assert mascot.geometry().right() <= table.left() + hm.PIXEL
    assert not mascot.fire.isVisible()

    # Fire, out of the mouth, towards the croissant
    atTable(mascot, hm.FIRE_AT + 200)
    assert mascot.fire.isVisible()
    assert mascot.pose.mouthOpen
    assert mascot.fire.geometry().left() >= mascot.feet.x()
    assert mascot.fire.geometry().right() >= table.left()
    atTable(mascot, hm.TOASTED_AT + 100)
    assert mascot.table.hasCroissant and mascot.table.toasted

    # Then it takes it and eats it, bite by bite
    atTable(mascot, hm.FIRE_END + 100)
    assert not mascot.fire.isVisible()
    assert mascot.pose.arm == "reachTable"
    bitesLeft = []
    for t in range(hm.TAKE_AT + 50, hm.WINDUP_AT, 150):
        atTable(mascot, t)
        assert not mascot.table.hasCroissant
        bitesLeft.append(mascot.pose.held or 0)
    assert bitesLeft[0] == hm.BITES
    assert bitesLeft == sorted(bitesLeft, reverse=True)
    assert set(bitesLeft) == set(range(hm.BITES + 1))

    # A fresh, untoasted croissant for the next round
    at(mascot, mascot.cycleDuration() + 10)
    assert mascot.table.hasCroissant and not mascot.table.toasted


def testThrowsABouleThatStopsByTheJack(mainWindow):
    mascot = stillMascot(mainWindow)
    stage = mascot.stage
    pitch = mascot.pitch.geometry()

    # The pitch lies at the bottom of the page, centered
    assert pitch.bottom() > stage.height() * 0.8
    assert abs(pitch.center().x() - stage.width() / 2) <= 2

    atTable(mascot, hm.THROW_AT - 1)
    assert not mascot.boule.isVisible()
    assert mascot.facing == mascot.throwDirection  # facing the jack to throw

    atTable(mascot, hm.THROW_AT + 1)
    assert mascot.boule.isVisible()
    assert (mascot.boule.geometry().center() - mascot.throwFrom.toPoint()).manhattanLength() < 12

    # A lob: it rises above the hand before it falls
    peak = min(mascot.boulePosition(hm.THROW_AT + k).y() for k in range(0, hm.FLIGHT_MS, 50))
    assert peak < mascot.throwFrom.y()

    # Lands short of the jack and rolls on the same way, stopping right by it
    landed = mascot.boulePosition(hm.THROW_AT + hm.FLIGHT_MS)
    rested = mascot.boulePosition(hm.THROW_AT + hm.FLIGHT_MS + hm.ROLL_MS)
    jack = mascot.pitch.jackX()
    assert (jack - landed.x()) * mascot.throwDirection > 0
    assert (rested.x() - landed.x()) * mascot.throwDirection > 0
    assert abs(rested.x() - jack) <= 6 * hm.PIXEL
    assert rested.y() == mascot.pitch.groundTop()

    # Still there while it walks home, gone when the next round starts
    endOf(mascot, 10)
    assert mascot.boule.isVisible()
    at(mascot, mascot.cycleDuration() + 10)
    assert not mascot.boule.isVisible()


def testCheersWhenTheBouleStops(mainWindow):
    mascot = stillMascot(mainWindow)
    atTable(mascot, hm.CHEER_AT + (hm.TABLE_MS - hm.CHEER_AT) / 2)
    assert mascot.pose.legs == "tuck"
    assert mascot.feet.y() < mascot.segments[5].start.y()  # a little hop


def testJumpsArcAboveBothLedges(mainWindow):
    mascot = stillMascot(mainWindow)
    jump = mascot.segments[1]
    at(mascot, mascot.segments[0].duration + jump.duration / 2)
    assert mascot.pose.legs == "tuck"
    assert mascot.feet.y() < min(jump.start.y(), jump.end.y())


def testLegsMoveWhileWalking(mainWindow):
    mascot = stillMascot(mainWindow)
    walkStart = sum(s.duration for s in mascot.segments[:2])
    legs = set()
    for step in range(4):
        at(mascot, walkStart + 1 + step * hm.STEP_MS)
        legs.add(mascot.pose.legs)
    assert legs == {"stand", "stride"}


def testOnlyAnimatesWhileTheSplashIsShown(tempDir, mainWindow):
    mascot = mainWindow.welcomeWidget.mascot
    waitUntilTrue(mascot.isAnimating)

    mainWindow.openRepo(unpackRepo(tempDir))
    assert not mascot.isAnimating(), "no ticking behind a repo"

    mainWindow.closeAllTabs()
    waitUntilTrue(mascot.isAnimating)


def colorsIn(widget: QWidget) -> set[str]:
    image = widget.grab().toImage()
    return {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}


def testEverythingIsDrawnAndLetsClicksThrough(mainWindow):
    mascot = stillMascot(mainWindow)
    atTable(mascot, hm.TOASTED_AT + 100)  # fire still going, croissant already toasted
    for widget in mascot, mascot.table, mascot.fire, mascot.boule, mascot.pitch:
        assert widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), widget.objectName()
    assert {hm._COLORS[k].name() for k in "OSR"} <= colorsIn(mascot)  # dino, spikes, beret
    assert {hm._COLORS[k].name() for k in ("T_", "D")} <= colorsIn(mascot.table)  # toasted croissant
    assert hm._COLORS["F"].name() in colorsIn(mascot.fire)
    assert {hm._COLORS[k].name() for k in "PJ"} <= colorsIn(mascot.pitch)  # sand and jack


def testFacingLeftMirrorsTheDinosaur(mainWindow):
    mascot = stillMascot(mainWindow)

    def pupilColumns():
        image = mascot.grab().toImage()
        y = 8 * hm.PIXEL + 1
        pupil = hm._COLORS["K"].name()
        return [x for x in range(image.width()) if image.pixelColor(x, y).name() == pupil]

    mascot.pose = hm.STAND
    mascot.facing = 1
    right = pupilColumns()
    mascot.facing = -1
    left = pupilColumns()
    assert right and left
    assert sum(right) / len(right) > mascot.width() / 2 > sum(left) / len(left)


def testWalksInFrontOfTheProps(mainWindow):
    mascot = stillMascot(mainWindow)
    widgets = [w for w in mascot.stage.children() if isinstance(w, QWidget)]
    for prop in mascot.table, mascot.pitch, mascot.boule, mascot.fire:
        assert widgets.index(mascot) > widgets.index(prop), prop.objectName()
