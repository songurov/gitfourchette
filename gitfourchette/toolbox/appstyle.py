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


class AppStyle(QProxyStyle):
    """
    Draws the app with a stock Qt style, but hands out our own icons where Qt
    would otherwise reach into the desktop's icon theme.

    Dialog buttons ask the style for their icons, so without this, a foreign
    icon set shows up on the very buttons the user is looking at.
    """

    def standardIcon(self, standardIcon, option=None, widget=None) -> QIcon:
        try:
            iconId = _ourStandardIcons[standardIcon]
        except KeyError:
            return super().standardIcon(standardIcon, option, widget)
        return stockIcon(iconId)
