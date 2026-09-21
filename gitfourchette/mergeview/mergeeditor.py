# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Settle a conflicted file without leaving the app: both versions side by side,
the result underneath, and one decision per conflict.
"""

from __future__ import annotations

from pathlib import Path

from gitfourchette import colors, settings
from gitfourchette.localization import *
from gitfourchette.mergeview.conflictparser import (
    MergeRegion, Side, parseConflicts, renderResolution)
from gitfourchette.qt import *
from gitfourchette.settings import MergeLayout
from gitfourchette.toolbox import *

FILLER = " "
"A line that stands in for text the other side doesn't have, so the panes stay level."


def layoutCaptions() -> dict[MergeLayout, tuple[str, str]]:
    """
    What each arrangement calls itself in the editor's header, and what it
    does. Built on demand, so that a change of language reaches it.
    """
    return {
        MergeLayout.SideBySide: (
            _("Side by side"),
            _("Our version and theirs next to each other, the result underneath")),
        MergeLayout.Stacked: (
            _("Stacked"),
            _("Our version above theirs, the result underneath")),
        MergeLayout.OneColumn: (
            _("One column"),
            _("One column, where each conflict shows our version over theirs")),
    }


class MergePane(QPlainTextEdit):
    """One version of the file, with its conflicts marked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.blockRanges: list[tuple[int, int]] = []
        "First and last block of each conflict, in the order they appear."

        self.sideRanges: list[tuple[tuple[int, int], tuple[int, int]]] = []
        """With both versions in one column, which blocks of each conflict are
        ours and which are theirs. Empty in the arrangements that give each
        version a pane of its own."""

    def mousePressEvent(self, event: QMouseEvent):
        super().mousePressEvent(event)
        block = self.cursorForPosition(event.position().toPoint()).blockNumber()
        for index, (first, last) in enumerate(self.blockRanges):
            if first <= block <= last:
                self.conflictClicked.emit(index)
                break

    conflictClicked = Signal(int)


class MergeEditor(QDialog):
    """
    The editor itself. It works on the text that git left in the working
    directory, markers and all, and hands back what the person settled on.
    """

    def __init__(self, path: str, text: str, parent=None, committed: str = "", labels=(), workdir: str = ""):
        """
        `text` is the file as git left it, markers and all. Pass `committed`
        to look at a merge that is already in history: the result pane then
        shows what was committed, until the person asks to decide again.
        """
        super().__init__(parent)
        self.setObjectName("MergeEditor")
        self.path = path
        self.workdir = workdir
        self.aiProcess = None
        self.aiIndices: list[int] = []
        self.aiBuffer = b""
        self.aiStream = None
        self.regions = parseConflicts(text)
        self.currentConflict = 0
        self.manualEdit = False
        self.committed = committed
        self.inspecting = bool(committed)
        self.crlf = text.count("\r\n") * 2 >= text.count("\n")
        self.labels = labels
        self.layoutMode = settings.prefs.mergeEditorLayout
        self.sidesShare = 0.5
        """How much of the room between the two versions goes to ours. Kept as
        a share rather than in pixels, so that a divider the person dragged
        survives a trip through another arrangement."""

        self.setWindowTitle(_("Merge of {0}", Path(path).name) if self.inspecting
                            else _("Resolve conflict in {0}", Path(path).name))

        # -- Header: which file, which conflict, and the way through them
        self.pathLabel = QLabel(escape(path), self)
        self.pathLabel.setObjectName("MergeEditorPath")
        self.counterLabel = QLabel(self)
        self.counterLabel.setObjectName("MergeEditorCounter")
        self.counterLabel.setProperty("class", "secondary")

        self.previousButton = QToolButton(self)
        self.previousButton.setText("↑")
        self.previousButton.setAccessibleName(_("Previous conflict"))
        self.previousButton.setToolTip(_("Previous conflict"))
        self.previousButton.clicked.connect(lambda: self.goToConflict(self.currentConflict - 1))
        self.nextButton = QToolButton(self)
        self.nextButton.setText("↓")
        self.nextButton.setAccessibleName(_("Next conflict"))
        self.nextButton.setToolTip(_("Next conflict"))
        self.nextButton.clicked.connect(lambda: self.goToConflict(self.currentConflict + 1))

        header = QHBoxLayout()
        header.addWidget(self.pathLabel)
        header.addStretch(1)
        header.addLayout(self.makeLayoutPicker())
        header.addSpacing(8)
        header.addWidget(self.counterLabel)
        header.addWidget(self.previousButton)
        header.addWidget(self.nextButton)

        # -- The two versions, side by side, and the result under them
        self.oursPane = MergePane(self)
        self.theirsPane = MergePane(self)
        self.outputPane = QPlainTextEdit(self)
        self.outputPane.setObjectName("MergeEditorOutput")
        self.outputPane.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.outputPane.setReadOnly(True)

        self.oursHeader = QLabel(self)
        self.theirsHeader = QLabel(self)
        self.outputHeader = QLabel(_("Result"), self)
        for label in (self.oursHeader, self.theirsHeader, self.outputHeader):
            label.setProperty("class", "secondary")
            tweakWidgetFont(label, 90)

        self.oursColumn = self._column(self.oursHeader, self.oursPane)
        self.theirsColumn = self._column(self.theirsHeader, self.theirsPane)

        self.sides = QSplitter(Qt.Orientation.Horizontal, self)
        self.sides.setObjectName("Split_MergeSides")
        self.sides.setChildrenCollapsible(False)
        self.sides.addWidget(self.oursColumn)
        self.sides.addWidget(self.theirsColumn)
        self.sides.setSizes([1, 1])

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setObjectName("Split_MergeEditor")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.sides)
        self.splitter.addWidget(self._column(self.outputHeader, self.outputPane))
        self.splitter.setSizes([600, 400])

        for pane in (self.oursPane, self.theirsPane):
            pane.conflictClicked.connect(self.goToConflict)
        self.oursPane.verticalScrollBar().valueChanged.connect(
            self.theirsPane.verticalScrollBar().setValue)
        self.theirsPane.verticalScrollBar().valueChanged.connect(
            self.oursPane.verticalScrollBar().setValue)

        # -- One decision per conflict, and the two that settle them all
        self.choiceButtons: list[tuple[QPushButton, tuple[Side, ...]]] = []
        choices = QHBoxLayout()
        choices.addWidget(QLabel(_("Keep:"), self))
        for label, choice in [
            (_("Ours"), (Side.Ours,)),
            (_("Theirs"), (Side.Theirs,)),
            (_("Ours, then theirs"), (Side.Ours, Side.Theirs)),
            (_("Theirs, then ours"), (Side.Theirs, Side.Ours)),
            (_("Neither"), ()),
        ]:
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, c=choice: self.chooseHere(c))
            choices.addWidget(button)
            self.choiceButtons.append((button, choice))
        choices.addStretch(1)

        self.allOursButton = QPushButton(_("All ours"), self)
        self.allOursButton.setToolTip(_("Settle every remaining conflict in favor of our version"))
        self.allOursButton.clicked.connect(lambda: self.chooseEverywhere((Side.Ours,)))
        self.allTheirsButton = QPushButton(_("All theirs"), self)
        self.allTheirsButton.setToolTip(_("Settle every remaining conflict in favor of their version"))
        self.allTheirsButton.clicked.connect(lambda: self.chooseEverywhere((Side.Theirs,)))
        choices.addWidget(self.allOursButton)
        choices.addWidget(self.allTheirsButton)

        self.aiButton = QPushButton(_("Ask AI"), self)
        self.aiButton.setObjectName("MergeEditorAiButton")
        self.aiButton.setToolTip(_("Propose a settlement for the conflicts still open, one at a time. "
                                   "Nothing is written to the file until you mark it resolved, and "
                                   "anything it proposes can be overruled like any other decision."))
        self.aiButton.clicked.connect(self.askAi)
        choices.addWidget(self.aiButton)

        # -- What's left to do, and the way out
        self.manualButton = QPushButton(_("Edit the result by hand"), self)
        self.manualButton.setCheckable(True)
        self.manualButton.toggled.connect(self.setManualEdit)

        self.summaryLabel = QLabel(self)
        self.summaryLabel.setObjectName("MergeEditorSummary")

        self.resolveButton = QPushButton(_("Mark as resolved"), self)
        self.resolveButton.setObjectName("MergeEditorResolveButton")
        self.resolveButton.setDefault(True)
        self.resolveButton.clicked.connect(self.finish)
        self.cancelButton = QPushButton(_("Cancel"), self)
        self.cancelButton.clicked.connect(self.reject)

        footer = QHBoxLayout()
        footer.addWidget(self.manualButton)
        footer.addWidget(self.summaryLabel, 1)
        footer.addWidget(self.cancelButton)
        footer.addWidget(self.resolveButton)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.splitter, 1)
        layout.addLayout(choices)
        layout.addLayout(footer)

        # From the keyboard: walk the conflicts, and settle the file. The
        # shortcuts work wherever the focus is in the editor, panes included.
        inEditor = Qt.ShortcutContext.WidgetWithChildrenShortcut
        makeWidgetShortcut(self, lambda: self.goToConflict(self.currentConflict + 1),
                           "Alt+Down", "F8", context=inEditor)
        makeWidgetShortcut(self, lambda: self.goToConflict(self.currentConflict - 1),
                           "Alt+Up", "Shift+F8", context=inEditor)
        makeWidgetShortcut(self, lambda: self.chooseHere((Side.Ours,)), "Alt+1", context=inEditor)
        makeWidgetShortcut(self, lambda: self.chooseHere((Side.Theirs,)), "Alt+2", context=inEditor)
        makeWidgetShortcut(self, self.finish, "Ctrl+Return", "Ctrl+Enter", context=inEditor)

        self.applyFont()
        self.applyLayoutMode()
        self.fillPanes()
        if self.inspecting:
            self.enterInspection()
        self.refresh()
        self.goToConflict(0)

    # -------------------------------------------------------------------------
    # How the editor is laid out

    def makeLayoutPicker(self) -> QHBoxLayout:
        """
        The arrangements, as one segmented control in the header: which one is
        on is the point, so it is a row of latched buttons rather than a menu
        you have to open to find out.
        """
        self.layoutButtons: list[tuple[QAbstractButton, MergeLayout]] = []
        group = QButtonGroup(self)
        group.setExclusive(True)

        row = QHBoxLayout()
        row.setSpacing(0)
        for mode, (caption, tip) in layoutCaptions().items():
            button = QToolButton(self)
            button.setObjectName(f"MergeEditorLayout_{mode.name}")
            button.setText(caption)
            button.setAccessibleName(caption)
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setChecked(mode == self.layoutMode)
            button.clicked.connect(lambda _checked=False, m=mode: self.setLayoutMode(m))
            group.addButton(button)
            row.addWidget(button)
            self.layoutButtons.append((button, mode))
        return row

    def setLayoutMode(self, mode: MergeLayout):
        """
        Lay the editor out another way, and remember it for next time. Nothing
        that has been decided is lost: the arrangement only moves the panes
        around what the conflicts already say.
        """
        if mode == self.layoutMode:
            return
        self.rememberSidesShare()
        self.layoutMode = mode
        if settings.prefs.mergeEditorLayout != mode:
            settings.prefs.mergeEditorLayout = mode
            settings.prefs.setDirty()
        self.applyLayoutMode()
        self.fillPanes()
        self.refresh()
        self.goToConflict(self.currentConflict)

    def rememberSidesShare(self):
        """
        Note where the divider between the two versions sits before the panes
        are moved. One column has no divider — and the pane it folds away
        measures zero — so there is nothing to learn from it.
        """
        if self.layoutMode == MergeLayout.OneColumn:
            return
        sizes = self.sides.sizes()
        room = sum(sizes)
        if len(sizes) == 2 and room > 0:
            self.sidesShare = sizes[0] / room

    def applyLayoutMode(self):
        """Put the panes where the current arrangement wants them."""
        oneColumn = self.layoutMode == MergeLayout.OneColumn
        self.sides.setOrientation(Qt.Orientation.Horizontal if self.layoutMode == MergeLayout.SideBySide
                                  else Qt.Orientation.Vertical)
        self.theirsColumn.setVisible(not oneColumn)
        if not oneColumn:
            # In shares of a notional thousand: the splitter scales them to
            # whatever room it has, in whichever direction it now runs
            ours = round(1000 * self.sidesShare)
            self.sides.setSizes([ours, 1000 - ours])
        for button, mode in self.layoutButtons:
            button.setChecked(mode == self.layoutMode)

    def enterInspection(self):
        """
        Looking at a merge from history: show what was committed, and keep
        every decision out of the way until the person asks for them.
        """
        self.outputHeader.setText(_("Kept in the merge"))
        self.outputPane.setPlainText(self.committed)
        self.resolveButton.setText(_("Decide again"))
        self.resolveButton.setToolTip(
            _("Go through this file's conflicts again, starting from the two versions above."))
        self.resolveButton.clicked.disconnect()
        self.resolveButton.clicked.connect(self.leaveInspection)
        self.manualButton.setVisible(False)
        for button, _choice in self.choiceButtons:
            button.setEnabled(False)
        self.allOursButton.setEnabled(False)
        self.allTheirsButton.setEnabled(False)

    def leaveInspection(self):
        """Take the decisions back: the result is built from the conflicts again."""
        self.inspecting = False
        self.outputHeader.setText(_("Result"))
        self.resolveButton.setText(_("Mark as resolved"))
        self.resolveButton.setToolTip("")
        self.resolveButton.clicked.disconnect()
        self.resolveButton.clicked.connect(self.finish)
        self.manualButton.setVisible(True)
        self.refresh()
        self.goToConflict(0)

    @staticmethod
    def _column(header: QLabel, view: QWidget) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(2)
        layout.addWidget(header)
        layout.addWidget(view)
        return container

    def applyFont(self):
        font = settings.prefs.monoFont()
        for pane in (self.oursPane, self.theirsPane, self.outputPane):
            pane.setFont(font)

    # -------------------------------------------------------------------------
    # What's on screen

    @property
    def conflicts(self) -> list[MergeRegion]:
        return [region for region in self.regions if region.conflicted]

    def fillPanes(self):
        """Write the two versions out the way the current arrangement wants them."""
        if self.layoutMode == MergeLayout.OneColumn:
            self.fillOneColumn()
        else:
            self.fillTwoPanes()
        self.writeHeaders()

    def fillTwoPanes(self):
        """
        A pane each, level with the other: where one side has fewer lines than
        the other, the shorter one gets blank ones, so a conflict sits at the
        same height in both.
        """
        for pane, side in ((self.oursPane, Side.Ours), (self.theirsPane, Side.Theirs)):
            lines: list[str] = []
            ranges: list[tuple[int, int]] = []
            for region in self.regions:
                if not region.conflicted:
                    lines += region.ours
                    continue
                own = region.sideLines(side)
                height = max(len(region.ours), len(region.theirs))
                first = len(lines)
                lines += own + [FILLER] * (height - len(own))
                ranges.append((first, len(lines) - 1))
            pane.setPlainText("\n".join(lines))
            pane.blockRanges = ranges
            pane.sideRanges = []

    def fillOneColumn(self):
        """
        One column, reading like the file itself: the text both sides agree on
        runs through it, and at each conflict our version is followed by theirs.
        A side that wrote nothing still gets a line, or there would be no way
        to tell whose turn it was.
        """
        lines: list[str] = []
        ranges: list[tuple[int, int]] = []
        sideRanges: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for region in self.regions:
            if not region.conflicted:
                lines += region.ours
                continue
            first = len(lines)
            lines += region.ours or [FILLER]
            middle = len(lines)
            lines += region.theirs or [FILLER]
            ranges.append((first, len(lines) - 1))
            sideRanges.append(((first, middle - 1), (middle, len(lines) - 1)))
        self.oursPane.setPlainText("\n".join(lines))
        self.oursPane.blockRanges = ranges
        self.oursPane.sideRanges = sideRanges
        self.theirsPane.setPlainText("")
        self.theirsPane.blockRanges = []
        self.theirsPane.sideRanges = []

    def writeHeaders(self):
        """Say which version is where, and where it came from."""
        labels = self.labels or next(((r.oursLabel, r.theirsLabel) for r in self.conflicts), ("", ""))
        if self.layoutMode == MergeLayout.OneColumn:
            self.oursHeader.setText(_("Ours over theirs — {0} over {1}", labels[0], labels[1])
                                    if labels[0] and labels[1] else _("Ours over theirs"))
            return
        self.oursHeader.setText(_("Ours — {0}", labels[0]) if labels[0] else _("Ours"))
        self.theirsHeader.setText(_("Theirs — {0}", labels[1]) if labels[1] else _("Theirs"))

    def refresh(self):
        """Put the result, the counter and the buttons back in step with the choices."""
        if self.inspecting:
            conflicts = self.conflicts
            self.counterLabel.setText(
                _("Conflict {0} of {1}", self.currentConflict + 1, len(conflicts)) if conflicts else "")
            self.summaryLabel.setText(_n("{n} conflict was settled here",
                                         "{n} conflicts were settled here", len(conflicts)))
            self.highlightCurrent()
            return
        if not self.manualEdit:
            self.outputPane.setPlainText(renderResolution(self.regions))

        conflicts = self.conflicts
        total = len(conflicts)
        left = sum(1 for region in conflicts if not region.settled)

        self.counterLabel.setText(
            _("Conflict {0} of {1}", self.currentConflict + 1, total) if total else _("No conflicts"))
        current = conflicts[self.currentConflict] if 0 <= self.currentConflict < total else None
        reason = current.reason if current is not None else ""
        self.summaryLabel.setText(
            reason if reason
            else _("All {0} conflicts settled", total) if not left
            else _n("{n} conflict left", "{n} conflicts left", left))

        current = conflicts[self.currentConflict] if total else None
        for button, choice in self.choiceButtons:
            button.setEnabled(current is not None and not self.manualEdit)
            button.setChecked(current is not None and current.settled and current.choice == choice)
        for button in (self.previousButton, self.nextButton):
            button.setEnabled(total > 1)
        self.allOursButton.setEnabled(bool(left) and not self.manualEdit)
        self.allTheirsButton.setEnabled(bool(left) and not self.manualEdit)
        self.highlightCurrent()

    def highlightCurrent(self):
        """
        Tint each side's conflicts in its own color, the one being decided on
        strongest: the eye should find the passage on both sides at once. The
        colors say which side is which, whether the two sit in two panes or
        one above the other in the same one.
        """
        conflicts = self.conflicts
        if not conflicts:
            return

        if self.layoutMode == MergeLayout.OneColumn:
            selections = []
            for index, ((ourFirst, ourLast), (theirFirst, theirLast)) in enumerate(self.oursPane.sideRanges):
                for base, first, last in ((colors.blue, ourFirst, ourLast),
                                          (colors.olive, theirFirst, theirLast)):
                    selections += self.tintBlocks(self.oursPane, first, last,
                                                  self.tint(base, index, conflicts[index].settled))
            self.oursPane.setExtraSelections(selections)
            self.theirsPane.setExtraSelections([])
            return

        for pane, base in ((self.oursPane, colors.blue), (self.theirsPane, colors.olive)):
            selections = []
            for index, (first, last) in enumerate(pane.blockRanges):
                color = self.tint(base, index, conflicts[index].settled)
                selections += self.tintBlocks(pane, first, last, color)
            pane.setExtraSelections(selections)

    def versionPanes(self) -> tuple[MergePane, ...]:
        """The panes holding a version of the file: one of them in one column."""
        if self.layoutMode == MergeLayout.OneColumn:
            return (self.oursPane,)
        return (self.oursPane, self.theirsPane)

    def tint(self, base: QColor, index: int, settled: bool) -> QColor:
        """A side's color, strongest on the conflict being decided on."""
        color = QColor(base)
        color.setAlphaF(0.40 if index == self.currentConflict else (0.18 if not settled else 0.07))
        return color

    @staticmethod
    def tintBlocks(pane: QPlainTextEdit, first: int, last: int, color: QColor) -> list:
        selections = []
        for blockNumber in range(first, last + 1):
            block = pane.document().findBlockByNumber(blockNumber)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(color)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = QTextCursor(block)
            selections.append(selection)
        return selections

    # -------------------------------------------------------------------------
    # Deciding

    def goToConflict(self, index: int):
        conflicts = self.conflicts
        if not conflicts:
            self.refresh()
            return
        self.currentConflict = max(0, min(index, len(conflicts) - 1))
        first, _last = self.oursPane.blockRanges[self.currentConflict]
        for pane in self.versionPanes():
            cursor = QTextCursor(pane.document().findBlockByNumber(first))
            pane.setTextCursor(cursor)
            pane.centerCursor()
        self.refresh()

    def chooseHere(self, choice: tuple[Side, ...]):
        conflicts = self.conflicts
        if not conflicts:
            return
        conflicts[self.currentConflict].decide(*choice)
        self.refresh()
        # Move on to the next conflict still waiting for a decision
        nextOpen = next((i for i, region in enumerate(conflicts) if not region.settled), -1)
        if nextOpen >= 0:
            self.goToConflict(nextOpen)

    # -------------------------------------------------------------------------
    # Asking an assistant

    def askAi(self):
        """
        Have the assistant propose a settlement for the conflicts still open.

        It decides regions, exactly as the buttons beside it do: nothing
        reaches the file until the editor is closed with "Mark as resolved",
        and every proposal can be overruled like any other decision.
        """
        from gitfourchette import settings
        from gitfourchette.exttools.aichat import availableProviders, cliArguments
        from gitfourchette.exttools.aiconflict import makeConflictPrompt, resolvableRegions

        if self.aiProcess is not None:
            return
        providers = availableProviders()
        wanted = settings.prefs.auditProvider or settings.history.aiProvider
        provider = wanted if wanted in providers else next(iter(providers), "")
        if not provider:
            self.summaryLabel.setText(_("No assistant installed."))
            return

        indices = resolvableRegions(self.conflicts)
        if not indices:
            self.summaryLabel.setText(_("Nothing left for it to settle."))
            return

        regions = self.conflicts
        prompt = makeConflictPrompt(self.path, regions, indices,
                                    oursLabel=regions[indices[0]].oursLabel,
                                    theirsLabel=regions[indices[0]].theirsLabel,
                                    language=settings.history.aiLanguage)
        self.aiIndices = indices
        self.aiBuffer = b""
        self.aiStream = None
        self.aiButton.setEnabled(False)
        self.summaryLabel.setText(_n("Asking {0} about {n} conflict…", "Asking {0} about {n} conflicts…",
                                     len(indices), provider.capitalize()))

        from gitfourchette.exttools.aichat import ResponseStream
        self.aiStream = ResponseStream(provider)
        process = QProcess(self)
        self.aiProcess = process
        if hasattr(QProcess, "UnixProcessParameters"):
            parameters = QProcess.UnixProcessParameters()
            parameters.flags = QProcess.UnixProcessFlag.CreateNewSession
            process.setUnixProcessParameters(parameters)
        if self.workdir:
            process.setWorkingDirectory(self.workdir)
        process.readyReadStandardOutput.connect(self.readAiOutput)
        process.finished.connect(self.aiFinished)
        process.errorOccurred.connect(lambda _error: self.aiFailed(process.errorString()))
        process.started.connect(lambda: (process.write(prompt.encode("utf-8")), process.closeWriteChannel()))
        model = settings.prefs.auditModel or (settings.history.aiModels or {}).get(provider, "")
        process.start(providers[provider], cliArguments(provider, model))

    def readAiOutput(self):
        import json as _json

        if self.aiProcess is None:
            return
        self.aiBuffer += bytes(self.aiProcess.readAllStandardOutput())
        while b"\n" in self.aiBuffer:
            line, self.aiBuffer = self.aiBuffer.split(b"\n", 1)
            try:
                event = _json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                self.aiStream.consume(event)

    def aiFinished(self, _code=0, _status=None):
        from gitfourchette.exttools.aiconflict import parseResolutions

        self.readAiOutput()
        if self.aiProcess is not None:
            self.aiProcess.deleteLater()
        self.aiProcess = None
        self.aiButton.setEnabled(True)

        text = self.aiStream.text if self.aiStream else ""
        settled = parseResolutions(text, set(self.aiIndices))
        for index, (lines, why) in settled.items():
            region = self.conflicts[index]
            region.decideCustom(lines, why)
        self.refresh()
        if not settled:
            self.summaryLabel.setText(_("The assistant settled none of them; they are yours to decide."))
            return
        remaining = len(self.aiIndices) - len(settled)
        # The ones it skipped are the honest part of the answer: say how many.
        self.summaryLabel.setText(
            _n("Settled {n} conflict; {0} left for you.", "Settled {n} conflicts; {0} left for you.",
               len(settled), remaining) if remaining
            else _n("Settled {n} conflict. Read it before you mark the file resolved.",
                    "Settled {n} conflicts. Read them before you mark the file resolved.", len(settled)))
        nextOpen = next((i for i, region in enumerate(self.conflicts) if not region.settled), -1)
        if nextOpen >= 0:
            self.goToConflict(nextOpen)

    def aiFailed(self, message: str):
        if self.aiProcess is not None:
            self.aiProcess.deleteLater()
        self.aiProcess = None
        self.aiButton.setEnabled(True)
        self.summaryLabel.setText(message)

    def chooseEverywhere(self, choice: tuple[Side, ...]):
        for region in self.conflicts:
            if not region.settled:
                region.decide(*choice)
        self.refresh()

    def setManualEdit(self, manual: bool):
        """
        Hand the result over to the person, or take it back. Taking it back
        writes the choices out again, so an edit isn't quietly kept around.
        """
        self.manualEdit = manual
        self.outputPane.setReadOnly(not manual)
        self.refresh()
        if manual:
            self.outputPane.setFocus()

    # -------------------------------------------------------------------------
    # Leaving

    def resolution(self) -> str:
        """
        What to write back. The decisions carry the file's own line endings;
        only text typed by hand comes out of the widget, where Qt has turned
        every ending into a newline, so it gets the file's ending back.
        """
        if self.inspecting:
            return self.committed
        if not self.manualEdit:
            return renderResolution(self.regions)
        text = self.outputPane.toPlainText()
        if self.crlf:
            text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        return text

    def finish(self):
        """Take the result, unless conflicts are still open and the person thinks again."""
        left = sum(1 for region in self.conflicts if not region.settled)
        if left and not self.manualEdit:
            question = _n("{n} conflict is still open, and its markers would stay in the file. "
                          "Mark the file as resolved anyway?",
                          "{n} conflicts are still open, and their markers would stay in the file. "
                          "Mark the file as resolved anyway?", left)
            askConfirmation(self, _("Unsettled conflicts"), question,
                            self.accept, okButtonText=_("Mark as resolved"))
            return
        self.accept()
