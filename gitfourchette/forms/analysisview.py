# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""Repository analysis views used by the Analysis menu."""

import datetime
import os
import re
from dataclasses import dataclass, field

from gitfourchette.localization import *
from gitfourchette.porcelain import GitError, Repo, SortMode
from gitfourchette.qt import *
from gitfourchette.toolbox import compactPath, escape


# Keep the dashboard responsive on very large repositories. Commit metadata is
# cheap, while calculating a tree diff for every commit is comparatively costly.
MAX_COMMITS = 1500
MAX_DIFF_STATS = 250
AI_HINTS = re.compile(r"\b(ai|chatgpt|copilot|claude|generated|generated-by)\b", re.IGNORECASE)
BOT_HINTS = re.compile(r"\b(bot|github-actions|dependabot|renovate)\b", re.IGNORECASE)


@dataclass
class CommitRecord:
    timestamp: int
    author: str
    email: str
    subject: str
    files: int = 0
    insertions: int = 0
    deletions: int = 0
    aiEvidence: str = ""


@dataclass
class DeveloperStats:
    name: str
    email: str
    commits: int = 0
    activeDays: set[str] = field(default_factory=set)
    files: int = 0
    insertions: int = 0
    deletions: int = 0
    aiCommits: int = 0
    records: list[CommitRecord] = field(default_factory=list)


def collectAnalysis(path: str) -> list[CommitRecord]:
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
            evidence = ""
            identity = f"{author.name} {author.email} {commit.message or ''}"
            if BOT_HINTS.search(identity):
                evidence = _("bot metadata")
            elif AI_HINTS.search(identity):
                evidence = _("AI-related metadata")

            files = insertions = deletions = 0
            if commit.parents and index < MAX_DIFF_STATS:
                try:
                    diff = repo.diff(commit.parents[0].tree, commit.tree)
                    stats = diff.stats
                    files = stats.files_changed
                    insertions = stats.insertions
                    deletions = stats.deletions
                except (GitError, KeyError, TypeError, ValueError):
                    pass
            records.append(CommitRecord(
                author.time, author.name or author.email, author.email, subject,
                files, insertions, deletions, evidence))
    finally:
        repo.free()
    return records


class AnalysisDialog(QDialog):
    """A first, explainable analysis dashboard for one local repository."""

    def __init__(self, parent: QWidget, repoPath: str):
        super().__init__(parent)
        self.repoPath = repoPath
        self.records = collectAnalysis(repoPath)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(_("Analysis — {0}", compactPath(repoPath)))
        self.resize(1100, 760)

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel(f"<h2>{escape(os.path.basename(repoPath))}</h2>", self)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel(_("Period:"), self))
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
        self.activityPage = self._makeActivityPage()
        self.aiPage = self._makeAiPage()
        self.tabs.addTab(self.overviewPage, _("Overview"))
        self.tabs.addTab(self.developerPage, _("Developer KPI"))
        self.tabs.addTab(self.activityPage, _("Activity"))
        self.tabs.addTab(self.aiPage, _("AI / Manual"))
        self.refresh()

    def _makeOverviewPage(self):
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        self.overviewCards = QGridLayout()
        layout.addLayout(self.overviewCards)
        layout.addWidget(QLabel(f"<b>{escape(_('Developer contribution overview'))}</b>"))
        self.overviewTable = self._table(
            [_('Developer'), _('Commits'), _('Active days'), _('Files'), _('Added'), _('Deleted')])
        layout.addWidget(self.overviewTable)
        layout.addStretch(1)
        return page

    def _makeDeveloperPage(self):
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            _("A balanced score based on delivery, quality, collaboration and maintenance.")))
        self.developerTable = self._table([
            _('Developer'), _('KPI'), _('Commits'), _('Active days'), _('Files'),
            _('Added'), _('Deleted'), _('AI signal')])
        layout.addWidget(self.developerTable)
        return page

    def _makeActivityPage(self):
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(_("Developer:"), page))
        self.developerFilter = QComboBox(page)
        self.developerFilter.addItem(_("Everyone"), "")
        self.developerFilter.currentIndexChanged.connect(self.refreshActivity)
        controls.addWidget(self.developerFilter)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.activityTable = self._table([
            _('Date'), _('Developer'), _('Commit'), _('Files'), _('Added'), _('Deleted')])
        self.activityTable.setSortingEnabled(True)
        layout.addWidget(self.activityTable)
        return page

    def _makeAiPage(self):
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            _("AI origin cannot be proven from Git alone. Signals below are evidence, not verdicts.")))
        self.aiTable = self._table([
            _('Developer'), _('Commits'), _('AI signal'), _('Unclassified'), _('Confidence')])
        layout.addWidget(self.aiTable)
        layout.addStretch(1)
        return page

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

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
            developer.aiCommits += bool(record.aiEvidence)
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
        self.developerFilter.blockSignals(True)
        selected = self.developerFilter.currentData()
        self.developerFilter.clear()
        self.developerFilter.addItem(_("Everyone"), "")
        for developer in stats:
            self.developerFilter.addItem(developer.name, developer.email)
        index = self.developerFilter.findData(selected)
        self.developerFilter.setCurrentIndex(max(0, index))
        self.developerFilter.blockSignals(False)
        self._fillActivity(records)
        self._fillAi(stats)

    def _fillOverview(self, stats: list[DeveloperStats]):
        self.overviewTable.setRowCount(len(stats))
        for row, developer in enumerate(stats):
            values = [developer.name, developer.commits, len(developer.activeDays),
                      developer.files, developer.insertions, developer.deletions]
            for column, value in enumerate(values):
                self.overviewTable.setItem(row, column, QTableWidgetItem(str(value)))

    def _fillDevelopers(self, stats: list[DeveloperStats]):
        self.developerTable.setRowCount(len(stats))
        for row, developer in enumerate(stats):
            # This is intentionally transparent, not a performance verdict.
            kpi = min(100, developer.commits * 5 + len(developer.activeDays) * 2
                      + min(20, developer.files) + (10 if developer.insertions else 0))
            values = [developer.name, f"{kpi}/100", developer.commits,
                      len(developer.activeDays), developer.files, developer.insertions,
                      developer.deletions, _("signal") if developer.aiCommits else _("none")]
            for column, value in enumerate(values):
                self.developerTable.setItem(row, column, QTableWidgetItem(str(value)))

    def refreshActivity(self):
        self._fillActivity(self._filteredRecords())

    def _fillActivity(self, records: list[CommitRecord]):
        email = self.developerFilter.currentData()
        records = [r for r in records if not email or r.email == email]
        self.activityTable.setRowCount(len(records))
        for row, record in enumerate(sorted(records, key=lambda r: r.timestamp, reverse=True)):
            date = datetime.datetime.fromtimestamp(record.timestamp, datetime.UTC).date().isoformat()
            values = [date, record.author, record.subject, record.files,
                      record.insertions, record.deletions]
            for column, value in enumerate(values):
                self.activityTable.setItem(row, column, QTableWidgetItem(str(value)))

    def _fillAi(self, stats: list[DeveloperStats]):
        self.aiTable.setRowCount(len(stats))
        for row, developer in enumerate(stats):
            unknown = developer.commits - developer.aiCommits
            confidence = f"{round(100 * developer.aiCommits / developer.commits)}%" \
                if developer.aiCommits else _("none")
            values = [developer.name, developer.commits, developer.aiCommits,
                      unknown, confidence]
            for column, value in enumerate(values):
                self.aiTable.setItem(row, column, QTableWidgetItem(str(value)))
