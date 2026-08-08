#!/usr/bin/env python3
"""Fail-closed GitHub SSH transport helpers for V2.62.

The helpers only validate identities and construct argv.  They never execute
Git, ``gh``, or a network operation.
"""

from __future__ import annotations

import re
from typing import Any


SCP_REMOTE_RE = re.compile(
    r"^git@github\.com:(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$"
)
URI_REMOTE_RE = re.compile(
    r"^ssh://git@github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$"
)
REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REFSPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]*$")


def validate_github_ssh_remote(remote_url: object) -> dict[str, Any]:
    """Accept GitHub SSH remotes and reject every HTTPS/file fallback."""

    if not isinstance(remote_url, str):
        return {
            "ok": False,
            "passed": False,
            "error_code": "E_V250_GITHUB_SSH_REMOTE",
        }
    match = SCP_REMOTE_RE.fullmatch(remote_url) or URI_REMOTE_RE.fullmatch(remote_url)
    if match is None:
        return {
            "ok": False,
            "passed": False,
            "error_code": "E_V250_GITHUB_SSH_ONLY",
            "remote_url": remote_url,
            "https_fallback_allowed": False,
        }
    owner = match.group("owner")
    repository = match.group("repo")
    return {
        "ok": True,
        "passed": True,
        "error_code": None,
        "transport": "ssh",
        "host": "github.com",
        "repository": f"{owner}/{repository}",
        "canonical_remote": f"git@github.com:{owner}/{repository}.git",
        "https_fallback_allowed": False,
    }


def require_github_ssh_remote(remote_url: object) -> dict[str, Any]:
    verdict = validate_github_ssh_remote(remote_url)
    if not verdict["ok"]:
        raise ValueError(str(verdict["error_code"]))
    return verdict


def build_push_argv(remote_name: str, refspec: str) -> list[str]:
    """Construct a fixed Git push argv after option-injection validation."""

    if REMOTE_NAME_RE.fullmatch(remote_name) is None:
        raise ValueError("E_V250_GIT_REMOTE_NAME")
    if REFSPEC_RE.fullmatch(refspec) is None or refspec.startswith("-"):
        raise ValueError("E_V250_GIT_REFSPEC")
    return ["git", "push", remote_name, refspec]


def github_operation_surface(operation: str) -> str:
    """Keep Git payload transport separate from GitHub API control surfaces."""

    if operation in {"fetch", "push_branch", "push_tag"}:
        return "git_ssh"
    if operation in {
        "create_pull_request",
        "read_actions",
        "read_ruleset",
        "create_release",
        "read_release",
    }:
        return "github_api_cli"
    raise ValueError("E_V250_GITHUB_OPERATION")
