# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.whatsnewdialog import WhatsNewDialog, loadReleases
from .util import *


def openWhatsNew(mainWindow) -> WhatsNewDialog:
    triggerMenuAction(mainWindow.menuBar(), "help/what")
    return findQDialog(mainWindow, "what’s new")


def testEveryReleaseOfTheYearIsThere(mainWindow):
    year, releases = loadReleases()
    assert year == 2026
    official = [r for r in releases if r.url.startswith("https://github.com/jorio/")]
    assert [r.version for r in official] == [
        "1.11.0", "1.10.0", "1.9.1", "1.9.0", "1.8.0", "1.7.1", "1.7.0", "1.6.0"]
    assert [r.date for r in releases] == sorted((r.date for r in releases), reverse=True)
    for release in releases:
        assert release.date.startswith(str(year)), release.version
        assert release.summary and release.highlights and release.contributors, release.version
    for release in official:
        assert release.url.endswith(f"/releases/tag/v{release.version}")
        assert "Iliyas Jorio" in release.contributors


def testWhatsNewOpensFromTheHelpMenu(mainWindow):
    dlg = openWhatsNew(mainWindow)
    text = dlg.browser.toPlainText()
    _year, releases = loadReleases()
    people = {name for r in releases for name in r.contributors}

    # A line about the year, then every release with its summary and its people
    assert "What’s new in 2026" in text
    assert "8 releases" in text and f"{len(people)} contributors" in text
    for release in releases:
        assert release.version in text
        assert release.summary in text
    assert "Thanks to: Iliyas Jorio, Jerry Hyun" in text
    assert "Workspaces preview" in text  # this build, on top of 1.11.0
    dlg.reject()


def testLinksOpenInTheBrowser(mainWindow):
    dlg = openWhatsNew(mainWindow)
    assert dlg.browser.openExternalLinks()
    assert 'href="https://github.com/jorio/gitfourchette/releases/tag/v1.11.0"' in dlg.browser.toHtml()
    dlg.reject()


def testWhatsNewIsOfferedOnHome(mainWindow):
    """It needs no repo, so Quick Launch offers it on Home too."""
    from .test_quicklaunch import openPalette, query
    palette = openPalette(mainWindow)
    query(palette, "what")
    assert palette.currentEntry().title == "What’s New…"
    QTest.keyClick(palette.lineEdit, Qt.Key.Key_Return)
    findQDialog(mainWindow, "what’s new").reject()
