# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import pathlib
import re

from gitfourchette import settings
from gitfourchette.forms.repositorystatistics import CommitActivityChart, ContributorDonut
from gitfourchette.forms.ui_welcomewidget import Ui_WelcomeWidget
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.reposcan import (
    DEFAULT_MAX_DEPTH, RepoDetails, RepoInfo, RepoScanner, defaultScanRoots, inspectRepoDetails)
from gitfourchette.toolbox import *


class WelcomeWidget(QFrame):
    """
    The Home page: what you see when no repo tab is open.

    Besides the usual new/open/clone buttons, it lists every repo this machine
    knows about, so you can see what you have and jump into any of it without
    hunting through a file dialog.
    """

    newRepo = Signal()
    openRepo = Signal()
    cloneRepo = Signal()
    openRepoPath = Signal(str)

    PathRole = Qt.ItemDataRole.UserRole + 0

    def __init__(self, parent):
        super().__init__(parent)

        self.ui = Ui_WelcomeWidget()
        self.ui.setupUi(self)

        logoPixmap = QPixmap("assets:icons/gitfourchette")
        logoPixmap.setDevicePixelRatio(4)
        self.ui.logoLabel.setText(qAppName())
        self.ui.logoLabel.setPixmap(logoPixmap)

        defaultFont = self.ui.welcomeLabel.font()
        fs1 = int(defaultFont.pointSizeF() * 1.3)
        fs2 = int(defaultFont.pointSizeF() * 1.8)
        appText = f"<span style=\'font-weight: bold; color: #407cbf; font-size: {fs2}pt\'>{qAppName()}</span>"
        welcomeText = self.ui.welcomeLabel.text()
        welcomeText = f"<html style=\'font-size: {fs1}pt;\'>" + welcomeText.format(app=appText)
        self.ui.welcomeLabel.setText(welcomeText)

        self.ui.newRepoButton.clicked.connect(self.newRepo)
        self.ui.openRepoButton.clicked.connect(self.openRepo)
        self.ui.cloneRepoButton.clicked.connect(self.cloneRepo)

        self.scanner: RepoScanner | None = None
        self.repoInfos: dict[str, RepoInfo] = {}
        self.detailCache: dict[str, RepoDetails] = {}
        self._buildReadmePage()
        self._buildRepoPane()

        # Repository manager navigation on the left, selected repo on the right.
        self.ui.splitter.insertWidget(0, self.ui.repoPane)
        self.ui.splitter.setStretchFactor(0, 1)
        self.ui.splitter.setStretchFactor(1, 4)
        self.ui.splitter.setSizes([280, 900])

    README_NAMES = ("README.md", "README.markdown", "README.rst", "README.txt", "README")
    README_SIZE_LIMIT = 512 * 1024
    "A README is meant to be read; anything larger is something else."

    def _buildReadmePage(self):
        page = self.ui.readmePage
        layout: QVBoxLayout = self.ui.readmePageLayout

        self.readmeTitle = QLabel(page)
        self.readmeTitle.setObjectName("HomeReadmeTitle")
        self.readmeTitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.repoPathLabel = QLabel(page)
        self.repoPathLabel.setObjectName("HomeRepoPath")
        self.repoPathLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.repoPathLabel.setWordWrap(True)

        self.repoFacts = QLabel(page)
        self.repoFacts.setObjectName("HomeRepoFacts")
        self.repoFacts.setTextFormat(Qt.TextFormat.RichText)
        self.repoFacts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.repoTabs = QTabWidget(page)
        self.repoTabs.setObjectName("HomeRepoTabs")

        summaryPage = QWidget(self.repoTabs)
        summaryLayout = QVBoxLayout(summaryPage)
        summaryLayout.setContentsMargins(8, 8, 8, 8)

        self.readmeView = QTextBrowser(summaryPage)
        self.readmeView.setObjectName("HomeReadmeView")
        self.readmeView.setOpenExternalLinks(True)
        summaryLayout.addWidget(self.readmeView)

        statisticsPage = QWidget(self.repoTabs)
        statisticsPageLayout = QVBoxLayout(statisticsPage)
        statisticsPageLayout.setContentsMargins(0, 0, 0, 0)
        statisticsScroll = QScrollArea(statisticsPage)
        statisticsScroll.setWidgetResizable(True)
        statisticsScroll.setFrameShape(QFrame.Shape.NoFrame)
        statisticsContent = QWidget(statisticsScroll)
        statisticsLayout = QVBoxLayout(statisticsContent)
        statisticsLayout.setContentsMargins(12, 12, 12, 12)
        statisticsScroll.setWidget(statisticsContent)
        statisticsPageLayout.addWidget(statisticsScroll)

        self.statisticsRange = QLabel(statisticsPage)
        self.statisticsRange.setObjectName("HomeStatisticsRange")
        statisticsLayout.addWidget(self.statisticsRange)

        commitsHeading = QLabel(f"<b>{escape(_('Commits per month'))}</b>", statisticsPage)
        statisticsLayout.addWidget(commitsHeading)
        self.commitChart = CommitActivityChart(statisticsPage)
        statisticsLayout.addWidget(self.commitChart)

        lower = QHBoxLayout()
        contributorsBox = QVBoxLayout()
        contributorsBox.addWidget(QLabel(f"<b>{escape(_('All contributors'))}</b>", statisticsPage))
        self.contributorTable = QTableWidget(statisticsPage)
        self.contributorTable.setObjectName("HomeContributorTable")
        self.contributorTable.setColumnCount(2)
        self.contributorTable.setHorizontalHeaderLabels([_("Contributor"), _("Commits")])
        self.contributorTable.horizontalHeader().setStretchLastSection(False)
        self.contributorTable.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.contributorTable.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.contributorTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.contributorTable.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.contributorTable.verticalHeader().setVisible(False)
        contributorsBox.addWidget(self.contributorTable)

        topBox = QVBoxLayout()
        topBox.addWidget(QLabel(f"<b>{escape(_('Top contributors'))}</b>", statisticsPage))
        self.contributorDonut = ContributorDonut(statisticsPage)
        topBox.addWidget(self.contributorDonut)
        lower.addLayout(contributorsBox, 1)
        lower.addLayout(topBox, 1)
        statisticsLayout.addLayout(lower)

        self.repoTabs.addTab(summaryPage, _("Summary"))
        self.repoTabs.addTab(statisticsPage, _("Statistics"))

        layout.addWidget(self.readmeTitle)
        layout.addWidget(self.repoPathLabel)
        layout.addWidget(self.repoFacts)
        layout.addWidget(self.repoTabs)

    def findReadme(self, repoPath: str) -> str:
        """Path of this repo’s README, whatever it chose to call it."""
        try:
            entries = {e.name.casefold(): e for e in os.scandir(repoPath) if e.is_file()}
        except OSError:
            return ""
        for name in WelcomeWidget.README_NAMES:
            entry = entries.get(name.casefold())
            if entry is not None:
                return entry.path
        return ""

    @staticmethod
    def dropUnreachableImages(markdown: str, basePath: str) -> str:
        """
        Take out pictures that can’t be shown.

        A README full of remote badges renders as a row of broken-image icons,
        which looks worse than not showing them at all. Local images that do
        exist are left alone, and alt text survives: that’s what the author
        wrote for people who can’t see the picture.
        """
        def keepLocal(match: re.Match) -> str:
            alt, target = match.group(1), match.group(2).split()[0].strip("<>")
            if not re.match(r"[a-z][a-z0-9+.-]*:|//", target, re.IGNORECASE) \
                    and os.path.isfile(os.path.join(basePath, target)):
                return match.group(0)
            return alt

        markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", keepLocal, markdown)
        return re.sub(r"<img\b[^>]*/?>", "", markdown, flags=re.IGNORECASE)

    def showReadme(self, repoPath: str) -> bool:
        """
        Show a repo’s README in place of the splash. Returns False when there
        is nothing to show, so the caller can leave Home as it was.

        The left half of this page was empty space; a click in the tree now
        says what the thing actually is, without opening it.
        """
        readmePath = self.findReadme(repoPath)
        if not readmePath:
            return False

        self.readmeView.setSearchPaths([repoPath])

        try:
            size = os.path.getsize(readmePath)
            text = "" if size > WelcomeWidget.README_SIZE_LIMIT else \
                pathlib.Path(readmePath).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.readmeView.setPlainText(_("Couldn’t read {0}: {1}", readmePath, str(exc)))
        else:
            if not text:
                self.readmeView.setPlainText(_("{0} is too large to preview.",
                                               os.path.basename(readmePath)))
            elif readmePath.casefold().endswith((".md", ".markdown")):
                self.readmeView.setMarkdown(self.dropUnreachableImages(text, repoPath))
            else:
                self.readmeView.setPlainText(text)

        self.ui.leftStack.setCurrentWidget(self.ui.readmePage)
        return True

    def showRepository(self, repoPath: str):
        """Fill the repository header, Summary and Statistics for one selection."""
        repoPath = os.path.normpath(repoPath)
        info = self.repoInfos.get(repoPath, RepoInfo(repoPath))
        details = self.detailCache.get(repoPath)
        if details is None:
            details = inspectRepoDetails(repoPath)
            self.detailCache[repoPath] = details

        name = settings.history.peekRepoNickname(repoPath)
        self.readmeTitle.setText(f"<h2 style='margin: 0'>{escape(name)}</h2>")
        self.repoPathLabel.setText(escape(compactPath(repoPath)))
        self.repoFacts.setText(self._repoFactsHtml(info, details))

        if not self.showReadme(repoPath):
            self.readmeView.setPlainText(_("This repository has no README."))
        self._showStatistics(details)
        self.ui.leftStack.setCurrentWidget(self.ui.readmePage)

    def _repoFactsHtml(self, info: RepoInfo, details: RepoDetails) -> str:
        locale = QLocale()

        def dateText(timestamp: int) -> str:
            if not timestamp:
                return "—"
            dateTime = QDateTime.fromSecsSinceEpoch(timestamp).toLocalTime()
            return locale.toString(dateTime, QLocale.FormatType.ShortFormat)

        changed = str(info.changedFiles)
        size = locale.formattedDataSize(details.sizeBytes) if details.sizeBytes else "—"
        remotes = ", ".join(details.remotes) or "—"
        branch = info.branch or _("Detached HEAD")
        leftRows = [
            (_("Changed files"), changed),
            (_("Repository size"), size),
            (_("Commits"), str(details.commitCount)),
            (_("Initial commit"), dateText(details.initialCommitTime)),
            (_("Last commit"), dateText(details.lastCommitTime)),
        ]
        rightRows = [
            (_("Branch"), branch),
            (_("Remotes"), remotes),
            (_("Local branches"), str(details.localBranches)),
            (_("Tags"), str(details.tags)),
        ]
        cells = ""
        for row in range(max(len(leftRows), len(rightRows))):
            cells += "<tr>"
            for rows in (leftRows, rightRows):
                if row < len(rows):
                    label, value = rows[row]
                    cells += (f"<td style='padding-right:12px'><b>{escape(label)}</b></td>"
                              f"<td style='padding-right:36px'>{escape(value)}</td>")
                else:
                    cells += "<td></td><td></td>"
            cells += "</tr>"
        return f"<table>{cells}</table>"

    def _showStatistics(self, details: RepoDetails):
        locale = QLocale()
        if details.initialCommitTime and details.lastCommitTime:
            first = QDateTime.fromSecsSinceEpoch(details.initialCommitTime).date()
            last = QDateTime.fromSecsSinceEpoch(details.lastCommitTime).date()
            self.statisticsRange.setText(
                f"<b>{escape(locale.toString(first, QLocale.FormatType.LongFormat))}</b>"
                f" &ndash; <b>{escape(locale.toString(last, QLocale.FormatType.LongFormat))}</b>")
        else:
            self.statisticsRange.setText(_("No commits yet"))

        topNames = [name for name, _count in details.contributors[:5]]
        monthLabels = []
        for month in details.months:
            date = QDate.fromString(month + "-01", "yyyy-MM-dd")
            monthLabels.append(locale.toString(date, "MMM yyyy"))
        series = [
            (name, [details.monthlyContributors.get(month, {}).get(name, 0)
                    for month in details.months])
            for name in topNames
        ]
        self.commitChart.setData(monthLabels, series)
        self.contributorDonut.setData(details.contributors)

        self.contributorTable.setRowCount(len(details.contributors))
        for row, (name, count) in enumerate(details.contributors):
            self.contributorTable.setItem(row, 0, QTableWidgetItem(name))
            countItem = QTableWidgetItem(str(count))
            countItem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.contributorTable.setItem(row, 1, countItem)
        self.contributorTable.resizeRowsToContents()

    def showSplash(self):
        self.ui.leftStack.setCurrentWidget(self.ui.splashPage)

    def _buildRepoPane(self):
        pane = self.ui.repoPane
        layout: QVBoxLayout = self.ui.repoPaneLayout

        self.paneTitle = QLabel(pane)
        self.paneTitle.setObjectName("HomeRepoPaneTitle")
        self.paneTitle.setText(_("Repositories on this machine"))

        self.paneStatus = QLabel(pane)
        self.paneStatus.setObjectName("HomeRepoPaneStatus")
        tweakWidgetFont(self.paneStatus, 90)

        self.filterEdit = QLineEdit(pane)
        self.filterEdit.setObjectName("HomeRepoFilter")
        self.filterEdit.setPlaceholderText(_("Type a name to filter…"))
        self.filterEdit.setClearButtonEnabled(True)
        self.filterEdit.textChanged.connect(self.applyFilter)

        self.repoTree = QTreeWidget(pane)
        self.repoTree.setObjectName("HomeRepoTree")
        self.repoTree.setHeaderHidden(True)
        self.repoTree.setUniformRowHeights(True)
        self.repoTree.itemActivated.connect(self.onItemActivated)
        self.repoTree.currentItemChanged.connect(self.onCurrentItemChanged)

        self.rescanButton = QPushButton(_("&Rescan"), pane)
        self.rescanButton.setObjectName("HomeRescanButton")
        self.rescanButton.clicked.connect(lambda: self.rescan(force=True))

        self.fetchAllButton = QPushButton(_("Fetch A&ll"), pane)
        self.fetchAllButton.setObjectName("HomeFetchAllButton")
        self.fetchAllButton.setIcon(stockIcon("git-fetch"))
        self.fetchAllButton.setToolTip(_("Ask every remote what’s new, so you can see "
                                         "which repos have commits waiting for you"))
        self.fetchAllButton.clicked.connect(lambda: self.rescan(force=True, fetch=True))

        self.foldersButton = QPushButton(_("&Folders"), pane)
        self.foldersButton.setObjectName("HomeFoldersButton")
        self.foldersButton.setToolTip(_("Choose which folders to search for repos"))
        self.foldersMenu = QMenu(self.foldersButton)
        self.foldersButton.setMenu(self.foldersMenu)
        self.foldersMenu.aboutToShow.connect(self.fillFoldersMenu)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.paneStatus)
        buttons.addStretch(1)
        buttons.addWidget(self.foldersButton)
        buttons.addWidget(self.fetchAllButton)
        buttons.addWidget(self.rescanButton)

        layout.addWidget(self.paneTitle)
        layout.addWidget(self.filterEdit)
        layout.addWidget(self.repoTree)
        layout.addLayout(buttons)

    # -------------------------------------------------------------------------
    # Scanning

    def scanRoots(self) -> list[str]:
        if settings.history.scanRoots:
            return settings.history.scanRoots
        if APP_TESTMODE:
            # Unit tests must never walk the real home directory
            return []
        return defaultScanRoots()  # pragma: no cover - APP_TESTMODE takes the branch above

    def refresh(self):
        """Show what we already know, then look for more in the background."""
        self.populate([RepoInfo.fromDict(d) for d in settings.history.scannedRepos])
        self.rescan()

    def stopScan(self):
        """Never let a running QThread outlive its widget: Qt aborts the process."""
        if self.scanner is not None and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait()
        self.fetchAllButton.setEnabled(True)

    def closeEvent(self, event: QCloseEvent):
        self.stopScan()
        super().closeEvent(event)

    def hideEvent(self, event: QHideEvent):
        # No point scanning while you're looking at a repo
        self.stopScan()
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent):
        # The one place that catches every way of landing here: app start with
        # no tabs, closing the last tab, or switching to Home.
        super().showEvent(event)
        self.refresh()

    def rescan(self, force: bool = False, fetch: bool = False):
        if self.scanner is not None and self.scanner.isRunning():
            if not force:
                return
            self.stopScan()

        roots = self.scanRoots()
        self.paneStatus.setText(_("Searching {0}…", ", ".join(compactPath(r) for r in roots)))
        self.fetchAllButton.setEnabled(not fetch)
        self.scanner = RepoScanner(roots, DEFAULT_MAX_DEPTH, fetch=fetch, parent=self)
        self.scanner.progress.connect(self.onScanProgress)
        self.scanner.activity.connect(self.onScanActivity)
        self.scanner.resultsReady.connect(self.onScanFinished)
        self.scanner.start()

    def onScanActivity(self, message: str):
        """A fetch takes long enough that silence looks like a hang."""
        if message:
            self.paneStatus.setText(message)

    def onScanProgress(self, repos: list[RepoInfo]):
        """Show what's turned up so far, so a long scan isn't a blank list."""
        self.populate(repos, scanning=True)

    def onScanFinished(self, repos: list[RepoInfo]):
        settings.history.scannedRepos = [r.asDict() for r in repos]
        settings.history.setDirty()
        self.fetchAllButton.setEnabled(True)
        self.populate(repos)

        # Say which repos we couldn't reach: a silent skip reads as "nothing new"
        failures = self.scanner.fetchFailures if self.scanner is not None else []
        if failures:
            self.paneStatus.setText(self.paneStatus.text() + " · " + _n(
                "{n} couldn’t be fetched", "{n} couldn’t be fetched", len(failures)))
            self.paneStatus.setToolTip(
                _("Couldn’t fetch:") + "\n" + "\n".join(compactPath(p) for p in failures))

    def fillFoldersMenu(self):
        actions = [ActionDef(_("&Add Folder…"), self.pickScanRoot, icon="folder-open")]

        roots = settings.history.scanRoots
        if roots:
            actions.append(ActionDef.SEPARATOR)
            for root in roots:
                actions.append(ActionDef(
                    _("Stop Searching {0}", compactPath(root)),
                    lambda r=root: self.removeScanRoot(r),
                    icon="SP_TrashIcon"))

        self.foldersMenu.clear()
        ActionDef.addToQMenu(self.foldersMenu, *actions)

    def removeScanRoot(self, root: str):
        settings.history.scanRoots = [r for r in settings.history.scanRoots if r != root]
        settings.history.setDirty()
        self.rescan(force=True)

    def pickScanRoot(self):
        qfd = PersistentFileDialog.openDirectory(self, "HomeScanRoot", _("Folder to search for repos"))
        qfd.fileSelected.connect(self.onScanRootPicked)
        qfd.show()

    def onScanRootPicked(self, path: str):
        if not path:  # pragma: no cover - the dialog doesn't emit an empty path
            return
        path = os.path.normpath(path)
        # Folders add up: repos aren't all under one roof
        roots = settings.history.scanRoots
        if path not in roots:
            settings.history.scanRoots = roots + [path]
            settings.history.setDirty()
        self.rescan(force=True)

    # -------------------------------------------------------------------------
    # The tree

    def populate(self, repos: list[RepoInfo], scanning: bool = False):
        """Lay the repos out as the folder tree they live in."""
        byPath = {os.path.normpath(r.path): r for r in repos}
        recentPaths = [os.path.normpath(p) for p in
                       settings.history.getRecentRepoPaths(settings.prefs.maxRecentRepos)]
        for path in recentPaths:
            byPath.setdefault(os.path.normpath(path), RepoInfo(path=os.path.normpath(path)))
        paths = list(byPath)
        self.repoInfos = byPath

        self.repoTree.clear()
        noReadme = 0
        folders: dict[str, QTreeWidgetItem] = {}
        prefix = os.path.commonpath(paths) if len(paths) > 1 else (os.path.dirname(paths[0]) if paths else "")

        if recentPaths:
            recentRoot = QTreeWidgetItem([_("Recent")])
            recentRoot.setExpanded(True)
            self.repoTree.addTopLevelItem(recentRoot)
            for path in recentPaths:
                recentRoot.addChild(self._repoTreeItem(byPath[path]))

        repositoryRoot = None
        if paths:
            repositoryRoot = QTreeWidgetItem([_("Repositories")])
            repositoryRoot.setExpanded(True)
            self.repoTree.addTopLevelItem(repositoryRoot)

        for path in sorted(paths, key=lambda p: p.casefold()):
            relative = os.path.relpath(path, prefix) if prefix and path.startswith(prefix) else path
            parts = [p for p in relative.split(os.sep) if p not in ("", ".")]
            parent: QTreeWidgetItem | None = None
            for depth, part in enumerate(parts[:-1]):
                key = os.sep.join(parts[:depth + 1])
                folder = folders.get(key)
                if folder is None:
                    folder = QTreeWidgetItem([part])
                    folder.setIcon(0, stockIcon("git-folder"))
                    folders[key] = folder
                    if parent is None:
                        repositoryRoot.addChild(folder)
                    else:
                        parent.addChild(folder)
                parent = folder

            info = byPath[path]
            leaf = self._repoTreeItem(info)
            if not info.unreadable and not self.findReadme(path):
                noReadme += 1
            if parent is None:
                repositoryRoot.addChild(leaf)
            else:
                parent.addChild(leaf)

        self.repoTree.expandAll()
        if self.repoTree.currentItem() is None:
            self.showSplash()
        roots = self.scanRoots()
        where = ", ".join(compactPath(r) for r in roots) if roots else ""
        count = _n("{n} repository", "{n} repositories", len(paths))
        if scanning:
            count = _("{0} so far…", count)
        elif noReadme:
            count += " · " + _n("{n} without a README", "{n} without a README", noReadme)
        self.paneStatus.setText(count + (f" · {elide(where, ems=40)}" if where else ""))
        self.paneStatus.setToolTip("\n".join(roots))
        self.applyFilter(self.filterEdit.text())

    def _repoTreeItem(self, info: RepoInfo) -> QTreeWidgetItem:
        path = os.path.normpath(info.path)
        label = settings.history.peekRepoNickname(path)
        badge = self.statusBadge(info)
        item = QTreeWidgetItem([f"{label}  {badge}" if badge else label])
        item.setData(0, WelcomeWidget.PathRole, path)
        item.setToolTip(0, self.statusToolTip(info))
        item.setIcon(0, stockIcon("git-folder" if os.path.isdir(path) else "achtung"))
        if info.needsAttention:
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
        return item

    @staticmethod
    def statusBadge(info: RepoInfo) -> str:
        """
        A compact marker for what's outstanding.

        Uncommitted work, unpushed commits and unpulled ones are separate
        problems, so they get separate marks: having committed says nothing
        about having pushed, and either says nothing about what the remote did
        in the meantime.
        """
        marks = []
        if info.dirty:
            marks.append("●")  # solid dot: changes not committed
        if info.ahead > 0:
            marks.append(f"↑{info.ahead}")  # up arrow: commits not pushed
        if info.behind > 0:
            marks.append(f"↓{info.behind}")  # down arrow: commits not pulled
        return " ".join(marks)

    def statusToolTip(self, info: RepoInfo) -> str:
        lines = [info.path]
        if info.branch:
            lines.append(_("Branch: {0}", info.branch))
        if info.unreadable:
            lines.append(_("This repo couldn’t be read."))
        elif not self.findReadme(info.path):
            lines.append(_("No README — worth adding one."))
        if info.dirty:
            lines.append(_("Uncommitted changes"))
        if info.ahead > 0:
            lines.append(_n("{n} commit not pushed", "{n} commits not pushed", info.ahead))
        if info.behind > 0:
            lines.append(_n("{n} commit waiting on the remote",
                            "{n} commits waiting on the remote", info.behind))
        if info.noUpstream and not info.unreadable:
            lines.append(_("This branch isn’t tracking a remote branch."))
        if not info.needsAttention and not info.noUpstream and not info.unreadable:
            lines.append(_("Nothing outstanding"))
        return "\n".join(lines)

    def applyFilter(self, needle: str):
        needle = needle.strip().casefold()
        for i in range(self.repoTree.topLevelItemCount()):
            self._filterItem(self.repoTree.topLevelItem(i), needle)

    def _filterItem(self, item: QTreeWidgetItem, needle: str) -> bool:
        """Hide what doesn't match; a folder stays if any of its repos does."""
        path = item.data(0, WelcomeWidget.PathRole)
        anyChildVisible = False
        for i in range(item.childCount()):
            anyChildVisible |= self._filterItem(item.child(i), needle)

        if not needle:
            matches = True
        elif path:
            matches = needle in item.text(0).casefold() or needle in path.casefold()
        else:
            matches = needle in item.text(0).casefold()

        visible = matches or anyChildVisible
        item.setHidden(not visible)
        return visible

    def onCurrentItemChanged(self, item: QTreeWidgetItem | None, previous=None):
        path = item.data(0, WelcomeWidget.PathRole) if item is not None else ""
        if path:
            self.showRepository(path)
        else:
            self.showSplash()

    def onItemActivated(self, item: QTreeWidgetItem, column: int = 0):
        path = item.data(0, WelcomeWidget.PathRole)
        if path:
            self.openRepoPath.emit(path)
        else:
            item.setExpanded(not item.isExpanded())
