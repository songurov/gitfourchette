# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# -----------------------------------------------------------------------------

from typing import NamedTuple

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.codeview.codehighlighter import CodeHighlighter
from gitfourchette.diffview.diffdocument import DiffDocument, DiffTextFormats, LineData, doppelgangerRanges
from gitfourchette.qt import *
from gitfourchette.syntax import ColorScheme, LexJob
from gitfourchette.toolbox import qstringLength


GUTTER_SPACE = " "
"""
Figure space: as wide as a digit, which in a fixed-pitch font is as wide as
anything else, and no whitespace mark is ever drawn on it. The line numbers
in front of the code are padded with it so that turning the marks on doesn't
fill the numbers with dots that belong to no line of code.
"""


class Row(NamedTuple):
    """One row of one pane."""

    text: str
    "Line number, origin sign and code, as the pane shows them."

    blockFormat: QTextBlockFormat | None
    "The row's tint; None keeps the document's own."

    spans: list[tuple[int, int, QTextCharFormat]]
    "What changed inside the line, in this row's coordinates."

    line: LineData | None = None
    "The line of the diff this row came from; None for filler rows."

    offset: int = 0
    "Where the code starts in `text`, past the line number."


class SideDiffHighlighter(CodeHighlighter):
    """
    Syntax colors for one pane of the side-by-side view. A pane's rows are
    lines of one side of the file with a line number written in front, so the
    highlighter has to be told which line each row came from.
    """

    rows: list[Row]

    def __init__(self, parent, oldSide: bool):
        super().__init__(parent)
        self.oldSide = oldSide
        self.rows = []

    def setRows(self, rows: list[Row], lexJob: LexJob | None):
        self.rows = rows
        self.stopLexJobs()
        if lexJob is not None:
            self.installLexJob(lexJob)
        self.rehighlight()

    def highlightSyntax(self, text: str):
        blockNumber = self.currentBlock().blockNumber()
        if not self.lexJobs or blockNumber >= len(self.rows):
            return

        row = self.rows[blockNumber]
        if row.line is None:
            return
        lineNumber = row.line.oldLineNo if self.oldSide else row.line.newLineNo
        if lineNumber < 0:  # A hunk header, or a line the other side owns
            return

        # A changed line sits on a tint of its own: its colors need to pop off it
        scheme = self.scheme.highContrastScheme if row.line.origin in "+-" else self.scheme.scheme
        column = row.offset
        boundary = len(text)

        for tokenType, tokenLength in self.lexJobs[0].tokens(lineNumber, text[row.offset:]):
            try:
                charFormat = scheme[tokenType]
            except KeyError:
                charFormat = ColorScheme.fillInFallback(scheme, tokenType)
            self.setFormat(column, tokenLength, charFormat)
            column += tokenLength
            if column >= boundary:
                break


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
        self.oldHighlighter = SideDiffHighlighter(self.oldView, oldSide=True)
        self.newHighlighter = SideDiffHighlighter(self.newView, oldSide=False)
        self.oldHighlighter.setDocument(self.oldView.document())
        self.newHighlighter.setDocument(self.newView.document())

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
        # A theme that comes from the desktop restyles the app without touching
        # the preferences: listen for both, as the unified view does, or a
        # light/dark flip would leave the panes in the colors it left behind.
        app.restyle.connect(self.refreshPrefs)
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
        Dress both panes like the unified view: its font, its tab width, its
        whitespace marks and its syntax colors. Code read next to its old self
        only lines up in a fixed-pitch font.
        """
        font = settings.prefs.monoFont()
        tabWidth = QFontMetricsF(font).horizontalAdvance(" " * settings.prefs.tabSpaces)

        flags = QTextOption.Flag(0)
        if settings.prefs.showWhitespace:
            flags |= QTextOption.Flag.ShowTabsAndSpaces

        scheme = settings.prefs.syntaxHighlightingScheme()

        for view, highlighter in ((self.oldView, self.oldHighlighter), (self.newView, self.newHighlighter)):
            view.setFont(font)
            view.setTabStopDistance(tabWidth)
            document = view.document()
            document.setDefaultFont(font)
            option = QTextOption(document.defaultTextOption())
            option.setFlags(flags)
            document.setDefaultTextOption(option)
            view.setStyleSheet(scheme.basicQss(view))
            highlighter.setColorScheme(scheme)
            highlighter.rehighlight()

    @staticmethod
    def _row(line: LineData | None, text: str, lineNo: int, origin: str,
             fmt: QTextBlockFormat | None = None, ranges: list[tuple[int, int]] = ()):
        """
        One row of a pane: its text, its block format, the character ranges
        that tell what changed inside the line, and the line it came from.
        """
        prefix = "" if lineNo < 0 else str(lineNo)
        head = f"{prefix:>6} {origin or ' '} ".replace(" ", GUTTER_SPACE)
        body = text.removesuffix("\n")
        emphasis = DiffTextFormats.doppelgangerDelCF if origin == "-" else DiffTextFormats.doppelgangerAddCF
        spans = [(len(head) + start, len(head) + min(end, len(body)), emphasis)
                 for start, end in ranges if start < len(body)]
        return Row(head + body, fmt, spans, line, len(head))

    @classmethod
    def _alignedRows(cls, lines: list[LineData]):
        oldRows = []
        newRows = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.hunkPos.isHunkHeaderLine():
                row = cls._row(None, line.text, -1, "", DiffTextFormats.hunkBF)
                oldRows.append(row)
                newRows.append(row)
                i += 1
                continue
            if line.origin not in "+-":
                oldRows.append(cls._row(line, line.text, line.oldLineNo, " "))
                newRows.append(cls._row(line, line.text, line.newLineNo, " "))
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
            filler = Row("", DiffTextFormats.fillerBF if hasFillerColor else None, [])
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
                    oldRows.append(cls._row(item, item.text, item.oldLineNo, "-", DiffTextFormats.delBF, delRanges))
                else:
                    oldRows.append(filler)
                if addition is not None:
                    item = addition[1]
                    newRows.append(cls._row(item, item.text, item.newLineNo, "+", DiffTextFormats.addBF, addRanges))
                else:
                    newRows.append(filler)
        return oldRows, newRows

    @classmethod
    def _fill(cls, view: QPlainTextEdit, rows):
        # Put all the text in at once, then format only the blocks that need it,
        # in one edit block. Inserting row by row relaid the document out after
        # every line: seconds for a long diff.
        view.setPlainText("\n".join(row.text for row in rows))
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
        for row in rows:
            blockFormat = row.blockFormat if row.blockFormat is not None else plainFormat
            if blockFormat is not None:
                cursor.setPosition(block.position())
                cursor.setBlockFormat(blockFormat)
            for start, end, charFormat in row.spans:
                # Qt counts UTF-16 units, Python counts characters
                cursor.setPosition(block.position() + qstringLength(row.text[:start]))
                cursor.setPosition(block.position() + qstringLength(row.text[:end]),
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
        self._lexWhileVisible(True)

    def hideEvent(self, event: QHideEvent):
        super().hideEvent(event)
        self._lexWhileVisible(False)

    def _lexWhileVisible(self, visible: bool):
        # The lex jobs are shared with the unified view, which puts them on ice
        # when it goes behind us. Whoever is on screen keeps them going.
        for highlighter in self.oldHighlighter, self.newHighlighter:
            highlighter.onParentVisibilityChanged(visible)

    def _showPendingDocument(self):
        document = self.pendingDocument
        self.pendingDocument = None
        if document is None:
            return
        self.shownDocument = document
        oldRows, newRows = self._alignedRows(document.lineData)
        self._fill(self.oldView, oldRows)
        self._fill(self.newView, newRows)
        # The lex jobs are the unified view's: both presentations read the same
        # file, so they read the same tokens
        self.oldHighlighter.setRows(oldRows, document.oldLexJob)
        self.newHighlighter.setRows(newRows, document.newLexJob)

    def recolor(self, document: DiffDocument):
        """
        Paint the rows again in the current colors after a switch between light
        and dark. The text and the scroll position stay put.
        """
        # A diff still waiting to be shown will be built in the current colors
        if document is not self.shownDocument:
            return
        oldRows, newRows = self._alignedRows(document.lineData)
        # The highlighters read the rows to find out which line of the file each
        # one came from: hand them the fresh batch so there is one set of rows,
        # not two that are only equal by luck
        self.oldHighlighter.rows = oldRows
        self.newHighlighter.rows = newRows
        # A row that was painted in the old colors may have no color now (filler rows)
        plainFormat = QTextBlockFormat()
        self._paint(self.oldView.document(), oldRows, plainFormat)
        self._paint(self.newView.document(), newRows, plainFormat)
