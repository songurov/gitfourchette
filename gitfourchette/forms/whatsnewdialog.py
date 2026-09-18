# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Help > What's New: this year's releases, each summed up in a sentence or two,
with its highlights, the people who made it, and a link to the full notes.

The content lives in assets/whatsnew.json. Summaries and highlights are written
by hand from CHANGELOG.md; contributors come from `git shortlog` over each
release's range of tags.
"""

import dataclasses
import json
from html import escape

from gitfourchette.localization import *
from gitfourchette.qt import *

WHATSNEW_ASSET = "assets:whatsnew.json"


@dataclasses.dataclass(frozen=True)
class Release:
    version: str
    date: str
    url: str
    summary: str
    highlights: list[str]
    contributors: list[str]


def loadReleases() -> tuple[int, list[Release]]:
    """The year, and its releases newest first."""
    file = QFile(WHATSNEW_ASSET)
    if not file.open(QIODevice.OpenModeFlag.ReadOnly):
        return 0, []
    try:
        data = json.loads(bytes(file.readAll()).decode("utf-8"))
    finally:
        file.close()
    releases = [Release(**r) for r in data.get("releases", [])]
    releases.sort(key=lambda r: r.date, reverse=True)
    return data.get("year", 0), releases


def releasesHtml(year: int, releases: list[Release]) -> str:
    locale = QLocale()
    people = {name for r in releases for name in r.contributors}
    official = [r for r in releases if r.url.startswith("https://github.com/jorio/")]

    parts = [
        f"<h2>{escape(_('What’s new in {0}', year))}</h2>",
        "<p>" + escape(_n("{n} release", "{n} releases", len(official))) + " · "
        + escape(_n("{n} contributor", "{n} contributors", len(people))) + "</p>",
    ]
    for release in releases:
        date = QDate.fromString(release.date, "yyyy-MM-dd")
        when = locale.toString(date, QLocale.FormatType.LongFormat) if date.isValid() else release.date
        parts.append(f"<h3>{escape(release.version)} <small>— {escape(when)}</small></h3>")
        parts.append(f"<p>{escape(release.summary)}</p>")
        if release.highlights:
            parts.append("<ul>" + "".join(f"<li>{escape(h)}</li>" for h in release.highlights) + "</ul>")
        if release.contributors:
            thanks = escape(_("Thanks to: {0}", ", ".join(release.contributors)))
            parts.append(f"<p><small>{thanks}</small></p>")
        parts.append(f"<p><a href=\"{escape(release.url)}\">{escape(_('Full release notes'))}</a></p>")
    return "\n".join(parts)


class WhatsNewDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("WhatsNewDialog")
        self.setWindowTitle(_("What’s New"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(640, 720)

        year, self.releases = loadReleases()

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(releasesHtml(year, self.releases))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.browser)
        layout.addWidget(buttons)
