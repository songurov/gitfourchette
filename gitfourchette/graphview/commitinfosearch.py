# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import re
from collections.abc import Iterable

from gitfourchette.commitquery import CommitQuery
from gitfourchette.graphview.commitlogmodel import CommitLogModel
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, RepoModel
from gitfourchette.search.itemviewsearchprovider import ItemViewSearchProvider
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.graphview.graphview import GraphView


class CommitInfoSearch(ItemViewSearchProvider):
    HashPattern = re.compile(r"[0-9a-fA-F]{1,40}")

    _buddy: GraphView
    likelyHash: bool
    query: CommitQuery

    def __init__(self, parent: GraphView):
        super().__init__(parent)
        self.likelyHash = False
        self.query = CommitQuery()

    # -------------------------------------------------------------------------
    # ItemViewSearchProvider implementation

    def _walkModelImpl(self, rows: Iterable[int]) -> QModelIndex:
        model = self.buddyModel

        if self.query.invalid:
            # A qualifier was given something we couldn't read as a date
            raise KeyError()

        for i in rows:
            index = model.index(i, 0)
            commit = model.data(index, CommitLogModel.Role.Commit)
            if commit is None or commit.id == UC_FAKEID:
                continue
            if self.likelyHash and str(commit.id).startswith(self._term):
                return index
            if self.query.matchesCommit(commit):
                return index

        raise KeyError()

    # -------------------------------------------------------------------------
    # SearchProvider implementation

    def shortTitle(self) -> str:
        return _("Info")

    def longTitle(self) -> str:
        return _("Find commit: text, author:name, after:2026-01-01, before:…")

    def canFilter(self) -> bool:
        return True

    def setFilterState(self, checked: bool):
        super().setFilterState(checked)
        self._queryFilter.filterOnly = self._wantFilter
        self._buddy.clFilter.updateQueryFilter()

    def freeze(self, frozen: bool):
        super().freeze(frozen)
        if frozen:
            # Another kind of search is taking over; stop narrowing the log down
            self._queryFilter.clear()
            self._buddy.clFilter.updateQueryFilter()

    @property
    def _queryFilter(self):
        return self._buddy.repoModel.commitQueryFilter

    def keyboardShortcut(self) -> str:
        return "Alt+I"

    def _termChanged(self):
        super()._termChanged()

        term = self._term
        self.likelyHash = (0 < len(term) <= 40) and bool(self.HashPattern.fullmatch(term))
        self.query = CommitQuery.parse(term)

        self._queryFilter.query = self.query
        self._buddy.clFilter.updateQueryFilter()

    def notFoundMessage(self) -> str:
        message = super().notFoundMessage()
        return CommitInfoSearch.makeNotFoundMessage(message, self._buddy.repoModel)

    @staticmethod
    def makeNotFoundMessage(message: str, repoModel: RepoModel) -> str:
        limitations = []

        if repoModel.hiddenCommits:
            limitations.append(_("hidden branches"))

        if repoModel.truncatedHistory:
            limitations.append(_("truncated history"))
        elif repoModel.repo.is_shallow:
            limitations.append(_("shallow clone"))

        if limitations:
            message += (f" <span style='color: {mutedToolTipColorHex()}'>" +
                        _("(search limited by {0})", ", ".join(limitations)))

        return message
