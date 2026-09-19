# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# -----------------------------------------------------------------------------

from gitfourchette.diffview.diffdocument import DiffDocument, DiffTextFormats, LineData
from gitfourchette.qt import *


class SideBySideDiffView(QWidget):
    """Aligned old/new presentation of a unified DiffDocument."""

    pendingDocument: DiffDocument | None
    "The diff to present the next time this view is shown."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pendingDocument = None
        self.oldView = self._makeView()
        self.newView = self._makeView()

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("Split_SideBySideDiff")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.oldView)
        splitter.addWidget(self.newView)
        splitter.setSizes([1, 1])

        self.oldView.verticalScrollBar().valueChanged.connect(self.newView.verticalScrollBar().setValue)
        self.newView.verticalScrollBar().valueChanged.connect(self.oldView.verticalScrollBar().setValue)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(splitter)

    def _makeView(self):
        view = QPlainTextEdit(self)
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return view

    @staticmethod
    def _row(text: str, lineNo: int, origin: str, fmt: QTextBlockFormat | None = None):
        prefix = "" if lineNo < 0 else str(lineNo)
        return f"{prefix:>6} {origin or ' '} {text.removesuffix(chr(10))}", fmt

    @classmethod
    def _alignedRows(cls, lines: list[LineData]):
        oldRows = []
        newRows = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.hunkPos.isHunkHeaderLine():
                row = cls._row(line.text, -1, "", DiffTextFormats.hunkBF)
                oldRows.append(row)
                newRows.append(row)
                i += 1
                continue
            if line.origin not in "+-":
                oldRows.append(cls._row(line.text, line.oldLineNo, " "))
                newRows.append(cls._row(line.text, line.newLineNo, " "))
                i += 1
                continue

            deletions = []
            additions = []
            clumpID = line.clumpID
            while i < len(lines) and lines[i].clumpID == clumpID:
                item = lines[i]
                (additions if item.origin == "+" else deletions).append(item)
                i += 1
            for n in range(max(len(deletions), len(additions))):
                if n < len(deletions):
                    item = deletions[n]
                    oldRows.append(cls._row(item.text, item.oldLineNo, "-", DiffTextFormats.delBF))
                else:
                    oldRows.append(("", None))
                if n < len(additions):
                    item = additions[n]
                    newRows.append(cls._row(item.text, item.newLineNo, "+", DiffTextFormats.addBF))
                else:
                    newRows.append(("", None))
        return oldRows, newRows

    @staticmethod
    def _fill(view: QPlainTextEdit, rows):
        # Put all the text in at once, then format only the blocks that need it,
        # in one edit block. Inserting row by row relaid the document out after
        # every line: seconds for a long diff.
        view.setPlainText("\n".join(text for text, _blockFormat in rows))
        document = view.document()
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        block = document.firstBlock()
        for _text, blockFormat in rows:
            if blockFormat is not None:
                cursor.setPosition(block.position())
                cursor.setBlockFormat(blockFormat)
            block = block.next()
        cursor.endEditBlock()
        view.moveCursor(QTextCursor.MoveOperation.Start)

    def replaceDocument(self, document: DiffDocument):
        # Build the presentation only when someone looks at it (see showEvent)
        self.pendingDocument = document
        if self.isVisible():
            self._showPendingDocument()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self._showPendingDocument()

    def _showPendingDocument(self):
        document = self.pendingDocument
        self.pendingDocument = None
        if document is None:
            return
        oldRows, newRows = self._alignedRows(document.lineData)
        self._fill(self.oldView, oldRows)
        self._fill(self.newView, newRows)
