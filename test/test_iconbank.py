# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pathlib
import re

from .util import *


# Use mainWindow fixture to make sure the temp icon cache is properly reset
@pytest.mark.skipif(QT5, reason="Qt 5: can't specify devicePixelRatio in QIcon.pixmap()")
def testStockIconImgTagDpr(mainWindow):
    from gitfourchette.toolbox import iconbank

    def extractSrc(imgTag):
        return re.search(r"<img src='([^']+)'", imgTag).group(1)

    pixmap = QPixmap()

    # DPR=1 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=1)
    src = extractSrc(tag)
    assert src.startswith("assets:icons/")
    pixmap.load(src)
    assert pixmap.size() == QSize(16, 16)
    srcDpr1 = src

    # DPR=1 cache hit
    tag = iconbank.stockIconImgTag("git-head", dpr=1)
    src = extractSrc(tag)
    assert src == srcDpr1

    # DPR=2 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=2)
    src = extractSrc(tag)
    srcDpr2 = src
    assert src.startswith(qTempDir())
    pixmap.load(src)
    assert pixmap.size() == QSize(32, 32)

    # DPR=2 cache hit
    tag = iconbank.stockIconImgTag("git-head", dpr=2)
    src = extractSrc(tag)
    assert src == srcDpr2

    # DPR=1.5 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=1.5)
    src = extractSrc(tag)
    pixmap.load(src)
    assert pixmap.size() == QSize(24, 24)


def _rendered(icon: QIcon) -> QImage:
    return icon.pixmap(16, 16).toImage()


def testTaskIconsAreAllOurOwn(mainWindow):
    """Every task that shows an icon must have one of ours to show."""

    from gitfourchette.tasks.taskbook import TaskBook
    from gitfourchette.toolbox import stockIcon

    assert TaskBook.icons, "expecting the task book to name some icons"
    for taskClass, iconId in TaskBook.icons.items():
        assert not stockIcon(iconId).isNull(), f"{taskClass.__name__} wants a missing icon {iconId!r}"


def testForeignIconNamesNeverReachTheDesktopTheme(mainWindow):
    """
    The app still calls some icons by their freedesktop names. Left to the
    desktop's icon theme, those come out in somebody else's style - usually
    full color, next to our flat line art.
    """

    from gitfourchette.toolbox import stockIcon

    assert _rendered(stockIcon("vcs-branch")) == _rendered(stockIcon("git-branch"))
    assert _rendered(stockIcon("user-identity")) == _rendered(stockIcon("git-identity"))
    assert _rendered(stockIcon("application-exit")) == _rendered(stockIcon("exit"))
    assert _rendered(stockIcon("SP_TrashIcon")) == _rendered(stockIcon("trash"))

    # A name we have no answer for fails here, rather than in a screenshot
    with pytest.raises(AssertionError):
        stockIcon("document-new")


def testEverySemanticIconUsesTheMonochromePalette():
    """Action and status icons must not quietly bring back hardcoded hues."""

    iconDir = pathlib.Path(__file__).parents[1] / "gitfourchette/assets/icons"
    semanticIcons = [
        "achtung", "git-discard", "git-discard-lines", "git-head-detached",
        "git-stage", "git-stage-lines", "git-unstage", "git-unstage-lines",
        "go-newer", "go-older", "gpg-verify-bad", "gpg-verify-cantcheck",
        "gpg-verify-expired", "gpg-verify-good-trusted", "gpg-verify-good-untrusted",
        "input-validated", "sigkill", "status_a", "status_d", "status_m",
        "status_r", "status_t", "status_u", "status_x", "urgent-tab",
    ]
    hardcodedColor = re.compile(
        r"#[0-9a-f]{3,8}|(?:fill|stroke)(?:=|:)['\"]?(?:red|green|orange|yellow|blue|purple)",
        re.IGNORECASE)
    for iconName in semanticIcons:
        svg = (iconDir / f"{iconName}.svg").read_text()
        assert not hardcodedColor.search(svg), iconName
