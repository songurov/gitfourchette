"""
The tokens that let GitFourchette speak to a code-hosting service.

Kept out of prefs.json on purpose. A token is not a preference: it is a
credential that can write to the company's repositories, and prefs.json is a
file people copy between machines, paste into bug reports and sync to backups
without thinking about it. This one is owner-readable only, holds nothing else,
and is deleted outright when the last token is removed.
"""

import dataclasses
import logging
import os

from gitfourchette.prefsfile import PrefsFile

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ForgeAccounts(PrefsFile):
    _filename = "forge.json"

    tokens: dict[str, str] = dataclasses.field(default_factory=dict)
    """Host name (lowercase, e.g. "gitlab.example.com") -> access token."""

    def write(self, force=False) -> str:
        # Create the file with its final permissions before anything is written
        # to it: chmod after the fact leaves a window in which the token sits
        # on disk world-readable.
        path = self._getFullPath(forWriting=True)
        if path and not os.path.exists(path):
            try:
                os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
            except OSError as error:  # pragma: no cover - platform-dependent
                logger.warning(f"Couldn't pre-create {path}: {error}")
        path = super().write(force)
        if path:
            try:
                os.chmod(path, 0o600)
            except OSError as error:  # pragma: no cover - not all filesystems have modes
                logger.warning(f"Couldn't restrict permissions on {path}: {error}")
        return path

    @staticmethod
    def normalizeHost(host: str) -> str:
        return (host or "").strip().lower()

    def tokenFor(self, host: str) -> str:
        return self.tokens.get(self.normalizeHost(host), "")

    def setToken(self, host: str, token: str):
        host = self.normalizeHost(host)
        if not host:
            return
        token = (token or "").strip()
        tokens = dict(self.tokens)
        if token:
            tokens[host] = token
        else:
            tokens.pop(host, None)
        self.tokens = tokens
        self.setDirty()

    def hosts(self) -> list[str]:
        return sorted(self.tokens)


accounts = ForgeAccounts()
"The app loads it on first use; see loadAccounts()."

_loaded = False


def loadAccounts() -> ForgeAccounts:
    """The tokens, read from disk once per session."""
    global _loaded
    if not _loaded:
        accounts.load()
        _loaded = True
    return accounts


def resetAccountsForTesting():
    """Forget what was loaded, so a test starts from an empty vault."""
    global _loaded
    accounts.reset()
    _loaded = False
