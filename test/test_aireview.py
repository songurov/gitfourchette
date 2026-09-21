"""The structured review: what the model answers with, and the comments it becomes."""

import os
import stat

import pytest

from gitfourchette.exttools import aireview
from gitfourchette.exttools.aireview import Finding, parseReview
from gitfourchette.forge import gitlab
from gitfourchette.forge.accounts import ForgeAccounts
from gitfourchette.forge.diffindex import diffLineIndex, resolvePosition

ANSWER = """Sure, here is the review:
```json
{
  "verdict": "request_changes",
  "summary": "Adds the promotion codes list.",
  "good": ["Cancellation tokens are propagated."],
  "findings": [
    {"file": "src/Handler.cs", "line": 34, "severity": "high", "confidence": "high", "kind": "issue",
     "category": "Performance", "problem": "Loads every redemption row.", "impact": "The page slows down.",
     "fix": "Aggregate in one grouped query.", "suggestion": ".GroupBy(x => x.CodeId)",
     "reference": {"title": "EF Core", "url": "https://learn.microsoft.com/ef"}},
    {"file": "src/Other.cs", "line": 7, "severity": "critical", "confidence": "low",
     "category": "Security", "problem": "Is the agency filter applied upstream?"}
  ]
}
```
Hope that helps."""


def testParseReviewOutOfAFencedAnswer():
    review = parseReview(ANSWER)
    assert review.verdict == "request_changes"
    assert review.good == ["Cancellation tokens are propagated."]
    assert len(review.findings) == 2

    first, second = review.findings
    assert (first.file, first.line, first.severity) == ("src/Handler.cs", 34, "high")
    assert first.blocking
    assert first.label == "issue (blocking)"

    # A finding the model isn't sure of never blocks, whatever severity it claims,
    # and is phrased as a question instead of an accusation.
    assert second.severity == "critical"
    assert not second.blocking
    assert second.commentKind == "question"


def testParseReviewRejectsJunk():
    assert parseReview("I couldn't review this.") is None
    assert parseReview("") is None
    assert parseReview('{"unrelated": 1}') is None
    # Valid JSON shape, but a finding with nothing to say isn't one
    review = parseReview('{"verdict": "comment", "findings": [{"file": "a.cs", "line": 2}]}')
    assert review is not None and review.findings == []


def testParseReviewClampsWhatTheModelInvents():
    review = parseReview("""{"verdict": "ship it", "findings": [
        {"file": "a.cs", "line": "not a number", "severity": "catastrophic", "confidence": "certain",
         "kind": "rant", "problem": "p", "reference": {"title": "x", "url": "javascript:alert(1)"}}]}""")
    finding = review.findings[0]
    assert review.verdict == "comment"
    assert finding.line == 0
    assert finding.severity == "medium"
    assert finding.confidence == "high"
    assert finding.kind == ""
    # Only an http(s) link is kept: a rendered javascript: URL is a trap
    assert finding.reference.url == ""


def testFindingFingerprintIsStable():
    finding = Finding(file="a.cs", line=3, severity="high", category="Performance", problem="p")
    assert finding.fingerprint() == Finding(file="a.cs", line=3, severity="high", category="Performance", problem="p").fingerprint()
    assert finding.fingerprint() != Finding(file="a.cs", line=4, severity="high", category="Performance", problem="p").fingerprint()

    marker = finding.marker("claude")
    assert "provider=claude" in marker
    assert f"fp={finding.fingerprint()}" in marker
    # The body never shows confidence, so the marker has to carry it: the next
    # run gates on it, and re-deriving it from the markdown gets it wrong.
    assert "conf=high" in marker and "sev=high" in marker


def testFindingRendersAsAReviewComment():
    finding = parseReview(ANSWER).findings[0]
    body = aireview.formatFinding(finding, language="Romanian", provider="codex")
    assert body.startswith("\U0001F7E0 **issue (blocking)** **[HIGH]** `[Performance]`")
    assert "**Problema:** Loads every redemption row." in body
    assert "**Solutie:** Aggregate in one grouped query." in body
    assert "```csharp\n.GroupBy(x => x.CodeId)\n```" in body
    assert "[EF Core](https://learn.microsoft.com/ef)" in body
    assert body.rstrip().endswith("-->")

    # In English the same finding keeps English headings
    assert "**Problem:**" in aireview.formatFinding(finding, language="English")

    # An unsure finding asks instead of accusing
    question = aireview.formatFinding(parseReview(ANSWER).findings[1], language="Romanian")
    assert "**Intrebare:**" in question


def testSuggestionFenceSurvivesBackticksInThePatch():
    finding = Finding(file="a.md", line=1, problem="p", suggestion="text with ``` inside")
    body = aireview.formatFinding(finding)
    # One backtick more than the longest run inside, or the fence closes early
    # and shreds the rest of the comment
    assert "````" in body
    assert body.count("````") == 2

    applicable = aireview.formatFinding(finding, applicableSuggestion=True)
    assert "````suggestion:-0+0" in applicable


def testSummaryNoteGroupsFindingsByArea():
    review = parseReview("""{"verdict": "comment", "summary": "s", "good": ["g"], "findings": [
        {"file": "api/Handler.cs", "line": 1, "severity": "high", "problem": "backend problem"},
        {"file": "app/page.ts", "line": 2, "severity": "low", "problem": "frontend nitpick"},
        {"file": "README.md", "line": 3, "severity": "medium", "problem": "doc problem"}]}""")
    note = aireview.summaryNote(review, "Code Review", headerLines=["branch → develop"], inlineCount=2)
    assert note.startswith("## \U0001F916 Code Review")
    assert "3 findings (2 inline)" in note
    assert "branch → develop" in note
    assert "⚙ Backend" in note and "\U0001F3A8 Frontend" in note and "\U0001F4C4 Other" in note
    assert "Must fix" in note  # the high-severity one
    assert "1 blocking issue" in note

    clean = aireview.summaryNote(aireview.Review(), "Code Review")
    assert "No issues found." in clean


def testPromptOnlyNamesTheDimensionsAsked():
    prompt = aireview.makeReviewPrompt("the diff", dimensions=["performance", "ef"], language="Romanian")
    assert "EF configuration" in prompt and "Performance" in prompt
    # A dimension nobody asked for must not leak in, or it comes back as findings
    assert "Security" not in prompt and "Tests" not in prompt
    assert "Romanian" in prompt

    assert "Performance" in aireview.makeReviewPrompt("d", dimensions=[])  # falls back to the defaults


DIFF = """diff --git a/src/Handler.cs b/src/Handler.cs
--- a/src/Handler.cs
+++ b/src/Handler.cs
@@ -30,4 +30,5 @@ public class Handler
     var context = 1;
-    var gone = 2;
+    var added = 3;
+    var more = 4;
diff --git a/new.txt b/new.txt
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+brand new
"""


def testDiffIndexReadsBothSides():
    index = diffLineIndex(DIFF)
    assert set(index) == {"src/Handler.cs", "new.txt"}
    handler = index["src/Handler.cs"]
    assert handler.oldPath == "src/Handler.cs"
    assert sorted(handler.added) == [31, 32]
    assert handler.context == {30: 30}
    # A file added by the change has no old side
    assert index["new.txt"].oldPath == "new.txt"


def testDiffIndexIsntFooledByContentThatLooksLikeAHeader():
    # A deleted line starting with "-- " is emitted as "--- ...", an added one
    # starting with "++ " as "+++ ...". Unguarded, the second re-points the
    # parser at a file that doesn't exist and loses every line after it.
    diff = """diff --git a/a.md b/a.md
--- a/a.md
+++ b/a.md
@@ -1,3 +1,3 @@
 keep
--- deleted markdown rule
+++ added markdown rule
+real addition
"""
    index = diffLineIndex(diff)
    assert set(index) == {"a.md"}
    assert sorted(index["a.md"].added) == [2, 3]


def testResolvePositionPlacesOrRefuses():
    index = diffLineIndex(DIFF)
    exact = resolvePosition(index, "src/Handler.cs", 31)
    assert (exact.newLine, exact.oldLine, exact.snapped) == (31, 0, False)

    # A context line exists on both sides, and GitLab rejects it without old_line
    context = resolvePosition(index, "src/Handler.cs", 30)
    assert (context.newLine, context.oldLine) == (30, 30)

    # A near miss snaps to the closest added line; a far one is left unplaced,
    # because a comment on an unrelated line is worse than none
    assert resolvePosition(index, "src/Handler.cs", 34).snapped
    assert resolvePosition(index, "src/Handler.cs", 34).newLine == 32
    assert resolvePosition(index, "src/Handler.cs", 99) is None
    assert resolvePosition(index, "absent.cs", 31) is None


def testGitLabProjectFromRemote():
    project = gitlab.projectFromRemote("git@gitlab.example.com:group/sub/project.git")
    assert project.host == "gitlab.example.com"
    assert project.path == "group/sub/project"
    assert project.encodedPath == "group%2Fsub%2Fproject"
    assert project.mergeRequestRoot(7).endswith("/merge_requests/7")
    # A self-hosted instance usually says so in its hostname; anything else isn't GitLab
    assert gitlab.projectFromRemote("git@github.com:owner/repo.git") is None
    assert gitlab.projectFromRemote("") is None


def testDiscussionPayloadCarriesTheWholePosition():
    index = diffLineIndex(DIFF)
    refs = gitlab.DiffRefs("base", "start", "head")
    payload = gitlab.discussionPayload("body", resolvePosition(index, "src/Handler.cs", 31), refs)
    position = payload["position"]
    assert position["new_line"] == 31 and position["new_path"] == "src/Handler.cs"
    assert position["base_sha"] == "base" and position["head_sha"] == "head"
    assert "old_line" not in position

    onContext = gitlab.discussionPayload("body", resolvePosition(index, "src/Handler.cs", 30), refs)
    assert onContext["position"]["old_line"] == 30


@pytest.mark.parametrize("suggestion,confidence,line,expected", [
    (".Take(10)", "high", 31, True),
    ("", "high", 31, False),                      # nothing to apply
    (".Take(10)", "medium", 31, False),           # the model wasn't sure
    ("+ added\n- removed", "high", 31, False),    # a pasted hunk, not source
    (".Take(10)", "high", 34, False),             # snapped: not where it thought it was
    (".Take(10)", "high", 30, False),             # context line: too wide a blast radius
])
def testOneClickPatchIsOfferedOnlyWhenEarned(suggestion, confidence, line, expected):
    index = diffLineIndex(DIFF)
    finding = Finding(file="src/Handler.cs", line=line, confidence=confidence, problem="p", suggestion=suggestion)
    position = resolvePosition(index, "src/Handler.cs", line)
    assert gitlab.canApplySuggestion(finding, position) is expected


def testTokensAreWrittenOwnerOnly(tmp_path, monkeypatch):
    vault = ForgeAccounts()
    monkeypatch.setattr(vault, "getParentDir", lambda: str(tmp_path))
    vault.setToken("GitLab.Example.com", "s3cret")
    path = vault.write()

    assert vault.tokenFor("gitlab.example.com") == "s3cret"
    assert vault.tokenFor("  GITLAB.EXAMPLE.COM ") == "s3cret"
    assert vault.tokenFor("github.com") == ""
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    reloaded = ForgeAccounts()
    monkeypatch.setattr(reloaded, "getParentDir", lambda: str(tmp_path))
    assert reloaded.load()
    assert reloaded.hosts() == ["gitlab.example.com"]

    # Removing the last token removes the file rather than leaving an empty vault
    vault.setToken("gitlab.example.com", "")
    vault.write()
    assert not os.path.exists(path)
