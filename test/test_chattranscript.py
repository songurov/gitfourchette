# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
How an AI answer reads: prose as prose, code as code.
"""

from gitfourchette.forms.chattranscript import messageHtml, transcriptHtml
from .util import *

ANSWER = """\
Here is what changed in `repowidget.py`:

```python
def prepareForDeletion(self):
    self.diffView.prepareForDeletion()
```

That's all.
"""


def htmlOf(content, **kwargs):
    return messageHtml(content, None, QColor("#202020"), QColor("#e0e0e0"), "Menlo", **kwargs)


def testCodeBlockGetsItsOwnBox(qapp):
    html = htmlOf(ANSWER)
    assert "def prepareForDeletion(self):" in html
    # Qt paints a background on a table cell, not on a <pre>
    assert "<table" in html
    assert "background-color:#202020" in html
    assert "Menlo" in html


def testProseStaysProse(qapp):
    html = htmlOf(ANSWER)
    assert "Here is what changed" in html
    assert "That&#8217;s all." in html or "That's all." in html
    assert html.index("Here is what changed") < html.index("def prepareForDeletion")


def testInlineCodeIsTinted(qapp):
    html = htmlOf(ANSWER)
    start = html.index("Here is what changed")
    end = html.index("<table")
    prose = html[start:end]
    assert "repowidget.py" in prose
    assert "background-color:#202020" in prose


def testUnterminatedBlockIsStillCode(qapp):
    # The CLI streams its answer: half a code block is the normal case
    html = htmlOf("Look:\n\n```python\ndef half(")
    assert "<table" in html
    assert "def half(" in html


def testCodeWithoutALanguageIsLeftAlone(qapp):
    html = htmlOf("```\nplain <b>text</b>\n```")
    assert "<table" in html
    assert "plain &lt;b&gt;text&lt;/b&gt;" in html


def testEachMessageIsNamedAndSeparated(qapp):
    messages = [{"role": "user", "content": "what changed?"},
                {"role": "assistant", "content": "this and that"}]
    html = transcriptHtml(messages, lambda role: "You" if role == "user" else "Assistant")
    assert "<b>You</b>" in html
    assert "<b>Assistant</b>" in html
    assert "<hr" in html
    assert html.index("You") < html.index("Assistant")


def testDefaultsToTheSchemeTheDiffsUse(mainWindow):
    # transcriptHtml with no scheme asks the app for the one the diffs are read in
    html = transcriptHtml([{"role": "assistant", "content": "```python\nx = 1\n```"}],
                          lambda role: "Assistant")
    assert "<table" in html
    # The code is there, colored token by token by the app's own scheme
    plain = QTextDocumentFragment.fromHtml(html).toPlainText()
    assert "x = 1" in plain
    assert html.count("<span style=\"color:") >= 2
