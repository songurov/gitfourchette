# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Whether the system asks apps to keep motion to a minimum.

Qt tells us about the system's contrast preference, but not about Reduce
Motion (macOS) or GNOME's animation switch, so we ask the system ourselves.
"""

import logging
import subprocess

from gitfourchette.qt import MACOS, FREEDESKTOP

logger = logging.getLogger(__name__)

MAC_COMMAND = ["defaults", "read", "com.apple.universalaccess", "reduceMotion"]
GNOME_COMMAND = ["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"]

_cachedAnswer: bool | None = None


def parseMacReduceMotion(output: str) -> bool:
    """Output of MAC_COMMAND: "1" with Reduce Motion on; "0", or nothing if it was never set."""
    return output.strip() == "1"


def parseGnomeEnableAnimations(output: str) -> bool:
    """Output of GNOME_COMMAND: "false" when the desktop's animations are turned off."""
    return output.strip().lower() == "false"


def _runCommand(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"Can't tell whether the system reduces motion: {exc}")
        return ""
    return result.stdout if result.returncode == 0 else ""


def systemReducesMotion(refresh: bool = False) -> bool:
    """
    True if the system asks for less motion. The answer is cached; pass
    refresh=True to ask the system again (e.g. when a window opens).
    """
    global _cachedAnswer

    if _cachedAnswer is not None and not refresh:
        return _cachedAnswer

    if MACOS:
        answer = parseMacReduceMotion(_runCommand(MAC_COMMAND))
    elif FREEDESKTOP:
        answer = parseGnomeEnableAnimations(_runCommand(GNOME_COMMAND))
    else:
        answer = False

    _cachedAnswer = answer
    return answer
