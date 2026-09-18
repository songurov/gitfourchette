import os

from gitfourchette.forms import analysisview
from gitfourchette.forms.analysisview import AnalysisDialog, collectAnalysis, collectDeveloperCommits
from .util import *

ANA = "ana@example.com"
BOB = "bob@example.com"


def makeHistory(tempDir) -> str:
    """
    Two developers, fixed author dates (local time), one unmerged branch and one merge:

        main:    Ana 03-02 · Bob 03-05 · Ana 03-10 · merge of topic by Ana 03-15 · Ana 04-20
        topic:   Bob 03-08 (merged)
        feature: Ana 03-12 (never merged)
    """
    path = os.path.join(tempDir.name, "history")
    os.makedirs(path)
    shell("""
        git init -q -b main .
        c() {
            printf '%s\\n' "$5" >> "$4"; git add "$4"
            GIT_AUTHOR_NAME="$1" GIT_AUTHOR_EMAIL="$2" GIT_AUTHOR_DATE="$3" git commit -q -m "$6"
        }
        c Ana ana@example.com 2026-03-02T12:00:00 a.txt one   "Ana: first"
        c Bob bob@example.com 2026-03-05T12:00:00 b.txt two   "Bob: first"
        git checkout -q -b topic
        c Bob bob@example.com 2026-03-08T12:00:00 t.txt topic "Bob: topic"
        git checkout -q main
        c Ana ana@example.com 2026-03-10T12:00:00 a.txt three "Ana: second"
        GIT_AUTHOR_NAME=Ana GIT_AUTHOR_EMAIL=ana@example.com GIT_AUTHOR_DATE=2026-03-15T12:00:00 \\
            git merge -q --no-ff topic -m "Ana: merge topic"
        git checkout -q -b feature
        c Ana ana@example.com 2026-03-12T12:00:00 f.txt f     "Ana: unmerged feature work"
        git checkout -q main
        c Ana ana@example.com 2026-04-20T12:00:00 a.txt four  "Ana: outside range"
    """, path, authorSig=None)
    return path


def openCommitsPage(mainWindow, path) -> AnalysisDialog:
    mainWindow.openRepo(path)
    mainWindow.openAnalysis(AnalysisDialog.COMMITS_TAB)
    dialog = mainWindow.analysisDialog
    waitUntilTrue(lambda: dialog.commitsDeveloper.count() > 0)
    return dialog


def showCommits(dialog: AnalysisDialog, email: str, first: str, last: str, merges=False) -> list[str]:
    """Pick a developer and a range; return the subjects listed, top to bottom."""
    qcbSetIndex(dialog.commitsDeveloper, email if email else "everyone")
    dialog.commitsFrom.setDate(QDate.fromString(first, "yyyy-MM-dd"))
    dialog.commitsTo.setDate(QDate.fromString(last, "yyyy-MM-dd"))
    dialog.commitsMerges.setChecked(merges)
    dialog.queryCommits()
    waitUntilTrue(lambda: dialog.commitsShown == dialog.commitsQuery)
    table = dialog.commitsTable
    return [table.item(row, 2).text() for row in range(table.rowCount())]


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
    assert dialog.tabs.count() == 3
    assert dialog.tabs.currentIndex() == 1
    waitUntilTrue(lambda: dialog.developerTable.rowCount() > 0)
    assert dialog.developerTable.rowCount() > 0
    dialog.close()


def testNoAiPage(tempDir, mainWindow):
    """Git can't tell AI-written commits apart: the page and its column are gone."""
    mainWindow.openRepo(unpackRepo(tempDir))
    mainWindow.openAnalysis()
    dialog = mainWindow.analysisDialog
    titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert titles == ["Overview", "Developer KPI", "Developer Commits"]
    headers = [dialog.developerTable.horizontalHeaderItem(c).text()
               for c in range(dialog.developerTable.columnCount())]
    assert not any("AI" in h for h in headers)
    menuTexts = [a.text() for a in mainWindow.menuBar().findChild(QMenu, "MWMainMenuAnalysis").actions()]
    assert not any("AI" in t for t in menuTexts)
    dialog.close()


def testDataMenuOpensDeveloperCommits(tempDir, mainWindow):
    mainWindow.openRepo(unpackRepo(tempDir))
    triggerMenuAction(mainWindow.menuBar(), "data/developer commits")
    dialog = mainWindow.analysisDialog
    assert dialog.tabs.currentIndex() == AnalysisDialog.COMMITS_TAB
    # The page brings its own dates, so the dashboard-wide Period box steps aside
    assert not dialog.period.isVisible()
    dialog.tabs.setCurrentIndex(AnalysisDialog.OVERVIEW_TAB)
    assert dialog.period.isVisible()
    waitUntilTrue(lambda: not dialog.isBusy())
    dialog.close()


def testOnlyThatDeveloperInThatRange(tempDir, mainWindow):
    dialog = openCommitsPage(mainWindow, makeHistory(tempDir))

    # Newest first; the unmerged branch counts too; April and merges don't
    assert showCommits(dialog, ANA, "2026-03-01", "2026-03-31") == [
        "Ana: unmerged feature work", "Ana: second", "Ana: first"]
    assert showCommits(dialog, BOB, "2026-03-01", "2026-03-31") == ["Bob: topic", "Bob: first"]
    # Both ends of the range are whole days
    assert showCommits(dialog, ANA, "2026-03-02", "2026-03-10") == ["Ana: second", "Ana: first"]
    assert showCommits(dialog, ANA, "2026-04-01", "2026-04-30") == ["Ana: outside range"]
    assert showCommits(dialog, BOB, "2026-04-01", "2026-04-30") == []
    assert dialog.commitsSummary.text().startswith("No commits by Bob")
    dialog.close()


def testSummaryAddsUpTheList(tempDir, mainWindow):
    dialog = openCommitsPage(mainWindow, makeHistory(tempDir))
    showCommits(dialog, ANA, "2026-03-01", "2026-03-31")
    # 3 commits on 3 days, one file each, one line added each
    assert dialog.commitsSummary.text() == "3 commits · 3 active days · 3 files changed · +3 −0"
    dialog.close()


def testReversedRangeStillWorks(tempDir, mainWindow):
    dialog = openCommitsPage(mainWindow, makeHistory(tempDir))
    assert showCommits(dialog, BOB, "2026-03-31", "2026-03-01") == ["Bob: topic", "Bob: first"]
    dialog.close()


def testMergeCommitsAreOptIn(tempDir, mainWindow):
    dialog = openCommitsPage(mainWindow, makeHistory(tempDir))
    withMerges = showCommits(dialog, ANA, "2026-03-01", "2026-03-31", merges=True)
    assert withMerges == ["Ana: merge topic (merge)", "Ana: unmerged feature work", "Ana: second", "Ana: first"]
    dialog.close()


def testEveryoneListsAllAuthors(tempDir, mainWindow):
    dialog = openCommitsPage(mainWindow, makeHistory(tempDir))
    assert showCommits(dialog, "", "2026-03-01", "2026-03-31") == [
        "Ana: unmerged feature work", "Ana: second", "Bob: topic", "Bob: first", "Ana: first"]
    dialog.close()


def testDeveloperListIsNotBoundedByTheDashboard(tempDir, mainWindow, monkeypatch):
    """The KPI tabs only read the newest MAX_COMMITS; the developer list reads everything."""
    monkeypatch.setattr(analysisview, "MAX_COMMITS", 1)
    dialog = openCommitsPage(mainWindow, makeHistory(tempDir))
    combo = dialog.commitsDeveloper
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels == ["Ana <ana@example.com> — 5 commits", "Bob <bob@example.com> — 2 commits", "Everyone"]
    waitUntilTrue(lambda: not dialog.isBusy())
    dialog.close()


def testStartsOnTheRepoOwnIdentity(tempDir, mainWindow):
    path = makeHistory(tempDir)
    shell("git config user.email BOB@example.com", path)
    dialog = openCommitsPage(mainWindow, path)
    assert dialog.commitsDeveloper.currentData() == BOB
    waitUntilTrue(lambda: not dialog.isBusy())
    dialog.close()


def testDiffStatsBeyondTheDashboardLimit(tempDir, mainWindow, monkeypatch):
    monkeypatch.setattr(analysisview, "MAX_DIFF_STATS", 0)
    path = makeHistory(tempDir)
    result = collectDeveloperCommits(path, ANA, 0, 2**40, includeMerges=False)
    first = next(c for c in result.commits if c.subject == "Ana: first")  # root commit, no parent
    assert (first.files, first.insertions, first.deletions) == (1, 1, 0)
    assert not result.truncated


def testDoubleClickShowsTheCommitInTheRepo(tempDir, mainWindow):
    path = makeHistory(tempDir)
    dialog = openCommitsPage(mainWindow, path)
    showCommits(dialog, ANA, "2026-03-10", "2026-03-10")
    item = dialog.commitsTable.item(0, 1)
    oid = item.data(Qt.ItemDataRole.UserRole)

    dialog.commitsTable.itemDoubleClicked.emit(item)

    rw = mainWindow.currentRepoWidget()
    waitUntilTrue(lambda: rw.navLocator.commit == oid)
    assert rw.repo.peel_commit(oid).message.startswith("Ana: second")
    dialog.close()


def testCommitsSortNumbersNumerically(tempDir, mainWindow):
    dialog = openCommitsPage(mainWindow, unpackRepo(tempDir))
    showCommits(dialog, "", "1970-01-01", "2100-01-01")
    table = dialog.commitsTable
    table.sortItems(4, Qt.SortOrder.AscendingOrder)
    values = [int(table.item(row, 4).text()) for row in range(table.rowCount())]
    assert len(values) > 2
    assert values == sorted(values)
    dialog.close()


def testClosingRightAwayStartsNoLateWork(tempDir, mainWindow):
    """Authors arriving after close used to start a query thread that outlived the dialog."""
    mainWindow.openRepo(makeHistory(tempDir))
    mainWindow.openAnalysis(AnalysisDialog.COMMITS_TAB)
    dialog = mainWindow.analysisDialog
    dialog.close()
    started = dialog.commitsQuery
    QTest.qWait(300)  # let the queued "authors ready" arrive
    assert dialog.commitsQuery == started


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
