#!/usr/bin/env python3
"""Authenticated, fail-closed GitHub adapter for the V2.40 release engine.

This module is internal.  ``release.py`` is the only public entry and is
responsible for persisting an operation intent before calling this adapter.
The adapter never accepts arbitrary commands: every mutation maps to one
fixed Git/GitHub operation and every call requires an exact expected-before
record plus the frozen release identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlparse


SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GITHUB_HOST = "github.com"
FIXED_REPOSITORY = "vibe-coding-era/goal-teams"
FIXED_REPOSITORY_ID = 1249985345
AUTHORIZED_ACTIONS = [
    "read_repository",
    "read_refs",
    "read_workflows",
    "read_releases",
    "read_rulesets",
    "enable_immutable_releases",
    "manage_promotion_ruleset",
    "manage_tag_ruleset",
    "push_candidate",
    "push_tag",
    "promote_main",
    "create_release_draft",
    "upload_release_assets",
    "publish_release",
    "dispatch_workflow",
]
WRITE_ACTIONS = {
    "immutable_release_enable",
    "tag_ruleset_create",
    "promotion_lock_create",
    "candidate_push",
    "tag_push",
    "draft_create",
    "asset_upload",
    "main_promote",
    "release_publish",
    "post_release_ci",
    "promotion_lock_finalize",
}
ASSET_BY_OPERATION = {
    "CP16.asset_upload_tar": "goal-teams-{version}.tar.gz",
    "CP16.asset_upload_sums": "SHA256SUMS",
    "CP16.asset_upload_release": "_release.json",
    "CP16.asset_upload_files": "_files.sha256",
}
CANONICAL_RELEASE_TITLE = "Goal Teams V2.40"
CANONICAL_RELEASE_BODY = (
    "Goal Teams V2.40. See release/current/README.md in the tagged source."
)
CANONICAL_TAG_MESSAGE = "Goal Teams V2.40"


def _git_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _git_argv(argv: Sequence[str]) -> list[str]:
    values = list(argv)
    if values and Path(values[0]).name == "git":
        values.insert(1, "--no-replace-objects")
    return values


def _require_github_dot_com_host() -> None:
    configured = os.environ.get("GH_HOST")
    if configured not in {None, "", GITHUB_HOST}:
        _fail(
            "E_V240_GITHUB_HOST_BINDING",
            "GH_HOST must be empty or exactly github.com",
        )


def _canonical_repository_url(value: str, repository: str) -> str | None:
    """Normalize only the fixed github.com HTTPS/SSH repository URLs."""

    scp = re.fullmatch(r"git@github\.com:([^?#]+?)(?:\.git)?/?", value)
    if scp is not None:
        path = scp.group(1)
    else:
        parsed = urlparse(value)
        try:
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme not in {"https", "ssh"}
            or parsed.hostname != GITHUB_HOST
            or port is not None
            or parsed.query
            or parsed.fragment
            or parsed.params
            or (parsed.scheme == "ssh" and parsed.username != "git")
            or (parsed.scheme == "https" and parsed.username is not None)
        ):
            return None
        path = parsed.path.lstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
    if path.endswith(".git"):
        path = path[:-4]
    if path != repository:
        return None
    return f"{GITHUB_HOST}/{repository}"


def _git_config_values(
    source_root: Path, argv: Sequence[str], *, allow_missing: bool = False
) -> list[str]:
    result = subprocess.run(
        _git_argv(("git", *argv)),
        cwd=source_root,
        env=_git_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    if allow_missing and result.returncode == 1:
        return []
    if result.returncode != 0:
        _fail(
            "E_V240_GITHUB_TRANSPORT_BINDING",
            f"cannot inspect Git transport ({' '.join(argv)})",
        )
    return [line for line in result.stdout.splitlines() if line]


def validate_github_transport(
    source_root: Path, repository: str
) -> dict[str, Any]:
    """Bind raw/resolved origin URLs and reject every Git URL rewrite."""

    _require_github_dot_com_host()
    if repository != FIXED_REPOSITORY:
        _fail(
            "E_V240_GITHUB_REPOSITORY_BINDING",
            "release adapter repository is not the fixed GitHub repository",
        )
    root = source_root.resolve()
    rewrites = _git_config_values(
        root,
        ("config", "--show-origin", "--get-regexp", r"^url\."),
        allow_missing=True,
    )
    if any(
        ".insteadof" in line.lower() or ".pushinsteadof" in line.lower()
        for line in rewrites
    ):
        _fail(
            "E_V240_GITHUB_URL_REWRITE",
            "Git url.*.insteadOf/pushInsteadOf is forbidden for release",
        )
    raw_fetch = _git_config_values(
        root, ("config", "--get-all", "remote.origin.url")
    )
    raw_push_configured = _git_config_values(
        root,
        ("config", "--get-all", "remote.origin.pushurl"),
        allow_missing=True,
    )
    raw_push = raw_push_configured or list(raw_fetch)
    resolved_fetch = _git_config_values(
        root, ("remote", "get-url", "--all", "origin")
    )
    resolved_push = _git_config_values(
        root, ("remote", "get-url", "--push", "--all", "origin")
    )
    expected = f"{GITHUB_HOST}/{repository}"
    groups = {
        "raw_fetch_urls": raw_fetch,
        "raw_push_urls": raw_push,
        "resolved_fetch_urls": resolved_fetch,
        "resolved_push_urls": resolved_push,
    }
    for label, values in groups.items():
        if len(values) != 1 or _canonical_repository_url(values[0], repository) != expected:
            _fail(
                "E_V240_GITHUB_TRANSPORT_BINDING",
                f"{label} is not the single fixed github.com repository URL",
            )
    receipt = {
        "api_host": GITHUB_HOST,
        "repository": repository,
        **groups,
        "pushurl_configured": bool(raw_push_configured),
        "url_rewrite_count": 0,
    }
    receipt["origin_binding_sha256"] = _canonical_sha256(receipt)
    return receipt


class AdapterError(RuntimeError):
    """Adapter failure carrying a machine-readable, conservative receipt."""

    def __init__(self, error_code: str, message: str, **details: Any) -> None:
        receipt: dict[str, Any] = {
            "passed": False,
            "error_code": error_code,
            "mutation_count": 0,
            "external_side_effect_count": 0,
        }
        receipt.update(details)
        self.receipt = receipt
        super().__init__(f"{error_code}: {message}")


def _fail(error_code: str, message: str, **details: Any) -> None:
    raise AdapterError(error_code, message, **details)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_ruleset(value: Mapping[str, Any]) -> dict[str, Any]:
    """Project POST/GET rulesets onto the caller-controlled policy fields.

    GitHub GET responses add server-owned fields such as ``id``, ``source``
    and timestamps.  They are evidence, but cannot be part of the create CAS
    identity because they do not exist in the submitted payload.
    """

    if not isinstance(value, Mapping):
        _fail("E_V240_RULESET_IDENTITY", "ruleset is not an object")
    required = ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")
    if any(field not in value for field in required):
        _fail("E_V240_RULESET_IDENTITY", "ruleset lacks a controlled field")
    bypass = value.get("bypass_actors")
    rules = value.get("rules")
    conditions = value.get("conditions")
    if not isinstance(bypass, list) or not isinstance(rules, list) or not isinstance(conditions, Mapping):
        _fail("E_V240_RULESET_IDENTITY", "ruleset controlled fields are malformed")
    normalized_bypass: list[dict[str, Any]] = []
    for record in bypass:
        if not isinstance(record, Mapping):
            _fail("E_V240_RULESET_IDENTITY", "ruleset bypass actor is malformed")
        normalized_bypass.append(
            {
                key: record[key]
                for key in ("actor_id", "actor_type", "bypass_mode")
                if key in record
            }
        )
    normalized_rules: list[dict[str, Any]] = []
    for record in rules:
        if not isinstance(record, Mapping) or "type" not in record:
            _fail("E_V240_RULESET_IDENTITY", "ruleset rule is malformed")
        normalized_rules.append(
            {key: record[key] for key in ("type", "parameters") if key in record}
        )
    normalized_bypass.sort(key=lambda item: _canonical_bytes(item))
    normalized_rules.sort(key=lambda item: _canonical_bytes(item))
    return {
        "name": value["name"],
        "target": value["target"],
        "enforcement": value["enforcement"],
        "bypass_actors": normalized_bypass,
        "conditions": json.loads(json.dumps(conditions)),
        "rules": normalized_rules,
    }


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = _git_argv(argv)
    merged = (
        _git_environment()
        if command and Path(command[0]).name == "git"
        else os.environ.copy()
    )
    if env:
        merged.update(env)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(
            "E_V240_ADAPTER_COMMAND",
            f"fixed adapter command failed ({argv[0]} rc={result.returncode})",
            stderr=result.stderr[-2000:],
        )
    return result


class GitHubAdapter:
    """Perform exact GitHub readback and explicitly authorized mutations."""

    def __init__(
        self,
        *,
        source_root: Path,
        workspace_root: Path,
        repository: str,
        version: str,
        candidate_commit: str,
        base_main_commit: str,
        authority: Mapping[str, Any],
        execute_external_writes: bool,
    ) -> None:
        if REPOSITORY_RE.fullmatch(repository) is None or repository != FIXED_REPOSITORY:
            _fail("E_V240_ADAPTER_IDENTITY", "invalid repository identity")
        if VERSION_RE.fullmatch(version) is None:
            _fail("E_V240_ADAPTER_IDENTITY", "invalid version identity")
        if SHA40_RE.fullmatch(candidate_commit) is None or SHA40_RE.fullmatch(
            base_main_commit
        ) is None:
            _fail("E_V240_ADAPTER_IDENTITY", "invalid frozen Git identity")
        self.source_root = source_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.repository = repository
        self.host_repository = f"{GITHUB_HOST}/{repository}"
        self.version = version
        self.tag = f"v{version[1:]}"
        self.candidate_commit = candidate_commit
        self.base_main_commit = base_main_commit
        self.authority = dict(authority)
        self.execute_external_writes = execute_external_writes

    def _validate_transport_authority(self) -> dict[str, Any]:
        return validate_github_transport(self.source_root, self.repository)

    def _gh_json(self, *args: str, not_found_ok: bool = False) -> Any:
        _require_github_dot_com_host()
        argv = ["gh", *args]
        if args and args[0] == "api":
            argv.extend(("--hostname", GITHUB_HOST))
        result = subprocess.run(
            argv,
            cwd=self.source_root,
            env={**os.environ, "GH_HOST": GITHUB_HOST},
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            combined = (result.stdout + result.stderr).lower()
            if not_found_ok and ("not found" in combined or "404" in combined):
                return None
            _fail(
                "E_V240_ADAPTER_COMMAND",
                "fixed github.com API command failed",
                stderr=result.stderr[-2000:],
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            _fail("E_V240_ADAPTER_READBACK", f"GitHub returned invalid JSON: {exc}")

    def _gh_api(self, endpoint: str, *args: str, not_found_ok: bool = False) -> Any:
        return self._gh_json(
            "api", endpoint, *args, not_found_ok=not_found_ok
        )

    def _ls_remote_ref(self, ref: str, *, peel: bool = False) -> str | None:
        query = f"{ref}^{{}}" if peel else ref
        result = _run(("git", "ls-remote", "origin", query), cwd=self.source_root)
        rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
        if not rows:
            return None
        if len(rows) != 1 or len(rows[0]) != 2 or SHA40_RE.fullmatch(rows[0][0]) is None:
            _fail("E_V240_ADAPTER_READBACK", f"ambiguous remote ref: {query}")
        return rows[0][0]

    def _rest_ref(self, ref: str) -> Mapping[str, Any] | None:
        if not ref.startswith(("refs/heads/", "refs/tags/")):
            _fail("E_V240_ADAPTER_READBACK", f"unsupported fixed ref: {ref}")
        endpoint_ref = quote(ref.removeprefix("refs/"), safe="/")
        value = self._gh_api(
            f"repos/{self.repository}/git/ref/{endpoint_ref}",
            not_found_ok=True,
        )
        if value is None:
            return None
        obj = value.get("object") if isinstance(value, Mapping) else None
        if (
            not isinstance(value, Mapping)
            or value.get("ref") != ref
            or not isinstance(obj, Mapping)
            or SHA40_RE.fullmatch(str(obj.get("sha", ""))) is None
            or obj.get("type") not in {"commit", "tag"}
        ):
            _fail("E_V240_ADAPTER_READBACK", f"malformed REST ref: {ref}")
        return value

    def _remote_tag_identity(self, tag: str) -> dict[str, Any] | None:
        ref = f"refs/tags/{tag}"
        self._validate_transport_authority()
        value = self._rest_ref(ref)
        secondary_direct = self._ls_remote_ref(ref)
        if value is None:
            if secondary_direct is not None:
                _fail("E_V240_GITHUB_REF_DIVERGENCE", "REST tag is absent but origin tag exists")
            return None
        obj = value["object"]
        tag_object = obj["sha"]
        if secondary_direct != tag_object:
            _fail("E_V240_GITHUB_REF_DIVERGENCE", "REST/origin tag object differs")
        if obj.get("type") != "tag":
            secondary_peeled = self._ls_remote_ref(ref, peel=True)
            if secondary_peeled is not None:
                _fail("E_V240_GITHUB_REF_DIVERGENCE", "lightweight tag unexpectedly peels")
            return {
                "tag": tag,
                "annotated": False,
                "tag_object": tag_object,
                "peeled_commit": None,
                "message": None,
            }
        tag_value = self._gh_api(f"repos/{self.repository}/git/tags/{tag_object}")
        target = tag_value.get("object") if isinstance(tag_value, Mapping) else None
        if (
            not isinstance(tag_value, Mapping)
            or tag_value.get("tag") != tag
            or not isinstance(target, Mapping)
            or target.get("type") != "commit"
            or SHA40_RE.fullmatch(str(target.get("sha", ""))) is None
            or not isinstance(tag_value.get("message"), str)
        ):
            _fail("E_V240_ADAPTER_READBACK", "malformed annotated REST tag")
        peeled_commit = target["sha"]
        secondary_peeled = self._ls_remote_ref(ref, peel=True)
        if secondary_peeled != peeled_commit:
            _fail("E_V240_GITHUB_REF_DIVERGENCE", "REST/origin peeled tag differs")
        return {
            "tag": tag,
            "annotated": True,
            "tag_object": tag_object,
            "peeled_commit": peeled_commit,
            "message": tag_value["message"].rstrip("\n"),
        }

    def _remote_ref(self, ref: str, *, peel: bool = False) -> str | None:
        if ref.startswith("refs/tags/"):
            identity = self._remote_tag_identity(ref.removeprefix("refs/tags/"))
            if identity is None:
                return None
            return (
                identity.get("peeled_commit")
                if peel
                else identity.get("tag_object")
            )
        self._validate_transport_authority()
        value = self._rest_ref(ref)
        obj = value.get("object") if isinstance(value, Mapping) else None
        primary = obj.get("sha") if isinstance(obj, Mapping) else None
        secondary = self._ls_remote_ref(ref, peel=peel)
        if primary != secondary:
            _fail("E_V240_GITHUB_REF_DIVERGENCE", "REST/origin ref differs")
        if value is not None and obj.get("type") != "commit":
            _fail("E_V240_ADAPTER_READBACK", "branch REST ref does not target a commit")
        return primary

    def _release_json(self) -> Mapping[str, Any] | None:
        _require_github_dot_com_host()
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{self.repository}/releases/tags/{self.tag}",
                "--hostname",
                GITHUB_HOST,
            ],
            cwd=self.source_root,
            env={**os.environ, "GH_HOST": GITHUB_HOST},
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            combined = (result.stdout + result.stderr).lower()
            if "not found" in combined or "release not found" in combined or "404" in combined:
                return None
            _fail(
                "E_V240_ADAPTER_READBACK",
                "cannot read GitHub Release",
                stderr=result.stderr[-2000:],
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            _fail("E_V240_ADAPTER_READBACK", f"invalid Release JSON: {exc}")
        if not isinstance(value, Mapping):
            _fail("E_V240_ADAPTER_READBACK", "Release response is not an object")
        assets = value.get("assets")
        if not isinstance(assets, list):
            _fail("E_V240_ADAPTER_READBACK", "REST Release assets are not an array")
        normalized_assets: list[dict[str, Any]] = []
        for asset in assets:
            if not isinstance(asset, Mapping):
                _fail("E_V240_ADAPTER_READBACK", "REST Release asset is malformed")
            normalized_assets.append(
                {
                    "id": asset.get("id"),
                    "name": asset.get("name"),
                    "size": asset.get("size"),
                    "digest": asset.get("digest"),
                    "url": asset.get("url"),
                }
            )
        return {
            "databaseId": value.get("id"),
            "isDraft": value.get("draft"),
            "isImmutable": value.get("immutable"),
            "tagName": value.get("tag_name"),
            "targetCommitish": value.get("target_commitish"),
            "name": value.get("name"),
            "body": value.get("body"),
            "publishedAt": value.get("published_at"),
            "assets": normalized_assets,
            "url": value.get("html_url"),
        }

    def _resolve_target_commitish(self, value: Any) -> str | None:
        """Resolve a Release target through live refs to one commit identity."""

        if not isinstance(value, str) or not value:
            return None
        if SHA40_RE.fullmatch(value) is not None:
            return value
        refs: list[str]
        if value.startswith("refs/"):
            refs = [value]
        elif value == self.tag:
            refs = [f"refs/tags/{value}", f"refs/heads/{value}"]
        else:
            refs = [f"refs/heads/{value}", f"refs/tags/{value}"]
        for ref in refs:
            if ref.startswith("refs/tags/"):
                peeled = self._remote_ref(ref, peel=True)
                if peeled is not None:
                    return peeled
            direct = self._remote_ref(ref)
            if direct is not None:
                return direct
        return None

    def _validate_release_expected_before(
        self,
        expected_before: Mapping[str, Any],
        *,
        require_release_id: bool,
    ) -> int | None:
        """Validate the persisted canonical Release metadata contract."""

        if (
            expected_before.get("targetCommitish") != self.candidate_commit
            or expected_before.get("name") != CANONICAL_RELEASE_TITLE
            or expected_before.get("body") != CANONICAL_RELEASE_BODY
        ):
            _fail(
                "E_V240_ADAPTER_EXPECTED_BEFORE",
                "persisted Release target/title/body is not canonical",
            )
        release_id = expected_before.get("release_id")
        if require_release_id and (
            not isinstance(release_id, int)
            or isinstance(release_id, bool)
            or release_id < 1
        ):
            _fail(
                "E_V240_ADAPTER_EXPECTED_BEFORE",
                "persisted published Release id is missing",
            )
        return release_id if isinstance(release_id, int) else None

    def _latest_release(self) -> Mapping[str, Any] | None:
        _require_github_dot_com_host()
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{self.repository}/releases/latest",
                "--hostname",
                GITHUB_HOST,
            ],
            cwd=self.source_root,
            env={**os.environ, "GH_HOST": GITHUB_HOST},
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            combined = (result.stdout + result.stderr).lower()
            if "not found" in combined or "404" in combined:
                return None
            _fail("E_V240_ADAPTER_READBACK", "cannot read Latest Release", stderr=result.stderr[-2000:])
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            _fail("E_V240_ADAPTER_READBACK", f"invalid Latest Release JSON: {exc}")
        if not isinstance(value, Mapping):
            _fail("E_V240_ADAPTER_READBACK", "Latest Release response is not an object")
        return value

    def _asset_path(self, operation_id: str) -> tuple[str, Path]:
        template = ASSET_BY_OPERATION.get(operation_id)
        if template is None:
            _fail("E_V240_ADAPTER_UNSUPPORTED", f"unknown asset operation: {operation_id}")
        name = template.format(version=self.version)
        release_dir = self.workspace_root / "release" / "versions" / self.version
        if name in {f"goal-teams-{self.version}.tar.gz", "SHA256SUMS"}:
            path = release_dir / "_artifacts" / name
        else:
            path = release_dir / name
        if not path.is_file() or path.is_symlink():
            _fail("E_V240_DRAFT_ASSET_SET", f"missing fixed release asset: {name}")
        return name, path

    def _release_asset_readback(
        self,
        operation_id: str,
        expected_before: Mapping[str, Any],
    ) -> dict[str, Any]:
        release = self._release_json()
        name, local_path = self._asset_path(operation_id)
        local_hash = _file_sha256(local_path)
        local_size = local_path.stat().st_size
        if expected_before.get("asset_sha256") != local_hash or expected_before.get("asset_size") != local_size:
            _fail("E_V240_DRAFT_ASSET_IDENTITY", f"asset expected-before drift: {name}")
        if release is None:
            return self._readback(
                "github_api", {"classification": "absent", "asset": name, "tag": self.tag}
            )
        if release.get("isDraft") is not True or release.get("tagName") != self.tag:
            return self._readback(
                "github_api", {"classification": "conflict", "asset": name, "release": dict(release)}
            )
        assets = release.get("assets")
        if not isinstance(assets, list):
            _fail("E_V240_ADAPTER_READBACK", "Release asset list is missing")
        matches = [asset for asset in assets if isinstance(asset, Mapping) and asset.get("name") == name]
        if not matches:
            return self._readback(
                "github_api", {"classification": "absent", "asset": name, "release_id": release.get("databaseId")}
            )
        if len(matches) != 1:
            return self._readback(
                "github_api", {"classification": "conflict", "asset": name, "reason": "duplicate_name"}
            )
        metadata = matches[0]
        if metadata.get("size") != local_size:
            return self._readback(
                "github_api", {"classification": "conflict", "asset": name, "reason": "size_mismatch"}
            )
        with tempfile.TemporaryDirectory(prefix="goal-teams-v240-asset-readback-") as directory:
            _run(
                (
                    "gh", "release", "download", self.tag, "--repo", self.host_repository,
                    "--dir", directory, "--pattern", name,
                ),
                cwd=self.source_root,
            )
            downloaded = Path(directory) / name
            if not downloaded.is_file() or downloaded.is_symlink():
                _fail("E_V240_ADAPTER_READBACK", f"downloaded asset is missing: {name}")
            downloaded_hash = _file_sha256(downloaded)
            downloaded_size = downloaded.stat().st_size
        classification = (
            "exact"
            if downloaded_hash == local_hash and downloaded_size == local_size
            else "conflict"
        )
        return self._readback(
            "github_api",
            {
                "classification": classification,
                "asset": name,
                "asset_id": metadata.get("id"),
                "sha256": downloaded_hash,
                "size": downloaded_size,
                "release_id": release.get("databaseId"),
            },
        )

    def _local_asset_set(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for operation_id in ASSET_BY_OPERATION:
            name, path = self._asset_path(operation_id)
            result[name] = {"sha256": _file_sha256(path), "size": path.stat().st_size}
        return dict(sorted(result.items()))

    def _persist_verified_bundle(
        self, release: Mapping[str, Any], *, expected_draft: bool
    ) -> dict[str, Any]:
        """Download the fixed four assets into an ignored, identity-bound bundle."""

        phase = "draft" if expected_draft else "published"
        parent = (
            self.workspace_root
            / "docs"
            / "release-state"
            / self.version
            / self.candidate_commit
        )
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / f"{phase}-bundle"
        if target.is_symlink() or parent.resolve() not in target.resolve(strict=False).parents:
            _fail("E_V240_TARGET_OUTSIDE", "bundle target escapes ignored release state")
        temp = Path(tempfile.mkdtemp(prefix=f".{phase}-bundle-", dir=parent))
        try:
            _run(
                (
                    "gh", "release", "download", self.tag, "--repo", self.host_repository,
                    "--dir", str(temp), "--pattern", f"goal-teams-{self.version}.tar.gz",
                    "--pattern", "SHA256SUMS", "--pattern", "_release.json",
                    "--pattern", "_files.sha256",
                ),
                cwd=self.source_root,
            )
            local_assets = self._local_asset_set()
            metadata_assets = release.get("assets")
            if not isinstance(metadata_assets, list):
                _fail("E_V240_ADAPTER_READBACK", "Release asset metadata is missing")
            metadata_by_name = {
                asset.get("name"): asset
                for asset in metadata_assets
                if isinstance(asset, Mapping) and isinstance(asset.get("name"), str)
            }
            if set(metadata_by_name) != set(local_assets):
                _fail("E_V240_DRAFT_ASSET_SET", "remote Release is not the fixed four-asset set")
            assets: list[dict[str, Any]] = []
            for name, expected in local_assets.items():
                downloaded = temp / name
                metadata = metadata_by_name[name]
                if (
                    not downloaded.is_file()
                    or downloaded.is_symlink()
                    or _file_sha256(downloaded) != expected["sha256"]
                    or downloaded.stat().st_size != expected["size"]
                    or metadata.get("size") != expected["size"]
                    or not isinstance(metadata.get("id"), int)
                ):
                    _fail("E_V240_DRAFT_ASSET_IDENTITY", f"downloaded asset identity drift: {name}")
                digest_metadata = metadata.get("digest")
                if digest_metadata not in {None, f"sha256:{expected['sha256']}"}:
                    _fail("E_V240_DRAFT_ASSET_IDENTITY", f"REST asset digest drift: {name}")
                assets.append(
                    {
                        "name": name,
                        "asset_id": metadata["id"],
                        "size": expected["size"],
                        "sha256": expected["sha256"],
                        "download_sha256": expected["sha256"],
                    }
                )
            record = json.loads((temp / "_release.json").read_text(encoding="utf-8"))
            if record.get("source_commit") != self.candidate_commit:
                _fail("E_V240_RELEASE_SOURCE_IDENTITY", "downloaded release record commit drift")
            identity = {
                "source_kind": "local_release_bundle" if expected_draft else "github_release_asset",
                "repository": self.repository,
                "version": self.version,
                "release_tag": self.tag,
                "release_id": release.get("databaseId"),
                "release_state": "draft" if expected_draft else "published",
                "source_commit": self.candidate_commit,
                "source_git_tree_id": record.get("source_git_tree_id"),
                "assets": assets,
            }
            if target.exists():
                if not target.is_dir() or target.is_symlink():
                    _fail("E_V240_BUNDLE_TAMPER", "persisted bundle target conflicts")
                expected_names = {path.name for path in temp.iterdir() if path.is_file()}
                observed_names = {path.name for path in target.iterdir() if path.is_file()}
                if expected_names != observed_names or any(
                    _file_sha256(temp / name) != _file_sha256(target / name)
                    for name in expected_names
                ):
                    _fail("E_V240_BUNDLE_TAMPER", "persisted bundle differs from live download")
            else:
                os.replace(temp, target)
                temp = Path()
            identity_path = parent / f"{phase}-release-identity.json"
            identity_bytes = (
                json.dumps(identity, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            ).encode("utf-8")
            if identity_path.exists():
                if (
                    not identity_path.is_file()
                    or identity_path.is_symlink()
                    or identity_path.read_bytes() != identity_bytes
                ):
                    _fail("E_V240_BUNDLE_TAMPER", "persisted release identity conflicts")
            else:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=parent, prefix=f".{identity_path.name}.", delete=False
                ) as stream:
                    identity_temp = Path(stream.name)
                    stream.write(identity_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(identity_temp, identity_path)
            return {
                "bundle_path": str(target),
                "release_identity_path": str(identity_path),
                "release_identity_sha256": _file_sha256(identity_path),
                "assets": assets,
                "asset_set_sha256": _canonical_sha256(local_assets),
            }
        finally:
            if str(temp) not in {"", "."}:
                shutil.rmtree(temp, ignore_errors=True)

    def _run_release_adapter(self, action: str) -> subprocess.CompletedProcess[str]:
        script = self.source_root / "scripts" / "release" / "publish-github-release.sh"
        return _run(
            (str(script), self.version, self.candidate_commit, action),
            cwd=self.source_root,
            env={"GOAL_TEAMS_RELEASE_ORCHESTRATOR": "1"},
        )

    def _ruleset_by_name(self, name: str) -> Mapping[str, Any] | None:
        values = self._gh_api(
            f"repos/{self.repository}/rulesets", "--paginate", "--slurp"
        )
        if isinstance(values, list) and len(values) == 1 and isinstance(values[0], list):
            values = values[0]
        if not isinstance(values, list):
            _fail("E_V240_ADAPTER_READBACK", "ruleset response is not an array")
        matches = [value for value in values if isinstance(value, Mapping) and value.get("name") == name]
        if len(matches) > 1:
            _fail("E_V240_REMOTE_RESOURCE_CONFLICT", f"duplicate ruleset name: {name}")
        if not matches:
            return None
        ruleset_id = matches[0].get("id")
        if not isinstance(ruleset_id, int) or ruleset_id < 1:
            _fail("E_V240_ADAPTER_READBACK", "ruleset id is missing")
        detail = self._gh_api(f"repos/{self.repository}/rulesets/{ruleset_id}")
        if not isinstance(detail, Mapping):
            _fail("E_V240_ADAPTER_READBACK", "ruleset detail is not an object")
        return detail

    def _live_authority(self) -> dict[str, Any]:
        origin_binding = self._validate_transport_authority()
        user = self._gh_api("user")
        repository = self._gh_api(f"repos/{self.repository}")
        immutable = self._gh_api(f"repos/{self.repository}/immutable-releases")
        # A successful list request establishes read capability.  Write
        # capability is bound to repository admin permission and is rechecked
        # immediately before every mutation.
        self._gh_api(f"repos/{self.repository}/rulesets")
        if not isinstance(user, Mapping) or not isinstance(repository, Mapping):
            _fail("E_V240_GITHUB_AUTHORITY_BINDING", "authority readback malformed")
        if (
            repository.get("full_name") != FIXED_REPOSITORY
            or repository.get("id") != FIXED_REPOSITORY_ID
        ):
            _fail("E_V240_GITHUB_REPOSITORY_BINDING", "fixed repository API identity drift")
        actor = {"actor_id": user.get("id"), "actor_login": user.get("login")}
        repo_binding = {
            "api_host": GITHUB_HOST,
            "repository_id": repository.get("id"),
            "repository_full_name": repository.get("full_name"),
            "origin_binding": origin_binding,
        }
        permissions = repository.get("permissions")
        admin = isinstance(permissions, Mapping) and permissions.get("admin") is True
        immutable_enabled = bool(
            isinstance(immutable, Mapping) and immutable.get("enabled") is True
        )
        capabilities = {
            "immutable_endpoint_capability": {
                "read": True,
                "enable": admin,
                "enabled": immutable_enabled,
                "endpoint_sha256": _canonical_sha256(immutable),
            },
            "ruleset_capability": {
                "read": True,
                "write": admin,
                "bypass_actor_supported": True,
                "endpoint_sha256": _canonical_sha256(
                    {"endpoint": f"repos/{self.repository}/rulesets", "read": True}
                ),
            },
        }
        result: dict[str, Any] = {
            **actor,
            **repo_binding,
            "origin_binding_sha256": origin_binding["origin_binding_sha256"],
            "permission": "admin" if admin else "not_admin",
            **capabilities,
            "authorized_external_actions": list(AUTHORIZED_ACTIONS),
            "observed_at": _utc_now(),
            "actor_binding_sha256": _canonical_sha256(actor),
            "repository_binding_sha256": _canonical_sha256(repo_binding),
            "capability_binding_sha256": _canonical_sha256(capabilities),
            "authorized_actions_sha256": _canonical_sha256(AUTHORIZED_ACTIONS),
        }
        result["receipt_sha256"] = _canonical_sha256(result)
        return result

    def _require_write_authority(self, action: str) -> None:
        if action not in WRITE_ACTIONS:
            return
        if not self.execute_external_writes or os.environ.get(
            "GOAL_TEAMS_RELEASE_WRITE"
        ) != "1":
            _fail(
                "E_V240_EXTERNAL_WRITE_NOT_AUTHORIZED",
                "remote write requires both input opt-in and GOAL_TEAMS_RELEASE_WRITE=1",
            )
        live = self._live_authority()
        for field in (
            "api_host",
            "actor_id",
            "actor_login",
            "repository_id",
            "repository_full_name",
            "origin_binding",
            "origin_binding_sha256",
            "permission",
            "immutable_endpoint_capability",
            "ruleset_capability",
            "authorized_external_actions",
            "actor_binding_sha256",
            "repository_binding_sha256",
            "capability_binding_sha256",
            "authorized_actions_sha256",
        ):
            if live.get(field) != self.authority.get(field):
                _fail("E_V240_GITHUB_AUTHORITY_BINDING", f"live authority drift: {field}")
        if self.authority.get("receipt_sha256") is None:
            _fail("E_V240_GITHUB_AUTHORITY_BINDING", "persisted authority receipt missing")

    def _validate_ruleset_payload(
        self, action: str, payload: Mapping[str, Any]
    ) -> None:
        normalized = normalize_ruleset(payload)
        conditions = normalized["conditions"]
        ref_name = conditions.get("ref_name") if isinstance(conditions, Mapping) else None
        includes = ref_name.get("include") if isinstance(ref_name, Mapping) else None
        rule_types = {rule.get("type") for rule in normalized["rules"]}
        if normalized["enforcement"] != "active":
            _fail("E_V240_RULESET_IDENTITY", "release rulesets must be active")
        if action == "tag_ruleset_create":
            if (
                normalized["target"] != "tag"
                or normalized["bypass_actors"] != []
                or set(includes or []) != {"refs/tags/v*"}
                or rule_types != {"update", "deletion"}
            ):
                _fail("E_V240_TAG_RULESET", "tag ruleset is not the permanent v* update/deletion lock")
        elif action == "promotion_lock_create":
            expected_bypass = [
                {
                    "actor_id": self.authority.get("actor_id"),
                    "actor_type": "User",
                    "bypass_mode": "always",
                }
            ]
            if (
                normalized["target"] != "branch"
                or normalized["bypass_actors"] != expected_bypass
                or set(includes or []) != {"refs/heads/main"}
                or rule_types != {"update"}
            ):
                _fail("E_V240_PROMOTION_LOCK", "promotion ruleset is not the exact main update lock")
        elif action == "promotion_lock_finalize":
            required = {
                "deletion",
                "non_fast_forward",
                "pull_request",
                "required_status_checks",
            }
            rules_by_type = {rule["type"]: rule for rule in normalized["rules"]}
            status_parameters = rules_by_type.get("required_status_checks", {}).get("parameters")
            pull_parameters = rules_by_type.get("pull_request", {}).get("parameters")
            status_records = (
                status_parameters.get("required_status_checks")
                if isinstance(status_parameters, Mapping)
                else None
            )
            status_contexts = {
                record.get("context")
                for record in status_records
                if isinstance(record, Mapping)
            } if isinstance(status_records, list) else set()
            if (
                normalized["target"] != "branch"
                or normalized["bypass_actors"]
                or set(includes or []) != {"refs/heads/main"}
                or rule_types != required
                or status_contexts
                != {"check-ubuntu", "check-macos", "release-asset-gate"}
                or not isinstance(status_records, list)
                or len(status_records) != 3
                or not isinstance(status_parameters, Mapping)
                or status_parameters.get("strict_required_status_checks_policy") is not True
                or status_parameters.get("do_not_enforce_on_create") is not False
                or not isinstance(pull_parameters, Mapping)
                or pull_parameters.get("dismiss_stale_reviews_on_push") is not True
                or pull_parameters.get("require_last_push_approval") is not True
                or pull_parameters.get("required_approving_review_count") != 1
                or pull_parameters.get("required_review_thread_resolution") is not True
            ):
                _fail("E_V240_PROMOTION_LOCK", "finalized main ruleset is not the exact frozen protection policy")

    @staticmethod
    def _readback(source: str, details: Mapping[str, Any]) -> dict[str, Any]:
        detail_copy = json.loads(json.dumps(details))
        return {
            "classification": str(details.get("classification", "exact")),
            "source": source,
            "observed_at": _utc_now(),
            "state_sha256": _canonical_sha256(detail_copy),
            "details": detail_copy,
        }

    def observe(
        self,
        *,
        operation_id: str,
        action: str,
        expected_before: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Read live state and classify it without mutation."""

        if action == "candidate_push":
            value = self._remote_ref("refs/heads/codex/v2.40")
            expected_after = self.candidate_commit
            classification = "exact" if value == expected_after else (
                "absent" if value is None else "conflict"
            )
            return self._readback(
                "git_ls_remote",
                {"classification": classification, "remote_commit": value, "ref": "refs/heads/codex/v2.40"},
            )
        if action == "tag_push":
            tag_identity = self._remote_tag_identity(self.tag)
            tag_object = tag_identity.get("tag_object") if tag_identity else None
            value = tag_identity.get("peeled_commit") if tag_identity else None
            message = tag_identity.get("message") if tag_identity else None
            classification = "exact" if (
                value == self.candidate_commit
                and tag_object is not None
                and message == CANONICAL_TAG_MESSAGE
            ) else (
                "absent" if tag_identity is None else "conflict"
            )
            return self._readback(
                "git_ls_remote",
                {"classification": classification, "tag": self.tag, "tag_object": tag_object, "peeled_commit": value, "message": message},
            )
        if action == "main_promote":
            value = self._remote_ref("refs/heads/main")
            classification = "exact" if value == self.candidate_commit else (
                "absent" if value is None else (
                    "before" if value == self.base_main_commit else "conflict"
                )
            )
            return self._readback(
                "git_ls_remote",
                {"classification": classification, "remote_commit": value, "ref": "refs/heads/main"},
            )
        if action == "asset_upload":
            return self._release_asset_readback(operation_id, expected_before)
        if action in {"asset_download_verify", "published_asset_download"}:
            release = self._release_json()
            expected_draft = action == "asset_download_verify"
            if release is None:
                return self._readback("github_api", {"classification": "absent", "tag": self.tag})
            if (
                release.get("tagName") != self.tag
                or (release.get("isDraft") is True) != expected_draft
            ):
                return self._readback("github_api", {"classification": "conflict", "release": dict(release)})
            # Downloading and byte-comparing is a read-only live observation,
            # not a remote mutation.  The ignored persisted bundle is the
            # only input later rehearsal/actual-install operations may use.
            bundle = self._persist_verified_bundle(release, expected_draft=expected_draft)
            return self._readback(
                "github_api",
                {
                    "classification": "exact",
                    "release_id": release.get("databaseId"),
                    "release_state": "draft" if expected_draft else "published",
                    **bundle,
                },
            )
        if action in {"draft_create", "release_publish"}:
            expected_release_id = self._validate_release_expected_before(
                expected_before,
                require_release_id=action == "release_publish",
            )
            release = self._release_json()
            if release is None:
                classification = "absent"
                details: dict[str, Any] = {"classification": classification, "tag": self.tag}
            else:
                is_draft = release.get("isDraft") is True
                resolved_target = self._resolve_target_commitish(
                    release.get("targetCommitish")
                )
                canonical_metadata = (
                    release.get("tagName") == self.tag
                    and resolved_target == self.candidate_commit
                    and release.get("name") == CANONICAL_RELEASE_TITLE
                    and release.get("body") == CANONICAL_RELEASE_BODY
                )
                if action == "release_publish" and is_draft:
                    classification = (
                        "before"
                        if canonical_metadata
                        and release.get("databaseId") == expected_release_id
                        else "conflict"
                    )
                else:
                    expected_published = action == "release_publish"
                    exact_state = (not is_draft) if expected_published else is_draft
                    classification = (
                        "exact"
                        if exact_state
                        and canonical_metadata
                        and (
                            not expected_published
                            or release.get("databaseId") == expected_release_id
                        )
                        else "conflict"
                    )
                details = {
                    "classification": classification,
                    **dict(release),
                    "resolvedTargetCommit": resolved_target,
                }
                if action == "release_publish" and classification == "exact":
                    tag_identity = self._remote_tag_identity(self.tag)
                    tag_object = tag_identity.get("tag_object") if tag_identity else None
                    peeled_commit = tag_identity.get("peeled_commit") if tag_identity else None
                    latest = self._latest_release()
                    details["latest"] = bool(
                        isinstance(latest, Mapping)
                        and latest.get("id") == release.get("databaseId")
                        and latest.get("tag_name") == self.tag
                    )
                    details["tagObject"] = tag_object
                    details["peeledCommit"] = peeled_commit
                    tag_exact = (
                        isinstance(tag_object, str)
                        and tag_object != self.candidate_commit
                        and peeled_commit == self.candidate_commit
                        and tag_identity.get("message") == CANONICAL_TAG_MESSAGE
                    )
                    if (
                        details["latest"] is not True
                        or release.get("isImmutable") is not True
                        or not tag_exact
                    ):
                        details["classification"] = "conflict"
                    else:
                        try:
                            bundle = self._persist_verified_bundle(
                                release, expected_draft=False
                            )
                        except AdapterError as exc:
                            details["classification"] = "conflict"
                            details["asset_identity_error"] = exc.receipt.get(
                                "error_code"
                            )
                        else:
                            details.update(bundle)
                            if (
                                bundle.get("asset_set_sha256")
                                != expected_before.get("asset_set_sha256")
                                or bundle.get("asset_set_sha256")
                                != expected_before.get("draft_asset_set_sha256")
                            ):
                                details["classification"] = "conflict"
            return self._readback("github_api", details)
        if action in {"immutable_release_enable", "immutable_release_verify"}:
            value = self._gh_api(f"repos/{self.repository}/immutable-releases")
            enabled = isinstance(value, Mapping) and value.get("enabled") is True
            authority = self._live_authority()
            return self._readback(
                "github_api",
                {"classification": "exact" if enabled else "absent", "enabled": enabled, "response": value, "authority": authority},
            )
        if action in {"github_authority_verify", "ruleset_capability_verify"}:
            authority = self._live_authority()
            if not self.authority:
                exact = (
                    authority.get("api_host") == GITHUB_HOST
                    and authority.get("repository_full_name") == self.repository
                    and authority.get("permission") == "admin"
                    and authority.get("authorized_external_actions") == AUTHORIZED_ACTIONS
                )
            else:
                exact = all(
                    authority.get(field) == self.authority.get(field)
                    for field in (
                        "api_host", "actor_id", "actor_login", "repository_id",
                        "repository_full_name", "permission",
                        "origin_binding", "origin_binding_sha256",
                        "immutable_endpoint_capability", "ruleset_capability",
                        "authorized_external_actions", "actor_binding_sha256",
                        "repository_binding_sha256", "capability_binding_sha256",
                        "authorized_actions_sha256",
                    )
                )
            return self._readback(
                "github_api", {"classification": "exact" if exact else "conflict", "authority": authority}
            )
        if action in {"promotion_lock_create", "tag_ruleset_create", "promotion_lock_finalize"}:
            if action == "promotion_lock_finalize":
                post_mutation = parameters.get("_post_mutation") is True
                prior_name = expected_before.get("ruleset_name")
                final_name = parameters.get("ruleset_name")
                prior_id = expected_before.get("ruleset_id")
                final_id = parameters.get("ruleset_id")
                if (
                    not isinstance(prior_name, str)
                    or not prior_name
                    or not isinstance(final_name, str)
                    or not final_name
                    or prior_name == final_name
                    or not isinstance(prior_id, int)
                    or prior_id < 1
                    or final_id != prior_id
                ):
                    _fail(
                        "E_V240_ADAPTER_EXPECTED_BEFORE",
                        "final ruleset must CAS the bound temporary ruleset id and distinct names",
                    )
                name = final_name if post_mutation else prior_name
            else:
                post_mutation = False
                prior_name = None
                final_name = None
                prior_id = None
                name = parameters.get("ruleset_name") or expected_before.get("ruleset_name")
            if not isinstance(name, str) or not name:
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "ruleset name missing")
            value = self._ruleset_by_name(name)
            if action == "promotion_lock_finalize" and not post_mutation:
                expected_payload = expected_before.get("ruleset_payload")
                bound_expected_sha = expected_before.get("ruleset_sha256")
            else:
                expected_payload = parameters.get("ruleset_payload")
                if expected_payload is None:
                    expected_payload = expected_before.get("ruleset_payload")
                bound_expected_sha = (
                    parameters.get("ruleset_payload_sha256")
                    or parameters.get("ruleset_sha256")
                    or expected_before.get("ruleset_sha256")
                )
            if not isinstance(expected_payload, Mapping):
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "canonical ruleset payload missing")
            if expected_payload.get("name") != name:
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "canonical ruleset name drift")
            expected_sha = _canonical_sha256(normalize_ruleset(expected_payload))
            if bound_expected_sha != expected_sha:
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "canonical ruleset digest drift")
            observed_sha = _canonical_sha256(normalize_ruleset(value)) if value is not None else None
            observed_id = value.get("id") if isinstance(value, Mapping) else None
            other_value: Mapping[str, Any] | None = None
            if action == "promotion_lock_finalize":
                other_name = prior_name if post_mutation else final_name
                assert isinstance(other_name, str)
                other_value = self._ruleset_by_name(other_name)
                id_exact = observed_id == prior_id
                if value is None and other_value is None:
                    classification = "absent"
                elif expected_sha == observed_sha and id_exact and other_value is None:
                    classification = "exact" if post_mutation else "before"
                else:
                    classification = "conflict"
            else:
                classification = "absent" if value is None else (
                    "exact" if expected_sha == observed_sha else "conflict"
                )
            return self._readback(
                "github_api",
                {
                    "classification": classification,
                    "ruleset_name": name,
                    "ruleset_id": observed_id,
                    "ruleset_sha256": observed_sha,
                    "ruleset": value,
                    "other_ruleset_name": (
                        (prior_name if post_mutation else final_name)
                        if action == "promotion_lock_finalize"
                        else None
                    ),
                    "other_ruleset_absent": (
                        other_value is None
                        if action == "promotion_lock_finalize"
                        else None
                    ),
                },
            )
        if action in {"ci_wait", "post_release_ci"}:
            run_id = parameters.get("run_id") or expected_before.get("run_id")
            release_intent = parameters.get("_release_intent")
            display_title = None
            if action == "post_release_ci":
                if not isinstance(release_intent, str) or re.fullmatch(r"[0-9a-f]{64}", release_intent) is None:
                    _fail("E_V240_CI_INTENT", "post-release CI requires its persisted operation idempotency key")
                display_title = f"Goal Teams V2.40 release {release_intent}"
                if run_id is None:
                    approval = expected_before.get("ci_approval")
                    approved_actor_id = (
                        approval.get("release_actor_id")
                        if isinstance(approval, Mapping)
                        else None
                    )
                    workflow_path = (
                        approval.get("workflow_path")
                        if isinstance(approval, Mapping)
                        else None
                    )
                    if workflow_path != ".github/workflows/release-gate.yml":
                        _fail("E_V240_CI_TRUST_BINDING", "post-release workflow approval is not fixed")
                    payload = self._gh_api(
                        f"repos/{self.repository}/actions/workflows/"
                        f"{quote(workflow_path, safe='')}/runs?event=workflow_dispatch&branch=main&per_page=100"
                    )
                    runs = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
                    if not isinstance(runs, list):
                        _fail("E_V240_CI_TRUST_BINDING", "workflow-dispatch run list is malformed")
                    approved_workflow_id = approval.get("workflow_id") if isinstance(approval, Mapping) else None
                    matches = []
                    for candidate in runs:
                        if not isinstance(candidate, Mapping):
                            continue
                        actor = candidate.get("actor")
                        triggering = candidate.get("triggering_actor")
                        if (
                            candidate.get("path") == workflow_path
                            and candidate.get("head_sha") == self.candidate_commit
                            and candidate.get("event") == "workflow_dispatch"
                            and isinstance(actor, Mapping)
                            and actor.get("id") == approved_actor_id
                            and isinstance(triggering, Mapping)
                            and triggering.get("id") == approved_actor_id
                            and candidate.get("display_title") == display_title
                            and (
                                not isinstance(approved_workflow_id, int)
                                or candidate.get("workflow_id") == approved_workflow_id
                            )
                        ):
                            matches.append(candidate)
                    if not matches:
                        return self._readback(
                            "github_actions_api",
                            {
                                "classification": "absent",
                                "release_intent": release_intent,
                                "display_title": display_title,
                            },
                        )
                    if len(matches) > 1:
                        return self._readback(
                            "github_actions_api",
                            {
                                "classification": "conflict",
                                "reason": "duplicate_dispatch_intent",
                                "release_intent": release_intent,
                                "display_title": display_title,
                                "matching_run_ids": [item.get("id") for item in matches],
                            },
                        )
                    run_id = matches[0].get("id")
            if not isinstance(run_id, int) or run_id < 1:
                return self._readback(
                    "github_actions_api", {"classification": "unavailable", "reason": "run_id_required"}
                )
            run = self._gh_api(f"repos/{self.repository}/actions/runs/{run_id}")
            jobs_payload = self._gh_api(
                f"repos/{self.repository}/actions/runs/{run_id}/jobs?per_page=100"
            )
            jobs_raw = jobs_payload.get("jobs") if isinstance(jobs_payload, Mapping) else None
            if not isinstance(run, Mapping) or not isinstance(jobs_raw, list):
                _fail("E_V240_CI_TRUST_BINDING", "Actions run/jobs response is malformed")
            jobs = [
                {
                    "name": job.get("name"),
                    "head_sha": run.get("head_sha"),
                    "conclusion": job.get("conclusion"),
                }
                for job in jobs_raw
                if isinstance(job, Mapping)
            ]
            workflow_path = run.get("path")
            blob = _run(
                ("git", "rev-parse", f"{self.candidate_commit}:{workflow_path}"),
                cwd=self.source_root,
            ).stdout.strip() if isinstance(workflow_path, str) else None
            ci_receipt = {
                "head_sha": run.get("head_sha"),
                "workflow_path": workflow_path,
                "workflow_blob_sha": blob,
                "workflow_id": run.get("workflow_id"),
                "run_id": run.get("id"),
                "run_attempt": run.get("run_attempt"),
                "event": run.get("event"),
                "actor_id": run.get("actor", {}).get("id") if isinstance(run.get("actor"), Mapping) else None,
                "triggering_actor_id": (
                    run.get("triggering_actor", {}).get("id")
                    if isinstance(run.get("triggering_actor"), Mapping)
                    else None
                ),
                "jobs": jobs,
                "created_at": run.get("created_at"),
                "release_intent": release_intent if action == "post_release_ci" else None,
                "display_title": run.get("display_title"),
            }
            expected_jobs = {"check-ubuntu", "check-macos", "release-asset-gate"}
            approval = expected_before.get("ci_approval")
            approved_actor_id = (
                approval.get("release_actor_id")
                if isinstance(approval, Mapping)
                else None
            )
            authority_actor_id = self.authority.get("actor_id")
            live_actor_id = ci_receipt["actor_id"]
            triggering_actor_id = ci_receipt["triggering_actor_id"]
            actor_exact = (
                isinstance(approved_actor_id, int)
                and not isinstance(approved_actor_id, bool)
                and approved_actor_id > 0
                and isinstance(authority_actor_id, int)
                and not isinstance(authority_actor_id, bool)
                and approved_actor_id == authority_actor_id
                and isinstance(live_actor_id, int)
                and not isinstance(live_actor_id, bool)
                and live_actor_id == approved_actor_id
                and isinstance(triggering_actor_id, int)
                and not isinstance(triggering_actor_id, bool)
                and triggering_actor_id == approved_actor_id
            )
            exact = (
                ci_receipt["head_sha"] == self.candidate_commit
                and actor_exact
                and isinstance(ci_receipt["run_id"], int)
                and not isinstance(ci_receipt["run_id"], bool)
                and ci_receipt["run_id"] > 0
                and isinstance(ci_receipt["run_attempt"], int)
                and not isinstance(ci_receipt["run_attempt"], bool)
                and ci_receipt["run_attempt"] > 0
                and run.get("conclusion") == "success"
                and (
                    action != "post_release_ci"
                    or (
                        ci_receipt["release_intent"] == release_intent
                        and ci_receipt["display_title"] == display_title
                    )
                )
                and {job.get("name") for job in jobs} == expected_jobs
                and all(job.get("conclusion") == "success" for job in jobs)
            )
            return self._readback(
                "github_actions_api",
                {
                    "classification": "exact" if exact else "unavailable",
                    "reason": None if exact else "matching_run_pending_or_failed",
                    "pending_existing": action == "post_release_ci",
                    "ci_receipt": ci_receipt,
                },
            )
        _fail("E_V240_ADAPTER_UNSUPPORTED", f"no live GitHub observer for {operation_id} ({action})")

    def execute(
        self,
        *,
        operation_id: str,
        action: str,
        expected_before: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Execute one fixed mutation, then return a fresh live readback."""

        if not isinstance(expected_before, Mapping):
            _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "expected-before is required")
        self._require_write_authority(action)
        before = self.observe(
            operation_id=operation_id,
            action=action,
            expected_before=expected_before,
            parameters=parameters,
        )
        classification = before.get("classification")
        if classification == "exact":
            before["adopted_existing"] = True
            if action == "release_publish":
                before["adopted_after_marker_loss"] = True
            before["external_side_effect_count"] = 0
            return before
        if action == "promotion_lock_finalize" and classification in {"conflict", "absent"}:
            # A crash may occur after the PUT has made the permanent policy
            # exact but before release.py persists its readback.  Reclassify
            # against the authorized post-mutation payload before considering
            # any replay; an exact final policy is adopted with zero writes.
            post_parameters = dict(parameters)
            post_parameters["_post_mutation"] = True
            post = self.observe(
                operation_id=operation_id,
                action=action,
                expected_before=expected_before,
                parameters=post_parameters,
            )
            if post.get("classification") == "exact":
                post["adopted_existing"] = True
                post["adopted_after_marker_loss"] = True
                post["external_side_effect_count"] = 0
                return post
        if action == "promotion_lock_finalize" and classification != "before":
            _fail(
                "E_V240_REMOTE_RESOURCE_CONFLICT",
                "final ruleset mutation requires the exact bound temporary ruleset CAS",
            )
        dispatch_pending = (
            action == "post_release_ci"
            and classification == "absent"
            and parameters.get("dispatch") is True
        )
        if action == "post_release_ci" and classification == "unavailable":
            _fail(
                "E_V240_CI_PENDING",
                "matching workflow dispatch already exists; adopt it without redispatch",
                external_side_effect_count=0,
            )
        if classification in {"conflict", "unavailable"} or (
            classification == "absent" and action == "post_release_ci" and not dispatch_pending
        ):
            _fail(
                "E_V240_REMOTE_RESOURCE_CONFLICT",
                f"cannot mutate from live classification {classification}",
            )

        if action == "immutable_release_enable":
            self._gh_api(
                f"repos/{self.repository}/immutable-releases",
                "--method",
                "PUT",
                "-F",
                "enabled=true",
            )
        elif action in {"promotion_lock_create", "tag_ruleset_create"}:
            payload = parameters.get("ruleset_payload")
            payload_sha = parameters.get("ruleset_payload_sha256")
            if (
                not isinstance(payload, Mapping)
                or payload_sha != _canonical_sha256(normalize_ruleset(payload))
            ):
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "ruleset payload digest mismatch")
            name = payload.get("name")
            if name != (parameters.get("ruleset_name") or expected_before.get("ruleset_name")):
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "ruleset payload name drift")
            self._validate_ruleset_payload(action, payload)
            with tempfile.NamedTemporaryFile(mode="wb", delete=False) as stream:
                payload_path = Path(stream.name)
                stream.write(_canonical_bytes(payload))
            try:
                _run(
                    ("gh", "api", f"repos/{self.repository}/rulesets", "--hostname", GITHUB_HOST, "--method", "POST", "--input", str(payload_path)),
                    cwd=self.source_root,
                )
            finally:
                payload_path.unlink(missing_ok=True)
        elif action == "promotion_lock_finalize":
            ruleset_id = parameters.get("ruleset_id")
            payload = parameters.get("ruleset_payload")
            payload_sha = parameters.get("ruleset_payload_sha256")
            if (
                not isinstance(ruleset_id, int)
                or ruleset_id < 1
                or ruleset_id != expected_before.get("ruleset_id")
                or not isinstance(payload, Mapping)
                or payload.get("name") != parameters.get("ruleset_name")
                or payload_sha != _canonical_sha256(normalize_ruleset(payload))
            ):
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "final ruleset CAS input is invalid")
            self._validate_ruleset_payload(action, payload)
            with tempfile.NamedTemporaryFile(mode="wb", delete=False) as stream:
                payload_path = Path(stream.name)
                stream.write(_canonical_bytes(payload))
            try:
                _run(
                    ("gh", "api", f"repos/{self.repository}/rulesets/{ruleset_id}", "--hostname", GITHUB_HOST, "--method", "PUT", "--input", str(payload_path)),
                    cwd=self.source_root,
                )
            finally:
                payload_path.unlink(missing_ok=True)
        elif action == "candidate_push":
            expected = expected_before.get("remote_candidate_commit")
            if expected not in {None, self.candidate_commit}:
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "candidate ref expected-before drift")
            _run(
                ("git", "push", "origin", f"{self.candidate_commit}:refs/heads/codex/v2.40"),
                cwd=self.source_root,
            )
        elif action == "tag_push":
            if expected_before.get("remote_tag_commit") is not None:
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "tag creation requires absent expected-before")
            local_tag = subprocess.run(
                _git_argv(("git", "rev-parse", f"refs/tags/{self.tag}^{{}}")),
                cwd=self.source_root,
                env=_git_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            if local_tag.returncode == 0:
                if local_tag.stdout.strip() != self.candidate_commit:
                    _fail("E_V240_REMOTE_RESOURCE_CONFLICT", "local tag identity conflicts")
            else:
                _run(
                    (
                        "git",
                        "tag",
                        "-a",
                        self.tag,
                        self.candidate_commit,
                        "-m",
                        CANONICAL_TAG_MESSAGE,
                    ),
                    cwd=self.source_root,
                )
            _run(("git", "push", "origin", f"refs/tags/{self.tag}"), cwd=self.source_root)
        elif action == "main_promote":
            expected = expected_before.get("remote_main_commit")
            if expected != self.base_main_commit:
                _fail("E_V240_REMOTE_MAIN_LEASE", "main expected-before is not frozen base")
            _run(
                (
                    "git",
                    "push",
                    f"--force-with-lease=refs/heads/main:{self.base_main_commit}",
                    "origin",
                    f"{self.candidate_commit}:refs/heads/main",
                ),
                cwd=self.source_root,
            )
        elif action == "draft_create":
            _run(
                (
                    "gh", "release", "create", self.tag, "--repo", self.host_repository,
                    "--verify-tag", "--draft", "--target", self.candidate_commit,
                    "--title", CANONICAL_RELEASE_TITLE,
                    "--notes", CANONICAL_RELEASE_BODY,
                ),
                cwd=self.source_root,
            )
        elif action == "asset_upload":
            name, path = self._asset_path(operation_id)
            expected_hash = expected_before.get("asset_sha256")
            expected_size = expected_before.get("asset_size")
            if expected_hash != _file_sha256(path) or expected_size != path.stat().st_size:
                _fail("E_V240_DRAFT_ASSET_IDENTITY", f"asset expected-before digest drift: {name}")
            _run(("gh", "release", "upload", self.tag, str(path), "--repo", self.host_repository), cwd=self.source_root)
        elif action in {"asset_download_verify", "published_asset_download"}:
            # The read-only observer above already performed the byte compare.
            pass
        elif action == "release_publish":
            expected_assets_sha = expected_before.get("draft_asset_set_sha256")
            local_assets = self._local_asset_set()
            if expected_assets_sha != _canonical_sha256(local_assets):
                _fail("E_V240_DRAFT_ASSET_IDENTITY", "publish intent is not bound to the verified four-asset set")
            if expected_before.get("candidate_commit") != self.candidate_commit or expected_before.get("tag") != self.tag:
                _fail("E_V240_RELEASE_SOURCE_IDENTITY", "publish intent identity drift")
            live_draft = self._release_json()
            if (
                not isinstance(live_draft, Mapping)
                or live_draft.get("isDraft") is not True
                or live_draft.get("databaseId") != expected_before.get("release_id")
            ):
                _fail("E_V240_REMOTE_RESOURCE_CONFLICT", "publish Draft release-id CAS failed")
            # Publish-last: immediately re-download and byte-compare the Draft
            # before changing its state.  The shell's post-publish verification
            # remains a postcondition and is not used as this gate.
            self._run_release_adapter("download")
            self._run_release_adapter("publish")
        elif action == "post_release_ci":
            workflow = parameters.get("workflow")
            if workflow != ".github/workflows/release-gate.yml":
                _fail("E_V240_CI_TRUST_BINDING", "unapproved post-release workflow")
            release_intent = parameters.get("_release_intent")
            if not isinstance(release_intent, str) or re.fullmatch(r"[0-9a-f]{64}", release_intent) is None:
                _fail("E_V240_CI_INTENT", "post-release workflow dispatch intent is missing")
            _run(
                (
                    "gh", "workflow", "run", workflow,
                    "--repo", self.host_repository,
                    "--ref", "main",
                    "--raw-field", f"release_intent={release_intent}",
                ),
                cwd=self.source_root,
                env={"GH_HOST": GITHUB_HOST},
            )
            _fail(
                "E_V240_CI_PENDING",
                "workflow dispatched; recover with the resulting run_id after it completes",
                external_side_effect_count=1,
            )
        else:
            _fail("E_V240_ADAPTER_UNSUPPORTED", f"no fixed mutation for {operation_id} ({action})")

        after_parameters = dict(parameters)
        if action == "promotion_lock_finalize":
            after_parameters["_post_mutation"] = True
        after = self.observe(
            operation_id=operation_id,
            action=action,
            expected_before=expected_before,
            parameters=after_parameters,
        )
        if after.get("classification") != "exact":
            _fail(
                "E_V240_ADAPTER_POSTCONDITION",
                f"mutation completed without exact live readback for {operation_id}",
                external_side_effect_count=1,
            )
        after["external_side_effect_count"] = 1
        return after


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
