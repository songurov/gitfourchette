# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
The conflict markers that git leaves in a file, as regions a person can decide
on one at a time. No Qt in here: MergeEditor puts these regions on screen.
"""

from __future__ import annotations

import dataclasses
import enum

MARKER_SIZE = 7
OURS_MARKER = "<" * MARKER_SIZE
BASE_MARKER = "|" * MARKER_SIZE
MIDDLE_MARKER = "=" * MARKER_SIZE
THEIRS_MARKER = ">" * MARKER_SIZE


class Side(enum.StrEnum):
    Ours = "ours"
    Theirs = "theirs"
    Base = "base"


@dataclasses.dataclass
class MergeRegion:
    """
    A run of lines in a conflicted file: either text both sides agree on, or a
    passage each side wrote differently.
    """

    ours: list[str]
    theirs: list[str]
    base: list[str] = dataclasses.field(default_factory=list)
    conflicted: bool = False
    oursLabel: str = ""
    baseLabel: str = ""
    theirsLabel: str = ""
    choice: tuple[Side, ...] = ()
    "Which sides to keep, in this order. Empty with decided means: neither."

    decided: bool = False
    "Whether someone has settled this conflict."

    @property
    def settled(self) -> bool:
        return not self.conflicted or self.decided

    def decide(self, *sides: Side):
        """Keep these sides, in this order; none of them is a decision too."""
        self.choice = sides
        self.decided = True

    def sideLines(self, side: Side) -> list[str]:
        return {Side.Ours: self.ours, Side.Theirs: self.theirs, Side.Base: self.base}[side]

    def resolvedLines(self) -> list[str]:
        """The lines this region contributes to the merged file."""
        if not self.conflicted:
            return self.ours
        lines = []
        for side in self.choice:
            lines += self.sideLines(side)
        return lines

    def markedUpLines(self) -> list[str]:
        """The region as git wrote it, markers and all, for a conflict left open."""
        lines = [f"{OURS_MARKER} {self.oursLabel}".rstrip(), *self.ours]
        if self.base or self.baseLabel:
            lines += [f"{BASE_MARKER} {self.baseLabel}".rstrip(), *self.base]
        lines += [MIDDLE_MARKER, *self.theirs, f"{THEIRS_MARKER} {self.theirsLabel}".rstrip()]
        return lines


def hasConflictMarkers(text: str) -> bool:
    return any(line.startswith(OURS_MARKER) for line in text.splitlines())


def parseConflicts(text: str) -> list[MergeRegion]:
    """
    Split a conflicted file into regions. Reads the plain markers as well as
    the diff3 and zdiff3 styles, which add the common ancestor.

    Markers that don't pair up are left as ordinary text: better to show the
    file as it is than to drop a line the person wrote.
    """
    regions: list[MergeRegion] = []
    common: list[str] = []
    lines = text.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith(OURS_MARKER):
            common.append(line)
            i += 1
            continue

        region = _parseOneConflict(lines, i)
        if region is None:  # unterminated marker: plain text after all
            common.append(line)
            i += 1
            continue

        region, i = region
        if common:
            regions.append(MergeRegion(ours=common, theirs=list(common)))
            common = []
        regions.append(region)

    if common:
        regions.append(MergeRegion(ours=common, theirs=list(common)))
    return regions


def _parseOneConflict(lines: list[str], start: int) -> tuple[MergeRegion, int] | None:
    ours: list[str] = []
    base: list[str] = []
    theirs: list[str] = []
    current = ours
    baseLabel = ""
    sawBase = False
    sawMiddle = False

    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.startswith(OURS_MARKER):  # a nested start: this one isn't a conflict
            return None
        if line.startswith(BASE_MARKER) and not sawMiddle:
            current = base
            sawBase = True
            baseLabel = line[MARKER_SIZE:].strip()
        elif line.startswith(MIDDLE_MARKER) and line.strip() == MIDDLE_MARKER:
            current = theirs
            sawMiddle = True
        elif line.startswith(THEIRS_MARKER):
            if not sawMiddle:
                return None
            region = MergeRegion(
                ours=ours, theirs=theirs, base=base, conflicted=True,
                oursLabel=lines[start][MARKER_SIZE:].strip(),
                baseLabel=baseLabel if sawBase else "",
                theirsLabel=line[MARKER_SIZE:].strip())
            return region, i + 1
        else:
            current.append(line)
        i += 1

    return None


def renderResolution(regions: list[MergeRegion]) -> str:
    """
    The merged file as it stands. A conflict nobody has decided on yet keeps
    its markers, so saving early never quietly drops one side.
    """
    lines: list[str] = []
    for region in regions:
        if region.conflicted and not region.settled:
            lines += region.markedUpLines()
        else:
            lines += region.resolvedLines()
    return "\n".join(lines)


def sideText(regions: list[MergeRegion], side: Side) -> str:
    """One side's whole file, as it reads on its own."""
    lines: list[str] = []
    for region in regions:
        lines += region.sideLines(side) if region.conflicted else region.ours
    return "\n".join(lines)
