"""
The transport: one conversation with a hosting service.

Deliberately built on Python's own HTTP client rather than QtNetwork. The
packaged builds strip QtNetwork out (see pkg/appimage/junklist.txt: the Qt
network module, its libraries and the TLS plugins all go), because until now
nothing but optional avatars wanted it. A feature that only works when the app
was built one particular way is a feature that breaks in front of the person
using it, so this asks for nothing beyond the standard library.

Every request carries the token and nothing else identifying; every reply comes
back as parsed JSON or as an error message that has been scrubbed of the token.
Plain HTTP is refused outright - a credential that can write to the company's
repositories does not travel in the clear, however the remote is spelled.
"""

from __future__ import annotations

from contextlib import suppress

import functools
import json
import logging
import os
import ssl
import threading
import urllib.error
import urllib.request

from gitfourchette.localization import *
from gitfourchette.qt import *

logger = logging.getLogger(__name__)

TIMEOUT = 30.0

# Where Linux distributions keep the certificate authorities. A packaged build
# carries its own Python, compiled somewhere else entirely: its OpenSSL looks
# for the store at the path it was built with (/opt/_internal/... in the
# manylinux image), finds nothing on the user's machine, and every HTTPS call
# fails with "unable to get local issuer certificate". The host's own store is
# right there - this is how to find it.
CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",      # Debian, Ubuntu, Arch
    "/etc/pki/tls/certs/ca-bundle.crt",        # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",                  # openSUSE
    "/etc/pki/tls/cacert.pem",
    "/etc/ssl/cert.pem",                       # Alpine, macOS
)
CA_DIRECTORIES = ("/etc/ssl/certs", "/etc/pki/tls/certs")


@functools.cache
def sslContext() -> ssl.SSLContext:
    """
    A context that can actually verify a certificate on this machine.

    SSL_CERT_FILE and SSL_CERT_DIR are honored first because OpenSSL reads them
    itself: someone who has pointed their environment at a corporate store has
    already said where it is.
    """
    context = ssl.create_default_context()
    if context.cert_store_stats()["x509_ca"] > 0:
        return context
    for path in CA_BUNDLES:
        if os.path.isfile(path):
            with suppress(OSError, ssl.SSLError):
                context.load_verify_locations(cafile=path)
                return context
    for path in CA_DIRECTORIES:
        if os.path.isdir(path):
            with suppress(OSError, ssl.SSLError):
                context.load_verify_locations(capath=path)
                return context
    logger.warning("No certificate authorities found; HTTPS verification will fail")
    return context



class ForgeError(Exception):
    pass


class ForgeSession(QObject):
    """
    Calls the host's REST API asynchronously, one request at a time.

    The work happens on a worker thread; the answer is delivered on the GUI
    thread through a signal, so callbacks can touch widgets. Callbacks get
    (payload, error): exactly one of them is meaningful. The session never
    raises into the event loop and never logs the token.
    """

    replied = Signal(object, str, object)
    "Payload, error, callback - emitted from the worker, received on the GUI thread."

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.token = token
        self.cancelled = False
        self.replied.connect(self._deliver)

    def abandon(self):
        """Stop delivering: the dialog that asked is going away."""
        self.cancelled = True

    def scrub(self, text: str) -> str:
        return text.replace(self.token, "***token***") if self.token else text

    def get(self, url: str, callback):
        self._run("GET", url, None, callback)

    def post(self, url: str, payload: dict, callback):
        self._run("POST", url, payload, callback)

    def _run(self, method: str, url: str, payload, callback):
        if not url.lower().startswith("https://"):
            callback(None, _("Refusing to send the token over an insecure URL: {0}", url))
            return
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"PRIVATE-TOKEN": self.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        thread = threading.Thread(target=self._work, args=(method, url, headers, body, callback), daemon=True)
        thread.start()

    def _work(self, method, url, headers, body, callback):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        payload, error = None, ""
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=sslContext()) as reply:
                payload = decodeJson(reply.read())
        except urllib.error.HTTPError as failure:
            error = describeFailure(failure.code, decodeJson(failure.read()), failure.reason)
        except urllib.error.URLError as failure:
            error = _("Couldn’t reach the server: {0}", failure.reason)
        except (OSError, ValueError) as failure:
            error = str(failure)
        except Exception as failure:  # A transport must never take the app down with it
            logger.warning("Unexpected failure talking to the host", exc_info=True)
            error = str(failure)
        try:
            self.replied.emit(payload, self.scrub(error), callback)
        except RuntimeError:  # The session was deleted while the request was in flight
            pass

    def _deliver(self, payload, error, callback):
        if not self.cancelled:
            callback(payload, error)


def decodeJson(data: bytes):
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except ValueError:
        return None


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
        detail = detail or _("the token was rejected")
    elif status == 403:
        detail = detail or _("the token isn’t allowed to do this (it needs the “api” scope)")
    elif status == 404:
        detail = detail or _("not found (wrong project path, or the token can’t see it)")
    if status and detail:
        return f"HTTP {status}: {detail}"
    if status:
        return f"HTTP {status}: {fallback}"
    return str(fallback)
