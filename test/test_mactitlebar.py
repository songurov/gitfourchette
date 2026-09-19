# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
On macOS, the title bar and the toolbar read as one surface.

Offscreen, there's no title bar to extend under, so a window with a fake safe
area stands in for it (the strip at the top of its contents margins).
"""

import os

import pytest

from gitfourchette import settings
from gitfourchette.themes import ThemeName, pinnedColorScheme
from gitfourchette.toolbox import mactitlebar
from gitfourchette.toolbox.mactitlebar import MacTitleBar, titleBarDoubleClickAction
from .util import *

requiresExpandedClientArea = pytest.mark.skipif(
    not MacTitleBar.isSupported(), reason="Qt 6.9+ required for ExpandedClientAreaHint")

TITLE_BAR_HEIGHT = 28


def sendMouse(window: QWidget, eventType: QEvent.Type, globalPos: QPoint,
              button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton):
    """
    Send a mouse event through the window's QWindow, the way the platform does,
    so that it reaches the widget under the cursor and bubbles up from there.
    """
    localPos = QPointF(window.mapFromGlobal(globalPos))
    event = QMouseEvent(eventType, localPos, localPos, QPointF(globalPos),
                        button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(window.windowHandle(), event)


def drag(window: QWidget, localStart: QPoint, delta: QPoint):
    start = window.mapToGlobal(localStart)
    sendMouse(window, QEvent.Type.MouseButtonPress, start)
    for step in (delta / 2, delta):
        sendMouse(window, QEvent.Type.MouseMove, start + step, button=Qt.MouseButton.NoButton)
    sendMouse(window, QEvent.Type.MouseButtonRelease, start + delta, buttons=Qt.MouseButton.NoButton)
    QTest.qWait(0)


def doubleClick(window: QWidget, localPos: QPoint):
    pos = window.mapToGlobal(localPos)
    sendMouse(window, QEvent.Type.MouseButtonPress, pos)
    sendMouse(window, QEvent.Type.MouseButtonRelease, pos, buttons=Qt.MouseButton.NoButton)
    sendMouse(window, QEvent.Type.MouseButtonDblClick, pos)
    sendMouse(window, QEvent.Type.MouseButtonRelease, pos, buttons=Qt.MouseButton.NoButton)
    QTest.qWait(0)


@pytest.fixture
def titleBarWindow(qtbot):
    window = QMainWindow()
    toolBar = QToolBar(window)
    toolBar.setMovable(False)
    button = QToolButton(toolBar)
    button.setText("Button")
    button.setFixedWidth(80)
    toolBar.addWidget(button)
    spacer = QWidget(toolBar)
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    toolBar.addWidget(spacer)
    window.addToolBar(toolBar)
    window.setCentralWidget(QWidget(window))

    titleBar = MacTitleBar(window)

    # Offscreen has no title bar, hence no safe area: fake one
    window.setContentsMargins(0, TITLE_BAR_HEIGHT, 0, 0)
    window.setGeometry(100, 150, 500, 300)
    window.show()
    qtbot.waitExposed(window)

    window.button = button
    window.spacer = spacer
    window.titleBar = titleBar
    yield window
    window.close()


@pytest.fixture(params=[True, False], ids=["macos", "elsewhere"])
def mainWindowIsOnMacOS(request, monkeypatch):
    """Pretend to be (or not to be) on macOS when the main window gets built."""
    from gitfourchette import mainwindow
    monkeypatch.setattr(mainwindow, "MACOS", request.param)
    return request.param


@requiresExpandedClientArea
def testMainWindowPaintsItsOwnTitleBarOnMacOnly(mainWindowIsOnMacOS, tempDir, mainWindow):
    macos = mainWindowIsOnMacOS
    flags = mainWindow.windowFlags()
    assert bool(flags & Qt.WindowType.ExpandedClientAreaHint) == macos
    assert bool(flags & Qt.WindowType.NoTitleBarBackgroundHint) == macos
    # Nothing changes elsewhere: no title bar logic hooked into the window either
    assert (mainWindow.findChild(MacTitleBar) is not None) == macos


@requiresExpandedClientArea
def testTitleBarWindowIsExpandedWithoutBackground(titleBarWindow):
    plainWindow = QMainWindow()
    plainWindow.setWindowFlags(plainWindow.windowFlags())  # let Qt fill in the default title bar hints
    defaultFlags = plainWindow.windowFlags()
    plainWindow.deleteLater()

    # Only the two hints are added: the traffic lights, including the full
    # screen button, stay as they were
    hints = Qt.WindowType.ExpandedClientAreaHint | Qt.WindowType.NoTitleBarBackgroundHint
    assert titleBarWindow.windowFlags() == defaultFlags | hints


@requiresExpandedClientArea
@pytest.mark.parametrize("where", ["title strip", "toolbar empty space"])
def testDraggingTheTitleBarMovesTheWindow(titleBarWindow, where):
    window = titleBarWindow
    if where == "title strip":
        point = QPoint(250, TITLE_BAR_HEIGHT // 2)
    else:
        point = window.spacer.geometry().center() + window.spacer.parentWidget().geometry().topLeft()
        assert window.childAt(point) is window.spacer

    before = window.pos()
    drag(window, point, QPoint(30, 20))
    assert window.pos() == before + QPoint(30, 20)

    drag(window, point, QPoint(-30, -20))
    assert window.pos() == before


@requiresExpandedClientArea
def testDraggingElsewhereDoesNotMoveTheWindow(titleBarWindow):
    window = titleBarWindow
    before = window.pos()

    clicks = []
    window.button.clicked.connect(lambda: clicks.append(True))
    buttonCenter = window.button.geometry().center() + window.button.parentWidget().geometry().topLeft()
    drag(window, buttonCenter, QPoint(0, 0))
    assert clicks, "the toolbar's buttons must still take their clicks"
    drag(window, buttonCenter, QPoint(30, 20))
    assert window.pos() == before

    drag(window, window.centralWidget().geometry().center(), QPoint(30, 20))
    assert window.pos() == before


@requiresExpandedClientArea
def testDraggingStopsBelowTheMenuBar(titleBarWindow):
    window = titleBarWindow
    availableTop = window.screen().availableGeometry().top()
    drag(window, QPoint(250, 5), QPoint(0, -1000))
    assert window.pos().y() == availableTop


@requiresExpandedClientArea
def testNoDraggingInFullScreen(titleBarWindow):
    window = titleBarWindow
    window.showFullScreen()
    waitUntilTrue(window.isFullScreen)
    assert not window.titleBar.isOnTitleBar(QPoint(250, 5))
    assert not window.titleBar.isOnTitleBar(window.spacer.geometry().center()
                                             + window.spacer.parentWidget().geometry().topLeft())
    window.showNormal()


@requiresExpandedClientArea
def testDoubleClickingTheTitleBarDoesWhatSystemSettingsSay(titleBarWindow, monkeypatch):
    window = titleBarWindow
    strip = QPoint(250, TITLE_BAR_HEIGHT // 2)

    monkeypatch.setattr(mactitlebar, "titleBarDoubleClickAction", lambda: "Maximize")
    doubleClick(window, strip)
    waitUntilTrue(window.isMaximized)
    doubleClick(window, strip)
    waitUntilTrue(lambda: not window.isMaximized())

    # "Fill" (macOS 15+) has no Qt equivalent: zoom is the closest thing
    monkeypatch.setattr(mactitlebar, "titleBarDoubleClickAction", lambda: "Fill")
    doubleClick(window, strip)
    waitUntilTrue(window.isMaximized)
    window.showNormal()
    waitUntilTrue(lambda: not window.isMaximized())

    calls = []
    monkeypatch.setattr(window, "showMinimized", lambda: calls.append("minimize"))
    monkeypatch.setattr(window, "showMaximized", lambda: calls.append("maximize"))
    monkeypatch.setattr(mactitlebar, "titleBarDoubleClickAction", lambda: "Minimize")
    doubleClick(window, strip)
    assert calls == ["minimize"]

    monkeypatch.setattr(mactitlebar, "titleBarDoubleClickAction", lambda: "None")
    doubleClick(window, strip)
    assert calls == ["minimize"]

    # Double-clicking the window's contents is none of the title bar's business
    monkeypatch.setattr(mactitlebar, "titleBarDoubleClickAction", lambda: "Maximize")
    doubleClick(window, window.centralWidget().geometry().center())
    assert calls == ["minimize"]


def testTitleBarDoubleClickActionReadsSystemSettings(tempDir):
    def action(**keys):
        prefs = QSettings(os.path.join(tempDir.name, "globalprefs.ini"), QSettings.Format.IniFormat)
        prefs.clear()
        for key, value in keys.items():
            prefs.setValue(key, value)
        return titleBarDoubleClickAction(prefs)

    assert action() == "Maximize"
    assert action(AppleMiniaturizeOnDoubleClick=False) == "Maximize"
    assert action(AppleMiniaturizeOnDoubleClick=True) == "Minimize"
    assert action(AppleActionOnDoubleClick="None", AppleMiniaturizeOnDoubleClick=True) == "None"
    assert action(AppleActionOnDoubleClick="Fill") == "Fill"


def testPinnedColorScheme():
    Scheme = Qt.ColorScheme
    assert pinnedColorScheme(f"{ThemeName.BuiltIn},dark") == Scheme.Dark
    assert pinnedColorScheme(f"{ThemeName.BuiltIn},light,#e93d58") == Scheme.Light
    assert pinnedColorScheme(f"{ThemeName.BuiltIn},#e93d58,dark") == Scheme.Dark
    # No mode: follow the system
    assert pinnedColorScheme(f"{ThemeName.BuiltIn}") == Scheme.Unknown
    assert pinnedColorScheme("") == Scheme.Unknown
    # Native Qt styles have no say in light vs dark
    assert pinnedColorScheme("Fusion") == Scheme.Unknown
    assert pinnedColorScheme("fusion,dark") == Scheme.Unknown


@pytest.mark.parametrize("macos", [True, False])
def testThemeSwitchPinsTheAppearanceOnMacOnly(tempDir, mainWindow, monkeypatch, macos):
    """
    The title bar's text (and native menus and dialogs) follow the app's
    appearance, so a light theme must not be left with the system's dark one.
    """
    if not hasattr(QStyleHints, "setColorScheme"):
        pytest.skip("QStyleHints.setColorScheme requires Qt 6.8+")

    from gitfourchette import application
    monkeypatch.setattr(application, "MACOS", macos)
    requests = []
    monkeypatch.setattr(QStyleHints, "setColorScheme", lambda _self, scheme: requests.append(scheme))

    mainWindow.onSetDarkTheme(True)
    assert requests[-1:] == ([Qt.ColorScheme.Dark] if macos else [])

    mainWindow.onSetDarkTheme(False)
    assert requests[-1:] == ([Qt.ColorScheme.Light] if macos else [])

    # Back to following the system: the pin must go
    GFApplication.applyPrefs(qtStyle=str(ThemeName.BuiltIn))
    assert settings.prefs.qtStyle == ThemeName.BuiltIn
    assert requests[-1:] == ([Qt.ColorScheme.Unknown] if macos else [])
