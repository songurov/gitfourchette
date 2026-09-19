# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
The strip over a file list: its title ("Unstaged (3)"), then its buttons.
"""

import re

from gitfourchette import settings
from gitfourchette.qt import *
from gitfourchette.themes import ThemeColors, ThemeVariant
from gitfourchette.toolbox import QElidedLabel, stockIcon

class FileListTitle(QElidedLabel):
    """
    A file list's title. Neutral writes the name in bold, full contrast, and
    the count that follows it in parentheses in the dim secondary color, the
    way Fork writes a bold "Unstaged" with nothing competing next to it.
    """

    countColor: QColor | None = None
    "Neutral: the color of the trailing count. None draws the whole text alike."

    _trailingCount = re.compile(r"^(.*?\S)(\s*[(（][^()（）]*[)）])$")

    def countSplit(self) -> tuple[str, str]:
        """The text as (name, count), e.g. ("Unstaged", " (3)"); the count is "" if there's none."""
        match = self._trailingCount.match(self.text())
        return (match.group(1), match.group(2)) if match else (self.text(), "")

    def paintEvent(self, event: QPaintEvent):
        name, count = self.countSplit()
        if self.countColor is None or not count:
            super().paintEvent(event)
            return

        metrics = self.fontMetrics()
        countFont = QFont(self.font())
        countFont.setBold(False)
        countMetrics = QFontMetrics(countFont)

        m = int(metrics.horizontalAdvance('x') / 2 - self.margin())
        rect = self.contentsRect().adjusted(self.margin() + m, self.margin(), -(self.margin() + m), -self.margin())
        if metrics.horizontalAdvance(name) + countMetrics.horizontalAdvance(count) > rect.width():
            # No room for both: elide the whole thing in one color
            super().paintEvent(event)
            return

        painter = QPainter(self)
        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(rect, alignment, name)
        rect.setLeft(rect.left() + metrics.horizontalAdvance(name))
        painter.setFont(countFont)
        painter.setPen(self.countColor)
        painter.drawText(rect, alignment, count)
        painter.end()


class FileListHeader(QWidget):
    """
    A file list's title, then its buttons, on one line over the list.

    The buttons come in their Modern order: small icons in a row. Neutral turns
    the list's main action (Stage, Unstage) into a text pill at the right end,
    like Fork's, and keeps the other buttons as small icons beside it, in the
    reverse order, so that the "all" versions sit right next to the pill.

    Going back to Modern puts back exactly what Neutral changed.
    """

    def __init__(self, parent: QWidget, title: FileListTitle, buttons: list[QToolButton],
                 pill: QToolButton | None = None):
        super().__init__(parent)
        self.setObjectName("fileListHeader")
        self.title = title
        self.buttons = buttons
        self.pill = pill
        self.neutralIcons: dict[QToolButton, str] = {}
        self.modernLooks: dict[QWidget, dict] = {}
        "How Neutral found each widget, to put it back when the look goes back to Modern"

        if pill is not None:
            pill.setProperty("class", "pill")

        layout = QHBoxLayout(self)
        layout.setSpacing(0)
        layout.addWidget(title, 1)
        self.layOut(neutral=False)

    def setNeutralIcon(self, button: QToolButton, iconId: str):
        """Give an icon, in Neutral, to a button that Modern shows as text (☰, AI)."""
        self.neutralIcons[button] = iconId

    def layOut(self, neutral: bool, inset: int = 0):
        layout = self.layout()
        assert isinstance(layout, QHBoxLayout)
        while layout.count() > 1:  # all but the title
            layout.takeAt(1)
        if not neutral:
            layout.setContentsMargins(3, 0, 0, 0)
            for button in self.buttons:
                layout.addWidget(button)
            return
        # The title lines up with the rows' selection below. The line under
        # the strip is drawn in its last pixel row (see theme.qss).
        layout.setContentsMargins(inset, 0, inset, 1)
        icons = [b for b in self.buttons if b is not self.pill]
        for button in reversed(icons):
            layout.addWidget(button)
        if self.pill is not None:
            layout.addSpacing(6)
            layout.addWidget(self.pill)

    def applyTheme(self, theme: ThemeColors | None):
        neutral = theme is not None and theme.variant == ThemeVariant.Neutral
        widgets = [self, self.title, *self.buttons]

        if not neutral:
            if self.modernLooks:
                self.layOut(neutral=False)
                self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
                self.title.countColor = None
                for widget in widgets:
                    self.restoreLooks(widget, self.modernLooks[widget])
                self.modernLooks = {}
            return

        if not self.modernLooks:
            self.modernLooks = {widget: self.saveLooks(widget) for widget in widgets}

        self.layOut(neutral=True, inset=theme.fileListInset)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Compact mode runs a notch smaller everywhere, the strip included
        height = theme.fileHeaderHeight - (4 if settings.prefs.compactUi else 0)
        self.setFixedHeight(height + 1)

        titleFont = QFont()
        titleFont.setBold(True)
        self.title.setFont(titleFont)
        self.title.setMinimumHeight(0)
        self.title.countColor = QColor(theme.textDim)

        pillHeight = height - 6
        for button in self.buttons:
            isPill = button is self.pill
            button.setAutoRaise(not isPill)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly if isPill
                                      else Qt.ToolButtonStyle.ToolButtonIconOnly)
            if isPill:
                button.setFont(QFont())
            button.setMinimumSize(0, pillHeight if isPill else 0)
            button.setMaximumSize(QWIDGETSIZE_MAX, pillHeight)
            if button in self.neutralIcons:
                button.setIcon(stockIcon(self.neutralIcons[button]))
            self.repolish(button)

    @staticmethod
    def saveLooks(widget: QWidget) -> dict:
        looks = {
            "minimumSize": widget.minimumSize(),
            "maximumSize": widget.maximumSize(),
            # A font the widget inherits goes back to being inherited
            "font": QFont(widget.font()) if widget.testAttribute(Qt.WidgetAttribute.WA_SetFont) else QFont(),
        }
        if isinstance(widget, QToolButton):
            looks["autoRaise"] = widget.autoRaise()
            looks["toolButtonStyle"] = widget.toolButtonStyle()
            looks["icon"] = widget.icon()
        return looks

    @classmethod
    def restoreLooks(cls, widget: QWidget, looks: dict):
        widget.setMinimumSize(looks["minimumSize"])
        widget.setMaximumSize(looks["maximumSize"])
        widget.setFont(looks["font"])
        if isinstance(widget, QToolButton):
            widget.setAutoRaise(looks["autoRaise"])
            widget.setToolButtonStyle(looks["toolButtonStyle"])
            widget.setIcon(looks["icon"])
            cls.repolish(widget)

    @staticmethod
    def repolish(widget: QWidget):
        """Style sheet rules that test autoRaise don't notice it changing on their own."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)
