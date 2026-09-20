# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffview.diffdocument import DiffDocument, DiffTextFormats, LineData
from gitfourchette.qt import *


class SideBySideDiffView(QWidget):
    """Aligned old/new presentation of a unified DiffDocument."""

    pendingDocument: DiffDocument | None
    "The diff to present the next time this view is shown."

    shownDocument: DiffDocument | None
    "The diff on display."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pendingDocument = None
        self.shownDocument = None
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

        app = GFApplication.instance()
        app.prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

    def _makeView(self):
        view = QPlainTextEdit(self)
        view.setReadOnly(True)
        # Both sides scroll sideways on their own, and a row on the left always
        # faces its counterpart on the right: wrapping would break the pairing.
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return view

    def refreshPrefs(self):
        """
        Set the code in the same font as the unified view, and mark whitespace
        where the unified view marks it. Code read next to its old self only
        lines up in a fixed-pitch font.
        """
        font = settings.prefs.monoFont()
        tabWidth = QFontMetricsF(font).horizontalAdvance(" " * settings.prefs.tabSpaces)

        flags = QTextOption.Flag(0)
        if settings.prefs.showWhitespace:
            flags |= QTextOption.Flag.ShowTabsAndSpaces

        for view in self.oldView, self.newView:
            view.setFont(font)
            view.setTabStopDistance(tabWidth)
            document = view.document()
            document.setDefaultFont(font)
            option = QTextOption(document.defaultTextOption())
            option.setFlags(flags)
            document.setDefaultTextOption(option)

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
            # Rows with nothing across from them are filler, drawn as such if the theme says how
            hasFillerColor = DiffTextFormats.fillerBF.background().style() != Qt.BrushStyle.NoBrush
            filler = ("", DiffTextFormats.fillerBF if hasFillerColor else None)
            for n in range(max(len(deletions), len(additions))):
                if n < len(deletions):
                    item = deletions[n]
                    oldRows.append(cls._row(item.text, item.oldLineNo, "-", DiffTextFormats.delBF))
                else:
                    oldRows.append(filler)
                if n < len(additions):
                    item = additions[n]
                    newRows.append(cls._row(item.text, item.newLineNo, "+", DiffTextFormats.addBF))
                else:
                    newRows.append(filler)
        return oldRows, newRows

    @classmethod
    def _fill(cls, view: QPlainTextEdit, rows):
        # Put all the text in at once, then format only the blocks that need it,
        # in one edit block. Inserting row by row relaid the document out after
        # every line: seconds for a long diff.
        view.setPlainText("\n".join(text for text, _blockFormat in rows))
        cls._paint(view.document(), rows)
        view.moveCursor(QTextCursor.MoveOperation.Start)

    @staticmethod
    def _paint(document: QTextDocument, rows, plainFormat: QTextBlockFormat | None = None):
        """Set the rows' block formats; rows without one get plainFormat, if given."""
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        block = document.firstBlock()
        for _text, blockFormat in rows:
            if blockFormat is None:
                blockFormat = plainFormat
            if blockFormat is not None:
                cursor.setPosition(block.position())
                cursor.setBlockFormat(blockFormat)
            block = block.next()
        cursor.endEditBlock()

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
        self.shownDocument = document
        oldRows, newRows = self._alignedRows(document.lineData)
        self._fill(self.oldView, oldRows)
        self._fill(self.newView, newRows)

    def recolor(self, document: DiffDocument):
        """
        Paint the rows again in the current colors after a switch between light
        and dark. The text and the scroll position stay put.
        """
        # A diff still waiting to be shown will be built in the current colors
        if document is not self.shownDocument:
            return
        oldRows, newRows = self._alignedRows(document.lineData)
        # A row that was painted in the old colors may have no color now (filler rows)
        plainFormat = QTextBlockFormat()
        self._paint(self.oldView.document(), oldRows, plainFormat)
        self._paint(self.newView.document(), newRows, plainFormat)
