# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools

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


def at(mascot: HomeMascot, t: float, rounds: int = 0):
    """Put the mascot at time t of a round, after `rounds` eggs brought home."""
    mascot.rounds = rounds
    mascot.elapsed = 0.0
    mascot.advance(t)


def endOf(mascot: HomeMascot, index: int):
    at(mascot, sum(s.duration for s in mascot.segments[:index + 1]) - 1)


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
    assert kinds == ["greet", "jump", "walk", "jump", "walk", "pick", "turn",
                     "walk", "jump", "walk", "jump", "place", "turn"]

    at(mascot, 1)
    assert mascot.feet.y() == logo.top
    endOf(mascot, 1)
    assert abs(mascot.feet.y() - welcomeLine.top) < 1  # landed on "Welcome to"
    endOf(mascot, 3)
    assert abs(mascot.feet.y() - nameLine.top) < 1  # landed on the name
    endOf(mascot, 6)
    assert mascot.facing == -1  # turned around to go home
    endOf(mascot, 10)
    assert abs(mascot.feet.y() - logo.top) < 1  # home again
    assert logo.left <= mascot.feet.x() <= logo.right
    endOf(mascot, 12)
    assert mascot.facing == 1  # ready for the next round


def testTakesItsTime(mainWindow):
    mascot = stillMascot(mainWindow)
    assert mascot.cycleDuration() >= 25_000
    assert hm.WALK_SPEED <= 25


def testNoSceneAtTheBottomAnyMore(mainWindow):
    """The pitch with the landmarks was dropped for a simpler page."""
    stage = mainWindow.welcomeWidget.ui.splashPage
    names = {w.objectName() for w in stage.findChildren(QWidget)}
    assert not names & {"HomeMascotPitch", "HomeMascotTable", "HomeEiffelTower", "HomeTriumphalArch"}


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
    # ...all without taking a step
    assert mascot.feet == start


def testAnEggFallsOntoTheEndOfTheName(mainWindow):
    mascot = stillMascot(mainWindow)
    _logo, _welcomeLine, nameLine = mascot.surfaces()
    fall = mascot.fallStart()

    at(mascot, fall - 1)
    assert not mascot.egg.isVisible()

    # It falls from above, faster and faster
    heights = []
    for k in (100, 600, 1100, 1600):
        at(mascot, fall + k)
        assert mascot.egg.isVisible()
        heights.append(mascot.egg.geometry().bottom())
    steps = [b - a for a, b in itertools.pairwise(heights)]
    assert steps[0] > 0
    assert all(later > earlier for earlier, later in itertools.pairwise(steps))  # accelerating

    # Lands on the name, near its end, before the dinosaur gets there
    at(mascot, fall + hm.FALL_MS + hm.BOUNCE_MS + 10)
    egg = mascot.egg.geometry()
    assert egg.bottom() + 1 == round(nameLine.top)
    assert nameLine.right - 12 * hm.PIXEL < egg.center().x() <= nameLine.right
    assert fall + hm.FALL_MS + hm.BOUNCE_MS < mascot.segmentStart("pick")
    # ...and it's in reach when the dinosaur stops
    at(mascot, mascot.segmentStart("pick"))
    assert egg.left() - mascot.geometry().right() < 2 * hm.PIXEL


def testCarriesTheEggHome(mainWindow):
    mascot = stillMascot(mainWindow)
    pick = mascot.segmentStart("pick")
    place = mascot.segmentStart("place")

    at(mascot, pick + 100)
    assert mascot.pose.arm == "reachDown"
    assert mascot.egg.isVisible() and not mascot.pose.carrying
    at(mascot, pick + hm.LET_GO_AT + 10)
    assert not mascot.egg.isVisible() and mascot.pose.carrying  # in its arms now

    # Held all the way home, jumps included
    for t in range(round(pick + hm.PICK_MS), round(place), 250):
        at(mascot, t)
        assert mascot.pose.carrying, t
        assert not mascot.egg.isVisible()


def testLaysTheEggInTheNest(mainWindow):
    mascot = stillMascot(mainWindow)
    logo, _welcomeLine, _nameLine = mascot.surfaces()
    place = mascot.segmentStart("place")

    # The nest sits on the logo, just behind the dinosaur's spot
    nest = mascot.nest.geometry()
    assert nest.bottom() + 1 == round(logo.top)
    assert nest.right() < mascot.segments[0].start.x()

    at(mascot, place + 100)
    assert mascot.facing == -1  # facing the nest
    assert mascot.nest.eggs == 0
    at(mascot, place + hm.LET_GO_AT + 10)
    assert mascot.nest.eggs == 1
    assert not mascot.pose.carrying


def testTheNestFillsUpThenHatches(mainWindow):
    mascot = stillMascot(mainWindow)
    place = mascot.segmentStart("place")

    at(mascot, place + hm.PLACE_MS, rounds=1)
    assert mascot.nest.eggs == 2
    at(mascot, place + hm.PLACE_MS, rounds=2)
    assert mascot.nest.eggs == 3

    # The round after a full nest: the eggs wobble, crack open, and the nest empties
    at(mascot, 100, rounds=3)
    assert (mascot.nest.eggs, mascot.nest.hatched) == (3, False)
    wobbles = set()
    for t in range(0, round(hm.GREET_MS / 2), 150):
        at(mascot, t, rounds=3)
        wobbles.add(mascot.nest.wobble)
    assert wobbles == {0, 1}
    at(mascot, hm.GREET_MS - 100, rounds=3)
    assert (mascot.nest.eggs, mascot.nest.hatched) == (3, True)
    at(mascot, hm.GREET_MS + 100, rounds=3)
    assert mascot.nest.eggs == 0
    at(mascot, place + hm.PLACE_MS, rounds=3)
    assert mascot.nest.eggs == 1  # and it starts over


def testRoundsAreCountedAsTheyGoBy(mainWindow):
    mascot = stillMascot(mainWindow)
    at(mascot, 0)
    mascot.advance(mascot.cycleDuration() * 2 + 10)
    assert mascot.rounds == 2
    assert mascot.nest.eggs == 2


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
    at(mascot, mascot.fallStart() + hm.FALL_MS + hm.BOUNCE_MS + 10, rounds=1)
    for widget in mascot, mascot.nest, mascot.egg:
        assert widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), widget.objectName()
    assert {hm._COLORS[k].name() for k in "OSR"} <= colorsIn(mascot)  # dino, spikes, beret
    assert {hm._COLORS[k].name() for k in "Vs"} <= colorsIn(mascot.egg)
    assert {hm._COLORS[k].name() for k in "nV"} <= colorsIn(mascot.nest)  # twigs, and an egg


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


def testWalksInFrontOfTheNestAndTheEgg(mainWindow):
    mascot = stillMascot(mainWindow)
    widgets = [w for w in mascot.stage.children() if isinstance(w, QWidget)]
    for prop in mascot.nest, mascot.egg:
        assert widgets.index(mascot) > widgets.index(prop), prop.objectName()
