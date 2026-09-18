# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import importlib.util
import json
import pathlib

from gitfourchette.forms.aboutdialog import AboutDialog, flagEmoji
from .util import *


def testTheRomanianTranslatorIsCreditedWithMoldovaALinkAndAFlag(mainWindow):
    triggerMenuAction(mainWindow.menuBar(), "help/about")
    dlg: AboutDialog = findQDialog(mainWindow, "about")
    markup = dlg.ui.ackBlurb.text()

    assert f"{flagEmoji('MD')} Română (Moldova):" in markup
    assert "<a href='https://www.linkedin.com/in/songurov'>Songurov Fiodor</a>" in markup
    # Every other language gets its flag too
    assert f"{flagEmoji('RU')} Русский:" in markup
    assert f"{flagEmoji('CZ')} Čeština:" in markup
    dlg.reject()


def testFlagEmoji():
    assert flagEmoji("MD") == "\U0001F1F2\U0001F1E9"
    assert flagEmoji("fr") == "\U0001F1EB\U0001F1F7"
    assert flagEmoji("") == ""


def _updateResources():
    rootDir = pathlib.Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location("update_resources", rootDir / "update_resources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def testRegeneratingCreditsFromWeblateKeepsWhatWeblateDoesntKnow(tempDir):
    updateResources = _updateResources()
    langDir = pathlib.Path(tempDir.name)
    updateResources.LANG_DIR = str(langDir)
    moldova = {"name": "Songurov Fiodor", "url": "https://www.linkedin.com/in/songurov", "country": "MD"}
    linkedRussian = {"name": "Alex Nadzharov", "url": "https://example.com/alex"}
    (langDir / "credits.json").write_text(json.dumps({"ro": [moldova], "ru": [linkedRussian]}))

    report = [{"Russian": [
        {"full_name": "Abduloh Raupov", "username": "abduloh", "change_count": 10},
        {"full_name": "Alex Nadzharov", "username": "alex", "change_count": 2},
    ]}]
    reportPath = langDir / "report.json"
    reportPath.write_text(json.dumps(report))
    updateResources.formatTranslatorCredits(str(reportPath))

    credits = json.loads((langDir / "credits.json").read_text())
    assert credits["ru"] == ["Abduloh Raupov", linkedRussian]  # the plain name got its link back
    assert credits["ro"] == [moldova]  # not on Weblate: kept as is
