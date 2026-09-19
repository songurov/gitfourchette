# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import weakref

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon
from gitfourchette.toolbox.qtutils import CallbackAccumulator, reevaluateStyleSheet


class QTabBar2Badge(QWidget):
    """What a tab has outstanding, at the right end of a pill tab (see QTabBar2.pillMode)."""

    Size = 16

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("QTW2Badge")
        self.setFixedSize(QTabBar2Badge.Size, QTabBar2Badge.Size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.iconKey = ""

    def setIconKey(self, iconKey: str):
        if iconKey != self.iconKey:
            self.iconKey = iconKey
            self.update()

    def paintEvent(self, event: QPaintEvent):
        # Look the icon up at paint time, so it's always drawn in the current theme's colors
        if self.iconKey:
            painter = QPainter(self)
            stockIcon(self.iconKey).paint(painter, self.rect())


class QTabBar2CloseButton(QToolButton):
    """Closes a pill tab, from its left end, while the pointer is over the tab (see QTabBar2.pillMode)."""

    def __init__(self, parent: "QTabBar2"):
        super().__init__(parent)
        self.setObjectName("QTW2CloseButton")
        self.setFixedSize(QTabBar2Badge.Size, QTabBar2Badge.Size)
        self.setIconSize(QSize(QTabBar2Badge.Size, QTabBar2Badge.Size))
        self.setIcon(stockIcon("close-small"))
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(_("Close tab"))
        self.clicked.connect(self.onClicked)

    def onClicked(self):
        tabBar = self.parentWidget()
        assert isinstance(tabBar, QTabBar2)
        # Tabs move around; find out which one we're on now
        for i in range(tabBar.count()):
            if tabBar.tabButton(i, QTabBar.ButtonPosition.LeftSide) is self:
                tabBar.tabCloseRequested.emit(i)
                return


class QTabBar2(QTabBar):
    tabMiddleClicked = Signal(int)
    tabDoubleClicked = Signal(int)
    visibilityChanged = Signal(bool)
    wheelDelta = Signal(QPoint)
    layoutChanged = Signal()
    suggestScrollToCurrentTab = Signal()

    middleClickedIndex: int
    doubleClickedIndex: int
    shadowText: list[str]

    pillMode: bool
    """
    Tabs are pills on a track (the Neutral theme). Qt's own close buttons are
    off: each tab carries a close button at its left end, shown only while the
    pointer is over the tab, and a badge at its right end that shows what the
    tab has outstanding instead of the tab's icon.
    """

    pillCloseButtons: bool
    "In pill mode, whether the pointer brings up a tab's close button (the tabCloseButton pref)."

    hoveredIndex: int
    "The tab under the pointer, or -1."

    separatorColor: QColor
    "In pill mode, the short lines between two tabs that are neither current nor hovered."

    labelPointDrop: float
    "How many points smaller than the app's font the tab names are."

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.middleClickedIndex = -1
        self.doubleClickedIndex = -1
        self.setObjectName("QTabBar2")
        self.shadowText = []
        self.pillMode = False
        self.pillCloseButtons = True
        self.hoveredIndex = -1
        self.separatorColor = QColor()
        self.labelPointDrop = 0
        self._trackedMouseBefore = False

        self.tabMoved.connect(self._onTabMoved)

    # -------------------------------------------------------------------------
    # Layout

    def tabSizeHint(self, index: int) -> QSize:
        # Keep individual tabs from getting too wide when several tabs compete
        # for real estate. Qt may ignore this hint when the tab bar is wide
        # enough to fit all tabs.

        try:
            # Avoid tabText() here - it may return pre-elided text!
            text = self.shadowText[index]
        except IndexError:
            # May occur until tabInserted is called
           text = self.tabText(index)

        hint = super().tabSizeHint(index)

        w = 32 + self.fontMetrics().horizontalAdvance(text)

        if self.pillMode:
            # Room for the close button on the left and the badge on the right
            w += 2 * QTabBar2Badge.Size
        elif self.tabsClosable():
            closeWidth = self.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
            w += 2 * closeWidth

        w = min(w, 250)

        hint.setWidth(w)
        return hint

    def tabLayoutChange(self):
        self.layoutChanged.emit()
        # A tab may have slid under the pointer (e.g. after closing the one that was there)
        self._updateHoveredIndex()

    # -------------------------------------------------------------------------
    # Pill mode

    def setPillMode(self, pill: bool, closeButtons: bool):
        """
        Switch between pill tabs and Qt's usual tabs (see pillMode).
        The caller sets tabsClosable for the usual tabs; pill tabs are never "closable" to Qt.
        """
        self.pillCloseButtons = closeButtons

        if pill != self.pillMode:
            self.pillMode = pill
            # Follow the pointer across the tabs, and give it back as it was
            if pill:
                self._trackedMouseBefore = self.hasMouseTracking()
                self.setMouseTracking(True)
            else:
                self.setMouseTracking(self._trackedMouseBefore)
                self.hoveredIndex = -1
            for i in range(self.count()):
                self._installPillButtons(i)

        if pill:
            for i in range(self.count()):
                self.tabButton(i, QTabBar.ButtonPosition.LeftSide).setIcon(stockIcon("close-small"))
            self._syncPillButtons()

        self.update()

    def _installPillButtons(self, i: int):
        Left = QTabBar.ButtonPosition.LeftSide
        Right = QTabBar.ButtonPosition.RightSide

        if self.pillMode:
            assert not self.tabsClosable(), "Qt's close button would take the badge's place"
            self.setTabIcon(i, QIcon())  # the badge says it instead
            self.setTabButton(i, Left, QTabBar2CloseButton(self))
            self.setTabButton(i, Right, QTabBar2Badge(self))
        else:
            for side in Left, Right:
                button = self.tabButton(i, side)
                if isinstance(button, (QTabBar2CloseButton, QTabBar2Badge)):
                    self.setTabButton(i, side, None)
                    button.deleteLater()

    def setLabelPointDrop(self, drop: float):
        """Draw the tab names `drop` points smaller than the rest of the app's text."""
        if drop == self.labelPointDrop:
            self._keepLabelFont()
            return
        self.labelPointDrop = drop
        if drop:
            self._keepLabelFont()
        else:
            self.setFont(QFont())  # follow the app's font again

    def _keepLabelFont(self):
        """
        Hold on to the smaller font. The style sheet puts back the font a
        widget had when it was first styled whenever it restyles it (e.g.
        when the tabs move into the window, or the theme changes), so this
        runs again after every font or style change.
        """
        if not self.labelPointDrop:
            return
        size = max(6.0, QApplication.font().pointSizeF() - self.labelPointDrop)
        if self.font().pointSizeF() != size:
            font = QApplication.font()
            font.setPointSizeF(size)
            self.setFont(font)

    def changeEvent(self, event: QEvent):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._keepLabelFont()

    def setTabBadge(self, i: int, iconKey: str):
        """In pill mode, show what tab `i` has outstanding (a stockIcon key) at its right end."""
        badge = self.tabButton(i, QTabBar.ButtonPosition.RightSide)
        assert isinstance(badge, QTabBar2Badge)
        badge.setIconKey(iconKey)

    def tabBadge(self, i: int) -> str:
        badge = self.tabButton(i, QTabBar.ButtonPosition.RightSide)
        return badge.iconKey if isinstance(badge, QTabBar2Badge) else ""

    def _updateHoveredIndex(self, pos: QPoint | None = None):
        if not self.pillMode:
            return
        if pos is None:
            pos = self.mapFromGlobal(QCursor.pos())
        index = self.tabAt(pos) if self.rect().contains(pos) and self.underMouse() else -1
        if index != self.hoveredIndex:
            self.hoveredIndex = index
            self._syncPillButtons()
            self.update()

    def _syncPillButtons(self):
        for i in range(self.count()):
            button = self.tabButton(i, QTabBar.ButtonPosition.LeftSide)
            if isinstance(button, QTabBar2CloseButton):
                button.setVisible(self.pillCloseButtons and i == self.hoveredIndex)
            badge = self.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(badge, QTabBar2Badge):
                badge.setVisible(True)

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)

        if not self.pillMode or not self.separatorColor.isValid():
            return

        # Short lines between two tabs where neither is lit up
        current = self.currentIndex()
        painter = QPainter(self)
        painter.setPen(self.separatorColor)
        for i in range(1, self.count()):
            if {i - 1, i} & {current, self.hoveredIndex}:
                continue
            rect = self.tabRect(i)
            length = min(16, rect.height() - 8)
            top = rect.top() + (rect.height() - length) // 2
            painter.drawLine(rect.left(), top, rect.left(), top + length - 1)

    # -------------------------------------------------------------------------
    # Mouse

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middleClickedIndex = self.tabAt(event.position().toPoint())
        else:
            self.middleClickedIndex = -1
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClickedIndex = self.tabAt(event.position().toPoint())
        else:
            self.doubleClickedIndex = -1
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Block double-click signal if mouse moved before releasing button
        self.doubleClickedIndex = -1
        super().mouseMoveEvent(event)
        self._updateHoveredIndex(event.position().toPoint())

    def leaveEvent(self, event: QEvent):
        super().leaveEvent(event)
        if self.hoveredIndex >= 0:
            self.hoveredIndex = -1
            self._syncPillButtons()
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        self.wheelDelta.emit(event.angleDelta())

        # DO NOT forward mouse wheel events to superclass
        # (avoid default Qt behavior that switches tabs via scroll wheel)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        runStandardHandler = True

        if event.buttons() != Qt.MouseButton.NoButton:
            # Signals will only fire if clicking a single button at a time
            pass

        elif event.button() == Qt.MouseButton.MiddleButton:
            i = self.tabAt(event.position().toPoint())
            if i >= 0 and i == self.middleClickedIndex:
                # Bypass standard mouseReleaseEvent to avoid hardcoded behavior
                # on PySide6+GNOME where middle-clicking a tab emits
                # tabCloseRequested, if tabsClosable is enabled.
                runStandardHandler = False
                self.tabMiddleClicked.emit(i)

        elif event.button() == Qt.MouseButton.LeftButton:
            i = self.tabAt(event.position().toPoint())
            if i >= 0 and i == self.doubleClickedIndex:
                runStandardHandler = False
                self.tabDoubleClicked.emit(i)

        self.middleClickedIndex = -1
        self.doubleClickedIndex = -1

        if runStandardHandler:
            super().mouseReleaseEvent(event)

        # Dragging a tab around may have hidden its buttons
        if self.pillMode:
            self._syncPillButtons()

    # -------------------------------------------------------------------------
    # Misc. events

    def focusInEvent(self, event: QFocusEvent):
        """Suggest scrolling to current tab when we receive keyboard focus"""
        super().focusInEvent(event)
        self.suggestScrollToCurrentTab.emit()

    def setVisible(self, visible: bool):
        """Forward setVisible to parent scroll area (when we get hidden due to only 1 tab remaining)"""
        super().setVisible(visible)
        self.visibilityChanged.emit(visible)

    # -------------------------------------------------------------------------
    # Shadow text bookkeeping - Needed because calling tabText() inside
    # tabSizeHint() returns elided text!

    def _onTabMoved(self, i: int, j: int):
        del self.shadowText[i]
        self.shadowText.insert(j, self.tabText(j))

    def tabInserted(self, index):
        self.shadowText.insert(index, self.tabText(index))
        super().tabInserted(index)
        if self.pillMode:
            self._installPillButtons(index)
            self._syncPillButtons()

    def tabRemoved(self, index):
        del self.shadowText[index]
        super().tabRemoved(index)

    def setTabText(self, index: int, text: str):
        currentText = self.shadowText[index]

        # Overriding tab text can be expensive, so avoid if there's no change
        if currentText != text:
            self.shadowText[index] = text
            super().setTabText(index, text)


class QTabWidget2OverflowGradient(QWidget):
    def paintEvent(self, event: QPaintEvent):
        W = 16  # gradient width
        P = 4  # opaque padding inside the gradient

        scrollArea = self.parentWidget()
        assert isinstance(scrollArea, QAbstractScrollArea)
        scrollBar = scrollArea.horizontalScrollBar()

        saw = scrollArea.width()
        sah = scrollArea.height()

        opaque = self.palette().color(QPalette.ColorRole.Window)
        transp = QColor(opaque)
        transp.setAlpha(0)

        painter = QPainter(self)

        if scrollBar.value() != 0:
            gradient = QLinearGradient(P, 0, W, 0)
            gradient.setColorAt(0, opaque)
            gradient.setColorAt(1, transp)
            painter.fillRect(QRect(0, 0, W, sah-1), gradient)

        if scrollBar.value() < scrollBar.maximum()-1:
            gradient = QLinearGradient(saw-W, 0, saw-P, 0)
            gradient.setColorAt(0, transp)
            gradient.setColorAt(1, opaque)
            painter.fillRect(QRect(saw-W, 0, W, sah-1), gradient)


class QTabWidget2Band(QWidget):
    """The strip that holds the tabs. With pill tabs, a line along its bottom sets it apart from the tab's contents."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("QTW2Band")
        self.lineColor = QColor()

    def paintEvent(self, event: QPaintEvent):
        if self.lineColor.isValid():
            painter = QPainter(self)
            painter.fillRect(0, self.height() - 1, self.width(), 1, self.lineColor)


class QTabWidget2(QWidget):
    currentChanged: Signal = Signal(int)
    tabCloseRequested: Signal = Signal(int)
    tabMiddleClicked: Signal = Signal(int)
    tabDoubleClicked: Signal = Signal(int)
    tabContextMenuRequested: Signal = Signal(QPoint, int)

    currentWidgetChanged = Signal()
    """Emitted when the displayed widget is actually changed (in contrast to
    currentChanged, which is emitted even when dragging the foreground tab)."""

    UrgentPropertyName = "QTabBar2_UrgentFlag"

    PillBandMargins = (8, 0, 8, 8)
    "Room around the pill tabs' track (left, top, right, bottom); the line under it takes the bottom pixel."

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("QTabWidget2")

        self.stacked = QStackedWidget(self)
        self.stacked.setObjectName("QTW2StackedWidget")

        self.shadowCurrentWidgetRef: weakref.ref[QWidget] = weakref.ref(self)
        """ Keep a weakref instead of a real reference to not impede GC of a
        dead widget. (A weakref on self stands in for "none".) """

        self.tabScrollArea = QScrollArea(self)
        self.tabScrollArea.setWidgetResizable(True)
        self.tabScrollArea.setFrameStyle(QFrame.Shape.NoFrame)
        self.tabScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabScrollArea.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.tabScrollArea.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.tabs = QTabBar2(self.tabScrollArea)
        self.tabs.tabMoved.connect(self.onTabMoved)
        self.tabs.currentChanged.connect(self.onCurrentChanged)
        self.tabs.tabCloseRequested.connect(self.tabCloseRequested)
        self.tabs.tabMiddleClicked.connect(self.tabMiddleClicked)
        self.tabs.tabDoubleClicked.connect(self.tabDoubleClicked)
        self.tabs.suggestScrollToCurrentTab.connect(self.ensureCurrentTabVisible)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)  # dramatically improves the tabs' appearance on macOS
        self.tabs.setUsesScrollButtons(False)  # can't have those with scroll area
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)

        self.overflowButton = QToolButton(self)
        self.overflowButton.setArrowType(Qt.ArrowType.DownArrow)
        self.overflowButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.overflowButton.setToolTip(_("List all tabs"))
        self.overflowButton.clicked.connect(self.onOverflowButtonClicked)
        self.overflowButton.setCheckable(True)
        self.overflowButton.setAutoRaise(True)
        self.overflowButton.hide()  # hiding now prevents jitter on boot because maximum height is adjuster later

        self.tabScrollArea.setWidget(self.tabs)
        self.tabs.visibilityChanged.connect(self.tabScrollArea.setVisible)
        self.tabs.wheelDelta.connect(self.scrollTabs)
        self.tabs.layoutChanged.connect(self.updateOverflowDropdown)

        self.overflowGradient = QTabWidget2OverflowGradient(self.tabScrollArea)
        self.overflowGradient.setObjectName("QTW2OverflowGradient")
        self.overflowGradient.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._pillTheme = None
        "The theme that asks for pill tabs, while they're on."

        topWidget = QTabWidget2Band(self)
        self.topWidget = topWidget
        topLayout = QHBoxLayout(topWidget)
        self.topLayout = topLayout
        topLayout.setSpacing(2)
        topLayout.setContentsMargins(0, 0, 0, 0)
        topLayout.addWidget(self.tabScrollArea)
        topLayout.addWidget(self.overflowButton)
        self.tabs.visibilityChanged.connect(self._layOutBand)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(topWidget)
        layout.addWidget(self.stacked)

        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.onCustomContextMenuRequested)

        self.overflowMenu = QMenu(self)
        self.overflowMenu.setObjectName("QTW2OverflowMenu")
        self.overflowMenu.setToolTipsVisible(True)
        self.overflowMenu.aboutToHide.connect(lambda: self.overflowButton.setChecked(False))

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

    def __len__(self):
        return self.tabs.count()

    def refreshPrefs(self):
        from gitfourchette.themes import activeTheme
        theme = activeTheme()
        pill = theme is not None and theme.pillTabs

        mustReevaluateStyleSheet = settings.prefs.expandingTabs != self.tabs.expanding()

        self.tabs.setExpanding(settings.prefs.expandingTabs)
        self.tabs.setAutoHide(settings.prefs.autoHideTabs)

        # Pill tabs bring their own close buttons, and Qt's would take the
        # badge's place: turn Qt's off before going pill, back on after leaving.
        if pill:
            self.tabs.setTabsClosable(False)
            self.tabs.setPillMode(True, settings.prefs.tabCloseButton)
        else:
            self.tabs.setPillMode(False, settings.prefs.tabCloseButton)
            self.tabs.setTabsClosable(settings.prefs.tabCloseButton)
        for i in range(self.count()):
            self._showTabStatus(i)
        self._applyPillLook(theme if pill else None)

        self.tabs.update()
        self.syncBarSize()
        self.onResize()
        self.updateOverflowDropdown()

        if mustReevaluateStyleSheet:
            reevaluateStyleSheet(self)

    def _applyPillLook(self, theme):
        """Dress the band for pill tabs, or leave it as it's always been with the usual tabs (theme is None)."""
        if theme is None and self._pillTheme is None:
            return
        self._pillTheme = theme

        if theme is not None:
            self.tabs.separatorColor = QColor(theme.tabSeparator)
            self.tabs.setLabelPointDrop(theme.tabLabelDrop)
        else:
            self.tabs.separatorColor = QColor()
            self.tabs.setLabelPointDrop(0)

        self._layOutBand()

    def _layOutBand(self):
        """
        Room around the pill tabs' track and a line under it, as long as the
        tabs show (autoHideTabs hides a lone tab).
        """
        theme = self._pillTheme
        band = theme is not None and self.tabs.isVisibleTo(self)
        self.topLayout.setContentsMargins(*(QTabWidget2.PillBandMargins if band else (0, 0, 0, 0)))
        self.topLayout.setSpacing(8 if theme is not None else 2)
        self.topWidget.lineColor = QColor(theme.border) if band else QColor()
        self.topWidget.update()

    def onCustomContextMenuRequested(self, localPoint: QPoint):
        globalPoint = self.tabs.mapToGlobal(localPoint)
        index = self.tabs.tabAt(localPoint)
        self.tabContextMenuRequested.emit(globalPoint, index)

    def onTabMoved(self, fromIndex: int, toIndex: int):
        # Keep QStackedWidget in sync with QTabBar
        w = self.stacked.widget(fromIndex)
        self.stacked.removeWidget(w)
        self.stacked.insertWidget(toIndex, w)

    def onCurrentChanged(self, i: int):
        # Keep QStackedWidget in sync with QTabBar
        self.stacked.setCurrentIndex(i)
        currentWidget = self.currentWidget()

        # Make sure the tab is visible within the scrollable area
        self.ensureCurrentTabVisible()

        # Remove urgent flag if any
        if currentWidget is not None and currentWidget.property(QTabWidget2.UrgentPropertyName):
            currentWidget.setProperty(QTabWidget2.UrgentPropertyName, None)
            # Put back whatever the tab was saying about itself before it shouted
            self._showTabStatus(i)

        # See if we should emit the currentWidgetChanged signal
        currentWidgetRef = weakref.ref(currentWidget or self)  # self stands in for None
        if currentWidgetRef != self.shadowCurrentWidgetRef:
            self.shadowCurrentWidgetRef = currentWidgetRef
            self.currentWidgetChanged.emit()

        # Forward signal
        self.currentChanged.emit(i)

    def addTab(self, w: QWidget, name: str) -> int:
        return self.insertTab(self.count(), w, name)

    def insertTab(self, index: int, w: QWidget, name: str) -> int:
        i1 = self.stacked.insertWidget(index, w)
        i2 = self.tabs.insertTab(index, name)
        self.syncBarSize()
        assert i1 == i2
        return i1

    def setCurrentIndex(self, i: int):
        self.tabs.setCurrentIndex(i)
        self.stacked.setCurrentIndex(i)
        self.tabs.update()

    def setCurrentWidget(self, widget: QWidget):
        i = self.indexOf(widget)
        assert i >= 0
        self.setCurrentIndex(i)

    def indexOf(self, widget: QWidget):
        return self.stacked.indexOf(widget)

    def widget(self, i: int):
        return self.stacked.widget(i)

    def currentIndex(self) -> int:
        return self.stacked.currentIndex()

    def setTabText(self, i: int, text: str):
        self.tabs.setTabText(i, text)

    def setTabTooltip(self, i: int, toolTip: str):
        self.tabs.setTabToolTip(i, toolTip)

    def currentWidget(self) -> QWidget:
        return self.stacked.currentWidget()

    def count(self) -> int:
        return self.stacked.count()

    def removeTab(self, i: int):
        assert isinstance(i, int)
        widget = self.stacked.widget(i)
        # remove widget from stacked view _before_ removing the tab,
        # because removing the tab may send a tab change event
        self.stacked.removeWidget(widget)
        self.tabs.removeTab(i)
        self.syncBarSize()

    def swapWidget(self, i: int, newWidget: QWidget):
        currentIndex = self.currentIndex()
        oldWidget = self.stacked.widget(i)
        self.stacked.removeWidget(oldWidget)
        assert oldWidget.parentWidget() is self.stacked, "QStackedWidget isn't supposed to deparent its pages"
        self.stacked.insertWidget(i, newWidget)
        self.stacked.setCurrentIndex(currentIndex)  # Keep it stable
        if currentIndex == i:
            self.shadowCurrentWidgetRef = weakref.ref(newWidget)
            self.currentWidgetChanged.emit()
        return oldWidget

    def widgets(self):
        for i in range(self.stacked.count()):
            yield self.stacked.widget(i)

    def syncBarSize(self):
        h = self.tabs.sizeHint().height()
        if h != 0:
            self.tabScrollArea.setFixedHeight(self.tabs.sizeHint().height())
            self.overflowGradient.resize(self.tabScrollArea.size())

    # I don't like deferring ensureCurrentTabVisible to the next event loop,
    # but the new tabbar width doesn't seem to be refreshed immediately in onCurrentChanged.
    @CallbackAccumulator.deferredMethod()
    def ensureCurrentTabVisible(self):
        i = self.currentIndex()
        if i < 0:
            return
        rect = self.tabs.tabRect(i)

        vr = self.tabScrollArea.viewport().contentsRect()
        vr.translate(self.tabScrollArea.horizontalScrollBar().value(), self.tabScrollArea.verticalScrollBar().value())

        if rect.left() < vr.left():
            p = QPoint(rect.left(), rect.center().y())
        else:
            p = QPoint(rect.right(), rect.center().y())
        self.tabScrollArea.ensureVisible(p.x(), p.y())

    def scrollTabs(self, delta: QPoint):
        x = delta.x()
        y = delta.y()
        xBias = abs(x) - abs(y)

        # Reduce jitter when it's unclear which axis the user intends to scroll on
        # (for trackpads)
        if abs(xBias) < 1:
            return

        deltaValue = x if xBias > 0 else y
        scrollBar = self.tabScrollArea.horizontalScrollBar()
        scrollBar.setValue(scrollBar.value() - deltaValue)

    @CallbackAccumulator.deferredMethod()  # don't update overflow button too often
    def updateOverflowDropdown(self):
        if self.tabs.count() <= 1:  # never overflow if there's just one tab
            isOverflowing = False
        else:
            isOverflowing = self.topWidget.width() < self.tabs.width()

        self.overflowGradient.setVisible(isOverflowing)
        self.overflowButton.setVisible(isOverflowing)

        if isOverflowing:
            self.overflowButton.setMaximumHeight(self.tabs.height())

    def onOverflowButtonClicked(self):
        self.overflowMenu.clear()
        for i in range(self.count()):
            action = QAction(self.overflowMenu)
            action.setText(self.tabs.tabText(i))
            action.setToolTip(self.tabs.tabToolTip(i))
            action.triggered.connect(lambda _dummy, j=i: self.setCurrentIndex(j))
            self.overflowMenu.addAction(action)

        pos = self.mapToGlobal(self.overflowButton.pos() + self.overflowButton.rect().bottomLeft())
        self.overflowMenu.popup(pos)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.onResize()

    def onResize(self):
        self.overflowGradient.resize(self.tabScrollArea.size())
        self.ensureCurrentTabVisible()

    StatusIconPropertyName = "gfTabStatusIcon"

    def _showTabStatus(self, i: int):
        """
        Show what tab `i` says about itself: its status icon, or the urgent icon
        while it wants attention. Pill tabs show it in their badge, at the right
        end; the usual tabs, as the tab's icon.
        """
        widget = self.widget(i)
        if widget is None:  # pragma: no cover - callers iterate over live tabs
            return
        if widget.property(QTabWidget2.UrgentPropertyName):
            iconKey = "urgent-tab"
        else:
            iconKey = widget.property(QTabWidget2.StatusIconPropertyName) or ""

        if self.tabs.pillMode:
            self.tabs.setTabBadge(i, iconKey)
        else:
            self.tabs.setTabIcon(i, stockIcon(iconKey) if iconKey else QIcon())

    def setTabStatusIcon(self, i: int, iconKey: str):
        """
        Mark a tab with what its contents have outstanding.

        Shares the one icon slot with requestAttention, which takes precedence
        while it lasts and hands the slot back when the tab is selected.
        """
        widget = self.widget(i)
        if widget is None:  # pragma: no cover - callers iterate over live tabs
            return
        if widget.property(QTabWidget2.StatusIconPropertyName) == iconKey:
            return
        widget.setProperty(QTabWidget2.StatusIconPropertyName, iconKey or None)
        self._showTabStatus(i)

    def tabStatusIcon(self, i: int) -> str:
        widget = self.widget(i)
        return (widget.property(QTabWidget2.StatusIconPropertyName) or "") if widget else ""

    def requestAttention(self, i: int):
        if i == self.currentIndex():
            return
        widget = self.widget(i)
        if widget is None:
            return
        if widget.property(QTabWidget2.UrgentPropertyName) == "true":
            return
        widget.setProperty(QTabWidget2.UrgentPropertyName, "true")
        self._showTabStatus(i)
