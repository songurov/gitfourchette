# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms import homemascot
from gitfourchette.forms.homemascot import HomeMascot
from .util import *


def stillMascot(mainWindow) -> HomeMascot:
    """The mascot with its timer off, so the test moves it by hand."""
    mascot = mainWindow.welcomeWidget.mascot
    waitUntilTrue(lambda: mascot.isVisible())
    mascot.timer.stop()
    mascot.elapsed = 0.0
    mascot.advance(0)
    return mascot


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


def at(mascot: HomeMascot, t: float):
    """Put the mascot at cycle time t."""
    mascot.elapsed = 0.0
    mascot.advance(t)


def endOf(mascot: HomeMascot, index: int):
    at(mascot, sum(s.duration for s in mascot.segments[:index + 1]) - 1)


def testWalksTheWholeRound(mainWindow):
    mascot = stillMascot(mainWindow)
    logo, welcomeLine, nameLine = mascot.surfaces()
    kinds = [s.kind for s in mascot.segments]
    assert kinds == ["greet", "jump", "walk", "jump", "walk", "eat", "turn",
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
    assert mascot.facing == -1  # turned around after eating
    endOf(mascot, 10)
    assert abs(mascot.feet.y() - logo.top) < 1  # home again
    assert logo.left <= mascot.feet.x() <= logo.right
    endOf(mascot, 11)
    assert mascot.facing == 1  # ready for the next round


def testTakesItsTime(mainWindow):
    """It was too busy: a round takes a while, and it strolls."""
    mascot = stillMascot(mainWindow)
    assert mascot.cycleDuration() >= 20_000
    assert homemascot.WALK_SPEED <= 25


def testTipsItsHatBeforeSettingOff(mainWindow):
    mascot = stillMascot(mainWindow)
    start = QPointF(mascot.segments[0].start)

    at(mascot, 200)
    assert mascot.pose.hat == homemascot.HAT_ON_HEAD
    assert mascot.pose.arm == "reachHat"
    at(mascot, 700)
    assert mascot.pose.hat == homemascot.HAT_LIFTED
    at(mascot, 1700)  # the bow: hat to the chest, eyes down
    assert mascot.pose.hat == homemascot.HAT_AT_CHEST
    assert mascot.pose.eyesDown
    at(mascot, 2600)
    assert mascot.pose.hat == homemascot.HAT_LIFTED
    endOf(mascot, 0)
    assert mascot.pose.hat == homemascot.HAT_ON_HEAD
    # ...all without taking a step
    assert mascot.feet == start
    at(mascot, homemascot.GREET_MS + 1)
    assert mascot.segments[1].kind == "jump"


def testEatsTheCroissantAtTheTable(mainWindow):
    mascot = stillMascot(mainWindow)
    _logo, _welcomeLine, nameLine = mascot.surfaces()
    table = mascot.table.geometry()
    eat = mascot.segmentStart("eat")

    # The table stands on the end of the name, the mascot stops just before it
    assert table.bottom() + 1 == round(nameLine.top)
    assert abs(table.right() + 1 - nameLine.right) <= 1
    assert mascot.segments[5].start.x() + 3 * homemascot.PIXEL < table.left()

    at(mascot, eat - 1)
    assert mascot.table.hasCroissant
    at(mascot, eat + 700)
    assert mascot.pose.arm == "reachTable"
    assert mascot.table.hasCroissant

    # Taken: it leaves the table for the hand, then goes bite by bite
    bitesLeft = []
    for t in range(homemascot.EAT_TAKE_AT + 100, homemascot.EAT_MS, 200):
        at(mascot, eat + t)
        assert not mascot.table.hasCroissant
        bitesLeft.append(mascot.pose.held or 0)
    assert bitesLeft[0] == homemascot.BITES
    assert bitesLeft == sorted(bitesLeft, reverse=True)
    assert set(bitesLeft) == set(range(homemascot.BITES + 1))
    assert bitesLeft[-1] == 0

    # Walks home without it, and a fresh one is there for the next round
    endOf(mascot, 9)
    assert not mascot.table.hasCroissant
    at(mascot, mascot.cycleDuration() + 10)
    assert mascot.table.hasCroissant


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
        at(mascot, walkStart + 1 + step * homemascot.STEP_MS)
        legs.add(mascot.pose.legs)
    assert legs == {"stand", "stride"}


def testOnlyAnimatesWhileTheSplashIsShown(tempDir, mainWindow):
    mascot = mainWindow.welcomeWidget.mascot
    waitUntilTrue(mascot.isAnimating)

    mainWindow.openRepo(unpackRepo(tempDir))
    assert not mascot.isAnimating(), "no ticking behind a repo"

    mainWindow.closeAllTabs()
    waitUntilTrue(mascot.isAnimating)


def testIsDrawnAndLetsClicksThrough(mainWindow):
    mascot = stillMascot(mainWindow)
    for widget in mascot, mascot.table:
        assert widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    image = mascot.grab().toImage()
    colors = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}
    assert homemascot._COLORS["B"].name() in colors
    assert homemascot._COLORS["H"].name() in colors
    table = mascot.table.grab().toImage()
    colors = {table.pixelColor(x, y).name() for x in range(table.width()) for y in range(table.height())}
    assert homemascot._COLORS["T"].name() in colors
    assert homemascot._COLORS["C"].name() in colors  # the croissant


def testFacingLeftMirrorsTheEyes(mainWindow):
    mascot = stillMascot(mainWindow)

    def eyeColumns():
        image = mascot.grab().toImage()
        y = 7 * homemascot.PIXEL + 1
        eye = homemascot._COLORS["E"].name()
        return [x for x in range(image.width()) if image.pixelColor(x, y).name() == eye]

    mascot.pose = homemascot.STAND
    mascot.facing = 1
    right = eyeColumns()
    mascot.facing = -1
    left = eyeColumns()
    assert right and left and right != left


def testWalksInFrontOfTheTable(mainWindow):
    mascot = stillMascot(mainWindow)
    widgets = [w for w in mascot.stage.children() if isinstance(w, QWidget)]
    assert widgets.index(mascot) > widgets.index(mascot.table)
