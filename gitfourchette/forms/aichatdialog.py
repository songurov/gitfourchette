"""Commit-scoped chat backed by an installed Codex or Claude CLI."""

import json
import os
import signal
import re
from datetime import datetime, timedelta
from contextlib import suppress
from pathlib import Path

from gitfourchette import settings
from gitfourchette.exttools.aichat import availableProviders, configuredModel, modelChoices, cliArguments, ResponseStream, makePrompt, makeWorktreePrompt
from gitfourchette.exttools.aichat import CHANGE_REQUEST_PROMPT, PRESETS, imageInstructions
from gitfourchette.exttools.aireviewcontext import projectGuidance
from gitfourchette.forms.chattranscript import answerHtml
from gitfourchette.forms.commitarea import CommitDescriptionEdit
from gitfourchette.localization import _, _n
from gitfourchette.qt import *
from gitfourchette.toolbox import (
    PersistentFileDialog, QElidedLabel, QFlowLayout, escape, makeWidgetShortcut, stockIcon)
from gitfourchette.webhost import WebHost


def roleLabel(role):
    """Who said it, in the reader's own language."""
    return _("You") if role == "user" else _("Assistant")


RULE = '<hr style="margin-top:14px; margin-bottom:14px;">'
"""
The divider between one turn and the next. Left to itself Qt draws it tight
against the paragraph above, where it reads as that paragraph's underline
rather than as a divider before the next question.
"""


def transcriptHtml(messages, roleLabel) -> str:
    """
    The whole conversation as one document: a rule between exchanges, the name
    of whoever speaks, then what they said. A question is quoted verbatim —
    Markdown typed into it belongs to the question, not to the document that
    quotes it — and an answer's code is set as code (see chattranscript).
    """
    blocks = []
    for index, message in enumerate(messages):
        content = message.get("content", "")
        if index:
            blocks.append(RULE)
        blocks.append(f"<p><b>{escape(roleLabel(message['role']))}</b></p>")
        if message["role"] == "user":
            quoted = "<br>".join(escape(line) for line in content.splitlines())
            blocks.append(f"<blockquote><p>{quoted}</p></blockquote>" if quoted else "")
        else:
            blocks.append(answerHtml(content))
    return "\n".join(block for block in blocks if block)


class ScopeList(CommitDescriptionEdit):
    """
    The commits, or the files, the chat is about. It is only as tall as the
    list it holds, up to three lines; past that it scrolls, so that picking
    twenty commits never pushes the conversation off the window.
    """

    MinLines = 1
    RestLines = 1
    MaxLines = 3

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setReadOnly(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)


class ChatInput(CommitDescriptionEdit):
    """
    The question box. Like the commit description it grows with what you type,
    but it starts at two lines and stops at six, so that a long question never
    eats the conversation above it. It keeps its frame: nothing else draws a
    box around it here.

    A screenshot pasted or dropped here becomes an attachment, the way it
    would in a terminal: imageDropped carries the file it was saved to.
    """

    imageDropped = Signal(str)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # override
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData):  # override
        if self._takeImages(source):
            return
        super().insertFromMimeData(source)

    def _takeImages(self, source: QMimeData) -> bool:
        """Save what was pasted or dropped, and say whether it was a picture."""
        took = False
        for url in source.urls():
            path = url.toLocalFile()
            if path and QImageReader(path).canRead():
                self.imageDropped.emit(path)
                took = True
        if took:
            return True
        if source.hasImage():
            image = QImage(source.imageData())
            if not image.isNull():
                file = QTemporaryFile(str(Path(qTempDir(), "pasted-XXXXXX.png")), self)
                file.setAutoRemove(False)
                file.open()
                file.close()
                if image.save(file.fileName(), "PNG"):
                    self.imageDropped.emit(file.fileName())
                    return True
        return False

    MinLines = 2
    RestLines = 2
    MaxLines = 6

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)


class TranscriptView(QTextBrowser):
    """
    The conversation, read as a document: the text column keeps to a
    comfortable measure however wide the window gets, one exchange is divided
    from the next, and it can be selected with the keyboard as well as the
    mouse.
    """

    Measure = 96
    "Widest line of prose, in characters, before the text column stops growing."

    Indent = 10
    "Space kept at the left of the column; anything over the measure goes to the right."

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.gutter = None

    def setHtml(self, html: str):
        super().setHtml(html)
        self.gutter = None
        self.applyMeasure()

    def resizeEvent(self, event: QResizeEvent):
        # Reflowing the text moves every line under the reader. Someone at the
        # foot of the conversation means to stay there — when Stop appears and
        # takes a row, or when the window is resized around them.
        bar = self.verticalScrollBar()
        atEnd = bar.value() >= bar.maximum() - bar.singleStep()
        super().resizeEvent(event)
        self.applyMeasure()
        if atEnd:
            bar.setValue(bar.maximum())

    def applyMeasure(self):
        """
        Inset the document's own margins rather than the viewport's, so that
        the text reflows to the measure instead of running off to the right —
        tables and code blocks included, since they sit in the same frame.
        """
        document = self.document()
        column = QFontMetricsF(document.defaultFont()).horizontalAdvance("x") * self.Measure
        gutter = max(0.0, self.viewport().width() - self.Indent - column)
        if self.gutter is not None and abs(self.gutter - gutter) < 1:
            return
        self.gutter = gutter

        frame = document.rootFrame()
        shape = frame.frameFormat()
        shape.setLeftMargin(self.Indent)
        shape.setRightMargin(gutter)
        frame.setFrameFormat(shape)


class ElapsedStatusLabel(QElidedLabel):
    """
    The status line, with a clock on it while the CLI is working: an answer
    can take minutes, and a line that only says "Responding…" doesn't tell
    you whether anything is happening. The last run's time stays on screen.
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.message = text
        self.elapsed = QElapsedTimer()
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self.refresh)

    def setText(self, text: str):  # override
        self.message = text
        self.refresh()

    def setClockRunning(self, running: bool):
        if running == self.clock.isActive():
            return
        if running:
            self.elapsed.start()
            self.clock.start()
        else:
            self.clock.stop()
        self.refresh()

    def refresh(self):
        seconds = self.elapsed.elapsed() // 1000 if self.elapsed.isValid() else 0
        if not seconds:
            super().setText(self.message)
            return
        clock = _("{0} s", seconds) if seconds < 60 else _("{0} min {1} s", seconds // 60, seconds % 60)
        if self.clock.isActive():
            super().setText(_("{0}  ({1})", self.message, clock))
        else:
            super().setText(_("{0}  (took {1})", self.message, clock))


class AiChatDialog(QDialog):
    ContextLimit = 180_000

    SetupWidth = 30
    "The header line's share of the width for the setup sentence, in M widths."

    SetupPadding = 8
    "Room a tool button keeps around its text, either side of it."

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
        self.scopeCaption = ""
        "What the chat is about, in the reader's own words, after the count in the header."
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
        layout.setSpacing(6)

        # The header says, on one line, what the chat is about and who answers
        # it. Everything that is set once lives behind the setup button, so
        # that the conversation starts at the top of the window.
        header = QHBoxLayout()
        header.setSpacing(6)
        self.scopeCombo = QComboBox()
        self.scopeCombo.addItems([_("Selected commits"), _("Developer activity")])
        if branch:
            self.scopeCombo.addItem(_("Branch review"))
        self.scopeCombo.setToolTip(_("Changing scope starts a new chat."))
        header.addWidget(self.scopeCombo)
        self.selectionLabel = QElidedLabel()
        header.addWidget(self.selectionLabel, 1)
        self.setupButton = QToolButton()
        self.setupButton.setCheckable(True)
        self.setupButton.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setupButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setupWidth = self.setupButton.fontMetrics().horizontalAdvance("M" * self.SetupWidth)
        self.setupButton.setMaximumWidth(self.setupWidth)
        header.addWidget(self.setupButton)
        layout.addLayout(header)

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
        if self.worktreePaths:
            self.scopeCombo.hide()
            self.scopeCaption = _("Uncommitted changes")
            self.branchControls.hide()
            self.activityControls.hide()
        self.commitList = ScopeList()
        layout.addWidget(self.commitList)

        # Set once, then forgotten: the header spells the choice out in words,
        # and this strip opens when someone wants to change it.
        self.setupStrip = QWidget()
        setupRow = QFlowLayout(self.setupStrip)
        setupRow.setContentsMargins(QMargins())
        setupRow.setSpacing(8)
        setupRow.addWidget(QLabel(_("Assistant:")))
        self.providerCombo = QComboBox()
        for provider in self.providers:
            self.providerCombo.addItem(provider.capitalize(), provider)
        preferred = self.providerCombo.findData(settings.history.aiProvider)
        if preferred >= 0:
            self.providerCombo.setCurrentIndex(preferred)
        setupRow.addWidget(self.providerCombo)
        setupRow.addWidget(QLabel(_("Model:")))
        self.modelCombo = QComboBox()
        self.modelCombo.setEditable(True)
        self.modelCombo.setMinimumWidth(220)
        setupRow.addWidget(self.modelCombo)
        setupRow.addWidget(QLabel(_("Response language:")))
        self.languageCombo = QComboBox()
        self.languageCombo.setEditable(True)
        self.languageCombo.addItems(["Română", "English", "Русский", "Українська", "Deutsch", "Français", "Español"])
        self.languageCombo.setCurrentText(settings.history.aiLanguage)
        setupRow.addWidget(self.languageCombo)
        self.rulesCheck = QCheckBox(_("Include project rules and skills"))
        self.rulesCheck.setChecked(True)
        setupRow.addWidget(self.rulesCheck)
        self.rulesButton = QPushButton(_("View rules"))
        self.rulesButton.setAutoDefault(False)
        self.rulesButton.clicked.connect(self.showGuidance)
        setupRow.addWidget(self.rulesButton)
        # Off unless asked for: the assistant reads, and only writes when told to
        self.editsCheck = QCheckBox(_("Let it change files"))
        self.editsCheck.setChecked(settings.history.aiAllowEdits)
        self.editsCheck.setToolTip(
            _("The assistant may edit files in the working directory when you ask it to. "
              "It never commits, stages or pushes: whatever it changes shows up as your "
              "uncommitted work, to keep or throw away."))
        setupRow.addWidget(self.editsCheck)
        layout.addWidget(self.setupStrip)

        self.chat = TranscriptView()
        layout.addWidget(self.chat, 1)

        # The questions two readers actually ask, each named after what it
        # gives back. A developer starts at the left; a CTO wanting a person's
        # week rather than a commit's diff ends at the right.
        presets = QFlowLayout()
        presets.setSpacing(6)
        self.presetButtons = []
        for command, (caption, prompt) in PRESETS.items():
            button = QPushButton(_(caption))
            button.setAutoDefault(False)
            button.setToolTip(f"/{command}\n" + _(prompt))
            button.clicked.connect(lambda checked=False, key=command: self.usePreset(key))
            presets.addWidget(button)
            self.presetButtons.append(button)
        self.activityButton = QPushButton(_("Developer's work…"))
        self.activityButton.setAutoDefault(False)
        self.activityButton.setToolTip(
            _("All local and remote-tracking branches · commit date · changing filters starts a new chat."))
        self.activityButton.clicked.connect(self.askAboutDeveloper)
        self.activityButton.setVisible(not self.worktreePaths)
        presets.addWidget(self.activityButton)
        presets.setAlignment(self.activityButton, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(presets)

        self.attachments: list[str] = []
        self.attachmentsRow = QWidget()
        self.attachmentsRow.setObjectName("AiChatAttachments")
        attachmentsLayout = QFlowLayout(self.attachmentsRow)
        attachmentsLayout.setContentsMargins(QMargins())
        attachmentsLayout.setSpacing(4)
        self.attachmentsRow.setVisible(False)
        layout.addWidget(self.attachmentsRow)

        self.input = ChatInput()
        self.input.setPlaceholderText(
            _("Ask about these changes…  /model to choose a model. Ctrl+Enter to send.") if self.worktreePaths
            else _("Ask about these commits…  /model to choose a model. Ctrl+Enter to send."))
        self.input.imageDropped.connect(self.attachImage)
        layout.addWidget(self.input)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.attachButton = QToolButton()
        self.attachButton.setIcon(stockIcon("attach-image"))
        self.attachButton.setAutoRaise(True)
        self.attachButton.setAccessibleName(_("Attach an image"))
        self.attachButton.setToolTip(
            _("Attach an image to your question — a screenshot of what went wrong, a diagram. "
              "You can also paste or drop one into the question."))
        self.attachButton.clicked.connect(self.chooseImages)
        buttons.addWidget(self.attachButton)
        self.status = ElapsedStatusLabel(_("Ready"))
        buttons.addWidget(self.status, 1)
        self.stopButton = QPushButton(_("Stop"))
        self.stopButton.setAutoDefault(False)
        self.stopButton.hide()
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
            self.input.setPlainText(_(CHANGE_REQUEST_PROMPT))
        self.sendButton = QPushButton(_("Send"))
        self.sendButton.setAutoDefault(False)
        # The one button the dialog exists for; the theme fills it with the accent.
        self.sendButton.setProperty("primary", True)
        self.sendButton.clicked.connect(self.send)
        buttons.addWidget(self.sendButton)
        layout.addLayout(buttons)
        self.providerCombo.currentIndexChanged.connect(self.loadModels)
        self.modelCombo.currentTextChanged.connect(self.modelChanged)
        self.languageCombo.currentTextChanged.connect(self.refreshSetup)
        self.rulesCheck.toggled.connect(self.refreshSetup)
        self.editsCheck.toggled.connect(self.editsToggled)
        self.setupButton.toggled.connect(self.showSetup)
        makeWidgetShortcut(self, self.send, "Ctrl+Return", "Ctrl+Enter")
        self.loadModels()
        self.showScope()
        self.setupButton.setChecked(settings.history.aiSetupExpanded)
        self.showSetup(self.setupButton.isChecked())
        self.sendButton.setEnabled(bool(self.providers))
        if not self.providers:
            self.setStatus(_("Install Codex CLI or Claude Code to use Ask AI."))
        self.input.setFocus()
        self.scopeCombo.currentIndexChanged.connect(self.scopeChanged)
        self.authorCombo.currentTextChanged.connect(self.invalidateActivity)
        self.daysSpin.valueChanged.connect(self.invalidateActivity)
        self.baseCombo.currentIndexChanged.connect(self.invalidateBranch)
        if branch:
            self.scopeCombo.setCurrentIndex(2)

    def setStatus(self, message, detail=""):
        """
        The one line at the bottom. It is elided, so a long complaint from git
        is kept whole under the pointer — and every message clears the one
        before it, tooltip included, so a failure never outlives the retry
        that put it right.
        """
        self.status.setText(message)
        self.status.setToolTip(detail)

    def showSetup(self, expanded):
        """Open or close the strip, and remember it: the choice outlives this chat."""
        self.setupStrip.setVisible(expanded)
        self.setupButton.setIcon(stockIcon("chevron-down" if expanded else "chevron-right"))
        if settings.history.aiSetupExpanded != expanded:
            settings.history.aiSetupExpanded = expanded
            settings.history.setDirty()

    def refreshSetup(self):
        """Say who answers, with what, in which language, as one line of prose."""
        # Once a CLI has answered, name the model it really used — but only
        # while the answer came from the assistant the header now names.
        answered = self.stream is not None and self.stream.provider == self.provider()
        model = self.stream.model if answered and self.stream.model else self.modelCombo.currentText()
        rest = [self.languageCombo.currentText().strip()]
        if self.editsCheck.isChecked():
            # The one thing here that lets the assistant touch your files:
            # it belongs in the header whether the strip is open or not
            rest.append(_("may change files"))
        if not self.rulesCheck.isChecked():
            rest.append(_("no project rules"))
        elif self.guidanceOmitted:
            # Rules that did not fit are the one thing here the reader has not
            # chosen, so the header carries it whether the strip is open or not
            rest.append(_n("{n} rule omitted", "{n} rules omitted", len(self.guidanceOmitted)))

        def say(name):
            return " · ".join(part for part in [self.provider().capitalize(), name, *rest] if part)

        sentence = say(model)
        # A vendor may name a model whatever it likes, so the header keeps a
        # fixed share of the line and takes what will not fit out of the name
        # rather than out of the words around it. The whole of the sentence
        # stays under the pointer.
        metrics = self.setupButton.fontMetrics()
        room = self.setupWidth - self.setupButton.iconSize().width() - 2 * self.SetupPadding
        shown = sentence
        if metrics.horizontalAdvance(shown) > room:
            spare = room - metrics.horizontalAdvance(say("") + " · ")
            shown = say(metrics.elidedText(model, Qt.TextElideMode.ElideMiddle, spare))
            if metrics.horizontalAdvance(shown) > room:
                shown = metrics.elidedText(sentence, Qt.TextElideMode.ElideMiddle, room)
        self.setupButton.setText(shown)
        # Cut down to its share of the line, the button takes exactly that
        # share: a longer name then moves nothing else along the header.
        self.setupButton.setMinimumWidth(self.setupWidth if shown != sentence else 0)
        self.setupButton.setToolTip(
            sentence + "\n" + _("Assistant, model, response language and project rules"))

    def scopeItems(self):
        """One line per commit or per file, for the list and for the header's tooltip."""
        if self.worktreePaths:
            return list(self.worktreePaths)
        return [f"{sha[:10]}  " + (self.repo[sha].message or "").partition("\n")[0] for sha in self.commits]

    def showScope(self):
        """
        Put what the chat is about on the header line: how much, then what.
        A single commit needs no list under it; several do, and the list is
        kept to three lines so the conversation keeps the room.
        """
        items = self.scopeItems()
        if self.worktreePaths:
            count = _n("{n} file", "{n} files", len(items))
        else:
            count = _n("{n} commit", "{n} commits", len(items))
        caption = self.scopeCaption or (items[0] if len(items) == 1 else "")
        self.selectionLabel.setText(" · ".join(part for part in (count, caption) if part))
        self.selectionLabel.setToolTip("\n".join(items))
        self.commitList.setPlainText("\n".join(items))
        self.commitList.setVisible(len(items) > 1)

    def askAboutDeveloper(self):
        """A CTO's question — what has this person been working on — in one click."""
        if self.scopeCombo.currentIndex() != 1:
            self.scopeCombo.setCurrentIndex(1)
        self.usePreset("summary")
        self.authorCombo.setFocus()

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

    def resetScope(self, commits, description="", caption=""):
        self.commits = list(commits)
        self.scopeDescription = description
        self.scopeCaption = caption
        self.guidance = ""
        self.guidanceSources = []
        self.guidanceOmitted = []
        self.rulesButton.setText(_("View rules"))
        self.rulesButton.setToolTip("")
        self.context = None
        self.contextTruncated = False
        self.messages.clear()
        self.render()
        self.showScope()
        self.refreshSetup()
        self.setBusy(False)

    def scopeChanged(self):
        activity = self.scopeCombo.currentIndex() == 1
        reviewingBranch = self.scopeCombo.currentIndex() == 2
        self.branchControls.setVisible(reviewingBranch)
        self.branchRange = None
        self.activityControls.setVisible(activity)
        # What the scope searches, and what leaving it costs, belongs on the
        # control that stays on screen for as long as the scope does.
        caveat = (_("All local and remote-tracking branches · commit date · changing filters starts a new chat.")
                  if activity else _("Changing scope starts a new chat."))
        self.scopeCombo.setToolTip(caveat)
        self.activityControls.setToolTip(caveat)
        self.resetScope([] if activity or reviewingBranch else self.selectedCommits)
        if reviewingBranch:
            self.loadBranch()
            return
        self.setStatus(_("Choose a developer and load commits.") if activity else _("Ready"))
        if activity and self.authorCombo.count() == 0:
            self.setBusy(True)
            self.stopped = False
            self.startProcess("git", ["shortlog", "-sne", "--all", "HEAD"], "authors")

    def invalidateBranch(self):
        if self.scopeCombo.currentIndex() == 2 and self.process is None:
            self.branchRange = None
            self.resetScope([])
            self.setStatus(_("Load the branch to apply this comparison."))

    def loadBranch(self):
        if self.process is not None:
            return
        self.branchRange = None
        self.resetScope([])
        base = self.baseCombo.currentData()
        if not base:
            self.setStatus(_("A different base branch is required for review."))
            return
        try:
            target = self.repo.references[self.branch].peel().id
            baseTip = self.repo.references[base].peel().id
            ancestor = self.repo.merge_base(baseTip, target)
        except (KeyError, ValueError) as error:
            self.setStatus(str(error))
            return
        if ancestor is None:
            self.setStatus(_("These branches have no common ancestor."))
            return
        self.branchRange = (str(ancestor), str(target))
        self.branchDescription = f"Review branch {self.branch} against {base}. Base tip: {baseTip}. Merge base: {ancestor}. Target: {target}. Review the aggregate diff from merge base to target, not unrelated base-branch changes."
        self.branchCaption = _("{0} → {1} · changes since their common ancestor", self.baseCombo.currentText(), self.branch.removeprefix("refs/heads/").removeprefix("refs/remotes/"))
        self.stopped = False
        self.setBusy(True)
        self.setStatus(_("Loading branch changes…"))
        self.startProcess("git", ["rev-list", "--reverse", f"{baseTip}..{target}", "--"], "branch")

    def prepareGuidance(self):
        paths = set()
        diffs = []
        # Uncommitted changes are compared against HEAD; look up its commit id,
        # since the repo's object lookup doesn't resolve reference names.
        revision = self.branchRange[1] if self.branchRange else self.commits[0] if self.commits else str(self.repo.head_commit_id)
        if self.worktreePaths:
            paths.update(self.worktreePaths)
        elif self.branchRange:
            diffs = [self.repo[self.branchRange[0]].tree.diff_to_tree(self.repo[revision].tree)]
        else:
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
        # That button is inside the strip, which is shut unless someone opened
        # it: the count of omitted rules has to reach the header line too.
        self.refreshSetup()

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
            self.setStatus(_("Load commits to apply these filters."))

    def loadActivity(self):
        if self.process is not None:
            return
        author = self.authorCombo.currentText().strip()
        if not author:
            self.setStatus(_("Enter a developer name or email."))
            return
        self.resetScope([])
        now = datetime.now().astimezone()
        since = now - timedelta(days=self.daysSpin.value())
        self.activityAuthor = author
        self.activityEmail = (self.authorCombo.currentData() or "") if author == self.authorCombo.itemText(self.authorCombo.currentIndex()) else ""
        self.activityDescription = f"Developer: {author}. Commit dates from {since.isoformat()} to {now.isoformat()}. All local refs; no fetch performed."
        # The prompt gets the timestamps; the header gets the filter in the
        # spin box's own words, so the two never say the period differently
        self.activityCaption = _("{0} · last {1}", author, self.daysSpin.text().strip())
        self.stopped = False
        self.setBusy(True)
        self.setStatus(_("Finding developer commits…"))
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
            self.setStatus(_("Choose a developer and load commits."))
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
            self.resetScope(list(dict.fromkeys(commits)), self.activityDescription, self.activityCaption)
            self.setStatus(_("Ready") if commits else _("No commits found for this developer and period."))
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
        self.refreshSetup()

    def render(self, toEnd=False):
        """
        Lay the exchange out as a document: a rule and a name before each turn,
        the question quoted under your name, then the answer in the assistant's
        own headings and lists.

        `toEnd` is for the moment a question is asked, when the end of the
        transcript is the whole point of the dialog; everything else respects
        where the reader left off.
        """
        bar = self.chat.verticalScrollBar()
        # Follow a streaming answer only from the end of it: someone reading
        # further up is not dragged back down by every word that arrives.
        following = toEnd or bar.value() >= bar.maximum() - bar.singleStep()
        place = bar.value()
        self.chat.setHtml(transcriptHtml(self.messages, roleLabel))
        bar.setValue(bar.maximum() if following else min(place, bar.maximum()))

    def setBusy(self, busy):
        self.status.setClockRunning(busy)
        self.sendButton.setEnabled(not busy and bool(self.providers) and bool(self.commits or self.worktreePaths))
        # Stop is not an option until there is something to stop
        self.stopButton.setVisible(busy)
        self.stopButton.setEnabled(busy)
        self.providerCombo.setEnabled(not busy)
        self.modelCombo.setEnabled(not busy)
        self.scopeCombo.setEnabled(not busy)
        self.activityControls.setEnabled(not busy)
        self.branchControls.setEnabled(not busy)
        self.languageCombo.setEnabled(not busy)
        self.rulesCheck.setEnabled(not busy)
        self.editsCheck.setEnabled(not busy)
        self.rulesButton.setEnabled(not busy and bool(self.commits or self.worktreePaths))
        self.activityButton.setEnabled(not busy)
        for button in self.presetButtons:
            button.setEnabled(not busy)

    def chooseImages(self):
        """Pick images from disk. The CLI reads them; we only pass the paths."""
        readable = " ".join("*." + bytes(fmt).decode() for fmt in QImageReader.supportedImageFormats())
        dialog = PersistentFileDialog.openFile(
            self, "AttachImage", _("Attach an image"), filter=_("Images") + f" ({readable})")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.filesSelected.connect(lambda paths: [self.attachImage(path) for path in paths])
        dialog.show()

    def attachImage(self, path: str):
        if path in self.attachments:
            return
        self.attachments.append(path)
        self.refreshAttachments()

    def removeAttachment(self, path: str):
        with suppress(ValueError):
            self.attachments.remove(path)
        self.refreshAttachments()

    def refreshAttachments(self):
        """One chip per image, each its own way out."""
        layout = self.attachmentsRow.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for path in self.attachments:
            chip = QPushButton(f"{Path(path).name}  \u00d7")
            chip.setObjectName("AiChatAttachmentChip")
            chip.setToolTip(_("{0} — click to leave it out", path))
            chip.setAutoDefault(False)
            chip.setIcon(stockIcon("attach-image"))
            chip.clicked.connect(lambda _checked=False, p=path: self.removeAttachment(p))
            layout.addWidget(chip)
        self.attachmentsRow.setVisible(bool(self.attachments))

    def editsToggled(self, allowed: bool):
        settings.history.aiAllowEdits = allowed
        settings.history.setDirty()
        self.refreshSetup()

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
                # The combo lives in the setup strip: open it before pointing at it
                self.setupButton.setChecked(True)
                self.modelCombo.setFocus()
                self.modelCombo.showPopup()
            self.input.clear()
            return
        command = question.split(maxsplit=1)[0].removeprefix("/")
        if question.startswith("/") and command in PRESETS:
            extra = question.partition(" ")[2]
            question = _(PRESETS[command][1]) + ("\n\n" + extra if extra else "")
        if not self.commits and not self.worktreePaths:
            self.setStatus(_("Load commits before sending a question."))
            return
        settings.history.aiProvider = self.provider()
        settings.history.aiLanguage = self.languageCombo.currentText().strip()
        settings.history.aiModels = {**settings.history.aiModels, self.provider(): self.model()}
        settings.history.setDirty()
        self.messages.append({"role": "user", "content": question})
        self.messages.append({"role": "assistant", "content": ""})
        self.input.clear()
        # A question just asked belongs on screen, wherever the reader had got
        # to in the answer before it; only the words that stream in afterwards
        # leave their place alone.
        self.render(toEnd=True)
        self.stopped = False
        if self.rulesCheck.isChecked():
            self.prepareGuidance()
        self.setBusy(True)
        if self.context is None:
            self.setStatus(_("Reading selected commits…"))
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
        self.setStatus(_("Waiting for {0}…", self.provider().capitalize()))
        context = (self.scopeDescription + "\n\n" if self.scopeDescription else "") + self.context
        if self.branchRange:
            summaries = "\n".join(f"{sha} {self.repo[sha].author.name}: " + (self.repo[sha].message or "").partition("\n")[0]
                                  for sha in self.commits)
            context = "Branch commits:\n" + summaries + "\n\n" + context
        guidance = self.guidance if self.rulesCheck.isChecked() else "Project guidance disabled by user."
        if self.rulesCheck.isChecked() and self.guidanceOmitted:
            guidance += "\n\nGuidance omitted due to limits; do not claim full rule compliance:\n" + "\n".join(self.guidanceOmitted)
        allowEdits = self.editsCheck.isChecked()
        if self.worktreePaths:
            prompt = makeWorktreePrompt(
                self.worktreePaths, context, self.messages[:-1], self.languageCombo.currentText().strip(),
                guidance, allowEdits=allowEdits)
        else:
            prompt = makePrompt(
                self.commits, context, self.messages[:-1], self.languageCombo.currentText().strip(),
                guidance, allowEdits=allowEdits)
        images = list(self.attachments)
        if images:
            prompt += imageInstructions(images)
        allowEdits = self.editsCheck.isChecked()
        self.startProcess(self.providers[self.provider()],
                          cliArguments(self.provider(), self.model(), images=images, allowEdits=allowEdits),
                          "assistant", prompt)

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
            self.refreshSetup()
        self.setStatus(_("Responding…") if self.stream.text else _("Analyzing commits…"))
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
            self.resetScope(commits, self.branchDescription, self.branchCaption)
            self.setStatus(_("Ready") if commits else _("No branch commits to review against this base."))
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
            self.setStatus(_("Ready · diff context truncated") if self.contextTruncated else _("Ready"))
            self.input.setFocus()

    def fail(self, message):
        if self.process:
            self.process.deleteLater()
            self.process = None
        if self.phase in ("authors", "activity", "branch"):
            self.setBusy(False)
            self.setStatus(_("Request interrupted: {0}", message), message)
            return
        self.messages[-1]["content"] += "\n\n" + _("Request interrupted: {0}", message)
        self.render()
        self.setBusy(False)
        self.setStatus(_("Stopped") if self.stopped else _("Request failed"))

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
