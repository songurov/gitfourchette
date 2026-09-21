"""The standing audit: what it reviews, what it leaves alone, and what it says twice (nothing)."""

import json
import sys
from typing import ClassVar

import pytest

from gitfourchette import settings
from gitfourchette.forge import audit, poster as posterModule, reviewrun
from gitfourchette.forge.gitlab import ChangeRequest, DiffRefs, ForgeProject
from gitfourchette.forge.reviewrun import ReviewRun
from .util import *

PROJECT = ForgeProject("gitlab.example.com", "group/project")

REVIEW = {
    "verdict": "comment",
    "summary": "Adds a handler.",
    "good": [],
    "findings": [
        {"file": "src/a.cs", "line": 2, "severity": "medium", "confidence": "high",
         "category": "Performance", "problem": "Reads every row.", "impact": "Slow.", "fix": "Aggregate."},
    ],
}

HOST_DIFF = [{"new_path": "src/a.cs", "old_path": "src/a.cs",
              "diff": "@@ -1,2 +1,3 @@\n context\n+added line\n+another added line\n"}]


class FakeSession:
    """Answers like GitLab would, and records what was sent."""

    POSTS: ClassVar[list] = []
    "Class-level: the run and the poster each make their own session."

    def __init__(self, token, parent=None):
        self.token = token
        self.posts = FakeSession.POSTS
        self.gets = []
        self.notes = []
        self.abandoned = False

    def abandon(self):
        self.abandoned = True

    def get(self, url, callback):
        self.gets.append(url)
        if "state=opened" in url:
            callback([dict(FakeSession.MERGE_REQUEST)], "")
        elif "/notes" in url:
            callback(list(FakeSession.NOTES), "")
        elif "/diffs" in url or "/changes" in url:
            callback(list(HOST_DIFF), "")
        elif "/repository/commits/" in url:
            callback({"committed_date": "2026-09-21T09:00:00Z"}, "")
        else:
            callback(dict(FakeSession.MERGE_REQUEST), "")

    def post(self, url, payload, callback):
        self.posts.append((url, payload))
        callback({"id": len(self.posts)}, "")


FakeSession.MERGE_REQUEST = {
    "iid": 7, "title": "Add a handler", "source_branch": "topic", "target_branch": "develop",
    "diff_refs": {"base_sha": "b", "start_sha": "s", "head_sha": "head1234"}}
FakeSession.NOTES = []


def fakeCli(monkeypatch, payload=REVIEW, usage=None):
    """A CLI that answers with this review, and reports what the turn cost."""
    usage = usage if usage is not None else {"input_tokens": 120000, "cached_input_tokens": 100000,
                                             "output_tokens": 3000}
    code = ("import sys, json\n"
            "sys.stdin.read()\n"
            f"review = json.loads({json.dumps(json.dumps(payload))})\n"
            "print(json.dumps({'type': 'item.completed', 'item': {'id': '1', 'type': 'agent_message', "
            "'text': json.dumps(review)}}))\n"
            f"print(json.dumps({{'type': 'turn.completed', 'usage': {json.dumps(usage)}}}))\n")
    monkeypatch.setattr(reviewrun, "cliArguments", lambda *args, **kwargs: ["-c", code])


@pytest.fixture
def repo(tempDir, mainWindow):
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    return rw.repo


def makeRun(monkeypatch, repo, notes=(), draft=False, **kwargs):
    monkeypatch.setattr(reviewrun, "ForgeSession", FakeSession)
    monkeypatch.setattr(posterModule, "ForgeSession", FakeSession)
    FakeSession.NOTES = list(notes)
    FakeSession.POSTS = []
    FakeSession.MERGE_REQUEST = dict(FakeSession.MERGE_REQUEST, draft=draft)
    changeRequest = ChangeRequest(iid=7, sourceBranch="topic", targetBranch="develop", draft=draft,
                                  refs=DiffRefs("b", "s", "head1234"))
    return ReviewRun(repo, PROJECT, "token", changeRequest, sys.executable, "codex", **kwargs)


def runToEnd(run):
    outcomes = []
    run.finished.connect(outcomes.append)
    run.start()
    waitUntilTrue(lambda: bool(outcomes))
    return outcomes[0]


def testItReviewsAMergeRequestItHasNeverSeen(repo, monkeypatch):
    fakeCli(monkeypatch)
    run = makeRun(monkeypatch, repo)
    outcome = runToEnd(run)

    assert outcome.decision.due
    assert outcome.findings == 1
    assert outcome.posted == 1
    assert not outcome.error

    discussions = [p for p in FakeSession.POSTS if "/discussions" in p[0]]
    notes = [p for p in FakeSession.POSTS if p[0].endswith("/notes")]
    assert len(discussions) == 1
    assert discussions[0][1]["position"]["new_line"] == 2
    # The summary note remembers the commit, so the next sweep knows
    assert audit.runMarker("codex", "head1234") in notes[-1][1]["body"]


def testItLeavesAloneWhatItAlreadyReviewedAtThisCommit(repo, monkeypatch):
    fakeCli(monkeypatch)
    reviewed = [{"body": "## Code Review\n\n" + audit.runMarker("codex", "head1234"), "system": False,
                 "created_at": "2026-09-21T10:00:00Z"}]
    run = makeRun(monkeypatch, repo, notes=reviewed)
    outcome = runToEnd(run)

    assert outcome.decision.verdict == audit.Verdict.ReviewedHere
    assert outcome.posted == 0
    # Nothing was sent, and the assistant was never even started
    assert FakeSession.POSTS == []
    assert run.process is None


def testADraftIsLeftAloneUntilItIsNot(repo, monkeypatch):
    fakeCli(monkeypatch)
    outcome = runToEnd(makeRun(monkeypatch, repo, draft=True))
    assert outcome.decision.verdict == audit.Verdict.Draft

    outcome = runToEnd(makeRun(monkeypatch, repo, draft=True, skipDrafts=False))
    assert outcome.decision.due and outcome.posted == 1


def testItDoesNotSayTwiceWhatTheMergeRequestAlreadyHeard(repo, monkeypatch):
    from gitfourchette.exttools.aireview import formatFinding, makeFinding

    fakeCli(monkeypatch)
    finding = makeFinding(REVIEW["findings"][0])
    heard = [{"body": formatFinding(finding, provider="codex"), "system": False,
              "created_at": "2026-09-21T10:00:00Z"}]
    run = makeRun(monkeypatch, repo, notes=heard)
    outcome = runToEnd(run)

    assert outcome.decision.due  # a new commit is still owed a review
    assert outcome.findings == 1
    assert outcome.repeated == 1
    assert [p for p in FakeSession.POSTS if "/discussions" in p[0]] == []
    # The summary still lands, and says what it held back
    summary = [p for p in FakeSession.POSTS if p[0].endswith("/notes")][-1][1]["body"]
    assert "already on this merge request" in summary


def testAPipelineReviewOfTheSameCommitIsEnough(repo, monkeypatch):
    fakeCli(monkeypatch)
    ciNote = [{"body": "## \U0001F916 DeepSeek Code Review\n\n> Comentarii de review", "system": False,
               "created_at": "2026-09-21T12:00:00Z"}]
    outcome = runToEnd(makeRun(monkeypatch, repo, notes=ciNote))
    assert outcome.decision.verdict == audit.Verdict.ReviewedByCi

    outcome = runToEnd(makeRun(monkeypatch, repo, notes=ciNote, skipCiReviewed=False))
    assert outcome.decision.due


def testTheWatcherSkipsWhatItCannotReview(tempDir, mainWindow, monkeypatch):
    from gitfourchette.forge.watcher import AuditWatcher

    rw = mainWindow.openRepo(unpackRepo(tempDir))
    settings.prefs.auditEnabled = True
    settings.prefs.auditRepos = [rw.repo.workdir, "/nonexistent/repo"]

    watcher = AuditWatcher(mainWindow)
    said = []
    watcher.progress.connect(said.append)
    done = []
    watcher.sweepFinished.connect(lambda *args: done.append(args))
    watcher.sweep()

    waitUntilTrue(lambda: bool(done))
    # The test repo's remote is GitHub, and the other path isn't a repository
    assert any("Can’t open" in message for message in said)
    assert any("No GitLab token" in message for message in said)
    assert done[0] == (0, 0)
    settings.prefs.auditEnabled = False
    settings.prefs.auditRepos = []


def testRunningItByHandWorksWhileTheTimerIsOff(tempDir, mainWindow, monkeypatch):
    from gitfourchette.forge.watcher import AuditWatcher

    rw = mainWindow.openRepo(unpackRepo(tempDir))
    settings.prefs.auditEnabled = False
    settings.prefs.auditRepos = []

    watcher = AuditWatcher(mainWindow)
    said = []
    watcher.progress.connect(said.append)

    # Nothing chosen yet: say so rather than appearing to do something
    watcher.sweep(force=True)
    assert any("Settings" in message for message in said)

    # The switch is off, but a sweep asked for by hand still runs
    settings.prefs.auditRepos = [rw.repo.workdir]
    done = []
    watcher.sweepFinished.connect(lambda *args: done.append(args))
    watcher.sweep(force=True)
    waitUntilTrue(lambda: bool(done))

    # And the timer still does nothing while the switch is off
    said.clear()
    done.clear()
    watcher.sweep()
    assert not done and not said

    settings.prefs.auditRepos = []


def testTheMenuOpensTheAuditWindow(mainWindow):
    from gitfourchette.forms.auditwindow import AuditWindow

    action = findMenuAction(mainWindow.globalMenuBar, "Data/Merge Request Audit")
    assert action.isEnabled()
    action.trigger()

    window = mainWindow.findChild(AuditWindow)
    assert window is not None and window.isVisible()
    # Nothing has run: the list says so instead of showing an empty table
    assert "hasn" in window.headline.text()
    assert window.runButton.isEnabled()
    assert not window.stopButton.isEnabled()
    window.close()


def testASweepWalksTheMergeRequestsAndSaysWhereItIs(tempDir, mainWindow, monkeypatch):
    from gitfourchette.forge import watcher as watcherModule
    from gitfourchette.forge.accounts import loadAccounts, resetAccountsForTesting
    from gitfourchette.forge.watcher import AuditWatcher, ItemState

    rw = mainWindow.openRepo(unpackRepo(tempDir))
    rw.repo.remotes.set_url("origin", "https://gitlab.example.com/group/project.git")
    resetAccountsForTesting()
    loadAccounts().setToken("gitlab.example.com", "token")

    fakeCli(monkeypatch)
    # The sweep asks which assistants are installed; in a test, exactly one is,
    # and it is this interpreter running the fake CLI above
    monkeypatch.setattr(watcherModule, "availableProviders", lambda: {"codex": sys.executable})
    settings.history.aiProvider = "codex"
    for module in (watcherModule, reviewrun, posterModule):
        monkeypatch.setattr(module, "ForgeSession", FakeSession)
    FakeSession.NOTES = []
    FakeSession.POSTS = []
    settings.prefs.auditRepos = [rw.repo.workdir]

    watcher = AuditWatcher(mainWindow)
    done = []
    watcher.sweepFinished.connect(lambda *args: done.append(args))
    watcher.sweep(force=True)
    waitUntilTrue(lambda: bool(done))

    assert done[0] == (1, 1)
    item = watcher.items[0]
    assert item.state == ItemState.Posted
    assert item.iid == 7 and item.project == "group/project"
    assert "comment posted" in item.detail
    assert item.webUrl() == "https://gitlab.example.com/group/project/-/merge_requests/7"

    settings.prefs.auditRepos = []
    resetAccountsForTesting()


def testStoppingLeavesTheRestUnreviewedAndSaysSo(mainWindow):
    from gitfourchette.forge.watcher import AuditItem, AuditWatcher, ItemState
    from gitfourchette.forms.auditwindow import AuditWindow

    watcher = AuditWatcher(mainWindow)
    watcher.items = [
        AuditItem(host="gitlab.example.com", project="group/one", iid=1, title="Done",
                  state=ItemState.Posted, detail="2 comments posted"),
        AuditItem(host="gitlab.example.com", project="group/two", iid=2, title="Under way",
                  state=ItemState.Running, detail="reviewing…"),
        AuditItem(host="gitlab.example.com", project="group/two", iid=3, title="Waiting"),
    ]
    watcher.sweeping = True

    window = AuditWindow(watcher, mainWindow)
    window.show()
    assert window.tree.topLevelItemCount() == 3
    assert window.tree.topLevelItem(0).text(0) == "!1 Done"
    assert window.tree.topLevelItem(1).text(3) == "Reviewing"
    assert window.stopButton.isEnabled() and not window.runButton.isEnabled()

    window.stopButton.click()

    # What was posted stays posted; what hadn't run is dropped, and says so
    assert [item.state for item in watcher.items] == [
        ItemState.Posted, ItemState.Cancelled, ItemState.Cancelled]
    assert window.tree.topLevelItem(2).text(3) == "Stopped"
    assert window.runButton.isEnabled() and not window.stopButton.isEnabled()
    window.close()


def testARunRecordsWhatItSpentAndWhatItSaid(repo, monkeypatch):
    fakeCli(monkeypatch)

    outcome = runToEnd(makeRun(monkeypatch, repo))

    assert outcome.elapsed > 0
    assert (outcome.inputTokens, outcome.cachedInputTokens, outcome.outputTokens) == (120000, 100000, 3000)

    # The comments are kept as they were posted, the summary note included
    assert [c.where for c in outcome.comments] == ["src/a.cs:2", ""]
    assert "Reads every row." in outcome.comments[0].body
    assert outcome.comments[-1].state == "summary"


def testTokensAreShownWithoutPretendingToKnowTheirPrice(repo, monkeypatch):
    fakeCli(monkeypatch)
    outcome = runToEnd(makeRun(monkeypatch, repo))
    assert outcome.inputTokens == 120000

    from gitfourchette.forms.auditwindow import formatElapsed, formatTokens
    assert formatTokens(123000) == "123k"
    assert formatTokens(0) == ""
    assert formatElapsed(72.4) == "1m 12s"


def testTheWindowLetsYouReadWhatWasPosted(mainWindow):
    from gitfourchette.forge.reviewrun import PostedComment
    from gitfourchette.forge.watcher import AuditItem, AuditWatcher, ItemState
    from gitfourchette.forms.auditwindow import AuditWindow

    watcher = AuditWatcher(mainWindow)
    watcher.items = [AuditItem(
        host="gitlab.example.com", project="group/one", iid=1, title="Localize the tab",
        author="Dorin Triboi", state=ItemState.Posted, detail="2 comments posted",
        elapsed=72.4, tokens=123000,
        comments=[PostedComment(where="src/a.cs:2", state="posted", body="**Problem:** Reads every row."),
                  PostedComment(where="", state="summary", body="## Code Review\n\nAll good.")])]

    window = AuditWindow(watcher, mainWindow)
    window.show()
    row = window.tree.topLevelItem(0)
    # Whose merge request it is, how long it took, what it spent - no invented price
    assert (row.text(1), row.text(4), row.text(5)) == ("Dorin Triboi", "1m 12s", "123k")

    window.tree.setCurrentItem(row)
    shown = window.commentView.toPlainText()
    assert "src/a.cs:2" in shown and "Reads every row." in shown
    assert "Summary note" in shown and "All good." in shown
    window.close()


def testTheListSaysWhichOnesAreStillDrafts(mainWindow):
    from gitfourchette.forge.watcher import AuditItem, AuditWatcher
    from gitfourchette.forms.auditwindow import AuditWindow

    watcher = AuditWatcher(mainWindow)
    watcher.items = [
        AuditItem(iid=1, title="Localize the tab", draft=True),
        AuditItem(iid=2, title="Draft: already says so", draft=True),
        AuditItem(iid=3, title="Ready for merge"),
    ]
    window = AuditWindow(watcher, mainWindow)
    window.show()

    # A draft is worth seeing at a glance, whichever way the setting is set
    assert window.tree.topLevelItem(0).text(0) == "!1 Draft: Localize the tab"
    assert window.tree.topLevelItem(1).text(0) == "!2 Draft: already says so"
    assert window.tree.topLevelItem(2).text(0) == "!3 Ready for merge"
    window.close()


def testDraftsAreReviewedUnlessYouSaySkipThem(repo, monkeypatch):
    from gitfourchette.forge import audit

    fakeCli(monkeypatch)
    # The default suits a team that drafts a merge request to ask for review
    assert settings.prefs.auditSkipDrafts is False

    outcome = runToEnd(makeRun(monkeypatch, repo, draft=True, skipDrafts=settings.prefs.auditSkipDrafts))
    assert outcome.decision.due and outcome.posted == 1

    outcome = runToEnd(makeRun(monkeypatch, repo, draft=True, skipDrafts=True))
    assert outcome.decision.verdict == audit.Verdict.Draft
