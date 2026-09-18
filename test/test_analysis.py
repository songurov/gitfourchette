from gitfourchette.forms.analysisview import AnalysisDialog, collectAnalysis
from .util import *


def testCollectAnalysisReadsCommitHistory(tempDir):
    workdir = unpackRepo(tempDir)
    records = collectAnalysis(workdir)
    assert records
    assert records[0].author
    assert records[0].subject


def testAnalysisMenuOpensDashboard(tempDir, mainWindow):
    workdir = unpackRepo(tempDir)
    mainWindow.openRepo(workdir)
    mainWindow.openAnalysis(1)
    dialog = mainWindow.analysisDialog
    assert isinstance(dialog, AnalysisDialog)
    assert dialog.tabs.count() == 4
    assert dialog.tabs.currentIndex() == 1
    assert dialog.developerTable.rowCount() > 0
    dialog.close()


def testAnalysisCanBeOpenedRepeatedly(tempDir, mainWindow):
    workdir = unpackRepo(tempDir)
    mainWindow.openRepo(workdir)
    mainWindow.openAnalysis()
    first = mainWindow.analysisDialog
    mainWindow.openAnalysis(2)
    second = mainWindow.analysisDialog
    assert first is not second
    assert second.tabs.currentIndex() == 2
    second.close()
