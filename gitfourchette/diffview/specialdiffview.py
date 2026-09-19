# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffview.specialdiff import SpecialDiffError, ImageDelta
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon, escape, DocumentLinks, contrastRatio, mixColors


def secondaryTextColor(foreground: QColor, background: QColor) -> QColor:
    """
    The dimmest blend of the foreground into the background, from 45% down,
    that still reads at 4.5:1 on the background.
    """
    ratio = .45
    while ratio > 0:
        color = mixColors(foreground, background, ratio)
        if contrastRatio(color, background) >= 4.5:
            return color
        ratio = round(ratio - .05, 2)
    return QColor(foreground)


class SpecialDiffView(QTextBrowser):
    linkActivated = Signal(QUrl)

    documentLinks: DocumentLinks | None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.documentLinks = None
        self.centered = False
        self.anchorClicked.connect(self.onAnchorClicked)
        GFApplication.instance().restyle.connect(self.refreshPrefs)
        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

    def refreshPrefs(self):
        scheme = settings.prefs.syntaxHighlightingScheme()
        styleSheet = scheme.basicQss(self)
        self.setStyleSheet(styleSheet)
        self.htmlHeader = "<html><style>a { font-weight: bold; }</style>" + settings.prefs.addDelColorsStyleTag()

    def onAnchorClicked(self, link: QUrl):
        if self.documentLinks is not None and self.documentLinks.processLink(link):
            return
        self.linkActivated.emit(link)

    def replaceDocument(self, newDocument: QTextDocument):
        self.documentLinks = None
        self.centered = False

        if self.document():
            self.document().deleteLater()

        self.setDocument(newDocument)
        self.clearHistory()

        self.setOpenLinks(False)

    def textColors(self) -> tuple[QColor, QColor]:
        """Foreground and background of the text, as the syntax scheme paints them."""
        scheme = settings.prefs.syntaxHighlightingScheme()
        if scheme:
            return scheme.foregroundColor, scheme.backgroundColor
        palette = self.palette()
        return palette.color(QPalette.ColorRole.Text), palette.color(QPalette.ColorRole.Base)

    def displaySpecialDiffError(self, err: SpecialDiffError):
        document = QTextDocument(self)
        document.setObjectName("DiffErrorDocument")

        # The message reads first; the details are a step back
        foreground, background = self.textColors()
        dim = secondaryTextColor(foreground, background).name()
        details = f"<span style='color: {dim};'>{err.details}</span>" if err.details else ""

        if err.centered:
            # Good news needs no alarm-sized icon: a small one, as quiet as the details
            icon = stockIcon(err.icon, f"gray={dim}")
            pixmap: QPixmap = icon.pixmap(28, 28)
            markup = (
                f"{self.htmlHeader}"
                "<table align='center' cellspacing='0' cellpadding='0'>"
                "<tr><td align='center'><img src='icon'/></td></tr>"
                f"<tr><td align='center' style='padding-top: 8px;'><big>{err.message}</big></td></tr>"
                f"<tr><td align='center' style='padding-top: 4px;'>{details}</td></tr>"
                "</table>")
        else:
            icon = stockIcon(err.icon)
            pixmap = icon.pixmap(48, 48)
            markup = (
                f"{self.htmlHeader}"
                "<table width='100%'>"
                "<tr>"
                f"<td width='{pixmap.width()}px'><img src='icon'/></td>"
                "<td width='100%' style='padding-left: 8px; padding-top: 8px;'>"
                f"<big>{err.message}</big>"
                f"<br/>{details}"
                "</td>"
                "</tr>"
                "</table>")

        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("icon"), pixmap)

        if err.preformatted:
            markup += F"<pre>{escape(err.preformatted)}</pre>"

        markup += err.longform

        document.setHtml(markup)
        self.replaceDocument(document)

        assert self.documentLinks is None
        self.documentLinks = err.links

        # Let DocumentLinks callbacks invoke RepoTasks using this QObject chain
        err.taskInvoker = document

        self.centered = err.centered
        self.placeVertically()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.placeVertically()

    def placeVertically(self):
        """Hold a centered page a little above the middle of the view, whatever its height."""
        if not self.centered:
            return
        document = self.document()
        frame = document.rootFrame()
        frameFormat = frame.frameFormat()
        contentHeight = document.size().height() - frameFormat.topMargin() - frameFormat.bottomMargin()
        top = max(document.documentMargin(), (self.viewport().height() - contentHeight) * .4)
        if abs(frameFormat.topMargin() - top) >= 1:
            frameFormat.setTopMargin(top)
            frame.setFrameFormat(frameFormat)

    def displayImageDelta(self, delta: ImageDelta):
        """
        Both revisions of an image, side by side, plus what changed between
        them. Looking at one at a time tells you nothing about a small edit.
        """

        sides = [file for file in (delta.old, delta.new) if file.image is not None]
        difference = delta.differenceImage()
        showLfsStatus = delta.old.deltaFile.lfs or delta.new.deltaFile.lfs

        green, red = settings.prefs.addDelColors()
        neutral = self.palette().color(QPalette.ColorRole.Mid)

        columns = len(sides) + (1 if difference is not None else 0)
        budget = max(120, (self.viewport().width() - 40 * columns) // columns)

        headers = []
        cells = []
        resources = []

        for file in sides:
            tag = "add" if file is delta.new else "del"
            name = (_("New image") if file is delta.new else
                    _("Old image") if delta.new.image else
                    _("Deleted image"))

            # Show LFS info if either side is an LFS pointer:
            if showLfsStatus and not file.deltaFile.lfs.isTentative():
                lfsInfo = "LFS" if file.deltaFile.lfs else _("not LFS")
                name = f"{name}, {lfsInfo}"

            size = self.locale().formattedDataSize(file.size)
            headers.append(f"<b><{tag}>{name}</{tag}></b><br>"
                           f"{file.image.width()} &times; {file.image.height()} {_('pixels')}, {size}")

            key = "new" if file is delta.new else "old"
            color = green if file is delta.new else red
            cells.append(self._imageCell(key, file.image, color, budget))
            resources.append((key, file.image))

        if difference is not None:
            headers.append(f"<b>{_('Difference')}</b><br>{_('blank = identical')}")
            cells.append(self._imageCell("difference", difference, neutral, budget))
            resources.append(("difference", difference))

        markup = (self.htmlHeader + "<center><table cellpadding='8'>"
                  + "<tr>" + "".join(f"<td style='text-align: center'>{h}</td>" for h in headers) + "</tr>"
                  + "<tr>" + "".join(f"<td style='text-align: center'>{c}</td>" for c in cells) + "</tr>"
                  + "</table></center>")

        document = QTextDocument(self)
        document.setObjectName("ImageDiffDocument")
        document.setHtml(markup)

        for key, image in resources:
            image.setDevicePixelRatio(self.devicePixelRatio())
            document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), image)

        self.replaceDocument(document)

    def _imageCell(self, key: str, image: QImage, borderColor: QColor, budget: int) -> str:
        """An image in a colored frame, shrunk to fit its column if it has to."""

        width = image.width() / self.devicePixelRatio()
        sizeAttr = f" width='{int(budget)}'" if width > budget else ""
        return (f"<table style='border: 4px solid {borderColor.name()}; border-collapse: collapse;'>"
                f"<tr><td><img src='{key}'{sizeAttr}/></td></tr></table>")
