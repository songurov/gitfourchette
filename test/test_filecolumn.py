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


def _headerLooks(title: QLabel) -> dict:
    """A file list's title and the buttons on its line, whatever holds them."""
    buttons = title.parentWidget().findChildren(QToolButton, options=Qt.FindChildOption.FindDirectChildrenOnly)
    buttons = [b for b in buttons if b.isVisible()]
    return {
        "height": title.height(),
        "order": [w.objectName() for w in sorted([title, *buttons], key=lambda w: w.x())],
        "titleFont": (title.font().pointSize(), title.font().bold()),
        "buttons": {b.objectName(): (b.toolButtonStyle(), b.autoRaise(), b.icon().isNull(), b.font().pointSize(),
                                     b.maximumHeight())
                    for b in buttons},
    }


def testNeutralFileListHeadersHaveStagePills(tempDir, mainWindow):
    GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark")
    try:
        rw = _openTree(tempDir, mainWindow)
        area = rw.diffArea
        QTest.qWait(0)
        modern = (_headerLooks(area.dirtyHeader), _headerLooks(area.stagedHeader))

        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark,neutral")
        rw.jump(NavLocator.inUnstaged("lib/ui/view.dart"), check=True)
        QTest.qWait(0)
        appPoints = QApplication.font().pointSize()
        textOnly, iconOnly = Qt.ToolButtonStyle.ToolButtonTextOnly, Qt.ToolButtonStyle.ToolButtonIconOnly
        smallPoints = round(appPoints * .9)

        # 30 px, as Fork's. The pill comes last, the other buttons are icons
        # in the reverse order, so that "Stage All" sits next to "Stage".
        assert _headerLooks(area.dirtyHeader) == {
            "height": 30,
            "order": ["dirtyHeader", "fileViewButton", "worktreeAiButton", "discardButton", "stageAllButton",
                      "stageButton"],
            "titleFont": (appPoints, True),
            "buttons": {
                "stageAllButton": (iconOnly, True, False, smallPoints, 24),
                "stageButton": (textOnly, False, False, appPoints, 24),
                "discardButton": (iconOnly, True, False, smallPoints, 24),
                "worktreeAiButton": (iconOnly, True, False, smallPoints, 24),  # a sparkle, not "AI"
                "fileViewButton": (iconOnly, True, False, appPoints, 24),  # a tree, not "☰"
            },
        }
        assert _headerLooks(area.stagedHeader)["order"] == [
            "stagedHeader", "fileViewButton", "unstageAllButton", "unstageButton"]

        # The pill ends where the rows' selection does, and has the button color
        dirtyHeader = area.stageButton.parentWidget()
        stagedHeader = area.unstageButton.parentWidget()
        assert dirtyHeader.height() == 31  # and a line under it
        pill = area.stageButton
        assert pill.text() == "Stage"
        assert pill.geometry().right() == dirtyHeader.width() - 1 - NEUTRAL_DARK.fileListInset
        image = dirtyHeader.grab().toImage()
        assert image.pixelColor(pill.x() + 3, pill.geometry().center().y()).name() == NEUTRAL_DARK.button
        # Nothing to unstage: the other pill is grayed out, but still a pill
        unstagePill = area.unstageButton
        assert not unstagePill.isEnabled()
        image2 = stagedHeader.grab().toImage()
        assert image2.pixelColor(unstagePill.x() + 3, unstagePill.geometry().center().y()).name() == \
            NEUTRAL_DARK.pillDisabled

        # The strip has the panel color, with a line under it
        title = area.dirtyHeader
        assert image.pixelColor(title.geometry().right() - 2, 3).name() == NEUTRAL_DARK.panelHeader
        assert image.pixelColor(title.geometry().right() - 2, dirtyHeader.height() - 1).name() == NEUTRAL_DARK.border

        # The name is bold and bright, the count dim
        assert title.countSplit() == ("Unstaged", " (2)")
        assert title.countColor == QColor(NEUTRAL_DARK.textDim)
        assert title.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText).name() == \
            NEUTRAL_DARK.text

        # The pill still stages
        pill.click()
        assert rw.stagedFiles.fileCount() == 1
        assert rw.dirtyFiles.fileCount() == 1

        # Back to Modern: every header is as it was
        GFApplication.applyPrefs(qtStyle=f"{BUILTIN},dark")
        QTest.qWait(0)
        assert (_headerLooks(area.dirtyHeader), _headerLooks(area.stagedHeader)) == modern
        assert area.dirtyHeader.countColor is None
    finally:
        GFApplication.applyPrefs(qtStyle="")


def _openWithCommitFormUnderTheDiff(tempDir, mainWindow, variant):
    from gitfourchette.settings import CommitFormPlacement
    from gitfourchette.themes import formatStyle
    # With the commit form under the diff, the file lists' width is the theme's alone
    GFApplication.applyPrefs(qtStyle=formatStyle(BUILTIN, "dark", variant=variant),
                             commitFormPlacement=CommitFormPlacement.BottomBar)
    rw = _openTree(tempDir, mainWindow)
    QTest.qWait(0)
    return rw.diffArea


@pytest.mark.parametrize(["variant", "width"], [("", 260), ("neutral", 360)])
def testFileColumnStartingWidth(tempDir, mainWindow, variant, width):
    try:
        area = _openWithCommitFormUnderTheDiff(tempDir, mainWindow, variant)
        assert area.findChild(QSplitter, "Split_DiffArea").sizes()[0] == width
    finally:
        GFApplication.applyPrefs(qtStyle="")


def testNeutralGivesMostOfTheColumnToUnstagedFiles(tempDir, mainWindow):
    try:
        area = _openWithCommitFormUnderTheDiff(tempDir, mainWindow, "neutral")
        unstaged, staged = area.findChild(QSplitter, "Split_Staging").sizes()
        assert unstaged / (unstaged + staged) == pytest.approx(.7, abs=.01)
    finally:
        GFApplication.applyPrefs(qtStyle="")
