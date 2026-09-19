# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import difflib
import re
from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.gitdriver.parsers import iterateLines
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.syntax import LexJob, ColorScheme
from gitfourchette.toolbox import *


_indexLinePattern = re.compile(r"index ([\da-f]+)\.\.([\da-f]+)")
_hunkHeaderPattern = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parseHunkHeader(text: str) -> tuple[int, int, int, int, str]:
    match = _hunkHeaderPattern.match(text)
    oldStartStr, oldLinesStr, newStartStr, newLinesStr = match.groups()
    oldStart = int(oldStartStr)
    newStart = int(newStartStr)
    oldLines = int(oldLinesStr) if oldLinesStr else 1
    newLines = int(newLinesStr) if newLinesStr else 1
    comment = text[match.end():]
    return oldStart, oldLines, newStart, newLines, comment


@dataclass
class DiffLinePos:
    hunkID: int

    hunkLineNum: int
    """
    0-indexed line number within the hunk.
    -1 means the hunk header line itself ("@@ ... @@").
    """

    def isHunkHeaderLine(self) -> bool:
        return self.hunkLineNum == -1


@dataclass
class LineData:
    text: str
    "Line text for visual representation."

    hunkPos: DiffLinePos
    "Which hunk this line pertains to, and its position in the hunk."

    origin: str = ""
    oldLineNo: int = -1
    newLineNo: int = -1

    cursorStart: int = -1
    "Cursor position at start of line in QDocument."

    cursorEnd: int = -1
    "Cursor position at end of line in QDocument."

    clumpID: int = -1
    "Which clump this line pertains to. 'Clumps' are groups of adjacent +/- lines."

    doppelganger: int = -1
    "Index of the doppelganger LineData in a perfectly even clump."

    trailerLength: int = 0
    "Stop highlighting the syntax past this column in the line."

    hiddenSuffix: str = ""
    """
    Suffix that follows `text` in a patch file but should be hidden in the UI,
    e.g. newline + backslash + ' No newline at end of file'.
    """

    @classmethod
    def getHunkExtents(cls, array: list[LineData], hunkID: int) -> tuple[int, int]:
        """
        Find indices of first and last LineData objects given the current hunk.
        """

        first = bisect_left(array, hunkID, 0, key=LineData._hunkIDKey)
        last = bisect_left(array, hunkID + 1, first, key=LineData._hunkIDKey) - 1
        return first, last

    def _hunkIDKey(self) -> int:
        return self.hunkPos.hunkID

    def parseHunkHeader(self) -> tuple[int, int, int, int, str]:
        assert self.hunkPos.hunkLineNum == -1
        return _parseHunkHeader(self.text)

    @property
    def originDelta(self) -> int:
        if self.origin == "+":
            return 1
        if self.origin == "-":
            return -1
        return 0

    @property
    def reverseOrigin(self) -> str:
        if self.origin == "+":
            return "-"
        if self.origin == "-":
            return "+"
        return self.origin


class DiffTextFormats:
    addBF = QTextBlockFormat()
    delBF = QTextBlockFormat()
    fillerBF = QTextBlockFormat()
    doppelgangerAddCF = QTextCharFormat()
    doppelgangerDelCF = QTextCharFormat()
    hunkBF = QTextBlockFormat()
    hunkCF = QTextCharFormat()
    warningCF = QTextCharFormat()

    generation = 0
    """
    Goes up each time refresh() changes the colors. A document holds copies
    of the formats it was built with; one built in an older generation must be
    painted again (see DiffDocument.recolor).
    """

    _madeFrom: tuple = ()
    "What the formats were last made from."

    @classmethod
    def refresh(cls, scheme: ColorScheme, colorblind: bool):
        # Every code view calls this whenever any setting changes. Only a new
        # look (light or dark, another syntax scheme, the colorblind palette)
        # makes new formats, and has every open diff painted again.
        madeFrom = (colorblind, *(
            None if color is None else color.rgba()
            for color in (scheme.backgroundColor, scheme.diffAdd, scheme.diffDel, scheme.diffFiller, scheme.diffHunkFg)))
        if madeFrom == cls._madeFrom:
            return
        cls._madeFrom = madeFrom
        cls.generation += 1

        bgColor = scheme.backgroundColor

        # Base del/add backgrounds.
        # Instead of using an alpha value, blend with the background color.
        # This way, we avoid overlapping alpha artifacts at the edges of QCharFormat runs.
        if colorblind:
            delColor1 = mixColors(bgColor, colors.orange, .35)
            addColor1 = mixColors(bgColor, colors.teal, .35)
        elif scheme.diffAdd and scheme.diffDel:
            # The built-in theme's own, with the automatic scheme
            delColor1 = scheme.diffDel
            addColor1 = scheme.diffAdd
        else:
            delColor1 = mixColors(bgColor, QColor(0xff5555), .35)
            addColor1 = mixColors(bgColor, QColor(0x55ff55), .35)

        # Starker contrast for per-character highlights
        if colorblind:
            delColor2 = mixColors(delColor1, colors.orange, .6)
            addColor2 = mixColors(addColor1, colors.teal, .6)
        elif scheme.isDark():
            delColor2 = mixColors(delColor1, QColor(0x993333), .6)
            addColor2 = mixColors(addColor1, QColor(0x339933), .6)
        else:
            delColor2 = mixColors(delColor1, QColor(0x993333), .25)
            addColor2 = mixColors(addColor1, QColor(0x339933), .25)

        if scheme.isDark():
            warningColor = colors.red
            hunkColor = colors.blue.lighter(125)
        else:
            warningColor = colors.red.darker(125)
            hunkColor = QColor(0x0050f0)

        cls.addBF.setBackground(addColor1)
        cls.delBF.setBackground(delColor1)

        # A side-by-side row with nothing across from it
        if scheme.diffFiller:
            cls.fillerBF.setBackground(scheme.diffFiller)
        else:
            cls.fillerBF.clearBackground()

        cls.doppelgangerAddCF.setBackground(addColor2)
        cls.doppelgangerDelCF.setBackground(delColor2)

        if scheme.diffHunkFg:
            # The built-in theme's own: a quiet, upright header
            cls.hunkCF.setFontItalic(False)
            cls.hunkCF.setForeground(scheme.diffHunkFg)
        else:
            cls.hunkCF.setFontItalic(True)
            cls.hunkCF.setForeground(hunkColor)

        cls.warningCF.setFontUnderline(True)
        cls.warningCF.setFontWeight(QFont.Weight.Bold)
        cls.warningCF.setBackground(scheme.backgroundColor)
        cls.warningCF.setForeground(warningColor)


@dataclass
class DiffDocument:
    document: QTextDocument
    lineData: list[LineData]
    pluses: int
    minuses: int
    maxLine: int
    oldHash: str
    newHash: str

    # Syntax highlighting
    oldLexJob: LexJob | None = None
    newLexJob: LexJob | None = None

    formatGeneration: int = 0
    "The DiffTextFormats.generation that the lines are painted in."

    class VeryLongLinesError(ValueError):
        pass

    class NoChangeError(ValueError):
        pass

    class BinaryError(ValueError):
        pass

    @staticmethod
    def fromPatch(patch: str, maxLineLength=0) -> DiffDocument:
        lineData: list[LineData] = []

        clumpID = 0
        numLinesInClump = 0
        perfectClumpTally = 0
        pluses = 0
        minuses = 0

        hunkID = -1
        oldLine = -1
        newLine = -1
        hunkLineNum = -1
        isBinary = False
        oldHash = ""
        newHash = ""

        for pos, endPos in iterateLines(patch):
            if maxLineLength and endPos - pos > maxLineLength:
                raise DiffDocument.VeryLongLinesError()

            firstChar = patch[pos]

            # Keep looking for first hunk
            if firstChar != "@" and hunkID < 0:
                if patch.startswith(("Binary files", "GIT binary patch"), pos, endPos):
                    isBinary = True
                elif patch.startswith("index ", pos, endPos):
                    # The 'index' line can be used to complete an existing delta with actual blob hashes
                    indexLineMatch = _indexLinePattern.match(patch, pos, endPos)
                    oldHash, newHash = indexLineMatch.groups()
                continue

            # Start new hunk
            if firstChar == "@":
                rawLine = patch[pos:endPos]
                oldLine, _dummy1, newLine, _dummy2, _dummy3 = _parseHunkHeader(rawLine)

                hunkID += 1
                hunkLineNum = -1
                hunkHeaderLD = LineData(text=rawLine, hunkPos=DiffLinePos(hunkID, -1),
                                        oldLineNo=oldLine, newLineNo=newLine)
                lineData.append(hunkHeaderLD)
                continue

            origin = firstChar

            # "No newline at end of file" (message might be localized)
            if origin == '\\':
                # Fix up the last LineData and don't create a new one.
                ld = lineData[-1]
                ld.text = ld.text.removesuffix("\n")
                ld.hiddenSuffix = "\n" + patch[pos:endPos]
                continue

            hunkLineNum += 1

            # Any lines that aren't +/- break up the current clump
            if origin not in "+-" and numLinesInClump != 0:
                # Process perfect clump (sum of + and - origins is 0)
                if numLinesInClump > 0 and perfectClumpTally == 0:
                    assert (numLinesInClump % 2) == 0, "line count should be even in perfect clumps"
                    clumpStart = len(lineData) - numLinesInClump
                    halfClump = numLinesInClump // 2
                    for doppel1 in range(clumpStart, clumpStart + halfClump):
                        doppel2 = doppel1 + halfClump
                        lineData[doppel1].doppelganger = doppel2
                        lineData[doppel2].doppelganger = doppel1

                # Start new clump
                clumpID += 1
                numLinesInClump = 0
                perfectClumpTally = 0

            ld = LineData(text=patch[pos+1:endPos],
                          hunkPos=DiffLinePos(hunkID, hunkLineNum),
                          origin=origin,
                          oldLineNo=-1 if origin == "+" else oldLine,
                          newLineNo=-1 if origin == "-" else newLine)

            if origin == '+':
                assert ld.newLineNo == newLine
                assert ld.oldLineNo == -1
                newLine += 1
                ld.clumpID = clumpID
                numLinesInClump += 1
                perfectClumpTally += 1
                pluses += 1
            elif origin == '-':
                assert ld.newLineNo == -1
                assert ld.oldLineNo == oldLine
                oldLine += 1
                ld.clumpID = clumpID
                numLinesInClump += 1
                perfectClumpTally -= 1
                minuses += 1
            else:
                assert origin == " ", f"unknown origin: {origin.encode('unicode_escape')!r}"
                assert ld.newLineNo == newLine
                assert ld.oldLineNo == oldLine
                newLine += 1
                oldLine += 1

            lineData.append(ld)

        if not lineData:
            if isBinary:
                raise DiffDocument.BinaryError()
            raise DiffDocument.NoChangeError()

        # Recreating a QTextDocument is faster than clearing any existing one.
        textDocument = QTextDocument()
        textDocument.setObjectName("DiffDocument")
        textDocument.setDocumentLayout(QPlainTextDocumentLayout(textDocument))

        diffDocument = DiffDocument(document=textDocument, lineData=lineData,
                                    pluses=pluses, minuses=minuses,
                                    maxLine=max(newLine, oldLine),
                                    oldHash=oldHash, newHash=newHash,
                                    formatGeneration=DiffTextFormats.generation)

        # Begin batching text insertions for performance.
        # This prevents Qt from recomputing the document's layout after every line insertion.
        cursor = QTextCursor(textDocument)
        cursor.beginEditBlock()

        # Build up document from the lineData array.
        diffDocument.buildTextDocument(cursor)

        # Emphasize doppelganger differences.
        diffDocument.formatDoppelgangerDiffs(cursor)

        # Done batching text insertions.
        cursor.endEditBlock()

        return diffDocument

    @staticmethod
    def _lineFormats(origin: str) -> tuple[QTextBlockFormat | None, QTextCharFormat | None]:
        """A line's block and character formats; None where it keeps the document's own."""
        if not origin:  # Hunk header
            return DiffTextFormats.hunkBF, DiffTextFormats.hunkCF
        if origin == '+':
            return DiffTextFormats.addBF, None
        if origin == '-':
            return DiffTextFormats.delBF, None
        return None, None

    @benchmark
    def buildTextDocument(self, cursor: QTextCursor):
        assert self.document.isEmpty()

        defaultBF = cursor.blockFormat()
        defaultCF = cursor.charFormat()
        showStrayCRs = settings.prefs.showStrayCRs
        isEmpty = True

        for ld in self.lineData:
            # Decide block format & character format
            bf, cf = self._lineFormats(ld.origin)
            if bf is None:
                bf = defaultBF
            if cf is None:
                cf = defaultCF

            # Process line ending
            trailer = ""
            if ld.text.endswith('\r\n'):
                trimBack = -2
                if showStrayCRs:
                    trailer = "<CRLF>"
            elif ld.text.endswith('\n'):
                trimBack = -1
            elif ld.text.endswith('\r'):
                trimBack = -1
                if showStrayCRs:
                    trailer = "<CR>"
            else:
                trailer = _("<no newline at end of file>")
                trimBack = None  # yes, None. This will cancel slicing.

            if isEmpty:
                ld.cursorStart = 0
            else:
                cursor.insertBlock()
                ld.cursorStart = cursor.position()

            cursor.setBlockFormat(bf)
            cursor.setBlockCharFormat(cf)
            cursor.insertText(ld.text[:trimBack])

            if trailer:
                ld.trailerLength = len(trailer)
                cursor.setCharFormat(DiffTextFormats.warningCF)
                cursor.insertText(trailer)

            ld.cursorEnd = cursor.position()
            isEmpty = False

    @benchmark
    def formatDoppelgangerDiffs(self, cursor: QTextCursor):
        if self.pluses == 0 or self.minuses == 0:  # Don't bother if there can't be any doppelgangers
            return

        doppelgangerBlocksQueue = []

        for lineNumber, line in enumerate(self.lineData):
            if line.doppelganger < 0:  # Skip lines without doppelgangers
                continue

            assert lineNumber != line.doppelganger, "line cannot be its own doppelganger"
            assert line.origin in "+-", "line with doppelganger must have origin"
            aheadOfDoppelganger = lineNumber < line.doppelganger

            if aheadOfDoppelganger:
                textA = line.text
                textB = self.lineData[line.doppelganger].text
                sm = difflib.SequenceMatcher(a=textA, b=textB)
                blocks = sm.get_matching_blocks()
                doppelgangerBlocksQueue.append(blocks)  # Set blocks aside for my doppelganger
            else:
                blocks = doppelgangerBlocksQueue.pop(0)  # Consume blocks set aside by my doppelganger

            if line.origin == "-":
                charFormat = DiffTextFormats.doppelgangerDelCF
            else:
                charFormat = DiffTextFormats.doppelgangerAddCF

            cursorPos = line.cursorStart
            oldBlockEnd = 0
            for blockStart, blockEnd in _invertMatchingBlocks(blocks, useA=aheadOfDoppelganger):
                assert blockStart >= oldBlockEnd

                # Advance Qt cursor (UTF-16!) to new doppelganger block
                cursorPos += qstringLength(line.text[oldBlockEnd: blockStart])
                cursor.setPosition(cursorPos, QTextCursor.MoveMode.MoveAnchor)

                # Move to end of doppelganger block and apply formatting
                cursorPos += qstringLength(line.text[blockStart: blockEnd])
                cursor.setPosition(cursorPos, QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(charFormat)

                oldBlockEnd = blockEnd

        assert not doppelgangerBlocksQueue, "should've consumed all doppelganger matching blocks!"

    def recolor(self) -> bool:
        """
        Paint the lines again in the current DiffTextFormats, after a switch
        between light and dark for instance. The document holds copies of the
        formats it was built with, so new colors don't reach it on their own.
        The text stays as it is, and so do a view's cursor and scroll position.

        Returns False if the lines were painted in the current colors already.
        """
        if self.formatGeneration == DiffTextFormats.generation:
            return False
        self.formatGeneration = DiffTextFormats.generation

        if self.document.isEmpty():  # Cleared by its view, nothing to paint
            return False

        # Nobody undoes a diff's colors: don't pile up a step for every line
        self.document.setUndoRedoEnabled(False)
        self._paintLines()
        return True

    @benchmark
    def _paintLines(self):
        plainCF = QTextCharFormat()
        keepAnchor = QTextCursor.MoveMode.KeepAnchor
        cursor = QTextCursor(self.document)
        cursor.beginEditBlock()

        for ld in self.lineData:
            blockFormat, charFormat = self._lineFormats(ld.origin)
            textEnd = ld.cursorEnd - ld.trailerLength

            if blockFormat is not None:
                cursor.setPosition(ld.cursorStart)
                cursor.setBlockFormat(blockFormat)

            if charFormat is not None:  # Hunk header
                cursor.setPosition(ld.cursorStart)
                cursor.setBlockCharFormat(charFormat)
                cursor.setPosition(textEnd, keepAnchor)
                cursor.setCharFormat(charFormat)
            elif ld.doppelganger >= 0:
                # Wipe the old emphasis, formatDoppelgangerDiffs puts it back below
                cursor.setPosition(ld.cursorStart)
                cursor.setPosition(textEnd, keepAnchor)
                cursor.setCharFormat(plainCF)

            if ld.trailerLength:
                cursor.setPosition(textEnd)
                cursor.setPosition(ld.cursorEnd, keepAnchor)
                cursor.setCharFormat(DiffTextFormats.warningCF)

        self.formatDoppelgangerDiffs(cursor)
        cursor.endEditBlock()


def _invertMatchingBlocks(blockList: list[difflib.Match], useA: bool) -> Iterator[tuple[int, int]]:
    px = 0

    for block in blockList:
        x1 = block.a if useA else block.b
        x2 = x1 + block.size

        if px != x1:
            yield px, x1

        px = x2
