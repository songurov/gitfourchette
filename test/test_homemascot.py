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


def testWalksTheWholeLoop(mainWindow):
    mascot = stillMascot(mainWindow)
    logo, welcomeLine, nameLine = mascot.surfaces()
    kinds = [s.kind for s in mascot.segments]
    assert kinds == ["idle", "jump", "walk", "jump", "walk", "idle", "walk", "jump", "walk", "jump"]

    def endOf(index: int):
        """Move to the very end of segment `index`."""
        mascot.elapsed = 0.0
        mascot.advance(sum(s.duration for s in mascot.segments[:index + 1]) - 1)

    # Starts on the logo
    mascot.elapsed = 0.0
    mascot.advance(1)
    assert mascot.feet.y() == logo.top
    # Lands on "Welcome to", walks right along it
    endOf(1)
    assert abs(mascot.feet.y() - welcomeLine.top) < 1
    endOf(2)
    assert mascot.facing == 1
    assert mascot.feet.x() > welcomeLine.left + (welcomeLine.right - welcomeLine.left) / 2
    # Lands on the end of the name
    endOf(3)
    assert abs(mascot.feet.y() - nameLine.top) < 1
    assert mascot.feet.x() > welcomeLine.right - 20
    # Turns around there, and walks back
    endOf(5)
    assert mascot.facing == -1
    endOf(6)
    assert mascot.facing == -1
    # Back on the logo at the end of the loop
    endOf(9)
    assert abs(mascot.feet.y() - logo.top) < 1
    assert logo.left <= mascot.feet.x() <= logo.right


def testJumpsArcAboveBothLedges(mainWindow):
    mascot = stillMascot(mainWindow)
    jump = mascot.segments[1]
    mascot.elapsed = 0.0
    mascot.advance(mascot.segments[0].duration + jump.duration / 2)
    assert mascot.sprite is homemascot._JUMP
    assert mascot.feet.y() < min(jump.start.y(), jump.end.y())


def testLegsMoveWhileWalking(mainWindow):
    mascot = stillMascot(mainWindow)
    walkStart = sum(s.duration for s in mascot.segments[:2])
    sprites = set()
    for step in range(4):
        mascot.elapsed = 0.0
        mascot.advance(walkStart + 1 + step * homemascot.STEP_MS)
        sprites.add(mascot.sprite)
    assert sprites == {homemascot._STAND, homemascot._STRIDE}


def testOnlyAnimatesWhileTheSplashIsShown(tempDir, mainWindow):
    mascot = mainWindow.welcomeWidget.mascot
    waitUntilTrue(mascot.isAnimating)

    mainWindow.openRepo(unpackRepo(tempDir))
    assert not mascot.isAnimating(), "no ticking behind a repo"

    mainWindow.closeAllTabs()
    waitUntilTrue(mascot.isAnimating)


def testIsDrawnAndLetsClicksThrough(mainWindow):
    mascot = stillMascot(mainWindow)
    assert mascot.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    image = mascot.grab().toImage()
    colors = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}
    assert homemascot._COLORS["B"].name() in colors
    assert homemascot._COLORS["H"].name() in colors


def testFacingLeftMirrorsTheEyes(mainWindow):
    mascot = stillMascot(mainWindow)

    def eyeColumns():
        image = mascot.grab().toImage()
        y = 4 * homemascot.PIXEL + 1
        eye = homemascot._COLORS["E"].name()
        return [x for x in range(image.width()) if image.pixelColor(x, y).name() == eye]

    mascot.facing = 1
    right = eyeColumns()
    mascot.facing = -1
    left = eyeColumns()
    assert right and left and right != left
