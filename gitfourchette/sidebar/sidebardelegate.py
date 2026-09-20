# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import enum

from gitfourchette.qt import *
from gitfourchette.sidebar.sidebarmodel import SidebarNode, SidebarModel, SidebarItem, SidebarLayout, SYMBOL_AHEAD, SYMBOL_BEHIND
from gitfourchette.toolbox import stockIcon, FittedText
from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine

if TYPE_CHECKING:
    from gitfourchette.sidebar.sidebar import Sidebar

PE_EXPANDED = QStyle.PrimitiveElement.PE_IndicatorArrowDown
PE_COLLAPSED = QStyle.PrimitiveElement.PE_IndicatorArrowRight

# These metrics are a good compromise for Breeze, macOS, and Fusion.
EXPAND_TRIANGLE_WIDTH = 6
PADDING = 4
EYE_WIDTH = 16
MENU_WIDTH = 16

# Source-list metrics (see ThemeColors.sidebarSourceList), in the proportions
# of a macOS source list: headers' text 30 px from the sidebar's edge (the
# repo's name 26), each level's rows 7 px further in, and the selection a 22 px
# pill that stays about 10 px clear of either edge.
SOURCE_LIST_INDENT = 7
SOURCE_LIST_MARGIN = 18
"Room left of the headers for their chevrons, besides the tree's own indentation."
SOURCE_LIST_TITLE_SHIFT = 4
"The repo's name has no chevron to clear: it starts this much left of the headers' text."
SOURCE_LIST_ICON_GAP = 4
SOURCE_LIST_CHEVRON_GAP = 21
"From the left of a chevron's 16 px box to the text or icon it expands."
PILL_INSET_LEFT = 8
PILL_INSET_RIGHT = 10
PILL_RADIUS = 6


class SidebarClickZone(enum.IntEnum):
    Invalid = 0
    Select = 1
    Expand = 2
    Hide = 3
    Menu = 4


class SidebarDelegate(QStyledItemDelegate):
    """
    Draws custom tree expand/collapse indicator arrows,
    and hide/show icons.
    """

    sidebar: Sidebar

    def __init__(self, parent: Sidebar):
        super().__init__(parent)
        self.sidebar = parent

    @staticmethod
    def unindentRect(item: SidebarItem, rect: QRect, indentation: int, sourceList: bool = False):
        if sourceList:
            # Rows keep the tree's indentation, past a margin for the headers'
            # chevrons, and end where the selection pill ends.
            left = SOURCE_LIST_MARGIN + SidebarLayout.SourceListIndentItems.get(item, 0) * indentation
            if item == SidebarItem.WorkdirHeader:
                left -= SOURCE_LIST_TITLE_SHIFT
            rect.adjust(left, 0, -PILL_INSET_RIGHT, 0)
            return rect
        if item not in SidebarLayout.UnindentItems:
            return
        unindentLevels = SidebarLayout.UnindentItems[item]
        unindentPixels = unindentLevels * indentation
        return rect.adjust(unindentPixels, 0, 0, 0)

    @staticmethod
    def pillRect(row: QRect, viewport: QRect) -> QRectF:
        """Where a source list draws the selection pill of a row, in viewport coordinates."""
        return QRectF(viewport.left() + PILL_INSET_LEFT, row.top() + 1,
                      viewport.width() - PILL_INSET_LEFT - PILL_INSET_RIGHT, row.height() - 2)

    @staticmethod
    def hasMenuButton(node: SidebarNode, sourceList: bool):
        """
        The repo's name is the one row that wears its menu in the open: a
        source list gives no hint that a row can be right-clicked, so the menu
        the header would pop up sits at the end of the row.
        """
        return sourceList and node.kind == SidebarItem.WorkdirHeader

    @staticmethod
    def menuRect(row: QRect) -> QRect:
        """
        Where the repo header draws its menu button, given the row's rect as
        Sidebar.visualRect hands it out (already unindented).
        """
        r = QRect(row)
        r.adjust(PADDING, 0, -PADDING, 0)
        r.setLeft(r.right() - MENU_WIDTH + 1)
        return r

    @staticmethod
    def getClickZone(node: SidebarNode, rect: QRect, x: int, sourceList: bool = False):
        if node.kind == SidebarItem.Spacer:
            return SidebarClickZone.Invalid
        elif (SidebarDelegate.hasMenuButton(node, sourceList)
              and x >= SidebarDelegate.menuRect(rect).left()):
            return SidebarClickZone.Menu
        elif node.mayHaveChildren() and x < rect.left():
            return SidebarClickZone.Expand
        elif node.canBeHidden() and x > rect.right() - EYE_WIDTH - PADDING:
            return SidebarClickZone.Hide
        else:
            return SidebarClickZone.Select

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        node = self.sidebar.filterIndexToNode(index)
        assert node.parent is not None, "can't paint root node"

        sidebarModel = self.sidebar.sidebarModel
        view = self.sidebar
        assert view is option.widget

        style: QStyle = view.style()
        sourceList = view.sourceList
        isActive = bool(option.state & QStyle.StateFlag.State_Active)
        isSelected = bool(option.state & QStyle.StateFlag.State_Selected)
        mouseOver = bool(option.state & QStyle.StateFlag.State_Enabled) and bool(option.state & QStyle.StateFlag.State_MouseOver)
        colorGroup = QPalette.ColorGroup.Active if isActive else QPalette.ColorGroup.Inactive

        makeRoomForMenu = SidebarDelegate.hasMenuButton(node, sourceList)

        isExplicitlyShown = False
        isExplicitlyHidden = False
        isImplicitlyHidden = False
        isHideAllButThisMode = sidebarModel.isHideAllButThisMode()
        makeRoomForEye = False
        if node.canBeHidden():
            isExplicitlyShown = sidebarModel.isExplicitlyShown(node)
            isExplicitlyHidden = sidebarModel.isExplicitlyHidden(node)
            isImplicitlyHidden = isExplicitlyHidden or sidebarModel.isImplicitlyHidden(node)
            makeRoomForEye = mouseOver or isExplicitlyShown or isExplicitlyHidden or isImplicitlyHidden

        painter.save()

        if node.kind == SidebarItem.Spacer and sourceList:
            # A hairline across the whole sidebar
            mouseOver = False
            option.state &= ~QStyle.StateFlag.State_MouseOver
            lineColor = option.palette.color(colorGroup, QPalette.ColorRole.WindowText)
            lineColor.setAlpha(38)
            middle = option.rect.top() + option.rect.height() // 2
            painter.fillRect(QRect(0, middle, view.viewport().width(), 1), lineColor)

        elif node.kind == SidebarItem.Spacer:
            mouseOver = False
            option.state &= ~QStyle.StateFlag.State_MouseOver

            r = QRect(option.rect)
            r.setLeft(0)
            middle = r.top() + int(r.height() / 2)

            tc1 = option.palette.color(colorGroup, QPalette.ColorRole.WindowText)
            tc2 = QColor(tc1)
            tc1.setAlpha(0)
            tc2.setAlpha(33)
            lineGradient = QLinearGradient(r.left() + PADDING, middle, r.right() - PADDING, middle)
            lineGradient.setColorAt(0, tc1)
            lineGradient.setColorAt(.2, tc2)
            lineGradient.setColorAt(1-.2, tc2)
            lineGradient.setColorAt(1, tc1)

            painter.save()
            painter.setPen(QPen(lineGradient, 1))
            painter.drawLine(r.left() + PADDING, middle, r.right() - PADDING, middle)
            painter.restore()

        # Unindent rect
        SidebarDelegate.unindentRect(node.kind, option.rect, view.indentation(), sourceList)

        # Set highlighted text color if this item is selected
        iconMode = QIcon.Mode.Normal
        if isSelected:
            penColor = option.palette.color(colorGroup, QPalette.ColorRole.HighlightedText)
            iconMode = QIcon.Mode.Selected if isActive else QIcon.Mode.SelectedInactive  # type: ignore[attr-defined]
        elif (not node.parent.parent and not sourceList
              and node.kind not in (SidebarItem.UncommittedChanges, SidebarItem.AllCommits)):
            penColor = option.palette.color(colorGroup, QPalette.ColorRole.WindowText)
            penColor.setAlphaF(.66)
        else:
            penColor = option.palette.color(colorGroup, QPalette.ColorRole.WindowText)

        if sourceList:
            # Selection and hover: a rounded pill inset from the edges of the
            # sidebar, whatever the row's depth. The theme's style sheet leaves
            # the row itself unfilled.
            if node.kind != SidebarItem.Spacer and (isSelected or mouseOver):
                if isSelected:
                    fill = option.palette.color(colorGroup, QPalette.ColorRole.Highlight)
                else:
                    fill = option.palette.color(colorGroup, QPalette.ColorRole.WindowText)
                    fill.setAlpha(16)
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(SidebarDelegate.pillRect(option.rect, view.viewport().rect()),
                                        PILL_RADIUS, PILL_RADIUS)
                painter.restore()

            # Chevron in the margin, pointing down when expanded
            if node.mayHaveChildren() and not node.wantForceExpand():
                chevron = "chevron-down" if view.isExpanded(index) else "chevron-right"
                r = QRect(0, 0, 16, 16)
                r.moveCenter(option.rect.center())
                r.moveLeft(option.rect.left() + PADDING - SOURCE_LIST_CHEVRON_GAP)
                stockIcon(chevron).paint(painter, r, mode=iconMode)

        else:
            # Draw expand/collapse triangle.
            if node.mayHaveChildren() and not node.wantForceExpand():
                opt2 = QStyleOptionViewItem(option)
                opt2.rect.adjust(-(EXPAND_TRIANGLE_WIDTH + PADDING), 0, 0, 0)  # args must be integers for pyqt5!
                opt2.rect.setWidth(EXPAND_TRIANGLE_WIDTH)

                # See QTreeView::drawBranches() in qtreeview.cpp for other interesting states
                opt2.state &= ~QStyle.StateFlag.State_MouseOver
                arrowPrimitive = PE_EXPANDED if view.isExpanded(index) else PE_COLLAPSED
                style.drawPrimitive(arrowPrimitive, opt2, painter, view)

            # Draw control background
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)

        # Adjust contents
        option.rect.adjust(PADDING, 0, -PADDING, 0)

        painter.setPen(penColor)

        # Draw decoration icon
        iconWidth = option.decorationSize.width()
        iconKey = index.data(SidebarModel.Role.IconKey)
        if iconKey:
            if sourceList and iconKey == "git-folder" and view.isExpanded(index):
                iconKey = "git-folder-open"
            r = QRect(option.rect)
            r.setWidth(iconWidth)
            icon = stockIcon(iconKey)
            icon.paint(painter, r, option.decorationAlignment, mode=iconMode)
            iconGap = SOURCE_LIST_ICON_GAP if sourceList else PADDING*150//100
            option.rect.adjust(r.width() + iconGap, 0, 0, 0)

        # Prepare text
        textRect = QRect(option.rect)
        if makeRoomForEye:
            textRect.adjust(0, 0, -EYE_WIDTH, 0)
        if makeRoomForMenu:
            textRect.adjust(0, 0, -(MENU_WIDTH + PADDING), 0)

        font: QFont = index.data(Qt.ItemDataRole.FontRole) or option.font
        baseFontSize = font.pointSizeF()

        # Draw ahead/behind/missing upstream indicators
        missingUpstream = index.data(SidebarModel.Role.MissingUpstream)
        aheadBehind = index.data(SidebarModel.Role.AheadBehind)
        if makeRoomForEye:
            # No upstream indicators
            pass

        elif missingUpstream:
            r = QRect(option.rect)
            r.setLeft(textRect.right() - EYE_WIDTH)
            unpluggedIcon = stockIcon("git-upstream-missing")
            unpluggedIcon.paint(painter, r, mode=iconMode)
            # Clip rect
            textRect.setRight(r.left())

        elif aheadBehind:
            a, b = aheadBehind

            # Set a smaller font
            font.setPointSizeF(baseFontSize * (.67 if a and b else .75))
            painter.setFont(font)
            metrics = painter.fontMetrics()

            textA = f" {a} {SYMBOL_AHEAD}" if a else ""
            textB = f" {b} {SYMBOL_BEHIND}" if b else ""
            advanceA = metrics.horizontalAdvance(textA) if a else 0
            advanceB = metrics.horizontalAdvance(textB) if b else 0

            AF = Qt.AlignmentFlag
            if not isSelected:
                painter.setPen(RecolorSvgIconEngine.IconColors.mainColor)
            painter.drawText(textRect, AF.AlignRight | (AF.AlignTop if b else AF.AlignVCenter) , textA)
            painter.drawText(textRect, AF.AlignRight | (AF.AlignBottom if a else AF.AlignVCenter), textB)

            # Restore font size
            font.setPointSizeF(baseFontSize)
            painter.setPen(penColor)

            # Clip rect
            textRect.setRight(textRect.right() - max(advanceA, advanceB))

        # Draw text
        painter.setFont(font)
        fullText = index.data(Qt.ItemDataRole.DisplayRole)
        isCannedString = node.kind <= SidebarItem.SubmodulesHeader
        if not isCannedString:
            FittedText.draw(painter, textRect, option.displayAlignment, fullText, option.textElideMode)
        else:
            text = painter.fontMetrics().elidedText(fullText, Qt.TextElideMode.ElideMiddle, textRect.width())
            painter.drawText(textRect, option.displayAlignment, text)

        # Draw eye
        if makeRoomForEye:
            r = QRect(option.rect)
            r.setLeft(textRect.right())
            r.setWidth(EYE_WIDTH)
            if isExplicitlyShown or mouseOver and isHideAllButThisMode:
                eyeIconName = "view-exclusive"
            elif isExplicitlyHidden or (isImplicitlyHidden and isHideAllButThisMode):
                eyeIconName = "view-hidden"
            elif isImplicitlyHidden:
                eyeIconName = "view-hidden-indirect"
            else:
                eyeIconName = "view-visible"
            unpluggedIcon = stockIcon(eyeIconName)
            unpluggedIcon.paint(painter, r, mode=iconMode)

        # Draw the repo header's menu button
        if makeRoomForMenu:
            r = QRect(option.rect)
            r.setLeft(option.rect.right() - MENU_WIDTH + 1)
            stockIcon("more-circle").paint(painter, r, mode=iconMode)

        painter.restore()
