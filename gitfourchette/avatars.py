# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Author avatars for the commit history.

A chip with the author's initials, colored from their email address, so that
the same person always gets the same color. No network access: the color and
the letters come from the signature that's already in the commit.
"""

# Keep annotations lazy: QtNetwork types don't exist when QtNetwork is absent (see HAS_QTNETWORK)
from __future__ import annotations

import hashlib
import logging
import os
import re

from gitfourchette.appconsts import APP_TESTMODE
from gitfourchette.porcelain import Signature
from gitfourchette.qt import *

logger = logging.getLogger(__name__)

AVATAR_SIZE = 16
AVATAR_RADIUS = 4
AVATAR_SPACING = 5

_INITIALS_SPLIT = re.compile(r"[\s._\-]+")


def avatarKey(signature: Signature) -> str:
    """Identity an avatar is keyed on: the email, or the name if there's none."""
    return (signature.email or signature.name).strip().lower()


def avatarInitials(signature: Signature) -> str:
    """One or two letters standing in for the author's name."""

    words = [w for w in _INITIALS_SPLIT.split(signature.name.strip()) if w[:1].isalnum()]

    if len(words) >= 2:
        return (words[0][0] + words[-1][0]).upper()
    if words:
        return words[0][:2].upper()

    # No usable name: fall back to the email, then to a placeholder
    return avatarKey(signature)[:2].upper() or "?"


def avatarColor(signature: Signature) -> QColor:
    """
    Stable color for an author. Hue comes from a hash of their email, while
    saturation and lightness are fixed, so that no author ends up with a chip
    that fights the rest of the interface.
    """

    digest = hashlib.sha256(avatarKey(signature).encode("utf-8")).digest()
    hue = (digest[0] << 8 | digest[1]) % 360
    return QColor.fromHsl(hue, 130, 110)


def paintAvatar(painter: QPainter, rect: QRect, signature: Signature, picture: QPixmap | None = None):
    """Draw the author's picture inside rect, or their initials if we have none."""

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if picture is not None:
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), AVATAR_RADIUS, AVATAR_RADIUS)
        painter.setClipPath(clip)
        painter.drawPixmap(rect, picture)
        painter.restore()
        return

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(avatarColor(signature))
    painter.drawRoundedRect(rect, AVATAR_RADIUS, AVATAR_RADIUS)

    font = QFont(painter.font())
    font.setStretch(QFont.Stretch.Unstretched)
    font.setBold(True)
    font.setPixelSize(max(7, round(rect.height() * .55)))
    painter.setFont(font)
    painter.setPen(QColor(Qt.GlobalColor.white))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, avatarInitials(signature))
    painter.restore()


GITHUB_NOREPLY = "users.noreply.github.com"


def githubLogin(email: str) -> str:
    """The GitHub account behind a noreply address (1234+login@users.noreply.github.com)."""

    user, _at, host = email.partition("@")
    if host != GITHUB_NOREPLY:
        return ""
    return user.split("+", 1)[-1]


def avatarUrl(signature: Signature) -> str:
    """
    Where to download this author's picture. GitHub noreply addresses name the
    account outright; everyone else goes through Gravatar, which is also what
    the hosting services fall back to.
    """

    email = avatarKey(signature)

    login = githubLogin(email)
    if login:
        return f"https://github.com/{login}.png?size={AVATAR_DOWNLOAD_SIZE}"

    if "@" not in email:
        return ""

    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?s={AVATAR_DOWNLOAD_SIZE}&d=404"


AVATAR_DOWNLOAD_SIZE = 64


def avatarCacheDir() -> str:
    parent = qTempDir() if APP_TESTMODE else QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation)
    return os.path.join(parent, "avatars")


class AvatarCache(QObject):
    """
    Author pictures downloaded from the hosting service, kept on disk.

    Nothing is downloaded unless the user asks for it: a request leaks the
    author's email address to a third party, which isn't something a git client
    should do on its own.
    """

    avatarReady = Signal()
    "Emitted when a picture arrives, so that whoever draws authors can repaint."

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.pixmaps: dict[str, QPixmap] = {}
        self.pending: set[str] = set()
        self.failed: set[str] = set()
        self.netman = None
        if HAS_QTNETWORK:
            self.netman = QNetworkAccessManager(self)
            self.netman.finished.connect(self._onReplyFinished)

    def clear(self):
        self.pixmaps.clear()
        self.pending.clear()
        self.failed.clear()

    def diskPath(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return os.path.join(avatarCacheDir(), f"{digest}.png")

    def urlFor(self, signature: Signature) -> str:
        """Overridable so that tests can serve a local file instead."""
        return avatarUrl(signature) if HAS_QTNETWORK else ""

    def pixmapFor(self, signature: Signature) -> QPixmap | None:
        """
        This author's picture, or None while we don't have one. Kicks off a
        download the first time an author shows up.
        """

        key = avatarKey(signature)

        try:
            return self.pixmaps[key]
        except KeyError:
            pass

        if key in self.pending or key in self.failed:
            return None

        pixmap = QPixmap(self.diskPath(key))
        if not pixmap.isNull():
            self.pixmaps[key] = pixmap
            return pixmap

        url = self.urlFor(signature)
        if not url:
            self.failed.add(key)
            return None

        self.pending.add(key)
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        request.setAttribute(QNetworkRequest.Attribute.User, key)
        self.netman.get(request)
        return None

    def _onReplyFinished(self, reply: QNetworkReply):
        reply.deleteLater()
        key = reply.request().attribute(QNetworkRequest.Attribute.User)
        self.pending.discard(key)

        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap.loadFromData(reply.readAll())

        if pixmap.isNull():
            logger.debug(f"No avatar for {key}")
            self.failed.add(key)
            return

        pixmap = pixmap.scaled(
            AVATAR_DOWNLOAD_SIZE, AVATAR_DOWNLOAD_SIZE,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)

        self.pixmaps[key] = pixmap

        os.makedirs(avatarCacheDir(), exist_ok=True)
        pixmap.save(self.diskPath(key), "PNG")

        self.avatarReady.emit()
