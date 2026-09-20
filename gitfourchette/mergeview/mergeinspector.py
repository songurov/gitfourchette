# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
What a merge commit decided: the files whose result matches neither side, the
two versions that met there, and what was kept.
"""

from __future__ import annotations

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class MergeInspector(QDialog):
    """
    The files somebody had to decide on in a merge, and what they decided.

    Git says which files those are: in a combined diff, a file only shows up
    when the merge result differs from every parent. Everything else came
    straight from one side and nobody had to choose.
    """

    fileChosen = Signal(str)
    "A path the person wants to look at side by side."

    def __init__(self, subject: str, shortHash: str, paths: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("MergeInspector")
        self.setWindowTitle(_("What merge {0} decided", shortHash))

        headline = QLabel(self)
        headline.setWordWrap(True)
        headline.setText("<b>" + escape(subject) + "</b>")

        explainer = QLabel(self)
        explainer.setWordWrap(True)
        explainer.setProperty("class", "secondary")
        explainer.setText(_n(
            "{n} file in this merge matches neither side: somebody decided what it would say.",
            "{n} files in this merge match neither side: somebody decided what they would say.",
            len(paths)))

        self.fileList = QListWidget(self)
        self.fileList.setObjectName("MergeInspectorFiles")
        self.fileList.addItems(paths)
        self.fileList.setCurrentRow(0)
        self.fileList.itemDoubleClicked.connect(lambda: self.openCurrent())

        self.openButton = QPushButton(_("See both versions"), self)
        self.openButton.setDefault(True)
        self.openButton.setEnabled(bool(paths))
        self.openButton.clicked.connect(self.openCurrent)
        closeButton = QPushButton(_("Close"), self)
        closeButton.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(closeButton)
        buttons.addWidget(self.openButton)

        layout = QVBoxLayout(self)
        layout.addWidget(headline)
        layout.addWidget(explainer)
        layout.addWidget(self.fileList, 1)
        layout.addLayout(buttons)

    def currentPath(self) -> str:
        item = self.fileList.currentItem()
        return item.text() if item is not None else ""

    def openCurrent(self):
        path = self.currentPath()
        if path:
            self.fileChosen.emit(path)
