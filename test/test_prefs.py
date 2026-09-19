# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import gettext
import textwrap

import pytest

from gitfourchette import settings
from gitfourchette.forms.prefsdialog import PrefsDialog
from gitfourchette.nav import NavLocator
from gitfourchette.toolbox.fontpicker import FontPicker
from .util import *

FORK_LANGUAGES = ["ro", "ru", "tr"]
"""Languages this build translates itself. The others come from upstream."""


class _MissingTranslation(gettext.NullTranslations):
    MISSING = "<missing>"

    def gettext(self, message):
        return self.MISSING

    def pgettext(self, context, message):
        return self.MISSING


def assertTranslatedInForkLanguages(*msgids: str, context=""):
    for lang in FORK_LANGUAGES:
        with open(QFile(f"assets:lang/{lang}.mo").fileName(), "rb") as moFile:
            catalog = gettext.GNUTranslations(moFile)
        catalog.add_fallback(_MissingTranslation())
        for msgid in msgids:
            text = catalog.pgettext(context, msgid) if context else catalog.gettext(msgid)
            assert text not in ("", _MissingTranslation.MISSING), f"{lang}: {msgid!r} isn't translated"


def testPrefsDialog(tempDir, mainWindow):
    def openPrefs() -> PrefsDialog:
        triggerMenuAction(mainWindow.menuBar(), "file/settings")
        return findQDialog(mainWindow, "settings")

    # Open a repo so that refreshPrefs functions are exercised in coverage
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)

    # Open prefs, reset to first tab to prevent spillage from any previous test
    dlg = openPrefs()
    dlg.setCategory(0)
    dlg.reject()

    # Open prefs, navigate to some tab and reject
    dlg = openPrefs()
    assert dlg.stackedWidget.currentIndex() == 0
    dlg.setCategory(2)
    dlg.reject()

    # Open prefs again and check that the tab was restored
    dlg = openPrefs()
    assert dlg.stackedWidget.currentIndex() == 2
    dlg.reject()

    # Change statusbar setting, and cancel
    assert mainWindow.statusBar().isVisible()
    dlg = openPrefs()
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showStatusBar")
    assert checkBox.isChecked()
    checkBox.setChecked(False)
    dlg.reject()
    assert mainWindow.statusBar().isVisible()

    # Change statusbar setting, and accept
    dlg = openPrefs()
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showStatusBar")
    assert checkBox.isChecked()
    checkBox.setChecked(False)
    dlg.accept()
    assert not mainWindow.statusBar().isVisible()

    # Change topo setting, and accept
    dlg = openPrefs()
    comboBox: QComboBox = dlg.findChild(QComboBox, "prefctl_chronologicalOrder")
    qcbSetIndex(comboBox, "topological")
    dlg.accept()
    acceptQMessageBox(mainWindow, "take effect.+reload")


def testPrefsComboBoxWithPreview(tempDir, mainWindow):
    # Play with QComboBoxWithPreview (for coverage)
    dlg = GFApplication.instance().openPrefsDialog("shortTimeFormat")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_shortTimeFormat").findChild(QComboBox)
    comboBox.setFocus()
    QTest.keyClick(comboBox, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    QTest.qWait(0)
    QTest.keyClick(comboBox, Qt.Key.Key_Down)
    QTest.qWait(0)
    QTest.keyClick(comboBox, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    QTest.qWait(0)  # trigger ItemDelegate.paint
    comboBox.setFocus()
    QTest.keyClicks(comboBox, "MMMM")  # trigger activation of out-of-bounds index
    QTest.keyClick(comboBox, Qt.Key.Key_Enter)
    dlg.reject()


def testPrefsFontControl(tempDir, mainWindow):
    # Open a repo so that refreshPrefs functions are exercized in coverage
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(rw.repo.head_commit_id))
    defaultFamily = rw.diffView.document().defaultFont().family()
    if WINDOWS and OFFSCREEN:
        randomFamily = "Sans Serif"
    else:
        randomFamily = next(family for family in QFontDatabase.families(QFontDatabase.WritingSystem.Latin)
                            if not QFontDatabase.isPrivateFamily(family))
    assert defaultFamily != randomFamily

    # Change font setting, and accept
    dlg = GFApplication.instance().openPrefsDialog("font")
    fontPicker: FontPicker = dlg.findChild(FontPicker, "prefctl_font")
    assert not fontPicker.resetButton.isEnabled()
    fontPicker.familyEdit.showPopup()
    fontPicker.familyEdit.setCurrentFont(QFont(randomFamily))
    fontPicker.familyEdit.hidePopup()
    assert fontPicker.resetButton.isEnabled()
    fontPicker.sizeEdit.setValue(27)
    dlg.accept()
    effectiveFont = rw.diffView.document().defaultFont()
    assert effectiveFont.family() == randomFamily
    assert effectiveFont.pointSize() == 27

    dlg = GFApplication.instance().openPrefsDialog("font")
    fontPicker: FontPicker = dlg.findChild(FontPicker, "prefctl_font")
    assert fontPicker.resetButton.isEnabled()
    fontPicker.resetButton.click()
    assert not fontPicker.resetButton.isEnabled()
    dlg.accept()
    effectiveFont = rw.diffView.document().defaultFont()
    assert effectiveFont.family() == defaultFamily


def testPrefsLanguageControl(tempDir, mainWindow):
    # Open a repo so that refreshPrefs functions are exercized in coverage
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)

    # Change font setting, and accept
    dlg = GFApplication.instance().openPrefsDialog("language")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_language")
    qcbSetIndex(comboBox, "fran.ais")
    dlg.accept()
    acceptQMessageBox(mainWindow, "application des pr.f.rences")


def testPrefsRecreateDiffDocument(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    if WINDOWS:
        with RepoContext(wd) as repo:
            repo.config["core.autocrlf"] = "false"

    writeFile(f"{wd}/crlf.txt", "hello\r\nthat's it")
    rw = mainWindow.openRepo(wd)

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("crlf.txt"))
    assert "<CRLF>" in rw.diffView.toPlainText()

    dlg = GFApplication.instance().openPrefsDialog("showStrayCRs")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showStrayCRs")
    assert checkBox.isChecked()
    checkBox.setChecked(False)
    dlg.accept()

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("crlf.txt"))
    assert "<CRLF>" not in rw.diffView.toPlainText()


def testPrefsShowWhitespace(tempDir, mainWindow):
    whitespaceFlags = QTextOption.Flag.ShowTabsAndSpaces

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/whitespace.txt", "x\t y\n")

    rw = mainWindow.openRepo(wd)
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("whitespace.txt"))

    def whitespaceFlagsSet() -> bool:
        f = rw.diffView.document().defaultTextOption().flags()
        return (f & whitespaceFlags) == whitespaceFlags

    assert not whitespaceFlagsSet()

    dlg = GFApplication.instance().openPrefsDialog("showWhitespace")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showWhitespace")
    assert checkBox is not None
    assert not checkBox.isChecked()
    checkBox.setChecked(True)
    dlg.accept()

    assert settings.prefs.showWhitespace
    assert whitespaceFlagsSet()

    dlg = GFApplication.instance().openPrefsDialog("showWhitespace")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showWhitespace")
    checkBox.setChecked(False)
    dlg.accept()

    assert not settings.prefs.showWhitespace
    assert not whitespaceFlagsSet()


def testPrefsUserCommandsSyntaxHighlighter(mainWindow):
    # This is just for code coverage for now.
    dlg = GFApplication.instance().openPrefsDialog("commands")
    editor: QPlainTextEdit = dlg.findChild(QPlainTextEdit, "prefctl_commands")
    editor.setPlainText(textwrap.dedent("""\
    # this is a standalone comment (not a command title)
    # -----
    ? hello $COMMIT $KOMMIT # Command &Title
    """))
    QTest.qWait(0)
    dlg.reject()


def testPrefsUserCommandsGuide(mainWindow):
    dlg = GFApplication.instance().openPrefsDialog("language")
    if not QT5:  # Qt 5 doesn't want to hide the guide button initially, but I don't care about Qt 5
        assert not dlg.guideButton.isVisible()
    dlg.reject()

    dlg = GFApplication.instance().openPrefsDialog("commands")
    guideBrowser = dlg.guideBrowser
    guideButton = dlg.guideButton
    assert guideButton.isVisible()
    assert not guideBrowser.isVisible()

    # Click button to show, click button again to hide
    guideButton.click()
    assert guideBrowser.isVisible()
    assert guideButton.isChecked()
    guideButton.click()
    assert not guideBrowser.isVisible()
    assert not guideButton.isChecked()

    dlg.reject()


def testPrefsQtStyleVariantPicker(mainWindow):
    accent1 = mainWindow.palette().highlight().color()

    dlg = GFApplication.instance().openPrefsDialog("qtStyle")

    group: QWidget = dlg.findChild(QWidget, "prefctl_qtStyle")
    comboBoxes: list[QComboBox] = group.findChildren(QComboBox)

    stylePicker = comboBoxes[0]
    variantPicker = comboBoxes[1]

    assert stylePicker.isVisible()
    assert not variantPicker.isVisible()

    qcbSetIndex(stylePicker, APP_DISPLAY_NAME)
    assert variantPicker.isVisible()
    assert variantPicker.currentText().lower() == "system colors"

    qcbSetIndex(variantPicker, "dark pink")
    dlg.accept()

    accent2 = mainWindow.palette().highlight().color()
    assert accent1 != accent2


@pytest.mark.parametrize(["nativeName", "applySettings", "pushBranch", "repoMenu"], [
    ("rom.n", "aplică setările", "Fă push la ramură", "&Depozit"),  # "română", in its own name
    ("русский", "Применение настроек", "Отправить ветку", "&Репо"),
    ("Türkçe", "Ayarları Uygula", "Dalı gönder", "De&po"),
], ids=["ro", "ru", "tr"])
def testTranslationIsOfferedAndTranslatesTheApp(tempDir, mainWindow, nativeName, applySettings, pushBranch, repoMenu):
    from gitfourchette.tasks import PushBranch
    from gitfourchette.tasks.taskbook import TaskBook

    dlg = GFApplication.instance().openPrefsDialog("language")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_language")
    qcbSetIndex(comboBox, nativeName)
    dlg.accept()
    acceptQMessageBox(mainWindow, applySettings)
    try:
        assert TaskBook.names[PushBranch] == pushBranch
        mainWindow.fillGlobalMenuBar()
        menus = [a.text() for a in mainWindow.menuBar().actions()]
        assert repoMenu in menus
    finally:
        # Straight back to English, without another "restart needed" box
        from gitfourchette import settings
        settings.prefs.language = ""
        GFApplication.instance().applyLanguagePref()


def testNoRawPrefKeyLabels(mainWindow):
    """No row of the dialog may show a pref's internal name instead of words."""
    dlg = GFApplication.instance().openPrefsDialog()
    keys = [w.objectName().removeprefix(PrefsDialog.ControlQObjectNamePrefix)
            for w in dlg.findChildren(QWidget)
            if w.objectName().startswith(PrefsDialog.ControlQObjectNamePrefix)]
    captions = {label.text().removesuffix(":") for label in dlg.findChildren(QLabel)}
    captions |= {checkBox.text() for checkBox in dlg.findChildren(QCheckBox)}
    assert "compactUi" in keys
    assert [key for key in keys if key in captions] == []
    dlg.reject()


def testDensityRowUsesTheToolbarWords(mainWindow):
    toolbar = mainWindow.mainToolBar
    toolbar.fillThemeMenu()
    compactTip = findMenuAction(toolbar.themeMenu, "compact").toolTip()
    compactTip = QTextDocumentFragment.fromHtml(compactTip).toPlainText()
    assert compactTip == "Smaller text and icon-only toolbar buttons"

    dlg = GFApplication.instance().openPrefsDialog("compactUi")
    comboBox: QComboBox = dlg.findChild(QComboBox, "prefctl_compactUi")
    assert sorted(comboBox.itemText(i) for i in range(comboBox.count())) == ["Compact", "Normal"]
    assert comboBox.currentText() == "Normal"
    assert comboBox.toolTip() == compactTip
    label: QLabel = next(label for label in dlg.findChildren(QLabel) if label.buddy() is comboBox)
    assert label.text() == "Density:"

    qcbSetIndex(comboBox, "compact")
    dlg.accept()
    try:
        assert settings.prefs.compactUi
    finally:
        GFApplication.applyPrefs(compactUi=False)

    assertTranslatedInForkLanguages("Density", "Smaller text and icon-only toolbar buttons")


def _themeStrings():
    """Every qtStyle string the app writes for the built-in theme: the toolbar's
    light/dark switch (withThemeMode) and the Settings variant picker."""
    from gitfourchette.themes import ThemeName, ThemeAccent, withThemeMode
    written = {str(ThemeName.BuiltIn)}  # "System colors"
    for engine in ["", "Fusion", ThemeName.BuiltIn]:
        for mode in ["", "light", "dark"]:
            for accent in ["", *ThemeAccent]:
                styleName = ",".join(t for t in [engine, mode, accent] if t)
                for dark in [False, True]:
                    written.add(withThemeMode(styleName, dark))
    return sorted(written)


def testThemeStringsRoundTripThroughOneParser():
    from gitfourchette.themes import ThemeName, formatStyle, parseStyle, withThemeMode

    strings = _themeStrings()
    assert f"{ThemeName.BuiltIn},dark" in strings  # the toolbar's own value
    for styleName in strings:
        assert formatStyle(*parseStyle(styleName)) == styleName

    # Token order and repeats don't matter; the last one wins, as when resolving a theme
    assert parseStyle(f"{ThemeName.BuiltIn},#e93d58,light,dark") == (ThemeName.BuiltIn, "dark", "#e93d58")
    assert withThemeMode(f"{ThemeName.BuiltIn},#e93d58,light", True) == f"{ThemeName.BuiltIn},dark,#e93d58"
    assert parseStyle("Fusion") == ("Fusion", "", "")
    assert parseStyle("") == ("", "", "")


def testThemePickerShowsEveryThemeTheAppWrites(mainWindow):
    for styleName in _themeStrings():
        settings.prefs.qtStyle = styleName

        dlg = GFApplication.instance().openPrefsDialog("qtStyle")
        group: QWidget = dlg.findChild(QWidget, "prefctl_qtStyle")
        stylePicker, variantPicker = group.findChildren(QComboBox)
        assert variantPicker.isVisible()
        assert variantPicker.currentData() == styleName

        # Picking the style that's already there changes nothing
        stylePicker.activated.emit(stylePicker.currentIndex())
        variantPicker.activated.emit(variantPicker.currentIndex())
        assert dlg.prefDiff == {}, styleName
        dlg.reject()


def testThemePickerKeepsTheToolbarsDarkPin(mainWindow):
    from gitfourchette.themes import ThemeName

    mainWindow.onSetDarkTheme(True)  # the toolbar's Theme > Dark
    assert settings.prefs.qtStyle == f"{ThemeName.BuiltIn},dark"

    dlg = GFApplication.instance().openPrefsDialog("qtStyle")
    group: QWidget = dlg.findChild(QWidget, "prefctl_qtStyle")
    stylePicker, variantPicker = group.findChildren(QComboBox)
    assert variantPicker.currentText() == "Dark"

    stylePicker.activated.emit(stylePicker.currentIndex())
    assert dlg.prefDiff == {}
    dlg.accept()
    assert settings.prefs.qtStyle == f"{ThemeName.BuiltIn},dark"


def testEveryCountIsABoundedSpinBox(mainWindow):
    dlg = GFApplication.instance().openPrefsDialog()
    controls = {w.objectName().removeprefix(PrefsDialog.ControlQObjectNamePrefix): w
                for w in dlg.findChildren(QWidget)
                if w.objectName().startswith(PrefsDialog.ControlQObjectNamePrefix)}
    intKeys = [key for key in controls if type(getattr(settings.prefs, key)) is int]
    assert {"maxTrashFiles", "recentCommitMessages", "maxRecentRepos"} <= set(intKeys)

    for key in intKeys:
        control = controls[key]
        before = getattr(settings.prefs, key)
        # Typing a minus sign over the value used to raise ValueError in the text-field version
        control.setFocus()
        control.selectAll()
        QTest.keyClicks(control, "-")
        assert isinstance(control, QSpinBox), key
        assert control.minimum() >= 0, key
        assert control.value() == before, key

    def bounds(key):
        spinBox: QSpinBox = controls[key]
        return spinBox.minimum(), spinBox.maximum(), spinBox.specialValueText()

    assert bounds("maxTrashFiles") == (0, 9999, "Off")
    assert bounds("recentCommitMessages") == (0, 50, "Off")
    assert bounds("maxRecentRepos") == (1, 50, "")

    dlg.accept()
    assert settings.prefs.maxTrashFiles == 250
    assert settings.prefs.recentCommitMessages == 10

    assertTranslatedInForkLanguages("Off", context="a count of zero turns the setting off")


def testCountOutsideItsRangeIsSavedAsShown(mainWindow):
    # 0 recent repositories would erase every repo record on the next save;
    # the box can't show 0 any more, and what it shows is what OK keeps
    settings.prefs.maxRecentRepos = 0
    dlg = GFApplication.instance().openPrefsDialog("maxRecentRepos")
    spinBox: QSpinBox = dlg.findChild(QSpinBox, "prefctl_maxRecentRepos")
    assert spinBox.value() == 1
    dlg.accept()
    assert settings.prefs.maxRecentRepos == 1


def testSectionTitlesAndPreviewsAreNotDrawnDisabled(mainWindow):
    from gitfourchette.themes import ThemeName
    from gitfourchette.toolbox import contrastRatio

    GFApplication.applyPrefs(qtStyle=f"{ThemeName.BuiltIn},dark")
    try:
        dlg = GFApplication.instance().openPrefsDialog("doubleClickTabBar")
        window = dlg.palette().color(QPalette.ColorRole.Window)

        # Section titles on the Mouse Shortcuts page are titles, not unavailable options
        titles = [label for label in dlg.findChildren(QLabel)
                  if label.text() in ("Repository tabs:", "File lists:", "Diff view:")]
        assert len(titles) == 3
        for title in titles:
            assert title.isEnabled()
            assert contrastRatio(title.palette().color(QPalette.ColorRole.WindowText), window) >= 7

        # The date format's sample is secondary text, readable at 4.5:1
        preview: QLabel = dlg.findChild(QWidget, "prefctl_shortTimeFormat").findChild(QLabel)
        preview.ensurePolished()
        assert preview.isEnabled()
        assert contrastRatio(preview.palette().color(QPalette.ColorRole.WindowText), window) >= 4.5
        dlg.reject()
    finally:
        GFApplication.applyPrefs(qtStyle="")
