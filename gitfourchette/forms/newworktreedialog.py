# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_newworktreedialog import Ui_NewWorktreeDialog
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class NewWorktreeDialog(QDialog):
    """
    Ask where to put a new worktree, and what to check out in it.
    Mirrors the three forms of `git worktree add`: a new branch, an existing
    branch that isn't checked out anywhere else, or a detached HEAD.
    """

    def __init__(
            self,
            parentDir: str,
            availableBranches: list[str],
            reservedNames: list[str],
            parent=None):

        super().__init__(parent)

        self.ui = Ui_NewWorktreeDialog()
        self.ui.setupUi(self)
        self.parentDir = parentDir

        self.acceptButton.setText(_("&Create"))

        self.ui.existingBranchComboBox.addItems(availableBranches)
        if not availableBranches:
            # Every local branch is already checked out somewhere, so git would
            # refuse this mode anyway.
            self.ui.existingBranchRadio.setEnabled(False)
            self.ui.existingBranchComboBox.setEnabled(False)

        # Radio buttons are auto-exclusive, so we can't fake an initial 'toggled'
        # signal the way we would with a checkbox: apply the initial state directly.
        self.ui.newBranchEdit.setEnabled(self.ui.newBranchRadio.isChecked())
        self.ui.existingBranchComboBox.setEnabled(self.ui.existingBranchRadio.isChecked())

        self.ui.browseButton.clicked.connect(self.browse)

        nameTaken = _("This name is already taken by another local branch.")
        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(self.acceptButton)
        validator.connectInput(self.ui.pathEdit, self.validatePath)
        validator.connectInput(
            self.ui.newBranchEdit,
            lambda name: nameValidationMessage(name, reservedNames, nameTaken)
            if self.ui.newBranchRadio.isChecked() else "")

        # Re-validate when switching modes: the branch name only matters in one of them
        for radio in (self.ui.newBranchRadio, self.ui.existingBranchRadio, self.ui.detachedRadio):
            radio.toggled.connect(lambda _dummy: validator.run())

        # Keep the default branch name in sync with the folder name until the
        # user types their own, which is what `git worktree add <path>` does.
        self.ui.pathEdit.textChanged.connect(self.syncDefaultBranchName)
        self._branchNameEdited = False
        self.ui.newBranchEdit.textEdited.connect(self.onBranchNameEdited)

        validator.run()

        convertToBrandedDialog(
            self, _("New worktree"),
            _("A worktree is a second working copy of this repo, with its own checked-out branch."))

        self.ui.pathEdit.setFocus()
        packDialog(self, lockHeight=True)

    @property
    def acceptButton(self):
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    def browse(self):
        qfd = PersistentFileDialog.saveFile(
            self, "NewWorktree", _("New worktree location"), self.path or self.parentDir)
        qfd.fileSelected.connect(self.ui.pathEdit.setText)
        qfd.show()

    def onBranchNameEdited(self):
        self._branchNameEdited = True

    def syncDefaultBranchName(self, path: str):
        if self._branchNameEdited:
            return
        # Don't block signals here: the validator listens to textChanged, and it
        # has already run once (against the empty field) by the time we get here.
        # setText doesn't emit textEdited, so this won't look like the user typing.
        self.ui.newBranchEdit.setText(os.path.basename(path.rstrip("/\\")))

    def validatePath(self, path: str) -> str:
        if not path.strip():
            return _("Please enter a location for the new worktree.")
        path = self.absolutePath(path)
        if os.path.isdir(path):
            # git accepts an existing directory as long as it's empty
            if os.listdir(path):
                return _("This folder already exists and isn’t empty.")
        elif os.path.lexists(path):
            return _("A file already exists at this location.")
        elif not os.path.isdir(os.path.dirname(path)):
            return _("The parent folder doesn’t exist.")
        return ""

    def absolutePath(self, path: str = "") -> str:
        path = path or self.ui.pathEdit.text()
        path = os.path.expanduser(path.strip())
        if not os.path.isabs(path):
            path = os.path.join(self.parentDir, path)
        return os.path.normpath(path)

    @property
    def path(self) -> str:
        return self.ui.pathEdit.text().strip()

    @property
    def newBranchName(self) -> str:
        """Name of the branch to create, or empty if not creating one."""
        if not self.ui.newBranchRadio.isChecked():
            return ""
        return self.ui.newBranchEdit.text().strip()

    @property
    def existingBranchName(self) -> str:
        """Name of the branch to check out, or empty if not checking one out."""
        if not self.ui.existingBranchRadio.isChecked():
            return ""
        return self.ui.existingBranchComboBox.currentText()

    @property
    def detached(self) -> bool:
        return self.ui.detachedRadio.isChecked()
