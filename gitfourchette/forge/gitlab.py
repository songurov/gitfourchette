"""
GitLab's merge-request API, as request shapes and response readers.

Nothing here touches the network: a function returns the URL to call or the
payload to send, and another reads what came back. That keeps the protocol -
which is where the mistakes live - testable without a server, and leaves the
transport (and its error handling) in one place, in session.py.
"""

import dataclasses
import urllib.parse

from gitfourchette.exttools.aireview import Finding
from gitfourchette.forge.diffindex import DiffPosition, FileDiff, indexFileHunks
from gitfourchette.toolbox import splitRemoteUrl
from gitfourchette.webhost import identifyHost

MAX_MERGE_REQUESTS = 20


@dataclasses.dataclass(frozen=True)
class ForgeProject:
    host: str
    path: str
    "Namespace and name as the host spells them, e.g. 'external/vcrm-core'."

    @property
    def apiRoot(self) -> str:
        return f"https://{self.host}/api/v4"

    @property
    def encodedPath(self) -> str:
        # GitLab identifies a project either by number or by its full path with
        # every slash escaped; the path is what a remote URL gives us.
        return urllib.parse.quote(self.path, safe="")

    @property
    def mergeRequestsRoot(self) -> str:
        return f"{self.apiRoot}/projects/{self.encodedPath}/merge_requests"

    def mergeRequestRoot(self, iid: int) -> str:
        return f"{self.mergeRequestsRoot}/{int(iid)}"


@dataclasses.dataclass
class DiffRefs:
    baseSha: str = ""
    startSha: str = ""
    headSha: str = ""

    def isComplete(self) -> bool:
        return bool(self.baseSha and self.startSha and self.headSha)


@dataclasses.dataclass
class ChangeRequest:
    """One merge request, as much of it as we need to comment on it."""
    iid: int = 0
    title: str = ""
    sourceBranch: str = ""
    targetBranch: str = ""
    webUrl: str = ""
    draft: bool = False
    author: str = ""
    refs: DiffRefs = dataclasses.field(default_factory=DiffRefs)

    def caption(self) -> str:
        draft = "Draft: " if self.draft and not self.title.lower().startswith("draft") else ""
        return f"!{self.iid} {draft}{self.title}"


def projectFromRemote(remoteUrl: str) -> ForgeProject | None:
    """The GitLab project a remote URL points at, or None if it isn't one."""
    host, path = splitRemoteUrl(remoteUrl)
    if not host or not path:
        return None
    hostInfo = identifyHost(remoteUrl)
    if hostInfo is None or hostInfo.name != "GitLab":
        return None
    return ForgeProject(host.lower(), path.removesuffix(".git").strip("/"))


def openMergeRequestsUrl(project: ForgeProject, sourceBranch: str) -> str:
    query = urllib.parse.urlencode({
        "source_branch": sourceBranch, "state": "opened",
        "order_by": "updated_at", "per_page": MAX_MERGE_REQUESTS})
    return f"{project.mergeRequestsRoot}?{query}"


def readDiffRefs(payload: dict) -> DiffRefs:
    refs = payload.get("diff_refs") if isinstance(payload, dict) else None
    if not isinstance(refs, dict):
        return DiffRefs()
    return DiffRefs(str(refs.get("base_sha") or ""), str(refs.get("start_sha") or ""), str(refs.get("head_sha") or ""))


def readMergeRequest(payload: dict) -> ChangeRequest | None:
    if not isinstance(payload, dict) or not payload.get("iid"):
        return None
    author = payload.get("author")
    return ChangeRequest(
        iid=int(payload["iid"]),
        title=str(payload.get("title") or ""),
        sourceBranch=str(payload.get("source_branch") or ""),
        targetBranch=str(payload.get("target_branch") or ""),
        webUrl=str(payload.get("web_url") or ""),
        draft=bool(payload.get("draft") or payload.get("work_in_progress")),
        author=str(author.get("name") or "") if isinstance(author, dict) else "",
        refs=readDiffRefs(payload),
    )


def readMergeRequests(payload) -> list[ChangeRequest]:
    if not isinstance(payload, list):
        return []
    found = (readMergeRequest(item) for item in payload)
    return [mr for mr in found if mr is not None]


def looksLikeDiffHunk(suggestion: str) -> bool:
    """A pasted hunk rather than source: applying it would write the '+' into the file."""
    lines = [line for line in suggestion.splitlines() if line.strip()]
    return bool(lines) and all(line.lstrip().startswith(("+", "-")) for line in lines)


def canApplySuggestion(finding: Finding, position: DiffPosition) -> bool:
    """
    Whether the patch may be offered as a one-click GitLab suggestion.

    Four conditions, all necessary: there is a patch, it is source rather than a
    pasted hunk, the model was sure, and the anchor is an exact hit on a line
    this change adds. A snapped anchor is by definition not where the model
    thought it was, and replacing untouched context is a wider blast radius than
    a single finding earned. Anything short of that still ships the patch, as a
    read-only fence.
    """
    suggestion = finding.suggestion or ""
    return bool(suggestion.strip()
                and not looksLikeDiffHunk(suggestion)
                and finding.confidence == "high"
                and not position.snapped
                and not position.oldLine)


def discussionPayload(body: str, position: DiffPosition, refs: DiffRefs) -> dict:
    payload = {
        "body": body,
        "position": {
            "base_sha": refs.baseSha,
            "start_sha": refs.startSha,
            "head_sha": refs.headSha,
            "position_type": "text",
            "old_path": position.oldPath or position.newPath,
            "new_path": position.newPath,
            "new_line": position.newLine,
        },
    }
    # A context line exists on both sides, and GitLab rejects the position
    # unless old_line accompanies it.
    if position.oldLine:
        payload["position"]["old_line"] = position.oldLine
    return payload


def notePayload(body: str) -> dict:
    return {"body": body}


def discussionsUrl(project: ForgeProject, iid: int) -> str:
    return f"{project.mergeRequestRoot(iid)}/discussions"


def notesUrl(project: ForgeProject, iid: int) -> str:
    return f"{project.mergeRequestRoot(iid)}/notes"


DIFF_PAGE_SIZE = 20
"""Files per page of a merge request's diff. Small on purpose: asking a
GitLab 17.7 instance for 100 files of a 68-file merge request answered 500
Internal Server Error, while 20 came back fine."""


def mergeRequestDiffsUrl(project: ForgeProject, iid: int, page=1) -> str:
    query = urllib.parse.urlencode({"per_page": DIFF_PAGE_SIZE, "page": page})
    return f"{project.mergeRequestRoot(iid)}/diffs?{query}"


def mergeRequestChangesUrl(project: ForgeProject, iid: int) -> str:
    """
    The older endpoint that returns every changed file in one answer.

    Deprecated by GitLab in favour of /diffs, and still the one that works when
    /diffs fails on a big merge request.
    """
    return f"{project.mergeRequestRoot(iid)}/changes"


def readDiffIndex(payload, index: dict[str, FileDiff] | None = None) -> dict[str, FileDiff]:
    """The host's own diff, as the lines a comment may be anchored to."""
    index = {} if index is None else index
    if isinstance(payload, dict):  # /changes wraps the same entries
        payload = payload.get("changes")
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict) or entry.get("deleted_file"):
            continue
        indexFileHunks(index, str(entry.get("new_path") or ""),
                       str(entry.get("old_path") or ""), str(entry.get("diff") or ""))
    return index


def isFullDiffPage(payload) -> bool:
    """Whether another page of files may follow this one."""
    return isinstance(payload, list) and len(payload) >= DIFF_PAGE_SIZE
