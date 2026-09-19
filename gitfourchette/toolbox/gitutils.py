# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
from contextlib import suppress
from typing import Literal

from gitfourchette import trtables
from gitfourchette.porcelain import *
from gitfourchette.qt import *

INITIALS_PATTERN = re.compile(r"(?:^|[\s\-.'‘’\"“”])+([^\s\-.'‘’\"“”])[^\s\-.]*")
FIRST_NAME_PATTERN = re.compile(r"(\S(\.?-|\.\s?|\s))*\S+")
WINDOWS_PATH_PATTERN = re.compile(r"['\"]?^[A-Za-z]:[/\\]")

REMOTE_URL_PATTERNS = [
    # HTTP/HTTPS
    # http://example.com/user/repo
    # https://example.com/user/repo
    # https://personal_access_token@example.com/user/repo (GitHub write access over HTTPS)
    re.compile(r"^(?P<protocol>https?):\/\/(?P<user>[^@/]+@)?(?P<host>[^\/]+?)\/(?P<path>.+)"),

    # SSH (scp-like syntax)
    # example.com:user/repo
    # git@example.com:user/repo
    re.compile(r"^(?P<user>[^@/]+@)?(?P<host>[^\/]+?):(?!\/)(?P<path>.+)"),

    # SSH (full syntax)
    # ssh://example.com/user/repo
    # ssh://git@example.com/user/repo
    # ssh://git@example.com:1234/user/repo
    re.compile(r"^(?P<protocol>ssh):\/\/(?P<user>[^@/]+@)?(?P<host>[^\/]+?)(:\d+)?\/(?P<path>.+)"),

    # Git protocol
    # git://example.com/user/repo
    # git://example.com:1234/user/repo
    re.compile(r"^(?P<protocol>git):\/\/(?P<host>[^\/]+?)(:\d+)?\/(?P<path>.+)"),
]


class AuthorDisplayStyle(enum.IntEnum):
    FullName = 1
    FirstName = 2
    LastName = 3
    Initials = 4
    FullEmail = 5
    EmailUserName = 6


@enum.unique
class PatchPurpose(enum.IntFlag):
    Stage = enum.auto()
    Unstage = enum.auto()
    Discard = enum.auto()

    Lines = enum.auto()
    Hunk = enum.auto()
    File = enum.auto()

    VerbMask = Stage | Unstage | Discard


def abbreviatePerson(sig: Signature, style: AuthorDisplayStyle = AuthorDisplayStyle.FullName):
    with suppress(IndexError):
        if style == AuthorDisplayStyle.FullName:
            return sig.name

        elif style == AuthorDisplayStyle.FirstName:
            match = FIRST_NAME_PATTERN.match(sig.name)
            return match[0] if match is not None else sig.name

        elif style == AuthorDisplayStyle.LastName:
            return sig.name.rsplit(' ', maxsplit=1)[-1]

        elif style == AuthorDisplayStyle.Initials:
            return re.sub(INITIALS_PATTERN, r"\1", sig.name)

        elif style == AuthorDisplayStyle.FullEmail:
            return sig.email

        elif style == AuthorDisplayStyle.EmailUserName:
            emailParts = sig.email.split('@', 1)
            if len(emailParts) == 2 and emailParts[1] == "users.noreply.github.com":
                # Strip ID from GitHub noreply addresses (1234567+username@users.noreply.github.com)
                return emailParts[0].split('+', 1)[-1]
            else:
                return emailParts[0]

    return sig.email  # type: ignore[unreachable]


def shortHash(oid: Oid | str) -> str:
    from gitfourchette.settings import prefs
    return str(oid)[:prefs.shortHashChars]


def nameValidationMessage(name: str, reservedNames: list[str], nameTakenMessage: str = "") -> str:
    try:
        validate_refname(name, reservedNames)
    except NameValidationError as exc:
        if exc.rule == NameValidationError.Rule.NAME_TAKEN_BY_REF and nameTakenMessage:
            return nameTakenMessage
        else:
            return trtables.enum(exc.rule)

    return ""  # validation passed, no error


def remoteUrlProtocol(url: str):
    # Bail early on Windows-style absolute paths (C:\Whatever) to avoid looking like an ssh url
    if WINDOWS_PATH_PATTERN.match(url):
        return ""

    for pattern in REMOTE_URL_PATTERNS:
        m = pattern.match(url)
        if m:
            try:
                return m.group("protocol")
            except IndexError:
                return "ssh"
    return ""


def splitRemoteUrl(url: str):
    for pattern in REMOTE_URL_PATTERNS:
        m = pattern.match(url)
        if m:
            host = m.group("host")
            path = m.group("path")
            return host, path
    return "", ""


def guessRemoteUrlFromText(text: str):
    if len(text) > 128:
        return ""

    text = text.strip()

    if any(c.isspace() for c in text):
        return ""

    host, path = splitRemoteUrl(text)
    if host and path:
        return text

    return ""


def formatTimeOffset(minutes: int):
    p = "-" if minutes < 0 else "+"
    h = abs(minutes) // 60
    m = abs(minutes) % 60
    return f"{p}{h:02}:{m:02}"


def signatureEnvironmentVariables(sig: Signature, infix: Literal["AUTHOR", "COMMITTER"]) -> dict[str, str]:
    return {
        f"GIT_{infix}_NAME": sig.name,
        f"GIT_{infix}_EMAIL": sig.email,
        f"GIT_{infix}_DATE": f"{sig.time}{formatTimeOffset(sig.offset)}",
    }


def signatureQDateTime(signature: Signature, localTime=False) -> QDateTime:
    if localTime:
        return QDateTime.fromSecsSinceEpoch(signature.time)
    else:
        return QDateTime.fromSecsSinceEpoch(signature.time, QTimeZone(signature.offset * 60))


COMPACT_DATE_FORMAT = "compact"
"""
A short date format that says no more than it has to: "14:52" today,
"3 Sep 14:52" earlier this year, "2025-12-31" before that.
"""


def compactDateFormat(dateTime: QDateTime, now: QDateTime | None = None) -> str:
    """The QLocale date format that COMPACT_DATE_FORMAT stands for, for this date."""
    today = (now or QDateTime.currentDateTime()).date()
    date = dateTime.date()
    if date == today:
        return "HH:mm"
    if date.year() == today.year():
        return "d MMM HH:mm"
    return "yyyy-MM-dd"


def formatShortDate(dateTime: QDateTime, format: str, locale: QLocale | None = None, now: QDateTime | None = None) -> str:
    """Format a date with the user's short date format, which may be COMPACT_DATE_FORMAT."""
    if format == COMPACT_DATE_FORMAT:
        format = compactDateFormat(dateTime, now)
    return (locale or QLocale()).toString(dateTime, format)


def signatureDateFormat(
        signature: Signature,
        format: str | QLocale.FormatType = QLocale.FormatType.LongFormat,
        localTime=False
) -> str:
    dateTime = signatureQDateTime(signature, localTime)
    if isinstance(format, str):
        text = formatShortDate(dateTime, format)
    else:
        text = QLocale().toString(dateTime, format)
    if not localTime and format != QLocale.FormatType.LongFormat:
        text += f" ({formatTimeOffset(signature.offset)})"
    return text
