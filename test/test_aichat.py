import os
import shutil
import sys
import time
from pygit2 import Signature

import pytest

from gitfourchette.exttools import aichat, toolcommands
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.forms import aichatdialog
from gitfourchette.forms.aichatdialog import AiChatDialog
from gitfourchette.nav import NavLocator
from gitfourchette import settings
from .util import *


@pytest.fixture
def aiDialog(tempDir, mainWindow, monkeypatch):
    monkeypatch.setattr(aichatdialog, "availableProviders", lambda: {"codex": sys.executable, "claude": sys.executable})
    monkeypatch.setattr(aichatdialog, "configuredModel", lambda provider: "configured-model")
    monkeypatch.setattr(aichatdialog, "modelChoices", lambda provider: ["other-model"])
    settings.history.aiProvider = "codex"
    settings.history.aiModels = {}
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    commits = [rw.repo.head.target, rw.repo[rw.repo.head.target].parent_ids[0]]
    dialog = AiChatDialog(rw.repo, commits, rw)
    dialog.show()
    yield dialog
    dialog.reject()


def testCliArguments():
    args = aichat.cliArguments("codex")
    assert "--model" not in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[-1] == "-"
    args = aichat.cliArguments("claude", "custom model")
    assert args[args.index("--model") + 1] == "custom model"
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob"


def testProviderDetection(monkeypatch):
    monkeypatch.setattr(ToolCommands, "which", lambda name: "/bin/claude" if name == "claude" else None)
    assert aichat.availableProviders() == {"claude": "/bin/claude"}


@pytest.mark.skipif(WINDOWS, reason="no login shell on Windows")
def testToolFoundOnTheLoginShellPath(tmp_path, monkeypatch):
    # A desktop launcher hands us a PATH that owes nothing to the shell
    # profile, so a CLI in the user's own bin directory is invisible until we
    # ask the login shell where it looks (see ToolCommands.loginShellPath)
    userBin = tmp_path / "bin"
    userBin.mkdir()
    tool = userBin / "make-believe-cli"
    tool.write_text("#!/bin/sh\necho hi\n")
    tool.chmod(0o755)

    fakeShell = tmp_path / "fakeshell"
    fakeShell.write_text(f"#!/bin/sh\necho {userBin}\n")
    fakeShell.chmod(0o755)

    monkeypatch.setattr(toolcommands, "_loginShellPath", None)
    monkeypatch.setenv("PATH", "/nonexistent")
    assert shutil.which("make-believe-cli") is None

    monkeypatch.setenv("SHELL", str(fakeShell))
    assert ToolCommands.which("make-believe-cli") == str(tool)

    # The shell is asked once, not on every lookup
    monkeypatch.setenv("SHELL", "/nonexistent/shell")
    assert ToolCommands.which("make-believe-cli") == str(tool)

    # A tool found there may call others installed beside it, so our own
    # children get those directories too
    assert str(userBin) in os.environ["PATH"].split(os.pathsep)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def testResponseStream(provider):
    stream = aichat.ResponseStream(provider)
    if provider == "codex":
        stream.consume({"type": "item.completed", "item": {"id": "1", "type": "command_execution", "aggregated_output": "private tool output"}})
        for text in ("partial", "answer"):
            stream.consume({"type": "item.completed", "item": {"id": "2", "type": "agent_message", "text": text}})
    else:
        stream.consume({"type": "system", "subtype": "init", "model": "actual-model"})
        stream.consume({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "answer"}}})
        stream.consume({"type": "assistant", "message": {"id": "1", "content": [{"type": "text", "text": "answer"}]}})
        stream.consume({"type": "result", "result": "answer"})
        assert stream.model == "actual-model"
    assert stream.text == "answer"


def testModelCommands(aiDialog):
    dlg = aiDialog
    assert dlg.model() == ""
    # The header names the assistant and the model it will really use
    assert "configured-model" in dlg.setupButton.text()
    assert "Codex" in dlg.setupButton.text()
    dlg.input.setPlainText("/model custom-model")
    dlg.send()
    assert dlg.model() == "custom-model"
    assert "custom-model" in dlg.setupButton.text()
    assert not dlg.messages
    dlg.input.setPlainText("/model default")
    dlg.send()
    assert dlg.model() == ""


def testHeaderSaysWhatTheChatIsAboutAndWhoAnswers(aiDialog):
    dlg = aiDialog
    # Two commits: the count on the header line, the subjects in the list below it
    assert "2 commits" in dlg.selectionLabel.text()
    assert all(sha[:10] in dlg.selectionLabel.toolTip() for sha in dlg.commits)
    assert dlg.commitList.isVisible()
    assert "English" in dlg.setupButton.text()
    assert "no project rules" not in dlg.setupButton.text()
    dlg.rulesCheck.setChecked(False)
    assert "no project rules" in dlg.setupButton.text()

    # One commit tells its own story on the header line; no list under it
    single = AiChatDialog(dlg.repo, [dlg.repo.head.target], dlg)
    single.show()
    assert "1 commit" in single.selectionLabel.text()
    assert (single.repo.head_commit.message or "").partition("\n")[0] in single.selectionLabel.text()
    assert not single.commitList.isVisible()
    single.reject()


def testSetupStripStaysTheWayYouLeaveIt(aiDialog):
    dlg = aiDialog
    # Everything that is set once starts out folded away, under a line that says what it says
    assert not settings.history.aiSetupExpanded
    assert not dlg.setupButton.isChecked()
    assert not dlg.setupStrip.isVisible()
    assert not dlg.providerCombo.isVisible()

    dlg.setupButton.setChecked(True)
    assert dlg.setupStrip.isVisible()
    assert dlg.providerCombo.isVisible()
    assert settings.history.aiSetupExpanded

    # The next chat opens on the same choice
    other = AiChatDialog(dlg.repo, [dlg.repo.head.target], dlg)
    other.show()
    assert other.setupButton.isChecked()
    assert other.setupStrip.isVisible()
    other.reject()


def testTranscriptKeepsYourPlaceUntilYouAskAgain(aiDialog, monkeypatch):
    dlg = aiDialog
    dlg.chat.resize(400, 200)
    dlg.messages = [{"role": "user", "content": "What changed?"},
                    {"role": "assistant", "content": "\n\n".join(f"Finding {i}." for i in range(200))}]
    dlg.render()
    bar = dlg.chat.verticalScrollBar()
    assert bar.maximum() > 0

    # Reading back through the answer isn't interrupted by the words still arriving
    bar.setValue(0)
    dlg.messages[-1]["content"] += "\n\n" + "\n\n".join(f"More {i}." for i in range(50))
    dlg.render()
    assert bar.value() == 0

    # Watching the end of it still follows along
    bar.setValue(bar.maximum())
    dlg.messages[-1]["content"] += "\n\n" + "\n\n".join(f"Tail {i}." for i in range(50))
    dlg.render()
    assert bar.value() == bar.maximum()

    # The question is set off from the answer, so the two never read as one
    assert "You" in dlg.chat.toPlainText()
    assert "Assistant" in dlg.chat.toPlainText()

    # Asking the next question is the one moment the end of the transcript wins:
    # your own question, and the answer it is waiting for, land on screen
    fakeCli(monkeypatch, "import sys, time; sys.stdin.read(); time.sleep(60)")
    dlg.context = "context"
    bar.setValue(0)
    dlg.input.setPlainText("And the tests?")
    dlg.send()
    assert bar.value() == bar.maximum()
    assert "And the tests?" in dlg.chat.toPlainText()
    waitUntilTrue(lambda: dlg.process.state() == QProcess.ProcessState.Running)
    dlg.stop()
    waitUntilTrue(lambda: dlg.process is None)


def testAQuestionsMarkdownStaysInTheQuestion(aiDialog):
    dlg = aiDialog
    # What you typed is quoted, not obeyed: a rule or a heading in the question
    # must not restyle the document that quotes it
    dlg.messages = [{"role": "user", "content": "Why the `---` here?\n# Not a heading"},
                    {"role": "assistant", "content": "# A heading of my own"}]
    dlg.render()
    text = dlg.chat.toPlainText()
    assert "Why the `---` here?" in text
    assert "# Not a heading" in text
    # The answer, on the other hand, is Markdown and is laid out as such
    assert "A heading of my own" in text and "# A heading of my own" not in text


def testOmittedRulesReachTheCollapsedHeader(aiDialog, monkeypatch):
    dlg = aiDialog
    monkeypatch.setattr(aichatdialog, "projectGuidance",
                        lambda *args, **kwargs: ("Root rules.", ["AGENTS.md"], ["big.md", "bigger.md"]))
    # The strip that holds View rules is shut, the way it opens by default
    assert not dlg.setupStrip.isVisible()
    dlg.prepareGuidance()
    assert not dlg.rulesButton.isVisible()
    # Incomplete rules are the one thing here nobody chose, so the header says so
    assert "2 rules omitted" in dlg.setupButton.text()
    assert "2 rules omitted" in dlg.setupButton.toolTip()
    # A fresh scope has no verdict on its rules yet, and stops claiming one
    dlg.resetScope(dlg.commits)
    assert "omitted" not in dlg.setupButton.text()


def testALongModelNameDoesNotWidenTheDialog(aiDialog):
    dlg = aiDialog
    dlg.modelCombo.setEditText("vendor/reasoning-model-5-20251101-thinking-high")
    dlg.layout().activate()
    capped = dlg.minimumSizeHint().width()
    dlg.modelCombo.setEditText("vendor/" + "very-long-" * 40 + "model")
    dlg.layout().activate()
    assert dlg.minimumSizeHint().width() == capped
    assert "…" in dlg.setupButton.text()
    # Elided on the line, whole under the pointer
    assert "vendor/" + "very-long-" * 40 + "model" in dlg.setupButton.toolTip()


def testTheActivityScopeSaysWhatItSearches(aiDialog):
    dlg = aiDialog
    assert "Changing scope starts a new chat." in dlg.scopeCombo.toolTip()
    dlg.scopeCombo.setCurrentIndex(1)
    waitUntilTrue(lambda: dlg.process is None)
    # Once you are in that scope, the controls you are using carry its caveat
    assert "All local and remote-tracking branches" in dlg.scopeCombo.toolTip()
    assert "All local and remote-tracking branches" in dlg.activityControls.toolTip()
    dlg.scopeCombo.setCurrentIndex(0)
    assert "Changing scope starts a new chat." in dlg.scopeCombo.toolTip()


def testStatusTooltipDoesNotOutliveTheFailure(aiDialog):
    dlg = AiChatDialog(aiDialog.repo, [], aiDialog, branch="refs/heads/master")
    waitUntilTrue(lambda: dlg.process is None)
    # git's complaint is too long for one line, so it waits under the pointer
    dlg.phase = "branch"
    dlg.fail("fatal: bad revision 'refs/heads/nope'")
    assert "fatal: bad revision" in dlg.status.text()
    assert dlg.status.toolTip() == "fatal: bad revision 'refs/heads/nope'"

    # The retry that puts it right takes the complaint with it
    dlg.baseCombo.setCurrentIndex(dlg.baseCombo.findData("refs/heads/no-parent"))
    dlg.loadBranch()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.status.text() == "Ready"
    assert not dlg.status.toolTip()
    dlg.reject()


def testDeveloperWorkButton(aiDialog):
    dlg = aiDialog
    addActivityCommit(dlg.repo, "Alice [dev]", "alice@example.com", 1, "refs/heads/alice-work")
    # One click for "what has this developer been working on"
    dlg.activityButton.click()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.scopeCombo.currentIndex() == 1
    assert dlg.activityControls.isVisible()
    assert dlg.authorCombo.findData("alice@example.com") >= 0
    assert dlg.input.toPlainText() == aichat.PRESETS["summary"][1]


def fakeCli(monkeypatch, code):
    # The fake CLI's source code travels through argv. On macOS, QProcess encodes arguments
    # with QFile.encodeName(), which decomposes accented letters (NFD): a literal such as
    # 'Français' would then differ from the NFC text that the dialog writes to stdin.
    # Escape non-ASCII characters so the script's string literals reach Python unchanged.
    code = code.encode("ascii", "backslashreplace").decode("ascii")
    monkeypatch.setattr(aichatdialog, "cliArguments", lambda *args, **kwargs: ["-c", code])


def fakeProviders(monkeypatch, providers):
    """Pretend that exactly these AI CLIs are installed, whatever is on the real PATH."""
    monkeypatch.setattr(aichat, "availableProviders", lambda: dict(providers))
    monkeypatch.setattr(aichatdialog, "availableProviders", lambda: dict(providers))
    monkeypatch.setattr(aichatdialog, "configuredModel", lambda provider: "configured-model")
    monkeypatch.setattr(aichatdialog, "modelChoices", lambda provider: ["other-model"])


@pytest.mark.parametrize("provider", ["codex", "claude"])
def testConversationAndContext(aiDialog, monkeypatch, provider):
    fakeCli(monkeypatch, """
import sys, json
prompt = sys.stdin.read()
assert 'commit ' in prompt and 'diff --git' in prompt
conversation = json.loads(prompt.split('Conversation (JSON):\\n')[1])
answer = 'answer-' + str(len(conversation))
print(json.dumps({'type': 'item.completed', 'item': {'id': '1', 'type': 'agent_message', 'text': answer}}))
print(json.dumps({'type': 'result', 'result': answer}))
""")
    dlg = aiDialog
    dlg.providerCombo.setCurrentIndex(dlg.providerCombo.findData(provider))
    dlg.input.setPlainText("Summarize both commits")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.messages[-1]["content"] == "answer-1"
    assert all(sha in dlg.context for sha in dlg.commits)
    dlg.input.setPlainText("Which changes are risky?")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.messages[-1]["content"] == "answer-3"
    assert dlg.sendButton.isEnabled()


@pytest.mark.parametrize("mode", ["exit", "event", "empty", "missing"])
def testCliFailure(aiDialog, monkeypatch, mode):
    scripts = {
        "exit": "import sys; sys.stdin.read(); print('Please log in', file=sys.stderr); sys.exit(1)",
        "event": "import sys; sys.stdin.read(); print('{\"type\":\"turn.failed\",\"error\":{\"message\":\"Please log in\"}}')",
        "empty": "import sys; sys.stdin.read()",
        "missing": "",
    }
    fakeCli(monkeypatch, scripts[mode])
    dlg = aiDialog
    if mode == "missing":
        dlg.providers["codex"] = "/nonexistent/gitfourchette-ai-cli"
    dlg.input.setPlainText("Review")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert "Request interrupted" in dlg.messages[-1]["content"]
    assert dlg.sendButton.isEnabled()


def testStop(aiDialog, monkeypatch):
    fakeCli(monkeypatch, "import sys, time; sys.stdin.read(); time.sleep(60)")
    dlg = aiDialog
    dlg.context = "context"
    # Nothing to stop yet, so the bottom row only offers Send
    assert not dlg.stopButton.isVisible()
    dlg.input.setPlainText("Review")
    dlg.send()
    waitUntilTrue(lambda: dlg.process.state() == QProcess.ProcessState.Running)
    assert dlg.stopButton.isVisible()
    dlg.stop()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.status.text() == "Stopped"
    assert dlg.sendButton.isEnabled()
    assert not dlg.stopButton.isVisible()


@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("installed", [False, True])
def testAskAiMenu(tempDir, mainWindow, monkeypatch, count, installed):
    monkeypatch.setattr(aichat, "availableProviders", lambda: {"codex": "/bin/codex"} if installed else {})
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    graph = rw.graphView
    head = rw.repo.head.target
    commits = [head]
    while len(commits) < count:
        commits.append(rw.repo[commits[-1]].parent_ids[0])
    rw.jump(NavLocator.inCommit(head).replace(selectedCommits=tuple(commits) if count > 1 else ()))
    selection = graph.selectionModel()
    selection.clearSelection()
    for oid in commits:
        selection.select(graph.getFilterIndexForCommit(oid), QItemSelectionModel.SelectionFlag.Select)
    graph.onContextMenuRequested(QPoint(20, 20))
    menu = graph.findChild(QMenu, "GraphViewCM")
    assert menu.actions()[0].text() == "Ask AI…"
    assert menu.actions()[0].isEnabled() == installed
    if installed:
        menu.actions()[0].trigger()
        dialog = graph.findChild(AiChatDialog)
        assert set(dialog.commits) == {str(oid) for oid in commits}
        assert dialog.process is None
        assert dialog.isModal()
        dialog.reject()
    menu.close()


def testTruncatedContext(aiDialog, monkeypatch):
    fakeCli(monkeypatch, """
import sys, json
prompt = sys.stdin.read()
assert 'Diff context truncated' in prompt
print(json.dumps({'type': 'item.completed', 'item': {'id': '1', 'type': 'agent_message', 'text': 'Limited context'}}))
""")
    dlg = aiDialog
    dlg.ContextLimit = 50
    dlg.input.setPlainText("Review")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.messages[-1]["content"] == "Limited context"
    assert "truncated" in dlg.status.text()


@pytest.mark.parametrize("command", list(aichat.PRESETS))
def testPresets(aiDialog, monkeypatch, command):
    dlg = aiDialog
    dlg.usePreset(command)
    assert dlg.input.toPlainText() == aichat.PRESETS[command][1]
    assert dlg.process is None
    fakeCli(monkeypatch, "import sys; sys.stdin.read(); print('{\"type\":\"result\",\"result\":\"done\"}')")
    dlg.providerCombo.setCurrentIndex(dlg.providerCombo.findData("claude"))
    dlg.input.setPlainText(f"/{command} Focus on the API")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert aichat.PRESETS[command][1] in dlg.messages[0]["content"]
    assert "Focus on the API" in dlg.messages[0]["content"]


def addActivityCommit(repo, name, email, daysAgo, ref):
    timestamp = int(time.time()) - daysAgo * 86400
    signature = Signature(name, email, timestamp, 0)
    head = repo[repo.head.target]
    return str(repo.create_commit(ref, signature, signature, name + " change", head.tree_id, [head.id]))


def testDeveloperActivity(aiDialog, monkeypatch):
    dlg = aiDialog
    recent = addActivityCommit(dlg.repo, "Alice [dev]", "alice@example.com", 1, "refs/heads/alice-new")
    addActivityCommit(dlg.repo, "Alice [dev]", "alice@example.com", 4, "refs/heads/alice-old")
    addActivityCommit(dlg.repo, "Bob", "bob@example.com", 1, "refs/heads/bob-new")
    dlg.context = "old context"
    dlg.messages = [{"role": "user", "content": "old question"}]
    dlg.scopeCombo.setCurrentIndex(1)
    waitUntilTrue(lambda: dlg.process is None)
    assert not dlg.messages
    assert not dlg.sendButton.isEnabled()
    dlg.authorCombo.setCurrentIndex(dlg.authorCombo.findData("alice@example.com"))
    dlg.loadActivity()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.commits == [recent]
    assert dlg.context is None
    assert "Alice" in dlg.scopeDescription
    assert dlg.sendButton.isEnabled()
    fakeCli(monkeypatch, """
import sys, json
prompt = sys.stdin.read()
assert 'Developer: Alice' in prompt and 'Commit dates from' in prompt
assert 'old question' not in prompt
print(json.dumps({'type': 'item.completed', 'item': {'id': '1', 'type': 'agent_message', 'text': 'Alice changed code'}}))
""")
    dlg.input.setPlainText("What did Alice do?")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.messages[-1]["content"] == "Alice changed code"
    dlg.daysSpin.setValue(7)
    assert not dlg.commits and not dlg.messages and dlg.context is None
    dlg.loadActivity()
    waitUntilTrue(lambda: dlg.process is None)
    assert len(dlg.commits) == 2
    dlg.scopeCombo.setCurrentIndex(0)
    assert dlg.commits == dlg.selectedCommits


def testDeveloperLiteralSearchAndEmptyResult(aiDialog):
    dlg = aiDialog
    recent = addActivityCommit(dlg.repo, "Alice [dev]", "alice@example.com", 0, "refs/heads/literal")
    dlg.scopeCombo.setCurrentIndex(1)
    waitUntilTrue(lambda: dlg.process is None)
    dlg.authorCombo.setEditText("[dev]")
    dlg.loadActivity()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.commits == [recent]
    dlg.authorCombo.setEditText("nobody@example.com")
    dlg.loadActivity()
    waitUntilTrue(lambda: dlg.process is None)
    assert not dlg.commits
    assert not dlg.sendButton.isEnabled()
    assert "No commits found" in dlg.status.text()
    dlg.input.setPlainText("Summarize")
    dlg.send()
    assert dlg.process is None


def testBranchReview(aiDialog, monkeypatch):
    repo = aiDialog.repo
    originalHead = repo.head.target
    dlg = AiChatDialog(repo, [], aiDialog, branch="refs/heads/master")
    waitUntilTrue(lambda: dlg.process is None)
    dlg.baseCombo.setCurrentIndex(dlg.baseCombo.findData("refs/heads/no-parent"))
    dlg.loadBranch()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.commits
    assert str(originalHead) in dlg.commits
    assert dlg.branchRange[1] == str(originalHead)
    assert dlg.branchRange[0] == str(repo.references["refs/heads/no-parent"].target)
    assert repo.head.target == originalHead
    dlg.languageCombo.setCurrentText("Français")
    dlg.usePreset("review")
    fakeCli(monkeypatch, """
import json, sys
prompt = sys.stdin.read()
assert 'Response language: Français' in prompt
assert 'Review branch refs/heads/master against refs/heads/no-parent' in prompt
assert 'diff --git' in prompt
print(json.dumps({'type': 'item.completed', 'item': {'id': '1', 'type': 'agent_message', 'text': 'Revue terminée'}}))
""")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.messages[-1]["content"] == "Revue terminée"
    assert settings.history.aiLanguage == "Français"
    assert repo.head.target == originalHead
    dlg.reject()


@pytest.mark.parametrize("ref", ["refs/heads/master", "refs/remotes/origin/master"])
def testBranchPresetMenu(tempDir, mainWindow, monkeypatch, ref):
    fakeProviders(monkeypatch, {"codex": "/bin/codex"})
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    menu = rw.sidebar.makeNodeMenu(rw.sidebar.findNodeByRef(ref))
    assert menu.actions()[0].text() == "Ask AI about branch…"
    # The branch menu is built from PRESETS, so it reads in the same order as
    # the chat's own row of buttons — spelled out here so that reordering one
    # cannot quietly reorder the other
    assert [a.text() for a in menu.actions()[1:6]] == [
        "What changed…", "Code review…", "Bugs and regressions…", "Performance risks…", "Security risks…"]
    # The test repo's origin is on GitHub: the pull request action follows the presets
    assert menu.actions()[6].text() == "Create or Open Pull Request…"
    assert menu.actions()[7].isSeparator()
    menu.actions()[1].trigger()
    dlg = rw.sidebar.findChild(AiChatDialog)
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.branch == ref
    assert dlg.input.toPlainText() == aichat.PRESETS["summary"][1]
    assert not dlg.messages
    dlg.reject()


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize("ref", ["refs/heads/master", "refs/remotes/origin/master"])
def testChangeRequestAction(tempDir, mainWindow, monkeypatch, ref, installed):
    fakeProviders(monkeypatch, {"codex": "/bin/codex"} if installed else {})
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    menu = rw.sidebar.makeNodeMenu(rw.sidebar.findNodeByRef(ref))
    assert menu.actions()[0].text() == "Ask AI about branch…"
    assert menu.actions()[0].isEnabled() == installed
    action = menu.actions()[6]
    assert action.text() == "Create or Open Pull Request…"
    assert action.isEnabled()

    with MockDesktopServicesContext() as services:
        action.trigger()
        openedUrls = list(services.urls)
    dlg = rw.sidebar.findChild(AiChatDialog)

    if not installed:
        # Without an AI CLI, the action opens an empty pull request page in the browser
        assert dlg is None
        assert openedUrls == [QUrl("https://github.com/libgit2/TestGitRepository/pull/new/master?expand=1")]
        return

    assert not openedUrls
    waitUntilTrue(lambda: dlg.process is None)
    # The chat keeps the five general-purpose presets, each named after what it
    # gives back and ordered as the questions get asked; the request summary is not one of them
    assert [b.text() for b in dlg.presetButtons] == [
        "What changed", "Code review", "Bugs and regressions", "Performance risks", "Security risks"]
    # "What has this developer been working on" sits beside them, not in a combo box
    assert dlg.activityButton.text() == "Developer's work…"
    assert dlg.branch == ref
    assert dlg.changeRequest == ("https://github.com/libgit2/TestGitRepository", "master")
    assert dlg.changeRequestButton.text() == "Open Pull Request"
    # The request summary prompt is ready to send, but nothing is sent without the user
    assert dlg.input.toPlainText() == aichat.CHANGE_REQUEST_PROMPT
    assert not dlg.messages
    dlg.reject()


def testProjectGuidance(aiDialog, tmp_path):
    from pathlib import Path
    from gitfourchette.exttools.aireviewcontext import projectGuidance
    repo = aiDialog.repo
    root = Path(repo.workdir)
    files = {
        "AGENTS.md": "Root coding standards.",
        "CLAUDE.md": "Claude project conventions.",
        ".claude/rules/api.md": "---\npaths: [src/**]\n---\nAPI rules.",
        ".claude/skills/review/SKILL.md": "Review skill criteria.",
        "src/AGENTS.md": "Specific source rules.",
        "other/AGENTS.md": "Unrelated rules.",
        "src/file.py": "print('hello')\n",
    }
    for path, contents in files.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(contents)
        repo.index.add(path)
    tree = repo.index.write_tree()
    signature = Signature("Reviewer", "reviewer@example.com")
    revision = str(repo.create_commit(None, signature, signature, "Rules", tree, [repo.head.target]))
    (root / "CLAUDE.md").write_text("Wrong working-tree revision.")
    local = root / ".agents/skills/local/SKILL.md"
    local.parent.mkdir(parents=True)
    local.write_text("Local skill criteria.")
    outside = tmp_path / "secret.md"
    outside.write_text("Must never be included.")
    (root / "CLAUDE.local.md").symlink_to(outside)
    guidance, sources, omitted = projectGuidance(repo, revision, ["src/file.py"])
    assert "Specific source rules" in guidance
    assert "Unrelated rules" not in guidance
    assert "Claude project conventions" in guidance
    assert "Wrong working-tree revision" not in guidance
    assert "API rules" in guidance and "Review skill criteria" in guidance
    assert "Local skill criteria" in guidance
    assert "Must never be included" not in guidance
    assert len(sources) == 6 and not omitted
    _, _, omitted = projectGuidance(repo, revision, ["src/file.py"], limit=10)
    assert omitted


def testLanguageAndGuidanceInPrompt():
    prompt = aichat.makePrompt(["abc"], "diff", [], "Română", "Use dependency injection.")
    assert "Response language: Română" in prompt
    assert "Use dependency injection." in prompt
    assert "selected response language take precedence" in prompt


def testWorktreePrompt():
    prompt = aichat.makeWorktreePrompt(
        ["src/one.py", "src/two.py"], "diff --git", [{"role": "user", "content": "Ce s-a schimbat?"}],
        "Română", "Check errors.")
    assert "selected uncommitted changes" in prompt
    assert "src/one.py\nsrc/two.py" in prompt
    assert "Response language: Română" in prompt
    assert "Ce s-a schimbat?" in prompt


def testAskAboutUncommittedChanges(aiDialog, monkeypatch):
    # Project rules are included by default, so they must be gathered for
    # uncommitted files too, against the tree that HEAD points to
    fakeCli(monkeypatch, """
import sys, json
prompt = sys.stdin.read()
assert 'master.txt' in prompt and 'diff --git' in prompt and 'Local guidance.' in prompt
print(json.dumps({'type': 'item.completed', 'item': {'id': '1', 'type': 'agent_message', 'text': 'answer'}}))
print(json.dumps({'type': 'result', 'result': 'answer'}))
""")
    repo = aiDialog.repo
    writeFile(f"{repo.workdir}/master.txt", "uncommitted change\n")
    writeFile(f"{repo.workdir}/AGENTS.md", "Local guidance.")
    dlg = AiChatDialog(repo, [], aiDialog, worktreePaths=["master.txt"])
    dlg.show()
    assert dlg.rulesCheck.isChecked()
    dlg.input.setPlainText("What changed?")
    dlg.send()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.messages[-1]["content"] == "answer"
    assert "Local working tree:AGENTS.md" in dlg.guidanceSources
    dlg.reject()


def testBranchReviewWithoutNewCommits(aiDialog):
    repo = aiDialog.repo
    repo.references.create("refs/heads/same-tip", repo.head.target)
    dlg = AiChatDialog(repo, [], aiDialog, branch="refs/heads/same-tip")
    waitUntilTrue(lambda: dlg.process is None)
    assert not dlg.commits
    assert not dlg.sendButton.isEnabled()
    assert "No branch commits" in dlg.status.text()
    dlg.reject()


def testStatusLineTimesTheRequest(aiDialog, monkeypatch):
    # An answer can take minutes; the status line says how long it has been
    monkeypatch.setattr(aichatdialog, "makePrompt", lambda *args, **kwargs: "prompt")
    fakeClock = [0]
    monkeypatch.setattr(aiDialog.status.elapsed, "isValid", lambda: True)
    monkeypatch.setattr(aiDialog.status.elapsed, "elapsed", lambda: fakeClock[0])

    aiDialog.status.setText("Responding…")
    assert aiDialog.status.text() == "Responding…"

    aiDialog.setBusy(True)
    fakeClock[0] = 42_000
    aiDialog.status.refresh()
    assert "42 s" in aiDialog.status.text()
    assert "Responding…" in aiDialog.status.text()

    fakeClock[0] = 125_000
    aiDialog.status.refresh()
    assert "2 min 5 s" in aiDialog.status.text()

    # Once it's over, the time it took stays on screen
    aiDialog.setBusy(False)
    aiDialog.status.setText("Ready")
    assert "took" in aiDialog.status.text()
    assert "2 min 5 s" in aiDialog.status.text()


def testImagesReachBothClis(tmp_path):
    # Codex takes images as files; Claude Code is told where to find them
    shot = tmp_path / "crash.png"
    shot.write_bytes(b"\x89PNG\r\n")

    codex = aichat.cliArguments("codex", images=[shot])
    assert codex[codex.index("--image") + 1] == str(shot)
    assert codex[-1] == "-", "the prompt still comes in on stdin"

    claude = aichat.cliArguments("claude", images=[shot])
    assert "--image" not in claude, "Claude Code has no such flag"

    instructions = aichat.imageInstructions([shot])
    assert str(shot) in instructions
    assert "Read each of them" in instructions
    assert aichat.imageInstructions([]) == ""


def testEditingModeIsOffUnlessAskedFor():
    # By default the assistant may only read
    claude = aichat.cliArguments("claude")
    assert claude[claude.index("--tools") + 1] == "Read,Grep,Glob"
    assert claude[claude.index("--permission-mode") + 1] == "dontAsk"
    codex = aichat.cliArguments("codex")
    assert codex[codex.index("--sandbox") + 1] == "read-only"

    prompt = aichat.makePrompt(["abc123"], "context", [], "English")
    assert "Do not edit files" in prompt

    # Asked for, it may change files in the working tree — never Git's state
    claude = aichat.cliArguments("claude", allowEdits=True)
    assert "Edit" in claude[claude.index("--tools") + 1]
    assert claude[claude.index("--permission-mode") + 1] == "acceptEdits"
    codex = aichat.cliArguments("codex", allowEdits=True)
    assert codex[codex.index("--sandbox") + 1] == "workspace-write"

    prompt = aichat.makePrompt(["abc123"], "context", [], "English", allowEdits=True)
    assert "You may change files in the working tree" in prompt
    assert "Do not run Git write operations" in prompt
    assert "Do not edit files" not in prompt

    worktreePrompt = aichat.makeWorktreePrompt(["a.py"], "context", [], allowEdits=True)
    assert "You may change files in the working tree" in worktreePrompt


def testAnswersShowCodeAsCode(aiDialog):
    # An answer's listing gets its own box, in the font and colors of the diffs
    aiDialog.messages = [
        {"role": "user", "content": "what does it do?"},
        {"role": "assistant", "content": "It calls this:\n\n```python\ndef prepare(self):\n    pass\n```\n"},
    ]
    aiDialog.render()
    html = aiDialog.chat.toHtml()
    assert "def prepare(self):" in aiDialog.chat.toPlainText()
    assert "<table" in html, "the listing sits in a box of its own"

    # A question is still quoted verbatim: Markdown in it stays in it
    aiDialog.messages = [{"role": "user", "content": "# not a heading"}]
    aiDialog.render()
    assert "# not a heading" in aiDialog.chat.toPlainText()


def testImagesRideAlongWithTheQuestion(aiDialog, monkeypatch, tmp_path):
    """A screenshot pasted into the question reaches the CLI."""
    started = []
    monkeypatch.setattr(AiChatDialog, "startProcess",
                        lambda self, program, args, phase, prompt="": started.append((args, prompt)))
    monkeypatch.setattr(aichatdialog, "makePrompt", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(aichatdialog, "makeWorktreePrompt", lambda *a, **k: "PROMPT")

    shot = tmp_path / "crash.png"
    QImage(4, 4, QImage.Format.Format_RGB32).save(str(shot))

    # Dropping one in shows a chip you can take back out
    aiDialog.input.imageDropped.emit(str(shot))
    assert aiDialog.attachments == [str(shot)]
    assert aiDialog.attachmentsRow.isVisibleTo(aiDialog)
    chip = aiDialog.attachmentsRow.findChildren(QPushButton)[0]
    assert "crash.png" in chip.text()

    aiDialog.context = "diff --git a/x b/x"
    aiDialog.input.setPlainText("what went wrong here?")
    aiDialog.messages.append({"role": "user", "content": "what went wrong here?"})
    aiDialog.startAssistant()
    args, prompt = started[-1]
    assert str(shot) in prompt, "Claude Code is told where the image is"
    if "--image" in args:  # Codex takes the file itself
        assert args[args.index("--image") + 1] == str(shot)

    # And the chip comes back out on request
    aiDialog.removeAttachment(str(shot))
    assert aiDialog.attachments == []
    assert not aiDialog.attachmentsRow.isVisibleTo(aiDialog)


def testLettingTheAssistantChangeFilesIsDeliberate(aiDialog, monkeypatch):
    """Editing is off until asked for, and the header says so while it's on."""
    started = []
    monkeypatch.setattr(AiChatDialog, "startProcess",
                        lambda self, program, args, phase, prompt="": started.append((args, prompt)))
    aiDialog.context = "diff --git a/x b/x"

    assert not aiDialog.editsCheck.isChecked()
    assert "may change files" not in aiDialog.setupButton.text()

    aiDialog.messages.append({"role": "user", "content": "fix it"})
    aiDialog.startAssistant()
    args, prompt = started[-1]
    assert "Do not edit files" in prompt
    assert "workspace-write" not in args and "acceptEdits" not in args

    aiDialog.editsCheck.setChecked(True)
    assert "may change files" in aiDialog.setupButton.text()
    assert settings.history.aiAllowEdits, "the choice is remembered"

    aiDialog.startAssistant()
    args, prompt = started[-1]
    assert "You may change files in the working tree" in prompt
    assert "Do not run Git write operations" in prompt
    assert "workspace-write" in args or "acceptEdits" in args

    aiDialog.editsCheck.setChecked(False)
