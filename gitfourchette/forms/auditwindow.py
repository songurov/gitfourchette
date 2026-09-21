"""
What the standing audit is doing, and how to stop it.

A process that posts under your name must be visible while it runs, not only
after it has finished: which merge request it is on, what it decided about the
ones before it, and one button that stops the rest.
"""

from gitfourchette.forge.watcher import ItemState
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *

STATE_WORDS = {
    ItemState.Queued: lambda: _p("audit state", "Waiting"),
    ItemState.Running: lambda: _p("audit state", "Reviewing"),
    ItemState.Posted: lambda: _p("audit state", "Done"),
    ItemState.Skipped: lambda: _p("audit state", "Skipped"),
    ItemState.Failed: lambda: _p("audit state", "Failed"),
    ItemState.Cancelled: lambda: _p("audit state", "Stopped"),
}


class AuditWindow(QDialog):
    def __init__(self, watcher, parent=None):
        super().__init__(parent)
        self.watcher = watcher
        self.setWindowTitle(_("Merge Request Audit"))
        self.setObjectName("AuditWindow")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(860, 460)

        layout = QVBoxLayout(self)

        self.headline = QElidedLabel("")
        layout.addWidget(self.headline)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Merge request"), _("Project"), _("State"), _("Detail")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(self.openInBrowser)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.runButton = QPushButton(_("Review now"))
        self.runButton.clicked.connect(lambda: self.watcher.sweep(force=True))
        buttons.addWidget(self.runButton)
        self.stopButton = QPushButton(_("Stop"))
        self.stopButton.clicked.connect(self.watcher.stop)
        buttons.addWidget(self.stopButton)
        buttons.addStretch(1)
        closeButton = QPushButton(_("Close"))
        closeButton.setAutoDefault(False)
        closeButton.clicked.connect(self.close)
        buttons.addWidget(closeButton)
        layout.addLayout(buttons)

        self.statusLabel = QElidedLabel("")
        self.statusLabel.setProperty("class", "secondary")
        layout.addWidget(self.statusLabel)

        watcher.itemsChanged.connect(self.refresh)
        watcher.sweepFinished.connect(self.sweepFinished)
        watcher.progress.connect(self.statusLabel.setText)
        self.refresh()

    def refresh(self):
        items = self.watcher.items
        # Rebuild only when the number of rows changed; otherwise update them in
        # place, so a sweep doesn't yank the selection out from under a reader.
        if self.tree.topLevelItemCount() != len(items):
            self.tree.clear()
            for item in items:
                row = QTreeWidgetItem([item.caption(), item.project, "", ""])
                row.setData(0, Qt.ItemDataRole.UserRole, item.webUrl())
                row.setToolTip(0, item.webUrl())
                self.tree.addTopLevelItem(row)
        for index, item in enumerate(items):
            row = self.tree.topLevelItem(index)
            row.setText(2, STATE_WORDS[item.state]())
            row.setText(3, item.detail)
            row.setToolTip(3, item.detail)
        for column in range(3):
            self.tree.resizeColumnToContents(column)
        self.refreshButtons()

    def refreshButtons(self):
        sweeping = self.watcher.sweeping
        self.runButton.setEnabled(not sweeping)
        self.stopButton.setEnabled(sweeping)
        if sweeping:
            running = sum(1 for item in self.watcher.items if item.state == ItemState.Running)
            waiting = sum(1 for item in self.watcher.items if item.state == ItemState.Queued)
            self.headline.setText(_n("Reviewing {0} merge request, {n} still waiting.",
                                     "Reviewing {0} merge requests, {n} still waiting.", waiting, running))
        elif self.watcher.items:
            posted = sum(1 for item in self.watcher.items if item.state == ItemState.Posted)
            self.headline.setText(_n("Last sweep: {n} merge request looked at, {0} reviewed.",
                                     "Last sweep: {n} merge requests looked at, {0} reviewed.",
                                     len(self.watcher.items), posted))
        else:
            self.headline.setText(_("The audit hasn’t looked at anything yet."))

    def sweepFinished(self, _reviewed, _considered):
        self.refresh()

    def openInBrowser(self, row: QTreeWidgetItem, _column: int):
        url = row.data(0, Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))
