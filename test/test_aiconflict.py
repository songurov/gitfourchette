"""Asking an assistant to settle merge conflicts, and what is done with its answer."""

import json
import sys

from gitfourchette.exttools import aiconflict
from gitfourchette.mergeview.conflictparser import Side, parseConflicts
from gitfourchette.mergeview.mergeeditor import MergeEditor
from gitfourchette.qt import *
from .util import *

CONFLICTED = """head
<<<<<<< ours
from ark import Bird
=======
from ark import Fish
>>>>>>> theirs
middle
<<<<<<< ours
speed = 3
=======
speed = 4
>>>>>>> theirs
tail
"""


def testItAsksAboutEveryOpenConflictWithItsContext():
    regions = parseConflicts(CONFLICTED)
    indices = aiconflict.resolvableRegions(regions)
    assert len(indices) == 2

    payload = aiconflict.regionPayload(regions, indices[0])
    assert payload["index"] == indices[0]
    assert payload["ours"] == ["from ark import Bird"]
    assert payload["theirs"] == ["from ark import Fish"]
    # A little of the agreed text travels with it: that is what makes the
    # passage readable, and it stops at the next conflict
    assert payload["before"] == ["head"]
    assert payload["after"] == ["middle"]

    prompt = aiconflict.makeConflictPrompt("src/a.py", regions, indices, oursLabel="develop",
                                           theirsLabel="feature")
    assert "src/a.py" in prompt
    assert "develop" in prompt and "feature" in prompt
    assert "from ark import Fish" in prompt
    # The permission to give up is the honest half of the instructions
    assert "LEAVE IT OUT" in prompt


def testAConflictTooBigToSettleIsNotAskedAbout(monkeypatch):
    monkeypatch.setattr(aiconflict, "MAX_REGION_LINES", 1)
    regions = parseConflicts(CONFLICTED)
    regions[1].theirs = ["a", "b", "c"]
    assert 1 not in aiconflict.resolvableRegions(regions)


def testSettledConflictsAreReadBackCarefully():
    allowed = {0, 1}
    answer = json.dumps({"resolutions": [
        {"index": 0, "lines": ["from ark import Bird, Fish"], "why": "both imports are used"},
        {"index": 0, "lines": ["duplicate"], "why": "answered twice"},
        {"index": 1, "lines": ["<<<<<<< ours", "speed = 4"], "why": "left a marker in"},
        {"index": 9, "lines": ["not a conflict we asked about"]},
        {"index": 1, "lines": [3, 4]},
        "not an object",
    ]})
    settled = aiconflict.parseResolutions(answer, allowed)

    assert list(settled) == [0]
    assert settled[0] == (["from ark import Bird, Fish"], "both imports are used")


def testAnAnswerThatIsNotAReviewIsNoAnswer():
    assert aiconflict.parseResolutions("I couldn't do it", {0}) == {}
    assert aiconflict.parseResolutions('{"something": "else"}', {0}) == {}
    # Fenced and chatty still counts, because that is how they answer
    fenced = "Sure:\n```json\n" + json.dumps({"resolutions": [{"index": 0, "lines": ["x"]}]}) + "\n```"
    assert aiconflict.parseResolutions(fenced, {0}) == {0: (["x"], "")}


def testTheEditorTakesWhatItProposesAsAnOrdinaryDecision(tempDir, mainWindow, monkeypatch):
    from gitfourchette.exttools import aichat

    answer = {"resolutions": [{"index": 0, "lines": ["from ark import Bird, Fish"],
                               "why": "both imports are used below"}]}
    code = ("import sys, json\n"
            "sys.stdin.read()\n"
            f"print(json.dumps({{'type': 'item.completed', 'item': {{'id': '1', 'type': 'agent_message', "
            f"'text': {json.dumps(json.dumps(answer))}}}}}))\n")
    monkeypatch.setattr(aichat, "availableProviders", lambda: {"codex": sys.executable})
    monkeypatch.setattr(aichat, "cliArguments", lambda *args, **kwargs: ["-c", code])

    editor = MergeEditor("src/a.py", CONFLICTED, parent=mainWindow)
    editor.show()
    assert editor.aiButton.isEnabled()

    editor.askAi()
    waitUntilTrue(lambda: editor.aiProcess is None)

    conflicts = editor.conflicts
    assert conflicts[0].settled
    assert conflicts[0].custom == ["from ark import Bird, Fish"]
    # It is a decision like any other: overrulable, and its reason is shown
    assert conflicts[0].reason == "both imports are used below"
    assert not conflicts[1].settled

    # What it settled is in the result, and the file still isn't written
    assert "from ark import Bird, Fish" in editor.resolution()
    assert "<<<<<<<" in editor.resolution()  # the conflict it left alone

    editor.goToConflict(0)
    editor.chooseHere((Side.Ours,))
    assert conflicts[0].custom is None and conflicts[0].reason == ""
    editor.reject()
