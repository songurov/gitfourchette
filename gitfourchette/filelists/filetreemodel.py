# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# -----------------------------------------------------------------------------

from gitfourchette.filelists.filelistmodel import FileListModel
from gitfourchette.qt import *

_EMPTY_INDEX = QModelIndex()


class _Node:
    def __init__(self, name: str, parent: "_Node | None" = None, sourceRow: int = -1):
        self.name = name
        self.parent = parent
        self.sourceRow = sourceRow
        self.children: list[_Node] = []


class FileTreeModel(QAbstractItemModel):
    """Directory presentation of a FileListModel. Only leaves represent files."""

    def __init__(self, source: FileListModel, parent: QObject):
        super().__init__(parent)
        self.source = source
        self.root = _Node("")
        self.paths: dict[str, _Node] = {}
        source.modelReset.connect(self.rebuild)
        self.rebuild()

    def rebuild(self):
        self.beginResetModel()
        self.root = _Node("")
        self.paths = {}
        folders: dict[str, _Node] = {"": self.root}
        for row, delta in enumerate(self.source.deltas):
            path = delta.new.path
            parts = path.split("/")
            parent = self.root
            prefix = ""
            for part in parts[:-1]:
                prefix = f"{prefix}/{part}" if prefix else part
                node = folders.get(prefix)
                if node is None:
                    node = _Node(part, parent)
                    parent.children.append(node)
                    folders[prefix] = node
                parent = node
            leaf = _Node(parts[-1], parent, row)
            parent.children.append(leaf)
            self.paths[path] = leaf
        self._compactFolders(self.root)
        self.endResetModel()

    def _compactFolders(self, node: _Node):
        for child in node.children:
            self._compactFolders(child)
        if node is self.root or node.sourceRow >= 0:
            return
        while len(node.children) == 1 and node.children[0].sourceRow < 0:
            child = node.children[0]
            node.name += "/" + child.name
            node.children = child.children
            for grandchild in node.children:
                grandchild.parent = node

    def _node(self, index: QModelIndex) -> _Node:
        return index.internalPointer() if index.isValid() else self.root

    def index(self, row: int, column: int = 0, parent: QModelIndex = _EMPTY_INDEX) -> QModelIndex:
        node = self._node(parent)
        if column != 0 or row < 0 or row >= len(node.children):
            return QModelIndex()
        return self.createIndex(row, column, node.children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        parent = self._node(index).parent
        if parent is None or parent is self.root:
            return QModelIndex()
        grandparent = parent.parent
        assert grandparent is not None
        return self.createIndex(grandparent.children.index(parent), 0, parent)

    def rowCount(self, parent: QModelIndex = _EMPTY_INDEX) -> int:
        return len(self._node(parent).children) if parent.column() <= 0 else 0

    def columnCount(self, parent: QModelIndex = _EMPTY_INDEX) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = self._node(index)
        if node.sourceRow < 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return node.name
            if role == Qt.ItemDataRole.DecorationRole:
                return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return node.name
        return self.source.data(self.source.index(node.sourceRow), role)

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled
        if self._node(index).sourceRow >= 0:
            flags |= Qt.ItemFlag.ItemIsSelectable
        return flags

    def indexForPath(self, path: str) -> QModelIndex:
        node = self.paths[path]
        assert node.parent is not None
        return self.createIndex(node.parent.children.index(node), 0, node)
