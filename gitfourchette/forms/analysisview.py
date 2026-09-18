# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""Repository analysis views used by the Analysis menu."""

import datetime
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gitfourchette.localization import *
from gitfourchette.porcelain import GitError, Oid, Repo, SortMode
from gitfourchette.qt import *
from gitfourchette.toolbox import QSignalBlockerContext, compactPath, escape


# Keep the dashboard responsive on very large repositories. Commit metadata is
# cheap, while calculating a tree diff for every commit is comparatively costly.
MAX_COMMITS = 1500
MAX_DIFF_STATS = 250

# The Developer Commits page answers "what did this person do between these two
# dates", so it can't stop at MAX_COMMITS: it reads the whole history of every
# branch, and only computes diff stats for the commits it keeps.
MAX_SCANNED_COMMITS = 100_000
MAX_LISTED_COMMITS = 5000


@dataclass
class CommitRecord:
    timestamp: int
    author: str
    email: str
    subject: str
    files: int = 0
    insertions: int = 0
    deletions: int = 0


@dataclass
class DeveloperStats:
    name: str
    email: str
    commits: int = 0
    activeDays: set[str] = field(default_factory=set)
    files: int = 0
    insertions: int = 0
    deletions: int = 0
    records: list[CommitRecord] = field(default_factory=list)


@dataclass
class Author:
    key: str
    name: str
    email: str
    commits: int = 0

    def label(self) -> str:
        return f"{self.name} <{self.email}>" if self.email else self.name


@dataclass
class DeveloperCommit:
    oid: Oid
    timestamp: int
    subject: str
    isMerge: bool
    files: int = 0
    insertions: int = 0
    deletions: int = 0


@dataclass
class DeveloperCommits:
    commits: list[DeveloperCommit]
    truncated: bool = False


def authorKey(name: str, email: str) -> str:
    """One developer = one email (or name, when there's no email), case-insensitive."""
    return (email or name).casefold()


class AnalysisTableItem(QTableWidgetItem):
    """Table item with numeric-aware sorting for KPI/activity columns."""

    def __init__(self, value):
        super().__init__(str(value))
        self.sortValue = value

    def __lt__(self, other):
        if isinstance(other, AnalysisTableItem):
            try:
                return self.sortValue < other.sortValue
            except TypeError:
                pass
        return super().__lt__(other)


class AnalysisWorker(QObject):
    """Runs one collector in a worker thread. `tag` tells stale results apart."""
    finished = Signal(object, object)
    failed = Signal(object, str)
    progress = Signal(int)

    def __init__(self, tag, function: Callable, *args):
        super().__init__()
        self.tag = tag
        self.function = function
        self.args = args

    def run(self):
        try:
            self.finished.emit(self.tag, self.function(*self.args, progress=self.progress.emit))
        except Exception as exc:  # pragma: no cover - depends on repository state
            self.failed.emit(self.tag, str(exc))


def collectAnalysis(path: str, progress=None) -> list[CommitRecord]:
    """Collect bounded, local-only history data for the selected repository."""
    repo = Repo(path)
    records = []
    try:
        if repo.head_is_unborn:
            return records
        walker = repo.walk(repo.head_commit_id, SortMode.TIME)
        for index, commit in enumerate(walker):
            if index >= MAX_COMMITS:
                break
            author = commit.author
            subject = (commit.message or "").splitlines()[0] if commit.message else ""

            files = insertions = deletions = 0
            if commit.parents and index < MAX_DIFF_STATS:
                files, insertions, deletions = _diffStats(repo, commit)
            records.append(CommitRecord(
                author.time, author.name or author.email, author.email, subject,
                files, insertions, deletions))
            if progress and index % 25 == 0:
                progress(index + 1)
                time.sleep(0.002)  # release the GIL so Qt can repaint/respond
    finally:
        repo.free()
    return records


def _diffStats(repo: Repo, commit) -> tuple[int, int, int]:
    """Files changed, lines added, lines deleted - against the first parent (or nothing)."""
    try:
        if commit.parents:
            diff = repo.diff(commit.parents[0].tree, commit.tree)
        else:
            diff = commit.tree.diff_to_tree(swap=True)
        stats = diff.stats
        return stats.files_changed, stats.insertions, stats.deletions
    except (GitError, KeyError, TypeError, ValueError):
        return 0, 0, 0


def _walkAllBranches(repo: Repo):
    """Every commit reachable from HEAD or any local/remote branch, newest first."""
    tips = []
    if not repo.head_is_unborn:
        tips.append(repo.head_commit_id)
    for branches in (repo.branches.local, repo.branches.remote):
        for name in branches:
            try:
                target = branches[name].resolve().target
            except (GitError, KeyError, ValueError):
                continue
            if isinstance(target, Oid) and target not in tips:
                tips.append(target)
    if not tips:
        return iter(())
    walker = repo.walk(tips[0], SortMode.TIME)
    for tip in tips[1:]:
        walker.push(tip)
    return walker


def collectAuthors(path: str, progress=None) -> tuple[list[Author], str]:
    """
    Everyone who authored a commit on any branch, most commits first, and the
    key of the repo's own git identity (so the page can start on "me").
    """
    repo = Repo(path)
    authors: dict[str, Author] = {}
    try:
        for index, commit in enumerate(_walkAllBranches(repo)):
            if index >= MAX_SCANNED_COMMITS:
                break
            name, email = commit.author.name, commit.author.email
            author = authors.setdefault(authorKey(name, email), Author(authorKey(name, email), name or email, email))
            author.commits += 1
            if progress and index % 500 == 0:
                progress(index + 1)
        me = ""
        if "user.email" in repo.config:
            me = authorKey("", repo.config["user.email"])
    finally:
        repo.free()
    return sorted(authors.values(), key=lambda a: (-a.commits, a.name.casefold())), me


def collectDeveloperCommits(
        path: str,
        key: str,
        start: int,
        end: int,
        includeMerges: bool,
        progress=None,
) -> DeveloperCommits:
    """
    Commits authored by `key` (every author if empty) with an author date in
    [start, end], on any branch. Author date, not commit date: a rebase or a
    cherry-pick doesn't move when the work was done.
    """
    repo = Repo(path)
    kept = []
    truncated = False
    try:
        for index, commit in enumerate(_walkAllBranches(repo)):
            if index >= MAX_SCANNED_COMMITS:
                truncated = True
                break
            author = commit.author
            if key and authorKey(author.name, author.email) != key:
                continue
            if not start <= author.time <= end:
                continue
            isMerge = len(commit.parents) > 1
            if isMerge and not includeMerges:
                continue
            kept.append(commit)
            if len(kept) >= MAX_LISTED_COMMITS:
                truncated = True
                break

        result = []
        for index, commit in enumerate(kept):
            subject = commit.message.splitlines()[0] if commit.message else ""
            files, insertions, deletions = _diffStats(repo, commit)
            result.append(DeveloperCommit(
                commit.id, commit.author.time, subject, len(commit.parents) > 1,
                files, insertions, deletions))
            if progress and index % 25 == 0:
                progress(index + 1)
                time.sleep(0.002)  # release the GIL so Qt can repaint/respond
    finally:
        repo.free()
    return DeveloperCommits(result, truncated)


class AnalysisDialog(QDialog):
    """A first, explainable analysis dashboard for one local repository."""

    OVERVIEW_TAB, DEVELOPER_TAB, COMMITS_TAB = range(3)

    def __init__(self, parent: QWidget, repoPath: str, showCommit: Callable[[Oid], None] | None = None):
        super().__init__(parent)
        self.repoPath = repoPath
        self.showCommit = showCommit
        self.records = []
        self.threads: list[QThread] = []
        self.closing = False
        self.commitsQuery = 0  # bumped on every query; older results are dropped
        self.commitsShown = 0  # the query whose results are in the table
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(_("Analysis — {0}", compactPath(repoPath)))
        self.resize(1100, 760)

        root = QVBoxLayout(self)
        self.loadingWidget = QWidget(self)
        loadingLayout = QHBoxLayout(self.loadingWidget)
        loadingLayout.setContentsMargins(0, 0, 0, 0)
        self.loadingLabel = QLabel(_("Loading repository history…"), self.loadingWidget)
        loadingLayout.addWidget(self.loadingLabel)
        progress = QProgressBar(self.loadingWidget)
        progress.setRange(0, 0)
        progress.setFixedWidth(180)
        loadingLayout.addWidget(progress)
        loadingLayout.addStretch(1)
        root.addWidget(self.loadingWidget)
        header = QHBoxLayout()
        title = QLabel(f"<h2>{escape(os.path.basename(repoPath))}</h2>", self)
        header.addWidget(title)
        header.addStretch(1)
        self.periodLabel = QLabel(_("Period:"), self)
        header.addWidget(self.periodLabel)
        self.period = QComboBox(self)
        self.period.addItem(_("Last 30 days"), 30)
        self.period.addItem(_("Last 90 days"), 90)
        self.period.addItem(_("All history"), 0)
        self.period.setCurrentIndex(2)
        self.period.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.period)
        root.addLayout(header)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs)
        self.overviewPage = self._makeOverviewPage()
        self.developerPage = self._makeDeveloperPage()
        self.commitsPage = self._makeCommitsPage()
        self.tabs.addTab(self.overviewPage, _("Overview"))
        self.tabs.addTab(self.developerPage, _("Developer KPI"))
        self.tabs.addTab(self.commitsPage, _("Developer Commits"))
        self.tabs.setEnabled(False)
        # The commits page has its own date range; the Period box would only confuse it
        self.tabs.currentChanged.connect(self._syncPeriodVisibility)
        self._syncPeriodVisibility()

        self._startJob("history", collectAnalysis, self.repoPath)
        self._startJob("authors", collectAuthors, self.repoPath)

    # -------------------------------------------------------------------------
    # Worker threads

    def _startJob(self, tag, function: Callable, *args):
        if self.closing:
            # A result that lands after close must not start a thread that would
            # outlive the dialog: Qt aborts on a QThread destroyed while running
            return
        thread = QThread(self)
        worker = AnalysisWorker(tag, function, *args)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._jobProgress if tag == "history" else self._commitsProgress)
        worker.finished.connect(self._jobFinished)
        worker.failed.connect(self._jobFailed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.worker = worker  # keep the Python wrapper alive while it runs
        self.threads.append(thread)
        thread.start()

    def _jobFinished(self, tag, result):
        if self.closing:
            return
        if tag == "history":
            self._analysisReady(result)
        elif tag == "authors":
            self._authorsReady(*result)
        elif tag == self.commitsQuery:
            self._fillCommits(result)
            self.commitsShown = tag

    def _jobFailed(self, tag, message):
        if tag == "history":
            self.loadingLabel.setText(_("Could not load analysis: {0}", message))
        elif tag == self.commitsQuery:
            self.commitsSummary.setText(_("Could not load commits: {0}", message))

    def _jobProgress(self, count):
        self.loadingLabel.setText(_("Loading repository history… {0} commits", count))

    def _commitsProgress(self, count):
        if self.commitsTable.rowCount() == 0:
            self.commitsSummary.setText(_("Reading commits… {0}", count))

    def isBusy(self) -> bool:
        """True while a worker thread still runs (tests wait on this)."""
        alive = []
        for thread in self.threads:
            try:
                if thread.isRunning():
                    alive.append(thread)
            except RuntimeError:  # deleted after finishing
                pass
        self.threads = alive
        return bool(alive)

    def closeEvent(self, event):
        self.closing = True
        self.commitsTimer.stop()
        # Do not destroy the dialog while a worker still owns a pygit2 Repo.
        for thread in self.threads:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait()
            except RuntimeError:
                pass
        super().closeEvent(event)

    def _analysisReady(self, records):
        self.records = records
        self.loadingWidget.hide()
        self.tabs.setEnabled(True)
        self.refresh()

    def _syncPeriodVisibility(self):
        visible = self.tabs.currentIndex() != self.COMMITS_TAB
        self.periodLabel.setVisible(visible)
        self.period.setVisible(visible)

    # -------------------------------------------------------------------------
    # Pages

    def _makeOverviewPage(self):
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        self.overviewCards = QGridLayout()
        layout.addLayout(self.overviewCards)
        layout.addWidget(QLabel(f"<b>{escape(_('Developer contribution overview'))}</b>"))
        self.overviewTable = self._table(
            [_('Developer'), _('Commits'), _('Active days'), _('Files'), _('Added'), _('Deleted')])
        layout.addWidget(self.overviewTable, 1)
        return page

    def _makeDeveloperPage(self):
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            _("A balanced score based on delivery, quality, collaboration and maintenance.")))
        self.developerTable = self._table([
            _('Developer'), _('KPI'), _('Commits'), _('Active days'), _('Files'),
            _('Added'), _('Deleted')])
        layout.addWidget(self.developerTable, 1)
        return page

    def _makeCommitsPage(self):
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)

        controls = QHBoxLayout()
        controls.addWidget(QLabel(_("Developer:"), page))
        self.commitsDeveloper = QComboBox(page)
        self.commitsDeveloper.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.commitsDeveloper.setMinimumContentsLength(24)
        controls.addWidget(self.commitsDeveloper, 1)

        today = QDate.currentDate()
        self.commitsFrom = self._dateEdit(page, today.addDays(-30))
        self.commitsTo = self._dateEdit(page, today)
        controls.addWidget(QLabel(_("From:"), page))
        controls.addWidget(self.commitsFrom)
        controls.addWidget(QLabel(_("To:"), page))
        controls.addWidget(self.commitsTo)

        self.commitsMerges = QCheckBox(_("Include merge commits"), page)
        self.commitsMerges.setToolTip(_("A merge's line count is the whole branch it brings in, "
                                        "not work done in the merge itself"))
        controls.addWidget(self.commitsMerges)
        layout.addLayout(controls)

        self.commitsSummary = QLabel(_("Loading developers…"), page)
        self.commitsSummary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.commitsSummary)

        self.commitsTable = self._table([
            _('Date'), _('Commit'), _('Message'), _('Files'), _('Added'), _('Deleted')])
        self.commitsTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.commitsTable.horizontalHeader().setStretchLastSection(False)
        self.commitsTable.itemDoubleClicked.connect(self._openCommitItem)
        layout.addWidget(self.commitsTable, 1)

        hint = QLabel(_("All branches. Dates are author dates. Double-click a commit to show it in the repository."), page)
        hint.setEnabled(False)  # dimmed
        layout.addWidget(hint)

        # Typing a date fires once per digit; wait until it settles
        self.commitsTimer = QTimer(self)
        self.commitsTimer.setSingleShot(True)
        self.commitsTimer.setInterval(150)
        self.commitsTimer.timeout.connect(self.queryCommits)
        for signal in (self.commitsDeveloper.currentIndexChanged, self.commitsFrom.dateChanged,
                       self.commitsTo.dateChanged, self.commitsMerges.toggled):
            signal.connect(self.commitsTimer.start)
        return page

    @staticmethod
    def _dateEdit(parent: QWidget, date: QDate) -> QDateEdit:
        edit = QDateEdit(date, parent)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        return edit

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(True)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return table

    # -------------------------------------------------------------------------
    # Overview & KPI

    def _filteredRecords(self) -> list[CommitRecord]:
        days = self.period.currentData()
        if not days:
            return list(self.records)
        if not self.records:
            return []
        newest = max(r.timestamp for r in self.records)
        cutoff = newest - days * 86400
        return [r for r in self.records if r.timestamp >= cutoff]

    @staticmethod
    def _stats(records: list[CommitRecord]) -> list[DeveloperStats]:
        stats: dict[str, DeveloperStats] = {}
        for record in records:
            key = record.email.casefold() or record.author.casefold()
            developer = stats.setdefault(key, DeveloperStats(record.author, record.email))
            developer.commits += 1
            developer.activeDays.add(datetime.datetime.fromtimestamp(
                record.timestamp, datetime.UTC).date().isoformat())
            developer.files += record.files
            developer.insertions += record.insertions
            developer.deletions += record.deletions
            developer.records.append(record)
        return sorted(stats.values(), key=lambda d: (-d.commits, d.name.casefold()))

    def _card(self, label: str, value: str) -> QLabel:
        card = QLabel(f"<small>{escape(label)}</small><br><b>{escape(value)}</b>")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setMargin(10)
        return card

    def refresh(self):
        records = self._filteredRecords()
        stats = self._stats(records)
        while self.overviewCards.count():
            item = self.overviewCards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        totalFiles = sum(r.files for r in records)
        totalAdded = sum(r.insertions for r in records)
        totalDeleted = sum(r.deletions for r in records)
        cards = [
            (_("Commits"), str(len(records))),
            (_("Developers"), str(len(stats))),
            (_("Files changed"), str(totalFiles)),
            (_("Lines changed"), str(totalAdded + totalDeleted)),
        ]
        for index, (label, value) in enumerate(cards):
            self.overviewCards.addWidget(self._card(label, value), 0, index)
        self._fillOverview(stats)
        self._fillDevelopers(stats)

    def _fillOverview(self, stats: list[DeveloperStats]):
        self.overviewTable.setRowCount(len(stats))
        for row, developer in enumerate(stats):
            values = [developer.name, developer.commits, len(developer.activeDays),
                      developer.files, developer.insertions, developer.deletions]
            for column, value in enumerate(values):
                self.overviewTable.setItem(row, column, AnalysisTableItem(value))

    def _fillDevelopers(self, stats: list[DeveloperStats]):
        self.developerTable.setRowCount(len(stats))
        for row, developer in enumerate(stats):
            # This is intentionally transparent, not a performance verdict.
            kpi = min(100, developer.commits * 5 + len(developer.activeDays) * 2
                      + min(20, developer.files) + (10 if developer.insertions else 0))
            values = [developer.name, f"{kpi}/100", developer.commits,
                      len(developer.activeDays), developer.files, developer.insertions,
                      developer.deletions]
            for column, value in enumerate(values):
                self.developerTable.setItem(row, column, AnalysisTableItem(value))

    # -------------------------------------------------------------------------
    # Developer Commits

    def _authorsReady(self, authors: list[Author], me: str):
        combo = self.commitsDeveloper
        with QSignalBlockerContext(combo):
            combo.clear()
            for author in authors:
                combo.addItem(_n("{name} — {n} commit", "{name} — {n} commits", author.commits,
                                 name=author.label()), author.key)
            combo.addItem(_("Everyone"), "")
            start = combo.findData(me) if me else -1
            combo.setCurrentIndex(max(start, 0))
        self.queryCommits()

    def commitsRange(self) -> tuple[int, int]:
        """Local midnight of the first day to the last second of the last day."""
        first, last = sorted(datetime.date(d.year(), d.month(), d.day())
                             for d in (self.commitsFrom.date(), self.commitsTo.date()))
        start = datetime.datetime.combine(first, datetime.time.min).astimezone()
        end = datetime.datetime.combine(last, datetime.time.max).astimezone()
        return int(start.timestamp()), int(end.timestamp())

    def queryCommits(self):
        self.commitsTimer.stop()
        if self.commitsDeveloper.count() == 0:
            return  # authors not loaded yet; they call back when they are
        self.commitsQuery += 1
        self.commitsTable.setRowCount(0)
        self.commitsSummary.setText(_("Reading commits…"))
        start, end = self.commitsRange()
        self._startJob(self.commitsQuery, collectDeveloperCommits, self.repoPath,
                       self.commitsDeveloper.currentData(), start, end, self.commitsMerges.isChecked())

    def _fillCommits(self, result: DeveloperCommits):
        commits = result.commits
        table = self.commitsTable
        table.setSortingEnabled(False)
        table.setRowCount(len(commits))
        activeDays = set()
        for row, commit in enumerate(sorted(commits, key=lambda c: c.timestamp, reverse=True)):
            when = datetime.datetime.fromtimestamp(commit.timestamp).astimezone()
            activeDays.add(when.date())
            subject = commit.subject + (" " + _("(merge)") if commit.isMerge else "")
            values = [when.strftime("%Y-%m-%d %H:%M"), str(commit.oid)[:7], subject,
                      commit.files, commit.insertions, commit.deletions]
            for column, value in enumerate(values):
                item = AnalysisTableItem(value)
                if column == 0:
                    item.sortValue = commit.timestamp
                item.setData(Qt.ItemDataRole.UserRole, commit.oid)
                table.setItem(row, column, item)
        table.setSortingEnabled(True)

        name = self.commitsDeveloper.currentText().split(" — ")[0]
        first, last = (d.toString("yyyy-MM-dd") for d in sorted(
            [self.commitsFrom.date(), self.commitsTo.date()]))
        if not commits:
            summary = _("No commits by {0} between {1} and {2}.", name, first, last)
        else:
            summary = " · ".join([
                _n("{n} commit", "{n} commits", len(commits)),
                _n("{n} active day", "{n} active days", len(activeDays)),
                _n("{n} file changed", "{n} files changed", sum(c.files for c in commits)),
                f"+{sum(c.insertions for c in commits)} −{sum(c.deletions for c in commits)}",
            ])
        if result.truncated:
            summary += " " + _("(stopped early: this repository is very large)")
        self.commitsSummary.setText(summary)

    def _openCommitItem(self, item: QTableWidgetItem):
        oid = item.data(Qt.ItemDataRole.UserRole)
        if oid is not None and self.showCommit is not None:
            self.showCommit(oid)
