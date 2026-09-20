# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import trtables
from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.settings import CONTEXT_LINES_RANGE, WhitespaceMode
from gitfourchette.toolbox import *


GROUP_GAP = 8
"""
Space between two groups of buttons. The row reads as a handful of sets, each
about one thing, rather than a line of interchangeable glyphs.
"""


class DiffButtons(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)

        self.diffMethodActions: dict[WhitespaceMode, QAction] = {}
        self.toggleIcons: dict[QToolButton, str] = {}

        # Each button is named after the setting it flips, so that a screen
        # reader has more to say than "button"; its description says what
        # flipping it does, and both go into the tooltip.
        self.contextButton = self._makeContextLinesButton()
        self.wholeFileButton = self._makeToggle(
            "diff-whole-file", "wholeFileDiff",
            description=_("Show the whole file, with the changes marked in place"))
        self.sideBySideButton = self._makeToggle(
            "diff-side-by-side", "sideBySideDiff",
            description=_("Read the new file next to the old one, in two panes"))
        self.wordWrapButton = self._makeToggle(
            "diff-wrap", "wordWrap",
            description=_("Wrap long lines instead of scrolling sideways"))
        self.showWhitespaceButton = self._makeToggle(
            "diff-show-whitespace", "showWhitespace",
            description=_("Mark the spaces and tabs in the code"))
        self.whitespaceModeButton = self._makeWhitespaceDiffButton()
        self.svgButton = self._makeToggle(
            "diff-svg", "renderSvg", _("SVG image preview"),
            description=_("Show the picture instead of the markup that draws it"))
        self.toggles = [
            self.wholeFileButton,
            self.sideBySideButton,
            self.wordWrapButton,
            self.showWhitespaceButton,
            self.svgButton,
        ]

        # Each group is about one thing: what this file is, how much of it to
        # show, how to lay it out, and what to make of whitespace.
        groups = [
            [self.svgButton],
            [self.contextButton, self.wholeFileButton],
            [self.sideBySideButton, self.wordWrapButton],
            [self.showWhitespaceButton, self.whitespaceModeButton],
        ]
        self.buttons = [button for group in groups for button in group]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(0)
        self.groupGaps: dict[QToolButton, QWidget] = {}
        for i, group in enumerate(groups):
            if i != 0:
                gap = QWidget(self)
                gap.setFixedWidth(GROUP_GAP)
                layout.addWidget(gap)
                self.groupGaps[group[0]] = gap
            for button in group:
                button.setAutoRaise(True)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setFixedSize(24, 24)
                layout.addWidget(button)

    def setSvgButtonVisible(self, visible: bool):
        """Only an SVG file has a picture to show, so the button comes and goes."""
        self.svgButton.setVisible(visible)
        # The gap that follows the button would otherwise open a hole in the row
        self.groupGaps[self.contextButton].setVisible(visible)

    # -------------------------------------------------------------------------
    # Constructor helpers

    def _makeWhitespaceDiffButton(self):
        button = QToolButton(self)
        menu = QMenu(button)

        actionGroup = QActionGroup(menu)
        actionGroup.setExclusive(True)

        for mode in WhitespaceMode:
            label = escamp(trtables.enum(mode))
            iconName = f"diff-whitespace-{mode or 'strict'}"
            action = QAction(stockIcon(iconName), label, button)
            action.triggered.connect(lambda _dummy, m=mode: self.setWhitespaceMode(m))
            action.setActionGroup(actionGroup)
            action.setCheckable(True)
            menu.addAction(action)
            self.diffMethodActions[mode] = action

        menu.insertSeparator(list(self.diffMethodActions.values())[1])

        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAccessibleName(trtables.prefKey("whitespaceMode"))

        # We'll "press" the button when the whitespace mode is anything but Strict.
        button.setCheckable(True)

        return button

    def _makeContextLinesButton(self):
        button = QToolButton(self)
        menu = QMenu(button)

        actionGroup = QActionGroup(menu)
        actionGroup.setExclusive(True)

        container = QWidget()
        layout = QHBoxLayout(container)

        spinbox = QSpinBox()
        spinbox.setRange(*CONTEXT_LINES_RANGE)  # Same range as in Settings
        spinbox.valueChanged.connect(self.setContextLines)
        spinbox.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)

        t1, t2 = _("Show up to # context lines").split("#")
        layout.addWidget(QLabel(t1))
        layout.addWidget(spinbox)
        layout.addWidget(QLabel(t2))

        wholeFileAction = QAction(_("Show &Whole File"), menu)
        wholeFileAction.setCheckable(True)
        wholeFileAction.setToolTip(_("Show the entire file, with the changes marked in place"))
        wholeFileAction.toggled.connect(self.setWholeFileDiff)
        self.wholeFileAction = wholeFileAction

        def aboutToShowContextLinesMenu():
            whole = settings.prefs.wholeFileDiff
            with QSignalBlockerContext(wholeFileAction):
                wholeFileAction.setChecked(whole)
            # A number of context lines means nothing when you're showing all of it
            container.setEnabled(not whole)
            spinbox.setValue(settings.prefs.contextLines)
            if not whole:
                spinbox.setFocus()
                spinbox.selectAll()

        widgetAction = QWidgetAction(menu)
        widgetAction.setDefaultWidget(container)
        menu.addAction(widgetAction)
        menu.addSeparator()
        menu.addAction(wholeFileAction)
        menu.aboutToShow.connect(aboutToShowContextLinesMenu)

        button.setAccessibleName(_("Context lines"))
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setText(_("Context"))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        return button

    def _makeToggle(self, icon: str, prefKey: str, name: str = "", description: str = ""):
        button = QToolButton(self)
        button.setCheckable(True)
        button.setAccessibleName(name or trtables.prefKey(prefKey))
        button.setAccessibleDescription(description)
        button.toggled.connect(lambda checked: GFApplication.applyPrefs(**{prefKey: checked}))
        self.toggleIcons[button] = icon
        self._refreshIcon(button, icon)
        return button

    @staticmethod
    def checkedColorTable() -> str:
        """
        A button that is on wears its icon in the accent color, as the
        reference does: a 24 px square of a slightly lighter gray says nothing
        from across the window.
        """
        return "gray=" + QApplication.palette().color(QPalette.ColorRole.Highlight).name()

    def _refreshIcon(self, button: QToolButton, icon: str):
        button.setIcon(stockIcon(icon, self.checkedColorTable() if button.isChecked() else ""))

    @staticmethod
    def _toggleToolTip(button: QToolButton) -> str:
        name = button.accessibleName()
        state = _("{0}: on", name) if button.isChecked() else _("{0}: off", name)
        description = button.accessibleDescription()
        return f"{state}\n{description}" if description else state

    # -------------------------------------------------------------------------
    # Sync with preferences

    def refreshPrefs(self):
        with QSignalBlockerContext(
                *self.buttons,
                *self.diffMethodActions.values(),
        ):
            self.wordWrapButton.setChecked(settings.prefs.wordWrap)
            self.showWhitespaceButton.setChecked(settings.prefs.showWhitespace)
            self.wholeFileButton.setChecked(settings.prefs.wholeFileDiff)
            self.sideBySideButton.setChecked(settings.prefs.sideBySideDiff)
            # A count of context lines means nothing while every line is shown
            self.contextButton.setEnabled(not settings.prefs.wholeFileDiff)
            # Nor does wrapping, while each pane scrolls sideways on its own:
            # lit and grouped with the button that turned it off, it would
            # promise something the two panes can't do.
            self.wordWrapButton.setEnabled(not settings.prefs.sideBySideDiff)
            label = "\u221e" if settings.prefs.wholeFileDiff else str(settings.prefs.contextLines)
            self.contextButton.setIcon(stockIcon("diff-context-lines", f"$TEXT$={label}"))
            if settings.prefs.wholeFileDiff:
                self.contextButton.setToolTip(trtables.prefKey("wholeFileDiff"))
            else:
                self.contextButton.setToolTip(
                    trtables.prefKey("contextLines").replace("#", str(settings.prefs.contextLines)))

            mode = settings.prefs.whitespaceMode
            for m, action in self.diffMethodActions.items():
                action.setChecked(m == mode)
            action = self.diffMethodActions[mode]

            toolTip = stripAccelerators(action.text())
            self.whitespaceModeButton.setToolTip(toolTip)

            # "Press" the button when the mode is anything but Strict.
            strict = mode == WhitespaceMode.Strict
            self.whitespaceModeButton.setChecked(not strict)
            self.whitespaceModeButton.setIcon(stockIcon(
                f"diff-whitespace-{mode or 'strict'}", "" if strict else self.checkedColorTable()))

            self.svgButton.setChecked(settings.prefs.renderSvg)

            for button in self.toggles:
                button.setToolTip(self._toggleToolTip(button))
                self._refreshIcon(button, self.toggleIcons[button])

    # -------------------------------------------------------------------------
    # Button callbacks

    @staticmethod
    def setWhitespaceMode(mode: WhitespaceMode):
        GFApplication.applyPrefs(whitespaceMode=mode)

    @staticmethod
    def setContextLines(n: int):
        GFApplication.applyPrefs(contextLines=n)

    def setWholeFileDiff(self, whole: bool):
        GFApplication.applyPrefs(wholeFileDiff=whole)
