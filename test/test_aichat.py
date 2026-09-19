import sys
import time
from pygit2 import Signature

import pytest

from gitfourchette.exttools import aichat
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
    monkeypatch.setattr(aichat.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)
    assert aichat.availableProviders() == {"claude": "/bin/claude"}


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
    assert "configured-model" in dlg.modelLabel.text()
    dlg.input.setPlainText("/model custom-model")
    dlg.send()
    assert dlg.model() == "custom-model"
    assert not dlg.messages
    dlg.input.setPlainText("/model default")
    dlg.send()
    assert dlg.model() == ""


def fakeCli(monkeypatch, code):
    monkeypatch.setattr(aichatdialog, "cliArguments", lambda *args: ["-c", code])


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
    dlg.input.setPlainText("Review")
    dlg.send()
    waitUntilTrue(lambda: dlg.process.state() == QProcess.ProcessState.Running)
    dlg.stop()
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.status.text() == "Stopped"
    assert dlg.sendButton.isEnabled()


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
    monkeypatch.setattr(aichat, "availableProviders", lambda: {"codex": "/bin/codex"})
    rw = mainWindow.openRepo(unpackRepo(tempDir))
    menu = rw.sidebar.makeNodeMenu(rw.sidebar.findNodeByRef(ref))
    assert menu.actions()[0].text() == "Ask AI about branch…"
    assert [a.text() for a in menu.actions()[1:6]] == [caption + "…" for caption, _prompt in aichat.PRESETS.values()]
    menu.actions()[1].trigger()
    dlg = rw.sidebar.findChild(AiChatDialog)
    waitUntilTrue(lambda: dlg.process is None)
    assert dlg.branch == ref
    assert dlg.input.toPlainText() == aichat.PRESETS["review"][1]
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
