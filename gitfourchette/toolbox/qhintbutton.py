# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon


class QHintButton(QToolButton):
    MinimumHitSize = 20
    "Smallest clickable area for a control, in points (Apple HIG, macOS)."

    def __init__(self, parent=None, toolTip="", iconKey="hint"):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRaise(True)
        self.setText(_("Help"))
        self.setIcon(stockIcon(iconKey))
        self.setToolTip(toolTip)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.connectClicked()

    def connectClicked(self):
        self.clicked.connect(lambda _checked=False: self.showHint())

    def makeReachable(self, subject: str):
        """
        Let keyboard and screen reader users get at the hint too: Tab stops on
        the button, Space or Enter shows the hint next to it, and the button's
        accessible name says which setting it explains.
        """
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(_("Help: {setting}", setting=subject))
        self.setMinimumSize(self.MinimumHitSize, self.MinimumHitSize)

    def showHint(self):
        # Clicked: show the hint at the pointer. Pressed from the keyboard: under the button.
        if self.underMouse():
            position = QCursor.pos()
        else:
            position = self.mapToGlobal(self.rect().bottomLeft())
        QToolTip.showText(position, self.toolTip(), self)

    def isEnterKey(self, event: QKeyEvent) -> bool:
        return (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier))

    def event(self, event: QEvent) -> bool:
        # Where Enter is a dialog-wide shortcut for OK, a focused hint button still gets to see it
        if event.type() == QEvent.Type.ShortcutOverride and self.hasFocus() and self.isEnterKey(event):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent):
        # QToolButton only answers Space; Enter should show the hint rather than close the dialog
        if self.hasFocus() and self.isEnterKey(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        # On release, like Space: a tooltip hides itself on any key event, the release included
        if self.hasFocus() and self.isEnterKey(event):
            if not event.isAutoRepeat():
                self.showHint()
            event.accept()
            return
        super().keyReleaseEvent(event)
