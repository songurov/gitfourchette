# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import math
import traceback
from contextlib import suppress
from dataclasses import dataclass

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.avatars import AVATAR_SIZE, AVATAR_SPACING, paintAvatar
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow, CommitToolTipZone
from gitfourchette.graphview.commitinfosearch import CommitInfoSearch
from gitfourchette.graphview.graphpaint import graphColumnWidth, paintGraphFrame
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, UC_FAKEREF, RepoModel, GpgStatus
from gitfourchette.settings import GraphRowLayout
from gitfourchette.sidebar.sidebarmodel import SYMBOL_AHEAD
from gitfourchette.toolbox import *


@dataclass
class RefBox:
    prefix: str
    icon: str = ""
    color: QColor = None
    darkColor: QColor = None
    """Foreground on a dark background. Brightening the light-theme color
    algorithmically washes saturated hues out, so each one is picked by hand."""
    keepPrefix: bool = False
    iconWidth: int = 16

    def penColor(self, dark: bool, fallback: QColor) -> QColor:
        if not self.color:
            return fallback
        if dark:
            return self.darkColor or self.color.lighter(300)
        return self.color


REFBOX_BG_ALPHA = (0.08, 0.20)
"""How much of the refbox color tints its background, light and dark."""


REFBOXES = [
    RefBox(RefPrefix.REMOTES, "git-remote", QColor("#0F7D8C"), QColor("#5FD3E3")),
    RefBox(RefPrefix.TAGS, "git-tag", QColor("#9A6B00"), QColor("#F2C14E")),
    RefBox(RefPrefix.HEADS, "git-branch", QColor("#2264B8"), QColor("#7FB4FF")),

    # detached HEAD as returned by Repo.map_commits_to_refs
    RefBox("HEAD", "git-head-detached", QColor("#B3382C"), QColor("#FF8C7A"), keepPrefix=True),

    # Working Directory
    RefBox(UC_FAKEREF, "git-workdir", QColor("#6B7280"), QColor("#A8AEB8")),

    # Mounted
    RefBox("FAKEREF_FUSEMOUNT", "git-mount", QColor("#6B7280"), QColor("#A8AEB8")),

    # Commit comparison
    RefBox("FAKEREF_COMPAREA", "compare-a", QColor(Qt.GlobalColor.red), iconWidth=48),
    RefBox("FAKEREF_COMPAREB", "compare-b", QColor(Qt.GlobalColor.blue), iconWidth=48),

    # Fallback
    RefBox("", "hint", QColor(Qt.GlobalColor.gray), keepPrefix=True)
]


ELISION = " […]"
ELISION_LENGTH = len(ELISION)


MAX_AUTHOR_CHARS = {
    AuthorDisplayStyle.Initials: 7,
    AuthorDisplayStyle.FullName: 20,
    AuthorDisplayStyle.FullEmail: 24,
}


XMARGIN = 4
XSPACING = 6

MIN_GRAPH_COLUMNS = 3
"""Lane columns reserved for the graph before any row is painted."""

MAX_GRAPH_COLUMNS = 16
"""Upper bound on the reserved graph column. Past this width, a busy graph
is clipped instead of pushing commit messages off the screen."""

NARROW_WIDTH = (500, 750)

AHEAD_SPACING = 4
"""Room between a branch's name and its count of commits to push."""


class CommitLogDelegate(QStyledItemDelegate):
    requestSignatureVerification = Signal(Oid)

    def __init__(
            self,
            repoModel: RepoModel,
            infoSearch: CommitInfoSearch | None = None,
            parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.repoModel = repoModel
        self.infoSearch = infoSearch

        self.mustRefreshMetrics = True
        self.hashCharWidth = 0
        self.dateMaxWidth = 0
        self.authorMaxWidth = 0
        self.hashColumnWidth = 0
        self.graphColumns = MIN_GRAPH_COLUMNS
        self.activeCommitFont = QFont()
        self.uncommittedFont = QFont()
        self.refboxFont = QFont()
        self.homeRefboxFont = QFont()

        self.mounts = GFApplication.instance().mountManager

        self._transientToolTipZones: list[CommitToolTipZone] | None = None

    def prepareForDeletion(self):
        del self.repoModel
        del self.infoSearch
        del self.mounts

    def newToolTipZone(self, zone: CommitToolTipZone):
        if self._transientToolTipZones is None:
            self._transientToolTipZones = []
        self._transientToolTipZones.append(zone)

    # --------------------------------------------------------------------------
    # Metrics

    def invalidateMetrics(self):
        self.mustRefreshMetrics = True
        self.graphColumns = MIN_GRAPH_COLUMNS

    def refreshMetrics(self, option: QStyleOptionViewItem):
        if not self.mustRefreshMetrics:
            return

        self.mustRefreshMetrics = False

        self.hashCharWidth = max(option.fontMetrics.horizontalAdvance(c) for c in "0123456789abcdef")

        self.activeCommitFont = QFont(option.font)
        self.activeCommitFont.setBold(True)

        self.uncommittedFont = QFont(option.font)
        self.uncommittedFont.setItalic(True)

        self.refboxFont = QFont(option.font)

        self.homeRefboxFont = QFont(self.refboxFont)
        self.homeRefboxFont.setWeight(QFont.Weight.Bold)

        wideDate = QDateTime.fromString("2999-12-25T23:59:59.999", Qt.DateFormat.ISODate)
        dateText = option.locale.toString(wideDate, settings.prefs.shortTimeFormat)
        if settings.prefs.authorDiffAsterisk:
            dateText += "*"
        self.dateMaxWidth = QFontMetrics(self.activeCommitFont).horizontalAdvance(dateText + " ")
        self.dateMaxWidth = int(self.dateMaxWidth)  # make sure it's an int for pyqt5 compat

        self.authorMaxWidth = self.hashCharWidth * MAX_AUTHOR_CHARS.get(settings.prefs.authorDisplayStyle, 16)
        if settings.prefs.showAvatars:
            self.authorMaxWidth += AVATAR_SIZE + AVATAR_SPACING

        self.hashColumnWidth = self.hashCharWidth * settings.prefs.shortHashChars + XSPACING

    # --------------------------------------------------------------------------
    # Qt callbacks

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        mult = settings.prefs.graphRowHeight
        r = super().sizeHint(option, index)
        r.setHeight(option.fontMetrics.height() * mult // 100)
        return r

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, fillBackground=True):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            assert self._transientToolTipZones is None
            self._paint(painter, option, index, fillBackground)
        except Exception as exc:  # pragma: no cover
            painter.restore()
            painter.save()
            self._paintError(painter, option, index, exc)
        finally:
            self._transientToolTipZones = None
        painter.restore()

    # --------------------------------------------------------------------------
    # Paint implementation

    def _paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, fillBackground: bool):
        assert index.isValid()

        isActive = bool(option.state & QStyle.StateFlag.State_Active)
        isSelected = bool(option.state & QStyle.StateFlag.State_Selected)
        colorGroup = QPalette.ColorGroup.Active if isActive else QPalette.ColorGroup.Inactive
        palette: QPalette = option.palette

        # Draw default background
        if fillBackground:
            style = option.widget.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)

        if isSelected:
            painter.setPen(palette.color(colorGroup, QPalette.ColorRole.HighlightedText))

        # Get metrics of '0' before setting a custom font,
        # so that alignments are consistent in all commits regardless of bold or italic.
        self.refreshMetrics(option)

        # Get the commit
        # special: SpecialRow = index.data(CommitLogModel.Role.SpecialRow)
        oid = index.data(CommitLogModel.Role.Oid)
        if oid is not None and oid != UC_FAKEID:
            commit = self.repoModel.repo.peel_commit(oid)
        else:
            commit = None

        # Set up rect
        rect = QRect(option.rect)
        rect.setLeft(rect.left() + XMARGIN)
        rect.setRight(rect.right() - XMARGIN)
        fullWidth = rect.width()

        # Compute column bounds
        authorWidth = self.authorMaxWidth
        dateWidth = self.dateMaxWidth
        hashWidth = self.hashColumnWidth if self.hashOnTheRight() else 0
        if fullWidth < NARROW_WIDTH[0] or not oid:
            authorWidth = 0
            dateWidth = 0
            hashWidth = 0
        elif fullWidth <= NARROW_WIDTH[1]:
            authorWidth = int(lerp(authorWidth/2, authorWidth, rect.width(), NARROW_WIDTH[0], NARROW_WIDTH[1]))
            hashWidth = 0  # the hash is the first thing to go in a cramped window
        leftBoundDate = rect.right() - dateWidth
        leftBoundHash = leftBoundDate - hashWidth
        leftBoundName = leftBoundHash - authorWidth
        rightBound = rect.right()
        tabBound = leftBoundName

        # Reserve rightmost column
        rect.setRight(leftBoundName - XMARGIN)

        # Set font
        if self.isBold(oid):
            painter.setFont(self.activeCommitFont)
        elif not oid:
            painter.setFont(self.uncommittedFont)

        # ...Left-to-right zones...

        # Hash
        if not self.hashOnTheRight():
            painter.save()
            if not isSelected:  # use muted color for hash if not selected
                painter.setPen(palette.color(colorGroup, QPalette.ColorRole.PlaceholderText))
            self._paintHash(painter, rect, oid)
            painter.restore()

        # Private
        self.paintPrivate(painter, option, index, rect, oid)

        # Use muted color from here on out for foreign commits (unless selected)
        if not isSelected and self.isDim(oid):
            painter.setPen(Qt.GlobalColor.gray)

        # Message
        if commit is not None:
            self._paintCommitMessage(painter, rect, commit)
        else:
            special: SpecialRow = index.data(CommitLogModel.Role.SpecialRow)
            self._paintSpecialMessage(painter, rect, special)

        # Pathspec match
        if (oid is not None
                and self.repoModel.commitPathspecFilter.isReady()
                and oid in self.repoModel.commitPathspecFilter.matchingIds):
            self._paintRefspecMatch(painter, rect, fullWidth // 8)

        # ...Jump to rightmost column...

        # Author
        if authorWidth != 0 and commit:
            rect.setLeft(tabBound)
            rect.setRight(leftBoundHash - XMARGIN)
            self._paintAuthor(painter, rect, commit)

        # Hash
        if hashWidth != 0 and commit:
            rect.setLeft(leftBoundHash)
            rect.setRight(leftBoundDate - XMARGIN)
            painter.save()
            if not isSelected:
                painter.setPen(palette.color(colorGroup, QPalette.ColorRole.PlaceholderText))
            self._paintHash(painter, rect, oid)
            painter.restore()

        # Date
        if dateWidth != 0 and commit:
            rect.setLeft(leftBoundDate)
            rect.setRight(rightBound)
            self._paintDate(painter, rect, commit)

        # Set author/date tooltip zone
        if authorWidth != 0 or dateWidth != 0:
            self.newToolTipZone(CommitToolTipZone(leftBoundName, rightBound, "author"))

        # Tooltip metrics
        # Block model signals to update it - otherwise QComboBox will constantly redraw itself
        model = index.model()
        with QSignalBlockerContext(model):
            model.setData(index, leftBoundName if authorWidth != 0 else -1, CommitLogModel.Role.AuthorColumnX)
            model.setData(index, self._transientToolTipZones, CommitLogModel.Role.ToolTipZones)

        # Flush temp mouse zones
        self._transientToolTipZones = None

    # --------------------------------------------------------------------------
    # Paint blocks

    def _paintHash(self, painter: QPainter, rect: QRect, oid: Oid | None):
        hcw = self.hashCharWidth
        hashText = shortHash(oid) if oid else ("·" * settings.prefs.shortHashChars)

        charRect = QRect(rect)
        charRect.setWidth(hcw)

        for hashChar in hashText:
            painter.drawText(charRect, Qt.AlignmentFlag.AlignCenter, hashChar)
            charRect.translate(hcw, 0)

        # Highlight searched hash
        if (self.infoSearch is not None
                and self.infoSearch.likelyHash
                and (term := self.infoSearch.term())
                and oid is not None
                and str(oid).startswith(term)):
            x1 = 0
            x2 = min(len(hashText), len(term)) * hcw
            SearchBar.highlightNeedle(painter, rect, hashText, 0, len(term), x1, x2)

        rect.setLeft(charRect.right())

    def _paintSpecialMessage(self, painter: QPainter, rect: QRect, special: SpecialRow):
        if special == SpecialRow.UncommittedChanges:
            text = self.uncommittedChangesMessage()
        elif special == SpecialRow.EndOfShallowHistory:
            text = _("Shallow clone – End of commit history")
        elif special == SpecialRow.TruncatedHistory:
            if self.repoModel.hiddenCommits and self.repoModel.hiddenRefs:
                text = _("History truncated to {0} commits (including hidden branches)")
            else:
                text = _("History truncated to {0} commits")
            text = text.format(QLocale().toString(self.repoModel.numRealCommits))
        else:
            raise NotImplementedError(f"*** Unsupported special row {special}")

        text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, text)

    def _paintCommitMessage(self, painter: QPainter, rect: QRect, commit: Commit):
        fullText = commit.message
        text, _contd = messageSummary(fullText, ELISION)

        text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, text)

        if len(text) == 0 or text.endswith(("…", ELISION)):
            self.newToolTipZone(CommitToolTipZone(rect.left(), rect.right(), "message"))

        # Highlight search term
        if (text
                and self.infoSearch is not None
                and (searchTerm := self.infoSearch.term())
                and searchTerm in fullText.lower()):
            needlePos = text.lower().find(searchTerm)
            if needlePos < 0:
                needlePos = len(text) - ELISION_LENGTH
                needleLen = ELISION_LENGTH
            else:
                needleLen = len(searchTerm)
            SearchBar.highlightNeedle(painter, rect, text, needlePos, needleLen)

    def _paintRefspecMatch(self, painter: QPainter, rect: QRect, maxWidth: int):
        metrics = painter.fontMetrics()
        bleed, iconWidth = 8, 16

        needle = self.repoModel.commitPathspecFilter.needle
        needle = metrics.elidedText(needle, Qt.TextElideMode.ElideRight, maxWidth)

        needleRect = QRect(rect)
        needleRect.setRight(rect.right() - bleed)
        needleRect.setLeft(needleRect.right() - metrics.horizontalAdvance(needle))

        self.newToolTipZone(CommitToolTipZone(needleRect.left(), needleRect.right(), "pathspec"))

        SearchBar.highlightNeedle(painter, needleRect, needle, lBleed=bleed + iconWidth, rBleed=bleed)

        needleRect.adjust(-iconWidth, 0, 0, 0)
        needleRect.setWidth(iconWidth)
        stockIcon("magnifying-glass", "gray=black").paint(painter, needleRect)

    def _paintAuthor(self, painter: QPainter, rect: QRect, commit: Commit):
        assert commit
        author = commit.author
        authorText = abbreviatePerson(author, settings.prefs.authorDisplayStyle)

        if settings.prefs.authorDiffAsterisk and author.email != commit.committer.email:
            authorText += "*"

        # Draw the author's chip, so a face-less history still reads at a glance
        if settings.prefs.showAvatars:
            size = min(AVATAR_SIZE, rect.height())
            chipRect = QRect(rect.left(), rect.top() + (rect.height() - size) // 2, size, size)
            picture = None
            if settings.prefs.downloadAvatars:
                picture = GFApplication.instance().avatarCache.pixmapFor(author)
            paintAvatar(painter, chipRect, author, picture)
            rect.setLeft(chipRect.right() + AVATAR_SPACING)

        gpgStatus, _gpgKeyInfo = self.repoModel.getCachedGpgStatus(commit)

        if gpgStatus == GpgStatus.Pending and settings.prefs.verifyGpgOnTheFly:
            self.requestSignatureVerification.emit(commit.id)

        # Draw seal for signed commits
        if gpgStatus > GpgStatus.Pending or (settings.prefs.verifyGpgOnTheFly and gpgStatus >= GpgStatus.Pending):
            sealRect = QRect(rect)
            sealRect.setRight(sealRect.left() + 16)
            icon = stockIcon(gpgStatus.iconName())
            icon.paint(painter, sealRect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            rect.setLeft(sealRect.right() + 4)

        FittedText.draw(painter, rect, Qt.AlignmentFlag.AlignVCenter, authorText, minStretch=QFont.Stretch.ExtraCondensed)

        # Highlight searched author
        if self.infoSearch is not None and (searchTerm := self.infoSearch.term()):
            needlePos = authorText.lower().find(searchTerm)
            if needlePos >= 0:
                SearchBar.highlightNeedle(painter, rect, authorText, needlePos, len(searchTerm))

    def _paintDate(self, painter: QPainter, rect: QRect, commit: Commit):
        author = commit.author
        dateText = signatureDateFormat(author, settings.prefs.shortTimeFormat, localTime=True)

        if settings.prefs.authorDiffAsterisk and author.time != commit.committer.time:
            dateText += "*"

        displayText = painter.fontMetrics().elidedText(dateText, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, displayText)

    # --------------------------------------------------------------------------
    # Refbox painting

    def _paintRefboxes(self, painter: QPainter, rect: QRect, refs: list[str]):
        repoModel = self.repoModel
        homeBranch = RefPrefix.HEADS + repoModel.homeBranch
        xMax = painter.clipBoundingRect().right()

        # Group refs in clusters (branches with same upstream)
        clusters: dict[str, list[str]] = {}
        nonLooseRefs = set()
        for refName in refs:
            # Skip refboxes for hidden refs
            if refName in repoModel.hiddenRefs:
                continue

            # Look for local branches
            if not refName.startswith(RefPrefix.HEADS):
                continue
            localName = refName.removeprefix(RefPrefix.HEADS)

            # Find the upstream for this local branch
            try:
                upstreamShorthand = repoModel.upstreams[localName]
                assert not upstreamShorthand.startswith(RefPrefix.REMOTES)
                upstreamRef = RefPrefix.REMOTES + upstreamShorthand
            except KeyError:
                continue

            # Don't create a cluster if the upstream isn't on the same row
            if upstreamRef not in refs:
                continue

            # Don't create a cluster if the upstream is hidden
            if upstreamRef in repoModel.hiddenRefs:
                continue

            # Append to the cluster
            try:
                clusters[upstreamRef].append(refName)
            except KeyError:
                clusters[upstreamRef] = [refName]

            nonLooseRefs.add(upstreamRef)
            nonLooseRefs.add(refName)

        # Draw clusters first
        for upstreamRef, localRefList in clusters.items():
            # See if we can omit the name of the remote branch
            if repoModel.singleRemote and len(localRefList) == 1:
                assert upstreamRef.startswith(RefPrefix.REMOTES)
                upstreamShorthand = upstreamRef.removeprefix(RefPrefix.REMOTES)
                _remoteName, remoteBranchName = split_remote_branch_shorthand(upstreamShorthand)
                _localBranchPrefix, localBranchName = RefPrefix.split(localRefList[0])
                omitRemoteName = remoteBranchName == localBranchName
            else:
                omitRemoteName = False

            # Draw local branches
            for i, localRef in enumerate(localRefList):
                self._paintRefbox(painter, rect, localRef, clipLeft=i != 0, clipRight=True, isHome=localRef == homeBranch)

            # Draw upstream at end of cluster
            self._paintRefbox(painter, rect, upstreamRef, clipLeft=True, forceOmitName=omitRemoteName)

            if rect.left() >= xMax:
                return

        # Draw loose refs
        for refName in refs:
            # Skip refboxes for hidden refs (except tags and special refs)
            if (refName in repoModel.hiddenRefs
                    and refName.startswith("refs/")
                    and not refName.startswith(RefPrefix.TAGS)):
                continue

            # Skip clustered refs we've drawn above
            if refName in nonLooseRefs:
                continue

            self._paintRefbox(painter, rect, refName, isHome=refName == homeBranch)

            if rect.left() >= xMax:
                return

    def _paintRefbox(
            self,
            painter: QPainter,
            rect: QRect,
            refName: str,
            isHome: bool = False,
            clipLeft: bool = False,
            clipRight: bool = False,
            forceOmitName: bool = False,
            forceToolTip: str | None = "",
    ):
        if refName == 'HEAD' and not self.repoModel.headIsDetached:
            return

        refboxDef = next(d for d in REFBOXES if refName.startswith(d.prefix))

        penColor = painter.pen().color()
        dark = penColor.lightnessF() > .5

        if forceOmitName:
            text = ""
        elif not refboxDef.keepPrefix:
            text = refName.removeprefix(refboxDef.prefix)
        else:
            text = refName
        color = refboxDef.penColor(dark, penColor)
        bgColor = QColor(color)  # modify copy
        bgColor.setAlphaF(REFBOX_BG_ALPHA[dark])
        iconName = refboxDef.icon

        # Omit remote name if there's a single remote
        if refboxDef.prefix == RefPrefix.REMOTES and self.repoModel.singleRemote:
            text = text.split('/', 1)[-1]

        # A local branch with commits to push says how many, like the sidebar
        aheadText = ""
        aheadToolTip = ""
        if refboxDef.prefix == RefPrefix.HEADS:
            ahead, pushTarget = self.repoModel.countUnpushed(refName.removeprefix(RefPrefix.HEADS))
            if ahead > 0:
                aheadText = f"{SYMBOL_AHEAD}{ahead}"
                if pushTarget:
                    aheadToolTip = _n("{n} commit not pushed to {0}", "{n} commits not pushed to {0}", ahead, pushTarget)
                else:
                    aheadToolTip = _n("{n} commit not pushed to any remote", "{n} commits not pushed to any remote", ahead)

        if isHome:
            font = self.homeRefboxFont
            iconName = "git-head"
        elif refName == 'HEAD' and self.repoModel.headIsDetached:
            text = _("Detached HEAD")
            font = self.homeRefboxFont
        else:
            font = self.refboxFont

        painter.setFont(font)
        painter.setPen(color)

        rrRadius = 4  # Rounded Rectangle radius
        lPadding = 4  # Left padding
        rPadding = 4  # Right padding
        vMargin = max(0, math.ceil((rect.height() - 16) / 4))  # Vertical margin

        if iconName:
            lPadding -= 1

        # The count is never elided: the name gives way first
        aheadWidth = QFontMetrics(font).horizontalAdvance(aheadText) if aheadText else 0

        # Determine max width
        maxWidth = int(settings.prefs.refBoxMaxWidth)
        remainingWidth = rect.width()
        if remainingWidth < 150:  # Super cramped
            maxWidth = 0  # Draw icon only
        maxWidth = min(remainingWidth, maxWidth)
        if aheadText:
            # The count takes room from the row, not from the name's share
            maxWidth = max(0, min(maxWidth, remainingWidth - aheadWidth - AHEAD_SPACING))

        # Text-only refbox: show text regardless of the user's preference
        if not iconName and text:
            maxWidth = max(maxWidth, remainingWidth)

        # Draw text.
        # No condensing here: squeezed letterforms next to normal text read as a
        # rendering glitch. A ref name that doesn't fit gets elided instead.
        if text and maxWidth != 0:
            text, fittedFont, textWidth = FittedText.fit(
                font, maxWidth, text, Qt.TextElideMode.ElideMiddle, limit=QFont.Stretch.Unstretched)
        else:
            textWidth = -rPadding  # Negate rPadding

        contentWidth = textWidth
        if aheadText:
            contentWidth = max(0, textWidth) + (AHEAD_SPACING if textWidth > 0 else 0) + aheadWidth

        lClip = 0
        rClip = 0
        if clipLeft:
            lPadding = 2 * lPadding
            lClip = rrRadius
        if clipRight:
            rPadding = 2 * rPadding + 2
            rClip = rrRadius

        if iconName:
            iconRect = QRect(rect)
            iconRect.adjust(lPadding, vMargin, 0, -vMargin)
            iconHeight = min(16, iconRect.height())
            iconWidth = round(refboxDef.iconWidth * iconHeight / 16)
            iconRect.setWidth(iconWidth)
            iconPadding = 2
        else:
            iconWidth = 0
            iconPadding = 0

        boxRect = QRect(rect)
        boxRect.setWidth(lPadding + iconWidth + iconPadding + contentWidth + rPadding)

        frameRect = QRectF(boxRect)
        frameRect.adjust(0, vMargin, 0, -vMargin)
        frameRect.adjust(-lClip, 0, 0, 0)
        clipBox = frameRect.adjusted(lClip, 0, -rClip+1, 0)

        if lClip or rClip:
            painter.save()
            painter.setClipRect(clipBox)

        framePath = QPainterPath()
        framePath.addRoundedRect(frameRect.adjusted(.5, .5, .5, -.5),  # Snap to pixel grid
                                 rrRadius, rrRadius)

        painter.drawPath(framePath)
        painter.fillPath(framePath, bgColor)

        if iconName:
            icon = stockIcon(iconName, f"gray={color.name()}")
            icon.paint(painter, iconRect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        textRect = QRect(boxRect)
        textRect.adjust(0, 0, -rPadding, 0)

        if aheadText:
            painter.drawText(textRect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, aheadText)
            textRect.adjust(0, 0, -(aheadWidth + AHEAD_SPACING), 0)

        if text and textWidth > 0:
            painter.setFont(fittedFont)
            painter.drawText(textRect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
            painter.setFont(font)

        # Reset clip rect
        if lClip or rClip:
            painter.restore()

        # Draw divider line
        if lClip:
            x  =  .5 + clipBox.left()
            yt =  .5 + frameRect.top()
            yb = -.5 + frameRect.bottom()
            ym =  .5 + int((yt+yb)/2)

            if rClip:
                # Simple divider
                divider = [QLineF(x, yt, x, yb)]
            else:
                # "Equals" sign punches through divider
                divider = [QLineF(x, yt, x, ym-3),
                           QLineF(x, ym+3, x, yb),
                           QLineF(x-2, ym-1, x+2, ym-1),
                           QLineF(x-2, ym+1, x+2, ym+1)]

            if PYSIDE6:
                painter.drawLines(divider)  # type: ignore[call-overload] # skip PySide6 for type checking
            else:
                painter.drawLines(*divider)

        # Append tooltip
        if forceToolTip is not None:
            toolTipText = forceToolTip or refName
            if aheadToolTip:
                toolTipText += "\n" + aheadToolTip
            zone = CommitToolTipZone(rect.left(), boxRect.right(), "ref", toolTipText)
            self.newToolTipZone(zone)

        # Advance caller rectangle
        rect.setLeft(round(clipBox.right()) + (6 if not rClip else 0))

    # --------------------------------------------------------------------------
    # Error painting

    def _paintError(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, exc: Exception):  # pragma: no cover
        """Last-resort row drawing routine used if _paint raises an exception."""

        # We want this to fail in unit tests.
        if APP_TESTMODE:
            raise exc

        text = "?" * 7
        with suppress(Exception):
            oid = index.data(CommitLogModel.Role.Oid)
            text = str(oid)[:7]
        with suppress(Exception):
            details = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
            text += " - " + shortenTracebackPath(details[-2].splitlines(False)[0]) + ":: " + repr(exc)

        bg, fg = QColor(Qt.GlobalColor.white), QColor(Qt.GlobalColor.red)
        if option.state & QStyle.StateFlag.State_Selected:
            bg, fg = fg, bg

        painter.fillRect(option.rect, bg)
        painter.setPen(fg)
        painter.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.SmallestReadableFont))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignVCenter, text)

    # --------------------------------------------------------------------------
    # To override

    def isBold(self, oid: Oid) -> bool:
        """Can be overridden"""
        return oid != NULL_OID and oid == self.repoModel.headCommitId

    def isDim(self, oid: Oid):
        """Can be overridden"""
        return oid != NULL_OID and oid in self.repoModel.foreignCommits

    def isUnpushed(self, oid: Oid | None) -> bool:
        """Can be overridden"""
        return oid is not None and oid in self.repoModel.unpushedCommits

    def uncommittedChangesMessage(self) -> str:
        """Can be overridden"""
        summaryText = _("Working Directory") + " "
        # Append change count if available
        numChanges = self.repoModel.numUncommittedChanges
        if numChanges == 0:
            summaryText += _("(Clean)")
        elif numChanges > 0:
            summaryText += _n("({n} change)", "({n} changes)", numChanges)
        # Append draft message if any
        draftMessage = self.repoModel.prefs.draftCommitMessage
        if draftMessage:
            draftMessage = messageSummary(draftMessage)[0].strip()
            draftIntro = _("Commit draft:")
            summaryText += f" – {draftIntro} {tquo(draftMessage)}"
        return summaryText

    def paintPrivate(
            self,
            painter: QPainter,
            option: QStyleOptionViewItem,
            index: QModelIndex,
            rect: QRect,
            oid: Oid | None,
    ):
        """
        Draw widget-specific information before the commit message.
        By default, draws the graph and refboxes. Can be overridden.
        """

        # ------ Graph
        if self.hashOnTheRight():
            # Fixed-width column, so the messages don't drift with the graph
            self._paintGraphColumn(painter, rect, oid)
        elif self.wantGraph(oid):
            graphRect = QRect(rect)
            hollow = self.isUnpushed(oid)
            paintGraphFrame(painter, graphRect, oid, self.repoModel.graph, self.repoModel.hiddenCommits, hollow)
            if hollow:
                self.newToolTipZone(CommitToolTipZone(rect.left(), graphRect.right(), "unpushed"))
            rect.setLeft(graphRect.right())

        # ------ Refboxes
        painter.save()
        painter.setClipRect(rect)
        self._paintRefIndicators(painter, rect, index, oid)
        painter.restore()

    def wantGraph(self, oid: Oid | None) -> bool:
        return oid is not None and not self.repoModel.commitPathspecFilter.wantFilter()

    def hashOnTheRight(self) -> bool:
        """True if the row opens with the graph and the hash sits next to the
        author, instead of the classic layout that opens with the hash."""
        return settings.prefs.graphRowLayout == GraphRowLayout.GraphFirst

    def _paintRefIndicators(self, painter: QPainter, rect: QRect, index: QModelIndex, oid: Oid | None):
        # ------ A/B icon
        abSide = index.data(CommitLogModel.Role.ComparisonSide)
        if abSide:
            tt = _("{0} side in the current comparison between two commits", tquo(abSide))
            self._paintRefbox(painter, rect, f"FAKEREF_COMPARE{abSide}", forceToolTip=tt)

        # ------ Mount icon
        if self.mounts.isMounted(oid):
            tt = _("This commit is currently mounted as a folder.")
            self._paintRefbox(painter, rect, "FAKEREF_FUSEMOUNT", forceToolTip=tt)

        # ------ Actual refs
        refsHere = self.repoModel.refsAt.get(oid, None)
        if refsHere:
            self._paintRefboxes(painter, rect, refsHere)

    def _paintGraphColumn(self, painter: QPainter, rect: QRect, oid: Oid | None):
        """
        Draw the graph in a column whose width doesn't depend on the row, so
        that every commit message starts at the same x.
        """

        width = min(graphColumnWidth(self.graphColumns) + XSPACING, rect.width() // 2)

        if self.wantGraph(oid):
            graphRect = QRect(rect)
            graphRect.setWidth(width)
            hollow = self.isUnpushed(oid)
            columns = paintGraphFrame(painter, graphRect, oid, self.repoModel.graph, self.repoModel.hiddenCommits, hollow)
            self.reserveGraphColumns(columns)
            if hollow:
                self.newToolTipZone(CommitToolTipZone(rect.left(), rect.left() + width, "unpushed"))

        rect.setLeft(rect.left() + width)

    def reserveGraphColumns(self, columns: int):
        """
        Widen the reserved graph column if this row needs more lanes than we've
        seen so far, and repaint so that the rows already drawn line up with it.
        The column only ever grows (up to MAX_GRAPH_COLUMNS), so this settles
        after a couple of passes instead of ping-ponging.
        """

        columns = min(columns, MAX_GRAPH_COLUMNS)
        if columns <= self.graphColumns:
            return

        self.graphColumns = columns

        view = self.parent()
        if isinstance(view, QWidget):
            view.update()

