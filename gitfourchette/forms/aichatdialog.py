"""Commit-scoped chat backed by an installed Codex or Claude CLI."""

import json
import os
import signal
import re
from datetime import datetime, timedelta
from pathlib import Path

from gitfourchette import settings
from gitfourchette.exttools.aichat import availableProviders, configuredModel, modelChoices, cliArguments, ResponseStream, makePrompt, makeWorktreePrompt
from gitfourchette.exttools.aichat import PRESETS
from gitfourchette.exttools.aireviewcontext import projectGuidance
from gitfourchette.localization import _, _n
from gitfourchette.qt import *
from gitfourchette.toolbox import makeWidgetShortcut
from gitfourchette.webhost import WebHost


class AiChatDialog(QDialog):
    ContextLimit = 180_000

    def __init__(self, repo, commits, parent=None, branch="", worktreePaths=None, changeRequest=None):
        super().__init__(parent)
        self.setWindowTitle(_("Ask AI"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(850, 680)
        self.repoPath = repo.workdir or repo.path
        self.repo = repo
        self.branch = branch
        self.worktreePaths = list(dict.fromkeys(worktreePaths or []))
        self.changeRequest = changeRequest
        self.branchRange = None
        self.guidance = ""
        self.guidanceSources = []
        self.guidanceOmitted = []
        self.selectedCommits = [str(oid) for oid in commits]
        self.initialActivityAuthor = repo[commits[0]].author.email if commits else ""
        self.scopeDescription = ""
        self.commits = [str(oid) for oid in commits]
        self.providers = availableProviders()
        self.messages = []
        self.context = None
        self.process = None
        self.buffer = b""
        self.stderr = b""
        self.contextBytes = b""
        self.contextTruncated = False
        self.stopped = False
        self.stream = None

        layout = QVBoxLayout(self)
        self.scopeCombo = QComboBox()
        self.scopeCombo.addItems([_("Selected commits"), _("Developer activity")])
        if branch:
            self.scopeCombo.addItem(_("Branch review"))
        layout.addWidget(self.scopeCombo)
        self.branchControls = QWidget()
        branchLayout = QHBoxLayout(self.branchControls)
        branchLayout.setContentsMargins(0, 0, 0, 0)
        branchLabel = QLabel(_("Review {0} against", branch.removeprefix("refs/heads/").removeprefix("refs/remotes/")))
        branchLabel.setWordWrap(True)
        branchLayout.addWidget(branchLabel)
        self.baseCombo = QComboBox()
        for ref in sorted(repo.references):
            if ref.startswith(("refs/heads/", "refs/remotes/")) and ref != branch and not ref.endswith("/HEAD"):
                self.baseCombo.addItem(ref.removeprefix("refs/heads/").removeprefix("refs/remotes/"), ref)
        for preferredBase in ("develop", "main", "master", "origin/develop", "origin/main", "origin/master"):
            index = self.baseCombo.findText(preferredBase)
            if index >= 0:
                self.baseCombo.setCurrentIndex(index)
                break
        branchLayout.addWidget(self.baseCombo, 1)
        self.loadBranchButton = QPushButton(_("Load branch"))
        self.loadBranchButton.setAutoDefault(False)
        self.loadBranchButton.clicked.connect(self.loadBranch)
        branchLayout.addWidget(self.loadBranchButton)
        layout.addWidget(self.branchControls)
        self.branchControls.hide()
        self.activityControls = QWidget()
        activityLayout = QHBoxLayout(self.activityControls)
        activityLayout.setContentsMargins(0, 0, 0, 0)
        self.authorCombo = QComboBox()
        self.authorCombo.setEditable(True)
        self.authorCombo.setMinimumWidth(260)
        self.authorCombo.setPlaceholderText(_("Developer name or email"))
        activityLayout.addWidget(self.authorCombo, 1)
        activityLayout.addWidget(QLabel(_("Last")))
        self.daysSpin = QSpinBox()
        self.daysSpin.setRange(1, 3650)
        self.daysSpin.setValue(2)
        self.daysSpin.setSuffix(_(" days"))
        activityLayout.addWidget(self.daysSpin)
        self.loadCommitsButton = QPushButton(_("Load commits"))
        self.loadCommitsButton.setAutoDefault(False)
        self.loadCommitsButton.clicked.connect(self.loadActivity)
        activityLayout.addWidget(self.loadCommitsButton)
        layout.addWidget(self.activityControls)
        self.activityControls.hide()
        self.scopeHint = QLabel(_("Changing scope starts a new chat."))
        self.scopeHint.setWordWrap(True)
        layout.addWidget(self.scopeHint)
        if self.worktreePaths:
            self.scopeCombo.hide()
            self.scopeHint.setText(_("Discussing selected staged and unstaged changes."))
            self.branchControls.hide()
            self.activityControls.hide()
        title = self.selectionLabel = QLabel(
            _n("{n} selected file", "{n} selected files", len(self.worktreePaths)) if self.worktreePaths
            else _n("{n} selected commit", "{n} selected commits", len(commits)))
        title.setToolTip("\n".join(self.worktreePaths or self.commits))
        layout.addWidget(title)
        self.commitList = QPlainTextEdit()
        self.commitList.setReadOnly(True)
        self.commitList.setMaximumHeight(85)
        self.commitList.setPlainText("\n".join(self.worktreePaths) if self.worktreePaths else "\n".join(
            f"{str(oid)[:10]}  " + (repo[oid].message or "").partition("\n")[0] for oid in commits))
        layout.addWidget(self.commitList)

        controls = QHBoxLayout()
        controls.addWidget(QLabel(_("Assistant:")))
        self.providerCombo = QComboBox()
        for provider in self.providers:
            self.providerCombo.addItem(provider.capitalize(), provider)
        preferred = self.providerCombo.findData(settings.history.aiProvider)
        if preferred >= 0:
            self.providerCombo.setCurrentIndex(preferred)
        controls.addWidget(self.providerCombo)
        controls.addWidget(QLabel(_("Model:")))
        self.modelCombo = QComboBox()
        self.modelCombo.setEditable(True)
        self.modelCombo.setMinimumWidth(220)
        controls.addWidget(self.modelCombo, 1)
        layout.addLayout(controls)
        self.modelLabel = QLabel()
        layout.addWidget(self.modelLabel)
        reviewOptions = QHBoxLayout()
        reviewOptions.addWidget(QLabel(_("Response language:")))
        self.languageCombo = QComboBox()
        self.languageCombo.setEditable(True)
        self.languageCombo.addItems(["Română", "English", "Русский", "Українська", "Deutsch", "Français", "Español"])
        self.languageCombo.setCurrentText(settings.history.aiLanguage)
        reviewOptions.addWidget(self.languageCombo)
        self.rulesCheck = QCheckBox(_("Include project rules and skills"))
        self.rulesCheck.setChecked(True)
        reviewOptions.addWidget(self.rulesCheck)
        self.rulesButton = QPushButton(_("View rules"))
        self.rulesButton.setAutoDefault(False)
        self.rulesButton.clicked.connect(self.showGuidance)
        reviewOptions.addWidget(self.rulesButton)
        layout.addLayout(reviewOptions)

        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        layout.addWidget(self.chat, 1)
        presets = QHBoxLayout()
        self.presetButtons = []
        for command, (caption, prompt) in PRESETS.items():
            button = QPushButton(_(caption))
            button.setAutoDefault(False)
            button.setToolTip(f"/{command}\n" + _(prompt))
            button.clicked.connect(lambda checked=False, key=command: self.usePreset(key))
            presets.addWidget(button)
            self.presetButtons.append(button)
        layout.addLayout(presets)
        self.input = QPlainTextEdit()
        self.input.setMaximumHeight(110)
        self.input.setPlaceholderText(
            _("Ask about these changes…  /model to choose a model. Ctrl+Enter to send.") if self.worktreePaths
            else _("Ask about these commits…  /model to choose a model. Ctrl+Enter to send."))
        layout.addWidget(self.input)
        buttons = QHBoxLayout()
        self.status = QLabel(_("Ready"))
        buttons.addWidget(self.status, 1)
        self.stopButton = QPushButton(_("Stop"))
        self.stopButton.setEnabled(False)
        self.stopButton.clicked.connect(self.stop)
        buttons.addWidget(self.stopButton)
        if self.changeRequest:
            remoteUrl, sourceBranch = self.changeRequest
            _url, hostName = WebHost.makeChangeRequestLink(remoteUrl, sourceBranch)
            self.changeRequestButton = QPushButton(
                _("Open Pull Request") if hostName == "GitHub" else _("Open Merge Request"))
            self.changeRequestButton.setAutoDefault(False)
            self.changeRequestButton.clicked.connect(self.openChangeRequest)
            buttons.addWidget(self.changeRequestButton)
        self.sendButton = QPushButton(_("Send"))
        self.sendButton.setAutoDefault(False)
        self.sendButton.clicked.connect(self.send)
        buttons.addWidget(self.sendButton)
        layout.addLayout(buttons)
        self.providerCombo.currentIndexChanged.connect(self.loadModels)
        self.modelCombo.currentTextChanged.connect(self.modelChanged)
        makeWidgetShortcut(self, self.send, "Ctrl+Return", "Ctrl+Enter")
        self.loadModels()
        self.sendButton.setEnabled(bool(self.providers))
        if not self.providers:
            self.status.setText(_("Install Codex CLI or Claude Code to use Ask AI."))
        self.input.setFocus()
        self.scopeCombo.currentIndexChanged.connect(self.scopeChanged)
        self.authorCombo.currentTextChanged.connect(self.invalidateActivity)
        self.daysSpin.valueChanged.connect(self.invalidateActivity)
        self.baseCombo.currentIndexChanged.connect(self.invalidateBranch)
        if branch:
            self.scopeCombo.setCurrentIndex(2)

    def openChangeRequest(self):
        remoteUrl, sourceBranch = self.changeRequest
        answer = next((m["content"].strip() for m in reversed(self.messages)
                       if m["role"] == "assistant" and m["content"].strip()), "")
        title, separator, body = answer.partition("\n")
        if not separator:
            body = ""
        url, _hostName = WebHost.makeChangeRequestLink(remoteUrl, sourceBranch, title, body.strip())
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def usePreset(self, command):
        self.input.setPlainText(_(PRESETS[command][1]))
        self.input.setFocus()

    def resetScope(self, commits, description=""):
        self.commits = list(commits)
        self.scopeDescription = description
        self.guidance = ""
        self.guidanceSources = []
        self.guidanceOmitted = []
        self.rulesButton.setText(_("View rules"))
        self.rulesButton.setToolTip("")
        self.context = None
        self.contextTruncated = False
        self.messages.clear()
        self.render()
        self.selectionLabel.setText(_n("{n} selected commit", "{n} selected commits", len(self.commits)))
        self.selectionLabel.setToolTip("\n".join(self.commits))
        self.commitList.setPlainText("\n".join(
            f"{sha[:10]}  " + (self.repo[sha].message or "").partition("\n")[0] for sha in self.commits))
        self.setBusy(False)

    def scopeChanged(self):
        activity = self.scopeCombo.currentIndex() == 1
        reviewingBranch = self.scopeCombo.currentIndex() == 2
        self.branchControls.setVisible(reviewingBranch)
        self.branchRange = None
        self.activityControls.setVisible(activity)
        self.scopeHint.setText(_("All local and remote-tracking branches · commit date · changing filters starts a new chat.")
                               if activity else _("Changing scope starts a new chat."))
        self.resetScope([] if activity or reviewingBranch else self.selectedCommits)
        if reviewingBranch:
            self.loadBranch()
            return
        self.status.setText(_("Choose a developer and load commits.") if activity else _("Ready"))
        if activity and self.authorCombo.count() == 0:
            self.setBusy(True)
            self.stopped = False
            self.startProcess("git", ["shortlog", "-sne", "--all", "HEAD"], "authors")

    def invalidateBranch(self):
        if self.scopeCombo.currentIndex() == 2 and self.process is None:
            self.branchRange = None
            self.resetScope([])
            self.status.setText(_("Load the branch to apply this comparison."))

    def loadBranch(self):
        if self.process is not None:
            return
        self.branchRange = None
        self.resetScope([])
        base = self.baseCombo.currentData()
        if not base:
            self.status.setText(_("A different base branch is required for review."))
            return
        try:
            target = self.repo.references[self.branch].peel().id
            baseTip = self.repo.references[base].peel().id
            ancestor = self.repo.merge_base(baseTip, target)
        except (KeyError, ValueError) as error:
            self.status.setText(str(error))
            return
        if ancestor is None:
            self.status.setText(_("These branches have no common ancestor."))
            return
        self.branchRange = (str(ancestor), str(target))
        self.branchDescription = f"Review branch {self.branch} against {base}. Base tip: {baseTip}. Merge base: {ancestor}. Target: {target}. Review the aggregate diff from merge base to target, not unrelated base-branch changes."
        self.scopeHint.setText(_("{0} → {1} · changes since their common ancestor", self.baseCombo.currentText(), self.branch.removeprefix("refs/heads/").removeprefix("refs/remotes/")))
        self.stopped = False
        self.setBusy(True)
        self.status.setText(_("Loading branch changes…"))
        self.startProcess("git", ["rev-list", "--reverse", f"{baseTip}..{target}", "--"], "branch")

    def prepareGuidance(self):
        paths = set()
        revision = self.branchRange[1] if self.branchRange else self.commits[0] if self.commits else "HEAD"
        if self.worktreePaths:
            paths.update(self.worktreePaths)
        elif self.branchRange:
            diffs = [self.repo[self.branchRange[0]].tree.diff_to_tree(self.repo[revision].tree)]
        else:
            diffs = []
            for sha in self.commits:
                commit = self.repo[sha]
                diffs.append(commit.parents[0].tree.diff_to_tree(commit.tree) if commit.parents else commit.tree.diff_to_tree())
        for diff in diffs:
            for delta in diff.deltas:
                paths.update(path for path in (delta.old_file.path, delta.new_file.path) if path)
        self.guidance, self.guidanceSources, self.guidanceOmitted = projectGuidance(self.repo, revision, paths)
        self.rulesButton.setText(_("View rules ({0})", len(self.guidanceSources)))
        if self.guidanceOmitted:
            self.rulesButton.setText(_("Rules: {0} included, {1} omitted", len(self.guidanceSources), len(self.guidanceOmitted)))
        self.rulesButton.setToolTip("\n".join([*self.guidanceSources, *self.guidanceOmitted]))

    def showGuidance(self):
        if self.process is not None or not self.commits:
            return
        self.prepareGuidance()
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Project rules and skills"))
        dialog.resize(750, 550)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText((self.guidance or _("No project guidance found."))
                          + ("\n\nOmitted:\n" + "\n".join(self.guidanceOmitted) if self.guidanceOmitted else ""))
        layout.addWidget(text)
        dialog.open()

    def invalidateActivity(self):
        if self.scopeCombo.currentIndex() == 1 and self.process is None:
            self.resetScope([])
            self.status.setText(_("Load commits to apply these filters."))

    def loadActivity(self):
        if self.process is not None:
            return
        author = self.authorCombo.currentText().strip()
        if not author:
            self.status.setText(_("Enter a developer name or email."))
            return
        self.resetScope([])
        now = datetime.now().astimezone()
        since = now - timedelta(days=self.daysSpin.value())
        self.activityAuthor = author
        self.activityEmail = (self.authorCombo.currentData() or "") if author == self.authorCombo.itemText(self.authorCombo.currentIndex()) else ""
        self.activityDescription = f"Developer: {author}. Commit dates from {since.isoformat()} to {now.isoformat()}. All local refs; no fetch performed."
        self.stopped = False
        self.setBusy(True)
        self.status.setText(_("Finding developer commits…"))
        self.startProcess("git", ["log", "--all", "HEAD", "--since-as-filter=" + since.isoformat(),
                                  "--until=" + now.isoformat(), "--format=%H%x00%aN%x00%aE"], "activity")

    def finishScopeQuery(self, phase):
        output = self.buffer.decode("utf-8", errors="replace")
        if phase == "authors":
            self.authorCombo.blockSignals(True)
            for line in output.splitlines():
                match = re.match(r"\s*\d+\s+(.+) <([^<>]*)>$", line)
                if match:
                    name, email = match.groups()
                    self.authorCombo.addItem(f"{name} <{email}>", email)
            initial = self.authorCombo.findData(self.initialActivityAuthor)
            if initial >= 0:
                self.authorCombo.setCurrentIndex(initial)
            self.authorCombo.blockSignals(False)
            self.status.setText(_("Choose a developer and load commits."))
        else:
            commits = []
            for line in output.splitlines():
                fields = line.split("\0")
                if len(fields) != 3:
                    continue
                sha, name, email = fields
                matches = (email.casefold() == self.activityEmail.casefold() if self.activityEmail
                           else self.activityAuthor.casefold() in f"{name} <{email}>".casefold())
                if matches:
                    commits.append(sha)
            self.resetScope(list(dict.fromkeys(commits)), self.activityDescription)
            self.scopeHint.setText(self.activityDescription)
            self.status.setText(_("Ready") if commits else _("No commits found for this developer and period."))
        self.setBusy(False)

    def provider(self):
        return self.providerCombo.currentData() or ""

    def model(self):
        value = self.modelCombo.currentText().strip()
        return "" if value == self.modelCombo.itemText(0) else value

    def loadModels(self):
        provider = self.provider()
        default = configuredModel(provider) if provider else ""
        self.modelCombo.blockSignals(True)
        self.modelCombo.clear()
        self.modelCombo.addItem(_("CLI default") + (f" ({default})" if default else ""))
        self.modelCombo.addItems(modelChoices(provider))
        saved = settings.history.aiModels.get(provider, "")
        if saved:
            if self.modelCombo.findText(saved) < 0:
                self.modelCombo.addItem(saved)
            self.modelCombo.setCurrentText(saved)
        self.modelCombo.blockSignals(False)
        self.modelChanged()

    def modelChanged(self):
        self.modelLabel.setText(_("Using {0} · {1}", self.provider().capitalize(), self.modelCombo.currentText()))

    def render(self):
        text = []
        for message in self.messages:
            role = _("You") if message["role"] == "user" else _("Assistant")
            text.append(f"### {role}\n\n{message['content']}")
        self.chat.setMarkdown("\n\n---\n\n".join(text))
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def setBusy(self, busy):
        self.sendButton.setEnabled(not busy and bool(self.providers) and bool(self.commits or self.worktreePaths))
        self.stopButton.setEnabled(busy)
        self.providerCombo.setEnabled(not busy)
        self.modelCombo.setEnabled(not busy)
        self.scopeCombo.setEnabled(not busy)
        self.activityControls.setEnabled(not busy)
        self.branchControls.setEnabled(not busy)
        self.languageCombo.setEnabled(not busy)
        self.rulesCheck.setEnabled(not busy)
        self.rulesButton.setEnabled(not busy and bool(self.commits or self.worktreePaths))
        for button in self.presetButtons:
            button.setEnabled(not busy)

    def send(self):
        if self.process is not None or not self.providers:
            return
        question = self.input.toPlainText().strip()
        if not question:
            return
        if question == "/model" or question.startswith("/model "):
            value = question.removeprefix("/model").strip()
            if value == "default":
                self.modelCombo.setCurrentIndex(0)
            elif value:
                self.modelCombo.setEditText(value)
            else:
                self.modelCombo.setFocus()
                self.modelCombo.showPopup()
            self.input.clear()
            return
        command = question.split(maxsplit=1)[0].removeprefix("/")
        if question.startswith("/") and command in PRESETS:
            extra = question.partition(" ")[2]
            question = _(PRESETS[command][1]) + ("\n\n" + extra if extra else "")
        if not self.commits and not self.worktreePaths:
            self.status.setText(_("Load commits before sending a question."))
            return
        settings.history.aiProvider = self.provider()
        settings.history.aiLanguage = self.languageCombo.currentText().strip()
        settings.history.aiModels = {**settings.history.aiModels, self.provider(): self.model()}
        settings.history.setDirty()
        self.messages.append({"role": "user", "content": question})
        self.messages.append({"role": "assistant", "content": ""})
        self.input.clear()
        self.render()
        self.stopped = False
        if self.rulesCheck.isChecked():
            self.prepareGuidance()
        self.setBusy(True)
        if self.context is None:
            self.status.setText(_("Reading selected commits…"))
            self.contextBytes = b""
            self.contextTruncated = False
            if self.worktreePaths:
                self.startProcess("git", ["--no-pager", "diff", "HEAD", "--no-ext-diff", "--no-textconv",
                                          "--stat", "--patch", "--", *self.worktreePaths], "context")
            elif self.branchRange:
                self.startProcess("git", ["--no-pager", "diff", "--no-ext-diff", "--no-textconv", "--stat", "--patch",
                                          *self.branchRange, "--"], "context")
            else:
                self.startProcess("git", ["--no-pager", "show", "--no-ext-diff", "--no-textconv",
                                      "--format=fuller", "--stat", "--patch", "--root",
                                      "--diff-merges=first-parent", *self.commits, "--"], "context")
        else:
            self.startAssistant()

    def startAssistant(self):
        self.stream = ResponseStream(self.provider())
        self.status.setText(_("Waiting for {0}…", self.provider().capitalize()))
        context = (self.scopeDescription + "\n\n" if self.scopeDescription else "") + self.context
        if self.branchRange:
            summaries = "\n".join(f"{sha} {self.repo[sha].author.name}: " + (self.repo[sha].message or "").partition("\n")[0]
                                  for sha in self.commits)
            context = "Branch commits:\n" + summaries + "\n\n" + context
        guidance = self.guidance if self.rulesCheck.isChecked() else "Project guidance disabled by user."
        if self.rulesCheck.isChecked() and self.guidanceOmitted:
            guidance += "\n\nGuidance omitted due to limits; do not claim full rule compliance:\n" + "\n".join(self.guidanceOmitted)
        if self.worktreePaths:
            prompt = makeWorktreePrompt(
                self.worktreePaths, context, self.messages[:-1], self.languageCombo.currentText().strip(), guidance)
        else:
            prompt = makePrompt(
                self.commits, context, self.messages[:-1], self.languageCombo.currentText().strip(), guidance)
        self.startProcess(self.providers[self.provider()], cliArguments(self.provider(), self.model()), "assistant", prompt)

    def startProcess(self, program, args, phase, prompt=""):
        self.phase = phase
        self.buffer = b""
        self.stderr = b""
        process = QProcess(self)
        self.process = process
        self.processGroup = hasattr(QProcess, "UnixProcessParameters")
        if self.processGroup:
            parameters = QProcess.UnixProcessParameters()
            parameters.flags = QProcess.UnixProcessFlag.CreateNewSession
            process.setUnixProcessParameters(parameters)
        process.setWorkingDirectory(self.repoPath)
        process.readyReadStandardOutput.connect(self.readOutput)
        process.readyReadStandardError.connect(self.readError)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.processError)
        if prompt:
            process.started.connect(lambda: (process.write(prompt.encode("utf-8")), process.closeWriteChannel()))
        process.start(program, args)

    def readError(self):
        if self.process:
            self.stderr = (self.stderr + bytes(self.process.readAllStandardError()))[-16000:]

    def readOutput(self):
        if not self.process:
            return
        data = bytes(self.process.readAllStandardOutput())
        if self.phase in ("authors", "activity", "branch"):
            self.buffer += data
            return
        if self.phase == "context":
            remaining = self.ContextLimit - len(self.contextBytes)
            self.contextBytes += data[:remaining]
            self.contextTruncated |= len(data) > remaining
            return
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.consumeLine(line)

    def consumeLine(self, line):
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                return
            self.stream.consume(event)
        except (ValueError, TypeError, AttributeError):
            return
        self.messages[-1]["content"] = self.stream.text
        if self.stream.model:
            self.modelLabel.setText(_("Using {0} · {1}", self.provider().capitalize(), self.stream.model))
        self.status.setText(_("Responding…") if self.stream.text else _("Analyzing commits…"))
        self.render()

    def processError(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.process:
            self.fail(self.process.errorString())

    def finished(self, code, exitStatus):
        if not self.process:
            return
        self.readOutput()
        self.readError()
        phase = self.phase
        if phase == "assistant" and self.buffer.strip():
            self.consumeLine(self.buffer)
        self.process.deleteLater()
        self.process = None
        if self.stopped:
            self.fail(_("Stopped."))
        elif code != 0 or exitStatus == QProcess.ExitStatus.CrashExit:
            error = self.stream.error if phase == "assistant" else ""
            self.fail(error or self.stderr.decode("utf-8", errors="replace") or _("CLI exited with code {0}.", code))
        elif phase in ("authors", "activity"):
            self.finishScopeQuery(phase)
        elif phase == "branch":
            commits = self.buffer.decode().splitlines()
            self.resetScope(commits, self.branchDescription)
            self.status.setText(_("Ready") if commits else _("No branch commits to review against this base."))
            if commits:
                self.prepareGuidance()
        elif phase == "context":
            self.context = self.contextBytes.decode("utf-8", errors="replace")
            if self.worktreePaths and self.repo.workdir:
                root = Path(self.repo.workdir).resolve()
                for path in self.worktreePaths:
                    # Plain `git diff HEAD` does not include untracked files.
                    if f"a/{path}" in self.context or f"b/{path}" in self.context:
                        continue
                    candidate = root / path
                    try:
                        if candidate.is_file() and candidate.resolve().is_relative_to(root):
                            remaining = self.ContextLimit - len(self.context.encode("utf-8"))
                            data = candidate.read_bytes()[:max(0, remaining)]
                            self.context += f"\n\n--- Untracked file: {path} ---\n" + data.decode("utf-8", errors="replace")
                            self.contextTruncated |= candidate.stat().st_size > len(data)
                    except OSError:
                        self.context += f"\n\n[Could not read selected file: {path}]"
            if self.contextTruncated:
                self.context += "\n[Diff context truncated. Inspect the listed revisions for omitted changes.]"
            self.startAssistant()
        elif self.stream.error:
            self.fail(self.stream.error)
        elif not self.stream.text.strip():
            self.fail(_("The CLI returned no answer. Check its login and model configuration."))
        else:
            self.setBusy(False)
            self.status.setText(_("Ready · diff context truncated") if self.contextTruncated else _("Ready"))
            self.input.setFocus()

    def fail(self, message):
        if self.process:
            self.process.deleteLater()
            self.process = None
        if self.phase in ("authors", "activity", "branch"):
            self.setBusy(False)
            self.status.setText(_("Request interrupted: {0}", message))
            return
        self.messages[-1]["content"] += "\n\n" + _("Request interrupted: {0}", message)
        self.render()
        self.setBusy(False)
        self.status.setText(_("Stopped") if self.stopped else _("Request failed"))

    def stop(self):
        if self.process:
            self.stopped = True
            pid = self.process.processId()
            if self.processGroup and pid:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return
            self.process.kill()

    def done(self, result):
        if self.process:
            process = self.process
            self.stop()
            process.waitForFinished(1000)
        super().done(result)
