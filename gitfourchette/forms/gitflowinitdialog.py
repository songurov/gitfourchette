# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_gitflowinitdialog import Ui_GitFlowInitDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import GitFlowConfig
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class GitFlowInitDialog(QDialog):
    """Pick the production and development branches and the branch prefixes."""

    def __init__(
            self,
            suggestion: GitFlowConfig,
            localBranches: list[str],
            origin: str,
            remoteBranches: list[str],
            parent=None):

        super().__init__(parent)

        self.ui = Ui_GitFlowInitDialog()
        self.ui.setupUi(self)

        self.suggestion = suggestion
        self.localBranches = list(localBranches)
        self.origin = origin
        self.remoteBranches = set(remoteBranches)

        ui = self.ui
        for comboBox, value in [(ui.masterComboBox, suggestion.master), (ui.developComboBox, suggestion.develop)]:
            comboBox.addItems(self.localBranches)
            comboBox.setEditText(value)
            comboBox.lineEdit().setValidator(ReplaceSpacesWithDashes())

        self.prefixEdits = {
            "feature": ui.featureEdit,
            "release": ui.releaseEdit,
            "hotfix": ui.hotfixEdit,
            "support": ui.supportEdit,
        }
        for field, edit in self.prefixEdits.items():
            edit.setText(getattr(suggestion, field))
            edit.setValidator(ReplaceSpacesWithDashes())
        ui.versionTagEdit.setText(suggestion.versiontag)
        ui.versionTagEdit.setValidator(ReplaceSpacesWithDashes())

        okButton = ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        okButton.setText(_("Initialize"))

        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(okButton)
        validator.connectInput(ui.masterComboBox.lineEdit(), self.validateMaster)
        validator.connectInput(ui.developComboBox.lineEdit(), self.validateDevelop)
        for edit in self.prefixEdits.values():
            validator.connectInput(edit, self.validatePrefix)
        validator.connectInput(ui.versionTagEdit, self.validateVersionTag)
        validator.run()

        ui.masterComboBox.editTextChanged.connect(self.refreshDevelopInfo)
        ui.developComboBox.editTextChanged.connect(self.refreshDevelopInfo)
        ui.developInfoLabel.setTextFormat(Qt.TextFormat.PlainText)
        tweakWidgetFont(ui.developInfoLabel, 90)

        convertToBrandedDialog(
            self,
            _("Initialize Git Flow"),
            _("These settings go in this repo’s .git/config, where the git-flow command line tools, "
              "Fork and SourceTree find them too."),
            multilineSubtitle=True)

        packDialog(self)
        self.refreshDevelopInfo()

    def refreshDevelopInfo(self):
        ui = self.ui
        develop = ui.developComboBox.currentText()
        exists = develop in self.localBranches

        if exists:
            text = ""
        elif develop in self.remoteBranches:
            text = _("{0} doesn’t exist yet. It will be created from {1}.",
                     tquo(develop), tquo(f"{self.origin}/{develop}"))
        else:
            text = _("{0} doesn’t exist yet. It will be created from {1}.",
                     tquo(develop), tquo(ui.masterComboBox.currentText()))

        ui.developInfoLabel.setText(text)
        ui.developInfoLabel.setVisible(not exists)
        ui.switchCheckBox.setEnabled(not exists)
        self.fitHeight()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.fitHeight()

    def fitHeight(self):
        """Shrink or grow with the info line, keeping the width."""
        self.ui.developInfoLabel.parentWidget().layout().invalidate()
        self.layout().invalidate()
        self.layout().activate()
        # The layout's own minimum height is for the narrowest width, where
        # every wrapped line is at its tallest: use the height for this width
        height = self.heightForWidth(self.width())
        if height > 0:
            self.setMinimumHeight(height)
            self.resize(self.width(), height)

    def validateMaster(self, name: str) -> str:
        if not name:
            return nameValidationMessage(name, [])
        if name not in self.localBranches:
            return _("There’s no local branch named {0}.", tquo(name))
        return ""

    def validateDevelop(self, name: str) -> str:
        if name == self.ui.masterComboBox.currentText():
            return _("The production and development branches must be different.")
        return nameValidationMessage(name, [])

    def validatePrefix(self, prefix: str) -> str:
        if not prefix:
            return _("Enter a prefix.")

        message = nameValidationMessage(prefix + "x", [])
        if message:
            return message

        # bugfix isn't shown, but git-flow uses it: it must not clash either
        others = [edit.text() for edit in self.prefixEdits.values()] + [self.suggestion.bugfix]
        others.remove(prefix)
        if any(other and (other.startswith(prefix) or prefix.startswith(other)) for other in others):
            return _("Each branch type needs its own prefix.")

        return ""

    def validateVersionTag(self, prefix: str) -> str:
        if not prefix:
            return ""
        return nameValidationMessage(prefix + "1.0", [])

    def config(self) -> GitFlowConfig:
        ui = self.ui
        return GitFlowConfig(
            master=ui.masterComboBox.currentText(),
            develop=ui.developComboBox.currentText(),
            feature=ui.featureEdit.text(),
            bugfix=self.suggestion.bugfix,
            release=ui.releaseEdit.text(),
            hotfix=ui.hotfixEdit.text(),
            support=ui.supportEdit.text(),
            versiontag=ui.versionTagEdit.text())

    def switchToDevelop(self) -> bool:
        switchCheckBox = self.ui.switchCheckBox
        return switchCheckBox.isEnabled() and switchCheckBox.isChecked()
