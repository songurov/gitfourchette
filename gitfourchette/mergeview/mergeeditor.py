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
from gitfourchette.toolbox import *

FILLER = " "
"A line that stands in for text the other side doesn't have, so the panes stay level."


class MergePane(QPlainTextEdit):
    """One version of the file, with its conflicts marked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.blockRanges: list[tuple[int, int]] = []
        "First and last block of each conflict, in the order they appear."

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

    def __init__(self, path: str, text: str, parent=None, committed: str = "", labels=()):
        """
        `text` is the file as git left it, markers and all. Pass `committed`
        to look at a merge that is already in history: the result pane then
        shows what was committed, until the person asks to decide again.
        """
        super().__init__(parent)
        self.setObjectName("MergeEditor")
        self.path = path
        self.regions = parseConflicts(text)
        self.currentConflict = 0
        self.manualEdit = False
        self.committed = committed
        self.inspecting = bool(committed)
        self.crlf = text.count("\r\n") * 2 >= text.count("\n")
        self.labels = labels

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

        sides = QSplitter(Qt.Orientation.Horizontal, self)
        sides.setObjectName("Split_MergeSides")
        sides.setChildrenCollapsible(False)
        sides.addWidget(self._column(self.oursHeader, self.oursPane))
        sides.addWidget(self._column(self.theirsHeader, self.theirsPane))
        sides.setSizes([1, 1])

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setObjectName("Split_MergeEditor")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(sides)
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
        self.fillPanes()
        if self.inspecting:
            self.enterInspection()
        self.refresh()
        self.goToConflict(0)

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
        """
        Lay out both versions so they stay level: where one side has fewer
        lines than the other, the shorter one gets blank ones.
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

        labels = self.labels or next(((r.oursLabel, r.theirsLabel) for r in self.conflicts), ("", ""))
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
        self.summaryLabel.setText(
            _("All {0} conflicts settled", total) if not left
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
        strongest: the eye should find the passage in both panes at once.
        """
        conflicts = self.conflicts
        if not conflicts:
            return
        for pane, base in ((self.oursPane, colors.blue), (self.theirsPane, colors.olive)):
            selections = []
            for index, (first, last) in enumerate(pane.blockRanges):
                settled = conflicts[index].settled
                color = QColor(base)
                color.setAlphaF(0.40 if index == self.currentConflict else (0.18 if not settled else 0.07))
                for blockNumber in range(first, last + 1):
                    block = pane.document().findBlockByNumber(blockNumber)
                    if not block.isValid():
                        continue
                    selection = QTextEdit.ExtraSelection()
                    selection.format.setBackground(color)
                    selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                    selection.cursor = QTextCursor(block)
                    selections.append(selection)
            pane.setExtraSelections(selections)

    # -------------------------------------------------------------------------
    # Deciding

    def goToConflict(self, index: int):
        conflicts = self.conflicts
        if not conflicts:
            self.refresh()
            return
        self.currentConflict = max(0, min(index, len(conflicts) - 1))
        first, _last = self.oursPane.blockRanges[self.currentConflict]
        for pane in (self.oursPane, self.theirsPane):
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
