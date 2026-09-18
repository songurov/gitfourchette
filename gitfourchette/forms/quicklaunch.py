# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Quick Launch: type a few letters of any command, repo or workspace, press Enter.

Commands aren't listed by hand. They're read from the menu bar when the palette
opens, so anything that has a menu item - including user commands - can be
launched from here, and nothing drifts out of sync with the menus.
"""

import dataclasses
import os
from collections.abc import Callable, Iterable

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *

QUICKLAUNCH_ACTION_NAME = "QuickLaunchAction"

_DetailRole = Qt.ItemDataRole.UserRole + 1
_IsHeaderRole = Qt.ItemDataRole.UserRole + 2
_EntryRole = Qt.ItemDataRole.UserRole + 3


@dataclasses.dataclass(frozen=True)
class QuickLaunchEntry:
    title: str
    """What the row says, and what the query is matched against first."""

    run: Callable[[], object]
    """Called after the palette has closed."""

    detail: str = ""
    """Dimmed text after the title: a shortcut, a path, a repo count."""

    icon: QIcon | str = ""
    """A QIcon, or the name of a stock icon."""

    keywords: str = ""
    """Extra text the query may match (e.g. a repo's full path)."""

    def score(self, terms: list[str]) -> int:
        """
        Lower is better; -1 means no match.
        Every term must appear somewhere; rows whose title starts with the
        query (or has a word that does) come before mere substring hits.
        """
        title = self.title.casefold()
        haystack = f"{title} {self.detail.casefold()} {self.keywords.casefold()}"
        if not all(term in haystack for term in terms):
            return -1
        first = terms[0]
        if title.startswith(first):
            return 0
        if any(word.startswith(first) for word in title.replace("›", " ").split()):
            return 1
        return 2 if first in title else 3


@dataclasses.dataclass(frozen=True)
class QuickLaunchSection:
    title: str
    entries: list[QuickLaunchEntry]


def menuBarEntries(menuBar: QMenuBar, skip: Iterable[QMenu] = ()) -> list[QuickLaunchEntry]:
    """
    Every enabled, visible command in the menu bar, alphabetically.

    Submenus in `skip` are left out - they're filled on demand, so what they
    hold when the palette opens is stale (the Recent and Workspace menus get
    their own sections instead). Items in other submenus are prefixed with
    the submenu's name, e.g. "Local Config Files › .gitignore". The root
    menu's name isn't shown, but the query can still match it ("data overview").
    """
    skip = set(skip)
    entries: dict[str, QuickLaunchEntry] = {}

    def walk(menu: QMenu, trail: list[str], rootName: str):
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible() or not action.isEnabled():
                continue
            if action.objectName() == QUICKLAUNCH_ACTION_NAME:
                continue

            text = stripAccelerators(action.text()).strip()
            if not text:
                continue

            submenu = action.menu()
            if submenu is not None:
                if submenu not in skip:
                    walk(submenu, [*trail, text], rootName)
                continue

            title = " › ".join([*trail, text])
            if title in entries:
                continue
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            entries[title] = QuickLaunchEntry(title, action.trigger, detail=shortcut, icon=action.icon(),
                                              keywords=rootName)

    for rootAction in menuBar.actions():
        rootMenu = rootAction.menu()
        if rootMenu is not None and rootAction.isVisible() and rootMenu not in skip:
            # The root menu's name ("Repo", "View") only adds noise to the title
            walk(rootMenu, [], stripAccelerators(rootAction.text()))

    return sorted(entries.values(), key=lambda e: e.title.casefold())


class _EntryDelegate(QStyledItemDelegate):
    """Title, then the detail in a dimmer color; section headers in bold."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        detail = index.data(_DetailRole) or ""
        isHeader = bool(index.data(_IsHeaderRole))

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        title = opt.text
        opt.text = ""

        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        textRect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        textRect = textRect.adjusted(2, 0, -4, 0)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        colorGroup = QPalette.ColorGroup.Normal
        textRole = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text

        painter.save()
        font = QFont(opt.font)
        font.setBold(isHeader)
        painter.setFont(font)
        painter.setPen(opt.palette.color(colorGroup, QPalette.ColorRole.PlaceholderText if isHeader else textRole))

        metrics = QFontMetrics(font)
        detailWidth = metrics.horizontalAdvance(detail) if detail else 0
        titleWidth = max(0, textRect.width() - (detailWidth + metrics.horizontalAdvance("M") if detail else 0))
        elidedTitle = metrics.elidedText(title, Qt.TextElideMode.ElideRight, titleWidth)
        align = Qt.AlignmentFlag.AlignVCenter
        painter.drawText(textRect, align | Qt.AlignmentFlag.AlignLeft, elidedTitle)

        if detail and not isHeader:
            if not selected:
                painter.setPen(opt.palette.color(colorGroup, QPalette.ColorRole.PlaceholderText))
            painter.drawText(textRect, align | Qt.AlignmentFlag.AlignRight, detail)

        painter.restore()


class QuickLaunch(QDialog):
    """
    A popup with a search field over a list. Arrows move, Enter runs,
    Esc (or a click elsewhere) closes.
    """

    def __init__(self, parent: QWidget, sections: list[QuickLaunchSection]):
        super().__init__(parent)
        self.setObjectName("QuickLaunch")
        self.setWindowTitle(_("Quick Launch"))
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.sections = sections

        blank = QPixmap(16, 16)
        blank.fill(Qt.GlobalColor.transparent)
        self.blankIcon = QIcon(blank)

        self.lineEdit = QLineEdit(self)
        self.lineEdit.setPlaceholderText(_("Command, repo or workspace"))
        self.lineEdit.setClearButtonEnabled(True)
        self.lineEdit.installEventFilter(self)

        self.model = QStandardItemModel(self)
        self.listView = QListView(self)
        self.listView.setModel(self.model)
        self.listView.setItemDelegate(_EntryDelegate(self.listView))
        self.listView.setUniformItemSizes(True)
        self.listView.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.listView.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listView.setIconSize(QSize(16, 16))
        self.listView.clicked.connect(self.runIndex)

        self.hintLabel = QLabel(_("Enter: run · Esc: close"), self)
        self.hintLabel.setEnabled(False)  # dimmed
        tweakWidgetFont(self.hintLabel, 90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self.lineEdit)
        layout.addWidget(self.listView)
        layout.addWidget(self.hintLabel)

        self.lineEdit.textChanged.connect(self.refill)
        self.refill()
        self.lineEdit.setFocus()

    def popUp(self):
        """Show the palette at the top of its window, like a search field."""
        window = self.parentWidget().window()
        width = min(640, max(420, window.width() * 5 // 10))
        height = min(460, max(240, window.height() * 6 // 10))
        self.resize(width, height)
        topCenter = window.mapToGlobal(QPoint(window.width() // 2, 0))
        self.move(topCenter.x() - width // 2, topCenter.y() + 48)
        self.show()
        self.activateWindow()
        self.lineEdit.setFocus()
        # The first selection happened before the view had its real size, and
        # scrolled the section header out of sight
        self.listView.scrollToTop()

    # -------------------------------------------------------------------------

    def refill(self):
        terms = self.lineEdit.text().casefold().split()
        self.model.clear()

        for section in self.sections:
            if terms:
                scored = [(entry.score(terms), i, entry) for i, entry in enumerate(section.entries)]
                entries = [entry for score, _i, entry in sorted(scored, key=lambda t: t[:2]) if score >= 0]
            else:
                entries = section.entries
            if not entries:
                continue

            header = QStandardItem(section.title)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            header.setData(True, _IsHeaderRole)
            self.model.appendRow(header)

            for entry in entries:
                item = QStandardItem(entry.title)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setData(entry.detail, _DetailRole)
                item.setData(entry, _EntryRole)
                item.setToolTip(entry.keywords if os.sep in entry.keywords else entry.title)
                icon = stockIcon(entry.icon) if isinstance(entry.icon, str) and entry.icon else entry.icon
                if not isinstance(icon, QIcon) or icon.isNull():
                    icon = self.blankIcon  # keep titles aligned with the rows that have one
                item.setIcon(icon)
                self.model.appendRow(item)

        self.selectRow(self.nextRunnableRow(-1, +1))

    def runnableRows(self) -> list[int]:
        return [row for row in range(self.model.rowCount())
                if not self.model.item(row).data(_IsHeaderRole)]

    def visibleTitles(self) -> list[str]:
        """The rows that can be run, top to bottom. Mostly for tests."""
        return [self.model.item(row).text() for row in self.runnableRows()]

    def currentEntry(self) -> QuickLaunchEntry | None:
        index = self.listView.currentIndex()
        return index.data(_EntryRole) if index.isValid() else None

    def nextRunnableRow(self, fromRow: int, step: int) -> int:
        rows = self.runnableRows()
        if not rows:
            return -1
        if step > 0:
            return next((r for r in rows if r > fromRow), rows[-1])
        return next((r for r in reversed(rows) if r < fromRow), rows[0])

    def selectRow(self, row: int):
        if row < 0:
            self.listView.setCurrentIndex(QModelIndex())
            return
        index = self.model.index(row, 0)
        self.listView.setCurrentIndex(index)
        self.listView.scrollTo(index)

    def moveSelection(self, step: int):
        current = self.listView.currentIndex().row()
        rows = self.runnableRows()
        if not rows:
            return
        if abs(step) == 1:
            row = self.nextRunnableRow(current, step)
        else:
            # Page: jump a screenful, then settle on the nearest runnable row
            target = max(0, min(self.model.rowCount() - 1, current + step))
            row = min(rows, key=lambda r: abs(r - target))
        self.selectRow(row)

    def runIndex(self, index: QModelIndex):
        entry = index.data(_EntryRole) if index.isValid() else None
        if entry is None:
            return
        # Close first: the command may open a dialog, which shouldn't fight
        # a popup that still holds the keyboard.
        self.close()
        entry.run()

    def runCurrent(self):
        self.runIndex(self.listView.currentIndex())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.lineEdit and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key = event.key()
            page = max(1, self.listView.viewport().height() // max(1, self.listView.sizeHintForRow(0)) - 1)
            steps = {
                Qt.Key.Key_Down: 1,
                Qt.Key.Key_Up: -1,
                Qt.Key.Key_PageDown: page,
                Qt.Key.Key_PageUp: -page,
            }
            if key in steps:
                self.moveSelection(steps[key])
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.runCurrent()
                return True
        return super().eventFilter(watched, event)
