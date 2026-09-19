# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
The file column (Unstaged over Staged) in the Neutral look, which follows
Fork's, and in Modern, which must stay as it was.
"""

from gitfourchette.nav import NavLocator
from gitfourchette.themes import NEUTRAL_DARK, ThemeName
from gitfourchette.toolbox import stockIcon

from .util import *

BUILTIN = str(ThemeName.BuiltIn)


def _openTree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/lib/ui/core/chips.dart", "chips")
    writeFile(f"{wd}/lib/ui/view.dart", "view")
    mainWindow.resize(1200, 900)  # room for every row: no scroll bar
    rw = mainWindow.openRepo(wd)
    GFApplication.applyPrefs(fileTreeView=True)
    return rw


def _pixel(widget: QWidget, point: QPoint) -> str:
    return widget.grab().toImage().pixelColor(point).name()


def _rowLooks(files) -> dict:
    folder = files.treeModel.indexForPath("lib/ui/view.dart").parent()
    assert folder.data(Qt.ItemDataRole.DisplayRole) == "lib/ui"
    folderIcon = folder.data(Qt.ItemDataRole.DecorationRole).pixmap(16, 16).toImage()
    return {
        "indentation": files.indentation(),
        "iconSize": files.iconSize().width(),
        "viewport": files.viewport().pos(),
        "folderColors": {folderIcon.pixelColor(x, y).name() for x in range(16) for y in range(16)
                         if folderIcon.pixelColor(x, y).alpha() == 255},
    }


def testNeutralFileRowsLookLikeForks(tempDir, mainWindow):
    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark")
    try:
        rw = _openTree(tempDir, mainWindow)
        files = rw.dirtyFiles
        modern = _rowLooks(files)

        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral")
        # Fork's measures: 16 px steps, 14 px icons, rows 10 px in, blue folders
        assert _rowLooks(files) == {
            "indentation": 16,
            "iconSize": 14,
            "viewport": QPoint(10, 10),
            "folderColors": {"#3bb7e6"},
        }

        # The selection is a pill across the whole row, the indentation
        # included, stopping short of the right edge; gray until the list
        # has the focus, then in the accent color
        rw.jump(NavLocator.inUnstaged("lib/ui/view.dart"), check=True)
        rw.diffView.setFocus()
        viewport = files.viewport()
        assert not files.verticalScrollBar().isVisible()
        selected = files.visualRect(files.treeModel.indexForPath("lib/ui/view.dart"))
        assert _pixel(viewport, QPoint(2, selected.center().y())) == NEUTRAL_DARK.selInactive
        assert _pixel(viewport, QPoint(viewport.width() - 4, selected.center().y())) == NEUTRAL_DARK.surface
        files.setFocus()
        accent = files.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name()
        assert _pixel(viewport, QPoint(2, selected.center().y())) == accent

        # With a scroll bar, the rows stop at it instead
        files.setFixedHeight(3 * selected.height())
        files.scrollTo(files.treeModel.indexForPath("lib/ui/view.dart"))
        QTest.qWait(0)
        assert files.verticalScrollBar().isVisible()
        selectedNow = files.visualRect(files.treeModel.indexForPath("lib/ui/view.dart"))
        assert _pixel(viewport, QPoint(viewport.width() - 2, selectedNow.center().y())) == accent
        files.setMinimumHeight(0)
        files.setMaximumHeight(QWIDGETSIZE_MAX)
        QTest.qWait(0)

        # A page follows the status tile of a file that isn't selected
        other = files.visualRect(files.treeModel.indexForPath("lib/ui/core/chips.dart"))
        image = viewport.grab().toImage()
        row = {image.pixelColor(x, other.center().y()).name() for x in range(other.left(), other.left() + 50)}
        assert NEUTRAL_DARK.fileGlyphColor in row

        # A folder has a thin chevron, centered in the last step of its indentation
        folder = files.visualRect(files.treeModel.indexForPath("lib/ui/view.dart").parent())
        slot = QRect(0, 0, 16, 16)
        slot.moveCenter(QRect(folder.left() - 16, folder.top(), 16, folder.height()).center())
        expected = QImage(slot.size(), QImage.Format.Format_RGB32)
        expected.fill(QColor(NEUTRAL_DARK.surface))
        painter = QPainter(expected)
        stockIcon("chevron-down").paint(painter, QRect(QPoint(0, 0), slot.size()))
        painter.end()
        assert image.copy(slot).convertToFormat(QImage.Format.Format_RGB32) == expected

        # Back to Modern: its rows come back as they were
        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark")
        assert _rowLooks(files) == modern
    finally:
        GFApplication.applyPrefs(qtStyle="")
