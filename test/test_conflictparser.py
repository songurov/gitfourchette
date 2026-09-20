# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Reading the conflict markers that git leaves in a file (no Qt in here).
"""

from gitfourchette.mergeview.conflictparser import (
    MergeRegion, Side, hasConflictMarkers, parseConflicts, renderResolution, sideText)

PLAIN = """\
hello
<<<<<<< HEAD
our line
=======
their line
>>>>>>> feature/x
goodbye"""

DIFF3 = """\
hello
<<<<<<< HEAD
our line
||||||| 1234567
old line
=======
their line
>>>>>>> feature/x
goodbye"""


def testFileWithoutMarkersIsOneRegion():
    text = "a\nb\nc"
    assert not hasConflictMarkers(text)
    regions = parseConflicts(text)
    assert len(regions) == 1
    assert not regions[0].conflicted
    assert renderResolution(regions) == text


def testPlainMarkers():
    assert hasConflictMarkers(PLAIN)
    regions = parseConflicts(PLAIN)
    assert [r.conflicted for r in regions] == [False, True, False]
    conflict = regions[1]
    assert conflict.ours == ["our line"]
    assert conflict.theirs == ["their line"]
    assert conflict.base == []
    assert conflict.oursLabel == "HEAD"
    assert conflict.theirsLabel == "feature/x"
    # Nothing decided yet: saving now keeps the markers, so no side is lost
    assert renderResolution(regions) == PLAIN


def testDiff3MarkersKeepTheAncestor():
    regions = parseConflicts(DIFF3)
    conflict = regions[1]
    assert conflict.base == ["old line"]
    assert conflict.ours == ["our line"]
    assert conflict.theirs == ["their line"]
    assert renderResolution(regions) == DIFF3


def testEachChoiceRendersItsLines():
    def resolved(*choice):
        regions = parseConflicts(DIFF3)
        regions[1].choice = choice
        return renderResolution(regions)

    assert resolved(Side.Ours) == "hello\nour line\ngoodbye"
    assert resolved(Side.Theirs) == "hello\ntheir line\ngoodbye"
    assert resolved(Side.Base) == "hello\nold line\ngoodbye"
    assert resolved(Side.Ours, Side.Theirs) == "hello\nour line\ntheir line\ngoodbye"
    assert resolved(Side.Theirs, Side.Ours) == "hello\ntheir line\nour line\ngoodbye"


def testDroppingASideIsAChoiceToo():
    regions = parseConflicts(PLAIN)
    regions[1].choice = ()
    assert not regions[1].settled
    regions[1].choice = (Side.Ours,)
    assert regions[1].settled


def testEachSideReadsAsItsOwnFile():
    regions = parseConflicts(DIFF3)
    assert sideText(regions, Side.Ours) == "hello\nour line\ngoodbye"
    assert sideText(regions, Side.Theirs) == "hello\ntheir line\ngoodbye"
    assert sideText(regions, Side.Base) == "hello\nold line\ngoodbye"


def testSeveralConflictsInOneFile():
    text = PLAIN + "\n" + PLAIN
    regions = parseConflicts(text)
    conflicts = [r for r in regions if r.conflicted]
    assert len(conflicts) == 2


def testUnterminatedMarkerStaysText():
    # Better to show the file as it is than to drop what the person wrote
    text = "hello\n<<<<<<< HEAD\nour line\ngoodbye"
    regions = parseConflicts(text)
    assert [r.conflicted for r in regions] == [False]
    assert renderResolution(regions) == text


def testMarkerlessTextInsideAConflictIsKept():
    regions = parseConflicts(PLAIN)
    assert regions[0].ours == ["hello"]
    assert regions[2].ours == ["goodbye"]


def testEmptySideIsARealChoice():
    text = "a\n<<<<<<< HEAD\n=======\ntheir line\n>>>>>>> x\nb"
    regions = parseConflicts(text)
    conflict = regions[1]
    assert conflict.ours == []
    assert conflict.theirs == ["their line"]
    conflict.choice = (Side.Ours,)
    assert renderResolution(regions) == "a\nb"


def testRegionKnowsItsOwnLines():
    region = MergeRegion(ours=["x"], theirs=["y"], conflicted=True, choice=(Side.Theirs,))
    assert region.resolvedLines() == ["y"]
