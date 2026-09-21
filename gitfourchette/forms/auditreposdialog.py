"""
Which projects the standing audit watches.

A project is listed because its repository is on this machine: the review reads
that repository's own rules and runs the assistant in its working directory. A
repository whose remote isn't a code host we can post to, or whose host has no
token yet, is shown with the reason rather than quietly left out.
"""

import os

from gitfourchette import settings
from gitfourchette.forge import gitlab
from gitfourchette.forge.accounts import loadAccounts
from gitfourchette.localization import *
from gitfourchette.porcelain import Repo
from gitfourchette.qt import *
from gitfourchette.toolbox import *


def describeRepo(path: str) -> tuple[str, str]:
    """The project this repository would be audited as, and what stands in the way."""
    try:
        repo = Repo(path)
    except Exception:
        return "", _("not a repository any more")
    project = gitlab.projectFromRemote(gitlab.remoteUrlOf(repo))
    if project is None:
        return "", _("no GitLab remote")
    if not loadAccounts().tokenFor(project.host):
        return project.path, _("no token for {0}", project.host)
    return project.path, ""


class AuditReposDialog(QDialog):
    def __init__(self, parent=None, chosen=()):
        super().__init__(parent)
        self.setWindowTitle(_("Projects to audit"))
        self.setObjectName("AuditReposDialog")
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        explanation = QLabel(_(
            "Every open merge request of the projects you tick is reviewed, and reviewed again "
            "whenever its author pushes. Comments are posted under your own name."))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        layout.addWidget(self.list, 1)

        known = list(dict.fromkeys([*chosen, *settings.history.repos]))
        for path in known:
            self.addRepo(path, path in chosen)

        buttons = QHBoxLayout()
        addButton = QPushButton(_("Add a repository…"))
        addButton.setAutoDefault(False)
        addButton.clicked.connect(self.browse)
        buttons.addWidget(addButton)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def addRepo(self, path: str, checked: bool):
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == path:
                return
        projectPath, obstacle = describeRepo(path)
        nickname = settings.history.getRepoNickname(path)
        caption = f"{nickname} — {projectPath or compactPath(path)}"
        if obstacle:
            caption += f"   ({obstacle})"
        item = QListWidgetItem(caption)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        if obstacle and not projectPath:
            # Nothing to post to: it can be ticked, but say plainly it won't run
            item.setForeground(QColor(128, 128, 128))
        self.list.addItem(item)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, _("Add a repository to audit"), os.path.expanduser("~"))
        if path:
            self.addRepo(path, True)

    def chosen(self) -> list[str]:
        return [self.list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.list.count())
                if self.list.item(row).checkState() == Qt.CheckState.Checked]
