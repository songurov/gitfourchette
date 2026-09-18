# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import json
import sys
from pathlib import Path
from textwrap import dedent

import pygit2
import pygments

from gitfourchette.forms.prefsdialog import availableLocaleCodes, localeCodeToLanguageName
from gitfourchette.forms.ui_aboutdialog import Ui_AboutDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette import settings

WEBSITE_URL = "https://gitfourchette.org"
DONATE_URL = "https://ko-fi.com/jorio"
TRANSLATE_URL = "https://gitfourchette.org/localization"


def getPygit2FeatureStrings():
    return [f.name.lower() for f in pygit2.enums.Feature if f & pygit2.features]


def simpleLink(url):
    return f"<a href='{url}'>{url}</a>"


# The flag shown next to a language: the country most of its speakers live in.
# Traditional Chinese gets none - any flag there would be a political statement.
LANGUAGE_FLAGS = {
    "cs": "CZ", "de": "DE", "es": "ES", "fr": "FR", "it": "IT", "ko": "KR", "pt": "PT",
    "pt_BR": "BR", "ro": "RO", "ru": "RU", "tr": "TR", "uk": "UA", "zh_Hans": "CN",
}


def flagEmoji(countryCode: str) -> str:
    """"MD" -> 🇲🇩: two regional indicator symbols."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in countryCode.upper() if "A" <= c.upper() <= "Z")


def translatorRow(lang: str, people: list) -> str:
    """
    One language of the translator credits. A translator is a name, or
    {"name", "url", "country"}: a linked name, and the country they translate
    from - which then names the row and picks its flag ("Română (Moldova)").
    """
    names = []
    countries = set()
    for person in people:
        if isinstance(person, str):
            names.append(escape(person))
            continue
        name = escape(person["name"])
        names.append(f"<a href='{escape(person['url'])}'>{name}</a>" if person.get("url") else name)
        if person.get("country"):
            countries.add(person["country"].upper())

    language = localeCodeToLanguageName(lang)
    country = next(iter(countries)) if len(countries) == 1 else ""
    if country:
        # "Moldova", in its own language's words when Qt knows them
        territory = QLocale(f"{lang.split('_')[0]}_{country}").nativeTerritoryName() or country
        language = f"{language} ({territory.removeprefix('Republica ')})"
    flag = flagEmoji(country or LANGUAGE_FLAGS.get(lang, ""))
    label = f"{flag} {language}" if flag else language
    return f"<tr><th>{label}:</th><td>{'<br>'.join(names)}</td></tr>\n"


class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        self.ui = Ui_AboutDialog()
        self.ui.setupUi(self)

        self.urlToolTip = UrlToolTip(self)
        self.urlToolTip.install()

        appVersion = QApplication.applicationVersion()
        appName = qAppName()

        self.setWindowTitle(self.windowTitle().format(appName))

        buildInfoItems = [
            "Flatpak" if FLATPAK else "",
            "AppImage" if "APPIMAGE" in INITIAL_ENVIRONMENT else "",
            APP_FREEZE_DATE,
            APP_FREEZE_COMMIT[:7]
        ]
        buildInfoItems = [s for s in buildInfoItems if s]
        buildInfo = f"({', '.join(buildInfoItems)})" if buildInfoItems else ""

        tagline = _("The comfortable Git UI for Linux.")

        # ---------------------------------------------------------------------
        # Header

        pixmap = QPixmap("assets:icons/gitfourchette")
        pixmap.setDevicePixelRatio(4)
        self.ui.iconLabel.setPixmap(pixmap)

        self.ui.header.setText(dedent(f"""\
            <span style="font-size: x-large"><b>{appName}</b></span>
            <br>{tagline}
            <br>{simpleLink(WEBSITE_URL)}"""))

        versionText = _("Version {0}", appVersion)
        self.ui.versionLabel.setText(dedent(f"""\
            <span style='color:{mutedTextColorHex(self)}'><b>{versionText}</b> {buildInfo}
            <br>Copyright © 2026 Iliyas Jorio"""))

        # ---------------------------------------------------------------------
        # About page

        self.ui.mugshot.setText("")
        self.ui.mugshot.setPixmap(QPixmap("assets:icons/mug"))

        # ---------------------------------------------------------------------
        # Components page

        try:
            from gitfourchette.mount.treemount import fuse
            fuseInfo = _("with {0}", f"FUSE {fuse.fuse_version_major}.{fuse.fuse_version_minor}")
        except (ImportError, OSError, AttributeError):
            fuseInfo = _("(not available)")

        self.ui.aboutBlurb.setText(dedent(f"""\
            <style>
                a {{ font-weight: bold; }}
                hr {{ background: gray; }}
                table {{ font-size: 8pt; margin-top: 0em; }}
                th {{ text-align: left; padding-right: 1em; color: gray; }}
            </style>
            <p>{linkify(_("If {app} helps you get work done, please consider [making a small donation].", app=appName), DONATE_URL)}</p>
            <p>{_("Thank you for your support!")}</p>
            <hr>
            <table cellspacing=0 cellpadding=0>
            <tr><th colspan=2>{appName} {appVersion}</th></tr>
            <tr><th>Git</th><td>{GitDriver.gitVersion() or _("(unknown version)")} ({settings.prefs.gitPath})</td></tr>
            <tr><th>LFS</th><td>{GitDriver.lfsVersion() or _("(not available)")}</td></tr>
            <tr><th>pygit2</th><td>{pygit2.__version__}</td></tr>
            <tr><th>libgit2</th><td>{pygit2.LIBGIT2_VERSION} ({', '.join(getPygit2FeatureStrings())})</td></tr>
            <tr><th>{QT_BINDING}</th><td>{QT_BINDING_VERSION}</td></tr>
            <tr><th>Qt</th><td>{qVersion()}</td></tr>
            <tr><th>mfusepy</th><td>{fuseInfo}</td></tr>
            <tr><th>Pygments</th><td>{pygments.__version__}</td></tr>
            <tr><th>Python</th><td>{'.'.join(str(i) for i in sys.version_info)}</td></tr>
            </table>
        """))

        # ---------------------------------------------------------------------
        # Acknowledgments page

        contributorCreditsPath = Path(QFile("assets:/contributors.txt").fileName())
        contributorCredits = contributorCreditsPath.read_text("utf-8")
        contributorCredits = contributorCredits.removeprefix("Iliyas Jorio\n")
        contributorCredits = f"<center style='white-space: pre'>{contributorCredits}</center>"

        translatorCreditsPath = Path(QFile("assets:lang/credits.json").fileName())
        translatorCredits = json.loads(translatorCreditsPath.read_text("utf-8"))
        translatorFilter = availableLocaleCodes()
        translatorMarkup = "<center><table>" + "".join(
            translatorRow(lang, people)
            for lang, people in translatorCredits.items()
            if lang in translatorFilter
        ) + "</table></center>"

        ackText = [
            _("Additional contributions by:") + contributorCredits,

            linkify(_("Translations welcome!"), TRANSLATE_URL)
            + " "
            + _("Brought to your native language by:")
            + translatorMarkup,

            _("Special thanks to Marc-Alexandre Espiaut for beta testing."),
        ]

        ackMarkup = "<style>th { text-align: right; padding-right: 8px; color: gray; }</style>"
        ackMarkup += paragraphs(*ackText)

        self.ui.ackBlurb.setText(ackMarkup)

        # ---------------------------------------------------------------------
        # License page

        self.ui.licenseBlurb.setText(dedent(f"""\
            <p>{appName} is free software: you can redistribute it and/or
            modify it under the terms of the GNU General Public License
            version 3 as published by the Free Software Foundation.</p>
            <p>{appName} is distributed in the hope that it will be useful,
            but WITHOUT ANY WARRANTY; without even the implied warranty of
            MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. For more
            details, read the full terms of the
            <a href='https://www.gnu.org/licenses/gpl-3.0.txt'>GNU General
            Public License, version 3</a>.</p>"""))

    @staticmethod
    def popUp(parent: QWidget):
        dialog = AboutDialog(parent)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        return dialog
