# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffview.diffdocument import DiffDocument, DiffTextFormats, LineData, doppelgangerRanges
from gitfourchette.qt import *
from gitfourchette.toolbox import qstringLength


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
    def _row(text: str, lineNo: int, origin: str, fmt: QTextBlockFormat | None = None,
             ranges: list[tuple[int, int]] = ()):
        """
        One row of a pane: its text, its block format, and the character ranges
        that tell what changed inside the line, in the row's own coordinates.
        """
        prefix = "" if lineNo < 0 else str(lineNo)
        head = f"{prefix:>6} {origin or ' '} "
        body = text.removesuffix("\n")
        emphasis = DiffTextFormats.doppelgangerDelCF if origin == "-" else DiffTextFormats.doppelgangerAddCF
        spans = [(len(head) + start, len(head) + min(end, len(body)), emphasis)
                 for start, end in ranges if start < len(body)]
        return head + body, fmt, spans

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
                (additions if item.origin == "+" else deletions).append((i, item))
                i += 1
            # Rows with nothing across from them are filler, drawn as such if the theme says how
            hasFillerColor = DiffTextFormats.fillerBF.background().style() != Qt.BrushStyle.NoBrush
            filler = ("", DiffTextFormats.fillerBF if hasFillerColor else None, [])
            for n in range(max(len(deletions), len(additions))):
                deletion = deletions[n] if n < len(deletions) else None
                addition = additions[n] if n < len(additions) else None

                # A line that faces its own old self: say which words changed
                delRanges = addRanges = ()
                if deletion is not None and addition is not None and deletion[1].doppelganger == addition[0]:
                    delRanges, addRanges = doppelgangerRanges(
                        deletion[1].text.removesuffix("\n"), addition[1].text.removesuffix("\n"))

                if deletion is not None:
                    item = deletion[1]
                    oldRows.append(cls._row(item.text, item.oldLineNo, "-", DiffTextFormats.delBF, delRanges))
                else:
                    oldRows.append(filler)
                if addition is not None:
                    item = addition[1]
                    newRows.append(cls._row(item.text, item.newLineNo, "+", DiffTextFormats.addBF, addRanges))
                else:
                    newRows.append(filler)
        return oldRows, newRows

    @classmethod
    def _fill(cls, view: QPlainTextEdit, rows):
        # Put all the text in at once, then format only the blocks that need it,
        # in one edit block. Inserting row by row relaid the document out after
        # every line: seconds for a long diff.
        view.setPlainText("\n".join(text for text, _blockFormat, _spans in rows))
        cls._paint(view.document(), rows)
        view.moveCursor(QTextCursor.MoveOperation.Start)

    @staticmethod
    def _paint(document: QTextDocument, rows, plainFormat: QTextBlockFormat | None = None):
        """
        Set the rows' block formats and the emphasis on the words that changed
        inside a line; rows without a block format get plainFormat, if given.
        """
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        block = document.firstBlock()
        for text, blockFormat, spans in rows:
            if blockFormat is None:
                blockFormat = plainFormat
            if blockFormat is not None:
                cursor.setPosition(block.position())
                cursor.setBlockFormat(blockFormat)
            for start, end, charFormat in spans:
                # Qt counts UTF-16 units, Python counts characters
                cursor.setPosition(block.position() + qstringLength(text[:start]))
                cursor.setPosition(block.position() + qstringLength(text[:end]),
                                   QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(charFormat)
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
