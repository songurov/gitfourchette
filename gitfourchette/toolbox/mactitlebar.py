# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *


def titleBarDoubleClickAction(globalPrefs: QSettings | None = None) -> str:
    """
    What double-clicking a title bar should do, as set in System Settings >
    Desktop & Dock: "Maximize" (zoom, the default), "Fill", "Minimize" or "None".
    """
    if globalPrefs is None:
        # A native QSettings without an application name reads the global
        # domain (NSGlobalDomain), where macOS keeps this setting.
        globalPrefs = QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, "apple.com")

    action = globalPrefs.value("AppleActionOnDoubleClick", "", type=str)
    if action:
        return action

    # Older versions of macOS only had a checkbox for minimizing
    if globalPrefs.value("AppleMiniaturizeOnDoubleClick", False, type=bool):
        return "Minimize"

    return "Maximize"


class MacTitleBar(QObject):
    """
    Make a main window's title bar and its top toolbar read as one surface on macOS.

    AppKit paints the title bar in its own grey whatever the app's palette says,
    so above a themed toolbar it shows up as a band of another color. Instead,
    the window's client area extends under a transparent title bar: the traffic
    lights and the title stay native, and behind them shows the window's own
    background, which is the toolbar's too. Qt keeps the window's contents clear
    of the title bar through its safe area margins, which a top-level widget
    counts in its contents margins.

    AppKit still moves the window when the title text itself is dragged, but the
    rest of the strip is now the window's. So this does what the title bar did
    there: drag to move the window, double-click to zoom or minimize as set in
    System Settings. The toolbar's empty space does the same, since it now looks
    like part of the title bar, as it would in a native unified toolbar.

    The title's text is drawn in the app's appearance (light or dark), which
    GFApplication pins to the theme's mode.
    """

    dragOffset: QPoint | None = None
    """Where the cursor grabbed the window, while it's being dragged by its title bar."""

    MouseEventTypes = (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseMove,
        QEvent.Type.MouseButtonRelease,
    )

    @staticmethod
    def isSupported() -> bool:
        return hasattr(Qt.WindowType, "ExpandedClientAreaHint")  # Qt 6.9+

    def __init__(self, window: QMainWindow):
        # No Python reference back to the window: that would make a cycle, and
        # the garbage collector could then clear this object's attributes while
        # the window, on its way out, still sends events through this filter.
        super().__init__(window)
        self.setObjectName("MacTitleBar")

        # Before the window is shown: changing a visible window's flags hides it
        window.setWindowFlags(window.windowFlags()
                              | Qt.WindowType.ExpandedClientAreaHint
                              | Qt.WindowType.NoTitleBarBackgroundHint)
        window.installEventFilter(self)

    def mainWindow(self) -> QMainWindow:
        window = self.parent()
        assert isinstance(window, QMainWindow)
        return window

    def isOnTitleBar(self, pos: QPoint) -> bool:
        """
        Whether a point (in window coordinates) is on the strip behind the
        traffic lights, or on a top toolbar's empty space.

        Clicks on a toolbar's buttons never get here: the buttons take them.
        """
        window = self.mainWindow()

        # A full-screen window has no title bar to stand in for, and doesn't move
        if window.isFullScreen():
            return False

        if pos.y() < window.contentsMargins().top():
            return True

        widget = window.childAt(pos)
        while widget is not None and widget is not window:
            if isinstance(widget, QToolBar):
                return window.toolBarArea(widget) == Qt.ToolBarArea.TopToolBarArea
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        eventType = event.type()
        if (eventType not in MacTitleBar.MouseEventTypes
                # As of PyQt6 6.8, QContextMenuEvent sometimes pretends to be a MouseButtonDblClick
                or not isinstance(event, QMouseEvent)
                or watched is not self.parent()):
            return False

        # Carry on with a drag that started on the title bar
        if self.dragOffset is not None and eventType != QEvent.Type.MouseButtonPress:
            if eventType == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                self.moveWindow(event.globalPosition().toPoint())
                event.accept()
                return True
            # The button is up: the drag is over, even if its release got lost
            self.dragOffset = None
            if eventType == QEvent.Type.MouseButtonRelease:
                event.accept()
                return True

        if (eventType not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
                or event.button() != Qt.MouseButton.LeftButton
                or not self.isOnTitleBar(event.position().toPoint())):
            return False

        event.accept()
        if eventType == QEvent.Type.MouseButtonDblClick:
            self.onDoubleClick()
        else:
            # Move the window by hand, like QToolBar does for a unified toolbar.
            # Not with QWindow.startSystemMove(): AppKit may never send the
            # mouse-up that ends a system drag, and Qt would go on thinking that
            # the button is held, so hovering would do nothing until the next click.
            self.dragOffset = event.globalPosition().toPoint() - self.mainWindow().pos()
        return True

    def moveWindow(self, cursorPos: QPoint):
        assert self.dragOffset is not None
        pos = cursorPos - self.dragOffset
        # Like a real title bar, don't slide up behind the menu bar
        screen = QGuiApplication.screenAt(cursorPos) or self.mainWindow().screen()
        pos.setY(max(pos.y(), screen.availableGeometry().top()))
        self.mainWindow().move(pos)

    def onDoubleClick(self):
        window = self.mainWindow()
        action = titleBarDoubleClickAction()
        if action == "None":
            pass
        elif action == "Minimize":
            window.showMinimized()
        elif window.isMaximized():  # "Maximize" (i.e. zoom), or "Fill", which Qt can't ask for
            window.showNormal()
        else:
            window.showMaximized()
