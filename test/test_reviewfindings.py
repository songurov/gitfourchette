"""Reviewing a branch, keeping what's worth posting, and posting it."""

import io
import json
import os
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from gitfourchette.exttools.aireview import Finding
from gitfourchette.forge import poster as posterModule
from gitfourchette.forge.gitlab import ChangeRequest, DiffRefs
from gitfourchette.forge.poster import PostState, ReviewPoster
from gitfourchette.forms import reviewfindingsdialog
from gitfourchette.forms.reviewfindingsdialog import ReviewFindingsDialog
from gitfourchette.qt import *
from .util import *

REVIEW = {
    "verdict": "request_changes",
    "summary": "Touches the file list.",
    "good": ["Small, focused change."],
    "findings": [
        {"file": "c/c1.txt", "line": 1, "severity": "high", "confidence": "high", "kind": "issue",
         "category": "Performance", "problem": "Reads the whole file.", "impact": "Slow.", "fix": "Stream it."},
        {"file": "nowhere.txt", "line": 900, "severity": "low", "confidence": "high",
         "category": "Structure", "problem": "Lives in the wrong layer."},
    ],
}


def fakeCli(monkeypatch, code):
    code = code.encode("ascii", "backslashreplace").decode("ascii")
    monkeypatch.setattr(reviewfindingsdialog, "cliArguments", lambda *args, **kwargs: ["-c", code])


def answerWith(payload: dict) -> str:
    """A fake CLI that reads the prompt and answers with this review."""
    return ("import sys, json\n"
            "prompt = sys.stdin.read()\n"
            f"review = json.loads({json.dumps(json.dumps(payload))})\n"
            "review['summary'] = review['summary'] + (' [security]' if 'Security:' in prompt else '')\n"
            "print(json.dumps({'type': 'item.completed', 'item': "
            "{'id': '1', 'type': 'agent_message', 'text': json.dumps(review)}}))\n")


@pytest.fixture
def reviewDialog(tempDir, mainWindow, monkeypatch):
    monkeypatch.setattr(reviewfindingsdialog, "availableProviders",
                        lambda: {"codex": sys.executable, "claude": sys.executable})
    monkeypatch.setattr(reviewfindingsdialog, "configuredModel", lambda provider: "configured-model")
    monkeypatch.setattr(reviewfindingsdialog, "modelChoices", lambda provider: ["other-model"])
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    rw.repo.remotes.set_url("origin", "https://gitlab.example.com/group/project.git")
    dialog = ReviewFindingsDialog(rw.repo, "refs/heads/master", rw)
    dialog.show()
    yield dialog
    dialog.reject()


def runReview(dialog, monkeypatch, payload=REVIEW):
    fakeCli(monkeypatch, answerWith(payload))
    dialog.baseCombo.setCurrentIndex(dialog.baseCombo.findData("refs/remotes/origin/first-merge"))
    dialog.runReview()
    waitUntilTrue(lambda: dialog.process is None and dialog.review is not None)


def testFindingsArriveUntickedAndNothingCanBePostedYet(reviewDialog, monkeypatch):
    dialog = reviewDialog
    assert not dialog.postButton.isEnabled()
    runReview(dialog, monkeypatch)

    assert dialog.tree.topLevelItemCount() == 2
    # Nothing is ticked by default: a finding is posted because someone read it,
    # not because a model produced it.
    assert dialog.selectedItems() == []
    assert not dialog.postButton.isEnabled()

    dialog.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert dialog.postButton.isEnabled()
    assert "1" in dialog.postButton.text()


def testTheReviewOnlySeesTheDimensionsTicked(reviewDialog, monkeypatch):
    dialog = reviewDialog
    for key, check in dialog.dimensionChecks.items():
        check.setChecked(key == "performance")
    runReview(dialog, monkeypatch)
    # The fake CLI reports back whether the prompt named a dimension nobody asked for
    assert "[security]" not in dialog.review.summary

    dialog.dimensionChecks["security"].setChecked(True)
    runReview(dialog, monkeypatch)
    assert "[security]" in dialog.review.summary


def testTheCommentIsShownAsTextAndCanBeRewritten(reviewDialog, monkeypatch):
    dialog = reviewDialog
    runReview(dialog, monkeypatch)
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))

    shown = dialog.bodyEdit.toPlainText()
    assert "Reads the whole file." in shown
    assert "[HIGH]" in shown
    # The marker is data for the next run, not something to read or edit
    assert "gf-review" not in shown

    dialog.bodyEdit.setPlainText("My own wording.")
    item = dialog.tree.topLevelItem(0)
    assert item.body == "My own wording."
    assert item.postedBody("English", "codex", marker=False) == "My own wording."
    assert item.postedBody("English", "codex").startswith("My own wording.\n\n<!-- gf-review")


def testSummaryNoteCarriesOnlyWhatWasKept(reviewDialog, monkeypatch):
    dialog = reviewDialog
    runReview(dialog, monkeypatch)
    dialog.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)

    note = dialog.summaryText(1)
    assert "Reads the whole file." in note
    # A finding the reviewer dropped must not reappear in the summary: that
    # would post it by the back door.
    assert "wrong layer" not in note
    assert "1 finding of 2 posted" in note


class FakeSession:
    """Answers like a host would, without a host."""

    def __init__(self, token, parent=None):
        self.token = token
        self.posts = []
        self.gets = []
        self.failOn = ""
        self.abandoned = False

    def abandon(self):
        self.abandoned = True

    MERGE_REQUEST: ClassVar[dict] = {
        "iid": 7, "title": "Localize the tab", "source_branch": "topic",
        "target_branch": "first-merge", "web_url": "https://gitlab.example.com/mr/7",
        "diff_refs": {"base_sha": "b", "start_sha": "s", "head_sha": "h"}}

    def get(self, url, callback):
        self.gets.append(url)
        # The list endpoint answers with an array, one merge request with an object
        callback([self.MERGE_REQUEST] if "?" in url else self.MERGE_REQUEST, "")

    def post(self, url, payload, callback):
        self.posts.append((url, payload))
        if self.failOn and self.failOn in json.dumps(payload):
            callback(None, "HTTP 400: line_code cannot be generated")
            return
        callback({"id": "1"}, "")


DIFF = """diff --git a/src/a.cs b/src/a.cs
--- a/src/a.cs
+++ b/src/a.cs
@@ -1,2 +1,3 @@
 context
+added line
+another added line
"""


def makePoster(monkeypatch, findings, **kwargs):
    monkeypatch.setattr(posterModule, "ForgeSession", FakeSession)
    from gitfourchette.forge.gitlab import ForgeProject
    project = ForgeProject("gitlab.example.com", "group/project")
    changeRequest = ChangeRequest(iid=7, sourceBranch="topic", targetBranch="develop",
                                  refs=DiffRefs("b", "s", "h"))
    return ReviewPoster(project, "token", changeRequest, DIFF, findings, provider="codex", **kwargs)


def testPosterPlacesWhatItCanAndSaysSoForTheRest(monkeypatch):
    placed = Finding(file="src/a.cs", line=2, problem="on an added line")
    snapped = Finding(file="src/a.cs", line=5, problem="a line or two off")
    unplaced = Finding(file="src/a.cs", line=400, problem="nowhere near the diff")
    poster = makePoster(monkeypatch, [placed, snapped, unplaced],
                        summaryBuilder=lambda inline: f"summary with {inline} inline")

    results = []
    poster.finished.connect(results.extend)
    poster.start()

    assert [r.state for r in results] == [PostState.Posted, PostState.Snapped, PostState.Unplaced]
    # Only the two that could be anchored were sent, plus the summary note
    discussions = [p for p in poster.session.posts if p[0].endswith("/discussions")]
    assert len(discussions) == 2
    assert discussions[0][1]["position"]["new_line"] == 2
    # The snapped one moved to the nearest line the change actually touches
    assert discussions[1][1]["position"]["new_line"] == 3
    notes = [p for p in poster.session.posts if p[0].endswith("/notes")]
    assert notes[-1][1]["body"] == "summary with 2 inline"


def testPosterReportsWhatTheHostRefused(monkeypatch):
    finding = Finding(file="src/a.cs", line=2, problem="on an added line")
    poster = makePoster(monkeypatch, [finding])
    # The host accepts the position but refuses the note (a protected branch, a
    # rate limit, a discussion API that moved): the reviewer has to hear why.
    poster.session.failOn = "on an added line"

    results = []
    poster.finished.connect(results.extend)
    poster.start()

    assert [r.state for r in results] == [PostState.Failed]
    assert "line_code cannot be generated" in results[0].message


def testPosterKeepsTheReviewersOwnWording(monkeypatch):
    finding = Finding(file="src/a.cs", line=2, problem="the model's wording")
    poster = makePoster(monkeypatch, [finding], bodies={finding.fingerprint(): "the reviewer's wording"})
    poster.start()
    body = poster.session.posts[0][1]["body"]
    assert body.startswith("the reviewer's wording")
    assert "the model's wording" not in body
    # The marker still rides along: the next run reads it back to know what it said
    assert "gf-review" in body


def testFindingTheMergeRequestAlignsTheComparison(reviewDialog, monkeypatch):
    dialog = reviewDialog
    monkeypatch.setattr(reviewfindingsdialog, "ForgeSession", FakeSession)
    monkeypatch.setattr(dialog, "ensureToken", lambda: "token")

    dialog.findMergeRequest()

    assert dialog.changeRequest.iid == 7
    assert "!7" in dialog.mrLabel.text() and "first-merge" in dialog.mrLabel.text()
    # The merge request decides what the change is measured against, so the
    # diff we review becomes the diff it shows
    assert dialog.baseCombo.currentText() == "origin/first-merge"
    assert "source_branch=topic" not in dialog.session.gets[0]  # the branch as the remote spells it
    assert "source_branch=master" in dialog.session.gets[0]


def testPostingSaysWhenThereIsNoToken(reviewDialog, monkeypatch):
    dialog = reviewDialog
    runReview(dialog, monkeypatch)
    dialog.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    # The reviewer opened the accounts window and closed it without a token
    monkeypatch.setattr(reviewfindingsdialog.ReviewFindingsDialog, "ensureToken", lambda self: "")

    dialog.postSelected()

    assert dialog.changeRequest is None
    assert "token" in dialog.statusLabel.text().lower()


def testAccountsAreKeptOutOfTheSettingsFile(mainWindow, monkeypatch):
    from gitfourchette import settings
    from gitfourchette.forge import accounts as accountsModule
    from gitfourchette.forms.forgeaccountsdialog import ForgeAccountsDialog

    accountsModule.resetAccountsForTesting()
    dialog = ForgeAccountsDialog(mainWindow)
    dialog.table.item(0, 0).setText("gitlab.example.com")
    dialog.table.cellWidget(0, 1).setText("s3cret")
    dialog.save()

    vault = accountsModule.loadAccounts()
    assert vault.tokenFor("gitlab.example.com") == "s3cret"

    settings.prefs.setDirty()
    prefsPath = settings.prefs.write(force=True)
    assert "s3cret" not in Path(prefsPath).read_text(encoding="utf-8")

    # Emptying the row takes the token away with it
    dialog = ForgeAccountsDialog(mainWindow)
    dialog.table.cellWidget(0, 1).setText("")
    dialog.save()
    assert accountsModule.loadAccounts().hosts() == []


class FakeReply:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def testTransportAsksForNothingBeyondTheStandardLibrary(mainWindow, monkeypatch):
    # The packaged AppImage strips QtNetwork out (pkg/appimage/junklist.txt), so
    # a transport built on it works from source and fails in front of the user.
    from gitfourchette.forge import session as sessionModule
    from gitfourchette.forge.session import ForgeSession

    assert "QNetworkAccessManager" not in Path(sessionModule.__file__).read_text(encoding="utf-8")

    sent = {}

    def fakeUrlopen(request, timeout=None, **kwargs):
        sent["url"] = request.full_url
        sent["method"] = request.get_method()
        sent["headers"] = {key.lower(): value for key, value in request.header_items()}
        sent["body"] = request.data
        return FakeReply(b'{"iid": 7}')

    monkeypatch.setattr(sessionModule.urllib.request, "urlopen", fakeUrlopen)
    session = ForgeSession("s3cret", mainWindow)
    seen = []
    session.post("https://gitlab.example.com/api/v4/x", {"body": "hi"}, lambda payload, error: seen.append((payload, error)))

    # The answer comes back on the GUI thread, so a callback may touch widgets
    waitUntilTrue(lambda: bool(seen))
    assert seen[0] == ({"iid": 7}, "")
    assert sent["method"] == "POST"
    assert sent["headers"]["private-token"] == "s3cret"
    assert json.loads(sent["body"]) == {"body": "hi"}


def testTransportRefusesPlainHttpAndNeverEchoesTheToken(mainWindow, monkeypatch):
    import urllib.error

    from gitfourchette.forge import session as sessionModule
    from gitfourchette.forge.session import ForgeSession

    session = ForgeSession("s3cret", mainWindow)
    seen = []
    session.get("http://gitlab.example.com/api/v4/x", lambda payload, error: seen.append((payload, error)))
    # A credential that can write to the company's repositories never travels in the clear
    assert seen[0][0] is None and "insecure" in seen[0][1].lower()

    def failingUrlopen(request, timeout=None, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(b'{"message": "401 Unauthorized for token s3cret"}'))

    monkeypatch.setattr(sessionModule.urllib.request, "urlopen", failingUrlopen)
    seen.clear()
    session.get("https://gitlab.example.com/api/v4/x", lambda payload, error: seen.append((payload, error)))
    waitUntilTrue(lambda: bool(seen))
    payload, error = seen[0]
    assert payload is None
    assert "HTTP 401" in error
    # The host echoed the token back at us; it must not reach the status line
    assert "s3cret" not in error and "***token***" in error


def testTransportFindsTheSystemCertificatesWhenItsOwnStoreIsEmpty(tmp_path, monkeypatch):
    # A packaged build carries a Python compiled elsewhere: its OpenSSL looks for
    # the certificate store at the path it was built with, finds nothing on this
    # machine, and every HTTPS call dies with "unable to get local issuer
    # certificate". That is exactly what the AppImage did.
    import ssl

    from gitfourchette.forge import session as sessionModule

    systemBundle = next((path for path in sessionModule.CA_BUNDLES if os.path.isfile(path)), "")
    if not systemBundle:
        pytest.skip("no system certificate bundle on this machine")

    bundle = tmp_path / "ca.pem"
    bundle.write_bytes(Path(systemBundle).read_bytes())

    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    monkeypatch.setattr(sessionModule, "CA_BUNDLES", (str(tmp_path / "absent.pem"), str(bundle)))
    monkeypatch.setattr(sessionModule, "CA_DIRECTORIES", ())
    sessionModule.sslContext.cache_clear()
    try:
        context = sessionModule.sslContext()
        assert context.cert_store_stats()["x509_ca"] > 0
    finally:
        sessionModule.sslContext.cache_clear()
