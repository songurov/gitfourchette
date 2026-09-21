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

def formatElapsed(seconds: float) -> str:
    if seconds <= 0:
        return ""
    if seconds < 60:
        return _("{0}s", round(seconds))
    return _("{0}m {1}s", int(seconds // 60), round(seconds % 60))


def formatTokens(tokens: int) -> str:
    if tokens <= 0:
        return ""
    if tokens < 10_000:
        return str(tokens)
    return _("{0}k", round(tokens / 1000))


def formatCost(cost: float) -> str:
    # Nothing rather than "$0.00": a review whose price nobody supplied did not
    # cost nothing, we just don't know what it cost.
    if cost <= 0:
        return ""
    return f"${cost:.2f}" if cost >= 0.01 else f"${cost:.4f}"


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

        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter, 1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Merge request"), _("Project"), _("State"),
                                   _("Time"), _("Tokens"), _("Cost"), _("Detail")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(self.openInBrowser)
        self.tree.currentItemChanged.connect(self.showComments)
        splitter.addWidget(self.tree)

        # The comments as they were posted: a process that writes under your
        # name should be readable here, not only on the merge request.
        self.commentView = QTextBrowser()
        self.commentView.setOpenExternalLinks(True)
        self.commentView.setPlaceholderText(_("Pick a merge request to read the comments it was sent."))
        splitter.addWidget(self.commentView)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

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
                row = QTreeWidgetItem([item.caption(), item.project, "", "", "", "", ""])
                row.setData(0, Qt.ItemDataRole.UserRole, item.webUrl())
                row.setToolTip(0, item.webUrl())
                self.tree.addTopLevelItem(row)
        for index, item in enumerate(items):
            row = self.tree.topLevelItem(index)
            row.setText(2, STATE_WORDS[item.state]())
            row.setText(3, formatElapsed(item.elapsed))
            row.setText(4, formatTokens(item.tokens))
            row.setText(5, formatCost(item.cost))
            row.setText(6, item.detail)
            row.setToolTip(6, item.detail)
            if item.cost <= 0 and item.tokens > 0:
                row.setToolTip(5, _("Set what your assistant charges in Settings to see the cost."))
            row.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.setTextAlignment(5, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for column in range(6):
            self.tree.resizeColumnToContents(column)
        self.showComments(self.tree.currentItem())
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
            spent = sum(item.cost for item in self.watcher.items)
            seconds = sum(item.elapsed for item in self.watcher.items)
            tail = ""
            if seconds:
                tail = _(" Took {0}", formatElapsed(seconds))
                if spent:
                    tail += _(", cost {0}.", formatCost(spent))
                else:
                    tail += "."
            self.headline.setText(_n("Last sweep: {n} merge request looked at, {0} reviewed.",
                                     "Last sweep: {n} merge requests looked at, {0} reviewed.",
                                     len(self.watcher.items), posted) + tail)
        else:
            self.headline.setText(_("The audit hasn’t looked at anything yet."))

    def showComments(self, current=None, _previous=None):
        index = self.tree.indexOfTopLevelItem(current) if current is not None else -1
        items = self.watcher.items
        if not 0 <= index < len(items):
            self.commentView.clear()
            return
        item = items[index]
        if not item.comments:
            self.commentView.setMarkdown(
                _("No comments: {0}", item.detail) if item.detail else _("No comments."))
            return
        parts = []
        for comment in item.comments:
            heading = _("Summary note") if not comment.where else f"`{comment.where}` — {comment.state}"
            parts.append(f"#### {heading}\n\n{comment.body}")
        self.commentView.setMarkdown("\n\n---\n\n".join(parts))

    def sweepFinished(self, _reviewed, _considered):
        self.refresh()

    def openInBrowser(self, row: QTreeWidgetItem, _column: int):
        url = row.data(0, Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))
