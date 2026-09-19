# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *


class QFlowLayout(QLayout):
    """
    Lays out items from left to right, and wraps them onto a new line when they
    run out of room. Items aligned with Qt.AlignmentFlag.AlignRight (see
    QLayout.setAlignment) gather at the right end of their line.

    The layout only needs to be as wide as its widest item, so a row of controls
    never forces its window to be wider than any single control.

    It doesn't take part in Qt's height-for-width mechanism: parent layouts
    would then treat the preferred height of the whole column as a hard
    minimum, so that, e.g., a text editor above the flow could no longer
    shrink. Instead, the layout reports the height that it needs at its current
    width, and asks its parents to make room whenever a new width changes that.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._width = -1  # Width of the latest geometry we were given (-1: none yet)

    # -------------------------------------------------------------------------
    # QLayout interface

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def minimumSize(self) -> QSize:
        width = max((item.minimumSize().width() for item in self._visibleItems()), default=0)
        return self._withMargins(width, self._neededHeight())

    def sizeHint(self) -> QSize:
        # Everything on a single line
        items = self._visibleItems()
        width = sum(self._itemSize(item, QWIDGETSIZE_MAX).width() for item in items)
        width += self._spacing() * max(0, len(items) - 1)
        return self._withMargins(width, self._neededHeight())

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)

        for item, geometry in self._arrange(self._innerWidth(rect.width()))[0]:
            item.setGeometry(geometry.translated(self._innerTopLeft(rect)))

        if rect.width() != self._width:
            oldHeight = self._neededHeight()
            self._width = rect.width()
            if self._neededHeight() != oldHeight:
                # The items wrap differently at this width: have the parent
                # layouts query our new height and make room for it.
                self.invalidate()

    # -------------------------------------------------------------------------
    # Arrangement

    def _visibleItems(self) -> list[QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    def _spacing(self) -> int:
        return max(0, self.spacing())

    def _itemSize(self, item: QLayoutItem, availableWidth: int) -> QSize:
        minimum = item.minimumSize()
        hint = item.sizeHint().expandedTo(minimum).boundedTo(item.maximumSize())
        return QSize(max(minimum.width(), min(hint.width(), availableWidth)), hint.height())

    def _innerWidth(self, width: int) -> int:
        margins = self.contentsMargins()
        return width - margins.left() - margins.right()

    def _innerTopLeft(self, rect: QRect) -> QPoint:
        margins = self.contentsMargins()
        return rect.topLeft() + QPoint(margins.left(), margins.top())

    def _withMargins(self, width: int, height: int) -> QSize:
        margins = self.contentsMargins()
        return QSize(width + margins.left() + margins.right(),
                     height + margins.top() + margins.bottom())

    def _neededHeight(self) -> int:
        """Height of the items at the latest width we were given (all on one line if none yet)."""
        width = self._innerWidth(self._width) if self._width >= 0 else QWIDGETSIZE_MAX
        return self._arrange(width)[1]

    def _arrange(self, width: int) -> tuple[list[tuple[QLayoutItem, QRect]], int]:
        """
        Break the items into lines that fit in the given width.
        Return each item's geometry relative to the top-left corner of the
        layout's contents, and the height of all the lines.
        """
        spacing = self._spacing()

        lines: list[list[tuple[QLayoutItem, QSize]]] = []
        lineWidth = 0
        for item in self._visibleItems():
            size = self._itemSize(item, width)
            if lines and lineWidth + spacing + size.width() <= width:
                lines[-1].append((item, size))
                lineWidth += spacing + size.width()
            else:
                lines.append([(item, size)])
                lineWidth = size.width()

        geometries = []
        y = 0
        for line in lines:
            lineHeight = max(size.height() for _item, size in line)
            leftAligned, rightAligned = [], []
            for item, size in line:
                isRight = bool(item.alignment() & Qt.AlignmentFlag.AlignRight)
                (rightAligned if isRight else leftAligned).append((item, size))

            x = 0
            for item, size in leftAligned:
                geometries.append((item, QRect(QPoint(x, y + (lineHeight - size.height()) // 2), size)))
                x += size.width() + spacing

            x = width
            for item, size in reversed(rightAligned):
                x -= size.width()
                geometries.append((item, QRect(QPoint(x, y + (lineHeight - size.height()) // 2), size)))
                x -= spacing

            y += lineHeight + spacing

        height = max(0, y - spacing)
        return geometries, height
