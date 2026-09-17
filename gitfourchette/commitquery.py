# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
The query behind the commit search box.

Plain words match the message or the author, as they always have. On top of
that, a word of the form ``key:value`` narrows the search down::

    author:alice                     commits by Alice
    after:2026-01-01                 committed on or after that day
    author:alice after:7d            both at once
    before:2025 after:2024           all of 2024

Only the keys below are qualifiers. Anything else - ``fix:`` in a conventional
commit message, say - is just text to look for.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta

AUTHOR_KEYS = frozenset({"author", "by"})
AFTER_KEYS = frozenset({"after", "since"})
BEFORE_KEYS = frozenset({"before", "until"})
QUALIFIER_KEYS = AUTHOR_KEYS | AFTER_KEYS | BEFORE_KEYS

_TOKEN_PATTERN = re.compile(r'[A-Za-z]+:"[^"]*"|"[^"]*"|\S+')
_QUALIFIER_PATTERN = re.compile(r'([a-z]+):(.*)', re.IGNORECASE)
_RELATIVE_PATTERN = re.compile(r'(\d+)\s*([dwmy])$')

_RELATIVE_UNITS = {"d": 1, "w": 7, "m": 30, "y": 365}

_PERIOD_FORMATS = [
    ("%Y-%m-%d %H:%M", "minute"),
    ("%Y-%m-%dT%H:%M", "minute"),
    ("%Y-%m-%d", "day"),
    ("%Y-%m", "month"),
    ("%Y", "year"),
]


def _periodBounds(value: str, now: datetime) -> tuple[int, int] | None:
    """
    The span of time a date means, as unix timestamps [start, end).

    A date is as precise as the user made it: "2026" is the whole year, and
    "2026-09-17" is that one day. A relative value such as "7d" is an instant.
    """

    value = value.strip().lower()

    if value in ("today", "yesterday"):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if value == "yesterday":
            start -= timedelta(days=1)
        return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())

    relative = _RELATIVE_PATTERN.match(value)
    if relative is not None:
        days = int(relative.group(1)) * _RELATIVE_UNITS[relative.group(2)]
        instant = int((now - timedelta(days=days)).timestamp())
        return instant, instant

    for fmt, unit in _PERIOD_FORMATS:
        try:
            start = datetime.strptime(value, fmt).astimezone()
        except ValueError:
            continue
        if unit == "minute":
            end = start + timedelta(minutes=1)
        elif unit == "day":
            end = start + timedelta(days=1)
        elif unit == "month":
            end = start.replace(year=start.year + start.month // 12, month=start.month % 12 + 1)
        else:
            end = start.replace(year=start.year + 1)
        return int(start.timestamp()), int(end.timestamp())

    return None


@dataclasses.dataclass(frozen=True)
class CommitQuery:
    text: str = ""
    "Free text to look for in the message or the author."

    authors: tuple[str, ...] = ()
    "Any one of these matching the author is enough."

    after: int = 0
    before: int = 0
    "Unix timestamps bounding the author date. 0 means unbounded."

    invalid: bool = False
    "Set when a qualifier was given a value we couldn't make sense of."

    def isEmpty(self) -> bool:
        return not (self.text or self.authors or self.after or self.before or self.invalid)

    @classmethod
    def parse(cls, term: str, now: datetime | None = None) -> CommitQuery:
        # A date the user types means a date in their own timezone
        now = (now or datetime.now(UTC)).astimezone()

        words = []
        authors = []
        after = 0
        before = 0
        invalid = False

        for token in _TOKEN_PATTERN.findall(term):
            match = _QUALIFIER_PATTERN.fullmatch(token)
            key = match.group(1).lower() if match is not None else ""

            if key not in QUALIFIER_KEYS:
                words.append(token.strip('"'))
                continue

            value = match.group(2).strip('"').strip()
            if not value:  # still being typed
                continue

            if key in AUTHOR_KEYS:
                authors.append(value.lower())
                continue

            bounds = _periodBounds(value, now)
            if bounds is None:
                invalid = True
            elif key in AFTER_KEYS:
                after = bounds[0]
            else:
                before = bounds[1]

        return cls(" ".join(words).lower(), tuple(authors), after, before, invalid)

    def matchesCommit(self, commit) -> bool:
        if self.invalid:
            return False

        author = commit.author

        if self.after and author.time < self.after:
            return False
        if self.before and author.time >= self.before:
            return False

        person = f"{author.name}\n{author.email}".lower()

        if self.authors and not any(a in person for a in self.authors):
            return False

        if self.text:
            return self.text in commit.message.lower() or self.text in person

        return True


@dataclasses.dataclass
class CommitQueryFilter:
    """The query the commit log is currently narrowed down to, if any."""

    query: CommitQuery = dataclasses.field(default_factory=CommitQuery)
    filterOnly: bool = False

    def wantFilter(self) -> bool:
        return self.filterOnly and not self.query.isEmpty()

    def clear(self):
        self.query = CommitQuery()
