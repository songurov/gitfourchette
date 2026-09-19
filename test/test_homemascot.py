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
                     "walk", "jump", "walk", "jump", "place", "turn", "rest"]

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


def testTakesItsTimeHoweverShortTheText(mainWindow):
    """How far it walks follows the font; how long a round takes doesn't.
    With little to walk along, it rests at home instead of hurrying."""
    mascot = stillMascot(mainWindow)
    label = mainWindow.welcomeWidget.ui.welcomeLabel
    label.setText(label.text().replace(qAppName(), "Git"))
    QTest.qWait(0)  # let the layout fit the label to its new text
    at(mascot, 0)

    home = mascot.segments[0].start
    walks = [s for s in mascot.segments if s.kind == "walk"]
    busy = sum(s.duration for s in mascot.segments if s.kind != "rest")
    assert busy < 25_000, "the text should be too short to fill a round by walking"

    assert mascot.cycleDuration() == pytest.approx(25_000)
    for walk in walks:  # still strolling
        assert walk.duration == pytest.approx(1000 * abs(walk.end.x() - walk.start.x()) / hm.WALK_SPEED)
    rest = mascot.segments[-1]
    assert rest.kind == "rest"
    assert rest.duration == pytest.approx(25_000 - busy)
    at(mascot, mascot.segmentStart("rest") + rest.duration / 2)
    assert mascot.feet == home
    assert (mascot.pose.legs, mascot.pose.arm, mascot.facing) == ("stand", "rest", 1)


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


def testMeasuringHomeLeavesAClosingTabAlone(tempDir, mainWindow):
    """
    Closing the last tab brings Home back before Qt has deleted that tab, and
    the mascot measures the page again. That mustn't deliver the tab's pending
    resize events: its diff view has already let go of its gutter, and would
    raise an error in a dialog.
    """
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    diffView = rw.diffView
    assert diffView.testAttribute(Qt.WidgetAttribute.WA_PendingResizeEvent), "not shown yet, so not sized yet"

    mainWindow.closeTab(0)  # torn down, but deleted later
    assert mainWindow.welcomeWidget.mascot.surfaces() is not None
    assert diffView.testAttribute(Qt.WidgetAttribute.WA_PendingResizeEvent), "the tab being torn down was resized"


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


def eyeCenter(mascot: HomeMascot) -> QPoint:
    ex, ey = hm._EYE[3]
    x = mascot.x() + (ex if mascot.facing > 0 else hm.CANVAS_W - ex) * hm.PIXEL
    return QPoint(x, mascot.y() + ey * hm.PIXEL)


def pupil(mascot: HomeMascot) -> tuple[int, int]:
    return next(xy for xy, key in mascot.pose.pixels().items() if key == "K")


def testLooksAtTheCursor(mainWindow):
    mascot = stillMascot(mainWindow)
    walk = sum(s.duration for s in mascot.segments[:2]) + 100  # walking right, eyes open
    at(mascot, walk)
    eye = eyeCenter(mascot)
    ex, ey = hm._EYE[0]

    cases = {
        (40, -30): (ex + 1, ey),      # ahead and above: front, up
        (40, 30): (ex + 1, ey + 1),   # ahead and below: front, down
        (-40, -30): (ex, ey),         # behind and above: back, up
        (-40, 30): (ex, ey + 1),      # behind and below: back, down
    }
    for (dx, dy), expected in cases.items():
        mascot.cursorPos = lambda d=(dx, dy): eye + QPoint(*d)
        mascot.advance(0)
        assert pupil(mascot) == expected, (dx, dy)

    # Walking the other way, "ahead" is on the other side
    at(mascot, mascot.segmentStart("walk", 2) + 100)
    assert mascot.facing == -1
    eye = eyeCenter(mascot)
    mascot.cursorPos = lambda: eye + QPoint(-40, 30)
    mascot.advance(0)
    assert pupil(mascot) == (ex + 1, ey + 1)

    # Nobody around: it looks ahead
    mascot.cursorPos = lambda: None
    mascot.advance(0)
    assert mascot.pose.look == hm.LOOK_AHEAD


def testLookingAtTheCursorCanBeTurnedOff(mainWindow):
    from gitfourchette.application import GFApplication
    mascot = stillMascot(mainWindow)
    at(mascot, sum(s.duration for s in mascot.segments[:2]) + 100)
    mascot.cursorPos = lambda: eyeCenter(mascot) + QPoint(-40, -30)  # behind, above
    GFApplication.applyPrefs(homeMascotFollowsCursor=False)
    try:
        mascot.advance(0)
        assert mascot.pose.look == hm.LOOK_AHEAD
    finally:
        GFApplication.applyPrefs(homeMascotFollowsCursor=True)
    mascot.advance(0)
    assert mascot.pose.look != hm.LOOK_AHEAD


def testTheSettingsSwitchTurnsTheMascotOff(mainWindow):
    from gitfourchette.forms.prefsdialog import PrefsDialog
    mascot = mainWindow.welcomeWidget.mascot
    waitUntilTrue(mascot.isAnimating)

    triggerMenuAction(mainWindow.menuBar(), "file/settings")
    dlg: PrefsDialog = findQDialog(mainWindow, "settings")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_homeMascot")
    assert checkBox.isChecked()
    assert dlg.findChild(QCheckBox, "prefctl_homeMascotFollowsCursor").isChecked()
    checkBox.setChecked(False)
    dlg.accept()

    # Gone, with its nest and egg, and no more ticking
    assert not mascot.isAnimating()
    for widget in mascot, mascot.nest, mascot.egg:
        assert not widget.isVisible(), widget.objectName()

    # Coming back to Home doesn't wake it up either
    mainWindow.welcomeWidget.ui.splashPage.hide()
    mainWindow.welcomeWidget.ui.splashPage.show()
    QTest.qWait(0)
    assert not mascot.isAnimating()

    # Switched back on: right back, nest included
    triggerMenuAction(mainWindow.menuBar(), "file/settings")
    dlg = findQDialog(mainWindow, "settings")
    dlg.findChild(QCheckBox, "prefctl_homeMascot").setChecked(True)
    dlg.accept()
    assert mascot.isAnimating()
    assert mascot.isVisible() and mascot.nest.isVisible()
