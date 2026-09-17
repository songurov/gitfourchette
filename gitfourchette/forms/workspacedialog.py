# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_workspacedialog import Ui_WorkspaceDialog
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class WorkspaceDialog(QDialog):
    """
    Name a workspace and pick which repos belong to it.

    The list covers every repo the app knows about, not just the open tabs,
    so a workspace can be assembled without opening its repos first.
    """

    PathRole = Qt.ItemDataRole.UserRole + 0

    def __init__(
            self,
            title: str,
            initialName: str,
            candidates: list[tuple[str, str]],
            checkedPaths: list[str],
            reservedNames: list[str],
            parent=None):
        """
        `candidates` is an ordered list of (path, display name).
        `checkedPaths` is ticked on open; its order wins in the result.
        """
        super().__init__(parent)

        self.ui = Ui_WorkspaceDialog()
        self.ui.setupUi(self)
        self.setWindowTitle(title)

        checkedSet = set(checkedPaths)
        for path, name in candidates:
            item = QListWidgetItem(name)
            item.setData(WorkspaceDialog.PathRole, path)
            item.setToolTip(path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if path in checkedSet
                               else Qt.CheckState.Unchecked)
            self.ui.repoList.addItem(item)

        self.ui.filterEdit.textChanged.connect(self.applyFilter)
        self.ui.selectAllButton.clicked.connect(lambda: self.setAllVisible(True))
        self.ui.deselectAllButton.clicked.connect(lambda: self.setAllVisible(False))
        allTip = _("Applies to the rows the filter is showing.")
        self.ui.selectAllButton.setToolTip(allTip)
        self.ui.deselectAllButton.setToolTip(allTip)
        self.ui.repoList.itemChanged.connect(self.refreshCount)
        self.ui.repoList.itemActivated.connect(self.toggleItem)

        nameTaken = _("This name is already taken by another workspace.")
        self.validator = ValidatorMultiplexer(self)
        self.validator.setGatedWidgets(self.acceptButton)
        self.validator.connectInput(self.ui.nameEdit, lambda text: self.validateName(text, reservedNames, nameTaken))

        self.ui.nameEdit.setText(initialName)
        self.refreshCount()

        convertToBrandedDialog(self, title, _("Switch between named sets of repos in one click."))
        # Don't let the branded wrapper squeeze the buttons into ellipses
        for button in (self.ui.selectAllButton, self.ui.deselectAllButton):
            button.setMinimumWidth(button.sizeHint().width())
        self.setMinimumWidth(max(560, self.sizeHint().width()))
        self.ui.nameEdit.setFocus()
        self.ui.nameEdit.selectAll()

    @property
    def acceptButton(self):
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    def validateName(self, text: str, reservedNames: list[str], nameTaken: str) -> str:
        text = text.strip()
        if not text:
            return _("Please enter a name for this workspace.")
        if text in reservedNames:
            return nameTaken
        if not self.checkedPaths():
            return _("Please pick at least one repository.")
        return ""

    def applyFilter(self, needle: str):
        needle = needle.strip().casefold()
        for i in range(self.ui.repoList.count()):
            item = self.ui.repoList.item(i)
            haystack = item.text().casefold() + " " + item.data(WorkspaceDialog.PathRole).casefold()
            item.setHidden(bool(needle) and needle not in haystack)

    def setAllVisible(self, checked: bool):
        """Tick or untick every row the filter is currently showing."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        with QSignalBlockerContext(self.ui.repoList):
            for i in range(self.ui.repoList.count()):
                item = self.ui.repoList.item(i)
                if not item.isHidden():
                    item.setCheckState(state)
        self.refreshCount()

    def toggleItem(self, item: QListWidgetItem):
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)

    def refreshCount(self):
        numChecked = len(self.checkedPaths())
        self.ui.countLabel.setText(_n("{n} repo selected", "{n} repos selected", numChecked))
        # Ticking the last repo off must disable Save, so re-run the name validator
        self.validator.run()

    def checkedPaths(self) -> list[str]:
        """Checked repos, with the initially-checked ones keeping their order."""
        return [self.ui.repoList.item(i).data(WorkspaceDialog.PathRole)
                for i in range(self.ui.repoList.count())
                if self.ui.repoList.item(i).checkState() == Qt.CheckState.Checked]

    @property
    def workspaceName(self) -> str:
        return self.ui.nameEdit.text().strip()
