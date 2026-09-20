from .util import *
from gitfourchette.nav import NavLocator
from gitfourchette.graphview.commitlogmodel import CommitLogModel


def _rowOid(gv, row):
    return gv.model().index(row, 0).data(CommitLogModel.Role.Oid)


def testProbeRightClickTarget(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    gv = rw.graphView

    qlvClickNthRow(gv, 1)
    print("\nPROBE navLocator after left-click row1:", gv.navLocator.commit, "expected", _rowOid(gv, 1))

    # Right-press on row 3 (not previously selected)
    index = gv.model().index(3, 0)
    gv.scrollTo(index)
    rect = gv.visualRect(index)
    QTest.mousePress(gv.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, rect.center())
    print("PROBE navLocator right after right-press row3:", gv.navLocator.commit, "expected", _rowOid(gv, 3))
    print("PROBE selection after right-press:", [i.row() for i in gv.selectedIndexes()])
    QTest.mouseRelease(gv.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, rect.center())
    cm = summonContextMenu(gv.viewport(), rect.center())
    print("PROBE menu on row3:", [a.text() for a in cm.actions()][:6])
    cm.close()


def testProbeEmptyAreaMenu(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    gv = rw.graphView
    qlvClickNthRow(gv, 2)
    # a point well below the last row
    lastRow = gv.model().rowCount() - 1
    r = gv.visualRect(gv.model().index(lastRow, 0))
    pt = QPoint(r.center().x(), r.bottom() + 40)
    print("\nPROBE indexAt empty point valid?", gv.indexAt(pt).isValid())
    QTest.mousePress(gv.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, pt)
    QTest.mouseRelease(gv.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, pt)
    print("PROBE selection after empty right-click:", [i.row() for i in gv.selectedIndexes()])
    cm = summonContextMenu(gv.viewport(), pt)
    print("PROBE menu on empty area:", [a.text() for a in cm.actions()][:8])
    cm.close()


def testProbeMultiSelectMenu(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    gv = rw.graphView
    qlvClickNthRow(gv, 1)
    qlvClickNthRow(gv, 5, modifier=Qt.KeyboardModifier.ShiftModifier)
    print("\nPROBE navLocator with 5 selected:", gv.navLocator)
    cm = summonContextMenu(gv.viewport())
    print("PROBE menu with 5 selected:", [a.text() for a in cm.actions()])
    cm.close()
