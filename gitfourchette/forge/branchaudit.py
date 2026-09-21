"""
Which branches on a remote are still work, and which are just sediment.

A branch outlives its merge request. It is merged, or abandoned, or forgotten
with three commits nobody will finish, and it stays on the remote either way
until someone looks. This works out which is which from evidence rather than
from names: what the merge request says happened, whether the tip is already
contained in the base branch, how long ago anyone touched it.

Nothing here talks to a server or a repository; it is given the facts and
returns a verdict, so the rules can be read and tested in one place.
"""

import dataclasses
import datetime
import enum
from contextlib import suppress as _suppress


class Verdict(enum.StrEnum):
    Protected = "protected"
    "A long-lived branch of the project: never proposed for deletion."
    Active = "active"
    Merged = "merged"
    "Its work is in the base branch, by merge request or by merge."
    Abandoned = "abandoned"
    "Its merge request was closed without merging."
    Stale = "stale"
    "No merge request, nothing new for a long time."
    Unclear = "unclear"


# A branch someone pushed today is not sediment, whatever else is true of it.
ACTIVE_DAYS = 14
STALE_DAYS = 60


@dataclasses.dataclass
class BranchFacts:
    """Everything known about one remote branch, before any judgement."""
    name: str = ""
    "Shorthand as the remote spells it, e.g. 'origin/feature/songurov/VCRM-1'."
    author: str = ""
    lastCommit: datetime.datetime | None = None
    ahead: int = 0
    "Commits this branch has that the base branch doesn't."
    behind: int = 0
    containedInBase: bool = False
    "Its tip is an ancestor of the base branch: the work is already there."
    mergeRequest: int = 0
    mergeRequestState: str = ""
    "opened, merged, closed, or empty when there is none."
    protected: bool = False


@dataclasses.dataclass
class BranchVerdict:
    verdict: Verdict
    reason: str = ""
    deletable: bool = False
    "Whether this is safe to propose for deletion - never true on its own for unfinished work."


def ageInDays(facts: BranchFacts, now: datetime.datetime | None = None) -> int:
    if facts.lastCommit is None:
        return 0
    now = now or datetime.datetime.now(datetime.UTC)
    last = facts.lastCommit
    if last.tzinfo is None:
        last = last.replace(tzinfo=datetime.UTC)
    return max(0, (now - last).days)


def judge(facts: BranchFacts, now: datetime.datetime | None = None) -> BranchVerdict:
    """
    What to do about this branch, and why - in that order of certainty.

    A merged merge request is the strongest evidence there is: it survives a
    squash, which "is the tip an ancestor of the base" does not. Containment in
    the base branch is next. Only then does age get a say, and age alone never
    makes something deletable - a branch nobody touched for a year may still be
    the only copy of work someone means to finish.
    """
    days = ageInDays(facts, now)

    if facts.protected:
        return BranchVerdict(Verdict.Protected, ("a long-lived branch of this project"))

    if facts.mergeRequestState == "merged":
        return BranchVerdict(Verdict.Merged, (
            f"merged in !{facts.mergeRequest}"), deletable=True)

    if facts.containedInBase:
        return BranchVerdict(Verdict.Merged, (
            "its commits are already in the base branch"), deletable=True)

    if facts.mergeRequestState == "opened":
        return BranchVerdict(Verdict.Active, (
            f"merge request !{facts.mergeRequest} is open"))

    if facts.mergeRequestState == "closed":
        return BranchVerdict(Verdict.Abandoned, (
            f"!{facts.mergeRequest} was closed without merging, {days} days ago"
            if days else f"!{facts.mergeRequest} was closed without merging"),
            deletable=days >= ACTIVE_DAYS)

    if days <= ACTIVE_DAYS:
        return BranchVerdict(Verdict.Active, (f"touched {days} days ago"))

    if days >= STALE_DAYS:
        return BranchVerdict(Verdict.Stale, (
            f"no merge request, nothing new for {days} days, {facts.ahead} commits not in the base branch"))

    return BranchVerdict(Verdict.Unclear, (
        f"no merge request, last touched {days} days ago"))




# --- Gathering the facts -----------------------------------------------------

LONG_LIVED = ("develop", "main", "master", "prod", "production", "uat", "test",
              "integration", "beta", "staging", "release")


def baseBranchOf(repo, remoteName: str) -> str:
    """The branch this remote's work is measured against."""
    names = set(repo.branches.remote)
    for candidate in ("develop", "main", "master"):
        if f"{remoteName}/{candidate}" in names:
            return f"{remoteName}/{candidate}"
    return ""


def isLongLived(shorthand: str) -> bool:
    _remote, _slash, name = shorthand.partition("/")
    return name.lower() in LONG_LIVED


def collectFacts(repo, remoteName: str, mergeRequests: dict | None = None, baseBranch="") -> list[BranchFacts]:
    """
    One BranchFacts per branch on this remote.

    `mergeRequests` maps a source branch name to (iid, state), as the host
    reported it; without it the verdicts fall back to what the repository alone
    can show, which cannot see a squashed merge.
    """
    import datetime as _datetime

    mergeRequests = mergeRequests or {}
    baseBranch = baseBranch or baseBranchOf(repo, remoteName)
    baseTip = None
    if baseBranch:
        with _suppress(KeyError, ValueError):
            baseTip = repo.branches.remote[baseBranch].target

    collected = []
    for shorthand in sorted(repo.branches.remote):
        if not shorthand.startswith(remoteName + "/") or shorthand.endswith("/HEAD"):
            continue
        with _suppress(KeyError, ValueError):
            branch = repo.branches.remote[shorthand]
            commit = repo[branch.target]
            when = _datetime.datetime.fromtimestamp(commit.commit_time, _datetime.UTC)
            ahead = behind = 0
            if baseTip is not None and branch.target != baseTip:
                ahead, behind = repo.ahead_behind(branch.target, baseTip)
            sourceBranch = shorthand[len(remoteName) + 1:]
            iid, state = mergeRequests.get(sourceBranch, (0, ""))
            collected.append(BranchFacts(
                name=shorthand,
                author=commit.author.name,
                lastCommit=when,
                ahead=ahead,
                behind=behind,
                containedInBase=baseTip is not None and branch.target != baseTip and ahead == 0,
                mergeRequest=iid,
                mergeRequestState=state,
                protected=shorthand == baseBranch or isLongLived(shorthand),
            ))
    return collected


def readMergeRequestIndex(payload, index: dict | None = None) -> dict:
    """
    Source branch -> (iid, state), from a page of merge requests.

    Pages arrive newest first, so the first mention of a branch is its latest
    merge request, and that is the one that says what happened to it.
    """
    index = {} if index is None else index
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source_branch") or "")
        if source and source not in index:
            index[source] = (int(entry.get("iid") or 0), str(entry.get("state") or ""))
    return index
