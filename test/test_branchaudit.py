"""Which branches on a remote are still work, and which are sediment."""

import datetime


from gitfourchette.forge import branchaudit
from gitfourchette.forge.branchaudit import BranchFacts, Verdict, judge
from gitfourchette.qt import *
from .util import *

NOW = datetime.datetime(2026, 9, 21, tzinfo=datetime.UTC)


def daysAgo(days: int) -> datetime.datetime:
    return NOW - datetime.timedelta(days=days)


def testAMergedMergeRequestSettlesItEvenAfterASquash():
    # A squash rewrites the commits, so the tip is NOT an ancestor of the base
    # branch: only the merge request knows the work landed.
    facts = BranchFacts(name="origin/feature/x", ahead=4, containedInBase=False,
                        mergeRequest=4747, mergeRequestState="merged", lastCommit=daysAgo(30))
    verdict = judge(facts, NOW)
    assert verdict.verdict == Verdict.Merged
    assert verdict.deletable
    assert "4747" in verdict.reason


def testCommitsAlreadyInTheBaseBranchAreDone():
    facts = BranchFacts(name="origin/feature/y", ahead=0, containedInBase=True, lastCommit=daysAgo(200))
    verdict = judge(facts, NOW)
    assert verdict.verdict == Verdict.Merged and verdict.deletable


def testAnOpenMergeRequestIsActiveHoweverOldItIs():
    facts = BranchFacts(name="origin/feature/z", ahead=2, mergeRequest=4760,
                        mergeRequestState="opened", lastCommit=daysAgo(300))
    verdict = judge(facts, NOW)
    assert verdict.verdict == Verdict.Active
    assert not verdict.deletable


def testAClosedMergeRequestWaitsBeforeItCountsAsAbandoned():
    fresh = judge(BranchFacts(mergeRequest=1, mergeRequestState="closed", lastCommit=daysAgo(2)), NOW)
    assert fresh.verdict == Verdict.Abandoned and not fresh.deletable

    old = judge(BranchFacts(mergeRequest=1, mergeRequestState="closed", lastCommit=daysAgo(90)), NOW)
    assert old.verdict == Verdict.Abandoned and old.deletable


def testAgeAloneNeverMakesABranchDeletable():
    # Unfinished work nobody touched for a year may still be the only copy of it
    verdict = judge(BranchFacts(ahead=3, lastCommit=daysAgo(365)), NOW)
    assert verdict.verdict == Verdict.Stale
    assert not verdict.deletable
    assert "365 days" in verdict.reason and "3 commits" in verdict.reason


def testLongLivedBranchesAreNeverProposed():
    for name in ("origin/develop", "origin/prod", "origin/uat", "origin/main"):
        facts = BranchFacts(name=name, protected=True, lastCommit=daysAgo(400))
        assert judge(facts, NOW).verdict == Verdict.Protected
        assert not judge(facts, NOW).deletable
    assert branchaudit.isLongLived("origin/develop")
    assert not branchaudit.isLongLived("origin/feature/develop-ish")


def testTheIndexKeepsTheLatestMergeRequestPerBranch():
    # Pages arrive newest first, so the first mention wins
    index = branchaudit.readMergeRequestIndex([
        {"iid": 20, "source_branch": "feature/x", "state": "merged"},
        {"iid": 11, "source_branch": "feature/x", "state": "closed"},
        {"iid": 12, "source_branch": "feature/y", "state": "opened"},
        "not a merge request",
    ])
    assert index == {"feature/x": (20, "merged"), "feature/y": (12, "opened")}


def testFactsComeFromTheRepository(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
    rw = mainWindow.openRepo(wd)

    facts = branchaudit.collectFacts(rw.repo, "localfs")
    byName = {fact.name: fact for fact in facts}
    assert "localfs/master" in byName
    assert all(not fact.name.endswith("/HEAD") for fact in facts)

    master = byName["localfs/master"]
    assert master.author
    assert master.lastCommit is not None
    # master is the base branch here, so it is protected rather than judged
    assert judge(master).verdict == Verdict.Protected

    # This fixture's no-parent is already contained in master, which is exactly
    # the case the repository alone can settle
    noParent = byName["localfs/no-parent"]
    assert noParent.ahead == 0 and noParent.behind > 0
    assert noParent.containedInBase
    verdict = judge(noParent)
    assert verdict.verdict == Verdict.Merged and verdict.deletable


def testTheWindowTicksNothingByItself(tempDir, mainWindow):
    from gitfourchette.forms.branchauditwindow import BranchAuditWindow

    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
    rw = mainWindow.openRepo(wd)

    window = BranchAuditWindow(rw.repo, "localfs", rw)
    window.show()

    assert window.tree.topLevelItemCount() > 0
    # Deleting a branch for everyone is not something a window does on its own
    assert window.ticked() == []
    assert not window.deleteButton.isEnabled()

    window.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert window.deleteButton.isEnabled()
    assert "1" in window.deleteButton.text()
    window.close()


def testTheTableSortsByWhatEachColumnMeans(tempDir, mainWindow, monkeypatch):
    from gitfourchette.forms.branchauditwindow import BranchAuditWindow, BranchRow

    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
    rw = mainWindow.openRepo(wd)

    window = BranchAuditWindow(rw.repo, "localfs", rw)
    # Stand-in rows, so the ordering rules are what is under test
    window.tree.setSortingEnabled(False)
    window.tree.clear()
    made = [
        (BranchFacts(name="localfs/b", ahead=9, mergeRequest=9, lastCommit=daysAgo(1)),
         branchaudit.BranchVerdict(Verdict.Active, "", deletable=False)),
        (BranchFacts(name="localfs/a", ahead=29, mergeRequest=100, lastCommit=daysAgo(100)),
         branchaudit.BranchVerdict(Verdict.Merged, "", deletable=True)),
    ]
    for fact, verdict in made:
        row = BranchRow(fact, verdict, [fact.name, "", "", str(fact.ahead), f"!{fact.mergeRequest}", "", ""])
        window.tree.addTopLevelItem(row)
    window.rows = made
    window.tree.setSortingEnabled(True)

    def order(column, ascending=True):
        window.tree.sortByColumn(column, Qt.SortOrder.AscendingOrder if ascending
                                 else Qt.SortOrder.DescendingOrder)
        return [window.tree.topLevelItem(i).fact.name for i in range(window.tree.topLevelItemCount())]

    assert order(0) == ["localfs/a", "localfs/b"]
    # 29 is more than 9, whatever alphabetical order thinks
    assert order(3) == ["localfs/b", "localfs/a"]
    assert order(2) == ["localfs/a", "localfs/b"]        # oldest commit first
    assert order(4) == ["localfs/b", "localfs/a"]        # !9 before !100
    assert order(5)[0] == "localfs/a"                    # what can go, first

    # Ticking follows the row, not its position in the table
    window.selectDeletable()
    assert window.ticked() == ["localfs/a"]
    order(0, ascending=False)
    assert window.ticked() == ["localfs/a"]
    window.close()
