"""
Review a branch, keep the findings that are worth a colleague's time, and post
them on its merge request.

The dialog is deliberately a middle step rather than a pipe. A model's review is
a draft: some of it is right, some of it misreads code it cannot see, and all of
it goes out under the reviewer's own name. So every finding arrives unticked
until it is read, the text that will be posted is shown as text and can be
rewritten, and nothing reaches the merge request until the button that says so
is pressed.
"""

import json
import logging

from gitfourchette import settings
from gitfourchette.exttools.aichat import ResponseStream, availableProviders, cliArguments, configuredModel, modelChoices
from gitfourchette.exttools.aireview import DIMENSIONS, Finding, Review, formatFinding, makeReviewPrompt, parseReview, severityEmoji, summaryNote
from gitfourchette.exttools.aireviewcontext import projectGuidance
from gitfourchette.forge import gitlab
from gitfourchette.forge.accounts import loadAccounts
from gitfourchette.forge.poster import PostState, ReviewPoster
from gitfourchette.forge.session import ForgeSession
from gitfourchette.localization import *
from gitfourchette.porcelain import RefPrefix, split_remote_branch_shorthand
from gitfourchette.qt import *
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)

# The whole diff goes to the model in one call. Past this many characters the
# tail is dropped and the reviewer is told so: a review that silently saw half
# the change is worse than one that says which half it saw.
DIFF_LIMIT = 600_000

PREFERRED_BASES = ("develop", "main", "master", "origin/develop", "origin/main", "origin/master")


def remoteUrlForBranch(repo, ref: str) -> tuple[str, str]:
    """The remote URL this branch would be merged on, and the branch name there."""
    prefix, shorthand = RefPrefix.split(ref)
    if prefix == RefPrefix.REMOTES:
        remoteName, sourceBranch = split_remote_branch_shorthand(shorthand)
    elif prefix == RefPrefix.HEADS:
        sourceBranch, remoteName = shorthand, ""
        branch = repo.branches.local.get(shorthand)
        upstream = branch.upstream if branch is not None else None
        if upstream is not None:
            remoteName, sourceBranch = split_remote_branch_shorthand(upstream.shorthand)
        if not remoteName:
            remoteName = "origin" if "origin" in repo.remotes else next(iter(repo.remotes.names()), "")
    else:
        return "", ""
    if not remoteName:
        return "", ""
    try:
        return repo.remotes[remoteName].url, sourceBranch
    except KeyError:
        return "", ""


class FindingItem(QTreeWidgetItem):
    def __init__(self, finding: Finding):
        super().__init__()
        self.finding = finding
        self.body = ""
        "The text that will be posted; empty until the reviewer edits it."
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        self.setCheckState(0, Qt.CheckState.Unchecked)
        self.setText(0, f"{severityEmoji(finding.severity)} {finding.severity.upper()}")
        self.setText(1, finding.category)
        self.setText(2, f"{finding.file}:{finding.line}" if finding.file else "")
        self.setText(3, finding.problem)
        self.setToolTip(3, finding.problem)

    def postedBody(self, language: str, provider: str, marker=True) -> str:
        if not self.body.strip():
            return formatFinding(self.finding, language=language, provider=provider if marker else "")
        body = self.body.rstrip()
        return body + "\n\n" + self.finding.marker(provider) if marker else body


class ReviewFindingsDialog(QDialog):
    def __init__(self, repo, branchRef: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.repoPath = repo.workdir
        self.branch = branchRef
        self.branchName = branchRef.removeprefix("refs/heads/").removeprefix("refs/remotes/")
        self.providers = availableProviders()
        self.process = None
        self.phase = ""
        self.buffer = b""
        self.stderr = b""
        self.stream = None
        self.diffText = ""
        self.diffTruncated = False
        self.review: Review | None = None
        self.guidance = ""
        self.guidanceSources: list[str] = []
        self.guidanceOmitted: list[str] = []
        self.changeRequest = None
        self.poster = None
        self.range = None

        remoteUrl, self.sourceBranch = remoteUrlForBranch(repo, branchRef)
        self.project = gitlab.projectFromRemote(remoteUrl)

        self.setWindowTitle(_("Review for merge request: {0}", self.branchName))
        self.setObjectName("ReviewFindingsDialog")
        self.resize(1000, 720)
        layout = QVBoxLayout(self)

        # --- What is being reviewed
        scopeRow = QHBoxLayout()
        scopeRow.addWidget(QLabel(_("Compare against:")))
        self.baseCombo = QComboBox()
        for ref in sorted(repo.references):
            if ref.startswith(("refs/heads/", "refs/remotes/")) and ref != branchRef and not ref.endswith("/HEAD"):
                self.baseCombo.addItem(ref.removeprefix("refs/heads/").removeprefix("refs/remotes/"), ref)
        for preferred in PREFERRED_BASES:
            index = self.baseCombo.findText(preferred)
            if index >= 0:
                self.baseCombo.setCurrentIndex(index)
                break
        scopeRow.addWidget(self.baseCombo, 1)
        self.mrLabel = QElidedLabel("")
        scopeRow.addWidget(self.mrLabel, 2)
        self.findMrButton = QPushButton(_("Find merge request"))
        self.findMrButton.setAutoDefault(False)
        self.findMrButton.clicked.connect(self.findMergeRequest)
        scopeRow.addWidget(self.findMrButton)
        layout.addLayout(scopeRow)

        # --- What to look at, and who looks
        setupStrip = QFlowLayout()
        setupStrip.setContentsMargins(QMargins())
        setupStrip.setSpacing(8)
        setupStrip.addWidget(QLabel(_("Assistant:")))
        self.providerCombo = QComboBox()
        for provider in self.providers:
            self.providerCombo.addItem(provider.capitalize(), provider)
        preferred = self.providerCombo.findData(settings.history.aiProvider)
        if preferred >= 0:
            self.providerCombo.setCurrentIndex(preferred)
        self.providerCombo.currentIndexChanged.connect(self.loadModels)
        setupStrip.addWidget(self.providerCombo)
        self.modelCombo = QComboBox()
        self.modelCombo.setEditable(True)
        self.modelCombo.setMinimumWidth(200)
        setupStrip.addWidget(self.modelCombo)
        setupStrip.addWidget(QLabel(_("Comments in:")))
        self.languageCombo = QComboBox()
        self.languageCombo.setEditable(True)
        self.languageCombo.addItems(["Română", "English", "Русский", "Deutsch", "Français", "Español"])
        self.languageCombo.setCurrentText(settings.history.aiLanguage or "English")
        setupStrip.addWidget(self.languageCombo)
        self.rulesCheck = QCheckBox(_("Include project rules and skills"))
        self.rulesCheck.setChecked(True)
        self.rulesCheck.setToolTip(_("The project’s own AGENTS.md, CLAUDE.md, .claude/rules and skills, "
                                     "read from the revision under review, are given to the reviewer as criteria."))
        setupStrip.addWidget(self.rulesCheck)
        layout.addLayout(setupStrip)

        dimensionStrip = QFlowLayout()
        dimensionStrip.setContentsMargins(QMargins())
        dimensionStrip.setSpacing(8)
        dimensionStrip.addWidget(QLabel(_("Look at:")))
        remembered = set(settings.history.reviewDimensions or ())
        self.dimensionChecks = {}
        for key, (caption, hint) in DIMENSIONS.items():
            check = QCheckBox(caption)
            check.setChecked(key in remembered if remembered else key in ("performance", "structure", "database", "ef"))
            check.setToolTip(hint)
            dimensionStrip.addWidget(check)
            self.dimensionChecks[key] = check
        layout.addLayout(dimensionStrip)

        # --- The findings
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Severity"), _("Category"), _("Location"), _("Finding"), _("Result")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.currentItemChanged.connect(self.showFinding)
        self.tree.itemChanged.connect(lambda *_args: self.refreshButtons())
        layout.addWidget(self.tree, 3)

        self.bodyEdit = QPlainTextEdit()
        self.bodyEdit.setPlaceholderText(_("Run a review, then pick a finding to see the comment it would post."))
        self.bodyEdit.textChanged.connect(self.bodyEdited)
        layout.addWidget(self.bodyEdit, 2)

        bottomRow = QHBoxLayout()
        self.summaryCheck = QCheckBox(_("Also post a summary note"))
        self.summaryCheck.setChecked(True)
        self.summaryCheck.setToolTip(_("One note gathering every finding, including those that couldn’t be "
                                       "placed on a line of the diff."))
        bottomRow.addWidget(self.summaryCheck)
        bottomRow.addStretch(1)
        self.selectAllButton = QPushButton(_("Select all"))
        self.selectAllButton.setAutoDefault(False)
        self.selectAllButton.clicked.connect(self.selectAll)
        bottomRow.addWidget(self.selectAllButton)
        self.copyButton = QPushButton(_("Copy as Markdown"))
        self.copyButton.setAutoDefault(False)
        self.copyButton.clicked.connect(self.copyMarkdown)
        bottomRow.addWidget(self.copyButton)
        self.reviewButton = QPushButton(_("Run review"))
        self.reviewButton.clicked.connect(self.runReview)
        bottomRow.addWidget(self.reviewButton)
        self.postButton = QPushButton(_("Post selected…"))
        self.postButton.setDefault(True)
        self.postButton.clicked.connect(self.postSelected)
        bottomRow.addWidget(self.postButton)
        closeButton = QPushButton(_("Close"))
        closeButton.setAutoDefault(False)
        closeButton.clicked.connect(self.reject)
        bottomRow.addWidget(closeButton)
        layout.addLayout(bottomRow)

        self.statusLabel = QElidedLabel("")
        layout.addWidget(self.statusLabel)

        self.loadModels()
        self.refreshButtons()
        if not self.providers:
            self.setStatus(_("No assistant found. Install the Codex or Claude CLI to run a review."))
        elif self.project is None:
            self.setStatus(_("This branch has no GitLab remote: a review can be run and copied, but not posted."))
        else:
            self.setStatus(_("Ready to review {0} against {1}.", self.branchName, self.baseCombo.currentText()))

    # --- Small helpers -------------------------------------------------------

    def setStatus(self, message: str):
        self.statusLabel.setText(message)

    def provider(self) -> str:
        return self.providerCombo.currentData() or ""

    def model(self) -> str:
        value = self.modelCombo.currentText().strip()
        return "" if value == self.modelCombo.itemText(0) else value

    def language(self) -> str:
        return self.languageCombo.currentText().strip()

    def loadModels(self):
        self.modelCombo.clear()
        provider = self.provider()
        if not provider:
            return
        configured = configuredModel(provider)
        self.modelCombo.addItem(_("Default ({0})", configured) if configured else _("Default"))
        self.modelCombo.addItems(modelChoices(provider))
        remembered = (settings.history.aiModels or {}).get(provider, "")
        if remembered:
            self.modelCombo.setCurrentText(remembered)

    def items(self) -> list[FindingItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def selectedItems(self) -> list[FindingItem]:
        return [item for item in self.items() if item.checkState(0) == Qt.CheckState.Checked]

    def refreshButtons(self):
        busy = self.process is not None or self.poster is not None
        selected = len(self.selectedItems())
        self.reviewButton.setEnabled(not busy and bool(self.providers))
        self.postButton.setEnabled(not busy and selected > 0 and self.project is not None)
        self.postButton.setText(_n("Post {n} comment…", "Post {n} comments…", selected) if selected else _("Post selected…"))
        self.copyButton.setEnabled(bool(self.items()))
        self.selectAllButton.setEnabled(bool(self.items()))
        self.findMrButton.setEnabled(not busy and self.project is not None)
        self.baseCombo.setEnabled(not busy)

    def selectAll(self):
        state = Qt.CheckState.Unchecked if len(self.selectedItems()) == len(self.items()) else Qt.CheckState.Checked
        for item in self.items():
            item.setCheckState(0, state)

    def showFinding(self, current, _previous=None):
        if not isinstance(current, FindingItem):
            self.bodyEdit.clear()
            return
        with QSignalBlockerContext(self.bodyEdit):
            self.bodyEdit.setPlainText(current.postedBody(self.language(), self.provider(), marker=False))

    def bodyEdited(self):
        current = self.tree.currentItem()
        if isinstance(current, FindingItem):
            current.body = self.bodyEdit.toPlainText()

    def copyMarkdown(self):
        items = self.selectedItems() or self.items()
        parts = [item.postedBody(self.language(), self.provider(), marker=False) for item in items]
        if self.review is not None and self.summaryCheck.isChecked():
            parts.insert(0, self.summaryText(-1))
        QApplication.clipboard().setText("\n\n---\n\n".join(parts))
        self.setStatus(_n("{n} finding copied as Markdown.", "{n} findings copied as Markdown.", len(items)))

    # --- Running the review --------------------------------------------------

    def dimensions(self) -> list[str]:
        return [key for key, check in self.dimensionChecks.items() if check.isChecked()]

    def remember(self):
        settings.history.reviewDimensions = self.dimensions()
        settings.history.aiProvider = self.provider()
        settings.history.aiLanguage = self.language()
        settings.history.aiModels = {**settings.history.aiModels, self.provider(): self.model()}
        settings.history.setDirty()

    def prepareGuidance(self):
        """The project's own rules and skills, read from the revision under review."""
        paths = set()
        diff = self.repo[self.range[0]].tree.diff_to_tree(self.repo[self.range[1]].tree)
        for delta in diff.deltas:
            paths.update(path for path in (delta.old_file.path, delta.new_file.path) if path)
        self.guidance, self.guidanceSources, self.guidanceOmitted = projectGuidance(self.repo, self.range[1], paths)

    def runReview(self):
        if self.process is not None or not self.providers:
            return
        base = self.baseCombo.currentData()
        if not base:
            self.setStatus(_("Choose a branch to compare against."))
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

        self.range = (str(ancestor), str(target))
        self.tree.clear()
        self.bodyEdit.clear()
        self.review = None
        self.diffText = ""
        self.diffTruncated = False
        self.remember()
        if self.rulesCheck.isChecked():
            self.prepareGuidance()
        else:
            self.guidance, self.guidanceSources, self.guidanceOmitted = "", [], []
        self.setStatus(_("Reading the changes…"))
        # The aggregate diff from the merge base, which is what the merge
        # request shows - not the base branch's own commits since the fork.
        self.startProcess("git", ["--no-pager", "diff", "--no-ext-diff", "--no-textconv",
                                  "--stat", "--patch", *self.range, "--"], "diff")

    def startAssistant(self):
        provider = self.provider()
        self.stream = ResponseStream(provider)
        scope = _("branch {0} against {1}", self.branchName, self.baseCombo.currentText())
        if self.changeRequest is not None:
            scope = _("merge request !{0}, {1} into {2}", self.changeRequest.iid,
                      self.changeRequest.sourceBranch, self.changeRequest.targetBranch)
        guidance = self.guidance
        if self.guidanceOmitted:
            guidance += ("\n\nGuidance omitted due to limits; do not claim full rule compliance:\n"
                         + "\n".join(self.guidanceOmitted))
        context = self.diffText
        if self.diffTruncated:
            context += ("\n\n[The diff was truncated at this point. Review only what is above, "
                        "and do not claim to have reviewed the whole change.]")
        prompt = makeReviewPrompt(context, dimensions=self.dimensions(), guidance=guidance,
                                  language=self.language(), scope=scope)
        self.setStatus(_("Reviewing with {0}…", provider.capitalize()))
        self.startProcess(self.providers[provider], cliArguments(provider, self.model()), "assistant", prompt)

    def startProcess(self, program, args, phase, prompt=""):
        self.phase = phase
        self.buffer = b""
        self.stderr = b""
        process = QProcess(self)
        self.process = process
        if hasattr(QProcess, "UnixProcessParameters"):
            parameters = QProcess.UnixProcessParameters()
            parameters.flags = QProcess.UnixProcessFlag.CreateNewSession
            process.setUnixProcessParameters(parameters)
        process.setWorkingDirectory(self.repoPath)
        process.readyReadStandardOutput.connect(self.readOutput)
        process.readyReadStandardError.connect(self.readError)
        process.finished.connect(self.processFinished)
        process.errorOccurred.connect(self.processError)
        if prompt:
            process.started.connect(lambda: (process.write(prompt.encode("utf-8")), process.closeWriteChannel()))
        self.refreshButtons()
        process.start(program, args)

    def readError(self):
        if self.process:
            self.stderr = (self.stderr + bytes(self.process.readAllStandardError()))[-16000:]

    def readOutput(self):
        if not self.process:
            return
        data = bytes(self.process.readAllStandardOutput())
        if self.phase == "diff":
            remaining = DIFF_LIMIT - len(self.diffText)
            self.diffText += data.decode("utf-8", errors="replace")[:max(0, remaining)]
            self.diffTruncated |= len(data) > remaining
            return
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.consumeLine(line)

    def consumeLine(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            return
        if isinstance(event, dict):
            self.stream.consume(event)
            self.setStatus(_("Reviewing with {0}… ({1} characters so far)",
                             self.provider().capitalize(), len(self.stream.text)))

    def processError(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.process:
            self.fail(self.process.errorString())

    def processFinished(self, code, _exitStatus):
        if not self.process:
            return
        self.readOutput()
        self.readError()
        phase = self.phase
        self.process.deleteLater()
        self.process = None
        self.refreshButtons()

        if code != 0 and phase == "diff":
            self.fail(self.stderr.decode("utf-8", errors="replace").strip() or _("Couldn’t read the changes."))
            return
        if phase == "diff":
            if not self.diffText.strip():
                self.setStatus(_("This branch changes nothing against {0}.", self.baseCombo.currentText()))
                return
            self.startAssistant()
            return

        # The assistant's turn: a non-zero exit with usable JSON is still a
        # review, so parse first and only complain if there's nothing in it.
        review = parseReview(self.stream.text if self.stream else "")
        if review is None:
            detail = self.stderr.decode("utf-8", errors="replace").strip()
            self.bodyEdit.setPlainText(self.stream.text if self.stream else "")
            self.fail(_("The assistant didn’t answer with a review. Its reply is below. {0}", detail))
            return
        self.applyReview(review)

    def fail(self, message: str):
        self.setStatus(message)
        self.refreshButtons()

    def applyReview(self, review: Review):
        self.review = review
        self.tree.clear()
        for finding in review.findings:
            self.tree.addTopLevelItem(FindingItem(finding))
        for column in range(4):
            self.tree.resizeColumnToContents(column)
        if review.findings:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
            blocking = sum(1 for f in review.findings if f.blocking)
            rules = _n("{n} rule", "{n} rules", len(self.guidanceSources)) if self.guidanceSources else _("no project rules")
            self.setStatus(_n("{n} finding, {0} of them blocking. Tick the ones worth posting. ({1})",
                              "{n} findings, {0} of them blocking. Tick the ones worth posting. ({1})",
                              len(review.findings), blocking, rules))
        else:
            self.setStatus(review.summary or _("Nothing worth a comment."))
        self.refreshButtons()

    # --- The merge request ---------------------------------------------------

    def token(self) -> str:
        return loadAccounts().tokenFor(self.project.host) if self.project else ""

    def ensureToken(self) -> str:
        token = self.token()
        if token:
            return token
        from gitfourchette.forms.forgeaccountsdialog import ForgeAccountsDialog
        dialog = ForgeAccountsDialog(self, focusHost=self.project.host)
        dialog.exec()
        return self.token()

    def findMergeRequest(self, thenPost=False):
        if self.project is None:
            return
        token = self.ensureToken()
        if not token:
            self.setStatus(_("No token for {0}: comments can’t be posted.", self.project.host))
            return
        self.pendingPost = thenPost
        self.setStatus(_("Looking for an open merge request from {0}…", self.sourceBranch))
        self.session = ForgeSession(token, self)
        self.session.get(gitlab.openMergeRequestsUrl(self.project, self.sourceBranch), self.gotMergeRequests)

    def gotMergeRequests(self, payload, error):
        if error:
            self.setStatus(error)
            return
        found = gitlab.readMergeRequests(payload)
        if not found:
            self.setStatus(_("No open merge request from {0} on {1}.", self.sourceBranch, self.project.host))
            return
        chosen = found[0]
        if len(found) > 1:
            captions = [mr.caption() for mr in found]
            caption, ok = QInputDialog.getItem(self, _("Merge requests"), _("Which merge request?"), captions, 0, False)
            if not ok:
                return
            chosen = found[captions.index(caption)]
        self.setMergeRequest(chosen)
        if getattr(self, "pendingPost", False):
            self.pendingPost = False
            self.postSelected()

    def setMergeRequest(self, changeRequest):
        self.changeRequest = changeRequest
        self.mrLabel.setText(_("!{0} {1} → {2}", changeRequest.iid, changeRequest.sourceBranch, changeRequest.targetBranch))
        self.mrLabel.setToolTip(changeRequest.webUrl)
        # The merge request decides what this change is measured against; align
        # the comparison with it so the diff we review is the diff it shows.
        for candidate in (changeRequest.targetBranch, f"origin/{changeRequest.targetBranch}"):
            index = self.baseCombo.findText(candidate)
            if index >= 0:
                self.baseCombo.setCurrentIndex(index)
                break
        self.refreshButtons()

    # --- Posting -------------------------------------------------------------

    def summaryText(self, inlineCount: int) -> str:
        headerLines = []
        if self.changeRequest is not None:
            headerLines.append(_("{0} → {1}", self.changeRequest.sourceBranch, self.changeRequest.targetBranch))
        selected = len(self.selectedItems())
        if selected != len(self.items()):
            headerLines.append(_n("{n} finding of {0} posted", "{n} findings of {0} posted", selected, len(self.items())))
        # Only what the reviewer kept goes in the note: a finding they dropped
        # was dropped, and listing it anyway would post it by the back door.
        kept = Review(verdict=self.review.verdict, summary=self.review.summary, good=self.review.good,
                      findings=[item.finding for item in self.selectedItems()])
        return summaryNote(kept, _("Code Review"), headerLines=headerLines,
                           inlineCount=inlineCount, language=self.language())

    def postSelected(self):
        items = self.selectedItems()
        if not items or self.project is None or self.poster is not None:
            return
        if self.changeRequest is None:
            self.findMergeRequest(thenPost=True)
            return
        token = self.ensureToken()
        if not token:
            return

        question = _n("Post {n} comment on merge request !{0}?", "Post {n} comments on merge request !{0}?",
                      len(items), self.changeRequest.iid)
        detail = _("They will appear under your own name on {0}.", self.project.host)
        askConfirmation(self, _("Post review comments"), f"{question}\n\n{detail}",
                        callback=lambda: self.startPosting(items, token), okButtonText=_("Post"))

    def startPosting(self, items, token):
        provider = self.provider()
        language = self.language()
        bodies = {item.finding.fingerprint(): item.postedBody(language, provider, marker=False)
                  for item in items if item.body.strip()}
        self.poster = ReviewPoster(
            self.project, token, self.changeRequest, self.diffText,
            [item.finding for item in items], provider=provider, language=language,
            summaryBuilder=self.summaryText if self.summaryCheck.isChecked() else None,
            bodies=bodies, parent=self)
        self.poster.progress.connect(lambda done, total, message: self.setStatus(f"{message} ({done}/{total})"))
        self.poster.finished.connect(self.posted)
        self.poster.failed.connect(self.postingFailed)
        self.refreshButtons()
        self.poster.start()

    def posted(self, results):
        self.poster = None
        byFingerprint = {item.finding.fingerprint(): item for item in self.items()}
        wording = {
            PostState.Posted: _("Posted"),
            PostState.Snapped: _("Posted (moved)"),
            PostState.Unplaced: _("In the summary only"),
            PostState.Failed: _("Failed"),
        }
        for result in results:
            item = byFingerprint.get(result.finding.fingerprint())
            if item is None:
                continue
            item.setText(4, wording[result.state])
            item.setToolTip(4, result.message)
            # A posted comment can't be unposted: untick it so a second press
            # doesn't duplicate the thread.
            if result.state in (PostState.Posted, PostState.Snapped):
                item.setCheckState(0, Qt.CheckState.Unchecked)
        posted = sum(1 for r in results if r.state in (PostState.Posted, PostState.Snapped))
        failed = [r for r in results if r.state == PostState.Failed]
        unplaced = sum(1 for r in results if r.state == PostState.Unplaced)
        message = _n("{n} comment posted.", "{n} comments posted.", posted)
        if unplaced:
            message += " " + _n("{n} couldn’t be placed on the diff and travels in the summary note.",
                                "{n} couldn’t be placed on the diff and travel in the summary note.", unplaced)
        if failed:
            message += " " + _n("{n} failed: {0}", "{n} failed: {0}", len(failed), failed[0].message)
        self.setStatus(message)
        self.refreshButtons()

    def postingFailed(self, message: str):
        self.poster = None
        self.setStatus(message)
        self.refreshButtons()

    # --- Leaving --------------------------------------------------------------

    def reject(self):  # override
        if self.process is not None:
            process, self.process = self.process, None
            process.kill()
        super().reject()
