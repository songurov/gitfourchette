# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

from gitfourchette.commitquery import CommitQuery
from .util import *

# Last: util's star import pulls in the datetime *module*, which would
# otherwise shadow the class
from datetime import UTC, datetime

NOW = datetime.fromisoformat("2026-09-17T12:00").astimezone()


@dataclasses.dataclass
class FakeCommit:
    message: str = "hello"
    author: Signature = None

    def __post_init__(self):
        if self.author is None:
            self.author = Signature("A U Thor", "a.u.thor@example.com", 1600000000, 0)


def parse(term):
    return CommitQuery.parse(term, NOW)


def stamp(timestamp, fmt="%Y-%m-%d %H:%M"):
    """A timestamp back in the local timezone, which is how the user typed it."""
    return datetime.fromtimestamp(timestamp, UTC).astimezone().strftime(fmt)


def testPlainWordsAreJustText():
    query = parse("fix the thing")
    assert query.text == "fix the thing"
    assert not query.authors
    assert not query.after and not query.before
    assert not query.isEmpty()

    # A conventional commit prefix is not a qualifier
    assert parse("fix: the thing").text == "fix: the thing"

    assert parse("").isEmpty()
    assert parse("   ").isEmpty()


def testAuthorQualifier():
    assert parse("author:alice").authors == ("alice",)
    assert parse("by:alice").authors == ("alice",)
    assert parse('author:"A U Thor"').authors == ("a u thor",)
    assert parse("author:alice author:bob").authors == ("alice", "bob")

    # Text and qualifiers mix
    query = parse('author:alice bug')
    assert query.authors == ("alice",) and query.text == "bug"

    # Half-typed qualifier doesn't narrow anything down yet
    assert parse("author:").isEmpty()


def testDateQualifiers():
    def bounds(term):
        query = parse(term)
        return query.after, query.before

    year, _ = bounds("after:2024")
    assert stamp(year, "%Y-%m-%d %H:%M") == "2024-01-01 00:00"

    _, month = bounds("before:2024-02")
    assert stamp(month, "%Y-%m-%d %H:%M") == "2024-03-01 00:00"

    day, _ = bounds("since:2024-02-29")
    assert stamp(day, "%Y-%m-%d %H:%M") == "2024-02-29 00:00"

    _, minute = bounds("until:2024-02-29T13:45")
    assert stamp(minute, "%Y-%m-%d %H:%M") == "2024-02-29 13:46"
    assert bounds('until:"2024-02-29 13:45"')[1] == minute, "a space needs quotes"

    # Relative values are an instant, not a period
    week, _ = bounds("after:1w")
    assert stamp(week, "%Y-%m-%d") == "2026-09-10"
    assert bounds("after:7d")[0] == week
    assert stamp(bounds("after:1m")[0], "%Y-%m-%d") == "2026-08-18"
    assert stamp(bounds("after:1y")[0], "%Y-%m-%d") == "2025-09-17"

    today, _ = bounds("after:today")
    assert stamp(today, "%Y-%m-%d %H:%M") == "2026-09-17 00:00"
    assert stamp(bounds("after:yesterday")[0], "%Y-%m-%d") == "2026-09-16"


def testUnreadableDateMakesTheQueryInvalid():
    query = parse("after:whenever")
    assert query.invalid
    assert not query.isEmpty(), "an invalid query is not an empty one"
    assert not query.matchesCommit(FakeCommit())


def testMatching():
    alice = Signature("Alice Liddell", "alice@example.com", 1600000000, 0)  # 2020-09-13
    bob = Signature("Bob Marley", "bob@example.com", 1700000000, 0)  # 2023-11-14

    aliceCommit = FakeCommit("Fix the rabbit hole", alice)
    bobCommit = FakeCommit("Add three little birds", bob)

    assert parse("rabbit").matchesCommit(aliceCommit)
    assert not parse("rabbit").matchesCommit(bobCommit)

    # Free text still matches the author, as it always has
    assert parse("liddell").matchesCommit(aliceCommit)
    assert parse("alice@example").matchesCommit(aliceCommit)

    assert parse("author:alice").matchesCommit(aliceCommit)
    assert not parse("author:alice").matchesCommit(bobCommit)
    assert parse("author:alice author:bob").matchesCommit(bobCommit), "several authors mean any of them"

    assert parse("after:2023").matchesCommit(bobCommit)
    assert not parse("after:2023").matchesCommit(aliceCommit)
    assert parse("before:2021").matchesCommit(aliceCommit)
    assert not parse("before:2021").matchesCommit(bobCommit)

    # Qualifiers narrow each other down
    assert parse("author:bob after:2023").matchesCommit(bobCommit)
    assert not parse("author:bob after:2024").matchesCommit(bobCommit)
    assert not parse("author:alice after:2023").matchesCommit(bobCommit)
    assert parse("author:bob birds").matchesCommit(bobCommit)
    assert not parse("author:bob rabbit").matchesCommit(bobCommit)

    # An empty query matches anything (nothing to narrow down)
    assert parse("").matchesCommit(aliceCommit)
