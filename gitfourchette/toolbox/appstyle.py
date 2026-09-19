# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox.iconbank import stockIcon

_SP = QStyle.StandardPixmap

_ourStandardIcons: dict[QStyle.StandardPixmap, str] = {
    _SP.SP_DialogOkButton: "check",
    _SP.SP_DialogApplyButton: "check",
    _SP.SP_DialogYesButton: "check",
    _SP.SP_DialogCancelButton: "close",
    _SP.SP_DialogNoButton: "close",
    _SP.SP_DialogCloseButton: "close",
    _SP.SP_DialogSaveButton: "save",
    _SP.SP_DialogDiscardButton: "trash",
    _SP.SP_DialogHelpButton: "hint",
    _SP.SP_DialogOpenButton: "git-folder",
    _SP.SP_DirIcon: "git-folder",
}

# No Qt style draws a Retry icon of its own. (Qt 5 doesn't have the name.)
if hasattr(_SP, "SP_DialogRetryButton"):
    _ourStandardIcons[_SP.SP_DialogRetryButton] = "retry"

if not (MACOS or WINDOWS):
    # Mac and Windows draw good-looking message box icons of their own.
    # Elsewhere, they come from whichever icon theme the desktop happens to
    # have, which rarely looks like the rest of our icons.
    _ourStandardIcons.update({
        _SP.SP_MessageBoxInformation: "info",
        _SP.SP_MessageBoxQuestion: "hint",
        _SP.SP_MessageBoxWarning: "achtung",
        _SP.SP_MessageBoxCritical: "error",
    })


_PE = QStyle.PrimitiveElement
_State = QStyle.StateFlag


class AppStyle(QProxyStyle):
    """
    Draws the app with a stock Qt style, but hands out our own icons where Qt
    would otherwise reach into the desktop's icon theme.

    Dialog buttons ask the style for their icons, so without this, a foreign
    icon set shows up on the very buttons the user is looking at.
    """

    indicatorOutline: tuple[QColor, QColor] | None = None
    """
    Outline for checkbox and radio button indicators (enabled, disabled), set
    by our own theme. Fusion derives the outline from the window color, which
    leaves an unchecked box nearly invisible on a dark palette (1.1:1). Only
    the outline is redrawn; the box, the check mark, the focus ring and the
    size stay the style's own. None leaves the style alone (native themes).
    """

    def drawPrimitive(self, element, option, painter, widget=None):
        super().drawPrimitive(element, option, painter, widget)

        if (self.indicatorOutline is None
                or element not in (_PE.PE_IndicatorCheckBox, _PE.PE_IndicatorRadioButton)
                or self.baseStyle().objectName().lower() != "fusion"):
            return

        state = option.state
        if state & _State.State_HasFocus and state & _State.State_KeyboardFocusChange:
            return  # Keep the style's focus outline

        enabledColor, disabledColor = self.indicatorOutline
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(enabledColor if state & _State.State_Enabled else disabledColor))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = option.rect
        # Same geometry as Fusion's own outline, so that it's covered exactly
        if element == _PE.PE_IndicatorCheckBox:
            painter.translate(.5, .5)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
        else:
            center = QPointF(rect.center()) + QPointF(1, 1)
            radius = (rect.width() + (rect.width() + 1) % 2) / 2.0 - 1
            painter.drawEllipse(center, radius, radius)
        painter.restore()

    def standardIcon(self, standardIcon, option=None, widget=None) -> QIcon:
        try:
            iconId = _ourStandardIcons[standardIcon]
        except KeyError:
            return super().standardIcon(standardIcon, option, widget)
        return stockIcon(iconId)
