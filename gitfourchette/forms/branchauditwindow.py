"""
What is still work on a remote, and what is sediment.

Every branch on the remote, with the evidence that decides it: what its merge
request says happened, whether its commits are already in the base branch, and
how long ago anyone touched it. Nothing is ticked for you - deleting a branch
for everyone is the kind of thing a person should have to say yes to, twice.
"""

from gitfourchette.forge import branchaudit, gitlab
from gitfourchette.forge.accounts import loadAccounts
from gitfourchette.forge.branchaudit import Verdict
from gitfourchette.forge.session import ForgeSession
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.tasks import DeleteRemoteBranches
from gitfourchette.toolbox import *

MAX_MERGE_REQUEST_PAGES = 5
MERGE_REQUESTS_PER_PAGE = 100

VERDICT_WORDS = {
    Verdict.Protected: lambda: _p("branch verdict", "Protected"),
    Verdict.Active: lambda: _p("branch verdict", "Active"),
    Verdict.Merged: lambda: _p("branch verdict", "Merged"),
    Verdict.Abandoned: lambda: _p("branch verdict", "Abandoned"),
    Verdict.Stale: lambda: _p("branch verdict", "Stale"),
    Verdict.Unclear: lambda: _p("branch verdict", "Unclear"),
}


class BranchAuditWindow(QDialog):
    def __init__(self, repo, remoteName: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.remoteName = remoteName
        self.rows: list[tuple] = []
        self.session = None
        self.mergeRequests: dict = {}
        self.page = 1

        self.setWindowTitle(_("Branches on {0}", remoteName))
        self.setObjectName("BranchAuditWindow")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1000, 560)

        layout = QVBoxLayout(self)
        self.headline = QElidedLabel("")
        layout.addWidget(self.headline)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Branch"), _("Author"), _("Last commit"), _("Ahead"),
                                   _("Merge request"), _("Verdict"), _("Why")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemChanged.connect(lambda *_args: self.refreshButtons())
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.selectButton = QPushButton(_("Tick what’s safe to delete"))
        self.selectButton.setAutoDefault(False)
        self.selectButton.clicked.connect(self.selectDeletable)
        buttons.addWidget(self.selectButton)
        self.refreshButton = QPushButton(_("Refresh"))
        self.refreshButton.setAutoDefault(False)
        self.refreshButton.clicked.connect(self.reload)
        buttons.addWidget(self.refreshButton)
        buttons.addStretch(1)
        self.deleteButton = QPushButton(_("Delete on remote…"))
        self.deleteButton.clicked.connect(self.deleteSelected)
        buttons.addWidget(self.deleteButton)
        closeButton = QPushButton(_("Close"))
        closeButton.setAutoDefault(False)
        closeButton.clicked.connect(self.close)
        buttons.addWidget(closeButton)
        layout.addLayout(buttons)

        self.statusLabel = QElidedLabel("")
        self.statusLabel.setProperty("class", "secondary")
        layout.addWidget(self.statusLabel)

        self.reload()

    # --- Gathering ------------------------------------------------------------

    def reload(self):
        """Read the repository first, then ask the host what it knows."""
        self.mergeRequests = {}
        self.page = 1
        self.fill()
        project = gitlab.projectFromRemote(self.repo.remotes[self.remoteName].url)
        token = loadAccounts().tokenFor(project.host) if project else ""
        if not project or not token:
            self.statusLabel.setText(_("No GitLab token for this remote: judging from the repository alone, "
                                       "which can’t see a squashed merge."))
            return
        self.statusLabel.setText(_("Reading merge requests…"))
        self.project = project
        self.session = ForgeSession(token, self)
        self.fetchMergeRequests()

    def fetchMergeRequests(self):
        query = (f"{self.project.mergeRequestsRoot}?state=all&order_by=updated_at"
                 f"&per_page={MERGE_REQUESTS_PER_PAGE}&page={self.page}")
        self.session.get(query, self.gotMergeRequests)

    def gotMergeRequests(self, payload, error):
        if error:
            self.statusLabel.setText(error)
            return
        branchaudit.readMergeRequestIndex(payload, self.mergeRequests)
        if isinstance(payload, list) and len(payload) >= MERGE_REQUESTS_PER_PAGE and self.page < MAX_MERGE_REQUEST_PAGES:
            self.page += 1
            self.fetchMergeRequests()
            return
        self.fill()
        self.statusLabel.setText(_n("Read {n} merge request.", "Read {n} merge requests.",
                                    len(self.mergeRequests)))

    def fill(self):
        facts = branchaudit.collectFacts(self.repo, self.remoteName, self.mergeRequests)
        self.rows = [(fact, branchaudit.judge(fact)) for fact in facts]
        self.tree.clear()
        for fact, verdict in self.rows:
            row = QTreeWidgetItem([
                fact.name,
                fact.author,
                fact.lastCommit.strftime("%Y-%m-%d") if fact.lastCommit else "",
                str(fact.ahead) if fact.ahead else "",
                f"!{fact.mergeRequest} {fact.mergeRequestState}" if fact.mergeRequest else "",
                VERDICT_WORDS[verdict.verdict](),
                verdict.reason,
            ])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Unchecked)
            if verdict.verdict == Verdict.Protected:
                # It can still be ticked; the confirmation lists what goes.
                row.setForeground(0, QColor(128, 128, 128))
            row.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.setToolTip(6, verdict.reason)
            self.tree.addTopLevelItem(row)
        for column in range(6):
            self.tree.resizeColumnToContents(column)
        self.refreshButtons()

    # --- Acting ---------------------------------------------------------------

    def items(self) -> list[QTreeWidgetItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def ticked(self) -> list[str]:
        return [item.text(0) for item in self.items() if item.checkState(0) == Qt.CheckState.Checked]

    def selectDeletable(self):
        for item, (_fact, verdict) in zip(self.items(), self.rows, strict=False):
            item.setCheckState(0, Qt.CheckState.Checked if verdict.deletable else Qt.CheckState.Unchecked)

    def refreshButtons(self):
        ticked = len(self.ticked())
        deletable = sum(1 for _fact, verdict in self.rows if verdict.deletable)
        self.deleteButton.setEnabled(ticked > 0)
        self.deleteButton.setText(_n("Delete {n} on remote…", "Delete {n} on remote…", ticked)
                                  if ticked else _("Delete on remote…"))
        self.selectButton.setEnabled(deletable > 0)
        self.headline.setText(_n("{n} branch on {0}, {1} safe to delete.",
                                 "{n} branches on {0}, {1} safe to delete.",
                                 len(self.rows), self.remoteName, deletable))

    def deleteSelected(self):
        names = self.ticked()
        if names:
            # The task asks once, lists them, and pushes one deletion per remote.
            DeleteRemoteBranches.invoke(self, names)
            self.close()
