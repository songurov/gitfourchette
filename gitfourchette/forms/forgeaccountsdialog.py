"""
The tokens GitFourchette uses to talk to a code-hosting service.

One row per host, because a token belongs to a host: the same person has a
different one for their company's GitLab than for a public instance, and a
token pasted against the wrong host would be sent to a server that has no
business seeing it.
"""

from gitfourchette.forge.accounts import loadAccounts
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class ForgeAccountsDialog(QDialog):
    def __init__(self, parent=None, focusHost=""):
        super().__init__(parent)
        self.accounts = loadAccounts()
        self.setWindowTitle(_("Code hosting accounts"))
        self.setObjectName("ForgeAccountsDialog")
        self.resize(620, 360)

        layout = QVBoxLayout(self)
        explanation = QLabel(_(
            "A token lets GitFourchette post review comments on your merge requests. "
            "Create one in your GitLab profile under Access Tokens, with the <b>api</b> scope. "
            "Tokens are kept in a file only you can read, separate from your settings."))
        explanation.setWordWrap(True)
        explanation.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(explanation)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([_("Host"), _("Token")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        addButton = QPushButton(_("Add host"))
        addButton.setAutoDefault(False)
        addButton.clicked.connect(lambda: self.addRow("", ""))
        buttons.addWidget(addButton)
        removeButton = QPushButton(_("Remove"))
        removeButton.setAutoDefault(False)
        removeButton.clicked.connect(self.removeRow)
        buttons.addWidget(removeButton)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

        for host in self.accounts.hosts():
            self.addRow(host, self.accounts.tokenFor(host))
        if focusHost and not self.accounts.tokenFor(focusHost):
            self.addRow(focusHost, "")
        if self.table.rowCount() == 0:
            self.addRow("", "")
        self.table.setCurrentCell(self.table.rowCount() - 1, 1)

    def addRow(self, host: str, token: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(host))
        editor = QLineEdit(token)
        editor.setEchoMode(QLineEdit.EchoMode.Password)
        editor.setPlaceholderText(_("Access token with the api scope"))
        self.table.setCellWidget(row, 1, editor)

    def removeRow(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def rows(self) -> list[tuple[str, str]]:
        collected = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            editor = self.table.cellWidget(row, 1)
            host = (item.text() if item else "").strip()
            token = (editor.text() if editor else "").strip()
            if host:
                collected.append((host, token))
        return collected

    def save(self):
        edited = self.rows()
        # A host the reviewer deleted from the table must lose its token, not
        # keep it silently because nothing overwrote it.
        for host in self.accounts.hosts():
            if host not in {self.accounts.normalizeHost(h) for h, _t in edited}:
                self.accounts.setToken(host, "")
        for host, token in edited:
            self.accounts.setToken(host, token)
        self.accounts.write()
        self.accept()
