# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.avatars import paintAvatar
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEREF
from gitfourchette.toolbox import *

AVATAR_PIXELS = 44


class CommitDetailView(QTextBrowser):
    """
    Everything about a commit that isn't its diff: who wrote it and when,
    where it sits in the graph, its whole message, and what it touched.
    """

    jumpRequested = Signal(NavLocator)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CommitDetailView")
        self.setOpenLinks(False)
        self.links = DocumentLinks()
        self.anchorClicked.connect(self._onAnchorClicked)

    def _onAnchorClicked(self, url: QUrl):
        # Forward to the *current* link bundle: setCommit replaces it every
        # time, so connecting to its processLink directly would leave every
        # link pointing at the bundle we happened to have at startup.
        self.links.processLink(url)

    def clear(self):
        self.links = DocumentLinks()
        self.setHtml("")

    def setCommit(self, repoModel, commit: Commit, deltas: list, isStash=False):
        self.links = DocumentLinks()
        muted = mutedTextColorHex(self)

        document = QTextDocument(self)
        avatarImage = self._avatarImage(commit.author)
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("avatar"), avatarImage)

        rows = []

        refs = repoModel.refsAt.get(commit.id, [])
        refNames = [RefPrefix.split(ref)[1] or ref for ref in refs if ref != UC_FAKEREF]
        if refNames:
            chips = " ".join(f"<code>&nbsp;{escape(name)}&nbsp;</code>" for name in refNames)
            rows.append((_("Refs"), chips))

        rows.append((_("SHA"), f"<code>{commit.id}</code>"))

        parents = ", ".join(self._commitLink(parentId) for parentId in commit.parent_ids)
        if parents:
            rows.append((_n("Parent", "Parents", len(commit.parent_ids)), parents))

        if commit.author != commit.committer:
            rows.append((_("Committer"), self._person(commit.committer)))

        table = "".join(
            f"<tr><th style='color: {muted}; text-align: right; padding-right: 8px;'>{key}</th>"
            f"<td>{value}</td></tr>"
            for key, value in rows)

        # The tab is already called Commit; only a stash needs saying
        kindLine = f"<p style='color: {muted}'>{_p('noun', 'Stash')}</p>" if isStash else ""

        markup = f"""\
            <table><tr>
            <td style='padding-right: 12px'><img src='avatar'/></td>
            <td>{self._person(commit.author)}<br>
            <span style='color: {muted}'>{escape(signatureDateFormat(commit.author, QLocale.FormatType.ShortFormat, localTime=True))}</span></td>
            </tr></table>
            <table>{table}</table>
            {kindLine}
            <pre style='white-space: pre-wrap'>{escape(commit.message.strip())}</pre>
            {self._fileTable(deltas, muted)}
            """

        document.setHtml(markup)
        self.setDocument(document)

    # -------------------------------------------------------------------------

    def _person(self, signature: Signature) -> str:
        return f"<b>{escape(signature.name)}</b> <small>&lt;{escape(signature.email)}&gt;</small>"

    def _commitLink(self, commitId: Oid) -> str:
        locator = NavLocator.inCommit(commitId)
        link = self.links.new(lambda: self.jumpRequested.emit(locator))
        return linkify(f"<code>{shortHash(commitId)}</code>", link)

    def _fileTable(self, deltas: list, muted: str) -> str:
        if not deltas:
            return f"<p style='color: {muted}'>{_('This commit is empty.')}</p>"

        rows = []
        for delta in deltas:
            path = delta.new.path or delta.old.path
            locator = NavLocator.inCommit(delta.new.sourceCommit, path)
            link = self.links.new(lambda loc=locator: self.jumpRequested.emit(loc))
            icon = stockIconImgTag(f"status_{delta.status.lower()}")
            rows.append(f"<tr><td>{icon}&nbsp;</td><td>{linkify(escape(path), link)}</td></tr>")

        heading = _n("{n} file changed:", "{n} files changed:", len(deltas))
        return f"<p style='color: {muted}'>{heading}</p><table>{''.join(rows)}</table>"

    def _avatarImage(self, signature: Signature) -> QImage:
        size = AVATAR_PIXELS
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        picture = None
        if settings.prefs.downloadAvatars:
            picture = GFApplication.instance().avatarCache.pixmapFor(signature)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paintAvatar(painter, QRect(0, 0, size, size), signature, picture)
        painter.end()

        image.setDevicePixelRatio(self.devicePixelRatio())
        return image
