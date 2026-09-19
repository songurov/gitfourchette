# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Widgets of the commit area under the working directory's changes: the box
that holds the message, and the buttons around it. DiffArea puts them together.
"""

import math

from gitfourchette.qt import *
from gitfourchette.themes import activeTheme


def setStyleProperty(widget: QWidget, name: str, value):
    """Set a dynamic property that the stylesheet keys off, and restyle the widget if the value changed."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class CommitMessageBox(QFrame):
    """
    One bordered field made of two: the subject line and the description.
    The fields inside have no border of their own, so the box shows where the
    keyboard focus is instead (dynamic property "focused", for the stylesheet).
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("focused", False)

    def watchFocus(self, *fields: QWidget):
        for field in fields:
            field.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            setStyleProperty(self, "focused", event.type() == QEvent.Type.FocusIn)
        return False


class CommitDescriptionEdit(QPlainTextEdit):
    """
    The commit message's body. It starts out a couple of lines tall, and grows
    with its text up to MaxLines; past that, it scrolls.
    """

    MinLines = 1
    RestLines = 2
    MaxLines = 8

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTabChangesFocus(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(lambda _size: self.updateGeometry())

    def lineCount(self) -> int:
        """Lines the text takes up at the current width, long ones wrapped (QPlainTextDocumentLayout counts in lines)."""
        return max(1, math.ceil(self.document().documentLayout().documentSize().height()))

    def heightForLines(self, lines: int) -> int:
        # Each line of text is as tall as the font's line spacing, rounded up (QTextLine.height);
        # QPlainTextEdit wants one more pixel than its lines and margins before it drops its scroll bar.
        lineHeight = math.ceil(QFontMetricsF(self.font()).lineSpacing())
        textHeight = lineHeight * lines + math.ceil(2 * self.document().documentMargin()) + 1
        margins = self.contentsMargins()
        viewportMargins = self.viewportMargins()
        return textHeight + margins.top() + margins.bottom() + viewportMargins.top() + viewportMargins.bottom()

    def minimumSizeHint(self) -> QSize:
        lines = min(max(self.lineCount(), self.MinLines), self.MaxLines)
        return QSize(super().minimumSizeHint().width(), self.heightForLines(lines))

    def sizeHint(self) -> QSize:
        lines = min(max(self.lineCount(), self.RestLines), self.MaxLines)
        return QSize(super().sizeHint().width(), self.heightForLines(lines))


class MenuToolButton(QToolButton):
    """
    A tool button whose menu also opens from the keyboard, with the Down key.
    With MenuButtonPopup, Space only clicks the button; the menu was out of
    reach without a mouse.
    """

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Down and self.menu() is not None and self.isEnabled():
            self.showMenu()
            return
        super().keyPressEvent(event)


class BadgeToolButton(MenuToolButton):
    """A tool button with a dot in its corner while `badge` is on, e.g. while one of the options in its menu is on."""

    BadgeRadius = 3

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.badge = False

    def setBadge(self, badge: bool):
        if badge != self.badge:
            self.badge = badge
            self.update()

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        if not self.badge:
            return
        r = self.BadgeRadius
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
        painter.drawEllipse(QPointF(self.width() - r - 2, r + 2), r, r)
        painter.end()


class PrimaryMenuButton(MenuToolButton):
    """
    The commit area's main button, filled with the accent while it's ready to
    go. When it isn't, the button looks dead, but it stays enabled so that its
    menu keeps working: only its default action is off. The built-in theme's
    menu arrow is a gray picture that would vanish on the accent, so the theme
    hides it and the button draws the arrow itself.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.ready = False
        setStyleProperty(self, "ready", False)

    def setReady(self, ready: bool):
        self.ready = ready
        setStyleProperty(self, "ready", ready)

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        theme = activeTheme()
        if theme is None or self.popupMode() != QToolButton.ToolButtonPopupMode.MenuButtonPopup:
            return

        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        zone = self.style().subControlRect(
            QStyle.ComplexControl.CC_ToolButton, option, QStyle.SubControl.SC_ToolButtonMenu, self)
        center = QRectF(zone).center()

        # A dead button keeps its arrow in full text color: the menu still works
        color = QColor(theme.onAccent if self.ready else theme.text)
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([
            center + QPointF(-3.5, -1.5),
            center + QPointF(0, 2),
            center + QPointF(3.5, -1.5),
        ]))
        painter.end()
