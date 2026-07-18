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
TAGGER_IDENT_RE = re.compile(
    r"^(?P<name>.+) <(?P<email>[^<>\s]+)> -?[0-9]+ [+-][0-9]{4}$"
)
FORBIDDEN_TAGGER_IDENTITY_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:test|testing|fixture|dummy|example)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
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
PERMANENT_TAG_RULESET_NAME = "goal-teams-tag-protection"
FIXED_WORKFLOW_PATH = ".github/workflows/release-gate.yml"
FIXED_WORKFLOW_FILE = "release-gate.yml"
EXCLUSIVE_PUBLISH_BINDING_SCHEMA = (
    "goal-teams-exclusive-release-publish-binding-v1"
)


def _validated_product_version(value: str) -> str:
    if VERSION_RE.fullmatch(value) is None:
        _fail("E_V240_ADAPTER_IDENTITY", "invalid version identity")
    return value


def canonical_release_title(version: str) -> str:
    return f"Goal Teams {_validated_product_version(version)}"


def canonical_release_body(version: str) -> str:
    title = canonical_release_title(version)
    return f"{title}. See release/current/README.md in the tagged source."


def canonical_tag_message(version: str) -> str:
    return canonical_release_title(version)


# Compatibility exports for test fixtures and callers that compare the current
# release.  They are still derived from the module source tree; production
# adapter operations use the independently verified instance VERSION below.
MODULE_PRODUCT_VERSION = (
    Path(__file__).resolve().parents[2] / "VERSION"
).read_text(encoding="utf-8").strip()
CANONICAL_RELEASE_TITLE = canonical_release_title(MODULE_PRODUCT_VERSION)
CANONICAL_RELEASE_BODY = canonical_release_body(MODULE_PRODUCT_VERSION)
CANONICAL_TAG_MESSAGE = canonical_tag_message(MODULE_PRODUCT_VERSION)


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
        version = _validated_product_version(version)
        if SHA40_RE.fullmatch(candidate_commit) is None or SHA40_RE.fullmatch(
            base_main_commit
        ) is None:
            _fail("E_V240_ADAPTER_IDENTITY", "invalid frozen Git identity")
        self.source_root = source_root.resolve()
        self.workspace_root = workspace_root.resolve()
        version_path = self.source_root / "VERSION"
        try:
            source_version = version_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            _fail(
                "E_V240_ADAPTER_IDENTITY",
                f"cannot read source-tree VERSION: {exc}",
            )
        if source_version != version or VERSION_RE.fullmatch(source_version) is None:
            _fail(
                "E_V240_ADAPTER_IDENTITY",
                "adapter version differs from the verified source-tree VERSION",
            )
        self.repository = repository
        self.host_repository = f"{GITHUB_HOST}/{repository}"
        self.version = version
        self.tag = f"v{version[1:]}"
        self.release_title = canonical_release_title(version)
        self.release_body = canonical_release_body(version)
        self.tag_message = canonical_tag_message(version)
        self.candidate_commit = candidate_commit
        self.base_main_commit = base_main_commit
        self.authority = dict(authority)
        self.execute_external_writes = execute_external_writes
    def _require_external_exclusive_publish_host(
        self,
        expected_before: Mapping[str, Any],
    ) -> None:
        """Return only a fail-closed binding for the external publish host.

        GitHub's update-release endpoint does not document an asset-sensitive
        conditional request.  The candidate repository therefore has no
        positive publish-authority path: no object, callback, config value, or
        serialized receipt supplied by candidate code can unlock the PATCH.
        A repository-external host must independently re-read this exact
        binding inside its own exclusive window and perform the mutation.
        """

        release_id = self._frozen_release_id(expected_before)
        binding = {
            "schema_version": EXCLUSIVE_PUBLISH_BINDING_SCHEMA,
            "repository": self.repository,
            "version": self.version,
            "tag": self.tag,
            "candidate_commit": self.candidate_commit,
            "release_id": release_id,
            "draft_asset_set_sha256": expected_before.get(
                "draft_asset_set_sha256"
            ),
            "draft_asset_identity_sha256": expected_before.get(
                "draft_asset_identity_sha256"
            ),
        }
        if (
            SHA256_RE.fullmatch(
                str(binding["draft_asset_set_sha256"] or "")
            )
            is None
            or SHA256_RE.fullmatch(
                str(binding["draft_asset_identity_sha256"] or "")
            )
            is None
        ):
            _fail(
                "E_V240_ADAPTER_EXPECTED_BEFORE",
                "exclusive publish binding lacks the frozen asset identity",
            )
        binding_sha256 = _canonical_sha256(binding)
        _fail(
            "E_V240_EXCLUSIVE_HOST_AUTHORITY_REQUIRED",
            "CP17 publish requires a real repository-external exclusive host",
            required_binding=binding,
            required_binding_sha256=binding_sha256,
        )

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
        tagger_value = tag_value.get("tagger") if isinstance(tag_value, Mapping) else None
        if (
            not isinstance(tag_value, Mapping)
            or tag_value.get("tag") != tag
            or not isinstance(target, Mapping)
            or target.get("type") != "commit"
            or SHA40_RE.fullmatch(str(target.get("sha", ""))) is None
            or not isinstance(tag_value.get("message"), str)
            or not isinstance(tagger_value, Mapping)
        ):
            _fail("E_V240_ADAPTER_READBACK", "malformed annotated REST tag")
        tagger = self._validate_release_tagger_identity(
            tagger_value.get("name"), tagger_value.get("email")
        )
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
            "tagger_name": tagger["name"],
            "tagger_email": tagger["email"],
            "tagger_identity_sha256": tagger["identity_sha256"],
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

    def _release_json(self, release_id: int | None = None) -> Mapping[str, Any] | None:
        """Read one Release, optionally through its frozen numeric identity."""

        if release_id is not None and (
            not isinstance(release_id, int)
            or isinstance(release_id, bool)
            or release_id < 1
        ):
            _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "invalid frozen Release id")
        endpoint = (
            f"repos/{self.repository}/releases/{release_id}"
            if release_id is not None
            else f"repos/{self.repository}/releases/tags/{self.tag}"
        )
        value = self._gh_api(endpoint, not_found_ok=True)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            _fail("E_V240_ADAPTER_READBACK", "Release response is not an object")
        observed_id = value.get("id")
        if (
            not isinstance(observed_id, int)
            or isinstance(observed_id, bool)
            or observed_id < 1
            or (release_id is not None and observed_id != release_id)
        ):
            _fail("E_V240_ADAPTER_READBACK", "Release numeric identity is malformed")
        assets = value.get("assets")
        if not isinstance(assets, list):
            _fail("E_V240_ADAPTER_READBACK", "REST Release assets are not an array")
        normalized_assets: list[dict[str, Any]] = []
        for asset in assets:
            if (
                not isinstance(asset, Mapping)
                or not isinstance(asset.get("id"), int)
                or isinstance(asset.get("id"), bool)
                or asset.get("id", 0) < 1
                or not isinstance(asset.get("name"), str)
                or not isinstance(asset.get("size"), int)
                or isinstance(asset.get("size"), bool)
                or asset.get("size", -1) < 0
            ):
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
            "databaseId": observed_id,
            "isDraft": value.get("draft"),
            "isImmutable": value.get("immutable"),
            "isPrerelease": value.get("prerelease"),
            "tagName": value.get("tag_name"),
            "targetCommitish": value.get("target_commitish"),
            "name": value.get("name"),
            "body": value.get("body"),
            "publishedAt": value.get("published_at"),
            "assets": normalized_assets,
            "url": value.get("html_url"),
        }

    @staticmethod
    def _frozen_release_id(expected_before: Mapping[str, Any]) -> int:
        release_id = expected_before.get("release_id")
        if (
            not isinstance(release_id, int)
            or isinstance(release_id, bool)
            or release_id < 1
        ):
            _fail(
                "E_V240_ADAPTER_EXPECTED_BEFORE",
                "frozen numeric Release id is required",
            )
        return release_id

    @staticmethod
    def _frozen_draft_asset_identity(expected_before: Mapping[str, Any]) -> str:
        digest = expected_before.get("draft_asset_identity_sha256")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            _fail(
                "E_V240_ADAPTER_EXPECTED_BEFORE",
                "frozen Draft REST asset identity digest is required",
            )
        return digest

    def _download_release_asset(self, asset_id: int, destination: Path) -> None:
        """Download one asset by immutable numeric asset id, never by tag."""

        if (
            not isinstance(asset_id, int)
            or isinstance(asset_id, bool)
            or asset_id < 1
        ):
            _fail("E_V240_ADAPTER_READBACK", "Release asset id is malformed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _require_github_dot_com_host()
        with destination.open("wb") as stream:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{self.repository}/releases/assets/{asset_id}",
                    "--hostname",
                    GITHUB_HOST,
                    "-H",
                    "Accept: application/octet-stream",
                ],
                cwd=self.source_root,
                env={**os.environ, "GH_HOST": GITHUB_HOST},
                stdout=stream,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            destination.unlink(missing_ok=True)
            stderr = result.stderr.decode("utf-8", errors="replace")
            _fail(
                "E_V240_ADAPTER_READBACK",
                "cannot download frozen Release asset",
                stderr=stderr[-2000:],
            )

    def _upload_release_asset(
        self,
        release_id: int,
        name: str,
        path: Path,
        *,
        operation_id: str,
        action: str,
        parameters: Mapping[str, Any],
    ) -> None:
        """Upload one asset to the frozen numeric Draft Release id."""

        if release_id < 1 or not path.is_file() or path.is_symlink():
            _fail("E_V240_DRAFT_ASSET_IDENTITY", "invalid numeric asset upload input")
        endpoint = (
            f"https://uploads.github.com/repos/{self.repository}/releases/"
            f"{release_id}/assets?name={quote(name, safe='')}"
        )
        self._validate_remote_mutation_guard(operation_id, action, parameters)
        _run(
            (
                "gh",
                "api",
                endpoint,
                "--hostname",
                GITHUB_HOST,
                "--method",
                "POST",
                "-H",
                "Content-Type: application/octet-stream",
                "--input",
                str(path),
            ),
            cwd=self.source_root,
            env={"GH_HOST": GITHUB_HOST},
        )

    def _local_tag_identity(self) -> dict[str, Any] | None:
        """Read the local tag as an annotated object with exact message/target."""

        ref = f"refs/tags/{self.tag}"
        exists = subprocess.run(
            _git_argv(("git", "show-ref", "--verify", "--quiet", ref)),
            cwd=self.source_root,
            env=_git_environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        if exists.returncode == 1:
            return None
        if exists.returncode != 0:
            _fail("E_V240_ADAPTER_COMMAND", "cannot inspect local tag")
        object_type = _run(("git", "cat-file", "-t", ref), cwd=self.source_root).stdout.strip()
        tag_object = _run(("git", "rev-parse", ref), cwd=self.source_root).stdout.strip()
        if SHA40_RE.fullmatch(tag_object) is None:
            _fail("E_V240_TAG_OBJECT_IDENTITY", "local tag object id is malformed")
        peeled_commit = _run(
            ("git", "rev-parse", f"{ref}^{{}}"), cwd=self.source_root
        ).stdout.strip()
        message = _run(
            ("git", "for-each-ref", "--format=%(contents)", ref),
            cwd=self.source_root,
        ).stdout.rstrip("\n")
        tagger: dict[str, str] | None = None
        if object_type == "tag":
            raw_object = _run(
                ("git", "cat-file", "-p", ref), cwd=self.source_root
            ).stdout
            header, separator, _body = raw_object.partition("\n\n")
            tagger_rows = [
                line.removeprefix("tagger ")
                for line in header.splitlines()
                if line.startswith("tagger ")
            ]
            if not separator or len(tagger_rows) != 1:
                _fail(
                    "E_V240_TAG_OBJECT_IDENTITY",
                    "local annotated tag has a malformed tagger header",
                )
            matched = TAGGER_IDENT_RE.fullmatch(tagger_rows[0])
            if matched is None:
                _fail(
                    "E_V240_TAG_OBJECT_IDENTITY",
                    "local annotated tag tagger identity is malformed",
                )
            tagger = self._validate_release_tagger_identity(
                matched.group("name"), matched.group("email")
            )
        return {
            "tag": self.tag,
            "annotated": object_type == "tag",
            "tag_object": tag_object,
            "peeled_commit": peeled_commit,
            "message": message,
            "tagger_name": tagger["name"] if tagger is not None else None,
            "tagger_email": tagger["email"] if tagger is not None else None,
            "tagger_identity_sha256": (
                tagger["identity_sha256"] if tagger is not None else None
            ),
        }

    @staticmethod
    def _validate_release_tagger_identity(name: Any, email: Any) -> dict[str, str]:
        """Validate a human release tagger without changing Git configuration."""

        normalized_name = name.strip() if isinstance(name, str) else ""
        normalized_email = email.strip() if isinstance(email, str) else ""
        lowered_email = normalized_email.lower()
        if (
            not normalized_name
            or not normalized_email
            or "@" not in normalized_email
            or lowered_email.endswith(".invalid")
            or FORBIDDEN_TAGGER_IDENTITY_RE.search(normalized_name) is not None
            or FORBIDDEN_TAGGER_IDENTITY_RE.search(normalized_email) is not None
        ):
            _fail(
                "E_V240_RELEASE_TAGGER_IDENTITY",
                "effective release tagger identity is absent or fixture-like",
            )
        identity = {"name": normalized_name, "email": normalized_email}
        return {
            **identity,
            "identity_sha256": _canonical_sha256(identity),
        }

    def _effective_release_tagger_identity(self) -> dict[str, str]:
        """Freeze the identity Git would use for an annotated release tag."""

        value = _run(
            ("git", "var", "GIT_COMMITTER_IDENT"), cwd=self.source_root
        ).stdout.strip()
        matched = TAGGER_IDENT_RE.fullmatch(value)
        if matched is None:
            _fail(
                "E_V240_RELEASE_TAGGER_IDENTITY",
                "cannot parse the effective release tagger identity",
            )
        return self._validate_release_tagger_identity(
            matched.group("name"), matched.group("email")
        )

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
            or expected_before.get("name") != self.release_title
            or expected_before.get("body") != self.release_body
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

    def _verify_exact_draft_for_publish(
        self,
        expected_before: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Re-read canonical Draft metadata and all four asset identities.

        The candidate adapter calls this before and after its mutation-edge
        guard, then fails closed for lack of host authority.  A real external
        host must repeat the same projection inside its exclusive window as the
        final zero-write gate before PATCH.  GitHub exposes no documented,
        asset-sensitive strong ETag, so no conditional-write claim is made.
        """

        release_id = self._frozen_release_id(expected_before)
        live_draft = self._release_json(release_id)
        resolved_target = (
            self._resolve_target_commitish(live_draft.get("targetCommitish"))
            if isinstance(live_draft, Mapping)
            else None
        )
        if (
            not isinstance(live_draft, Mapping)
            or live_draft.get("isDraft") is not True
            or live_draft.get("isImmutable") is not False
            or live_draft.get("isPrerelease") is not False
            or live_draft.get("databaseId") != release_id
            or live_draft.get("tagName") != self.tag
            or live_draft.get("targetCommitish") != self.candidate_commit
            or resolved_target != self.candidate_commit
            or live_draft.get("name") != self.release_title
            or live_draft.get("body") != self.release_body
        ):
            _fail(
                "E_V240_REMOTE_RESOURCE_CONFLICT",
                "publish Draft metadata/target changed before PATCH",
            )
        bundle = self._persist_verified_bundle(
            live_draft,
            expected_draft=True,
            expected_asset_identity_sha256=self._frozen_draft_asset_identity(
                expected_before
            ),
        )
        expected_assets_sha = expected_before.get("draft_asset_set_sha256")
        expected_identity_sha = expected_before.get(
            "draft_asset_identity_sha256"
        )
        if (
            bundle.get("asset_set_sha256") != expected_assets_sha
            or bundle.get("asset_identity_sha256") != expected_identity_sha
        ):
            _fail(
                "E_V240_DRAFT_ASSET_IDENTITY",
                "publish Draft four-asset identity changed before PATCH",
            )
        return {
            "release_id": release_id,
            "resolved_target": resolved_target,
            "asset_set_sha256": expected_assets_sha,
            "asset_identity_sha256": expected_identity_sha,
        }

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

    def _fixed_workflow_identity(
        self,
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind the fixed workflow's numeric API identity to its Git source."""

        approved_id = approval.get("workflow_id")
        if (
            approval.get("workflow_path") != FIXED_WORKFLOW_PATH
            or not isinstance(approved_id, int)
            or isinstance(approved_id, bool)
            or approved_id < 1
            or SHA40_RE.fullmatch(str(approval.get("workflow_blob_sha", "")))
            is None
        ):
            _fail(
                "E_V240_CI_TRUST_BINDING",
                "CI approval lacks the fixed workflow numeric/source identity",
            )
        value = self._gh_api(
            f"repos/{self.repository}/actions/workflows/{FIXED_WORKFLOW_FILE}"
        )
        if (
            not isinstance(value, Mapping)
            or value.get("id") != approved_id
            or value.get("path") != FIXED_WORKFLOW_PATH
            or value.get("state") != "active"
        ):
            _fail(
                "E_V240_CI_TRUST_BINDING",
                "live workflow id/path/state differs from the CP05 approval",
            )
        blob = _run(
            (
                "git",
                "rev-parse",
                f"{self.candidate_commit}:{FIXED_WORKFLOW_PATH}",
            ),
            cwd=self.source_root,
        ).stdout.strip()
        if (
            SHA40_RE.fullmatch(blob) is None
            or blob != approval.get("workflow_blob_sha")
        ):
            _fail(
                "E_V240_CI_TRUST_BINDING",
                "fixed workflow source blob differs from the CP05 approval",
            )
        return {
            "workflow_id": approved_id,
            "source_path": FIXED_WORKFLOW_PATH,
            "source_blob_sha": blob,
        }

    @staticmethod
    def _canonical_run_workflow_path(raw_path: Any) -> dict[str, Any]:
        """Accept only the fixed path or GitHub's exact ``@main`` suffix."""

        if raw_path == FIXED_WORKFLOW_PATH:
            raw_ref: str | None = None
        elif raw_path == f"{FIXED_WORKFLOW_PATH}@main":
            raw_ref = "main"
        else:
            _fail(
                "E_V240_CI_TRUST_BINDING",
                "Actions run path is not the fixed workflow source path",
                workflow_raw_path=raw_path,
            )
        return {
            "source_path": FIXED_WORKFLOW_PATH,
            "raw_path": raw_path,
            "raw_ref": raw_ref,
        }

    def _all_workflow_runs(self, workflow_id: int) -> list[Mapping[str, Any]]:
        """Read every page for one numeric workflow, without server filters.

        GitHub documents a 1,000-result cap when workflow-run query filters are
        used.  Recovery therefore paginates the unfiltered numeric-workflow
        endpoint and applies every event/head/actor/intent predicate locally.
        """

        if (
            not isinstance(workflow_id, int)
            or isinstance(workflow_id, bool)
            or workflow_id < 1
        ):
            _fail("E_V240_CI_TRUST_BINDING", "workflow id is invalid")
        payload = self._gh_api(
            f"repos/{self.repository}/actions/workflows/"
            f"{workflow_id}/runs?per_page=100",
            "--paginate",
            "--slurp",
        )
        pages: list[Any]
        if isinstance(payload, Mapping):
            pages = [payload]
        elif isinstance(payload, list):
            pages = payload
        else:
            _fail(
                "E_V240_CI_TRUST_BINDING",
                "paginated workflow-run response is malformed",
            )
        runs: list[Mapping[str, Any]] = []
        for page in pages:
            page_runs = page.get("workflow_runs") if isinstance(page, Mapping) else None
            if not isinstance(page_runs, list) or any(
                not isinstance(run, Mapping) for run in page_runs
            ):
                _fail(
                    "E_V240_CI_TRUST_BINDING",
                    "workflow-run page is malformed",
                )
            runs.extend(page_runs)
        return runs

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
        release_id = self._frozen_release_id(expected_before)
        release = self._release_json(release_id)
        name, local_path = self._asset_path(operation_id)
        local_hash = _file_sha256(local_path)
        local_size = local_path.stat().st_size
        if expected_before.get("asset_sha256") != local_hash or expected_before.get("asset_size") != local_size:
            _fail("E_V240_DRAFT_ASSET_IDENTITY", f"asset expected-before drift: {name}")
        if release is None:
            return self._readback(
                "github_api",
                {
                    "classification": "absent",
                    "asset": name,
                    "tag": self.tag,
                    "release_id": release_id,
                },
            )
        if (
            release.get("databaseId") != release_id
            or release.get("isDraft") is not True
            or release.get("tagName") != self.tag
        ):
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
            downloaded = Path(directory) / name
            self._download_release_asset(metadata.get("id"), downloaded)
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

    def _release_asset_identity(self, release: Mapping[str, Any]) -> dict[str, Any]:
        """Canonicalize live REST asset ids against the sealed local bytes."""

        local_assets = self._local_asset_set()
        metadata_assets = release.get("assets")
        if not isinstance(metadata_assets, list) or len(metadata_assets) != len(
            local_assets
        ):
            _fail(
                "E_V240_DRAFT_ASSET_IDENTITY",
                "Release is not the fixed four-asset identity set",
            )
        metadata_by_name: dict[str, Mapping[str, Any]] = {}
        asset_ids: set[int] = set()
        rows: list[dict[str, Any]] = []
        for metadata in metadata_assets:
            if not isinstance(metadata, Mapping):
                _fail(
                    "E_V240_DRAFT_ASSET_IDENTITY",
                    "REST asset identity row is malformed",
                )
            name = metadata.get("name")
            asset_id = metadata.get("id")
            size = metadata.get("size")
            if (
                not isinstance(name, str)
                or name not in local_assets
                or name in metadata_by_name
                or not isinstance(asset_id, int)
                or isinstance(asset_id, bool)
                or asset_id < 1
                or asset_id in asset_ids
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size != local_assets.get(name, {}).get("size")
            ):
                _fail(
                    "E_V240_DRAFT_ASSET_IDENTITY",
                    "REST asset name/id/size identity drift",
                )
            local_sha256 = local_assets[name]["sha256"]
            if metadata.get("digest") != f"sha256:{local_sha256}":
                _fail(
                    "E_V240_DRAFT_ASSET_IDENTITY",
                    f"REST asset digest drift: {name}",
                )
            metadata_by_name[name] = metadata
            asset_ids.add(asset_id)
            rows.append(
                {
                    "name": name,
                    "asset_id": asset_id,
                    "size": size,
                    "sha256": local_sha256,
                }
            )
        if set(metadata_by_name) != set(local_assets):
            _fail(
                "E_V240_DRAFT_ASSET_IDENTITY",
                "REST asset names differ from the sealed four-asset set",
            )
        rows.sort(key=lambda row: row["name"])
        return {
            "local_assets": local_assets,
            "metadata_by_name": metadata_by_name,
            "rows": rows,
            "sha256": _canonical_sha256(rows),
        }

    def _persist_verified_bundle(
        self,
        release: Mapping[str, Any],
        *,
        expected_draft: bool,
        expected_asset_identity_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Download the fixed four assets into an ignored, identity-bound bundle."""

        # This gate intentionally precedes parent.mkdir/tempfile creation.  A
        # delete/re-upload can preserve bytes while changing REST asset ids;
        # such a Release must not pollute the persisted bundle or be published.
        asset_identity = self._release_asset_identity(release)
        if expected_asset_identity_sha256 is not None and (
            SHA256_RE.fullmatch(str(expected_asset_identity_sha256)) is None
            or asset_identity["sha256"] != expected_asset_identity_sha256
        ):
            _fail(
                "E_V240_DRAFT_ASSET_IDENTITY",
                "live REST asset ids differ from the frozen Draft identity",
            )
        local_assets = asset_identity["local_assets"]
        metadata_by_name = asset_identity["metadata_by_name"]
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
            release_id = release.get("databaseId")
            if (
                not isinstance(release_id, int)
                or isinstance(release_id, bool)
                or release_id < 1
            ):
                _fail("E_V240_ADAPTER_READBACK", "Release numeric identity is missing")
            for name in sorted(local_assets):
                metadata = metadata_by_name[name]
                asset_id = metadata.get("id")
                if (
                    not isinstance(asset_id, int)
                    or isinstance(asset_id, bool)
                    or asset_id < 1
                ):
                    _fail("E_V240_ADAPTER_READBACK", f"Release asset id is missing: {name}")
                self._download_release_asset(asset_id, temp / name)
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
                if digest_metadata != f"sha256:{expected['sha256']}":
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
                "asset_identity_sha256": asset_identity["sha256"],
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
        if not isinstance(values, list):
            _fail("E_V240_ADAPTER_READBACK", "ruleset response is not an array")
        flattened: list[Mapping[str, Any]] = []
        if all(isinstance(value, Mapping) for value in values):
            flattened = list(values)
        elif all(isinstance(page, list) for page in values):
            for page in values:
                if any(not isinstance(value, Mapping) for value in page):
                    _fail(
                        "E_V240_ADAPTER_READBACK",
                        "ruleset page contains a malformed row",
                    )
                flattened.extend(page)
        else:
            _fail(
                "E_V240_ADAPTER_READBACK",
                "ruleset pagination shape is malformed",
            )
        matches = [value for value in flattened if value.get("name") == name]
        if len(matches) > 1:
            _fail("E_V240_REMOTE_RESOURCE_CONFLICT", f"duplicate ruleset name: {name}")
        if not matches:
            return None
        ruleset_id = matches[0].get("id")
        if not isinstance(ruleset_id, int) or ruleset_id < 1:
            _fail("E_V240_ADAPTER_READBACK", "ruleset id is missing")
        detail = self._gh_api(f"repos/{self.repository}/rulesets/{ruleset_id}")
        if (
            not isinstance(detail, Mapping)
            or detail.get("id") != ruleset_id
            or detail.get("name") != name
        ):
            _fail(
                "E_V240_ADAPTER_READBACK",
                "ruleset detail does not match its live list identity",
            )
        return detail

    def _classic_main_protection_compatibility(
        self,
        *,
        actor_login: str,
        actor_is_admin: bool,
    ) -> dict[str, Any]:
        """Fail closed when classic protection can block the release lease.

        Repository rulesets and classic branch protection are cumulative.  A
        reusable ruleset bypass therefore does not prove that the release actor
        can perform the exact main update when classic protection remains.  We
        accept an absent classic policy, an admin-bypass policy, or an explicit
        force-push policy with no direct-push blockers and an actor-compatible
        restriction list.
        """

        value = self._gh_api(
            f"repos/{self.repository}/branches/main/protection",
            not_found_ok=True,
        )
        endpoint_sha256 = _canonical_sha256(value)
        if value is None:
            return {
                "present": False,
                "release_actor_can_force_with_lease": True,
                "compatibility_mode": "absent",
                "endpoint_sha256": endpoint_sha256,
            }
        if not isinstance(value, Mapping):
            _fail(
                "E_V240_CLASSIC_BRANCH_PROTECTION",
                "classic main protection response is malformed",
            )

        def enabled(name: str) -> bool:
            record = value.get(name)
            return isinstance(record, Mapping) and record.get("enabled") is True

        restrictions = value.get("restrictions")
        restrictions_allow_actor = restrictions is None
        if restrictions is not None:
            if not isinstance(restrictions, Mapping):
                _fail(
                    "E_V240_CLASSIC_BRANCH_PROTECTION",
                    "classic main push restrictions are malformed",
                )
            users = restrictions.get("users")
            if not isinstance(users, list) or any(
                not isinstance(user, Mapping) for user in users
            ):
                _fail(
                    "E_V240_CLASSIC_BRANCH_PROTECTION",
                    "classic main user restrictions are malformed",
                )
            restrictions_allow_actor = any(
                user.get("login") == actor_login for user in users
            )

        enforce_admins = enabled("enforce_admins")
        admin_bypass = actor_is_admin and not enforce_admins
        direct_push_blockers = {
            "required_status_checks": value.get("required_status_checks")
            is not None,
            "required_pull_request_reviews": value.get(
                "required_pull_request_reviews"
            )
            is not None,
            "required_signatures": enabled("required_signatures"),
            "required_linear_history": enabled("required_linear_history"),
            "lock_branch": enabled("lock_branch"),
        }
        explicit_force_path = (
            enabled("allow_force_pushes")
            and restrictions_allow_actor
            and not any(direct_push_blockers.values())
        )
        compatible = admin_bypass or explicit_force_path
        receipt = {
            "present": True,
            "release_actor_can_force_with_lease": compatible,
            "compatibility_mode": (
                "admin_bypass"
                if admin_bypass
                else "explicit_force_push"
                if explicit_force_path
                else "conflict"
            ),
            "enforce_admins": enforce_admins,
            "allow_force_pushes": enabled("allow_force_pushes"),
            "restrictions_allow_actor": restrictions_allow_actor,
            "direct_push_blockers": direct_push_blockers,
            "endpoint_sha256": endpoint_sha256,
        }
        if not compatible:
            _fail(
                "E_V240_CLASSIC_BRANCH_PROTECTION",
                "classic main protection can block the release actor lease",
                classic_main_protection=receipt,
            )
        return receipt

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
        classic_main = self._classic_main_protection_compatibility(
            actor_login=str(user.get("login") or ""),
            actor_is_admin=admin,
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
            "classic_main_protection": classic_main,
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
            "classic_main_protection",
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
        excludes = ref_name.get("exclude") if isinstance(ref_name, Mapping) else None
        rules = normalized["rules"]
        rule_types = {rule.get("type") for rule in rules}
        rules_by_type = {rule["type"]: rule for rule in rules}
        exact_ref_condition = (
            set(conditions) == {"ref_name"}
            and isinstance(ref_name, Mapping)
            and set(ref_name) == {"include", "exclude"}
            and isinstance(includes, list)
            and len(includes) == 1
            and excludes == []
        )
        if len(rules_by_type) != len(rules):
            _fail("E_V240_RULESET_IDENTITY", "duplicate ruleset rule type")
        if normalized["enforcement"] != "active":
            _fail("E_V240_RULESET_IDENTITY", "release rulesets must be active")
        if action == "tag_ruleset_create":
            update_parameters = rules_by_type.get("update", {}).get("parameters")
            if (
                normalized["name"] != PERMANENT_TAG_RULESET_NAME
                or normalized["target"] != "tag"
                or normalized["bypass_actors"] != []
                or not exact_ref_condition
                or includes != ["refs/tags/v*"]
                or rule_types != {"update", "deletion"}
                or update_parameters
                != {"update_allows_fetch_and_merge": False}
            ):
                _fail("E_V240_TAG_RULESET", "tag ruleset is not the permanent v* update/deletion lock")
        elif action in {"promotion_lock_create", "promotion_lock_finalize"}:
            expected_bypass = [
                {
                    "actor_id": self.authority.get("actor_id"),
                    "actor_type": "User",
                    "bypass_mode": "always",
                }
            ]
            required = {
                "deletion",
                "non_fast_forward",
                "pull_request",
                "required_status_checks",
            }
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
                normalized["name"] != "goal-teams-main-protection"
                or normalized["target"] != "branch"
                or normalized["bypass_actors"] != expected_bypass
                or not exact_ref_condition
                or includes != ["refs/heads/main"]
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
                or pull_parameters.get("require_code_owner_review") is not False
                or pull_parameters.get("require_last_push_approval") is not True
                or pull_parameters.get("required_approving_review_count") != 1
                or pull_parameters.get("required_review_thread_resolution") is not True
            ):
                _fail(
                    "E_V240_PROMOTION_LOCK",
                    "main ruleset is not the exact reusable release-actor protection policy",
                )

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
            if (
                "remote_candidate_commit" not in expected_before
                or expected_before.get("remote_candidate_commit")
                not in {None, self.candidate_commit}
            ):
                _fail(
                    "E_V240_ADAPTER_EXPECTED_BEFORE",
                    "candidate ref expected-before lease is missing or invalid",
                )
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
            if (
                "remote_tag_commit" not in expected_before
                or expected_before.get("remote_tag_commit") is not None
            ):
                _fail(
                    "E_V240_ADAPTER_EXPECTED_BEFORE",
                    "tag creation requires an explicit absent expected-before lease",
                )
            tag_identity = self._remote_tag_identity(self.tag)
            tag_object = tag_identity.get("tag_object") if tag_identity else None
            value = tag_identity.get("peeled_commit") if tag_identity else None
            message = tag_identity.get("message") if tag_identity else None
            tagger_name = tag_identity.get("tagger_name") if tag_identity else None
            tagger_email = tag_identity.get("tagger_email") if tag_identity else None
            tagger_identity_sha256 = (
                tag_identity.get("tagger_identity_sha256") if tag_identity else None
            )
            classification = "exact" if (
                value == self.candidate_commit
                and tag_object is not None
                and message == self.tag_message
                and SHA256_RE.fullmatch(str(tagger_identity_sha256 or ""))
                is not None
            ) else (
                "absent" if tag_identity is None else "conflict"
            )
            return self._readback(
                "git_ls_remote",
                {
                    "classification": classification,
                    "tag": self.tag,
                    "tag_object": tag_object,
                    "peeled_commit": value,
                    "message": message,
                    "tagger_name": tagger_name,
                    "tagger_email": tagger_email,
                    "tagger_identity_sha256": tagger_identity_sha256,
                },
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
            release_id = self._frozen_release_id(expected_before)
            expected_asset_identity_sha256 = (
                self._frozen_draft_asset_identity(expected_before)
                if action == "published_asset_download"
                else None
            )
            release = self._release_json(release_id)
            expected_draft = action == "asset_download_verify"
            if release is None:
                return self._readback(
                    "github_api",
                    {
                        "classification": "absent",
                        "tag": self.tag,
                        "release_id": release_id,
                    },
                )
            if (
                release.get("databaseId") != release_id
                or
                release.get("tagName") != self.tag
                or (release.get("isDraft") is True) != expected_draft
            ):
                return self._readback("github_api", {"classification": "conflict", "release": dict(release)})
            # Downloading and byte-comparing is a read-only live observation,
            # not a remote mutation.  The ignored persisted bundle is the
            # only input later rehearsal/actual-install operations may use.
            try:
                bundle = self._persist_verified_bundle(
                    release,
                    expected_draft=expected_draft,
                    expected_asset_identity_sha256=expected_asset_identity_sha256,
                )
            except AdapterError as exc:
                return self._readback(
                    "github_api",
                    {
                        "classification": "conflict",
                        "release_id": release_id,
                        "release_state": "draft" if expected_draft else "published",
                        "asset_identity_error": exc.receipt.get("error_code"),
                    },
                )
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
            expected_asset_identity_sha256 = (
                self._frozen_draft_asset_identity(expected_before)
                if action == "release_publish"
                else None
            )
            release = self._release_json(
                expected_release_id if action == "release_publish" else None
            )
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
                    and release.get("targetCommitish")
                    == self.candidate_commit
                    and resolved_target == self.candidate_commit
                    and release.get("name") == self.release_title
                    and release.get("body") == self.release_body
                    and release.get("isPrerelease") is False
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
                live_asset_identity_sha256: str | None = None
                asset_identity_error: str | None = None
                if (
                    action == "release_publish"
                    and canonical_metadata
                    and release.get("databaseId") == expected_release_id
                ):
                    try:
                        live_asset_identity_sha256 = self._release_asset_identity(
                            release
                        )["sha256"]
                    except AdapterError as exc:
                        asset_identity_error = str(
                            exc.receipt.get("error_code")
                        )
                        classification = "conflict"
                    else:
                        if (
                            live_asset_identity_sha256
                            != expected_asset_identity_sha256
                        ):
                            asset_identity_error = (
                                "E_V240_DRAFT_ASSET_IDENTITY"
                            )
                            classification = "conflict"
                details = {
                    "classification": classification,
                    **dict(release),
                    "resolvedTargetCommit": resolved_target,
                    "asset_identity_sha256": live_asset_identity_sha256,
                    "asset_identity_error": asset_identity_error,
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
                    details["taggerName"] = (
                        tag_identity.get("tagger_name") if tag_identity else None
                    )
                    details["taggerEmail"] = (
                        tag_identity.get("tagger_email") if tag_identity else None
                    )
                    details["taggerIdentitySha256"] = (
                        tag_identity.get("tagger_identity_sha256")
                        if tag_identity
                        else None
                    )
                    tag_exact = (
                        isinstance(tag_object, str)
                        and tag_object != self.candidate_commit
                        and peeled_commit == self.candidate_commit
                        and tag_identity.get("message") == self.tag_message
                        and SHA256_RE.fullmatch(
                            str(tag_identity.get("tagger_identity_sha256", ""))
                        )
                        is not None
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
                                release,
                                expected_draft=False,
                                expected_asset_identity_sha256=(
                                    expected_asset_identity_sha256
                                ),
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
                        "classic_main_protection",
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
                    or not isinstance(prior_id, int)
                    or prior_id < 1
                    or final_id != prior_id
                ):
                    _fail(
                        "E_V240_ADAPTER_EXPECTED_BEFORE",
                        "final ruleset must CAS the bound reusable ruleset id and name",
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
            validation_action = (
                "promotion_lock_create"
                if action == "promotion_lock_finalize" and not post_mutation
                else action
            )
            self._validate_ruleset_payload(validation_action, expected_payload)
            expected_sha = _canonical_sha256(normalize_ruleset(expected_payload))
            if bound_expected_sha != expected_sha:
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "canonical ruleset digest drift")
            normalized_live: Mapping[str, Any] | None = None
            if value is not None:
                self._validate_ruleset_payload(validation_action, value)
                normalized_live = normalize_ruleset(value)
            observed_sha = (
                _canonical_sha256(normalized_live)
                if normalized_live is not None
                else None
            )
            observed_id = value.get("id") if isinstance(value, Mapping) else None
            if value is not None and (
                not isinstance(observed_id, int)
                or isinstance(observed_id, bool)
                or observed_id < 1
            ):
                _fail("E_V240_ADAPTER_READBACK", "live ruleset id is missing")
            other_value: Mapping[str, Any] | None = None
            if action == "promotion_lock_finalize":
                id_exact = observed_id == prior_id
                if prior_name == final_name:
                    other_name = None
                    if value is None:
                        classification = "absent"
                    elif expected_sha == observed_sha and id_exact:
                        classification = "exact"
                    else:
                        classification = "conflict"
                else:
                    other_name = prior_name if post_mutation else final_name
                    assert isinstance(other_name, str)
                    other_value = self._ruleset_by_name(other_name)
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
                    "ruleset": normalized_live,
                    "other_ruleset_name": (
                        other_name
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
            approval = expected_before.get("ci_approval")
            if not isinstance(approval, Mapping):
                _fail(
                    "E_V240_CI_TRUST_BINDING",
                    "CI operation lacks the CP05 workflow approval",
                )
            workflow_identity = self._fixed_workflow_identity(approval)
            workflow_id = workflow_identity["workflow_id"]
            approved_actor_id = approval.get("release_actor_id")
            expected_event = (
                "push" if action == "ci_wait" else "workflow_dispatch"
            )
            run_id = parameters.get("run_id") or expected_before.get("run_id")
            release_intent = parameters.get("_release_intent")
            display_title = None
            if action == "post_release_ci":
                if not isinstance(release_intent, str) or re.fullmatch(r"[0-9a-f]{64}", release_intent) is None:
                    _fail("E_V240_CI_INTENT", "post-release CI requires its persisted operation idempotency key")
                display_title = f"{self.release_title} release {release_intent}"
            if run_id is None:
                matches: list[Mapping[str, Any]] = []
                for candidate in self._all_workflow_runs(workflow_id):
                    actor = candidate.get("actor")
                    triggering = candidate.get("triggering_actor")
                    if not (
                        candidate.get("workflow_id") == workflow_id
                        and candidate.get("head_sha") == self.candidate_commit
                        and candidate.get("event") == expected_event
                        and isinstance(actor, Mapping)
                        and actor.get("id") == approved_actor_id
                        and isinstance(triggering, Mapping)
                        and triggering.get("id") == approved_actor_id
                        and (
                            action != "post_release_ci"
                            or candidate.get("display_title") == display_title
                        )
                    ):
                        continue
                    # A potential identity match with a tag/ref/path suffix
                    # spoof is a conflict, not an absent run that permits a
                    # second dispatch.
                    self._canonical_run_workflow_path(candidate.get("path"))
                    matches.append(candidate)
                if not matches:
                    return self._readback(
                        "github_actions_api",
                        {
                            "classification": (
                                "absent"
                                if action == "post_release_ci"
                                else "unavailable"
                            ),
                            "reason": "matching_run_not_found",
                            "release_intent": release_intent,
                            "display_title": display_title,
                            "workflow_id": workflow_id,
                        },
                    )
                if len(matches) > 1:
                    return self._readback(
                        "github_actions_api",
                        {
                            "classification": "conflict",
                            "reason": "duplicate_workflow_run_identity",
                            "release_intent": release_intent,
                            "display_title": display_title,
                            "workflow_id": workflow_id,
                            "matching_run_ids": [
                                item.get("id") for item in matches
                            ],
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
            run_path = self._canonical_run_workflow_path(run.get("path"))
            if run.get("workflow_id") != workflow_id:
                _fail(
                    "E_V240_CI_TRUST_BINDING",
                    "Actions run numeric workflow identity drift",
                )
            jobs = [
                {
                    "name": job.get("name"),
                    "head_sha": run.get("head_sha"),
                    "conclusion": job.get("conclusion"),
                }
                for job in jobs_raw
                if isinstance(job, Mapping)
            ]
            ci_receipt = {
                "head_sha": run.get("head_sha"),
                "workflow_path": workflow_identity["source_path"],
                "workflow_raw_path": run_path["raw_path"],
                "workflow_raw_ref": run_path["raw_ref"],
                "workflow_blob_sha": workflow_identity["source_blob_sha"],
                "workflow_id": workflow_id,
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
                and ci_receipt["event"] == expected_event
                and ci_receipt["workflow_id"] == approval.get("workflow_id")
                and ci_receipt["workflow_path"] == approval.get("workflow_path")
                and ci_receipt["workflow_blob_sha"]
                == approval.get("workflow_blob_sha")
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

    def _validate_remote_mutation_guard(
        self,
        operation_id: str,
        action: str,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Re-read CP14 policy and main immediately before one remote write."""

        guard = parameters.get("_remote_mutation_guard")
        required_fields = {
            "schema_version",
            "operation_id",
            "action",
            "main_ref",
            "allowed_main_commits",
            "temporary_main_lock",
            "permanent_tag_ruleset",
        }
        if (
            not isinstance(guard, Mapping)
            or set(guard) != required_fields
            or guard.get("schema_version")
            != "goal-teams-v2.40-remote-mutation-guard-v1"
            or guard.get("operation_id") != operation_id
            or guard.get("action") != action
            or guard.get("main_ref") != "refs/heads/main"
        ):
            _fail(
                "E_V240_ADAPTER_EXPECTED_BEFORE",
                "remote mutation guard is missing or not intent-bound",
            )
        checkpoint_id = operation_id.split(".", 1)[0]
        expected_allowed = [self.base_main_commit]
        if checkpoint_id == "CP17" and action != "main_promote":
            expected_allowed = [self.candidate_commit]
        allowed_main = guard.get("allowed_main_commits")
        if allowed_main != expected_allowed:
            _fail(
                "E_V240_ADAPTER_EXPECTED_BEFORE",
                "remote mutation guard has a non-canonical main lease",
            )

        def validate_ruleset_identity(
            value: Any, *, validation_action: str
        ) -> dict[str, Any]:
            if not isinstance(value, Mapping) or set(value) != {
                "ruleset_id",
                "ruleset_name",
                "ruleset_sha256",
                "ruleset",
            }:
                _fail(
                    "E_V240_ADAPTER_EXPECTED_BEFORE",
                    "remote mutation guard ruleset identity is incomplete",
                )
            ruleset_id = value.get("ruleset_id")
            payload = value.get("ruleset")
            if (
                not isinstance(ruleset_id, int)
                or isinstance(ruleset_id, bool)
                or ruleset_id < 1
                or not isinstance(payload, Mapping)
            ):
                _fail(
                    "E_V240_ADAPTER_EXPECTED_BEFORE",
                    "remote mutation guard ruleset id/payload is invalid",
                )
            self._validate_ruleset_payload(validation_action, payload)
            normalized = normalize_ruleset(payload)
            digest = _canonical_sha256(normalized)
            if (
                value.get("ruleset_name") != normalized.get("name")
                or value.get("ruleset_sha256") != digest
            ):
                _fail(
                    "E_V240_ADAPTER_EXPECTED_BEFORE",
                    "remote mutation guard ruleset digest is invalid",
                )
            live = self._ruleset_by_name(str(value["ruleset_name"]))
            live_id = live.get("id") if isinstance(live, Mapping) else None
            if (
                not isinstance(live, Mapping)
                or live_id != ruleset_id
                or isinstance(live_id, bool)
            ):
                _fail(
                    "E_V240_REMOTE_RESOURCE_CONFLICT",
                    "live ruleset numeric identity differs at the mutation edge",
                )
            self._validate_ruleset_payload(validation_action, live)
            live_normalized = normalize_ruleset(live)
            if (
                live_normalized != normalized
                or _canonical_sha256(live_normalized) != digest
            ):
                _fail(
                    "E_V240_REMOTE_RESOURCE_CONFLICT",
                    "live ruleset payload differs at the mutation edge",
                )
            return {
                "ruleset_id": ruleset_id,
                "ruleset_name": normalized["name"],
                "ruleset_sha256": digest,
                "ruleset": normalized,
            }

        temporary = validate_ruleset_identity(
            guard.get("temporary_main_lock"),
            validation_action="promotion_lock_create",
        )
        permanent_tag = validate_ruleset_identity(
            guard.get("permanent_tag_ruleset"),
            validation_action="tag_ruleset_create",
        )
        live_main = self._remote_ref("refs/heads/main")
        if live_main not in allowed_main:
            _fail(
                "E_V240_REMOTE_MAIN_LEASE",
                "main differs from the intent-bound mutation-edge lease",
            )
        return {
            "temporary_main_lock": temporary,
            "permanent_tag_ruleset": permanent_tag,
            "main_commit": live_main,
        }

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
        if (
            action == "release_publish"
            and classification == "conflict"
            and isinstance(before.get("details"), Mapping)
            and before["details"].get("asset_identity_error")
            == "E_V240_DRAFT_ASSET_IDENTITY"
        ):
            _fail(
                "E_V240_DRAFT_ASSET_IDENTITY",
                "live Release asset ids differ from the frozen Draft identity",
            )
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
                "final ruleset verification requires the exact bound reusable ruleset CAS",
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

        frozen_tagger: dict[str, str] | None = None
        local_tag_object: str | None = None
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
            if expected is not None:
                _fail(
                    "E_V240_ADAPTER_EXPECTED_BEFORE",
                    "candidate creation requires an explicit absent expected-before lease",
                )
            _run(
                (
                    "git",
                    "push",
                    "--force-with-lease=refs/heads/codex/v2.40:",
                    "origin",
                    f"{self.candidate_commit}:refs/heads/codex/v2.40",
                ),
                cwd=self.source_root,
            )
        elif action == "tag_push":
            if expected_before.get("remote_tag_commit") is not None:
                _fail("E_V240_ADAPTER_EXPECTED_BEFORE", "tag creation requires absent expected-before")
            frozen_tagger = self._effective_release_tagger_identity()
            local_tag = self._local_tag_identity()
            if local_tag is None:
                _run(
                    (
                        "git",
                        "tag",
                        "-a",
                        self.tag,
                        self.candidate_commit,
                        "-m",
                        self.tag_message,
                    ),
                    cwd=self.source_root,
                    env={
                        "GIT_COMMITTER_NAME": frozen_tagger["name"],
                        "GIT_COMMITTER_EMAIL": frozen_tagger["email"],
                    },
                )
                local_tag = self._local_tag_identity()
            if (
                not isinstance(local_tag, Mapping)
                or local_tag.get("annotated") is not True
                or SHA40_RE.fullmatch(str(local_tag.get("tag_object", "")))
                is None
                or local_tag.get("peeled_commit") != self.candidate_commit
                or local_tag.get("message") != self.tag_message
            ):
                _fail(
                    "E_V240_REMOTE_RESOURCE_CONFLICT",
                    "local tag is not the canonical annotated tag",
                )
            if (
                local_tag.get("tagger_name") != frozen_tagger["name"]
                or local_tag.get("tagger_email") != frozen_tagger["email"]
                or local_tag.get("tagger_identity_sha256")
                != frozen_tagger["identity_sha256"]
            ):
                _fail(
                    "E_V240_RELEASE_TAGGER_IDENTITY",
                    "local tag is not bound to the frozen release tagger identity",
                )
            local_tag_object = str(local_tag["tag_object"])
            self._validate_remote_mutation_guard(
                operation_id, action, parameters
            )
            _run(
                (
                    "git",
                    "push",
                    f"--force-with-lease=refs/tags/{self.tag}:",
                    "origin",
                    f"refs/tags/{self.tag}:refs/tags/{self.tag}",
                ),
                cwd=self.source_root,
            )
        elif action == "main_promote":
            expected = expected_before.get("remote_main_commit")
            if expected != self.base_main_commit:
                _fail("E_V240_REMOTE_MAIN_LEASE", "main expected-before is not frozen base")
            self._validate_remote_mutation_guard(
                operation_id, action, parameters
            )
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
            self._validate_remote_mutation_guard(
                operation_id, action, parameters
            )
            _run(
                (
                    "gh", "release", "create", self.tag, "--repo", self.host_repository,
                    "--verify-tag", "--draft", "--target", self.candidate_commit,
                    "--title", self.release_title,
                    "--notes", self.release_body,
                ),
                cwd=self.source_root,
            )
        elif action == "asset_upload":
            release_id = self._frozen_release_id(expected_before)
            name, path = self._asset_path(operation_id)
            expected_hash = expected_before.get("asset_sha256")
            expected_size = expected_before.get("asset_size")
            if expected_hash != _file_sha256(path) or expected_size != path.stat().st_size:
                _fail("E_V240_DRAFT_ASSET_IDENTITY", f"asset expected-before digest drift: {name}")
            self._upload_release_asset(
                release_id,
                name,
                path,
                operation_id=operation_id,
                action=action,
                parameters=parameters,
            )
        elif action in {"asset_download_verify", "published_asset_download"}:
            # The read-only observer above already performed the byte compare.
            pass
        elif action == "release_publish":
            release_id = self._frozen_release_id(expected_before)
            expected_assets_sha = expected_before.get("draft_asset_set_sha256")
            local_assets = self._local_asset_set()
            if expected_assets_sha != _canonical_sha256(local_assets):
                _fail("E_V240_DRAFT_ASSET_IDENTITY", "publish intent is not bound to the verified four-asset set")
            if expected_before.get("candidate_commit") != self.candidate_commit or expected_before.get("tag") != self.tag:
                _fail("E_V240_RELEASE_SOURCE_IDENTITY", "publish intent identity drift")
            # Verify once before the mutation guard and once after it.  The
            # candidate repository can only produce the final binding; it has
            # no positive path to the publish PATCH.  A real external host must
            # repeat this read in its own exclusive mutation window.
            self._verify_exact_draft_for_publish(expected_before)
            self._validate_remote_mutation_guard(
                operation_id, action, parameters
            )
            self._verify_exact_draft_for_publish(expected_before)
            self._require_external_exclusive_publish_host(expected_before)
        elif action == "post_release_ci":
            workflow = parameters.get("workflow")
            if workflow != ".github/workflows/release-gate.yml":
                _fail("E_V240_CI_TRUST_BINDING", "unapproved post-release workflow")
            release_intent = parameters.get("_release_intent")
            if not isinstance(release_intent, str) or re.fullmatch(r"[0-9a-f]{64}", release_intent) is None:
                _fail("E_V240_CI_INTENT", "post-release workflow dispatch intent is missing")
            self._validate_remote_mutation_guard(
                operation_id, action, parameters
            )
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
        if action == "tag_push":
            details = after.get("details")
            if (
                not isinstance(details, Mapping)
                or not isinstance(frozen_tagger, Mapping)
                or details.get("tag_object") != local_tag_object
                or details.get("tagger_name") != frozen_tagger.get("name")
                or details.get("tagger_email") != frozen_tagger.get("email")
                or details.get("tagger_identity_sha256")
                != frozen_tagger.get("identity_sha256")
            ):
                _fail(
                    "E_V240_TAG_OBJECT_IDENTITY",
                    "remote tag object/tagger differs from the frozen local tag",
                    external_side_effect_count=1,
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
