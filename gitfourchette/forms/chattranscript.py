# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
An AI conversation as rich text: prose reads as prose, and code reads as code
— its own block, in the diff's font and colors, instead of a run of gray text.
"""

from __future__ import annotations

import re

from gitfourchette import settings
from gitfourchette.qt import *
from gitfourchette.syntax.colorscheme import ColorScheme
from gitfourchette.toolbox import escape, mixColors

FENCE = re.compile(r"^[ \t]*```([^\n`]*)\n(.*?)(?:^[ \t]*```[ \t]*$|\Z)", re.DOTALL | re.MULTILINE)
"A fenced code block. An unterminated one (the CLI is still writing it) runs to the end."

INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")


def answerHtml(content: str, scheme: ColorScheme | None = None, palette: QPalette | None = None) -> str:
    """
    One answer: its prose as Markdown, its code in a box of its own, in the
    colors the diffs are read in.
    """
    palette = palette or QApplication.palette()
    scheme = scheme if scheme is not None else settings.prefs.syntaxHighlightingScheme()
    window = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.Text)
    return messageHtml(content, scheme, _codeBackground(scheme, window, text),
                       text, settings.prefs.monoFont().family())


def transcriptHtml(messages, roleLabel, scheme: ColorScheme | None = None, palette: QPalette | None = None) -> str:
    """
    The whole conversation. `roleLabel` names a message's author ("You" or
    "Assistant"); `scheme` colors the code, and defaults to the one the diffs
    are read in.
    """
    palette = palette or QApplication.palette()
    scheme = scheme if scheme is not None else settings.prefs.syntaxHighlightingScheme()

    window = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.Text)
    codeBg = _codeBackground(scheme, window, text)
    rule = mixColors(window, text, 0.25).name()
    fontFamily = settings.prefs.monoFont().family()

    blocks = []
    for index, message in enumerate(messages):
        if index:
            blocks.append(f'<hr style="border: 1px solid {rule};">')
        blocks.append(f'<p><b>{escape(roleLabel(message["role"]))}</b></p>')
        blocks.append(messageHtml(message.get("content", ""), scheme, codeBg, text, fontFamily))
    return "\n".join(blocks)


def messageHtml(content: str, scheme: ColorScheme | None, codeBg: QColor,
                textColor: QColor, fontFamily: str) -> str:
    """One message: its prose as Markdown, its code blocks as code."""
    html = []
    position = 0
    for match in FENCE.finditer(content):
        html.append(proseHtml(content[position:match.start()], codeBg))
        html.append(codeBlockHtml(match.group(2), match.group(1).strip(),
                                  scheme, codeBg, textColor, fontFamily))
        position = match.end()
    html.append(proseHtml(content[position:], codeBg))
    return "\n".join(part for part in html if part)


def proseHtml(text: str, codeBg: QColor) -> str:
    """Markdown, as Qt renders it, with inline code given a tint of its own."""
    if not text.strip():
        return ""
    placeholders: list[str] = []

    def stash(match: re.Match) -> str:
        placeholders.append(match.group(1))
        return f"\u0001{len(placeholders) - 1}\u0002"

    text = INLINE_CODE.sub(stash, text)

    document = QTextDocument()
    document.setMarkdown(text, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
    body = _body(document.toHtml())

    for index, code in enumerate(placeholders):
        tinted = (f'<span style="background-color:{codeBg.name()}; '
                  f'font-family:\'{settings.prefs.monoFont().family()}\';">'
                  f'&nbsp;{escape(code)}&nbsp;</span>')
        body = body.replace(f"\u0001{index}\u0002", tinted)
    return body


def codeBlockHtml(code: str, language: str, scheme: ColorScheme | None,
                  codeBg: QColor, textColor: QColor, fontFamily: str) -> str:
    """
    A code block in a box of its own. Qt's rich text paints a background on a
    table cell but not on a <pre>, so the box is a one-cell table.
    """
    code = code.rstrip("\n")
    inner = highlightedCode(code, language, scheme, textColor)
    rim = mixColors(codeBg, textColor, 0.18).name()
    return (f'<table width="100%" cellpadding="8" cellspacing="0" border="1" '
            f'bordercolor="{rim}" style="background-color:{codeBg.name()};"><tr><td>'
            f'<pre style="font-family:\'{fontFamily}\'; margin:0;">{inner}</pre>'
            f'</td></tr></table>')


def highlightedCode(code: str, language: str, scheme: ColorScheme | None, textColor: QColor) -> str:
    """The code, colored by the same scheme the diffs use. Plain text if we can't lex it."""
    lexer = _lexer(language)
    if lexer is None or scheme is None or not scheme:
        return escape(code)

    from pygments import lex

    spans = []
    for tokenType, value in lex(code, lexer):
        if not value:
            continue
        color = _tokenColor(scheme, tokenType)
        piece = escape(value)
        spans.append(f'<span style="color:{color.name()};">{piece}</span>' if color else piece)
    return "".join(spans) or escape(code)


def _tokenColor(scheme: ColorScheme, tokenType) -> QColor | None:
    """Pygments token types fall back to their parent, and so do their colors."""
    while tokenType is not None:
        charFormat = scheme.scheme.get(tokenType)
        if charFormat is not None:
            brush = charFormat.foreground()
            if brush.style() != Qt.BrushStyle.NoBrush:
                return brush.color()
        tokenType = getattr(tokenType, "parent", None)
    return None


def _lexer(language: str):
    if not language:
        return None
    try:
        from pygments.lexers import get_lexer_by_name
        return get_lexer_by_name(language.lower(), stripnl=False, ensurenl=False)
    except Exception:  # no lexer for this language, or pygments isn't happy with it
        return None


def _codeBackground(scheme: ColorScheme | None, window: QColor, text: QColor) -> QColor:
    """
    A shade apart from the page, whichever way the page goes. The scheme's own
    background is no good here: it matches the page in the theme it belongs to,
    and a box you can't see isn't a box.
    """
    return mixColors(window, text, 0.09)


def _body(html: str) -> str:
    match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL)
    return match.group(1).strip() if match else html
