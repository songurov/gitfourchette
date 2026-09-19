# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
import sys

import pytest

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.forms.checkoutcommitdialog import CheckoutCommitDialog
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.identitydialog import IdentityDialog
from gitfourchette.forms.newtagdialog import NewTagDialog
from gitfourchette.forms.signatureform import SignatureOverride
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.nav import NavLocator
from gitfourchette.repowidget import RepoWidget
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from gitfourchette.tasks import AmendCommit, NewCommit, TaskBook
from gitfourchette.tasks.committasks import recentCommitSummaries
from gitfourchette.themes import ThemeName, ThemeVariant, activeTheme, formatStyle
from . import reposcenario
from .test_diff import accessibleNameOf, tabStops
from .test_prefs import assertTranslatedInForkLanguages
from .util import *

QDateTime19991231 = QDateTime.fromString("1999-12-31 23:59:00", "yyyy-MM-dd HH:mm:ss")


def commitFromCommitArea(rw):
    """With nothing staged, the Commit button is dead, but its menu isn't: an empty commit starts from New Commit…."""
    triggerMenuAction(rw.diffArea.commitButton.menu(), "new commit")


def fakeCommitAi(monkeypatch, code: str):
    """Pretend Codex is installed, and have it run this Python code instead."""
    from gitfourchette import diffarea
    # Non-ASCII literals would be mangled on their way through argv (see test_aichat.fakeCli)
    code = code.encode("ascii", "backslashreplace").decode("ascii")
    monkeypatch.setattr(diffarea, "availableProviders", lambda: {"codex": sys.executable})
    monkeypatch.setattr(diffarea, "configuredModel", lambda provider: "")
    monkeypatch.setattr(diffarea, "cliArguments", lambda *args: ["-c", code])


def buttonFill(button: QAbstractButton) -> QColor:
    """The color a button is filled with, just inside its left edge."""
    image = button.grab().toImage()
    return image.pixelColor(4, image.height() // 2)


def testCommitFormPlacementPreservesMessage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    form = rw.diffArea.commitForm
    rw.diffArea.setCommitMessage("Keep this message\n\nAnd its description")

    # Along the bottom, under the diff, out of the box
    assert settings.prefs.commitFormPlacement == settings.CommitFormPlacement.BottomBar
    assert form.parentWidget() is rw.diffArea.bottomCommitFormHost

    GFApplication.applyPrefs(commitFormPlacement=settings.CommitFormPlacement.FilesPanel)
    assert form.parentWidget() is rw.diffArea.stageCommitFormHost
    assert rw.diffArea.commitMessage() == "Keep this message\n\nAnd its description"

    GFApplication.applyPrefs(commitFormPlacement=settings.CommitFormPlacement.BottomBar)
    assert form.parentWidget() is rw.diffArea.bottomCommitFormHost
    assert rw.diffArea.commitMessage() == "Keep this message\n\nAnd its description"


def testBottomBarCommitFormOnlyUnderWorkdirDiffs(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    mainWindow.resize(1400, 1000)
    # A height saved for the old, taller commit form doesn't carry over
    RepoWidget.sharedSplitterSizes["Split_BottomCommitForm"] = [300, 400]
    rw = mainWindow.openRepo(wd)
    host = rw.diffArea.bottomCommitFormHost
    splitter = rw.diffArea.bottomCommitSplitter
    oid = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")

    assert settings.prefs.commitFormPlacement == settings.CommitFormPlacement.BottomBar
    assert rw.navLocator.context.isWorkdir()
    assert host.isVisibleTo(rw)
    QTest.qWait(0)
    startHeight = splitter.sizes()[1]
    assert 90 <= startHeight <= 140, "about as tall as its box and its row of buttons"

    # Make the form taller than it starts out
    total = sum(splitter.sizes())
    splitter.setSizes([total - 300, 300])
    QTest.qWait(0)
    formHeight = splitter.sizes()[1]
    assert formHeight > startHeight + 100, "should be clearly taller than it starts out"

    # A past commit's diff runs to the bottom: nothing to commit there
    rw.jump(NavLocator.inCommit(oid, "a/a1.txt"), check=True)
    assert not host.isVisibleTo(rw)

    # Changing a pref while looking at a commit doesn't bring the form back
    GFApplication.applyPrefs(sideBySideDiff=not settings.prefs.sideBySideDiff)
    assert not host.isVisibleTo(rw)

    # Back to the working directory: the form returns, as tall as it was
    rw.jump(NavLocator.inWorkdir())
    rw.taskRunner.joinWorkerThread()
    assert host.isVisibleTo(rw)
    QTest.qWait(0)
    assert splitter.sizes()[1] == formHeight

    # Picking the bottom bar while looking at a commit waits for the working directory too
    GFApplication.applyPrefs(commitFormPlacement=settings.CommitFormPlacement.FilesPanel)
    rw.jump(NavLocator.inCommit(oid, "a/a1.txt"), check=True)
    GFApplication.applyPrefs(commitFormPlacement=settings.CommitFormPlacement.BottomBar)
    assert not host.isVisibleTo(rw)
    rw.jump(NavLocator.inWorkdir())
    rw.taskRunner.joinWorkerThread()
    assert host.isVisibleTo(rw)


def testCommitAiButtonRequiresCliAndStagedChanges(tempDir, mainWindow, monkeypatch):
    from gitfourchette import diffarea

    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    monkeypatch.setattr(diffarea, "availableProviders", lambda: {"codex": "/usr/bin/codex"})
    rw = mainWindow.openRepo(wd)
    button = rw.diffArea.commitAiButton

    assert button.isEnabled()
    assert "Codex" in button.toolTip()
    assert button.accessibleName() == "Write the commit message with AI"


def testCommitAiButtonDisabledWithoutCli(tempDir, mainWindow, monkeypatch):
    from gitfourchette import diffarea

    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    monkeypatch.setattr(diffarea, "availableProviders", dict)
    rw = mainWindow.openRepo(wd)

    # Staged changes are there, so the missing CLI is the only thing holding the button back
    assert not rw.diffArea.stagedFiles.isEmpty()
    assert not rw.diffArea.commitAiButton.isEnabled()
    assert "Install" in rw.diffArea.commitAiButton.toolTip()


def testCommitAiWritesMessageInChosenLanguageAndDetail(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    fakeCommitAi(monkeypatch, """
import json, sys
prompt = sys.stdin.read()
assert 'Use this language: Français.' in prompt, prompt[:400]
assert '3-6 informative lines' in prompt, prompt[:400]
message = 'Ajoute un fichier vide\\n\\nPour la démonstration.'
print(json.dumps({'type': 'item.completed', 'item': {'id': '1', 'type': 'agent_message', 'text': message}}))
""")
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea

    # The language and the detail are in the ✦ button's menu
    menu = area.commitAiButton.menu()
    menu.aboutToShow.emit()
    triggerMenuAction(menu, "^Français$")
    menu.aboutToShow.emit()
    triggerMenuAction(menu, "^Concise$")
    assert settings.history.aiLanguage == "Français"
    assert settings.history.aiCommitDetail == "concise"
    menu.aboutToShow.emit()
    assert findMenuAction(menu, "^Français$").isChecked()
    assert not findMenuAction(menu, "^English$").isChecked()
    assert findMenuAction(menu, "^Concise$").isChecked()
    assert "Français · Concise" in area.commitAiButton.toolTip()

    # A click writes the message: its first line is the subject, the rest the description
    area.commitAiButton.click()
    assert area.commitAiSpinner.isVisibleTo(area)
    waitUntilTrue(lambda: area.commitAiProcess is None)
    assert area.commitSubjectEditor.text() == "Ajoute un fichier vide"
    assert area.commitDescriptionEditor.toPlainText() == "Pour la démonstration."
    assert not area.commitAiSpinner.isVisibleTo(area)

    # A language typed into the AI chat is offered too
    settings.history.aiLanguage = "Italiano"
    menu.aboutToShow.emit()
    assert findMenuAction(menu, "^Italiano$").isChecked()


def testCommitAiStopsWhenClickedAgain(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    fakeCommitAi(monkeypatch, "import time; time.sleep(60)")
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea

    area.commitAiButton.click()
    waitUntilTrue(lambda: area.commitAiPhase == "assistant" and area.commitAiProcess is not None
                  and area.commitAiProcess.state() == QProcess.ProcessState.Running)
    process = area.commitAiProcess
    assert area.commitAiButton.isEnabled(), "a click stops it"
    assert "Click to stop" in area.commitAiButton.toolTip()
    assert "Writing a message" in area.commitSubjectEditor.placeholderText()

    finished = []
    process.finished.connect(lambda code, status: finished.append(status))
    area.commitAiButton.click()
    assert area.commitAiProcess is None
    waitUntilTrue(lambda: finished)
    assert finished == [QProcess.ExitStatus.CrashExit], "killed"
    assert not [box for box in rw.findChildren(QMessageBox) if box.isVisible()], "stopping isn't an error"
    assert area.commitSubjectEditor.placeholderText() == "Commit subject"
    assert not area.commitAiSpinner.isVisibleTo(area)
    assert area.commitAiButton.isEnabled(), "ready to write again"


def testInlineCommitSkipsDialog(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)
    rw.diffArea.commitSubjectEditor.setText("Inline summary")
    rw.diffArea.commitDescriptionEditor.setPlainText("Inline description")

    rw.diffArea.commitButton.click()

    assert not [dialog for dialog in rw.findChildren(CommitDialog) if dialog.isVisible()]
    assert rw.repo.head_commit.message == "Inline summary\n\nInline description\n"
    assert rw.diffArea.commitMessage() == ""
    assert not rw.diffArea.commitSignoffAction.isChecked()
    assert not rw.diffArea.commitNoVerifyAction.isChecked()
    assert not rw.diffArea.amendCommitCheckBox.isChecked()


def testCommitButtonNeedsSomethingToCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/a/a1.txt", "changed\n")
    GFApplication.applyPrefs(qtStyle=formatStyle(ThemeName.BuiltIn, "dark", variant=ThemeVariant.Neutral))
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    accent = QColor(activeTheme().accent)

    # Nothing staged: Commit is off, says so plainly, and says why
    assert area.commitButton.text() == "Commit"
    assert not area.commitAction.isEnabled()
    assert "Nothing is staged" in area.commitButton.toolTip()
    assert buttonFill(area.commitButton) != accent

    # ...but its menu still works: the dialogs and Commit & Push stay within reach
    assert area.commitButton.isEnabled(), "a dead Commit keeps its menu: only its default action is off"
    menu = area.commitButton.menu()
    assert findMenuAction(menu, "new commit").isEnabled()
    assert findMenuAction(menu, "amend last commit").isEnabled()
    headBefore = rw.repo.head_commit.id
    area.setCommitMessage("Not going anywhere")
    area.commitButton.click()
    assert rw.repo.head_commit.id == headBefore, "a dead Commit button commits nothing"
    assert not [dialog for dialog in rw.findChildren(CommitDialog) if dialog.isVisible()]
    area.setCommitMessage("")

    # Something staged: Commit is on, and it's the one button filled with the accent
    rw.dirtyFiles.selectAll()
    rw.dirtyFiles.stage()
    assert area.commitAction.isEnabled()
    assert area.commitButton.text() == "Commit"
    assert "Commit 1 staged file" in area.commitButton.toolTip()
    assert buttonFill(area.commitButton) == accent
    otherButtons = [button for button in area.findChildren(QAbstractButton)
                    if button.isVisible() and button is not area.commitButton]
    assert len(otherButtons) >= 10
    assert [button.objectName() for button in otherButtons if buttonFill(button) == accent] == []

    # Its menu commits and pushes, and still opens the full commit dialogs
    menu = area.commitButton.menu()
    assert [stripAccelerators(action.text()) for action in menu.actions() if not action.isSeparator()] == [
        "Commit & Push", "New Commit…", "Amend Last Commit…"]


def testAmendLoadsLastCommitMessage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    oldHead = rw.repo.head_commit
    assert not area.commitAction.isEnabled(), "nothing staged"

    # Ticking Amend with nothing written brings the last commit's message in
    area.amendCommitCheckBox.click()
    assert area.commitMessage() == oldHead.message.strip()
    assert area.commitAction.isEnabled(), "rewording the last commit needs nothing staged"
    assert area.commitButton.text() == "Amend"
    assert findMenuAction(area.commitButton.menu(), "amend & push").isEnabled()

    # Unticking it untouched takes the message back out
    area.amendCommitCheckBox.click()
    assert area.commitMessage() == ""
    assert area.commitButton.text() == "Commit"
    assert not area.commitAction.isEnabled()

    # What the user wrote stays, ticked or not
    area.setCommitMessage("Reworded")
    area.amendCommitCheckBox.click()
    assert area.commitMessage() == "Reworded"

    # Amend from the commit area
    area.commitButton.click()
    newHead = rw.repo.head_commit
    assert newHead.id != oldHead.id
    assert newHead.message == "Reworded\n"
    assert newHead.parent_ids == oldHead.parent_ids
    assert area.commitMessage() == ""
    assert not area.amendCommitCheckBox.isChecked()


def testAmendKeepsAnUntouchedMessageWordForWord(tempDir, mainWindow):
    """Amending someone else's commit mustn't quietly reflow their message."""
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.amend_commit_on_head("Subject with no blank line\nStraight into the body\nAnd another line")
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    oldHead = rw.repo.head_commit

    # The subject and the body are edited apart, but an untouched message goes back out as it came in
    area.amendCommitCheckBox.click()
    assert area.commitSubjectEditor.text() == "Subject with no blank line"
    assert area.commitDescriptionEditor.toPlainText() == "Straight into the body\nAnd another line"
    assert area.commitMessage() == oldHead.message.strip()

    area.commitButton.click()
    assert rw.repo.head_commit.message.strip() == oldHead.message.strip()

    # Once the message is edited, the subject and the body are separated as usual
    area.amendCommitCheckBox.click()
    area.setCommitMessage("Subject with no blank line\nStraight into the body")
    area.commitDescriptionEditor.setPlainText("Rewritten body")
    area.commitButton.click()
    assert rw.repo.head_commit.message.strip() == "Subject with no blank line\n\nRewritten body"


def testCommitAreaOptionsMenu(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    writeFile(f"{wd}/a/a1.txt", "an unstaged change\n")
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    button = area.commitOptionsButton
    menu = button.menu()

    assert button.accessibleName() == "More commit options"
    assert [stripAccelerators(action.text()) for action in menu.actions() if not action.isSeparator()] == [
        "Sign Off", "No-Verify", "Stash Changes…"]

    # A dot on ⋯ while an option is on
    assert not button.badge
    triggerMenuAction(menu, "sign off")
    assert button.badge
    assert "Sign Off" in button.toolTip()

    area.setCommitMessage("Signed off inline")
    area.commitButton.click()
    assert "Signed-off-by:" in rw.repo.head_commit.message

    # The options go back to off once committed
    assert not area.commitSignoffAction.isChecked()
    assert not button.badge

    # Stash… is there too
    triggerMenuAction(menu, "stash")
    findQDialog(rw, "stash").reject()


def testCommitAreaNoVerifyBypassesHooks(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        echo "#!/usr/bin/env bash\necho 'hello from hook'\nexit 1" > .git/hooks/pre-commit
        chmod +x .git/hooks/pre-commit
        echo whatever >> master.txt
        git add master.txt
    """, wd)
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea

    area.setCommitMessage("past the hook")
    area.commitButton.click()
    acceptQMessageBox(rw, "git.+exited with code 1.+hello from hook")
    assert area.commitMessage() == "past the hook", "kept for another try"

    triggerMenuAction(area.commitOptionsButton.menu(), "no-verify")
    area.commitButton.click()
    assert rw.repo.head_commit.message == "past the hook\n"


def testCommitAndPushFromCommitArea(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    menu = area.commitButton.menu()

    # It goes straight through, so it waits for a message
    assert not findMenuAction(menu, "commit & push").isEnabled()
    area.setCommitMessage("Commit, then push")
    assert findMenuAction(menu, "commit & push").isEnabled()
    assert findMenuAction(menu, "commit & push").shortcut().matches(QKeySequence("Ctrl+Alt+Return")) \
        == QKeySequence.SequenceMatch.ExactMatch

    triggerMenuAction(menu, "commit & push")
    assert rw.repo.head_commit.message == "Commit, then push\n"
    findQDialog(rw, "push").reject()


def testCommitAreaRecentSubjects(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    area.commitDescriptionEditor.setPlainText("Keep this description")

    menu = area.commitRecentButton.menu()
    menu.aboutToShow.emit()
    summaries = recentCommitSummaries(rw.repo, settings.prefs.recentCommitMessages)
    assert len(summaries) >= 2
    assert [action.text().replace("&&", "&") for action in menu.actions()] == summaries

    menu.actions()[1].trigger()
    assert area.commitSubjectEditor.text() == summaries[1]
    assert area.commitDescriptionEditor.toPlainText() == "Keep this description"


def testCommitSubjectCounter(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    counter = area.commitSubjectCounter

    assert not counter.isVisibleTo(area), "nothing to count yet"
    area.commitSubjectEditor.setText("x" * 12)
    assert counter.isVisibleTo(area)
    assert counter.text() == "12/50"
    assert not counter.property("state")
    area.commitSubjectEditor.setText("x" * 51)
    assert counter.text() == "51/50"
    assert counter.property("state") == "long"


def testCommitDescriptionGrowsWithItsText(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.resize(1400, 1000)
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea
    editor = area.commitDescriptionEditor

    def settle():
        for _i in range(5):
            QTest.qWait(0)

    settle()
    lineHeight = editor.fontMetrics().lineSpacing()
    startHeight = area.bottomCommitFormHost.height()
    assert editor.height() < 3 * lineHeight + 8, "a couple of lines to start with"

    editor.setPlainText("\n".join(f"line {i}" for i in range(5)))
    settle()
    assert editor.height() >= 5 * lineHeight
    assert area.bottomCommitFormHost.height() > startHeight, "the commit area makes room"
    assert not editor.verticalScrollBar().isVisible()

    editor.setPlainText("\n".join(f"line {i}" for i in range(30)))
    settle()
    assert editor.height() < 9 * lineHeight + 8, "past 8 lines, it scrolls"
    assert editor.verticalScrollBar().isVisible()


def testPasteMessageIntoCommitSubject(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea

    QApplication.clipboard().setText("summary\n\ndetails1\ndetails2")
    area.commitSubjectEditor.setFocus()
    QTest.keySequence(area.commitSubjectEditor, "Ctrl+V")
    assert area.commitSubjectEditor.text() == "summary"
    assert area.commitDescriptionEditor.toPlainText() == "details1\ndetails2"
    assert area.commitSubjectCounter.text() == "7/50"

    # A description that's already written isn't thrown away: the pasted lines follow it
    area.commitSubjectEditor.clear()
    QApplication.clipboard().setText("another summary\nmore details")
    QTest.keySequence(area.commitSubjectEditor, "Ctrl+V")
    assert area.commitSubjectEditor.text() == "another summary"
    assert area.commitDescriptionEditor.toPlainText() == "details1\ndetails2\n\nmore details"


def testCommitAreaKeyboard(tempDir, mainWindow, monkeypatch):
    from gitfourchette import diffarea

    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    monkeypatch.setattr(diffarea, "availableProviders", lambda: {"codex": "/usr/bin/codex"})
    rw = mainWindow.openRepo(wd)
    area = rw.diffArea

    # Tab: the subject, the description, then the buttons from left to right, Commit last
    order = [area.commitSubjectEditor, area.commitDescriptionEditor, area.commitAiButton, area.commitRecentButton,
             area.amendCommitCheckBox, area.commitOptionsButton, area.commitButton]
    stops = tabStops(area.commitSubjectEditor)
    stops = [area.commitSubjectEditor, *stops[:stops.index(area.commitButton) + 1]]
    assert stops == order

    # Every control has a name worth reading out
    for control in order:
        assert re.search(r"\w\w", accessibleNameOf(control)), control.objectName()

    # Return in the subject goes on to the description; Ctrl+Return commits
    area.commitSubjectEditor.setFocus()
    QTest.keyClicks(area.commitSubjectEditor, "From the keyboard")
    QTest.keyClick(area.commitSubjectEditor, Qt.Key.Key_Return)
    assert area.commitDescriptionEditor.hasFocus()
    assert area.commitMessageBox.property("focused")
    QTest.keyClicks(area.commitDescriptionEditor, "No mouse needed")
    QTest.keySequence(area.commitDescriptionEditor, "Ctrl+Return")
    assert rw.repo.head_commit.message == "From the keyboard\n\nNo mouse needed\n"


def testCommitAreaIsTranslated():
    assertTranslatedInForkLanguages(
        "Commit subject", "Description", "Write the commit message with AI", "Amend", "Sign Off", "No-Verify",
        "Add a “Signed-off-by” line to the message (git commit --signoff)",
        "Skip the pre-commit and commit-msg hooks (git commit --no-verify)",
        "More commit options", "On: {0}", "No recent messages", "Commit && Push", "Amend && Push",
        "Characters in the subject. Up to {0} reads well everywhere; some tools cut longer subjects short.",
        "Nothing is staged. Stage files first, or tick Amend to change the last commit.",
        "Concise", "Detailed", "Deep", "Writing a message with {0}…", "Generating a commit message… Click to stop.",
        "Install and configure Codex CLI or Claude Code to generate a commit message.",
        "Stage files to generate a commit message with AI.",
        "Generate a commit message from staged changes with {0}.",
        "AI commit message", "CLI exited with code {0}.", "There are no staged changes to describe.",
        "The CLI returned no commit message.")
    assertTranslatedInForkLanguages("Commit {n} staged file", plural="Commit {n} staged files")


def testCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)
    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["a/a1.txt"]
    rw.diffArea.commitButton.click()

    dialog: CommitDialog = findQDialog(rw, "commit")
    QTest.keyClicks(dialog.ui.summaryEditor, "Some New Commit")
    assert dialog.acceptButton.isEnabled()

    dialog.ui.revealSignature.click()

    sigUI = dialog.ui.signature.ui
    qcbSetIndex(sigUI.replaceComboBox, "author")
    sigUI.nameEdit.clear()
    assert not dialog.acceptButton.isEnabled()
    sigUI.nameEdit.setText("Custom Author")
    sigUI.emailEdit.setText("custom.author@example.com")
    sigUI.timeEdit.setDateTime(QDateTime19991231)

    assert dialog.acceptButton.isEnabled()
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "Some New Commit\n"
    assert headCommit.author.name == "Custom Author"
    assert headCommit.author.email == "custom.author@example.com"
    assert headCommit.author.time == QDateTime19991231.toSecsSinceEpoch()
    assert headCommit.committer.name == TEST_SIGNATURE.name
    assert "Signed-off-by:" not in headCommit.message

    assert len(headCommit.parents) == 1
    diff = rw.repo.diff(headCommit.parents[0], headCommit)
    patches: list[Patch] = list(diff)
    assert len(patches) == 1
    assert patches[0].delta.new_file.path == "a/a1.txt"

    assert findTextInWidget(mainWindow.statusBar2, rf"commit.+{id7(headCommit)}.+created")


def testRecentCommitSummariesAreEditable(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)
    summaries = recentCommitSummaries(rw.repo, 10)
    assert summaries[0] == rw.repo.head_commit.message.splitlines()[0]
    assert len(summaries) <= 10
    assert len(summaries) == len(set(summaries))

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    combo = dialog.ui.summaryComboBox
    assert [combo.itemText(i) for i in range(combo.count())] == summaries
    assert dialog.ui.summaryEditor.text() == ""
    combo.setCurrentIndex(0)
    assert dialog.ui.summaryEditor.text() == summaries[0]
    dialog.ui.summaryEditor.setText("A new summary")
    assert dialog.getFullMessage() == "A new summary\n"
    dialog.reject()


def testCommitUntrackedFileInEmptyRepo(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "TestEmptyRepository")
    touchFile(F"{wd}/SomeNewFile.txt")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)

    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["SomeNewFile.txt"]

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    QTest.keyClicks(dialog.ui.summaryEditor, "Initial commit")
    dialog.accept()

    rows = qlvGetRowData(rw.graphView, CommitLogModel.Role.Commit)
    commit: Commit = rows[-1].peel(Commit)
    assert commit.message == "Initial commit\n"


def testCommitMessageDraftSavedOnCancel(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == ""
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    QTest.keyClicks(dialog.ui.summaryEditor, "hoping to save this message")
    dialog.reject()
    assert rw.repoModel.prefs.hasDraftCommit()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Nothing

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == "hoping to save this message"
    assert dialog.ui.descriptionEditor.toPlainText() == ""
    dialog.ui.revealSignature.click()
    dialog.ui.signature.ui.replaceComboBox.setCurrentIndex(2)
    dialog.reject()
    assert rw.repoModel.prefs.hasDraftCommit()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Both
    assert rw.repoModel.prefs.draftCommitSignature is not None

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert rw.repoModel.prefs.hasDraftCommit()
    assert dialog.ui.summaryEditor.text() == "hoping to save this message"
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Both
    dialog.accept()  # Go through with the commit this time

    # Ensure nothing remains of the draft after a successful commit
    commitFromCommitArea(rw)
    acceptQMessageBox(rw, "empty commit")
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert not rw.repoModel.prefs.hasDraftCommit()
    assert dialog.ui.summaryEditor.text() == ""
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    dialog.reject()


def testClearCommitMessageDraft(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    commitFromCommitArea(rw)
    acceptQMessageBox(rw, "empty commit")
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == ""
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    QTest.keyClicks(dialog.ui.summaryEditor, "hoping to save this message")
    dialog.reject()

    assert rw.repoModel.prefs.hasDraftCommit()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Nothing

    assert rw.navLocator.context.isWorkdir()
    triggerContextMenuAction(rw.graphView.viewport(), "clear draft")

    assert not rw.repoModel.prefs.hasDraftCommit()
    assert not rw.repoModel.prefs.draftCommitMessage


def testCommitMessageDraftWithInvalidSignatureSavedOnCancel(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    dialog.ui.summaryEditor.setText("hoping to save this message")
    dialog.ui.revealSignature.click()
    dialog.ui.signature.ui.replaceComboBox.setCurrentIndex(2)
    dialog.ui.signature.ui.nameEdit.setText("")
    dialog.ui.signature.ui.emailEdit.setText("")
    assert not dialog.acceptButton.isEnabled()
    dialog.reject()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Nothing
    assert rw.repoModel.prefs.draftCommitSignature is None
    assert rw.repoModel.prefs.hasDraftCommit()

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == "hoping to save this message"
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    dialog.accept()  # Go through with the commit this time


def testPasteMultilineCommitMessage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    QTest.keyClicks(dialog.ui.summaryEditor, "aaa")
    QTest.keyClicks(dialog.ui.descriptionEditor, "bbb")

    QApplication.clipboard().setText("summary\ndetails1\ndetails2")

    dialog.ui.summaryEditor.setFocus()
    QTest.keySequence(dialog.ui.summaryEditor, "Ctrl+V")
    assert dialog.ui.summaryEditor.text() == "aaasummary"
    assert dialog.ui.counterLabel.text() == str(len("aaasummary"))
    assert dialog.ui.descriptionEditor.toPlainText() == "details1\ndetails2"

    # TODO: Ctrl+Zing in both fields isn't ideal
    QTest.keySequence(dialog.ui.summaryEditor, "Ctrl+Z")
    assert dialog.ui.summaryEditor.text() == "aaa"
    QTest.keySequence(dialog.ui.descriptionEditor, "Ctrl+Z")
    assert dialog.ui.descriptionEditor.toPlainText() == "bbb"

    dialog.reject()


def testAmendCommit(tempDir, mainWindow):
    oldMessage = "Delete c/c2-2.txt"
    newMessage = "amended commit message"
    newAuthorName = "Jean-Michel Tartempion"
    newAuthorEmail = "jmtartempion@example.com"

    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    oldHeadCommit = rw.repo.head_commit

    # Kick off amend dialog
    triggerMenuAction(rw.diffArea.commitButton.menu(), "amend")

    dialog: CommitDialog = findQDialog(rw, "amend")
    assert dialog.ui.summaryEditor.text() == oldMessage
    assert dialog.ui.infoText.isVisible()
    assert findTextInWidget(dialog.ui.infoText, "amending commit")
    dialog.ui.summaryEditor.setText(newMessage)
    dialog.ui.revealSignature.setChecked(True)
    dialog.ui.signature.ui.nameEdit.setText(newAuthorName)
    dialog.ui.signature.ui.emailEdit.setText(newAuthorEmail)
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.id != oldHeadCommit.id
    assert headCommit.message == newMessage + "\n"
    assert headCommit.author.name == newAuthorName
    assert headCommit.author.email == newAuthorEmail
    assert headCommit.committer.name == TEST_SIGNATURE.name
    assert headCommit.committer.email == TEST_SIGNATURE.email

    assert rw.graphView.currentRowKind == SpecialRow.UncommittedChanges  # uncommitted changes should still be selected
    assert rw.stagedFiles.isVisibleTo(rw)
    assert rw.dirtyFiles.isVisibleTo(rw)
    assert not rw.committedFiles.isVisibleTo(rw)

    assert findTextInWidget(mainWindow.statusBar2, rf"commit.+{id7(oldHeadCommit)}.+amended.+{id7(headCommit)}")


def testAmendCommitDontBreakRefresh(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    # Kick off amend dialog
    rw.jump(NavLocator.inWorkdir())
    triggerContextMenuAction(rw.graphView.viewport(), "amend")

    # Amend HEAD commit without any changes, i.e. just change the timestamp.
    dialog: CommitDialog = findQDialog(rw, "amend")
    dialog.accept()


def testEmptyCommitRaisesWarning(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    commitFromCommitArea(rw)
    acceptQMessageBox(rw, "create.+empty commit")

    commitDialog = findQDialog(rw, "commit", t=CommitDialog)
    assert commitDialog.ui.infoText.isVisible()
    assert findTextInWidget(commitDialog.ui.infoText, "empty commit")
    commitDialog.reject()

    triggerContextMenuAction(rw.graphView.viewport(), "amend")
    commitDialog = findQDialog(rw, "amend", t=CommitDialog)
    assert commitDialog.ui.infoText.isVisible()
    assert findTextInWidget(commitDialog.ui.infoText, "amending commit.+without changing its contents")
    commitDialog.reject()

    # Look for additional hint text when there are unstaged changes
    writeFile(f"{wd}/toto.txt", "toto")
    writeFile(f"{wd}/titi.txt", "titi")
    rw.refreshRepo()
    commitFromCommitArea(rw)
    qmb = findQMessageBox(rw, "create.+empty commit")
    assert re.search("2 unstaged files.+you should.+stage.+them first", qmb.text(), re.I)
    qmb.reject()


def testCommitWithoutUserIdentity(tempDir, mainWindow):
    clearSessionwideIdentity()

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    assert "user.name" not in rw.repo.config
    assert "user.email" not in rw.repo.config

    commitFromCommitArea(rw)
    acceptQMessageBox(rw, "create.+empty commit")

    identityDialog = findQDialog(rw, "identity", t=IdentityDialog)
    identityOK = identityDialog.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
    assert not identityOK.isEnabled()
    identityDialog.ui.nameEdit.setText("Archibald Haddock")
    identityDialog.ui.emailEdit.setText("1e15sabords@example.com")
    assert identityOK.isEnabled()
    identityDialog.accept()

    commitDialog = findQDialog(rw, "commit", t=CommitDialog)
    commitDialog.ui.summaryEditor.setText("ca geht's mol?")
    commitDialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "ca geht's mol?\n"
    assert headCommit.author.name == "Archibald Haddock"
    assert headCommit.author.email == "1e15sabords@example.com"


def testCommitStableDate(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    commitFromCommitArea(rw)
    acceptQMessageBox(rw, "empty commit")

    dialog = findQDialog(rw, "commit", t=CommitDialog)
    dialog.ui.summaryEditor.setText("hold on a sec...")

    # Wait for next second before confirming.
    # Commit time should not depend on when the dialog is accepted.
    QTest.qWait(1001)
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "hold on a sec...\n"
    assert signatures_equalish(headCommit.author, headCommit.committer)


def testAmendAltersCommitterDate(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    headCommit = rw.repo.head_commit
    triggerMenuAction(rw.diffArea.commitButton.menu(), "amend")

    dialog: CommitDialog = findQDialog(rw, "amend")
    dialog.ui.summaryEditor.setText("hold on a sec...")
    dialog.accept()

    amendedHeadCommit = rw.repo.head_commit
    assert amendedHeadCommit.message == "hold on a sec...\n"
    assert signatures_equalish(amendedHeadCommit.author, headCommit.author)
    assert not signatures_equalish(amendedHeadCommit.committer, headCommit.committer)
    assert not signatures_equalish(amendedHeadCommit.author, amendedHeadCommit.committer)
    assert amendedHeadCommit.author.name != TEST_SIGNATURE.name
    assert amendedHeadCommit.committer.name == TEST_SIGNATURE.name
    assert amendedHeadCommit.committer.time > amendedHeadCommit.author.time


@pytest.mark.parametrize(["task", "dialogTitle"], [(NewCommit, "new commit"), (AmendCommit, "amend")])
def testCommitButtonMenuLeavesShortcutsToMainWindow(tempDir, mainWindow, task, dialogTitle):
    # The commit button's menu holds the same actions as the Repo menu.
    # If both claimed the same shortcut, Qt would find it ambiguous and do nothing.
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)
    assert findMenuAction(rw.diffArea.commitButton.menu(), dialogTitle).shortcut() == TaskBook.shortcuts[task][0]

    QTest.keySequence(mainWindow, TaskBook.shortcuts[task][0])
    findQDialog(rw, dialogTitle, t=CommitDialog).reject()


def testCommitDialogJumpsToWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6")
    rw.jump(NavLocator.inCommit(oid1))

    triggerMenuAction(mainWindow.menuBar(), r"repo/commit")
    findQDialog(rw, r"commit").reject()
    assert NavLocator.inUnstaged("a/a1.txt").isSimilarEnoughTo(rw.navLocator)

    rw.jump(NavLocator.inStaged("a/a1.txt"))
    triggerMenuAction(mainWindow.menuBar(), r"repo/commit")
    findQDialog(rw, r"commit").reject()
    assert NavLocator.inStaged("a/a1.txt").isSimilarEnoughTo(rw.navLocator)


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is flaky here")
def testCommitDialogCtrlReturn(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), r"repo/commit")
    acceptQMessageBox(rw, "create an empty commit anyway")

    commitDialog: CommitDialog = findQDialog(rw, r"commit")

    # Widget focus is finicky in offscreen tests unless we force the dialog to be active first
    commitDialog.activateWindow()
    waitUntilTrue(commitDialog.isActiveWindow)

    commitDialog.ui.summaryEditor.setText("hello from ctrl+return")

    # Make sure the shortcut works even when a QPlainTextEdit (multiline editor) has focus
    commitDialog.ui.descriptionEditor.setFocus()
    assert commitDialog.ui.descriptionEditor.hasFocus()
    QTest.keySequence(commitDialog.focusWidget(), "Ctrl+Return")

    assert rw.repo.head_commit_message.strip() == "hello from ctrl+return"


@pytest.mark.parametrize("method", ["graphkey", "graphcm"])
def testCheckoutCommitDetachHead(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    for loc in [NavLocator.inCommit(Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6"), "master.txt"),
                NavLocator.inCommit(Oid(hex="6db9c2ebf75590eef973081736730a9ea169a0c4"), "a/a2.txt"),
                ]:
        rw.jump(loc, check=True)
        rw.activateWindow()
        QTest.qWait(0)

        if method == "graphcm":
            triggerContextMenuAction(rw.graphView.viewport(), r"check.?out")
        elif method == "graphkey":
            QTest.keyPress(rw.graphView.viewport(), Qt.Key.Key_Return)
        else:
            raise NotImplementedError(f"unknown method {method}")

        checkoutDialog: CheckoutCommitDialog = findQDialog(rw, "check.?out commit")
        checkoutDialog.ui.detachHeadRadioButton.setChecked(True)
        checkoutDialog.accept()

        assert repo.head_is_detached
        assert repo.head_commit_id == loc.commit

        assert rw.graphView.currentCommitId == loc.commit, "graphview's selected commit has jumped around"


def testCheckoutCommitBlockedByConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.statelessConflictingChange(wd)

    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), r"check.?out")

    acceptQMessageBox(rw, "fix merge conflicts before performing this action")


def testDetachHeadOnSameCommitAsCheckedOutBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    headId = rw.repo.head_commit_id
    assert not rw.repo.head_is_detached
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.DetachedHead)

    triggerMenuAction(mainWindow.menuBar(), "view/go to head commit")
    rw.graphView.setFocus()
    QTest.keyPress(rw.graphView, Qt.Key.Key_Return)

    checkoutDialog: CheckoutCommitDialog = findQDialog(rw, "check.?out commit")
    checkoutDialog.ui.detachHeadRadioButton.setChecked(True)
    checkoutDialog.accept()

    assert rw.repo.head_is_detached
    assert rw.repo.head_commit_id == headId

    # Sidebar must now reflect detached HEAD
    currentSidebarNode = rw.sidebar.filterIndexToNode(rw.sidebar.currentIndex())
    assert currentSidebarNode.kind == SidebarItem.DetachedHead


def testCommitOnDetachedHead(tempDir, mainWindow):
    oid = Oid(hex='1203b03dc816ccbb67773f28b3c19318654b0bc8')

    wd = unpackRepo(tempDir)
    shell(f"git checkout {oid}", wd)
    rw = mainWindow.openRepo(wd)

    assert rw.repo.head_is_detached
    assert rw.repo.head.target == oid

    displayedCommits = qlvGetRowData(rw.graphView, Qt.ItemDataRole.UserRole)
    assert rw.repo.head_commit in displayedCommits

    commitFromCommitArea(rw)
    acceptQMessageBox(rw, "create.+empty commit")
    commitDialog: CommitDialog = findQDialog(rw, "commit")
    commitDialog.ui.summaryEditor.setText("hello from detached HEAD")
    commitDialog.accept()

    assert rw.repo.head_is_detached
    assert rw.repo.head.target != oid  # detached HEAD should no longer point to initial commit

    newHeadCommit = rw.repo.head_commit
    assert newHeadCommit.message == "hello from detached HEAD\n"

    displayedCommits = qlvGetRowData(rw.graphView, Qt.ItemDataRole.UserRole)
    assert newHeadCommit in displayedCommits


def testRevertCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "revert")
    acceptQMessageBox(rw, "do you want to revert")
    acceptQMessageBox(rw, "reverting.+c9ed7bf.+successful")

    commitDialog: CommitDialog = rw.findChild(CommitDialog)
    assert commitDialog.isVisible()
    assert re.search(r"revert.+delete c.c2-2.txt", commitDialog.ui.summaryEditor.text(), re.I)
    assert re.search(r"revert.+commit.+c9ed7bf", commitDialog.ui.descriptionEditor.toPlainText(), re.I)
    commitDialog.reject()

    assert rw.navLocator.context.isWorkdir()
    assert qlvGetRowData(rw.stagedFiles) == ["c/c2-2.txt"]
    assert rw.repo.status() == {"c/c2-2.txt": FileStatus.INDEX_NEW}
    assert rw.repo.state() == RepositoryState.REVERT


def testRevertCommitDud(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "revert")
    acceptQMessageBox(rw, "do you want to revert")
    acceptQMessageBox(rw, "nothing to revert")

    assert rw.repo.state() == RepositoryState.NONE


def testRevertCommitCausesConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "revert")
    acceptQMessageBox(rw, "do you want to revert")

    assert rw.repo.state() == RepositoryState.REVERT
    assert rw.repo.any_conflicts
    assert rw.conflictView.isVisible()
    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, "conflict")

    rw.conflictView.ui.theirsButton.click()
    acceptQMessageBox(rw, "accept their")
    assert findTextInWidget(rw.mergeBanner.label, "conclude the revert")
    assert rw.repo.state() == RepositoryState.REVERT

    rw.diffArea.commitButton.click()
    commitDialog: CommitDialog = rw.findChild(CommitDialog)
    assert commitDialog.isVisible()
    assert findTextInWidget(commitDialog.ui.summaryEditor, r"revert.+rename c.c2.txt.+c.c2-2.txt")
    commitDialog.accept()

    assert rw.repo.state() == RepositoryState.NONE


def testRevertCommitGitError(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Dirty a file that revert would overwrite: git bails out with rc 128.
    writeFile(f"{wd}/master.txt", "local uncommitted changes\n")

    oid = Oid(hex='58be4659bb571194ed4562d04b359d26216f526e')  # "On master again"

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid, "master.txt"), check=True)
    triggerContextMenuAction(rw.graphView.viewport(), "revert")
    acceptQMessageBox(rw, "do you want to revert commit 58be465")

    acceptQMessageBox(rw, "would be overwritten")
    assert rw.repo.state() == RepositoryState.NONE


def testAbortRevertCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "revert")
    acceptQMessageBox(rw, "do you want to revert")
    rejectQMessageBox(rw, "reverting.+c9ed7bf.+successful")

    assert rw.repo.state() == RepositoryState.REVERT
    assert rw.mergeBanner.isVisible()
    assert "revert" in rw.mergeBanner.label.text().lower()
    assert "abort" in rw.mergeBanner.buttons[-1].text().lower()

    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "abort revert")
    assert rw.repo.state() == RepositoryState.NONE
    assert not os.path.exists(f"{wd}/c/c2-2.txt")


@pytest.mark.parametrize("worktree", [False, True])
def testCherrypick(tempDir, mainWindow, worktree):
    wd = unpackRepo(tempDir)

    if worktree:
        barePath = makeBareCopy(wd, "bareOrigin", preFetch=True)
        wd = f"{barePath}/MyCoolWorktree"
        shell(f"git worktree add {wd}", barePath)

    shell("git switch no-parent", wd)

    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    acceptQMessageBox(rw, "do you want to apply.+changes from.+ac7e7e4")

    assert rw.diffArea.fileStackPage() == "workdir"
    assert rw.repo.status() == {"a/a1.txt": FileStatus.INDEX_NEW}

    rw.diffArea.commitButton.click()
    dialog = findQDialog(rw, "commit", t=CommitDialog)
    assert findTextInWidget(dialog.ui.infoText, "will conclude the cherry")
    assert dialog.ui.summaryEditor.text() == "First a/a1"
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Author

    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "First a/a1\n"
    assert headCommit.author.name == "A U Thor"

    headCommitHash = str(headCommit.id)[:5]
    assert re.match(rf"commit.+{headCommitHash}.+created", mainWindow.statusBar().currentMessage(), re.I)

    rw.jump(NavLocator.inCommit(headCommit.id))
    assert qlvGetRowData(rw.committedFiles) == ["a/a1.txt"]


def testCherrypickWithConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    oid = Oid(hex='1b2bae55ac95a4be3f8983b86cd579226d0eb247')  # provoke a conflict on '.gitignore'

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid, ".gitignore"), check=True)
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    acceptQMessageBox(rw, "do you want to apply.+changes from.+1b2bae5")

    assert rw.repo.state() == RepositoryState.CHERRYPICK
    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, "cherry-picking.+conflicts need fixing")

    assert NavLocator.inUnstaged(".gitignore").isSimilarEnoughTo(rw.navLocator)
    assert rw.diffArea.conflictView.isVisible()
    rw.diffArea.conflictView.ui.theirsButton.click()
    acceptQMessageBox(rw, "accept their")

    assert findTextInWidget(rw.mergeBanner.label, "cherry-picking.+commit to conclude")

    rw.diffArea.commitButton.click()
    dialog = findQDialog(rw, "commit", t=CommitDialog)
    assert findTextInWidget(dialog.ui.infoText, "will conclude the cherry")
    dialog.accept()

    assert rw.repo.head_commit.message.strip() == "commit to provoke a conflict"
    assert rw.repo.head_commit.author.name.startswith("Victor")
    assert rw.repo.head_commit.committer.name == TEST_SIGNATURE.name


def testCherrypickEditAuthor(tempDir, mainWindow):
    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    wd = unpackRepo(tempDir)
    shell("git switch no-parent", wd)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    acceptQMessageBox(rw, "do you want to apply.+changes from.+ac7e7e4")

    rw.diffArea.commitButton.click()
    dialog = findQDialog(rw, "commit", t=CommitDialog)
    assert findTextInWidget(dialog.ui.infoText, "will conclude the cherry")
    assert dialog.ui.summaryEditor.text() == "First a/a1"
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Author
    dialog.ui.signature.ui.nameEdit.setText("Someone Else")
    dialog.ui.signature.ui.emailEdit.setText("someone.else@example.com")
    dialog.ui.signature.ui.timeEdit.setDateTime(QDateTime19991231)
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "First a/a1\n"
    assert headCommit.author.name == "Someone Else"
    assert headCommit.author.email == "someone.else@example.com"
    assert headCommit.author.time == QDateTime19991231.toSecsSinceEpoch()
    assert headCommit.committer.name == TEST_SIGNATURE.name


def testCherrypickDud(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="f73b95671f326616d66b2afb3bdfcdbbce110b44")
    rw.jump(NavLocator.inCommit(oid))

    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    acceptQMessageBox(rw, "do you want to apply.+changes from.+f73b956")
    acceptQMessageBox(rw, "nothing to cherry.?pick.+already")
    assert rw.repo.state() == RepositoryState.NONE


def testCherrypickGitError(tempDir, mainWindow):
    """Cherry-pick failing with an unexpected exit code must report Git's own
    error message instead of raising an opaque NotImplementedError."""
    wd = unpackRepo(tempDir)
    shell("git switch no-parent", wd)

    # Dirty a file that the cherry-pick would overwrite: git bails out with rc 128.
    writeFile(f"{wd}/a/a1.txt", "local uncommitted changes\n")

    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    acceptQMessageBox(rw, "do you want to apply.+changes from.+ac7e7e4")

    qmb = findQMessageBox(rw, "would be overwritten")
    qmb.accept()
    assert rw.repo.state() == RepositoryState.NONE


def testAbortCherrypick(tempDir, mainWindow):
    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    wd = unpackRepo(tempDir)
    shell("git switch no-parent", wd)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    acceptQMessageBox(rw, "do you want to apply.+changes from.+ac7e7e4")

    assert rw.diffArea.fileStackPage() == "workdir"
    assert rw.repo.status() == {"a/a1.txt": FileStatus.INDEX_NEW}
    assert rw.repo.state() == RepositoryState.CHERRYPICK
    assert "First a/a1" in rw.repoModel.prefs.draftCommitMessage
    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, r"cherry.+commit to conclude")
    assert "abort" in rw.mergeBanner.buttons[-1].text().lower()

    # Abort cherrypick
    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "abort.+cherry.+a/a1")

    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.status() == {}
    assert rw.repoModel.prefs.draftCommitMessage == ""


def testNewTag(tempDir, mainWindow):
    newTag = "cool-tag"

    wd = unpackRepo(tempDir)

    # Nuke remotes for coverage of the no-remote code path.
    # (See also testPushTagOnCreate)
    shell("git remote remove origin", wd)

    rw = mainWindow.openRepo(wd)
    assert newTag not in rw.repo.listall_tags()

    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "tag this commit")

    dlg: NewTagDialog = findQDialog(rw, "new tag")
    QTest.keyClicks(dlg.ui.nameEdit, newTag)
    assert dlg.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dlg.accept()

    assert newTag in rw.repo.listall_tags()


def testForceNewTag(tempDir, mainWindow):
    firstCommit = "2c349335b7f797072cf729c4f3bb0914ecb6dec9"  # "First a/a2"
    secondCommit = "ac7e7e44c1885efb472ad54a78327d66bfc4ecef"  # "First a/a1"
    newTag = "cool-tag"

    wd = unpackRepo(tempDir)

    # Nuke remotes for coverage of the no-remote code path.
    # (See also testPushTagOnCreate)
    shell(f"""
        git remote remove origin
        git tag {newTag} {firstCommit}
    """, wd)

    rw = mainWindow.openRepo(wd)
    assert newTag in rw.repo.listall_tags()
    assert rw.repo.commit_id_from_tag_name(newTag) == Oid(hex=firstCommit)

    secondOid = Oid(hex=secondCommit)

    rw.jump(NavLocator.inCommit(secondOid))
    triggerContextMenuAction(rw.graphView.viewport(), "tag this commit")

    dlg: NewTagDialog = findQDialog(rw, "new tag")
    okButton = dlg.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    # 'Replace' checkbox disabled until it's needed
    assert not dlg.ui.forceCheckBox.isEnabled()

    # Type in a tag name that already exists
    dlg.ui.nameEdit.setText(newTag)

    assert not okButton.isEnabled()  # disabled b/c tag name is duplicated
    assert dlg.ui.forceCheckBox.isEnabled()
    dlg.ui.forceCheckBox.setChecked(True)

    assert okButton.isEnabled()
    dlg.accept()

    assert rw.repo.commit_id_from_tag_name(newTag) == secondOid


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteTag(tempDir, mainWindow, method):
    tagToDelete = "annotated_tag"

    wd = unpackRepo(tempDir)

    # Nuke remotes for coverage of the no-remote code path.
    # (See also testPushDeleteTag)
    shell("git remote remove origin", wd)

    rw = mainWindow.openRepo(wd)
    assert tagToDelete in rw.repo.listall_tags()
    node = rw.sidebar.findNodeByRef(f"refs/tags/{tagToDelete}")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "delete")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    else:
        raise NotImplementedError(f"unknown method {method}")

    findQDialog(rw, "delete tag").accept()
    assert tagToDelete not in rw.repo.listall_tags()


def testSignOffAddsSignedOffByLine(tempDir, mainWindow):
    # Stage a change and open the commit dialog
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/signed.txt", "signed change\n")
    rw = mainWindow.openRepo(wd)
    qlvClickNthRow(rw.dirtyFiles, 0)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)
    rw.diffArea.commitButton.click()

    # Create a commit with sign-off
    dialog = findQDialog(rw, "commit", t=CommitDialog)
    dialog.ui.summaryEditor.setText("Commit with sign-off")

    signoffAction: QAction = dialog.ui.signoffButton.actions()[0]
    assert findTextInWidget(signoffAction, "Signed-off-by")
    assert not signoffAction.isChecked()
    signoffAction.trigger()
    assert signoffAction.isChecked()

    dialog.accept()

    # Commit should have a Signed-off-by line
    headCommit = rw.repo.head_commit
    assert "Signed-off-by:" in headCommit.message


@pytest.mark.parametrize("hookName", [".git/hooks/pre-commit", ".git/hooks/commit-msg"])
def testBypassCommitHooks(tempDir, mainWindow, hookName):
    wd = unpackRepo(tempDir)

    shell(f"""
        echo "#!/usr/bin/env bash\necho 'hello from hook'\nexit 1" > {hookName}
        chmod +x {hookName}
        echo whatever >> master.txt
        git add master.txt
    """, wd)

    rw = mainWindow.openRepo(wd)

    # Attempt to create a commit, but don't bypass the hooks (enabled by default)
    rw.diffArea.commitButton.click()
    dialog = findQDialog(rw, "commit", t=CommitDialog)
    dialog.ui.summaryEditor.setText("bypass commit hooks")
    assert dialog.ui.hookButton.isVisible()
    assert re.search(r"hook.+will run", dialog.ui.hookButton.toolTip(), re.IGNORECASE)
    dialog.accept()
    acceptQMessageBox(rw, "git.+exited with code 1.+hello from hook")

    # Create a commit, bypass the hooks
    rw.diffArea.commitButton.click()
    dialog = findQDialog(rw, "commit", t=CommitDialog)
    assert dialog.ui.hookButton.isVisible()
    action = dialog.ui.hookButton.actions()[0]
    action.trigger()
    assert re.search(r"bypassing.+hook", dialog.ui.hookButton.toolTip(), re.IGNORECASE)
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert "bypass commit hooks" in headCommit.message


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "sidebardclick"])
def testCheckoutTag(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    repo = rw.repo

    node = sb.findNodeByRef("refs/tags/annotated_tag")
    if method == "sidebarmenu":
        menu = sb.makeNodeMenu(node)
        triggerMenuAction(menu, "check out")
    elif method == "sidebarkey":
        sb.setFocus()
        sb.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
    elif method == "sidebardclick":
        index = sb.nodeToFilterIndex(node)
        rect = sb.visualRect(index)
        QTest.mouseDClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topLeft())
    else:
        raise NotImplementedError(f"unknown method {method}")

    checkoutDialog: CheckoutCommitDialog = findQDialog(rw, "check.?out commit")
    checkoutDialog.ui.detachHeadRadioButton.setChecked(True)
    checkoutDialog.accept()

    oid = Oid(hex="c070ad8c08840c8116da865b2d65593a6bb9cd2a")
    assert repo.head_is_detached
    assert repo.head_commit_id == oid
    assert rw.graphView.currentCommitId == oid
