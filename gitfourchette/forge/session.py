"""
The transport: one conversation with a hosting service.

Every request carries the token and nothing else identifying; every reply comes
back as parsed JSON or as an error message that has been scrubbed of the token.
Plain HTTP is refused outright - a credential that can write to the company's
repositories does not travel in the clear, however the remote is spelled.
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress

from gitfourchette.qt import *

logger = logging.getLogger(__name__)

TIMEOUT_MS = 30000


class ForgeError(Exception):
    pass


class ForgeSession(QObject):
    """
    Calls the host's REST API, one request at a time, asynchronously.

    Callbacks get (payload, error): exactly one of them is meaningful. The
    session never raises into the event loop and never logs the token.
    """

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        if not HAS_QTNETWORK:  # pragma: no cover - depends on the Qt build
            raise ForgeError("QtNetwork isn't available in this build of Qt.")
        self.token = token
        self.netman = QNetworkAccessManager(self)
        self.netman.setTransferTimeout(TIMEOUT_MS)
        self.replies: list = []

    def scrub(self, text: str) -> str:
        return text.replace(self.token, "***token***") if self.token else text

    def makeRequest(self, url: str) -> QNetworkRequest:
        if not url.lower().startswith("https://"):
            raise ForgeError(f"Refusing to send the token over an insecure URL: {url}")
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"PRIVATE-TOKEN", self.token.encode("utf-8"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        return request

    def get(self, url: str, callback):
        self._run(url, callback, self.netman.get)

    def post(self, url: str, payload: dict, callback):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def send(request):
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json; charset=utf-8")
            return self.netman.post(request, body)

        self._run(url, callback, send)

    def _run(self, url: str, callback, send):
        try:
            request = self.makeRequest(url)
        except ForgeError as error:
            callback(None, str(error))
            return
        reply = send(request)
        self.replies.append(reply)
        reply.finished.connect(lambda: self._finish(reply, callback))

    def _finish(self, reply, callback):
        with suppress(ValueError):
            self.replies.remove(reply)
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        data = bytes(reply.readAll())
        error = reply.error()
        reply.deleteLater()

        payload = None
        if data:
            try:
                payload = json.loads(data.decode("utf-8", errors="replace"))
            except ValueError:
                payload = None

        if error != QNetworkReply.NetworkError.NoError or not (200 <= status < 300):
            callback(None, self.scrub(describeFailure(status, payload, reply.errorString())))
            return
        callback(payload, "")


def describeFailure(status: int, payload, fallback: str) -> str:
    """
    What went wrong, in the host's own words when it bothered to say.

    GitLab answers a rejected position with a 400 and an explanation; showing
    "Bad Request" instead of "line_code cannot be generated" is the difference
    between a reviewer fixing the anchor and giving up on the feature.
    """
    detail = ""
    if isinstance(payload, dict):
        for key in ("message", "error", "error_description"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                break
            if isinstance(value, (list, dict)):
                detail = json.dumps(value, ensure_ascii=False)[:400]
                break
    if status == 401:
        detail = detail or "the token was rejected"
    elif status == 403:
        detail = detail or "the token isn't allowed to do this (it needs the 'api' scope)"
    elif status == 404:
        detail = detail or "not found (wrong project path, or the token can't see it)"
    if status and detail:
        return f"HTTP {status}: {detail}"
    if status:
        return f"HTTP {status}: {fallback}"
    return fallback
