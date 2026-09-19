# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os

from gitfourchette.avatars import AvatarCache, avatarCacheDir, avatarUrl, githubLogin, paintAvatar
from .util import *


def makePicture(path: str, color="#ff8800") -> str:
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(path, "PNG")
    return QUrl.fromLocalFile(path).toString()


def testGithubNoreplyAddressNamesTheAccount():
    assert githubLogin("1234567+octocat@users.noreply.github.com") == "octocat"
    assert githubLogin("octocat@users.noreply.github.com") == "octocat"
    assert githubLogin("octocat@example.com") == ""


def testAvatarsModuleLoadsWithoutQtNetwork():
    # QtNetwork is optional: the PyInstaller bundles leave it out.
    # Without it, the app must still start (it used to die with "NameError: QNetworkReply").
    import subprocess
    import sys
    import textwrap
    from pathlib import Path
    import gitfourchette

    code = textwrap.dedent("""\
        import sys
        from importlib.abc import MetaPathFinder

        class HideQtNetwork(MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name.endswith(".QtNetwork"):
                    raise ImportError(name)
                return None

        sys.meta_path.insert(0, HideQtNetwork())

        from gitfourchette.qt import HAS_QTNETWORK
        assert not HAS_QTNETWORK
        import gitfourchette.avatars
    """)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(gitfourchette.__file__).parents[1])
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def testAvatarUrlPicksASource():
    ghUrl = avatarUrl(Signature("Octo Cat", "1234+octocat@users.noreply.github.com"))
    assert ghUrl == "https://github.com/octocat.png?size=64"

    # Anyone else goes through Gravatar, which the hosting services fall back to anyway
    gravatarUrl = avatarUrl(Signature("A U Thor", "A.U.Thor@Example.com"))
    assert gravatarUrl.startswith("https://www.gravatar.com/avatar/")
    assert gravatarUrl == avatarUrl(Signature("Whoever", "a.u.thor@example.com")), "email is normalized"

    # Nothing to key a picture on
    assert avatarUrl(Signature("Nobody", "not-an-email")) == ""


def testAvatarDownloadIsCachedOnDisk(tempDir, mainWindow):
    signature = Signature("A U Thor", "a.u.thor@example.com")
    url = makePicture(f"{tempDir.name}/face.png")

    cache = AvatarCache(mainWindow)
    assert cache.urlFor(signature) == avatarUrl(signature), "the real source, before we stub it out"
    cache.urlFor = lambda sig: url

    assert cache.pixmapFor(signature) is None, "nothing to draw until the picture lands"
    waitUntilTrue(lambda: cache.pixmapFor(signature) is not None)

    picture = cache.pixmapFor(signature)
    assert not picture.isNull()
    assert os.path.isfile(cache.diskPath("a.u.thor@example.com"))

    # A fresh cache picks the picture up from disk instead of asking again
    coldCache = AvatarCache(mainWindow)
    coldCache.urlFor = lambda sig: ""  # would give up immediately
    assert coldCache.pixmapFor(signature) is not None


def testFailedAvatarDownloadIsNotRetried(tempDir, mainWindow):
    signature = Signature("Ghost", "ghost@example.com")
    missing = QUrl.fromLocalFile(f"{tempDir.name}/no-such-face.png").toString()

    cache = AvatarCache(mainWindow)
    cache.urlFor = lambda sig: missing

    assert cache.pixmapFor(signature) is None
    waitUntilTrue(lambda: not cache.pending)

    assert cache.pixmapFor(signature) is None
    assert "ghost@example.com" in cache.failed
    assert not cache.pending, "a miss is remembered, not retried on every repaint"

    # An author we can't build a URL for is written off just the same
    cache.urlFor = lambda sig: ""
    assert cache.pixmapFor(Signature("Nobody", "nobody@example.com")) is None
    assert "nobody@example.com" in cache.failed

    cache.clear()
    assert not cache.failed


def testAvatarCacheDirIsolatedInTestMode(mainWindow):
    assert "testmode" in avatarCacheDir()


def testAvatarPictureIsDrawnInsteadOfInitials(mainWindow):
    signature = Signature("A U Thor", "a.u.thor@example.com")

    picture = QPixmap(64, 64)
    picture.fill(QColor("#ff8800"))

    canvas = QImage(32, 32, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("#000000"))

    painter = QPainter(canvas)
    paintAvatar(painter, QRect(0, 0, 32, 32), signature, picture)
    painter.end()

    assert QColor(canvas.pixel(16, 16)) == QColor("#ff8800"), "the picture fills the chip"
    assert QColor(canvas.pixel(0, 0)) != QColor("#ff8800"), "...with its corners rounded off"
