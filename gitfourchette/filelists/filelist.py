# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import suppress
from typing import Literal

from gitfourchette import trtables
from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.exttools.usercommand import UserCommand
from gitfourchette.filelists.filebatchtask import FileBatchTask
from gitfourchette.filelists.filelistmodel import FileListModel
from gitfourchette.filelists.filetreemodel import FileTreeModel
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.gitdriver import *
from gitfourchette.gitdriver.gitdeltafile import HexHashFFFF
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.search.itemviewsearchprovider import ItemViewSearchProvider
from gitfourchette.settings import FileListClick, getDiffToolName, getExternalEditorName
from gitfourchette.tasks import *
from gitfourchette.themes import ThemeVariant, activeTheme
from gitfourchette.toolbox import *


class FileListDelegate(QStyledItemDelegate):
    """
    Item delegate for FileList that supports highlighting search terms from a SearchBar
    """

    NeutralIconLead = 5
    "Neutral: room before a row's first icon."
    NeutralIconGap = 5
    "Neutral: room after each icon but the last."
    NeutralTextLead = 7
    "Neutral: room between the last icon and the name."

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        widget = option.widget
        assert isinstance(widget, FileList)
        neutral = widget.neutralRows

        isActive = bool(option.state & QStyle.StateFlag.State_Active)
        if neutral:
            isActive = widget.selectionIsEmphasized()
        isSelected = bool(option.state & QStyle.StateFlag.State_Selected)
        colorGroup = QPalette.ColorGroup.Active if isActive else QPalette.ColorGroup.Inactive

        # Gather data from model
        icon: QIcon = index.data(Qt.ItemDataRole.DecorationRole)
        emblem: QIcon | None = index.data(FileListModel.Role.Decoration2)
        font: QFont = index.data(Qt.ItemDataRole.FontRole)
        fullText: str = index.data(Qt.ItemDataRole.DisplayRole)
        searchTerm: str = widget.searchBar.provider.term()

        if index.data(FileListModel.Role.Delta) is None:
            if neutral:
                self.paintNeutralFolder(painter, option, icon, fullText)
            else:
                super().paint(painter, option, index)
            return

        # Prepare icon and text rects
        rect = QRect(option.rect)
        if neutral:
            rect.adjust(self.NeutralIconLead, 0, -2 - widget.rowRightInset(), 0)
        else:
            rect.adjust(2, 0, -2, 0)

        # Begin painting
        painter.save()
        if font:
            painter.setFont(font)
        fontMetrics = painter.fontMetrics()

        # Draw default background (Neutral: FileList.drawRow has drawn the whole row's)
        if not neutral:
            widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, widget)

        # Draw icons. Neutral follows the status tile with a page, as Fork does.
        icons = [icon, widget.fileGlyph(isSelected and isActive), emblem] if neutral else [icon, emblem]
        icons = [i for i in icons if i is not None]
        for i in icons:
            iconRect = QRect(rect)
            iconRect.setWidth(option.decorationSize.width())
            i.paint(painter, iconRect, option.decorationAlignment)
            if neutral:
                gap = self.NeutralTextLead if i is icons[-1] else self.NeutralIconGap
                rect.setLeft(iconRect.right() + 1 + gap)
            else:
                rect.setLeft(iconRect.right() + 4)

        # Prepare elided text
        text = fontMetrics.elidedText(fullText, option.textElideMode, rect.width())

        # Split path into directory and filename for better readability
        isFileNameFirst = settings.prefs.pathDisplayStyle == PathDisplayStyle.FileNameFirst
        if isFileNameFirst:
            parts = text.split('\0', 1)
        else:
            slash = text.rfind('/')
            if slash < fullText.rfind('/'):
                # The last slash is either elided, or it's after the ellipsis.
                ellipsis = text.rfind('\u2026')
                slash = max(slash, ellipsis)
            parts = [text[:slash + 1], text[slash + 1:]]

        # Draw text parts
        textRectBackup = QRect(rect)
        for partNo, part in enumerate(parts):
            isDirectoryPart = isFileNameFirst == (partNo > 0)

            colorRole = (QPalette.ColorRole.HighlightedText if isSelected
                         else QPalette.ColorRole.PlaceholderText if isDirectoryPart
                         else QPalette.ColorRole.WindowText)

            textColor = option.palette.color(colorGroup, colorRole)
            if isSelected and isDirectoryPart:
                textColor.setAlphaF(0.7)

            painter.setPen(textColor)
            painter.drawText(rect, option.displayAlignment, part)

            # Prepare rect for next part
            partWidth = fontMetrics.horizontalAdvance(part)
            rect.setLeft(rect.left() + partWidth)

        # Restore text rect
        rect = textRectBackup

        # Highlight search term
        if searchTerm and searchTerm in fullText.lower():
            needlePos = text.lower().find(searchTerm)
            if needlePos < 0:
                needlePos = text.find("\u2026")  # unicode ellipsis character (...)
                needleLen = 1
            else:
                needleLen = len(searchTerm)

            SearchBar.highlightNeedle(painter, rect, text, needlePos, needleLen)

        # Finish painting
        painter.restore()

    def paintNeutralFolder(self, painter: QPainter, option: QStyleOptionViewItem, icon: QIcon, text: str):
        """A folder row, lined up with the file rows: its icon where their status tiles are."""
        widget = option.widget
        assert isinstance(widget, FileList)
        rect = QRect(option.rect)
        rect.adjust(self.NeutralIconLead, 0, -2 - widget.rowRightInset(), 0)
        iconRect = QRect(rect)
        iconRect.setWidth(option.decorationSize.width())
        # A folder drawn in the tiles' 14 px comes out squat next to them: give it 2 px more
        folderRect = iconRect.adjusted(-1, 0, 1, 0)
        icon.paint(painter, folderRect, option.decorationAlignment)
        rect.setLeft(iconRect.right() + 1 + self.NeutralIconGap)

        painter.save()
        painter.setPen(option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText))
        text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, rect.width())
        painter.drawText(rect, option.displayAlignment, text)
        painter.restore()


class FileListSearchProvider(ItemViewSearchProvider):
    @property
    def buddyModel(self):
        view = self._buddy
        return view.flModel

    def _currentRow(self):
        view = self._buddy
        path = view.currentIndex().data(FileListModel.Role.FilePath)
        return view.flModel.fileRows.get(path, -1)

    def _jumpToIndex(self, index: QModelIndex):
        view = self._buddy
        if view.treeMode:
            path = index.data(FileListModel.Role.FilePath)
            index = view.treeModel.indexForPath(path)
            ancestor = index.parent()
            while ancestor.isValid():
                view.expand(ancestor)
                ancestor = ancestor.parent()
        view.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.SelectCurrent)


class FileList(QTreeView):
    nothingClicked = Signal()
    """ Only emitted if the widget has focus. """
    selectedCountChanged = Signal(int)
    openSubRepo = Signal(str)
    statusMessage = Signal(str)

    repoModel: RepoModel

    _selectionBackup: list[str]
    """
    Backup of selected paths before refreshing the view.
    """

    def __init__(self, repoModel: RepoModel, parent: QWidget, navContext: NavContext):
        super().__init__(parent)

        self.repoModel = repoModel

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.onContextMenuRequested)

        self._flModel = FileListModel(self, self.repoModel.repo, navContext)
        self.treeModel = FileTreeModel(self._flModel, self)
        self.treeMode = False
        self.setModel(self._flModel)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self._selectionBackup = []

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        iconSize = self.fontMetrics().height()
        self.setIconSize(QSize(iconSize, iconSize))
        self.defaultIconSize = iconSize
        self.neutralRows = False
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # prevent editing text after double-clicking
        self.setUniformRowHeights(True)  # potential perf boost with many files

        searchProvider = FileListSearchProvider(self)
        searchProvider.dataRole = FileListModel.Role.FilePath

        self.searchBar = SearchBar(self, searchProvider)
        self.searchBar.ui.forwardButton.hide()
        self.searchBar.ui.backwardButton.hide()
        self.searchBar.hide()
        self._flModel.modelAboutToBeReset.connect(self.searchBar.reevaluateSearchTerm)

        # Search result highlighter
        self.setItemDelegate(FileListDelegate(self))

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        GFApplication.instance().restyle.connect(self.refreshTheme)
        self.refreshPrefs()

        makeWidgetShortcut(self, self.searchBar.hideOrBeep, "Escape")
        makeWidgetShortcut(self, self.copyPaths, QKeySequence.StandardKey.Copy)

    def refreshPrefs(self):
        self.setTreeMode(settings.prefs.fileTreeView)
        self.setVerticalScrollMode(settings.prefs.listViewScrollMode)
        nameFirst = settings.prefs.pathDisplayStyle == PathDisplayStyle.FileNameFirst
        self.setTextElideMode(Qt.TextElideMode.ElideRight if nameFirst else Qt.TextElideMode.ElideMiddle)
        self.refreshTheme()

    def refreshTheme(self):
        """
        Neutral lays the rows out like Fork's: inset from the edges, a folder
        level every 16 px under a thin chevron, 14 px icons, and a rounded pill
        across the whole row for the selection. Other themes keep Qt's rows.
        """
        theme = activeTheme()
        self.neutralRows = theme is not None and theme.variant == ThemeVariant.Neutral

        if theme is not None and theme.fileTreeIndent:
            self.setIndentation(theme.fileTreeIndent)
        else:
            self.resetIndentation()

        iconSize = (theme.fileIconSize if theme is not None else 0) or self.defaultIconSize
        self.setIconSize(QSize(iconSize, iconSize))
        self.viewport().update()

    def rowRightInset(self) -> int:
        """
        Neutral: room between the rows and the list's right edge. The theme's
        padding leaves it out so the scroll bar can sit at the edge; when the
        scroll bar shows, the rows stop at it instead.
        """
        theme = activeTheme()
        if not self.neutralRows or theme is None or self.verticalScrollBar().isVisible():
            return 0
        return theme.fileListInset

    def selectionIsEmphasized(self) -> bool:
        """Neutral: the selection takes the accent color while the list has the focus, as on the Mac."""
        return self.hasFocus() and self.isActiveWindow()

    def fileGlyph(self, onAccent: bool = False) -> QIcon:
        """Neutral: the page drawn after a file's status tile, in the selected text's color on the accent."""
        theme = activeTheme()
        if theme is None:
            return stockIcon("doc-filled")
        color = self.palette().color(QPalette.ColorRole.HighlightedText).name() if onAccent else theme.fileGlyphColor
        return stockIcon("doc-filled", f"gray={color}")

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if self.neutralRows and self.selectionModel().isSelected(index):
            group = QPalette.ColorGroup.Active if self.selectionIsEmphasized() else QPalette.ColorGroup.Inactive
            radius = activeTheme().outerRadius
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.palette().color(group, QPalette.ColorRole.Highlight))
            pill = QRectF(option.rect).adjusted(0, 0, -self.rowRightInset(), 0)
            painter.drawRoundedRect(pill, radius, radius)
            painter.restore()
        super().drawRow(painter, option, index)

    def drawBranches(self, painter: QPainter, rect: QRect, index: QModelIndex):
        if not self.neutralRows:
            super().drawBranches(painter, rect, index)
            return
        if not self.treeMode or self.treeModel.rowCount(index) == 0:
            return  # no folder, no chevron
        # A thin chevron, centered in the last step of the indentation
        indent = self.indentation()
        slot = QRect(rect.right() + 1 - indent, rect.top(), indent, rect.height())
        iconRect = QRect(0, 0, 16, 16)
        iconRect.moveCenter(slot.center())
        stockIcon("chevron-down" if self.isExpanded(index) else "chevron-right").paint(painter, iconRect)

    def focusInEvent(self, event: QFocusEvent):
        super().focusInEvent(event)
        if self.neutralRows:
            self.viewport().update()  # the selection's color follows the focus

    def focusOutEvent(self, event: QFocusEvent):
        super().focusOutEvent(event)
        if self.neutralRows:
            self.viewport().update()

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    @property
    def navContext(self) -> NavContext:
        return self.flModel.navContext

    @property
    def flModel(self) -> FileListModel:
        return self._flModel

    def fileCount(self) -> int:
        return self.flModel.rowCount()

    def setTreeMode(self, enabled: bool):
        if self.treeMode == enabled:
            return
        selectedPaths = list(self.selectedPaths())
        currentPath = self.currentIndex().data(FileListModel.Role.FilePath)
        with QSignalBlockerContext(self):
            self.treeMode = enabled
            self.setModel(self.treeModel if enabled else self.flModel)
            if enabled:
                self.expandAll()
            selection = QItemSelection()
            for path in selectedPaths:
                index = self.indexForPath(path)
                selection.select(index, index)
            self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.Select)
            if currentPath in self.flModel.fileRows:
                self.selectionModel().setCurrentIndex(
                    self.indexForPath(currentPath), QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selectedCountChanged.emit(len(selectedPaths))
        self.searchBar.reevaluateSearchTerm()

    def indexForPath(self, path: str) -> QModelIndex:
        return (self.treeModel.indexForPath(path) if self.treeMode
                else self.flModel.index(self.flModel.getRowForFile(path)))

    def isEmpty(self):
        return self.fileCount() == 0

    def setContents(self, deltas: Iterable[GitDelta]):
        self.flModel.setContents(deltas)
        if self.treeMode:
            self.expandAll()
        self.updateFocusPolicy()
        self.searchBar.reevaluateSearchTerm()

    def clear(self):
        self.flModel.clear()
        assert self.isEmpty()
        self.updateFocusPolicy()

    def updateFocusPolicy(self):
        focusPolicy = Qt.FocusPolicy.StrongFocus if not self.isEmpty() else Qt.FocusPolicy.ClickFocus
        self.setFocusPolicy(focusPolicy)

    # -------------------------------------------------------------------------
    # Context menu

    def makeContextMenu(self):
        deltas = list(self.selectedDeltas())
        if len(deltas) == 0:
            return None

        actions = self.contextMenuActions(deltas)
        actions.extend([
            ActionDef.SEPARATOR,
            ActionDef(_("Tree view"), lambda: GFApplication.applyPrefs(fileTreeView=True), checkState=self.treeMode),
            ActionDef(_("List view"), lambda: GFApplication.applyPrefs(fileTreeView=False), checkState=not self.treeMode),
        ])
        menu = ActionDef.makeQMenu(self, actions)
        menu.setObjectName("FileListContextMenu")
        return menu

    def onContextMenuRequested(self, point: QPoint):
        index = self.indexAt(point)
        if self.treeMode and index.isValid() and index.data(FileListModel.Role.Delta) is None:
            return
        menu = self.makeContextMenu()
        if menu is not None:
            menu.aboutToHide.connect(menu.deleteLater)
            menu.popup(self.mapToGlobal(point))

    def contextMenuActions(self, deltas: list[GitDelta]) -> list[ActionDef]:
        """ To be overridden """

        def pathDisplayStyleAction(pds: PathDisplayStyle):
            return ActionDef(
                englishTitleCase(trtables.enum(pds)),
                lambda: GFApplication.applyPrefs(pathDisplayStyle=pds),
                checkState=settings.prefs.pathDisplayStyle == pds)

        n = len(deltas)

        actions = [
            ActionDef.SEPARATOR,

            ActionDef(
                _n("Open &Folder", "Open {n} &Folders", n),
                self.showInFolder,
                "SP_DirIcon",
            ),

            ActionDef(
                _n("&Copy Path", "&Copy {n} Paths", n),
                self.copyPaths,
                shortcuts=QKeySequence.StandardKey.Copy,
            ),

            ActionDef(
                englishTitleCase(_("Path display style")),
                submenu=[pathDisplayStyleAction(style) for style in PathDisplayStyle],
            ),
        ]

        actions.extend(GFApplication.instance().mainWindow.contextualUserCommands(
            UserCommand.Token.File,
            UserCommand.Token.FileDir,
            UserCommand.Token.FileAbs,
            UserCommand.Token.FileDirAbs,
        ))

        return actions

    def contextMenuActionStash(self):
        return ActionDef(
            _("Stas&h Changes…"),
            self.wantPartialStash,
            icon="git-stash-black",
            shortcuts=TaskBook.shortcuts.get(NewStash, []))

    def contextMenuActionRevertMode(self, deltas: list[GitDelta], callback: Callable, ellipsis=True) -> ActionDef:
        n = len(deltas)
        action = ActionDef(_n("Revert Mode Change", "Revert Mode Changes", n), callback, enabled=False)

        # Scan deltas for mode changes
        for delta in deltas:
            # Scan for Modified, Renamed, or Copied
            if delta.status not in [GitStatus.Modified, GitStatus.Renamed, GitStatus.Copied]:
                continue

            # Skip if mode didn't change
            if delta.old.mode == delta.new.mode:
                continue

            # It has to be a mode we can actually revert
            if delta.new.mode not in [FileMode.BLOB, FileMode.BLOB_EXECUTABLE]:
                continue

            action.enabled = True

            # Set specific caption if it's a single item
            if n != 1:
                pass
            elif delta.new.mode == FileMode.BLOB_EXECUTABLE:
                action.caption = _("Revert Mode to Non-Executable")
            elif delta.new.mode == FileMode.BLOB:
                action.caption = _("Revert Mode to Executable")

        if ellipsis:
            action.caption += "…"

        return action

    def contextMenuActionsDiff(self, deltas: list[GitDelta]) -> list[ActionDef]:
        n = len(deltas)

        return [
            ActionDef(
                _("Open Diff in {0}", settings.getDiffToolName()),
                self.wantOpenInDiffTool,
                icon="vcs-diff"),

            ActionDef(
                _n("E&xport Diff As Patch…", "E&xport Diffs As Patch…", n),
                self.savePatchAs),
        ]

    def contextMenuActionsEdit(self, deltas: list[GitDelta]) -> list[ActionDef]:
        n = len(deltas)

        return [
            ActionDef(
                _("&Edit in {tool}", tool=settings.getExternalEditorName()),
                self.openWorkdirFile,
                icon="SP_FileIcon"),

            ActionDef(
                _n("Edit &HEAD Version in {tool}", "Edit &HEAD Versions in {tool}", n=n, tool=settings.getExternalEditorName()),
                self.openHeadRevision,
                enabled=any(not d.status.isAddedOrUntracked for d in deltas),
            ),
        ]

    def contextMenuActionBlame(self, deltas: list[GitDelta]) -> ActionDef:
        isEnabled = False
        if len(deltas) == 1:
            delta = deltas[0]
            assert self.navContext == NavContext.fromGitDeltaSource(delta.source)
            isEnabled = (not delta.source.isWorkdir()) or (not delta.status.isAddedOrUntracked)

        return ActionDef(
            englishTitleCase(OpenBlame.name()) + "\u2026",
            self.blameFile,
            icon=TaskBook.icons[OpenBlame],
            enabled=isEnabled,
            shortcuts=TaskBook.shortcuts[OpenBlame],
        )

    # -------------------------------------------------------------------------

    def confirmBatch(self, callback: FileBatchTask.UnitFunc, title: str, prompt: str):
        deltas = list(self.selectedDeltas())
        FileBatchTask.invoke(self, deltas, callback, title, prompt)

    def openWorkdirFile(self):
        def run(task: RepoTask, delta: GitDelta):
            entryPath = task.repo.in_workdir(delta.new.path)
            ToolProcess.startTextEditor(task.parentWidget(), entryPath)
            yield from task.flowEnterUiThread()  # dummy yield

        toolName = getExternalEditorName()

        self.confirmBatch(
            run,
            _("Open in {0}", toolName),
            _("Really open [# files] in {0}?", toolName))

    def wantOpenInDiffTool(self):
        def run(task: RepoTask, delta: GitDelta):
            yield from task.flowSubtask(OpenInDiffTool, delta)

        toolName = getDiffToolName()

        self.confirmBatch(
            run,
            _("Open in {0}", toolName),
            _("Really open [# files] in {0}?", toolName))

    def showInFolder(self):
        def run(task: RepoTask, delta: GitDelta):
            path = task.repo.in_workdir(delta.new.path)
            path = os.path.normpath(path)  # get rid of any trailing slashes (submodules)
            if not os.path.exists(path):  # check exists, not isfile, for submodules
                raise FileNotFoundError(_("File doesn’t exist at this path anymore."))
            showInFolder(path)
            yield from task.flowEnterUiThread()  # dummy yield

        self.confirmBatch(run, _("Open paths"), _("Really open [# folders]?"))

    def copyPaths(self):
        text = '\n'.join(self.repo.in_workdir(path) for path in self.selectedPaths())
        if not text:
            QApplication.beep()
            return

        if WINDOWS:  # Ensure backslash directory separators
            from pathlib import Path
            path = Path(text)
            text = str(path)

        QApplication.clipboard().setText(text)
        self.statusMessage.emit(clipboardStatusMessage(text))

    def selectRow(self, rowNumber=0):
        if self.isEmpty():
            self.emitNothingClicked()
            self.clearSelection()
        else:
            row = rowNumber or 0
            if self.treeMode:
                path = self.flModel.getFileAtRow(row)
                self.setCurrentIndex(self.treeModel.indexForPath(path))
            else:
                self.setCurrentIndex(self.flModel.index(row, 0))

    def emitNothingClicked(self):
        if self.hasFocus():
            self.nothingClicked.emit()

    def selectionChanged(self, justSelected: QItemSelection, justDeselected: QItemSelection):
        super().selectionChanged(justSelected, justDeselected)

        # We're the active FileList, clear counterpart.
        self._setCounterpart(-1)

        # Don't bother emitting signals if we're blocked
        if self.signalsBlocked():
            return

        selectedIndexes = self.selectedIndexes()
        numSelectedTotal = len(selectedIndexes)

        justSelectedIndexes = list(justSelected.indexes())
        if justSelectedIndexes:
            current = justSelectedIndexes[0]
        else:
            # Deselecting (e.g. with shift/ctrl) doesn't necessarily mean that the selection has been emptied.
            # Find an index that is still selected to keep the DiffView in sync with the selection.
            current = self.currentIndex()

            if current.isValid() and selectedIndexes:
                # currentIndex may be outside the selection, find the selected index that is closest to currentIndex.
                current = min(selectedIndexes, key=lambda index: abs(index.row() - current.row()))
            else:
                current = None

        self.selectedCountChanged.emit(numSelectedTotal)

        if not current or not current.isValid():
            self.emitNothingClicked()
            return

        locator: NavLocator = current.data(FileListModel.Role.Locator)
        if locator is None:
            return
        locator = locator.withExtraFlags(NavFlags.BypassFileSelect)
        Jump.invoke(self, locator)

    def highlightCounterpart(self, loc: NavLocator):
        try:
            row = self.flModel.getRowForFile(loc.path)
        except KeyError:
            row = -1
        self._setCounterpart(row)

    def _setCounterpart(self, newRow: int):
        model = self.flModel
        oldRow = model.highlightedCounterpartRow

        if oldRow == newRow:
            return

        model.highlightedCounterpartRow = newRow

        if oldRow >= 0:
            oldIndex = (self.treeModel.indexForPath(model.getFileAtRow(oldRow)) if self.treeMode
                        else model.index(oldRow, 0))
            self.update(oldIndex)

        if newRow >= 0:
            newIndex = (self.treeModel.indexForPath(model.getFileAtRow(newRow)) if self.treeMode
                        else model.index(newRow, 0))
            self.selectionModel().setCurrentIndex(newIndex, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.update(newIndex)

    def mouseMoveEvent(self, event: QMouseEvent):
        """
        By default, ExtendedSelection lets the user select multiple items by
        holding down LMB and dragging. This event handler enforces single-item
        selection unless the user holds down Shift or Ctrl.
        """
        isLMB = bool(event.buttons() & Qt.MouseButton.LeftButton)
        isShift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        isCtrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if isLMB and not isShift and not isCtrl:
            self.mousePressEvent(event)  # re-route event as if it were a click event
            self.scrollTo(self.indexAt(event.pos()))  # mousePressEvent won't scroll to the item on its own
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        super().mouseReleaseEvent(event)  # Let standard item selection occur first
        index = self.indexAt(event.pos())
        if event.button() == Qt.MouseButton.MiddleButton and index.data(FileListModel.Role.Delta) is not None:
            self.onSpecialClick("middle")

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        super().mouseDoubleClickEvent(event)  # Let standard item selection occur first
        index = self.indexAt(event.pos())
        if self.treeMode and index.isValid() and index.data(FileListModel.Role.Delta) is None:
            self.setExpanded(index, not self.isExpanded(index))
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.onSpecialClick("double")

    def onSpecialClick(self, click: Literal["middle", "double"]):
        if click == "double":
            action = settings.prefs.doubleClickFileList
        elif click == "middle":
            action = settings.prefs.middleClickFileList
        else:
            raise NotImplementedError(f"unknown special click kind '{click}'")

        if action == FileListClick.Nothing:
            pass
        elif action == FileListClick.Folder:
            self.showInFolder()
        elif action == FileListClick.Blame:
            self.blameFile()
        elif action == FileListClick.Edit:
            self.openWorkdirFile()
        elif action == FileListClick.DiffTool:
            self.wantOpenInDiffTool()
        elif action == FileListClick.Stage:
            self.wantStageOrUnstage()
        else:
            raise NotImplementedError(f"unknown special click action '{click}'")

    def selectedDeltas(self) -> Iterator[GitDelta]:
        for index in self.selectedIndexes():
            delta = index.data(FileListModel.Role.Delta)
            if delta is not None:
                yield delta

    def selectedPaths(self) -> Iterator[str]:
        for index in self.selectedIndexes():
            path = index.data(FileListModel.Role.FilePath)
            if path is not None:
                yield path

    def earliestSelectedRow(self) -> int:
        try:
            i = iter(self.selectedIndexes())
            path = next(i).data(FileListModel.Role.FilePath)
            return self.flModel.getRowForFile(path)
        except StopIteration:
            return -1

    def savePatchAs(self):
        deltas = list(self.selectedDeltas())
        ExportPatchCollection.invoke(self, deltas)

    def revertPaths(self):
        # TODO: Convert into a task? (So we can build the patch asynchronously)
        deltas = list(self.selectedDeltas())
        assert len(deltas) == 1
        delta = deltas[0]
        tokens = GitDriver.buildDiffCommand(delta)
        patchData = GitDriver.runSync(*tokens, directory=self.repo.workdir, strict=True)
        ApplyPatchData.invoke(self, patchData, reverse=True,
                              title=_("Revert changes in file"),
                              question=_("Do you want to revert this patch?"))

    def firstPath(self) -> str:
        index: QModelIndex = self.flModel.index(0)
        if index.isValid():
            return index.data(FileListModel.Role.FilePath)
        else:
            return ""

    def selectFile(self, file: str) -> bool:
        if not file:
            return False

        try:
            row = self.flModel.getRowForFile(file)
        except KeyError:
            return False

        index = self.treeModel.indexForPath(file) if self.treeMode else self.flModel.index(row)
        if self.treeMode:
            parent = index.parent()
            while parent.isValid():
                self.expand(parent)
                parent = parent.parent()
        if self.selectionModel().isSelected(index):
            # Re-selecting an already selected row may deselect it??
            return True
        self.setCurrentIndex(index)
        return True

    def deltaForFile(self, file: str) -> GitDelta:
        row = self.flModel.getRowForFile(file)
        return self.flModel.deltas[row]

    def openHeadRevision(self):
        def run(task: RepoTask, delta: GitDelta):
            fakeHeadFile = GitDeltaFile(delta.old.path, HexHashFFFF, source=GitDeltaSource.Commit, sourceCommit=self.repo.head_commit_id)
            fakeHeadDelta = GitDelta(GitStatus.Modified, new=fakeHeadFile)
            yield from task.flowSubtask(OpenRevisionInEditor, fakeHeadDelta, old=False)

        toolName = getExternalEditorName()
        self.confirmBatch(
            run,
            _("Open HEAD revision"),
            _("Really open [# files] in {0}?", toolName))

    def wantPartialStash(self):
        paths = set()
        for delta in self.selectedDeltas():
            # Add both old and new paths so that both are pre-selected
            # if we're stashing a rename.
            paths.add(delta.old.path)
            paths.add(delta.new.path)
        NewStash.invoke(self, list(paths))

    def wantStageOrUnstage(self):
        # To be overridden in DirtyFiles and StagedFiles
        QApplication.beep()

    def openSubmoduleTabs(self):
        for delta in self.selectedDeltas():
            if delta.isSubtreeCommitPatch():
                self.openSubRepo.emit(delta.new.path)

    def backUpSelection(self):
        oldSelected = list(self.selectedPaths())
        self._selectionBackup = oldSelected

    def clearSelectionBackup(self):
        self._selectionBackup = []

    def restoreSelectionBackup(self) -> bool:
        if not self._selectionBackup:
            return False

        paths = self._selectionBackup
        self._selectionBackup = []

        currentIndex: QModelIndex = self.currentIndex()
        cPath = currentIndex.data(FileListModel.Role.FilePath)

        if cPath not in paths:
            # Don't attempt to restore if we've jumped to another file
            return False

        if len(paths) == 1 and paths[0] == cPath:
            # Don't bother if the one file that we've selected is still the current one
            return False

        flModel = self.flModel
        selectionModel = self.selectionModel()
        SF = QItemSelectionModel.SelectionFlag

        with QSignalBlockerContext(self):
            # If we directly manipulate the QItemSelectionModel by calling .select() row-by-row,
            # then shift-selection may act counter-intuitively if the selection was discontiguous.
            # Preparing a QItemSelection upfront mitigates the strange shift-select behavior.
            newItemSelection = QItemSelection()
            for path in paths:
                with suppress(KeyError):
                    flModel.fileRows[path]
                    index = self.treeModel.indexForPath(path) if self.treeMode else flModel.index(flModel.fileRows[path])
                    newItemSelection.select(index, index)
            selectionModel.clearSelection()
            selectionModel.select(newItemSelection, SF.Rows | SF.Select)
            selectionModel.setCurrentIndex(currentIndex, SF.Rows | SF.Current)

        return True

    def blameFile(self):
        def run(delta: GitDelta):
            if delta.source.isWorkdir():
                path = delta.old.path
                commit = NULL_OID
            else:
                path = delta.new.path
                commit = delta.new.sourceCommit
            OpenBlame.invoke(self, path, commit)

        # TODO: For now, only one blame at a time is supported
        try:
            delta = next(self.selectedDeltas())
            run(delta)
        except StopIteration:
            QApplication.beep()
