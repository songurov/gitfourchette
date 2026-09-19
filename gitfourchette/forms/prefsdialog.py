# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar

from gitfourchette import prefsschema, settings, trtables
from gitfourchette.application import GFApplication
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.exttools.toolpresets import ToolPresets
from gitfourchette.exttools.usercommandsyntaxhighlighter import UserCommandSyntaxHighlighter
from gitfourchette.gitdriver import GitDriver
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.settings import CONTEXT_LINES_RANGE, SHORT_DATE_PRESETS, PrefEffects, prefs
from gitfourchette.syntax import ColorScheme, PygmentsPresets
from gitfourchette.themes import ThemeName, ThemeColors, ThemeAccent, formatStyle, parseStyle
from gitfourchette.toolbox import *
from gitfourchette.toolbox.reducemotion import systemReducesMotion

logger = logging.getLogger(__name__)

SAMPLE_SIGNATURE = Signature("Jean-Michel Tartempion", "jm.tarte@example.com", 0, 0)
SAMPLE_FILE_PATH = "spam/.ham/eggs/hello.c"

# This dict initially contains hardcoded language names, e.g. to disambiguate
# both Portugueses, to give U.S. English a shorter name, etc. For all other
# languages, the dict is fleshed out with QLocale.nativeLanguageName().
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Español",
    "pt": "Português PT",
    "pt_BR": "Português BR",
}


class _GridBuilder:
    """
    Appends rows to a grid of labels on the left and controls on the right.
    The grid has no spacing of its own: gaps are empty rows and columns with
    a size, so that each gap can be the size it needs, and a pane without
    any labels still puts its controls in the control column.
    """

    LabelColumn = 0
    FieldColumn = 2

    def __init__(self, grid: QGridLayout, labelColumnWidth: int, columnGap: int):
        self.grid = grid
        self.row = 0
        self.wide = False
        grid.setContentsMargins(QMargins())
        grid.setSpacing(0)
        grid.setColumnMinimumWidth(self.LabelColumn, labelColumnWidth)
        grid.setColumnMinimumWidth(1, columnGap)
        grid.setColumnStretch(self.FieldColumn, 1)

    def addGap(self, height: int):
        self.grid.setRowMinimumHeight(self.row, height)
        self.row += 1

    def addRow(self, label: QWidget | None, field: QWidget | QLayout):
        if self.wide:  # No label column: the field takes the whole width
            assert label is None
            if isinstance(field, QLayout):
                self.grid.addLayout(field, self.row, 0, 1, 3)
            else:
                self.grid.addWidget(field, self.row, 0, 1, 3)
            self.row += 1
            return
        if label is not None:
            self.grid.addWidget(label, self.row, self.LabelColumn, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if isinstance(field, QLayout):
            self.grid.addLayout(field, self.row, self.FieldColumn)
        else:
            self.grid.addWidget(field, self.row, self.FieldColumn)
        self.row += 1

    def addSpanning(self, widget: QWidget):
        self.grid.addWidget(widget, self.row, 0, 1, 3)
        self.row += 1

    def addBeside(self, label: QLabel, firstRow: int):
        """Put a label in the label column, level with the top of the rows added since firstRow."""
        # The label fills the column, so that it only wraps when the column is too narrow
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(label, firstRow, self.LabelColumn, self.row - firstRow, 1)

    def addStretch(self):
        self.grid.setRowStretch(self.row, 1)
        self.row += 1


def availableLocaleCodes() -> list[str]:
    """
    Returns gettext-compatible locale codes for which we have translation files.
    Note: English NOT included!
    """
    return [f.removesuffix(".mo") for f in QDir("assets:lang", "*.mo").entryList()]


def localeCodeToLanguageName(code: str) -> str:
    try:
        name = LANGUAGE_NAMES[code]
    except KeyError:
        # Cache native language name
        name = QLocale(code).nativeLanguageName()
        name = name or f"???{code}???"  # Fallback if language code not recognized by Qt
        name = name[0].upper() + name[1:]  # Many languages don't capitalize their name
        LANGUAGE_NAMES[code] = name

    return name


class PrefsDialog(QDialog):
    lastPane: ClassVar[str] = ""
    "Pane shown last; the next window opens on it (kept in session.json across launches)."

    useToolBar: ClassVar[bool] = MACOS
    "Switch panes from a toolbar of icons at the top, like a Mac settings window; elsewhere, from a list on the left."

    animateResize: ClassVar[bool] = True
    "Let the window's height glide to the next pane's (never while the system asks for less motion)."

    ControlQObjectNamePrefix = "prefctl_"
    NoteQObjectNamePrefix = "prefnote_"
    LocSettingHelpSuffix = "_help"

    PaneWidth = 640
    "Width of a pane's content: labels, gap and controls."

    WindowMargin = 20
    "Around the pane's content (left, right, bottom)."

    ToolBarGap = 16
    "Between the pane toolbar and the pane's content."

    ToolBarIconSize = 24
    ToolBarLabelPointSize = 11

    ResizeDurationMs = 180
    "How long the window takes to fit a pane's height."

    MaxScreenFraction = 0.8
    "A pane taller than this much of the screen scrolls instead."

    LabelColumnMaxWidth = 220
    "Labels wider than this wrap."

    ColumnGap = 8
    "Between a label and its control."

    RowGap = 8
    "Between two rows of a section."

    CheckBoxRowGap = 4
    "Between two checkboxes in a row: they read as one group."

    NoteGap = 2
    "Between a control and the note under it."

    SectionGap = 10
    "Above and below the hairline between two sections."

    TitleGap = 6
    "Between a title on its own row and the section's first row."

    RadioGap = 16
    "Between the radio buttons of one choice, when they fit on one row."

    DebounceMs = 400
    "A count or a format applies once it stops changing for this long, so each spin step doesn't reload the diff."

    CommandsDebounceMs = 800
    "Custom commands rebuild the Commands menu: wait for a pause in the typing."

    WriteDelayMs = 1000
    "Prefs are saved this long after the last change, and when the window closes."

    ReloadDelayMs = 1500
    "Repositories reload this long after the last change that needs it, and when the window closes."

    @benchmark
    def __init__(self, parent: QWidget, focusOn: str = ""):
        super().__init__(parent)

        self.setObjectName("PrefsDialog")
        # A settings window: no minimize or zoom button, and no "?" button in its title bar
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, False)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self.prefDiff: dict[str, Any] = {}
        "What changed while this window was open: key -> new value."

        self.valuesAtOpen: dict[str, Any] = {}
        "Value of each assigned pref when the window opened."

        self.pending: dict[str, Any] = {}
        "Values waiting for a pause (counts, commands) or a commit (paths and commands of external programs)."

        self.commitKeys: set[str] = set()
        "Prefs that apply only once the field is left or a preset is picked, and only if valid."

        self.validators: dict[str, Callable[[Any], str]] = {}
        "Checks for commitKeys: an error message, or an empty string if the value can be used."

        self.restartNotes: dict[str, QLabel] = {}
        "Notes saying a change needs a restart, per pref key."

        self.debounceTimer = QTimer(self)
        self.debounceTimer.setSingleShot(True)
        self.debounceTimer.timeout.connect(self.applyPendingValues)

        self.writeTimer = QTimer(self)
        self.writeTimer.setSingleShot(True)
        self.writeTimer.setInterval(self.WriteDelayMs)
        self.writeTimer.timeout.connect(self.writePrefs)

        self.reloadTimer = QTimer(self)
        self.reloadTimer.setSingleShot(True)
        self.reloadTimer.setInterval(self.ReloadDelayMs)
        self.reloadTimer.timeout.connect(self.reloadRepos)
        self.reloadPending = False

        self.panes = list(prefsschema.PANES)
        self.categoryKeys: list[str] = [pane.id for pane in self.panes]

        self.pages: list[QWidget | None] = [None] * len(self.panes)
        "Content of each pane, built the first time it's shown."

        self.dependencies: dict[str, tuple[str, bool]] = {}
        """
        Rows that only mean something while another setting has a given value:
        child key -> (parent checkbox key, parent value that enables the child).
        The child is disabled, not hidden, and keeps its own value.
        """

        self.dependentRowWidgets: dict[str, list[QWidget]] = {}
        "Widgets of each row in dependencies, to enable or disable along with their parent."

        self.labelColumnWidth = self.measureLabelColumn()
        "One width for the label column of every pane, so that switching panes doesn't shift the controls."

        self.reducesMotion = systemReducesMotion(refresh=True)
        self.resizeAnimation = QVariantAnimation(self)
        self.resizeAnimation.setDuration(self.ResizeDurationMs)
        self.resizeAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.resizeAnimation.valueChanged.connect(lambda height: self.setFixedHeight(int(height)))

        # One scroll area per pane, filled in when the pane is first shown
        self.stackedWidget = QStackedWidget(self)
        self.stackedWidget.setFixedWidth(self.PaneWidth)
        for pane in self.panes:
            scrollArea = QScrollArea(self.stackedWidget)
            scrollArea.setObjectName(f"prefspane_{pane.id}")
            scrollArea.setFrameShape(QFrame.Shape.NoFrame)
            scrollArea.setWidgetResizable(True)
            scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scrollArea.viewport().setAutoFillBackground(False)
            self.stackedWidget.addWidget(scrollArea)

        self.paneBar: QToolBar | None = None
        self.paneActions: list[QAction] = []
        self.categoryList: QListWidget | None = None
        self.buttonBox: QDialogButtonBox | None = None

        if self.useToolBar:
            self._buildPaneBar()
        else:
            self._buildPaneList()

        self._buildShortcuts()

        GFApplication.instance().focusChanged.connect(self.onFocusChanged)

        # Open where the user asked to go, or where they left off
        if focusOn and prefsschema.findPane(focusOn) >= 0:
            self.jumpTo(focusOn)
        else:
            self.setCategory(PrefsDialog.lastPane if PrefsDialog.lastPane in self.categoryKeys else 0)

    # -------------------------------------------------------------------------
    # Window shell

    def _buildPaneBar(self):
        """
        Mac settings window: a row of icons with their names across the top,
        the current pane's name in the title bar, and its content underneath.
        """
        bar = QToolBar(self)
        bar.setObjectName("PrefsPaneBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        bar.setIconSize(QSize(self.ToolBarIconSize, self.ToolBarIconSize))
        barFont = QFont(bar.font())
        barFont.setPointSizeF(self.ToolBarLabelPointSize if MACOS else barFont.pointSizeF())
        bar.setFont(barFont)

        def spacer():
            widget = QWidget(bar)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            return widget

        group = QActionGroup(self)
        group.setExclusive(True)

        bar.addWidget(spacer())
        for index, pane in enumerate(self.panes):
            name = trtables.prefKey(pane.id)
            action = QAction(stockIcon(pane.icon), name, self)
            action.setCheckable(True)
            action.setToolTip(name)
            action.triggered.connect(lambda _checked=False, i=index: self.setCategory(i))
            group.addAction(action)
            bar.addAction(action)
            button = bar.widgetForAction(action)
            button.setObjectName(f"prefspanebutton_{pane.id}")
            button.setAccessibleName(name)
            button.setFont(barFont)
            self.paneActions.append(action)
        bar.addWidget(spacer())
        self.paneBar = bar

        content = QVBoxLayout()
        content.setContentsMargins(self.WindowMargin, self.ToolBarGap, self.WindowMargin, self.WindowMargin)
        content.setSpacing(0)
        content.addWidget(self.stackedWidget)
        self._addButtonBox(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addLayout(content)

        self.setFixedWidth(self.PaneWidth + 2 * self.WindowMargin)

    def _buildPaneList(self):
        """Elsewhere: the panes in a list on the left, wide enough for every name in full."""
        paneList = QListWidget(self)
        paneList.setObjectName("PrefsPaneList")
        paneList.setUniformItemSizes(True)
        paneList.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        paneList.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        paneList.setTextElideMode(Qt.TextElideMode.ElideNone)
        paneList.setIconSize(QSize(self.ToolBarIconSize, self.ToolBarIconSize))
        for pane in self.panes:
            item = QListWidgetItem(stockIcon(pane.icon), trtables.prefKey(pane.id))
            paneList.addItem(item)
        widest = max(paneList.fontMetrics().horizontalAdvance(trtables.prefKey(pane.id)) for pane in self.panes)
        paneList.setFixedWidth(widest + self.ToolBarIconSize + 48)
        paneList.currentRowChanged.connect(self.onCategoryChanged)
        self.categoryList = paneList

        right = QVBoxLayout()
        right.setSpacing(0)
        right.addWidget(self.stackedWidget)
        self._addButtonBox(right)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self.WindowMargin, self.WindowMargin, self.WindowMargin, self.WindowMargin)
        layout.setSpacing(self.WindowMargin)
        layout.addWidget(paneList)
        layout.addLayout(right)

        self.setFixedWidth(paneList.width() + self.PaneWidth + 3 * self.WindowMargin)

    def _addButtonBox(self, layout: QBoxLayout):
        # Changes apply as they're made, so there's nothing to confirm or cancel. Where the desktop
        # expects a way out at the bottom of a window (KDE, Windows), there's a Close button.
        if MACOS or GNOME:
            return
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.buttonBox.rejected.connect(self.reject)
        layout.addSpacing(self.WindowMargin)
        layout.addWidget(self.buttonBox)

    def _buildShortcuts(self):
        # Esc, the close button and Cmd+W (Ctrl+W) all close the window, keeping every change
        closeShortcut = QShortcut(QKeySequence.StandardKey.Close, self)
        closeShortcut.activated.connect(self.close)

        # Cmd+1 to Cmd+8 (Ctrl elsewhere) go straight to a pane
        for index in range(min(len(self.panes), 9)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self.setCategory(i, fromKeyboard=True))

        # Ctrl+Tab, Ctrl+Shift+Tab step through them (on macOS, Qt calls the Control key Meta)
        nextKeys = makeMultiShortcut(QKeySequence.StandardKey.NextChild, *(["Meta+Tab"] if MACOS else []))
        previousKeys = makeMultiShortcut(QKeySequence.StandardKey.PreviousChild, *(["Meta+Shift+Backtab"] if MACOS else []))
        for keys, step in ((nextKeys, 1), (previousKeys, -1)):
            shortcut = QShortcut(self)
            shortcut.setKeys(keys)
            shortcut.activated.connect(lambda step=step: self.stepCategory(step))

    def setCategory(self, pane: int | str, fromKeyboard: bool = False):
        index = self.categoryKeys.index(pane) if isinstance(pane, str) else pane
        if self.categoryList is not None:
            if self.categoryList.currentRow() != index:
                self.categoryList.setCurrentRow(index)  # calls onCategoryChanged
            else:
                self.onCategoryChanged(index)
        else:
            self.onCategoryChanged(index)
        if fromKeyboard:
            self.focusFirstControl()

    def stepCategory(self, step: int):
        self.setCategory((self.stackedWidget.currentIndex() + step) % len(self.panes), fromKeyboard=True)

    def onCategoryChanged(self, index: int):
        if index < 0:
            return
        self.ensurePaneBuilt(index)
        self.stackedWidget.setCurrentIndex(index)
        paneName = trtables.prefKey(self.categoryKeys[index])
        self.setWindowTitle(paneName)
        if self.paneActions:
            self.paneActions[index].setChecked(True)
            self.refreshPaneBarIcons()
        self.fitToPane()

        # Remember which pane we've last shown for next time the window opens
        PrefsDialog.lastPane = self.categoryKeys[index]

    def ensurePaneBuilt(self, index: int) -> QWidget:
        page = self.pages[index]
        if page is None:
            page = self._renderPane(self.panes[index])
            self._bindDependencies()
            scrollArea = self.stackedWidget.widget(index)
            assert isinstance(scrollArea, QScrollArea)
            scrollArea.setWidget(page)
            page.setAutoFillBackground(False)
            self.pages[index] = page
        return page

    def jumpTo(self, prefKey: str):
        """Show the pane with this setting, and put the keyboard focus on it."""
        index = prefsschema.findPane(prefKey)
        if index < 0:
            return
        self.setCategory(index)
        control = self.pages[index].findChild(QWidget, self.ControlQObjectNamePrefix + prefKey)
        if control is not None:
            control.setFocus()

    def focusFirstControl(self):
        page = self.pages[self.stackedWidget.currentIndex()]
        for widget in page.findChildren(QWidget):
            if (widget.isEnabled() and widget.isVisibleTo(page)
                    and widget.focusPolicy() & Qt.FocusPolicy.TabFocus and widget.focusProxy() is None):
                widget.setFocus(Qt.FocusReason.TabFocusReason)
                return

    def paneHeight(self, index: int) -> int:
        """Height of a pane's content at the pane's width."""
        layout = self.ensurePaneBuilt(index).layout()
        if layout.hasHeightForWidth():
            return layout.totalHeightForWidth(self.PaneWidth)
        return layout.totalSizeHint().height()

    def targetHeight(self, index: int) -> int:
        content = self.paneHeight(index)
        extra = 0
        if self.buttonBox is not None:
            extra = self.WindowMargin + self.buttonBox.sizeHint().height()
        if self.paneBar is not None:
            height = self.paneBar.sizeHint().height() + self.ToolBarGap + content + extra + self.WindowMargin
        else:
            listHeight = sum(self.categoryList.sizeHintForRow(i) for i in range(self.categoryList.count()))
            listHeight += 2 * self.categoryList.frameWidth() + 8
            height = 2 * self.WindowMargin + max(content + extra, listHeight)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            height = min(height, int(screen.availableGeometry().height() * self.MaxScreenFraction))
        return height

    def fitToPane(self):
        """Settings windows fit the pane they show: the height follows it, the width stays."""
        target = self.targetHeight(self.stackedWidget.currentIndex())
        self.resizeAnimation.stop()
        animate = (self.animateResize and self.isVisible() and self.paneBar is not None
                   and not self.reducesMotion and self.height() != target)
        if animate:
            self.resizeAnimation.setStartValue(self.height())
            self.resizeAnimation.setEndValue(target)
            self.resizeAnimation.start()
        else:
            self.setFixedHeight(target)

    def refreshPaneBarIcons(self):
        """The current pane's icon takes the accent color, like its fill and its brighter name."""
        accent = self.palette().color(QPalette.ColorRole.Highlight).name()
        for action, pane in zip(self.paneActions, self.panes, strict=True):
            action.setIcon(stockIcon(pane.icon, f"gray={accent}") if action.isChecked() else stockIcon(pane.icon))

    def changeEvent(self, event: QEvent):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange) and self.paneActions:
            self.refreshPaneBarIcons()
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self.fitToPane)  # e.g. Density changed the font

    # -------------------------------------------------------------------------
    # Layout

    def visibleSections(self, pane: prefsschema.Pane) -> list[tuple[prefsschema.Section, list[prefsschema.Row]]]:
        sections = []
        for section in pane.sections:
            rows = [row for row in section.rows if not self.isRowHidden(row)]
            if rows:
                sections.append((section, rows))
        return sections

    def _renderPane(self, pane: prefsschema.Pane) -> QWidget:
        """
        Lay out one page: a label column shared by every page, right-aligned,
        and the controls to its right. Sections are separated by a hairline.
        A section's title sits in the label column beside its first row when
        that row has no label of its own; otherwise it gets a row of its own.
        """
        page = QWidget(self)
        page.setObjectName(f"prefspage_{pane.id}")

        builder = _GridBuilder(QGridLayout(page), self.labelColumnWidth, self.ColumnGap)
        builder.wide = pane.wide

        for sectionIndex, (section, rows) in enumerate(self.visibleSections(pane)):
            if sectionIndex > 0:
                builder.addGap(self.SectionGap)
                builder.addSpanning(QFaintSeparator(page))
                builder.addGap(self.SectionGap)
            self._renderSection(builder, section, rows)

        guide = trtables.prefKeyNoDefault(f"{pane.id}_guide")
        if guide:
            builder.addGap(self.RowGap)
            self._renderGuide(builder, pane.id, guide)

        builder.addStretch()
        return page

    def _renderGuide(self, builder: _GridBuilder, paneId: str, guideHtml: str):
        """A reference for the pane, folded under a disclosure button until it's asked for."""
        browser = QTextBrowser(self)
        browser.setObjectName(f"prefguidetext_{paneId}")
        browser.setOpenExternalLinks(True)
        browser.setHtml(guideHtml)
        browser.setMinimumHeight(240)
        browser.setVisible(False)
        tweakWidgetFont(browser, 90)

        button = QToolButton(self)
        button.setObjectName(f"prefguide_{paneId}")
        button.setText(_("Command reference"))
        button.setAccessibleName(button.text())
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setArrowType(Qt.ArrowType.RightArrow)
        button.setAutoRaise(True)
        button.setCheckable(True)

        def toggle(show: bool):
            button.setArrowType(Qt.ArrowType.DownArrow if show else Qt.ArrowType.RightArrow)
            browser.setVisible(show)

        button.toggled.connect(toggle)

        builder.addRow(None, button)
        builder.addGap(self.NoteGap)
        builder.addRow(None, browser)

    def _renderSection(self, builder: _GridBuilder, section: prefsschema.Section, rows: list[prefsschema.Row]):
        titleBeside = None
        if section.title:
            title = self.makeTitle(section.title)
            if self.rowLabelText(rows[0]):
                builder.addSpanning(title)
                builder.addGap(self.TitleGap)
            else:
                titleBeside = title

        firstGridRow = builder.row
        previousRow = None
        for row in rows:
            if previousRow is not None:
                tight = self.isCheckBoxRow(previousRow) and self.isCheckBoxRow(row) and not previousRow.note
                builder.addGap(self.CheckBoxRowGap if tight else self.RowGap)
            self._renderRow(builder, row)
            previousRow = row

        if titleBeside is not None:
            # Like a Mac settings window: the title leads its rows from the label column
            builder.addBeside(titleBeside, firstGridRow)

    def _renderRow(self, builder: _GridBuilder, row: prefsschema.Row):
        key = row.key

        if row.parent:
            self.dependencies[key] = (row.parent.removeprefix("!"), not row.parent.startswith("!"))
        isChild = key in self.dependencies

        caption, suffix = self.rowCaption(row)
        labelText = self.rowLabelText(row)

        # Make the actual control widget
        control = self.makeControlWidget(row, prefs.__dict__[key], caption)
        note: QLabel | None = None
        if isinstance(control, tuple):  # The control comes with its own live note
            control, note = control
        rowWidgets: list[QWidget] = [control]

        # Name the control so that unit tests can find it
        if not control.objectName():
            control.setObjectName(self.ControlQObjectNamePrefix + key)

        # Tack an extra QLabel to the end if there's a suffix
        if suffix:
            rowWidgets.append(QLabel(suffix))

        if row.toggle:
            self.prependCheckBox(rowWidgets, row.toggle, caption)
        elif key == "resetDontShowAgain":
            rowWidgets.append(self.dontShowAgainCountLabel(control))

        # Any help text? Then make a help button for it & set tooltip text on the main control.
        # A row with a note says the gist under the control already: the tooltip is enough there.
        tip = trtables.prefKeyNoDefault(key + self.LocSettingHelpSuffix).format(app=qAppName())
        hintButton = None
        if tip:
            control.setToolTip(tip)
        if tip and not row.note:
            hintButton = QHintButton(self, tip)
            hintButton.makeReachable(stripAccelerators(" ".join(t for t in (caption, suffix) if t)))
            # Keep rows tight, but never below the smallest clickable size
            hintButton.setMaximumHeight(max(QHintButton.MinimumHitSize, 2 + hintButton.fontMetrics().height()))

        # The field: the row's widgets side by side, at their natural size
        field = QHBoxLayout()
        field.setSpacing(6)
        if isChild and not labelText and isinstance(rowWidgets[0], QCheckBox):
            # Line up a dependent checkbox's text with its parent's text
            field.addSpacing(self.checkBoxTextIndent(rowWidgets[0]))
        for w in rowWidgets:
            field.addWidget(w)
        if hintButton is not None:
            field.addWidget(hintButton)
        if control.sizePolicy().horizontalPolicy() not in (QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding):
            field.addStretch()

        label = None
        if labelText:
            label = QLabel(labelText)
            label.setBuddy(rowWidgets[0])
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if label.sizeHint().width() > self.LabelColumnMaxWidth:
                label.setWordWrap(True)
                label.setFixedWidth(self.LabelColumnMaxWidth)
            if tip:
                label.setToolTip(tip)

        if isChild:
            self.dependentRowWidgets[key] = ([label] if label else []) + rowWidgets

        builder.addRow(label, field)

        noteText = trtables.prefKeyNoDefault(row.note) if row.note else ""
        if key in PrefEffects.RestartApp:
            # Shown only while the value differs from the one the app started with
            note = self.makeNote(_("Takes effect after you restart {app}.", app=qAppName()), key)
            self.restartNotes[key] = note
            self.refreshRestartNote(key)
        elif key in self.commitKeys:
            # Shown only when the value can't be used
            note = self.makeNote("", key)
            note.setVisible(False)
        if noteText and note is None:
            note = self.makeNote(noteText, key)
        if note is not None:
            if not note.objectName():
                note.setObjectName(self.NoteQObjectNamePrefix + key)
            builder.addGap(self.NoteGap)
            if isChild and not labelText and isinstance(rowWidgets[0], QCheckBox):
                # Under the dependent checkbox's text, like the checkbox itself
                noteField = QHBoxLayout()
                noteField.addSpacing(self.checkBoxTextIndent(rowWidgets[0]))
                noteField.addWidget(note)
                builder.addRow(None, noteField)
            else:
                builder.addRow(None, note)
            if isChild:
                self.dependentRowWidgets[key].append(note)

    def makeTitle(self, titleKey: str) -> QLabel:
        title = QLabel(trtables.prefKey(titleKey))
        title.setObjectName(f"preftitle_{titleKey}")
        title.setFont(self.titleFont())  # A title, not an option that happens to be unavailable
        title.setWordWrap(True)
        title.setMaximumWidth(self.LabelColumnMaxWidth)
        return title

    def makeNote(self, text: str, key: str) -> QLabel:
        """Secondary text under a control, wrapped at the control column."""
        note = QLabel(text)
        note.setObjectName(self.NoteQObjectNamePrefix + key)
        note.setProperty("class", "secondary")  # Dimmed, but still readable
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.AutoText)
        note.setFont(self.noteFont())
        note.setMaximumWidth(self.controlColumnWidth())
        return note

    @staticmethod
    def noteFont() -> QFont:
        """
        Notes are secondary, so on macOS they're smaller, but never under 11 pt.
        Desktop fonts elsewhere are 9-10 pt already: notes keep the app's size
        there, and the dimmed color alone sets them apart.
        """
        font = QFont(QApplication.font())
        size = QApplication.font().pointSizeF()
        if MACOS:
            size = max(size - 2, 11.0)
        font.setPointSizeF(size)
        return font

    @staticmethod
    def titleFont() -> QFont:
        font = QFont(QApplication.font())
        font.setBold(True)
        return font

    def controlColumnWidth(self) -> int:
        return self.PaneWidth - self.labelColumnWidth - self.ColumnGap

    @staticmethod
    def checkBoxTextIndent(checkBox: QCheckBox) -> int:
        style = checkBox.style()
        return (style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, checkBox)
                + style.pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing, None, checkBox))

    def measureLabelColumn(self) -> int:
        """Width of the widest label or side title of any pane, up to LabelColumnMaxWidth."""
        labelMetrics = QFontMetrics(QApplication.font())
        titleMetrics = QFontMetrics(self.titleFont())
        widest = 0
        for pane in prefsschema.PANES:
            for section, rows in self.visibleSections(pane):
                if section.title and not self.rowLabelText(rows[0]):
                    widest = max(widest, titleMetrics.horizontalAdvance(trtables.prefKey(section.title)))
                for row in rows:
                    text = self.rowLabelText(row)
                    widest = max(widest, labelMetrics.horizontalAdvance(stripAccelerators(text)))
        return min(widest + 2, self.LabelColumnMaxWidth)

    def rowCaption(self, row: prefsschema.Row) -> tuple[str, str]:
        """The row's caption, and the unit after its control, if any ('#' in the translated string)."""
        suffix = ""
        caption = trtables.prefKey(row.label or row.key)
        if "#" in caption:
            caption, suffix = caption.split("#")
            caption = caption.rstrip()
            suffix = suffix.lstrip()
        return caption, suffix

    def rowLabelText(self, row: prefsschema.Row) -> str:
        """What the label column says for this row: empty if the control carries its own caption."""
        caption, _suffix = self.rowCaption(row)
        if not caption or row.toggle or row.key == "resetDontShowAgain" or self.isCheckBoxRow(row):
            return ""  # The control carries the caption: a checkbox or a push button
        return caption + _(":")

    def isCheckBoxRow(self, row: prefsschema.Row) -> bool:
        return (type(prefs.__dict__[row.key]) is bool
                and row.control == "auto"
                and row.key != "resetDontShowAgain"  # A push button
                and not self.boolChoiceNames(row.key))

    @staticmethod
    def boolChoiceNames(key: str) -> tuple[str, str] | None:
        """Words for the True and False choices of a bool pref shown as a choice, not a checkbox."""
        trueText = trtables.prefKeyNoDefault(key + "_true")
        falseText = trtables.prefKeyNoDefault(key + "_false")
        if trueText or falseText:
            return trueText, falseText
        return None

    def _bindDependencies(self):
        for childKey, (parentKey, parentValue) in list(self.dependencies.items()):
            parent = self.findChild(QCheckBox, self.ControlQObjectNamePrefix + parentKey)
            childWidgets = self.dependentRowWidgets.get(childKey, [])
            if parent is None or not childWidgets:  # Not built yet, or not shown on this platform
                continue
            self.bindEnabled(parent, childWidgets, enabledWhen=parentValue)
            del self.dependencies[childKey]  # Bound once

    def bindEnabled(self, parent: QCheckBox, widgets: list[QWidget], enabledWhen: bool = True):
        """Enable `widgets` only while `parent` is checked (or unchecked, if not `enabledWhen`)."""

        def follow(state: Qt.CheckState):
            for widget in widgets:
                widget.setEnabled((state == Qt.CheckState.Checked) == enabledWhen)

        parent.checkStateChanged.connect(follow)
        follow(parent.checkState())  # Prime enabled/disabled state

    # -------------------------------------------------------------------------
    # Applying changes as they're made

    def assign(self, k: str, v: Any):
        """
        A control changed a pref. Most changes apply right away; counts, formats
        and commands wait for a pause; paths and commands of external programs
        wait until the field is left, and apply only if they can be used.
        """
        self.valuesAtOpen.setdefault(k, prefs.__dict__[k])
        if v == self.valuesAtOpen[k]:
            self.prefDiff.pop(k, None)
        else:
            self.prefDiff[k] = v
        logger.debug(f"Assign {k} {v} ({type(v)})")

        if k in self.commitKeys:
            self.pending[k] = v
        elif k == "commands":
            self.pending[k] = v
            self.debounceTimer.start(self.CommandsDebounceMs)
        elif type(v) is int or k == "shortTimeFormat":
            self.pending[k] = v
            self.debounceTimer.start(max(self.DebounceMs, self.debounceTimer.interval() if self.debounceTimer.isActive() else 0))
        else:
            self.applyValues({k: v})

    def assignMany(self, values: dict[str, Any]):
        """Several prefs that one control sets together, applied together after a pause."""
        for k, v in values.items():
            self.valuesAtOpen.setdefault(k, prefs.__dict__[k])
            if v == self.valuesAtOpen[k]:
                self.prefDiff.pop(k, None)
            else:
                self.prefDiff[k] = v
            self.pending[k] = v
        self.debounceTimer.start(self.DebounceMs)

    def commit(self, k: str) -> bool:
        """Apply a pending path or command once it's been entered, if it can be used."""
        if k not in self.pending:
            return True
        value = self.pending[k]
        validate = self.validators.get(k)
        error = validate(value) if validate else ""
        errorNote = self.findChild(QLabel, self.NoteQObjectNamePrefix + k)
        if errorNote is not None:
            errorNote.setText(error)
            errorNote.setVisible(bool(error))
        if error:
            return False
        del self.pending[k]
        self.applyValues({k: value})
        return True

    def applyPendingValues(self):
        """Apply what's waiting for a pause (not the paths waiting to be committed)."""
        self.debounceTimer.stop()
        values = {k: v for k, v in self.pending.items() if k not in self.commitKeys}
        for k in values:
            del self.pending[k]
        if values:
            self.applyValues(values)

    def applyValues(self, values: dict[str, Any]):
        values = {k: v for k, v in values.items() if prefs.__dict__[k] != v}
        if not values:
            return
        GFApplication.instance()._applyPrefs(dict(values), quiet=True)
        self.writeTimer.start()
        for k in values:
            self.refreshRestartNote(k)
        if PrefEffects.ReloadRepo & set(values):
            self.reloadPending = True
            self.reloadTimer.start()

    def flush(self):
        """Apply everything still waiting, reload what needs it, and save."""
        self.applyPendingValues()
        for k in list(self.pending):
            self.commit(k)
        if self.reloadPending:
            self.reloadRepos()
        self.writePrefs()

    def writePrefs(self):
        self.writeTimer.stop()
        if prefs.isDirty():
            prefs.write()

    def reloadRepos(self):
        """Some changes (sorting, how many commits to load) take a full reload of the repositories."""
        self.reloadTimer.stop()
        self.reloadPending = False
        mainWindow = GFApplication.instance().mainWindow
        if mainWindow is not None and mainWindow.tabs.count() != 0:
            mainWindow.reloadAllTabs()

    def refreshRestartNote(self, k: str):
        note = self.restartNotes.get(k)
        if note is None:
            return
        launchValue = GFApplication.instance().prefsAtLaunch.get(k, prefs.__dict__[k])
        note.setVisible(prefs.__dict__[k] != launchValue)

    def onFocusChanged(self, old: QWidget | None, _new: QWidget | None):
        # A count that's been typed in applies as soon as the field is left, without waiting
        if old is not None and self.isAncestorOf(old) and self.pending:
            self.applyPendingValues()

    def done(self, result: int):
        # Closing never discards anything: whatever is still waiting applies now
        with suppress(TypeError, RuntimeError):
            GFApplication.instance().focusChanged.disconnect(self.onFocusChanged)
        self.flush()
        super().done(result)

    def getMostRecentValue(self, k):
        if k in self.pending:
            return self.pending[k]
        elif k in prefs.__dict__:
            return prefs.__dict__[k]
        else:
            return None

    @staticmethod
    def isRowHidden(row: prefsschema.Row) -> bool:
        if row.notOn == "macos":
            return MACOS
        elif row.notOn == "frozen":
            return bool(APP_FREEZE_QT)
        assert not row.notOn, f"unknown platform {row.notOn}"
        return False

    def makeControlWidget(self, row: prefsschema.Row, value, caption: str) -> QWidget | tuple[QWidget, QLabel]:
        key = row.key
        valueType = type(value)

        if row.control == "radio":
            return self.radioControl(key, value, caption)
        elif row.control == "context":
            return self.contextControl(key, value, caption)
        elif key == "language":
            return self.languageControl(key, value)
        elif key == "qtStyle":
            return self.qtStyleControl(key, value)
        elif key == "font":
            return self.fontControl(key)
        elif key == "shortTimeFormat":
            return self.dateFormatControl(key, value, SHORT_DATE_PRESETS)
        elif key == "pathDisplayStyle":
            return self.enumControl(key, value, valueType, previewCallback=lambda v: abbreviatePath(SAMPLE_FILE_PATH, v))
        elif key == "authorDisplayStyle":
            return self.enumControl(key, value, valueType, previewCallback=lambda v: abbreviatePerson(SAMPLE_SIGNATURE, v))
        elif key == "shortHashChars":
            return self.boundedIntControl(key, value, 4, 40)
        elif key == "maxRecentRepos":
            # Not 0: remembering no repos would erase their nicknames and other records
            return self.boundedIntControl(key, value, 1, 50)
        elif key == "maxTrashFiles":
            control = self.boundedIntControl(key, value, 0, 9999)
            control.setSpecialValueText(_p("a count of zero turns the setting off", "Off"))
            return control
        elif key == "recentCommitMessages":
            control = self.boundedIntControl(key, value, 0, 50)
            control.setSpecialValueText(_p("a count of zero turns the setting off", "Off"))
            return control
        elif key == "tabSpaces":
            return self.boundedIntControl(key, value, 1, 16)
        elif key == "autoFetchMinutes":
            return self.boundedIntControl(key, value, 1, 9999)
        elif key == "syntaxHighlighting":
            return self.syntaxHighlightingControl(key, value)
        elif key == "maxCommits":
            control = self.boundedIntControl(key, value, 0, 999_999_999, 1000)
            control.setSpecialValueText(_p("a limit of zero means no limit", "No limit"))
            return control
        elif key == "externalEditor":
            return self.strControlWithPresets(key, value, ToolPresets.Editors, leaveBlankHint=True)
        elif key == "externalDiff":
            return self.strControlWithPresets(
                key, value, ToolPresets.DiffTools,
                validate=lambda cmd: ToolCommands.checkCommand(cmd, "$L", "$R"))
        elif key == "externalMerge":
            return self.strControlWithPresets(
                key, value, ToolPresets.MergeTools,
                validate=lambda cmd: ToolCommands.checkCommand(cmd, "$L", "$R", "$B", "$M"))
        elif key == "terminal":
            return self.strControlWithPresets(
                key, value, ToolPresets.Terminals,
                validate=lambda cmd: ToolCommands.checkCommand(cmd, "$COMMAND"))
        elif key == "commands":
            return self.userCommandTextEditControl(key, value)
        elif key == "resetDontShowAgain":
            return QPushButton(caption, self)  # dontShowAgainCountLabel wires it up
        elif key in ["largeFileThresholdKB", "imageFileThresholdKB", "maxTrashFileKB"]:
            control = self.boundedIntControl(key, value, 0, 999_999)
            control.setSpecialValueText(_p("a limit of zero means no limit", "No limit"))
            return control
        elif key == "gitPath":
            presets = {}
            builtInGit = ToolPresets.flatpakBuiltInGit()
            if builtInGit:
                presets[_("Built-in git (sandboxed)")] = builtInGit
            presets[_("Auto-detected system git")] = ToolPresets.defaultGit(hostOnly=True)
            return self.strControlWithPresets(key, value, presets, validate=GitDriver.validateGitPath)
        elif issubclass(valueType, enum.Enum):
            return self.enumControl(key, value, type(value))
        elif valueType is int:
            # A count without a range of its own still gets a spin box: never negative, never free text
            return self.boundedIntControl(key, value, 0, 999_999)
        elif valueType is bool:
            choiceNames = self.boolChoiceNames(key)
            if choiceNames:
                trueText, falseText = choiceNames
                return self.boolComboBoxControl(key, value, trueName=trueText, falseName=falseText)
            else:
                return self.boolCheckBoxControl(key, value, caption)
        else:
            raise NotImplementedError(f"Write pref widget for {key}")

    @benchmark
    def languageControl(self, prefKey: str, prefValue: str):
        defaultCaption = _p("system default language setting", "System default")
        control = QComboBox(self)
        control.addItem(defaultCaption, userData="")
        control.insertSeparator(1)

        localeRatios = {}
        for wipLine in Path(QFile("assets:lang/wip.txt").fileName()).read_text().strip().splitlines():
            code, ratio = wipLine.split(" ")
            localeRatios[code] = ratio
        localeRatios["en"] = "100"

        localeCodes = availableLocaleCodes()
        assert "en" not in localeCodes, "English shouldn't have an .mo file"
        localeCodes.append("en")

        localeNames = {code: localeCodeToLanguageName(code) for code in localeCodes}
        localeCodes.sort(key=lambda code: "0" if code == "en" else localeNames[code].casefold())

        for code in localeCodes:
            name = f"{localeNames[code]} ({localeRatios.get(code, '--')}%)"
            control.addItem(name, code)

        control.setCurrentIndex(control.findData(prefValue))
        control.activated.connect(lambda index: self.assign(prefKey, control.currentData(Qt.ItemDataRole.UserRole)))
        control.setMaxVisibleItems(20)

        return control

    def fontControl(self, prefKey: str):
        fontControl = FontPicker(self)

        familyKey = prefKey
        sizeKey = "fontSize"

        def assignFont(family: str, size: int):
            self.assignMany({familyKey: family, sizeKey: size})

        fontControl.setCurrentFont(self.getMostRecentValue(familyKey), self.getMostRecentValue(sizeKey))
        fontControl.assign.connect(assignFont)
        return fontControl

    def strControlWithPresets(self, prefKey, prefValue, presets, leaveBlankHint=False, validate=None):
        control = QComboBoxWithPreview(self)
        control.setEditable(True)

        for k in presets:
            preview = presets[k]
            if not preview and leaveBlankHint:
                preview = "- " + _p("hint user to leave the field blank", "leave blank") + " -"
            control.addItemWithPreview(k, presets[k], preview)
            if prefValue == presets[k]:
                control.setCurrentIndex(control.count()-1)

        if leaveBlankHint:
            control.lineEdit().setPlaceholderText(_("Leave blank for system default."))

        control.setEditText(prefValue)
        control.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred))

        # Half-typed paths and commands never reach the app: they apply once the field
        # is left (or a preset is picked), and only if they can be used.
        self.commitKeys.add(prefKey)
        if validate:
            self.validators[prefKey] = validate
        control.editTextChanged.connect(lambda text: self.assign(prefKey, text))
        control.lineEdit().editingFinished.connect(lambda: self.commit(prefKey))
        control.activated.connect(lambda _index: self.commit(prefKey))

        if validate and prefKey != "gitPath":  # Running git on each keystroke would be too slow
            validator = ValidatorMultiplexer(self)
            validator.connectInput(control.lineEdit(), validate, mustBeValid=False)
            validator.run()

        return control

    def userCommandTextEditControl(self, prefKey, prefValue):
        monoFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fontMetrics = QFontMetricsF(monoFont)

        control = QPlainTextEdit(self)
        control.setFont(monoFont)
        control.setMinimumWidth(round(fontMetrics.horizontalAdvance("x" * 72)))
        control.setTabStopDistance(fontMetrics.horizontalAdvance(" " * 4))

        highlighter = UserCommandSyntaxHighlighter(control)
        highlighter.setDocument(control.document())

        control.setPlaceholderText(_(
            "# Enter custom terminal commands here.\n"
            "# You can then launch them from the {menu} menu.\n"
            "# Open {button} below for more information.",
            menu=tquo(stripAccelerators(_("&Commands"))),
            button=tquo(_("Command reference"))))

        control.setPlainText(prefValue)
        control.textChanged.connect(lambda: self.assign(prefKey, control.toPlainText()))
        return control

    def dontShowAgainCountLabel(self, button: QPushButton) -> QLabel:
        """
        Say how many messages are hidden next to the button that brings them
        back. With nothing hidden, the button has nothing to do.
        """
        countLabel = QLabel(self)
        countLabel.setProperty("class", "secondary")

        def refresh():
            count = len(prefs.dontShowAgain)
            countLabel.setText(_n("{n} message is hidden.", "{n} messages are hidden.", count))
            button.setEnabled(count > 0)

        def reset():
            self.assign("resetDontShowAgain", True)
            refresh()

        button.clicked.connect(reset)
        refresh()
        return countLabel

    def boundedIntControl(self, prefKey, prefValue, minValue, maxValue, step=1):
        control = QSpinBox(self)
        control.setMinimum(minValue)
        control.setMaximum(maxValue)
        control.setValue(prefValue)
        if control.value() != prefValue:
            # A stored value outside the range shows as the nearest bound; make that what OK saves,
            # so the box never displays a value other than the one in effect afterwards
            self.assign(prefKey, control.value())
        control.setSingleStep(step)
        control.setGroupSeparatorShown(True)
        control.setAlignment(Qt.AlignmentFlag.AlignRight)
        control.setStepType(QSpinBox.StepType.AdaptiveDecimalStepType)
        control.valueChanged.connect(lambda v, k=prefKey: self.assign(k, v))
        return control

    def boolComboBoxControl(self, prefKey: str, prefValue: bool, falseName: str, trueName: str) -> QComboBox:
        control = QComboBox(self)
        control.addItem(trueName)  # index 0 --> True
        control.addItem(falseName)  # index 1 --> False
        control.setCurrentIndex(int(not prefValue))
        control.activated.connect(lambda index: self.assign(prefKey, index == 0))
        return control

    def boolCheckBoxControl(self, prefKey: str, prefValue: bool, caption: str) -> QCheckBox:
        control = QCheckBox(caption, self)
        control.setChecked(prefValue)
        control.checkStateChanged.connect(lambda state, k=prefKey: self.assign(k, state == Qt.CheckState.Checked))
        return control

    def radioChoices(self, prefKey: str, prefValue) -> list[tuple[str, Any, str]]:
        """(caption, value, object name suffix) of each choice, the default choice first."""
        default = settings.Prefs.__dataclass_fields__[prefKey].default
        if type(prefValue) is bool:
            choiceNames = self.boolChoiceNames(prefKey)
            assert choiceNames, f"{prefKey} needs words for its choices ({prefKey}_true, {prefKey}_false)"
            trueText, falseText = choiceNames
            choices = [(trueText, True, "true"), (falseText, False, "false")]
        else:
            choices = [(trtables.enum(member), member, member.name) for member in type(prefValue)]
            choices = [choice for choice in choices if choice[0]]
        choices.sort(key=lambda choice: choice[1] != default)
        return choices

    def radioControl(self, prefKey: str, prefValue, caption: str) -> QWidget:
        """
        One radio button per choice, on one row when they fit in the control
        column, stacked otherwise.
        """
        group = QWidget(self)
        group.setAccessibleName(stripAccelerators(caption))
        buttonGroup = QButtonGroup(group)

        buttons = []
        for text, value, nameSuffix in self.radioChoices(prefKey, prefValue):
            button = QRadioButton(text, group)
            button.setObjectName(f"{self.ControlQObjectNamePrefix}{prefKey}_{nameSuffix}")
            button.setChecked(value == prefValue)
            button.toggled.connect(lambda checked, v=value: checked and self.assign(prefKey, v))
            buttonGroup.addButton(button)
            buttons.append(button)

        oneRowWidth = sum(b.sizeHint().width() for b in buttons) + self.RadioGap * (len(buttons) - 1)
        layout: QBoxLayout
        if oneRowWidth <= self.controlColumnWidth():
            layout = QHBoxLayout(group)
            layout.setSpacing(self.RadioGap)
        else:
            layout = QVBoxLayout(group)
            layout.setSpacing(4)
        layout.setContentsMargins(QMargins())
        for button in buttons:
            layout.addWidget(button)

        group.setFocusProxy(next(b for b in buttons if b.isChecked()) if any(b.isChecked() for b in buttons) else buttons[0])
        return group

    def contextControl(self, prefKey: str, prefValue: int, caption: str) -> QWidget:
        """
        How much of the file a diff shows around each change: a number of
        lines, or the whole file. Two prefs, one choice.
        """
        wholeKey = "wholeFileDiff"
        whole = prefs.__dict__[wholeKey]

        group = QWidget(self)
        group.setObjectName(self.ControlQObjectNamePrefix + "context")
        group.setAccessibleName(stripAccelerators(caption))
        buttonGroup = QButtonGroup(group)

        aroundButton = QRadioButton(group)
        aroundButton.setObjectName(f"{self.ControlQObjectNamePrefix}{wholeKey}_false")
        spinBox = self.boundedIntControl(prefKey, prefValue, *CONTEXT_LINES_RANGE)
        spinBox.setParent(group)
        spinBox.setObjectName(self.ControlQObjectNamePrefix + prefKey)
        aroundLabel = QLabel(_("lines around each change"), group)
        aroundButton.setAccessibleName(aroundLabel.text())
        wholeButton = QRadioButton(_("Whole file"), group)
        wholeButton.setObjectName(f"{self.ControlQObjectNamePrefix}{wholeKey}_true")
        wholeButton.setToolTip(trtables.prefKeyNoDefault(wholeKey + self.LocSettingHelpSuffix))
        buttonGroup.addButton(aroundButton)
        buttonGroup.addButton(wholeButton)

        layout = QHBoxLayout(group)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(6)
        layout.addWidget(aroundButton)
        layout.addWidget(spinBox)
        layout.addWidget(aroundLabel)
        layout.addSpacing(self.RadioGap)
        layout.addWidget(wholeButton)

        def follow(wholeFile: bool):
            # A number of lines means nothing while the whole file is shown
            spinBox.setEnabled(not wholeFile)
            aroundLabel.setEnabled(not wholeFile)

        (wholeButton if whole else aroundButton).setChecked(True)
        follow(whole)
        wholeButton.toggled.connect(follow)
        wholeButton.toggled.connect(lambda checked: self.assign(wholeKey, checked))
        return group

    def enumControl(self, prefKey, prefValue, enumType, previewCallback=None) -> QComboBox | QComboBoxWithPreview:
        control: QComboBox | QComboBoxWithPreview
        if previewCallback:
            control = QComboBoxWithPreview(self)
        else:
            control = QComboBox(self)

        for enumMember in enumType:
            # PySide6 demotes StrEnum to str when stored with QComboBox.setItemData().
            # Wrap the value in a tuple to preserve the type. (PyQt5 & PyQt6 do the right thing here)
            data = (enumMember,)
            name = trtables.enum(enumMember)

            if name == "":
                continue

            if previewCallback:
                control.addItemWithPreview(name, data, previewCallback(enumMember))  # type: ignore[attr-defined] # mypy not smart enough here
            else:
                control.addItem(name, data)
            if prefValue == enumMember:
                control.setCurrentIndex(control.count() - 1)

            if data == ("",):
                control.insertSeparator(control.count())

        control.activated.connect(lambda i: self.assign(prefKey, control.itemData(i)[0]))  # unpack the tuple!

        return control

    def qtStyleControl(self, prefKey, prefValue):
        currentStyleName, _mode, _accent = parseStyle(prefValue)
        control = QComboBox(self)
        variantPicker = self._customThemeVariantPickerControl(prefValue)

        separator = ("", "")
        defaultStyle = (_p("system default theme setting", "System default"), "")
        nativeStyles = [(name, name) for name in QStyleFactory.keys()]  # noqa: SIM118
        customStyles = [(trtables.enum(theme), str(theme)) for theme in ThemeName]
        nativeStyles.sort()
        customStyles.sort()

        entries = [defaultStyle, *customStyles, separator, *nativeStyles]
        for caption, styleName in entries:
            if not caption and not styleName:
                control.insertSeparator(control.count())
            else:
                control.addItem(caption, userData=styleName)
                if styleName == currentStyleName:
                    control.setCurrentIndex(control.count() - 1)

        def onPickStyle():
            i = control.currentIndex()
            newValue = control.itemData(i, Qt.ItemDataRole.UserRole)
            if newValue in ThemeName:
                variantPicker.setVisible(True)
                accentIndex = variantPicker.currentIndex()
                accentName = variantPicker.itemData(accentIndex)
                newValue = accentName
            else:
                variantPicker.setVisible(False)
            if parseStyle(newValue) == parseStyle(prefValue):
                newValue = prefValue  # Same theme, however it was spelled: nothing changes
            self.assign(prefKey, newValue)

        control.activated.connect(onPickStyle)
        variantPicker.activated.connect(onPickStyle)
        variantPicker.setVisible(currentStyleName in ThemeName)

        group = QWidget(self)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(QMargins())
        layout.addWidget(control)
        layout.addWidget(variantPicker)
        return group

    def _customThemeVariantPickerControl(self, prefValue: str) -> QComboBox:
        picker = QComboBox(self)
        picker.setIconSize(QSize(16, 16))
        enforceComboBoxMaxVisibleItems(picker, 32)

        # Compare parsed values, so that any spelling of the current theme finds its item
        currentVariant = parseStyle(prefValue)

        def addVariant(icon: QIcon, caption: str, mode: str = "", accent: str = ""):
            value = formatStyle(ThemeName.BuiltIn, mode, accent)
            picker.addItem(icon, caption, value)
            if parseStyle(value) == currentVariant:
                picker.setCurrentIndex(picker.count() - 1)

        addVariant(stockIcon("light-dark-toggle"), _("System colors"))

        for dark in [False, True]:
            picker.insertSeparator(picker.count())

            mode = "dark" if dark else "light"
            theme = ThemeColors.resolveTheme(formatStyle(ThemeName.BuiltIn, mode))

            # Light or dark with the system's accent: what the toolbar's Theme menu picks
            modeCaption = stripAccelerators(_("&Dark") if dark else _("&Light"))
            addVariant(stockIcon(f"theme-{mode}"), modeCaption, mode)

            for accent in ThemeAccent:
                icon = stockIcon("theme-chip", f"white={theme.bg} black={theme.text} blue={accent}")
                caption = _("Dark {color}") if dark else _( "Light {color}")
                caption = caption.format(color=trtables.enum(accent))
                addVariant(icon, caption, mode, accent)

        return picker

    def dateFormatControl(self, prefKey, prefValue, presets):
        currentDate = QDateTime.currentDateTime()
        sampleDate = QDateTime(QDate(currentDate.date().year(), 1, 30), QTime(9, 45))

        def genPreview(f):
            return QLocale().toString(sampleDate, f)

        def onEditTextChanged(text):
            preview.setText(genPreview(text))
            self.assign(prefKey, text)

        preview = self.makeNote(genPreview(prefValue), prefKey)

        control = QComboBoxWithPreview(self)
        control.setEditable(True)
        for presetName, presetFormat in presets.items():
            control.addItemWithPreview(presetName, presetFormat, genPreview(presetFormat))
            if prefValue == presetFormat:
                control.setCurrentIndex(control.count()-1)
        control.setMinimumWidth(200)
        control.setEditText(prefValue)
        control.editTextChanged.connect(onEditTextChanged)

        return control, preview

    @benchmark
    def syntaxHighlightingControl(self, prefKey, prefValue):
        autoCaption = _p("syntax highlighting", "Automatic ({name})", name=PygmentsPresets.Dark if isDarkTheme() else PygmentsPresets.Light)
        offCaption = _p("syntax highlighting", "Off")

        control = QComboBox(self)
        control.setIconSize(QSize(16, 16))  # Required if enforceComboBoxMaxVisibleItems kicks in
        control.addItem(stockIcon("light-dark-toggle"), autoCaption, userData=PygmentsPresets.Automatic)
        control.addItem(stockIcon("SP_BrowserStop"), offCaption, userData=PygmentsPresets.Off)
        control.insertSeparator(control.count())

        previousStyleName = ""
        for styleName, chipColors in ColorScheme.stylePreviews(prefs.pygmentsPlugins).items():
            # Insert a separator between light and dark themes, i.e. when sorting resets
            if styleName < previousStyleName:
                control.insertSeparator(control.count())
            previousStyleName = styleName
            # Little icon to preview the colors in this style
            chip = stockIcon("colorscheme-chip", chipColors)
            control.addItem(chip, styleName, userData=styleName)

        index = control.findData(prefValue)
        control.setCurrentIndex(index)

        def onPickStyle(index):
            pickedStyleName = control.itemData(index, Qt.ItemDataRole.UserRole)
            self.assign(prefKey, pickedStyleName)

        control.activated.connect(onPickStyle)

        control.setMaxVisibleItems(30)
        enforceComboBoxMaxVisibleItems(control)  # Prevent Fusion from creating a giant popup

        return control

    def prependCheckBox(self, rowWidgets: list[QWidget], booleanKey: str, caption: str) -> QCheckBox:
        """
        Add a QCheckBox on the same row as an existing widget,
        controlling whether another pref key is enabled or disabled.
        """

        booleanValue = prefs.__dict__[booleanKey]

        checkBox = self.boolCheckBoxControl(booleanKey, booleanValue, caption)
        checkBox.setObjectName(f"prefctl_{booleanKey}")  # Name the control so that unit tests can find it
        self.bindEnabled(checkBox, list(rowWidgets))

        rowWidgets.insert(0, checkBox)
        QWidget.setTabOrder(rowWidgets[0], rowWidgets[1])
        return checkBox
