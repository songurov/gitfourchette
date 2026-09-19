# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import urllib.parse

from gitfourchette.toolbox import *


HTTPS_PORT = 443


@dataclasses.dataclass
class WebHost:
    name: str
    branchPrefix: str
    port: int = HTTPS_PORT
    icon: str = ""
    """Stock icon for the hosting service, if we have a mark for it."""

    @staticmethod
    def makeLink(remoteUrl: str, branch: str = ""):
        host, path = splitRemoteUrl(remoteUrl)

        if not host:
            return "", ""

        path = path.removesuffix(".git")

        try:
            hostInfo = WEB_HOSTS[host]
            hostName = hostInfo.name
        except KeyError:
            hostInfo = WEB_HOSTS["github.com"]  # fall back to GitHub's scheme
            hostName = host

        port = "" if hostInfo.port == HTTPS_PORT else f":{hostInfo.port}"
        suffix = ""

        if branch:
            suffix = hostInfo.branchPrefix + urllib.parse.quote(branch, safe='/')

        return f"https://{host}{port}/{path}{suffix}", hostName

    @staticmethod
    def makeChangeRequestLink(remoteUrl: str, branch: str, title="", body=""):
        host, path = splitRemoteUrl(remoteUrl)
        hostInfo = identifyHost(remoteUrl)
        if not host or not hostInfo or hostInfo.name not in ("GitHub", "GitLab"):
            return "", ""
        path = path.removesuffix(".git")
        port = "" if hostInfo.port == HTTPS_PORT else f":{hostInfo.port}"
        root = f"https://{host}{port}/{path}"
        if hostInfo.name == "GitHub":
            url = root + "/pull/new/" + urllib.parse.quote(branch, safe="/")
            query = {"expand": "1"}
            if title:
                query["title"] = title
            if body:
                query["body"] = body
        else:
            url = root + "/-/merge_requests/new"
            query = {"merge_request[source_branch]": branch}
            if title:
                query["merge_request[title]"] = title
            if body:
                query["merge_request[description]"] = body
        return url + "?" + urllib.parse.urlencode(query), hostInfo.name


WEB_HOSTS = {
    "github.com": WebHost("GitHub", "/tree/", icon="host-github"),
    "gitlab.com": WebHost("GitLab", "/-/tree/", icon="host-gitlab"),
    "git.sr.ht": WebHost("Sourcehut", "/tree/"),
    "codeberg.org": WebHost("Codeberg", "/src/branch/", icon="host-codeberg"),
    "git.launchpad.net": WebHost("Launchpad", "/log?h="),
    "bitbucket.org": WebHost("Bitbucket", "/src/", icon="host-bitbucket"),
}

SELF_HOSTED_HINTS = {
    "gitlab": "gitlab.com",
    "github": "github.com",
    "bitbucket": "bitbucket.org",
}
"""A self-hosted instance usually says so in its hostname (gitlab.example.com),
which is as far as we can go without talking to the server."""


def identifyHost(remoteUrl: str) -> WebHost | None:
    """Which hosting service a remote URL points to, if we recognize it."""

    host, _path = splitRemoteUrl(remoteUrl)
    if not host:
        return None

    try:
        return WEB_HOSTS[host]
    except KeyError:
        pass

    host = host.lower()
    for hint, knownHost in SELF_HOSTED_HINTS.items():
        if hint in host:
            return WEB_HOSTS[knownHost]

    return None
