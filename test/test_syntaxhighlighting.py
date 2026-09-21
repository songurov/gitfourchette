# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from .util import *

from gitfourchette.syntax import LexJobCache, LexJob
from gitfourchette.nav import NavLocator

SAMPLE_CODE = """\
'''
hello multiline comment
such advanced lexing
'''

from ark import Bird

class Duck(Bird):
    def __init__(self, *args, **kwargs):
        print("quack")
"""


def digestFormatRange(formatRange: QTextLayout.FormatRange):
    start = formatRange.start
    length = formatRange.length
    isStyled = formatRange.format.foreground().color() != QColor(Qt.GlobalColor.black)
    return (start, length, isStyled)


def testDeferredSyntaxHighlighting(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Write sample code, with enough tokens to require a round-trip in LexJob
    writeFile(f"{wd}/hello.py", SAMPLE_CODE * 500)

    rw = mainWindow.openRepo(wd)

    commentLine = rw.diffView.document().findBlockByLineNumber(2)
    importLine = rw.diffView.document().findBlockByLineNumber(6)
    assert commentLine.text() == "hello multiline comment"
    assert importLine.text() == "from ark import Bird"

    assert not rw.diffView.highlighter.newLexJob.lexingComplete

    # Check low-quality lexing of comment line
    QTest.qWait(0)
    formatRange = commentLine.layout().formats()[0]
    assert digestFormatRange(formatRange) == (0, len("hello"), False)

    # Low-quality lexing of import line should suffice
    formatRange = importLine.layout().formats()[0]
    assert digestFormatRange(formatRange) == (0, len("from"), True)

    # Let LexJob finish its high-quality highlighting
    while not rw.diffView.highlighter.newLexJob.lexingComplete:
        QTest.qWait(0)
    QTest.qWait(0)  # Let highlighter respond

    # Now the inside of the multiline comment should be properly formatted
    formatRange = commentLine.layout().formats()[0]
    assert digestFormatRange(formatRange) == (0, len("hello multiline comment"), True)


def testLexJobCaching(tempDir, mainWindow):
    GFApplication.applyPrefs(largeFileThresholdKB=0)

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/aaaa.empty", "")  # first file is empty to avoid starting a LexJob off the bat
    writeFile(f"{wd}/big.py", SAMPLE_CODE * 3000)  # enough tokens to require LexJob round-trip
    writeFile(f"{wd}/small.py", SAMPLE_CODE * 4)

    rw = mainWindow.openRepo(wd)

    def getNewLexJob() -> LexJob:
        return rw.diffView.highlighter.newLexJob

    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()

    # Remember which job handles big.py
    job = getNewLexJob()

    assert not getNewLexJob().lexingComplete
    waitUntilTrue(lambda: getNewLexJob().scheduler.isActive(), interval=0)
    assert not getNewLexJob().lexingComplete

    # Switch away from DiffView, put LexJob on ice
    rw.jump(NavLocator.inUnstaged("aaaa.empty"), check=True)
    assert not rw.diffView.isVisible()
    assert not getNewLexJob().scheduler.isActive()

    # Switch back to DiffView, restore LexJob
    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()
    assert job is getNewLexJob()
    assert getNewLexJob().scheduler.isActive()

    # Change document in DiffView
    rw.jump(NavLocator.inUnstaged("small.py"), check=True)
    assert job is not getNewLexJob()

    # Restore document
    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()
    assert job is getNewLexJob()


@pytest.mark.skipif(WINDOWS, reason="TODO: flaky on Windows")
def testEvictLexJobFromCache(tempDir, mainWindow):
    GFApplication.applyPrefs(largeFileThresholdKB=1_000_000)
    assert not LexJobCache.cache
    assert LexJobCache.totalFileSize == 0

    wd = unpackRepo(tempDir)

    bigChunk = SAMPLE_CODE * 100
    bigChunk += "\n# Differentiator: XXXX"

    # Make one too many copies of the file to fit in LexJob cache
    numCopies = 1 + LexJobCache.MaxBudget // len(bigChunk)
    for i in range(numCopies):
        blobContents = bigChunk.removesuffix("XXXX") + f"{i:04}"
        writeFile(f"{wd}/copy{i:04}.py", blobContents)

    # Create a giant file that doesn't fit in cache
    writeFile(f"{wd}/giantfile.py", SAMPLE_CODE * (1 + LexJobCache.MaxBudget // len(SAMPLE_CODE)))

    rw = mainWindow.openRepo(wd)

    def getNewLexJob() -> LexJob:
        return rw.diffView.highlighter.newLexJob

    # Remember which LexJob handles copy0000.py
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("copy0000.py"))
    job = getNewLexJob()

    # Check that jumping back and forth to copy0000.py reuses the cached LexJob
    rw.jump(NavLocator.inUnstaged("copy0001.py"), True)
    assert job is not getNewLexJob()
    # Giant file that exceeds cache size shouldn't evict our old job
    rw.jump(NavLocator.inUnstaged("giantfile.py"), True)
    assert rw.diffView.isVisible()  # make we're not showing the "diff too large" message
    assert job is not getNewLexJob()
    rw.jump(NavLocator.inUnstaged("copy0000.py"), True)
    assert job is getNewLexJob()

    # Start lexing every file.
    # Touching the last file should cause copy0000.py's LexJob to be evicted.
    for i in range(numCopies):
        rw.jump(NavLocator.inUnstaged(f"copy{i:04}.py"), check=True)

    # Jump back to copy0000.py
    # Should start a new LexJob because it's been evicted
    rw.jump(NavLocator.inUnstaged("copy0000.py"), check=True)
    assert job is not getNewLexJob()


# Simple coverage test
def testSyntaxHighlightingNullOid(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell(f"""
        echo {shlex.quote(SAMPLE_CODE)} > hello.py
        git add hello.py
        rm hello.py
    """, wd)

    mainWindow.openRepo(wd)


# Simple coverage test
def testSyntaxHighlightingEmptyOid(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell(f"""
        touch hello.py
        git add hello.py
        echo {shlex.quote(SAMPLE_CODE)} > hello.py
    """, wd)

    mainWindow.openRepo(wd)


def testSyntaxHighlightingFillInFallbackTokenTypes(tempDir, mainWindow):
    # YAML has bespoke token types that aren't part of the standard Pygments token set,
    # e.g. Token.Literal.Scalar.Plain, Token.Punctuation.Indicator.
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/hello.yml", "- name: Hello\n")

    from gitfourchette.settings import prefs
    scheme = prefs.syntaxHighlightingScheme()
    numKnownTokens1 = len(scheme.highContrastScheme)

    mainWindow.openRepo(wd)
    numKnownTokens2 = len(scheme.highContrastScheme)
    assert numKnownTokens2 > numKnownTokens1


def testWhitespaceHighlighting(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    GFApplication.applyPrefs(showWhitespace=True)

    for space in [" ", "\t", "\xA0"]:
        writeFile(f"{wd}/hello.txt", f"hello{space}space\n")
        rw.refreshRepo()
        QTest.qWait(0)  # wait for syntax highlighting to finish

        doc: QTextDocument = rw.diffView.document()
        block = doc.findBlockByNumber(1)
        formatRanges = block.layout().formats()

        # In plain text files, the highlighter only applies formatting to
        # whitespace. Non-space text is not formatted. Make sure we apply
        # formatting to all kinds of whitespace rendered by ShowTabsAndSpaces.
        assert formatRanges
        for span in formatRanges:
            token = block.text()[span.start: span.start + span.length]
            assert token == space


def testHidingDiffAfterLexJobIsGone(tempDir, mainWindow):
    """
    Nothing owns a LexJob - they're kept alive by refcounting - so one can be
    collected while a highlighter still lists it. Hiding the diff must not
    reach into the dead job. (Used to crash on the way out of the app:
    "wrapped C/C++ object of type QTimer has been deleted".)
    """

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/hello.py", SAMPLE_CODE * 500)

    rw = mainWindow.openRepo(wd)
    highlighter = rw.diffView.highlighter
    assert highlighter.lexJobs, "expecting the diff to be lexed"

    doomedJob = highlighter.lexJobs[0]
    destroyCppObject(doomedJob)
    assert doomedJob not in highlighter.lexJobs, "a dead job should be dropped at once"

    # Every path that walks the jobs must survive it
    highlighter.onParentVisibilityChanged(False)
    highlighter.onParentVisibilityChanged(True)
    highlighter.rehighlight()
    highlighter.stopLexJobs()


def testSideBySideSyntaxHighlighting(tempDir, mainWindow):
    """
    Both panes of the side-by-side view color the code, and a line sitting on
    a red or green tint gets the colors that stand out on it.
    """

    wd = unpackRepo(tempDir)
    before = "def a():\n    return 1\n\ndef b():\n    return 2\n\nb()\n"
    writeFile(f"{wd}/duck.py", before)
    with RepoContext(wd) as repo:
        repo.index.add("duck.py")
        repo.index.write()
    writeFile(f"{wd}/duck.py", before.replace("return 2", "return 3"))

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("duck.py"), check=True)
    GFApplication.applyPrefs(sideBySideDiff=True)
    side = rw.diffArea.sideBySideDiffView
    # Give the shared lex job a chance to run; the panes must be colored by
    # the time it's done (and if nothing keeps it going, they never are)
    job = rw.diffView.highlighter.newLexJob
    deadline = QDeadlineTimer(2000)
    while not job.lexingComplete and not deadline.hasExpired():
        QTest.qWait(10)
    QTest.qWait(0)  # let the highlighter respond to the last pulse

    def keyword(view, row, word):
        """Where the keyword is colored in the row, and in what color."""
        block = view.document().find(row).block()
        assert block.isValid(), f"no row {row!r}"
        at = block.text().index(word)
        spans = [s for s in block.layout().formats() if s.start <= at < s.start + s.length]
        assert len(spans) == 1, f"expected {word!r} to be colored once, got {len(spans)} spans"
        return spans[0].start, spans[0].format.foreground().color().name()

    context = keyword(side.newView, "return 1", "return")
    changed = keyword(side.newView, "return 3", "return")
    removed = keyword(side.oldView, "return 2", "return")

    # The coloring starts at the code, not at the line number in front of it
    assert context[0] == side.newView.document().find("return 1").block().text().index("return")
    # A line on a tint gets the high-contrast color, a plain line the usual one
    assert changed[1] != context[1]
    assert removed[1] == changed[1]
    # The old pane is colored too, not just the new one
    assert keyword(side.oldView, "return 1", "return")[1] == context[1]


def testLineBeyondWhatWasLexedDoesNotRaise(tempDir, mainWindow):
    """
    A document can outrun the data its lexer was given - a last line with no
    newline, a blob that changed under a view still showing it. Asking for a
    line the lexer never produced must come back empty, not as an exception
    dialog over the diff someone was reading.
    """
    from pygments.lexers import PythonLexer

    job = LexJob(PythonLexer(), SAMPLE_CODE.encode(), "beyond.py")
    while not job.lexingComplete:
        job.lexChunk()

    lastLexed = max(job.hqTokenMap)
    assert job.tokens(lastLexed, "") is not None
    assert job.tokens(lastLexed + 500, "whatever the document says") == []
