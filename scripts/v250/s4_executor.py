#!/usr/bin/env python3
"""Execute and reconcile the V2.63 S4 publish/install contract.

Every possible mutation is journaled before invocation, followed by an
independent readback.  An exception never causes an automatic replay: the
executor performs one read-only reconciliation, emits a digest-bound terminal
receipt, and lets a later invocation resume only from exact observed state.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Callable, Mapping, Protocol, Sequence


ROOT = Path(__file__).resolve().parents[2]
VERSION = "V2.63"
REPOSITORY = "vibe-coding-era/goal-teams"
GH_REPOSITORY = "github.com/vibe-coding-era/goal-teams"
TAG = "v2.63"
TITLE = "Goal Teams V2.63"
CANONICAL_REMOTE = "git@github.com:vibe-coding-era/goal-teams.git"
CANONICAL_RELEASE_URL = (
    "https://github.com/vibe-coding-era/goal-teams/releases/tag/v2.63"
)
DRAFT_RELEASE_URL_RE = re.compile(
    r"^https://github\.com/vibe-coding-era/goal-teams/releases/tag/"
    r"untagged-[0-9a-f]{20,64}$"
)
RELEASE_PROFILE_RELATIVE = Path("references/release-profiles/v2.63.json")
SCHEMA_PATH = ROOT / "schemas" / "v2.50" / "release-control.schema.json"
RUNTIME_TRANSITION_SCHEMA_PATH = (
    ROOT / "schemas" / "v2.50" / "runtime-transition-receipt.schema.json"
)
RUNTIME_TRANSITION_SCHEMA_ID = (
    "https://goal-teams.local/schemas/v2.50/"
    "runtime-transition-receipt.schema.json"
)
SCHEMA_REF = (
    "https://goal-teams.local/schemas/v2.50/release-control.schema.json"
    "#/$defs/s4_outcome_receipt"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,256}$")
CANONICAL_ASSET_NAMES = (
    "SHA256SUMS",
    "_files.sha256",
    "_release.json",
    "goal-teams-V2.63.tar.gz",
)
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_PACKAGE_FILES = 20000
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
POSITIVE_DECIMAL_RE = re.compile(r"^[1-9][0-9]*$")

JOURNAL_LAYOUT = (
    ("tag_local_create", "tag_local_create", "refs/tags/v2.63", "local_repository"),
    ("tag_push", "tag_push", "refs/tags/v2.63", "external_service"),
    ("release_create", "release_create", "v2.63", "external_service"),
    (
        "asset_upload:SHA256SUMS",
        "asset_upload",
        "SHA256SUMS",
        "external_service",
    ),
    (
        "asset_upload:_files.sha256",
        "asset_upload",
        "_files.sha256",
        "external_service",
    ),
    (
        "asset_upload:_release.json",
        "asset_upload",
        "_release.json",
        "external_service",
    ),
    (
        "asset_upload:goal-teams-V2.63.tar.gz",
        "asset_upload",
        "goal-teams-V2.63.tar.gz",
        "external_service",
    ),
    ("release_publish", "release_publish", "v2.63", "external_service"),
    ("install", "install", "canonical CODEX_HOME", "local_install"),
)


def canonical_sha256(value: Any) -> str:
    """Return the canonical JSON SHA-256 used by V2.63 receipts."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


_canonical_sha256 = canonical_sha256


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise S4ExecutionError("E_V250_S4_MODULE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_release_profile_contract(repository_root: Path) -> dict[str, str]:
    """Load the fixed public Release identity from the exact source tree."""

    path = repository_root.resolve() / RELEASE_PROFILE_RELATIVE
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > 1024 * 1024
        ):
            raise S4ExecutionError("E_V250_S4_RELEASE_PROFILE")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S4ExecutionError("E_V250_S4_RELEASE_PROFILE") from exc
    if (
        not isinstance(value, dict)
        or value.get("version") != VERSION
        or value.get("status") != "active"
        or value.get("tag") != TAG
        or value.get("release_title") != TITLE
        or value.get("tag_message") != TITLE
        or not isinstance(value.get("release_body"), str)
        or not value["release_body"]
    ):
        raise S4ExecutionError("E_V250_S4_RELEASE_PROFILE")
    return {
        "release_title": value["release_title"],
        "release_body": value["release_body"],
        "tag_message": value["tag_message"],
    }


class S4ExecutionError(RuntimeError):
    """Stable S4 error; raw command output and credentials are never retained."""

    def __init__(self, code: str, *, receipt: dict[str, Any] | None = None) -> None:
        self.code = code
        self.receipt = receipt or {}
        super().__init__(code)


class OperationJournal:
    """In-memory execute-once journal included in every terminal receipt."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = [
            {
                "step_id": step_id,
                "operation": operation,
                "target": target,
                "scope": scope,
                "state": "not_started",
                "attempted_this_run": False,
                "readback_state": "not_run",
            }
            for step_id, operation, target, scope in JOURNAL_LAYOUT
        ]

    def _entry(self, step_id: str) -> dict[str, Any]:
        for entry in self._entries:
            if entry["step_id"] == step_id:
                return entry
        raise S4ExecutionError("E_V250_S4_JOURNAL_STEP")

    def attempt(self, step_id: str) -> None:
        entry = self._entry(step_id)
        if entry["attempted_this_run"]:
            raise S4ExecutionError("E_V250_S4_JOURNAL_REPLAY")
        entry["attempted_this_run"] = True
        entry["state"] = "attempted"
        entry["readback_state"] = "not_run"

    def observe(self, step_id: str, observed: str) -> None:
        if observed not in {"absent", "exact", "conflict", "unavailable"}:
            raise S4ExecutionError("E_V250_S4_JOURNAL_OBSERVATION")
        entry = self._entry(step_id)
        entry["readback_state"] = observed
        if observed == "exact":
            entry["state"] = "confirmed"
        elif observed == "unavailable" and entry["attempted_this_run"]:
            entry["state"] = "uncertain"
        elif entry["attempted_this_run"]:
            entry["state"] = "attempted"
        else:
            entry["state"] = "not_started"

    def snapshot(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self._entries))

    def attempted(self) -> list[dict[str, Any]]:
        return [entry for entry in self._entries if entry["attempted_this_run"]]


class OutcomeValidator(Protocol):
    @property
    def identity(self) -> dict[str, Any]: ...

    def validate(self, receipt: Mapping[str, Any]) -> None: ...


_AJV_PROGRAM = r"""
const fs = require('fs');
let Ajv2020;
try { Ajv2020 = require('ajv/dist/2020'); }
catch (_) { process.exit(3); }
let schema, runtimeSchema;
try { schema = JSON.parse(fs.readFileSync(process.argv[1], 'utf8')); }
catch (_) { process.exit(4); }
try { runtimeSchema = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')); }
catch (_) { process.exit(4); }
let validate;
try {
  const ajv = new Ajv2020({allErrors: true, strict: true, validateFormats: false});
  ajv.addSchema(runtimeSchema);
  validate = ajv.compile(schema);
} catch (_) { process.exit(4); }
if (process.argv[3] === 'check') process.exit(0);
let instance;
try { instance = JSON.parse(fs.readFileSync(process.argv[4], 'utf8')); }
catch (_) { process.exit(5); }
process.exit(validate(instance) ? 0 : 1);
"""


class Draft202012OutcomeValidator:
    """Use a real Draft 2020-12 implementation or fail closed."""

    def __init__(
        self,
        schema_path: Path = SCHEMA_PATH,
        runtime_schema_path: Path = RUNTIME_TRANSITION_SCHEMA_PATH,
    ) -> None:
        try:
            metadata = schema_path.lstat()
            runtime_metadata = runtime_schema_path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > 4 * 1024 * 1024
                or not stat.S_ISREG(runtime_metadata.st_mode)
                or runtime_metadata.st_size > 4 * 1024 * 1024
            ):
                raise OSError
            raw = schema_path.read_bytes()
            runtime_raw = runtime_schema_path.read_bytes()
            root = json.loads(raw)
            runtime_root = json.loads(runtime_raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA_UNAVAILABLE") from exc
        if (
            not isinstance(root, dict)
            or root.get("$schema")
            != "https://json-schema.org/draft/2020-12/schema"
            or not isinstance(root.get("$defs"), dict)
            or "s4_outcome_receipt" not in root["$defs"]
        ):
            raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA_INVALID")
        if (
            not isinstance(runtime_root, dict)
            or runtime_root.get("$schema")
            != "https://json-schema.org/draft/2020-12/schema"
            or runtime_root.get("$id") != RUNTIME_TRANSITION_SCHEMA_ID
        ):
            raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA_INVALID")
        self.schema_sha256 = hashlib.sha256(raw).hexdigest()
        self.runtime_transition_schema_sha256 = hashlib.sha256(
            runtime_raw
        ).hexdigest()
        self.runtime_schema = runtime_root
        self.wrapper = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": root["$defs"],
            "$ref": "#/$defs/s4_outcome_receipt",
        }
        self._python_validator: Any | None = None
        self._node: str | None = None
        if importlib.util.find_spec("jsonschema") is not None:
            try:
                import jsonschema  # type: ignore[import-not-found]

                jsonschema.Draft202012Validator.check_schema(self.runtime_schema)
                jsonschema.Draft202012Validator.check_schema(self.wrapper)
                resolver = jsonschema.RefResolver.from_schema(
                    self.wrapper,
                    store={RUNTIME_TRANSITION_SCHEMA_ID: self.runtime_schema},
                )
                self._python_validator = jsonschema.Draft202012Validator(
                    self.wrapper,
                    resolver=resolver,
                )
                self.engine = "python-jsonschema-draft202012"
                return
            except Exception as exc:
                raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA_INVALID") from exc
        node = shutil.which("node")
        if node is None:
            raise S4ExecutionError("E_V250_S4_SCHEMA_VALIDATOR_UNAVAILABLE")
        self._node = node
        self.engine = "node-ajv-draft2020"
        self._run_ajv(None, check_only=True)

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "state": "validated",
            "engine": self.engine,
            "schema_ref": SCHEMA_REF,
            "schema_sha256": self.schema_sha256,
            "runtime_transition_schema_sha256": (
                self.runtime_transition_schema_sha256
            ),
        }

    def _run_ajv(
        self, receipt: Mapping[str, Any] | None, *, check_only: bool = False
    ) -> None:
        assert self._node is not None
        try:
            with tempfile.TemporaryDirectory(
                prefix="goal-teams-v250-schema-"
            ) as temp:
                work = Path(temp)
                schema_file = work / "schema.json"
                runtime_schema_file = work / "runtime-schema.json"
                schema_file.write_bytes(_canonical_json_bytes(self.wrapper))
                runtime_schema_file.write_bytes(
                    _canonical_json_bytes(self.runtime_schema)
                )
                argv = [
                    self._node,
                    "-e",
                    _AJV_PROGRAM,
                    str(schema_file),
                    str(runtime_schema_file),
                    "check" if check_only else "validate",
                ]
                if not check_only:
                    instance_file = work / "instance.json"
                    assert receipt is not None
                    instance_file.write_bytes(
                        _canonical_json_bytes(dict(receipt))
                    )
                    argv.append(str(instance_file))
                result = subprocess.run(
                    argv,
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    env={
                        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                        "HOME": str(Path(pwd.getpwuid(os.getuid()).pw_dir)),
                    },
                )
        except OSError as exc:
            raise S4ExecutionError(
                "E_V250_S4_SCHEMA_VALIDATOR_UNAVAILABLE"
            ) from exc
        if result.returncode == 3:
            raise S4ExecutionError("E_V250_S4_SCHEMA_VALIDATOR_UNAVAILABLE")
        if result.returncode == 4:
            raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA_INVALID")
        if result.returncode != 0:
            raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA")

    def validate(self, receipt: Mapping[str, Any]) -> None:
        if self._python_validator is not None:
            try:
                self._python_validator.validate(receipt)
            except Exception as exc:
                raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA") from exc
            return
        self._run_ajv(receipt)


def load_outcome_validator() -> OutcomeValidator:
    return Draft202012OutcomeValidator()


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], *, cwd: Path) -> CommandResult: ...


class SubprocessRunner:
    def run(self, argv: Sequence[str], *, cwd: Path) -> CommandResult:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)


class S4Backend(Protocol):
    def read_fetch_remote(self) -> str: ...

    def read_push_remote(self) -> str: ...

    def read_local_tag(self, tag: str) -> dict[str, object] | None: ...

    def create_annotated_tag(self, tag: str, commit: str, title: str) -> None: ...

    def read_tag(self, tag: str) -> dict[str, object] | None: ...

    def push_tag(self, tag: str, object_sha: str) -> None: ...

    def read_release(
        self, repository: str, tag: str
    ) -> dict[str, object] | None: ...

    def create_draft_release(
        self,
        repository: str,
        tag: str,
        title: str,
        body: str,
    ) -> None: ...

    def upload_asset(self, repository: str, tag: str, path: Path) -> None: ...

    def publish_release(self, repository: str, tag: str) -> None: ...

    def download_asset(
        self, repository: str, tag: str, name: str, target: Path
    ) -> None: ...

    def read_installed_state(self) -> dict[str, object] | None: ...

    def read_installed_version(self) -> str | None: ...

    def install(self, bundle: Path, identity_path: Path) -> None: ...

    def verify_installed_payload(
        self,
        package_files: list[dict[str, object]],
        state: dict[str, object],
    ) -> dict[str, object]: ...


def _checked(
    runner: CommandRunner, argv: Sequence[str], *, cwd: Path, code: str
) -> CommandResult:
    result = runner.run(argv, cwd=cwd)
    if result.returncode != 0:
        raise S4ExecutionError(code)
    return result


def _parse_http_json(result: CommandResult) -> tuple[int, dict[str, object]]:
    normalized = result.stdout.replace("\r\n", "\n")
    first_line = normalized.splitlines()[0] if normalized.splitlines() else ""
    match = re.match(r"^HTTP/(?:1\.[01]|2(?:\.0)?)\s+([0-9]{3})\b", first_line)
    if match is None:
        raise S4ExecutionError("E_V250_S4_GITHUB_RESPONSE")
    separator = normalized.find("\n\n")
    body = normalized[separator + 2 :] if separator >= 0 else ""
    try:
        payload = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise S4ExecutionError("E_V250_S4_GITHUB_RESPONSE") from exc
    if not isinstance(payload, dict):
        raise S4ExecutionError("E_V250_S4_GITHUB_RESPONSE")
    return int(match.group(1)), payload


def _parse_annotated_tag(
    raw: str, *, object_sha: str, expected_tag: str
) -> dict[str, object]:
    header, separator, message = raw.partition("\n\n")
    if not separator:
        raise S4ExecutionError("E_V250_S4_TAG_NOT_ANNOTATED")
    values: dict[str, str] = {}
    for line in header.splitlines():
        key, space, value = line.partition(" ")
        if space and key in {"object", "type", "tag"}:
            values[key] = value
    normalized_message = message.rstrip("\n")
    if (
        values.get("type") != "commit"
        or values.get("tag") != expected_tag
        or COMMIT_RE.fullmatch(values.get("object", "")) is None
        or normalized_message != TITLE
    ):
        if normalized_message != TITLE:
            raise S4ExecutionError("E_V250_S4_TAG_MESSAGE_DRIFT")
        raise S4ExecutionError("E_V250_S4_TAG_NOT_ANNOTATED")
    return {
        "tag": expected_tag,
        "object_sha": object_sha,
        "peeled_commit": values["object"],
        "annotated": True,
        "message": normalized_message,
    }


class CommandBackend:
    """Production backend with fixed GitHub targets and no shell evaluation."""

    def __init__(
        self,
        repository_root: Path,
        runner: CommandRunner | None = None,
        *,
        code_home: Path | None = None,
    ) -> None:
        self.root = repository_root.resolve()
        self.runner = runner or SubprocessRunner()
        canonical_home = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".codex"
        self.code_home = (code_home or canonical_home).expanduser().absolute()

    @staticmethod
    def _require_repository(repository: str) -> None:
        if repository != REPOSITORY:
            raise S4ExecutionError("E_V250_S4_REPOSITORY_TARGET")

    def read_fetch_remote(self) -> str:
        return _checked(
            self.runner,
            ["git", "remote", "get-url", "origin"],
            cwd=self.root,
            code="E_V250_S4_GIT_REMOTE_READ",
        ).stdout.strip()

    def read_push_remote(self) -> str:
        return _checked(
            self.runner,
            ["git", "remote", "get-url", "--push", "origin"],
            cwd=self.root,
            code="E_V250_S4_GIT_REMOTE_READ",
        ).stdout.strip()

    def _read_tag_object(self, reference: str, object_sha: str, tag: str) -> dict[str, object]:
        kind = _checked(
            self.runner,
            ["git", "cat-file", "-t", reference],
            cwd=self.root,
            code="E_V250_S4_TAG_READBACK",
        ).stdout.strip()
        if kind != "tag":
            raise S4ExecutionError("E_V250_S4_TAG_NOT_ANNOTATED")
        raw = _checked(
            self.runner,
            ["git", "cat-file", "tag", reference],
            cwd=self.root,
            code="E_V250_S4_TAG_READBACK",
        ).stdout
        return _parse_annotated_tag(raw, object_sha=object_sha, expected_tag=tag)

    def read_local_tag(self, tag: str) -> dict[str, object] | None:
        reference = f"refs/tags/{tag}"
        presence = self.runner.run(
            ["git", "show-ref", "--verify", "--quiet", reference],
            cwd=self.root,
        )
        if presence.returncode == 1:
            return None
        if presence.returncode != 0:
            raise S4ExecutionError("E_V250_S4_LOCAL_TAG_READ")
        object_sha = _checked(
            self.runner,
            ["git", "rev-parse", "--verify", reference],
            cwd=self.root,
            code="E_V250_S4_LOCAL_TAG_READ",
        ).stdout.strip()
        if COMMIT_RE.fullmatch(object_sha) is None:
            raise S4ExecutionError("E_V250_S4_LOCAL_TAG_READ")
        return self._read_tag_object(object_sha, object_sha, tag)

    def create_annotated_tag(self, tag: str, commit: str, title: str) -> None:
        if tag != TAG or title != TITLE or COMMIT_RE.fullmatch(commit) is None:
            raise S4ExecutionError("E_V250_S4_TAG_CREATE_INPUT")
        _checked(
            self.runner,
            ["git", "tag", "-a", tag, commit, "-m", title],
            cwd=self.root,
            code="E_V250_S4_TAG_CREATE",
        )

    def read_tag(self, tag: str) -> dict[str, object] | None:
        result = _checked(
            self.runner,
            [
                "git",
                "ls-remote",
                "origin",
                f"refs/tags/{tag}",
                f"refs/tags/{tag}^{{}}",
            ],
            cwd=self.root,
            code="E_V250_S4_TAG_READBACK",
        )
        rows: dict[str, str] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2 or COMMIT_RE.fullmatch(parts[0]) is None:
                raise S4ExecutionError("E_V250_S4_TAG_READBACK")
            rows[parts[1]] = parts[0]
        if not rows:
            return None
        direct = rows.get(f"refs/tags/{tag}")
        peeled = rows.get(f"refs/tags/{tag}^{{}}")
        if direct is None or peeled is None or len(rows) != 2:
            raise S4ExecutionError("E_V250_S4_TAG_NOT_ANNOTATED")
        _checked(
            self.runner,
            ["git", "fetch", "--no-tags", "origin", f"refs/tags/{tag}"],
            cwd=self.root,
            code="E_V250_S4_TAG_READBACK",
        )
        value = self._read_tag_object(direct, direct, tag)
        if value["peeled_commit"] != peeled:
            raise S4ExecutionError("E_V250_S4_TAG_DRIFT")
        return value

    def push_tag(self, tag: str, object_sha: str) -> None:
        if tag != TAG or COMMIT_RE.fullmatch(object_sha) is None:
            raise S4ExecutionError("E_V250_S4_TAG_PUSH_INPUT")
        _checked(
            self.runner,
            ["git", "push", "origin", f"{object_sha}:refs/tags/{tag}"],
            cwd=self.root,
            code="E_V250_S4_TAG_PUSH",
        )

    def read_release(
        self, repository: str, tag: str
    ) -> dict[str, object] | None:
        self._require_repository(repository)
        result = self.runner.run(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                "X-GitHub-Api-Version: 2022-11-28",
                "--include",
                f"repos/{REPOSITORY}/releases/tags/{tag}",
            ],
            cwd=self.root,
        )
        status, payload = _parse_http_json(result)
        if status == 404:
            access_result = _checked(
                self.runner,
                [
                    "gh", "api", "--hostname", "github.com", "--method", "GET",
                    "-H", "Accept: application/vnd.github+json",
                    "-H", "X-GitHub-Api-Version: 2022-11-28", "--include",
                    f"repos/{REPOSITORY}",
                ],
                cwd=self.root,
                code="E_V250_S4_RELEASE_READBACK",
            )
            access_status, access_payload = _parse_http_json(access_result)
            permissions = access_payload.get("permissions")
            if (
                access_status != 200
                or not isinstance(permissions, dict)
                or permissions.get("push") is not True
            ):
                raise S4ExecutionError("E_V250_S4_RELEASE_READBACK")
            listed = _checked(
                self.runner,
                [
                    "gh", "api", "--hostname", "github.com", "--method", "GET",
                    "-H", "Accept: application/vnd.github+json",
                    "-H", "X-GitHub-Api-Version: 2022-11-28", "--paginate",
                    "--slurp", f"repos/{REPOSITORY}/releases?per_page=100",
                ],
                cwd=self.root,
                code="E_V250_S4_RELEASE_READBACK",
            )
            try:
                release_pages = json.loads(listed.stdout)
            except json.JSONDecodeError as exc:
                raise S4ExecutionError("E_V250_S4_GITHUB_RESPONSE") from exc
            if (
                not isinstance(release_pages, list)
                or not release_pages
                or any(
                    not isinstance(page, list)
                    or len(page) > 100
                    or any(
                        not isinstance(item, dict)
                        or not isinstance(item.get("tag_name"), str)
                        or not item["tag_name"]
                        for item in page
                    )
                    for page in release_pages
                )
            ):
                raise S4ExecutionError("E_V250_S4_GITHUB_RESPONSE")
            matches = [
                item
                for page in release_pages
                for item in page
                if item.get("tag_name") == tag
            ]
            if not matches:
                return None
            if len(matches) != 1:
                raise S4ExecutionError("E_V250_S4_RELEASE_READBACK")
            return dict(matches[0])
        if result.returncode != 0 or status != 200:
            raise S4ExecutionError("E_V250_S4_RELEASE_READBACK")
        return payload

    def create_draft_release(
        self,
        repository: str,
        tag: str,
        title: str,
        body: str,
    ) -> None:
        self._require_repository(repository)
        profile = _load_release_profile_contract(self.root)
        if (
            tag != TAG
            or title != profile["release_title"]
            or body != profile["release_body"]
        ):
            raise S4ExecutionError("E_V250_S4_RELEASE_CREATE_INPUT")
        _checked(
            self.runner,
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                GH_REPOSITORY,
                "--title",
                title,
                "--notes",
                body,
                "--draft",
                "--verify-tag",
            ],
            cwd=self.root,
            code="E_V250_S4_RELEASE_CREATE",
        )

    def upload_asset(self, repository: str, tag: str, path: Path) -> None:
        self._require_repository(repository)
        if path.name not in CANONICAL_ASSET_NAMES:
            raise S4ExecutionError("E_V250_S4_ASSET_UPLOAD_INPUT")
        _checked(
            self.runner,
            [
                "gh",
                "release",
                "upload",
                tag,
                str(path),
                "--repo",
                GH_REPOSITORY,
            ],
            cwd=self.root,
            code="E_V250_S4_ASSET_UPLOAD",
        )

    def publish_release(self, repository: str, tag: str) -> None:
        self._require_repository(repository)
        _checked(
            self.runner,
            [
                "gh",
                "release",
                "edit",
                tag,
                "--repo",
                GH_REPOSITORY,
                "--draft=false",
                "--latest=false",
            ],
            cwd=self.root,
            code="E_V250_S4_RELEASE_PUBLISH",
        )

    def download_asset(
        self, repository: str, tag: str, name: str, target: Path
    ) -> None:
        self._require_repository(repository)
        if name not in CANONICAL_ASSET_NAMES:
            raise S4ExecutionError("E_V250_S4_ASSET_DOWNLOAD_INPUT")
        target.parent.mkdir(parents=True, exist_ok=True)
        _checked(
            self.runner,
            [
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                GH_REPOSITORY,
                "--dir",
                str(target.parent),
                "--pattern",
                name,
            ],
            cwd=self.root,
            code="E_V250_S4_ASSET_DOWNLOAD",
        )
        if not target.is_file() or target.is_symlink():
            raise S4ExecutionError("E_V250_S4_ASSET_DOWNLOAD")

    def read_installed_state(self) -> dict[str, object] | None:
        path = self.code_home / "state" / "goal-teams" / "current.json"
        if not path.exists():
            return None
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size > 16 * 1024 * 1024
        ):
            raise S4ExecutionError("E_V250_S4_INSTALLED_STATE")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise S4ExecutionError("E_V250_S4_INSTALLED_STATE") from exc
        if not isinstance(value, dict):
            raise S4ExecutionError("E_V250_S4_INSTALLED_STATE")
        return value

    def read_installed_version(self) -> str | None:
        path = self.code_home / "skills" / "goal-teams" / "VERSION"
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise S4ExecutionError("E_V250_S4_INSTALLED_VERSION")
        try:
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise S4ExecutionError("E_V250_S4_INSTALLED_VERSION") from exc

    def install(self, bundle: Path, identity_path: Path) -> None:
        _checked(
            self.runner,
            [
                "/usr/bin/env",
                "-i",
                f"HOME={self.code_home.parent}",
                f"CODEX_HOME={self.code_home}",
                "PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG=C.UTF-8",
                "LC_ALL=C.UTF-8",
                "PYTHONDONTWRITEBYTECODE=1",
                "GIT_TERMINAL_PROMPT=0",
                str(self.root / "scripts" / "install" / "install-local.sh"),
                "--release-bundle",
                str(bundle),
                "--release-identity",
                str(identity_path),
            ],
            cwd=self.root,
            code="E_V250_S4_FORMAL_INSTALL",
        )

    @staticmethod
    def _file_record(path: Path, relative: str) -> dict[str, object]:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_DRIFT") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            code = (
                "E_V250_S4_INSTALLED_PACKAGE_SYMLINK"
                if stat.S_ISLNK(metadata.st_mode)
                else "E_V250_S4_INSTALLED_PACKAGE_DRIFT"
            )
            raise S4ExecutionError(code)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_DRIFT") from exc
        digest = hashlib.sha256()
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                before = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_dev != metadata.st_dev
                    or before.st_ino != metadata.st_ino
                    or before.st_size != metadata.st_size
                    or before.st_mtime_ns != metadata.st_mtime_ns
                ):
                    raise S4ExecutionError(
                        "E_V250_S4_INSTALLED_PACKAGE_DRIFT"
                    )
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                after = os.fstat(handle.fileno())
                if (
                    after.st_dev != before.st_dev
                    or after.st_ino != before.st_ino
                    or after.st_size != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns
                ):
                    raise S4ExecutionError(
                        "E_V250_S4_INSTALLED_PACKAGE_DRIFT"
                    )
        except OSError as exc:
            raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_DRIFT") from exc
        return {
            "path": relative,
            "sha256": digest.hexdigest(),
            "size": metadata.st_size,
            "mode": stat.S_IMODE(metadata.st_mode),
        }

    @staticmethod
    def _walk_regular_tree(root: Path) -> tuple[list[dict[str, object]], set[str]]:
        try:
            metadata = root.lstat()
        except OSError as exc:
            raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_DRIFT") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_SYMLINK")
        if not stat.S_ISDIR(metadata.st_mode):
            raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_DRIFT")
        files: list[dict[str, object]] = []
        directories: set[str] = set()

        def visit(directory: Path, prefix: PurePosixPath) -> None:
            try:
                children = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as exc:
                raise S4ExecutionError(
                    "E_V250_S4_INSTALLED_PACKAGE_DRIFT"
                ) from exc
            for child in children:
                relative = (prefix / child.name).as_posix()
                try:
                    child_meta = child.stat(follow_symlinks=False)
                except OSError as exc:
                    raise S4ExecutionError(
                        "E_V250_S4_INSTALLED_PACKAGE_DRIFT"
                    ) from exc
                if stat.S_ISLNK(child_meta.st_mode):
                    raise S4ExecutionError(
                        "E_V250_S4_INSTALLED_PACKAGE_SYMLINK"
                    )
                child_path = Path(child.path)
                if stat.S_ISDIR(child_meta.st_mode):
                    directories.add(relative)
                    visit(child_path, PurePosixPath(relative))
                elif stat.S_ISREG(child_meta.st_mode):
                    files.append(CommandBackend._file_record(child_path, relative))
                else:
                    raise S4ExecutionError(
                        "E_V250_S4_INSTALLED_PACKAGE_DRIFT"
                    )

        visit(root, PurePosixPath())
        return sorted(files, key=lambda item: str(item["path"])), directories

    def _reject_symlink_ancestors(self, target: Path, code: str) -> None:
        try:
            relative = target.relative_to(self.code_home)
            current = self.code_home
            if stat.S_ISLNK(current.lstat().st_mode):
                raise S4ExecutionError(code)
            for part in relative.parts:
                current = current / part
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise S4ExecutionError(code)
        except ValueError as exc:
            raise S4ExecutionError(code) from exc
        except OSError as exc:
            raise S4ExecutionError(code) from exc

    def verify_installed_payload(
        self,
        package_files: list[dict[str, object]],
        state: dict[str, object],
    ) -> dict[str, object]:
        stored = state.get("package_files")
        if stored != package_files:
            raise S4ExecutionError("E_V250_S4_INSTALLED_STATE_MANIFEST_DRIFT")
        expected_dirs: set[str] = set()
        for entry in package_files:
            path = PurePosixPath(str(entry["path"]))
            parent = path.parent
            while parent != PurePosixPath("."):
                expected_dirs.add(parent.as_posix())
                parent = parent.parent
        skill_root = self.code_home / "skills" / "goal-teams"
        self._reject_symlink_ancestors(
            skill_root, "E_V250_S4_INSTALLED_PACKAGE_SYMLINK"
        )
        actual_files, actual_dirs = self._walk_regular_tree(skill_root)
        if actual_files != package_files or actual_dirs != expected_dirs:
            raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_DRIFT")

        managed = state.get("managed_agent_files")
        fallback = state.get("fallback_agent_files")
        hashes = state.get("agent_hashes")
        if (
            not isinstance(managed, list)
            or not isinstance(fallback, list)
            or not isinstance(hashes, dict)
            or any(not isinstance(name, str) for name in [*managed, *fallback])
            or len(set([*managed, *fallback])) != len([*managed, *fallback])
            or set(hashes) != set([*managed, *fallback])
        ):
            raise S4ExecutionError("E_V250_S4_INSTALLED_AGENT_DRIFT")
        package_by_path = {
            str(entry["path"]): entry for entry in package_files
        }
        packaged_agents = {
            PurePosixPath(path).name
            for path in package_by_path
            if PurePosixPath(path).parent == PurePosixPath("subagents")
            and PurePosixPath(path).name.startswith("goal-")
            and PurePosixPath(path).suffix == ".toml"
        }
        if not packaged_agents or set(managed) != packaged_agents:
            raise S4ExecutionError("E_V250_S4_INSTALLED_AGENT_DRIFT")
        for name in sorted(hashes):
            if Path(name).name != name or not isinstance(hashes[name], str):
                raise S4ExecutionError("E_V250_S4_INSTALLED_AGENT_DRIFT")
            path = self.code_home / "agents" / name
            self._reject_symlink_ancestors(
                path, "E_V250_S4_INSTALLED_AGENT_SYMLINK"
            )
            try:
                record = self._file_record(path, ".")
            except S4ExecutionError as exc:
                if exc.code == "E_V250_S4_INSTALLED_PACKAGE_SYMLINK":
                    raise S4ExecutionError(
                        "E_V250_S4_INSTALLED_AGENT_SYMLINK"
                    ) from exc
                raise S4ExecutionError("E_V250_S4_INSTALLED_AGENT_DRIFT") from exc
            file_snapshot_digest = canonical_sha256(
                [{"path": ".", "type": "file", **{k: record[k] for k in ("mode", "sha256", "size")}}]
            )
            if hashes[name] != file_snapshot_digest:
                raise S4ExecutionError("E_V250_S4_INSTALLED_AGENT_DRIFT")
            if name in managed:
                packaged = package_by_path.get(f"subagents/{name}")
                if packaged is None or any(
                    packaged.get(field) != record.get(field)
                    for field in ("sha256", "size", "mode")
                ):
                    raise S4ExecutionError("E_V250_S4_INSTALLED_AGENT_DRIFT")
        return {
            "package_file_count": len(package_files),
            "package_tree_sha256": canonical_sha256(package_files),
            "state_package_files_sha256": canonical_sha256(stored),
            "agent_file_count": len(hashes),
            "agent_set_sha256": canonical_sha256(hashes),
            "symlink_count": 0,
        }


def _default_control_validator(
    version: str,
    commit: str,
    control: dict[str, object],
    *,
    receipt_root: Path | None = None,
) -> dict[str, object]:
    module = _load_module(
        "_goal_teams_v250_skill_release_for_s4",
        ROOT / "scripts" / "release" / "skill_release.py",
    )
    runtime_paths: dict[str, Path | None] = {
        "runtime_route_receipt_path": (
            None
            if receipt_root is None
            else receipt_root / "release-route-receipt.json"
        ),
        "runtime_authorization_receipt_path": (
            None if receipt_root is None else receipt_root / "authorization.json"
        ),
    }
    if version == "V2.63":
        runtime_paths.update(
            {
                "runtime_route_facts_receipt_path": (
                    None
                    if receipt_root is None
                    else receipt_root / "release-route-facts.json"
                ),
                "runtime_derived_route_receipt_path": (
                    None
                    if receipt_root is None
                    else receipt_root / "release-route-derived.json"
                ),
            }
        )
    return module.validate_v250_s4_control(
        version,
        commit,
        control,
        **runtime_paths,
    )


def _read_json_object(path: Path, error_code: str) -> dict[str, object]:
    """Read one bounded regular JSON object without following a file symlink."""

    if not isinstance(path, Path):
        raise S4ExecutionError(error_code)
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > MAX_RECEIPT_BYTES
        ):
            raise OSError
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S4ExecutionError(error_code) from exc
    if not isinstance(value, dict):
        raise S4ExecutionError(error_code)
    return value


def _default_checkpoint_validator(
    version: str,
    commit: str,
    checkpoint_receipt: Path,
    *,
    receipt_root: Path,
    release_root: Path,
    expected_workflow_run_id: str,
    expected_workflow_run_attempt: str,
    release_control: dict[str, object],
) -> dict[str, object]:
    """Validate the exact ready artifact chain that authorizes S4 continuation."""

    if not all(
        isinstance(path, Path)
        for path in (checkpoint_receipt, receipt_root, release_root)
    ):
        raise S4ExecutionError("E_V250_S4_CHECKPOINT_PATH")
    try:
        root_metadata = receipt_root.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise OSError
        expected_receipt_root = (release_root / version / "_receipts").resolve()
        if receipt_root.resolve() != expected_receipt_root:
            raise S4ExecutionError("E_V250_S4_CHECKPOINT_PATH")
        expected_checkpoint = receipt_root / "_checkpoint.json"
        if checkpoint_receipt.resolve() != expected_checkpoint.resolve():
            raise S4ExecutionError("E_V250_S4_CHECKPOINT_PATH")
    except S4ExecutionError:
        raise
    except OSError as exc:
        raise S4ExecutionError("E_V250_S4_RECEIPT_ROOT") from exc

    checkpoint = _read_json_object(
        checkpoint_receipt, "E_V250_S4_CHECKPOINT_INPUT"
    )
    formal_control = _read_json_object(
        receipt_root / "release-control.json",
        "E_V250_S4_CHECKPOINT_CONTROL_BINDING",
    )
    try:
        control_matches = (
            formal_control == release_control
            and canonical_sha256(formal_control)
            == canonical_sha256(release_control)
        )
    except (TypeError, ValueError) as exc:
        raise S4ExecutionError(
            "E_V250_S4_CHECKPOINT_CONTROL_BINDING"
        ) from exc
    if not control_matches:
        raise S4ExecutionError("E_V250_S4_CHECKPOINT_CONTROL_BINDING")

    module = _load_module(
        "_goal_teams_v250_skill_release_for_s4_checkpoint",
        ROOT / "scripts" / "release" / "skill_release.py",
    )
    return module.validate_v250_continuation_checkpoint(
        version,
        commit,
        checkpoint,
        receipt_root=receipt_root,
        release_root=release_root,
        expected_workflow_run_id=expected_workflow_run_id,
        expected_workflow_run_attempt=expected_workflow_run_attempt,
    )


def _require_checkpoint_verdict(
    verdict: object,
    *,
    version: str,
    commit: str,
) -> None:
    valid = (
        isinstance(verdict, dict)
        and verdict.get("ok") is True
        and verdict.get("passed") is True
        and verdict.get("status") == "continuation_checkpoint_passed"
        and verdict.get("error_code") is None
        and verdict.get("errors") == []
        and verdict.get("check_state") == "passed"
        and verdict.get("run_outcome") == "passed"
        and verdict.get("evidence_state") == "current"
        and verdict.get("claim_scope") == "release_asset_chain_only"
        and verdict.get("version") == version
        and verdict.get("source_commit") == commit
        and isinstance(verdict.get("checkpoint_sha256"), str)
        and SHA256_RE.fullmatch(str(verdict["checkpoint_sha256"])) is not None
        and verdict.get("persistent_local_mutation_count") == 0
        and verdict.get("external_mutation_count") == 0
        and verdict.get("external_side_effect_count") == 0
    )
    if valid:
        return
    candidates: list[object] = []
    if isinstance(verdict, dict):
        errors = verdict.get("errors")
        if isinstance(errors, list):
            candidates.extend(errors)
        candidates.append(verdict.get("error_code"))
    code = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, str)
            and re.fullmatch(r"E_[A-Z0-9_:-]+", candidate) is not None
        ),
        "E_V250_S4_CHECKPOINT_REQUIRED",
    )
    raise S4ExecutionError(str(code))


def _asset_paths(release_root: Path, version: str) -> dict[str, Path]:
    snapshot = release_root / version
    return {
        "SHA256SUMS": snapshot / "_artifacts" / "SHA256SUMS",
        "_files.sha256": snapshot / "_files.sha256",
        "_release.json": snapshot / "_release.json",
        f"goal-teams-{version}.tar.gz": snapshot
        / "_artifacts"
        / f"goal-teams-{version}.tar.gz",
    }


def _validate_local_assets(
    *,
    release_root: Path,
    repository_root: Path,
    control: Mapping[str, object],
    version: str,
    commit: str,
) -> tuple[dict[str, Path], list[dict[str, object]], dict[str, object]]:
    expected_root = (repository_root / "release" / "versions").resolve()
    actual_root = release_root.resolve()
    if actual_root != expected_root:
        raise S4ExecutionError("E_V250_S4_RELEASE_ROOT")
    paths = _asset_paths(actual_root, version)
    if tuple(paths) != CANONICAL_ASSET_NAMES:
        raise S4ExecutionError("E_V250_S4_ASSET_SET")
    assets: list[dict[str, object]] = []
    for name, path in paths.items():
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise S4ExecutionError("E_V250_S4_ASSET_SET") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > MAX_ASSET_BYTES
        ):
            raise S4ExecutionError("E_V250_S4_ASSET_SET")
        assets.append(
            {"name": name, "size": metadata.st_size, "sha256": _sha256_file(path)}
        )
    s2 = control.get("s2")
    expected_assets = s2.get("assets") if isinstance(s2, dict) else None
    if expected_assets != assets or control.get("asset_set_digest") != canonical_sha256(assets):
        raise S4ExecutionError("E_V250_S4_LOCAL_ASSET_DRIFT")
    try:
        record = json.loads(paths["_release.json"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S4ExecutionError("E_V250_S4_RELEASE_RECORD") from exc
    if (
        not isinstance(record, dict)
        or record.get("version") != version
        or record.get("source_commit") != commit
        or record.get("source_git_tree_id") != control.get("source_tree")
        or not isinstance(record.get("tree_sha256"), str)
        or SHA256_RE.fullmatch(record["tree_sha256"]) is None
    ):
        raise S4ExecutionError("E_V250_S4_RELEASE_RECORD")
    return paths, assets, record


def _default_prewrite_boundary_validator(
    *,
    repository_root: Path,
    release_root: Path,
    source_commit: str,
    source_tree: str,
    control: Mapping[str, object],
    asset_paths: Mapping[str, Path],
) -> dict[str, object]:
    """Revalidate the frozen source and same asset boundary before S4 writes."""

    boundary = control.get("repository_boundary")
    s2 = control.get("s2")
    integrity = control.get("asset_integrity_validation")
    if not all(isinstance(value, dict) for value in (boundary, s2, integrity)):
        raise S4ExecutionError("E_V250_S4_REPOSITORY_BOUNDARY_REQUIRED")
    assert isinstance(boundary, dict)
    assert isinstance(s2, dict)
    assert isinstance(integrity, dict)
    commands = boundary.get("argv")
    if (
        not isinstance(commands, list)
        or len(commands) != 3
        or any(not isinstance(argv, list) for argv in commands)
        or len(commands[0]) != 2
        or len(commands[1]) != 2
        or commands[0][1] != "scripts/checks/check-workspace-boundaries.py"
        or commands[1][1] != "scripts/checks/check-package-manifest.py"
        or commands[0][0] != commands[1][0]
        or re.fullmatch(
            r"python(?:3(?:\.[0-9]+)?)?",
            Path(str(commands[0][0])).name,
        )
        is None
        or commands[2] != integrity.get("argv")
        or boundary.get("cwd") != "."
        or integrity.get("cwd") != "."
    ):
        raise S4ExecutionError("E_V250_S4_REPOSITORY_BOUNDARY_COMMANDS")
    module = _load_module(
        "_goalteams_v250_repository_boundary_for_s4",
        repository_root / "scripts/v250/repository_boundary.py",
    )
    try:
        contract = module.boundary_contract_digests(
            repository_root=repository_root
        )
        original_verdict = module.validate_boundary_receipt(
            boundary,
            source_commit=source_commit,
            source_tree=source_tree,
            asset_set_id=str(control.get("asset_set_id", "")),
            asset_set_digest=str(control.get("asset_set_digest", "")),
            package_manifest_digest=contract["package_manifest_digest"],
            validator_digest=contract["validator_digest"],
            argv=commands,
            cwd=".",
            s2_receipt_sha256=s2.get("receipt_sha256"),
        )
        if original_verdict.get("ok") is not True:
            errors = original_verdict.get("errors")
            code = errors[0] if isinstance(errors, list) and errors else None
            raise ValueError(code or "E_V250_REPOSITORY_BOUNDARY_NOT_CURRENT")
        local_validation = {
            "passed": True,
            "public_asset_sources": {
                name: str(asset_paths[name]) for name in CANONICAL_ASSET_NAMES
            },
            "asset_integrity_validation_receipt": dict(integrity),
        }
        live = module.run_repository_boundary(
            source_commit=source_commit,
            source_tree=source_tree,
            s2_receipt=dict(s2),
            asset_validation_receipt=local_validation,
            release_root=release_root,
            repository_root=repository_root,
        )
        live_verdict = module.validate_boundary_receipt(
            live,
            source_commit=source_commit,
            source_tree=source_tree,
            asset_set_id=str(control.get("asset_set_id", "")),
            asset_set_digest=str(control.get("asset_set_digest", "")),
            package_manifest_digest=contract["package_manifest_digest"],
            validator_digest=contract["validator_digest"],
            argv=live.get("argv", []),
            cwd=".",
            s2_receipt_sha256=s2.get("receipt_sha256"),
        )
    except S4ExecutionError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        code = str(exc)
        if re.fullmatch(r"E_[A-Z0-9_:-]+", code) is None:
            code = "E_V250_S4_REPOSITORY_BOUNDARY_REVALIDATION"
        raise S4ExecutionError(code) from exc
    comparable = (
        "source_commit",
        "source_tree",
        "asset_set_id",
        "asset_set_digest",
        "s2_receipt_sha256",
        "package_manifest_digest",
        "validator_digest",
    )
    if (
        live_verdict.get("ok") is not True
        or live.get("receipt_mode") != "executed_now"
        or live.get("reused_receipt_sha256") is not None
        or any(live.get(key) != boundary.get(key) for key in comparable)
    ):
        raise S4ExecutionError("E_V250_S4_REPOSITORY_BOUNDARY_REVALIDATION")
    return {
        "ok": True,
        "passed": True,
        "original_receipt_sha256": boundary.get("receipt_sha256"),
        "live_receipt_sha256": live.get("receipt_sha256"),
        "source_commit": source_commit,
        "source_tree": source_tree,
        "asset_set_id": control.get("asset_set_id"),
        "asset_set_digest": control.get("asset_set_digest"),
    }


def _validate_tag(tag_value: object, commit: str) -> dict[str, object]:
    value = tag_value if isinstance(tag_value, dict) else {}
    if (
        value.get("tag") != TAG
        or value.get("annotated") is not True
        or value.get("peeled_commit") != commit
        or value.get("message") != TITLE
        or not isinstance(value.get("object_sha"), str)
        or COMMIT_RE.fullmatch(value["object_sha"]) is None
    ):
        raise S4ExecutionError("E_V250_S4_TAG_DRIFT")
    return dict(value)


def _validate_release_identity(
    release: object,
    expected_assets: Mapping[str, Mapping[str, object]],
    *,
    release_body: str,
    require_complete: bool,
    require_published: bool,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    value = release if isinstance(release, dict) else {}
    if (
        not isinstance(value.get("id"), int)
        or isinstance(value.get("id"), bool)
        or value["id"] < 1
        or value.get("tag_name") != TAG
        or value.get("name") != TITLE
        or value.get("body") != release_body
        or value.get("prerelease") is not False
        or not isinstance(value.get("draft"), bool)
        or (require_published and value.get("draft") is not False)
        or not isinstance(value.get("assets"), list)
    ):
        raise S4ExecutionError("E_V250_S4_RELEASE_DRIFT")
    observed: dict[str, dict[str, object]] = {}
    for raw in value["assets"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            raise S4ExecutionError("E_V250_S4_REMOTE_ASSET_DRIFT")
        name = raw["name"]
        if name in observed or name not in expected_assets:
            raise S4ExecutionError("E_V250_S4_REMOTE_ASSET_DRIFT")
        expected = expected_assets[name]
        digest = raw.get("digest")
        if (
            not isinstance(raw.get("id"), int)
            or isinstance(raw.get("id"), bool)
            or raw["id"] < 1
            or raw.get("state") != "uploaded"
            or raw.get("size") != expected["size"]
            or (
                digest not in {None, ""}
                and digest != f"sha256:{expected['sha256']}"
            )
        ):
            raise S4ExecutionError("E_V250_S4_REMOTE_ASSET_DRIFT")
        observed[name] = dict(raw)
    if require_complete and set(observed) != set(expected_assets):
        raise S4ExecutionError("E_V250_S4_REMOTE_ASSET_DRIFT")
    release_url = value.get("html_url")
    if (
        (value.get("draft") is False and release_url != CANONICAL_RELEASE_URL)
        or (
            value.get("draft") is True
            and release_url != CANONICAL_RELEASE_URL
            and (
                not isinstance(release_url, str)
                or DRAFT_RELEASE_URL_RE.fullmatch(release_url) is None
            )
        )
    ):
        raise S4ExecutionError("E_V250_S4_RELEASE_DRIFT")
    return dict(value), observed


def _asset_identity_projection(
    assets: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    stable_fields = ("id", "name", "size", "state", "digest")
    return {
        name: {field: asset.get(field) for field in stable_fields}
        for name, asset in assets.items()
    }


def _receipt_tag_observation(value: object) -> dict[str, object] | None:
    """Project a raw tag readback into the schema-safe failure receipt shape."""

    raw = value if isinstance(value, dict) else {}
    keys = ("tag", "object_sha", "peeled_commit", "annotated", "message")
    if (
        raw.get("tag") != TAG
        or not isinstance(raw.get("object_sha"), str)
        or COMMIT_RE.fullmatch(raw["object_sha"]) is None
        or not isinstance(raw.get("peeled_commit"), str)
        or COMMIT_RE.fullmatch(raw["peeled_commit"]) is None
        or raw.get("annotated") is not True
        or raw.get("message") != TITLE
    ):
        return None
    return {key: raw[key] for key in keys}


def _receipt_release_observation(value: object) -> dict[str, object] | None:
    """Retain a terminal published release observation without widening Schema."""

    raw = value if isinstance(value, dict) else {}
    if (
        not isinstance(raw.get("id"), int)
        or isinstance(raw.get("id"), bool)
        or raw["id"] < 1
        or raw.get("html_url") != CANONICAL_RELEASE_URL
        or raw.get("draft") is not False
        or raw.get("prerelease") is not False
    ):
        return None
    return {
        "release_id": raw["id"],
        "url": raw["html_url"],
        "state": "published",
        "draft": False,
        "prerelease": False,
    }


def _observed_remote_assets(value: object) -> dict[str, dict[str, object]]:
    raw = value if isinstance(value, dict) else {}
    assets = raw.get("assets")
    if not isinstance(assets, list):
        return {}
    return {
        asset["name"]: dict(asset)
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and asset["name"] in CANONICAL_ASSET_NAMES
    }


def _record_remote_tag_observation(
    context: dict[str, Any], value: object, *, existing: bool = False
) -> None:
    context["tag_readback"] = _receipt_tag_observation(value)
    if existing:
        context.setdefault("reconciliation_observed_steps", set()).add("tag_push")


def _record_release_observation(
    context: dict[str, Any], value: object, *, existing: bool = False
) -> None:
    context["release_readback"] = _receipt_release_observation(value)
    context["remote_assets"] = _observed_remote_assets(value)
    if existing:
        context.setdefault("reconciliation_observed_steps", set()).add(
            "release_create"
        )


def _download_one_exact(
    *,
    backend: S4Backend,
    name: str,
    expected: Mapping[str, object],
    remote: Mapping[str, object],
    target: Path,
) -> dict[str, object]:
    backend.download_asset(REPOSITORY, TAG, name, target)
    if not target.is_file() or target.is_symlink():
        raise S4ExecutionError("E_V250_S4_ASSET_DOWNLOAD")
    metadata = target.stat()
    digest = _sha256_file(target)
    if (
        metadata.st_size != expected["size"]
        or digest != expected["sha256"]
        or remote.get("size") != metadata.st_size
    ):
        raise S4ExecutionError("E_V250_S4_DOWNLOAD_DRIFT")
    return {
        "name": name,
        "asset_id": remote["id"],
        "size": metadata.st_size,
        "sha256": digest,
        "download_sha256": digest,
    }


def _download_exact_bundle(
    *,
    backend: S4Backend,
    bundle: Path,
    local_assets: Mapping[str, Mapping[str, object]],
    remote_assets: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    bundle.mkdir()
    return [
        _download_one_exact(
            backend=backend,
            name=name,
            expected=local_assets[name],
            remote=remote_assets[name],
            target=bundle / name,
        )
        for name in CANONICAL_ASSET_NAMES
    ]


def _verify_remote_asset(
    *,
    backend: S4Backend,
    name: str,
    local_assets: Mapping[str, Mapping[str, object]],
    release_body: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    release = backend.read_release(REPOSITORY, TAG)
    value, remote_assets = _validate_release_identity(
        release,
        local_assets,
        release_body=release_body,
        require_complete=False,
        require_published=False,
    )
    remote = remote_assets.get(name)
    if remote is None:
        raise S4ExecutionError("E_V250_S4_REMOTE_ASSET_ABSENT")
    with tempfile.TemporaryDirectory(prefix="goal-teams-v250-asset-readback-") as temp:
        _download_one_exact(
            backend=backend,
            name=name,
            expected=local_assets[name],
            remote=remote,
            target=Path(temp) / name,
        )
    return value, remote_assets


def _build_published_identity(
    *,
    release: Mapping[str, object],
    downloaded: list[dict[str, object]],
    control: Mapping[str, object],
) -> dict[str, object]:
    return {
        "source_kind": "github_release_asset",
        "repository": REPOSITORY,
        "version": VERSION,
        "release_tag": TAG,
        "release_id": release["id"],
        "release_state": "published",
        "source_commit": control["source_commit"],
        "source_git_tree_id": control["source_tree"],
        "assets": downloaded,
    }


def _parse_release_file_manifest(path: Path) -> list[dict[str, object]]:
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise S4ExecutionError("E_V250_S4_RELEASE_FILES") from exc
    if not data.endswith(b"\n"):
        raise S4ExecutionError("E_V250_S4_RELEASE_FILES")
    entries: list[dict[str, object]] = []
    seen_casefold: set[str] = set()
    previous: str | None = None
    for line in text.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            raise S4ExecutionError("E_V250_S4_RELEASE_FILES")
        digest, git_mode, size_raw, relative = parts
        try:
            size = int(size_raw)
        except ValueError as exc:
            raise S4ExecutionError("E_V250_S4_RELEASE_FILES") from exc
        path_value = PurePosixPath(relative)
        if (
            SHA256_RE.fullmatch(digest) is None
            or git_mode not in {"100644", "100755"}
            or size < 0
            or not relative
            or relative != unicodedata.normalize("NFC", relative)
            or "\\" in relative
            or path_value.is_absolute()
            or any(part in {"", ".", ".."} for part in path_value.parts)
            or path_value.as_posix() != relative
            or relative.casefold() in seen_casefold
            or (previous is not None and relative <= previous)
        ):
            raise S4ExecutionError("E_V250_S4_RELEASE_FILES")
        previous = relative
        seen_casefold.add(relative.casefold())
        entries.append(
            {
                "path": relative,
                "sha256": digest,
                "size": size,
                "mode": 0o755 if git_mode == "100755" else 0o644,
            }
        )
        if len(entries) > MAX_PACKAGE_FILES:
            raise S4ExecutionError("E_V250_S4_RELEASE_FILES")
    if not entries:
        raise S4ExecutionError("E_V250_S4_RELEASE_FILES")
    return entries


def _validate_release_file_binding(
    record: Mapping[str, object], package_files: list[dict[str, object]]
) -> None:
    digest_input = b"".join(
        (
            f"{item['path']}\0"
            f"{('100755' if item['mode'] == 0o755 else '100644')}\0"
            f"{item['size']}\0{item['sha256']}\n"
        ).encode("utf-8")
        for item in package_files
    )
    if (
        record.get("file_count") != len(package_files)
        or record.get("total_bytes")
        != sum(int(item["size"]) for item in package_files)
        or record.get("tree_sha256") != hashlib.sha256(digest_input).hexdigest()
    ):
        raise S4ExecutionError("E_V250_S4_RELEASE_FILES_BINDING")


def _installed_state_matches(
    state: object,
    *,
    identity: Mapping[str, object],
    identity_sha256: str,
    record: Mapping[str, object],
    installed_version: str | None,
) -> bool:
    if not isinstance(state, dict):
        return False
    tar_name = f"goal-teams-{identity['version']}.tar.gz"
    tar_digest = next(
        item["sha256"]
        for item in identity["assets"]
        if isinstance(item, dict) and item.get("name") == tar_name
    )
    return bool(
        state.get("source_kind") == "github_release_asset"
        and state.get("repository") == identity["repository"]
        and state.get("version") == identity["version"]
        and state.get("release_tag") == identity["release_tag"]
        and state.get("release_id") == identity["release_id"]
        and state.get("release_state") == "published"
        and state.get("source_commit") == identity["source_commit"]
        and state.get("source_git_tree_id") == identity["source_git_tree_id"]
        and state.get("release_assets") == identity["assets"]
        and state.get("release_identity_sha256") == identity_sha256
        and state.get("release_asset_sha256") == tar_digest
        and state.get("bundle_tree_sha256") == record["tree_sha256"]
        and state.get("source_tree_digest") == record["tree_sha256"]
        and state.get("source_dirty") is False
        and installed_version == identity["version"]
    )


def _safe_string(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _known_identity(
    version: str, commit: str, control: object
) -> dict[str, object | None]:
    value = control if isinstance(control, dict) else {}
    authorization = value.get("authorization_receipt")
    authorization_id = (
        authorization.get("authorization_id")
        if isinstance(authorization, dict)
        else None
    )
    return {
        "repository": REPOSITORY if value.get("repository") == REPOSITORY else None,
        "version": VERSION if version == VERSION else None,
        "tag": TAG if value.get("tag") == TAG else None,
        "source_commit": _safe_string(commit, COMMIT_RE),
        "source_tree": _safe_string(value.get("source_tree"), COMMIT_RE),
        "asset_set_id": _safe_string(value.get("asset_set_id"), SAFE_ID_RE),
        "asset_set_digest": _safe_string(value.get("asset_set_digest"), SHA256_RE),
        "intent_sha256": _safe_string(value.get("intent_sha256"), SHA256_RE),
        "authorization_id": _safe_string(authorization_id, SAFE_ID_RE),
        "release_control_sha256": _safe_string(
            value.get("release_control_sha256"), SHA256_RE
        ),
    }


def _known_asset_readback(
    control: object,
    local_assets: Mapping[str, Mapping[str, object]] | None = None,
    remote_assets: Mapping[str, Mapping[str, object]] | None = None,
    downloaded: Sequence[Mapping[str, object]] | None = None,
) -> list[dict[str, object | None]]:
    control_value = control if isinstance(control, dict) else {}
    s2 = control_value.get("s2")
    raw = s2.get("assets") if isinstance(s2, dict) else []
    candidates = {
        row.get("name"): row
        for row in raw
        if isinstance(row, dict) and row.get("name") in CANONICAL_ASSET_NAMES
    }
    local = local_assets or {}
    remote = remote_assets or {}
    downloaded_by_name = {
        row.get("name"): row for row in (downloaded or []) if isinstance(row, Mapping)
    }
    output: list[dict[str, object | None]] = []
    for name in CANONICAL_ASSET_NAMES:
        source = local.get(name) or candidates.get(name, {})
        remote_row = remote.get(name, {})
        download = downloaded_by_name.get(name, {})
        size = source.get("size") if isinstance(source, Mapping) else None
        digest = source.get("sha256") if isinstance(source, Mapping) else None
        output.append(
            {
                "name": name,
                "asset_id": (
                    remote_row.get("id")
                    if isinstance(remote_row.get("id"), int)
                    and not isinstance(remote_row.get("id"), bool)
                    else None
                ),
                "size": size if isinstance(size, int) and not isinstance(size, bool) else None,
                "sha256": digest if isinstance(digest, str) and SHA256_RE.fullmatch(digest) else None,
                "download_sha256": (
                    download.get("download_sha256")
                    if isinstance(download.get("download_sha256"), str)
                    and SHA256_RE.fullmatch(str(download.get("download_sha256")))
                    else None
                ),
            }
        )
    return output


def _operation_metrics(journal: OperationJournal) -> dict[str, Any]:
    entries = journal.snapshot()
    attempted = [entry for entry in entries if entry["attempted_this_run"]]
    confirmed = [entry for entry in attempted if entry["state"] == "confirmed"]
    uncertain = [entry for entry in attempted if entry["state"] == "uncertain"]
    external_confirmed = [
        entry
        for entry in confirmed
        if entry["scope"] in {"external_service", "local_install"}
    ]
    counts = {
        "tag_create": sum(
            entry["step_id"] == "tag_local_create" for entry in attempted
        ),
        "tag_push": sum(entry["step_id"] == "tag_push" for entry in attempted),
        "release_create": sum(
            entry["step_id"] == "release_create" for entry in attempted
        ),
        "asset_upload": sum(
            str(entry["step_id"]).startswith("asset_upload:") for entry in attempted
        ),
        "release_publish": sum(
            entry["step_id"] == "release_publish" for entry in attempted
        ),
        "install": sum(entry["step_id"] == "install" for entry in attempted),
    }
    return {
        "entries": entries,
        "operation_counts": counts,
        "write_attempt_count": len(attempted),
        "external_write_attempt_count": sum(
            entry["scope"] in {"external_service", "local_install"}
            for entry in attempted
        ),
        "confirmed_side_effect_count": len(confirmed),
        "external_side_effect_count": len(external_confirmed),
        "uncertain_write_count": len(uncertain),
        "action_executed": bool(confirmed or uncertain),
    }


def _failure_class(journal: OperationJournal) -> str:
    attempted = journal.attempted()
    if not attempted:
        return "blocked_before_write"
    if any(entry["state"] in {"confirmed", "uncertain"} for entry in attempted):
        return "partial_or_uncertain"
    return "failed_after_write"


def _read_unavailable(exc: Exception) -> bool:
    if isinstance(exc, OSError):
        return True
    if not isinstance(exc, S4ExecutionError):
        return True
    return any(
        marker in exc.code
        for marker in (
            "READBACK",
            "DOWNLOAD",
            "GITHUB_RESPONSE",
            "INSTALLED_STATE",
            "INSTALLED_VERSION",
        )
    )


def _reconcile(
    journal: OperationJournal,
    context: dict[str, Any],
) -> dict[str, Any]:
    attempted = journal.attempted()
    observed_steps = context.get("reconciliation_observed_steps", set())
    existing_steps = (
        [step for step in ("tag_push", "release_create") if step in observed_steps]
        if isinstance(observed_steps, set)
        else []
    )
    steps = [str(entry["step_id"]) for entry in attempted]
    steps.extend(step for step in existing_steps if step not in steps)
    if not steps:
        return {
            "performed": True,
            "trigger": "exception",
            "overall_state": "not_required",
            "entries": [],
        }
    backend: S4Backend | None = context.get("backend")
    local_assets: Mapping[str, Mapping[str, object]] = context.get("local_assets", {})
    release_body = context.get("release_body")
    entries: list[dict[str, str]] = []
    for step_id in steps:
        entry = journal._entry(step_id)
        observed = "unavailable"
        if backend is not None:
            try:
                if step_id == "tag_local_create":
                    value = backend.read_local_tag(TAG)
                    if value is None:
                        observed = "absent"
                    else:
                        _validate_tag(value, str(context.get("commit", "")))
                        observed = "exact"
                elif step_id == "tag_push" and context.get("safe_remote"):
                    value = backend.read_tag(TAG)
                    _record_remote_tag_observation(context, value)
                    if value is None:
                        observed = "absent"
                    else:
                        validated = _validate_tag(
                            value, str(context.get("commit", ""))
                        )
                        baseline = context.get("baseline_tag_readback")
                        observed = (
                            "conflict"
                            if isinstance(baseline, dict)
                            and _receipt_tag_observation(validated) != baseline
                            else "exact"
                        )
                elif step_id == "release_create" and context.get("safe_remote"):
                    release = backend.read_release(REPOSITORY, TAG)
                    _record_release_observation(context, release)
                    if release is None:
                        observed = "absent"
                    else:
                        value, remote = _validate_release_identity(
                            release,
                            local_assets,
                            release_body=str(release_body),
                            require_complete=False,
                            require_published=False,
                        )
                        baseline_release = context.get("baseline_release_readback")
                        baseline_assets = context.get("baseline_remote_assets")
                        observed = (
                            "conflict"
                            if (
                                isinstance(baseline_release, dict)
                                and _receipt_release_observation(value)
                                != baseline_release
                            )
                            or (
                                isinstance(baseline_assets, dict)
                                and _asset_identity_projection(remote)
                                != _asset_identity_projection(baseline_assets)
                            )
                            else "exact"
                        )
                elif step_id.startswith("asset_upload:") and context.get("safe_remote"):
                    name = step_id.split(":", 1)[1]
                    release = backend.read_release(REPOSITORY, TAG)
                    if release is None:
                        observed = "absent"
                    else:
                        _, remote = _validate_release_identity(
                            release,
                            local_assets,
                            release_body=str(release_body),
                            require_complete=False,
                            require_published=False,
                        )
                        if name not in remote:
                            observed = "absent"
                        else:
                            with tempfile.TemporaryDirectory(
                                prefix="goal-teams-v250-reconcile-asset-"
                            ) as temp:
                                _download_one_exact(
                                    backend=backend,
                                    name=name,
                                    expected=local_assets[name],
                                    remote=remote[name],
                                    target=Path(temp) / name,
                                )
                            observed = "exact"
                elif step_id == "release_publish" and context.get("safe_remote"):
                    release = backend.read_release(REPOSITORY, TAG)
                    if release is None:
                        observed = "absent"
                    else:
                        _validate_release_identity(
                            release,
                            local_assets,
                            release_body=str(release_body),
                            require_complete=True,
                            require_published=True,
                        )
                        observed = "exact"
                elif step_id == "install":
                    identity = context.get("identity")
                    record = context.get("record")
                    package_files = context.get("package_files")
                    identity_sha256 = context.get("identity_sha256")
                    if not all(
                        value is not None
                        for value in (identity, record, package_files, identity_sha256)
                    ):
                        observed = "unavailable"
                    else:
                        state = backend.read_installed_state()
                        installed_version = backend.read_installed_version()
                        if state is None:
                            observed = "absent"
                        elif not _installed_state_matches(
                            state,
                            identity=identity,
                            identity_sha256=identity_sha256,
                            record=record,
                            installed_version=installed_version,
                        ):
                            observed = "conflict"
                        else:
                            backend.verify_installed_payload(package_files, state)
                            observed = "exact"
            except Exception as exc:
                observed = "unavailable" if _read_unavailable(exc) else "conflict"
        journal.observe(step_id, observed)
        entries.append({"step_id": step_id, "observed_state": observed})
    states = [entry["observed_state"] for entry in entries]
    if "unavailable" in states:
        overall = "uncertain"
    elif "exact" in states and any(state != "exact" for state in states):
        overall = "partial"
    elif states and all(state == "exact" for state in states):
        overall = "exact"
    elif "conflict" in states:
        overall = "conflict"
    else:
        overall = "absent"
    return {
        "performed": True,
        "trigger": "exception",
        "overall_state": overall,
        "entries": entries,
    }


def _assert_outcome_invariants(receipt: Mapping[str, Any]) -> None:
    without_digest = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    if receipt.get("receipt_sha256") != canonical_sha256(without_digest):
        raise S4ExecutionError("E_V250_S4_OUTCOME_DIGEST")
    journal = receipt.get("operation_journal")
    if not isinstance(journal, list) or len(journal) != len(JOURNAL_LAYOUT):
        raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")
    for entry, expected in zip(journal, JOURNAL_LAYOUT, strict=True):
        if (
            not isinstance(entry, dict)
            or tuple(
                entry.get(key)
                for key in ("step_id", "operation", "target", "scope")
            )
            != expected
        ):
            raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")
        state = entry.get("state")
        attempted_flag = entry.get("attempted_this_run")
        readback = entry.get("readback_state")
        if (
            not isinstance(attempted_flag, bool)
            or (state == "confirmed" and readback != "exact")
            or (state == "uncertain" and (not attempted_flag or readback != "unavailable"))
            or (state == "attempted" and (not attempted_flag or readback not in {"not_run", "absent", "conflict"}))
            or (state == "not_started" and attempted_flag)
            or (not attempted_flag and state in {"attempted", "uncertain"})
        ):
            raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")
    attempted = [entry for entry in journal if entry.get("attempted_this_run") is True]
    confirmed = [entry for entry in attempted if entry.get("state") == "confirmed"]
    uncertain = [entry for entry in attempted if entry.get("state") == "uncertain"]
    external_confirmed = [
        entry
        for entry in confirmed
        if entry.get("scope") in {"external_service", "local_install"}
    ]
    expected_counts = {
        "tag_create": sum(entry.get("step_id") == "tag_local_create" for entry in attempted),
        "tag_push": sum(entry.get("step_id") == "tag_push" for entry in attempted),
        "release_create": sum(entry.get("step_id") == "release_create" for entry in attempted),
        "asset_upload": sum(str(entry.get("step_id", "")).startswith("asset_upload:") for entry in attempted),
        "release_publish": sum(entry.get("step_id") == "release_publish" for entry in attempted),
        "install": sum(entry.get("step_id") == "install" for entry in attempted),
    }
    expected_action = any(
        entry.get("state") in {"confirmed", "uncertain"} for entry in attempted
    )
    if (
        receipt.get("operation_counts") != expected_counts
        or receipt.get("write_attempt_count") != len(attempted)
        or receipt.get("external_write_attempt_count")
        != sum(
            entry.get("scope") in {"external_service", "local_install"}
            for entry in attempted
        )
        or receipt.get("confirmed_side_effect_count") != len(confirmed)
        or receipt.get("external_side_effect_count") != len(external_confirmed)
        or receipt.get("uncertain_write_count") != len(uncertain)
        or receipt.get("action_executed") is not expected_action
    ):
        raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")
    failure_class = receipt.get("failure_class")
    reconciliation = receipt.get("reconciliation")
    if not isinstance(reconciliation, dict):
        raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")
    if failure_class is None:
        required_confirmed = {
            "tag_push",
            "release_create",
            "release_publish",
            "install",
            *(f"asset_upload:{name}" for name in CANONICAL_ASSET_NAMES),
        }
        states = {entry.get("step_id"): entry.get("state") for entry in journal}
        if (
            receipt.get("ok") is not True
            or receipt.get("passed") is not True
            or any(states.get(step) != "confirmed" for step in required_confirmed)
            or uncertain
            or receipt.get("download_asset_set_digest")
            != receipt.get("asset_set_digest")
            or receipt.get("execution_mode")
            != ("executed_and_verified" if expected_action else "reconciled_existing")
            or reconciliation.get("performed") is not False
            or reconciliation.get("trigger") != "not_required"
            or reconciliation.get("overall_state") != "exact"
            or reconciliation.get("entries") != []
        ):
            raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")
        assets = receipt.get("asset_readback")
        tag = receipt.get("tag_readback")
        install = receipt.get("install_readback")
        if (
            not isinstance(assets, list)
            or [asset.get("name") for asset in assets if isinstance(asset, dict)]
            != list(CANONICAL_ASSET_NAMES)
            or any(
                not isinstance(asset, dict)
                or not isinstance(asset.get("asset_id"), int)
                or isinstance(asset.get("asset_id"), bool)
                or not isinstance(asset.get("size"), int)
                or isinstance(asset.get("size"), bool)
                or asset.get("size", -1) < 0
                or not isinstance(asset.get("sha256"), str)
                or SHA256_RE.fullmatch(asset["sha256"]) is None
                or asset.get("download_sha256") != asset.get("sha256")
                for asset in assets
            )
            or len({asset["asset_id"] for asset in assets}) != len(assets)
            or canonical_sha256(
                [
                    {
                        key: asset[key]
                        for key in ("name", "size", "sha256")
                    }
                    for asset in assets
                ]
            )
            != receipt.get("asset_set_digest")
            or not isinstance(tag, dict)
            or tag.get("tag") != receipt.get("tag")
            or tag.get("peeled_commit") != receipt.get("source_commit")
            or tag.get("annotated") is not True
            or tag.get("message") != TITLE
            or not isinstance(install, dict)
            or install.get("version") != receipt.get("version")
            or install.get("source_commit") != receipt.get("source_commit")
            or install.get("source_tree") != receipt.get("source_tree")
            or install.get("package_tree_sha256")
            != install.get("state_package_files_sha256")
            or install.get("installation_performed")
            is not (expected_counts["install"] == 1)
        ):
            raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")
    else:
        expected_class = (
            "blocked_before_write"
            if not attempted
            else (
                "partial_or_uncertain"
                if any(entry.get("state") in {"confirmed", "uncertain"} for entry in attempted)
                else "failed_after_write"
            )
        )
        reconciliation_entries = reconciliation.get("entries")
        attempted_ids = [entry.get("step_id") for entry in attempted]
        reconciliation_ids = (
            [entry.get("step_id") for entry in reconciliation_entries]
            if isinstance(reconciliation_entries, list)
            else []
        )
        supplemental_ids = [
            step_id for step_id in reconciliation_ids if step_id not in attempted_ids
        ]
        if (
            failure_class != expected_class
            or receipt.get("passed") is not False
            or reconciliation.get("performed") is not True
            or reconciliation.get("trigger") != "exception"
            or not isinstance(reconciliation_entries, list)
            or any(not isinstance(entry, dict) for entry in reconciliation_entries)
            or reconciliation_ids[: len(attempted_ids)] != attempted_ids
            or len(set(reconciliation_ids)) != len(reconciliation_ids)
            or any(
                step_id not in {"tag_push", "release_create"}
                for step_id in supplemental_ids
            )
            or any(
                not isinstance(item, dict)
                or next(
                    (
                        entry.get("readback_state")
                        for entry in journal
                        if entry.get("step_id") == item.get("step_id")
                    ),
                    None,
                ) != item.get("observed_state")
                for item in reconciliation_entries
            )
        ):
            raise S4ExecutionError("E_V250_S4_OUTCOME_INVARIANT")


def _finalize_receipt(
    receipt: dict[str, Any], validator: OutcomeValidator
) -> dict[str, Any]:
    receipt.pop("receipt_sha256", None)
    receipt["schema_validation"] = dict(validator.identity)
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    _assert_outcome_invariants(receipt)
    validator.validate(receipt)
    return receipt


def validate_outcome_receipt(
    receipt: Mapping[str, Any], validator: OutcomeValidator | None = None
) -> None:
    selected = validator or load_outcome_validator()
    if receipt.get("schema_validation") != selected.identity:
        raise S4ExecutionError("E_V250_S4_OUTCOME_SCHEMA_IDENTITY")
    _assert_outcome_invariants(receipt)
    selected.validate(receipt)


def _base_outcome(
    *,
    identity: Mapping[str, object | None],
    journal: OperationJournal,
    reconciliation: Mapping[str, Any],
    control: object,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = _operation_metrics(journal)
    return {
        "schema_version": "goal-teams-v2.63-s4-outcome-receipt-v2",
        "gate_id": "s4_publish_install_readback",
        **identity,
        "action_executed": metrics["action_executed"],
        "external_side_effect_count": metrics["external_side_effect_count"],
        "write_attempt_count": metrics["write_attempt_count"],
        "external_write_attempt_count": metrics["external_write_attempt_count"],
        "confirmed_side_effect_count": metrics["confirmed_side_effect_count"],
        "uncertain_write_count": metrics["uncertain_write_count"],
        "operation_counts": metrics["operation_counts"],
        "operation_journal": metrics["entries"],
        "reconciliation": dict(reconciliation),
        "git_transport": "ssh_only",
        "https_git_fallback_allowed": False,
        "additional_user_confirmation_required": False,
        "tag_readback": context.get("tag_readback"),
        "release_readback": context.get("release_readback"),
        "asset_readback": _known_asset_readback(
            control,
            context.get("local_assets"),
            context.get("remote_assets"),
            context.get("downloaded"),
        ),
        "download_asset_set_digest": context.get("download_asset_set_digest"),
        "install_readback": context.get("install_readback"),
    }


def _failure_receipt(
    *,
    code: str,
    identity: Mapping[str, object | None],
    journal: OperationJournal,
    reconciliation: Mapping[str, Any],
    control: object,
    context: Mapping[str, Any],
    validator: OutcomeValidator | None,
    validator_error: str | None = None,
) -> dict[str, Any]:
    classification = _failure_class(journal)
    receipt = {
        **_base_outcome(
            identity=identity,
            journal=journal,
            reconciliation=reconciliation,
            control=control,
            context=context,
        ),
        "check_state": "blocked" if classification == "blocked_before_write" else "failed",
        "run_outcome": "blocked" if classification == "blocked_before_write" else "failed",
        "evidence_state": "invalid",
        "ok": False,
        "passed": False,
        "error_code": code,
        "failure_class": classification,
        "execution_mode": None,
    }
    if validator is None:
        try:
            schema_digest = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
        except OSError:
            schema_digest = None
        try:
            runtime_schema_digest = hashlib.sha256(
                RUNTIME_TRANSITION_SCHEMA_PATH.read_bytes()
            ).hexdigest()
        except OSError:
            runtime_schema_digest = None
        receipt["schema_validation"] = {
            "state": "unavailable",
            "engine": None,
            "schema_ref": SCHEMA_REF,
            "schema_sha256": schema_digest,
            "runtime_transition_schema_sha256": runtime_schema_digest,
            "error_code": validator_error or "E_V250_S4_SCHEMA_VALIDATOR_UNAVAILABLE",
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt
    try:
        return _finalize_receipt(receipt, validator)
    except Exception as exc:
        validation_code = (
            exc.code
            if isinstance(exc, S4ExecutionError)
            else (
                "E_V250_S4_SCHEMA_VALIDATOR_UNAVAILABLE"
                if isinstance(exc, OSError)
                else "E_V250_S4_OUTCOME_SCHEMA"
            )
        )
        receipt.pop("receipt_sha256", None)
        receipt["schema_validation"] = {
            **validator.identity,
            "state": (
                "unavailable" if isinstance(exc, OSError) else "invalid"
            ),
            "error_code": validation_code,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt


def execute_s4(
    *,
    version: str,
    commit: str,
    release_control: dict[str, object],
    release_root: Path,
    checkpoint_receipt: Path,
    receipt_root: Path,
    expected_workflow_run_id: str,
    expected_workflow_run_attempt: str,
    repository_root: Path = ROOT,
    backend: S4Backend | None = None,
    runner: CommandRunner | None = None,
    checkpoint_validator: Callable[..., dict[str, object]] = (
        _default_checkpoint_validator
    ),
    control_validator: Callable[
        [str, str, dict[str, object]], dict[str, object]
    ] = _default_control_validator,
    prewrite_boundary_validator: Callable[..., dict[str, object]] | None = None,
    outcome_validator: OutcomeValidator | None = None,
) -> dict[str, object]:
    """Execute absent S4 operations once and require exact terminal readback."""

    journal = OperationJournal()
    identity = _known_identity(version, commit, release_control)
    context: dict[str, Any] = {"commit": commit}
    validator: OutcomeValidator | None = None
    try:
        if sys.version_info < (3, 11):
            raise S4ExecutionError("E_V250_S4_PYTHON_VERSION")
        validator = outcome_validator or load_outcome_validator()
        if version != VERSION or COMMIT_RE.fullmatch(commit) is None:
            raise S4ExecutionError("E_V250_S4_IDENTITY")
        if not isinstance(release_control, dict):
            raise S4ExecutionError("E_V250_RELEASE_CONTROL_REQUIRED")
        if (
            not isinstance(expected_workflow_run_id, str)
            or not isinstance(expected_workflow_run_attempt, str)
            or POSITIVE_DECIMAL_RE.fullmatch(expected_workflow_run_id) is None
            or POSITIVE_DECIMAL_RE.fullmatch(expected_workflow_run_attempt) is None
        ):
            raise S4ExecutionError(
                "E_V250_S4_CHECKPOINT_WORKFLOW_IDENTITY"
            )
        checkpoint_verdict = checkpoint_validator(
            version,
            commit,
            checkpoint_receipt,
            receipt_root=receipt_root,
            release_root=release_root,
            expected_workflow_run_id=expected_workflow_run_id,
            expected_workflow_run_attempt=expected_workflow_run_attempt,
            release_control=release_control,
        )
        _require_checkpoint_verdict(
            checkpoint_verdict,
            version=version,
            commit=commit,
        )
        if control_validator is _default_control_validator:
            verdict = _default_control_validator(
                version,
                commit,
                release_control,
                receipt_root=receipt_root,
            )
        else:
            verdict = control_validator(version, commit, release_control)
        if not isinstance(verdict, dict) or verdict.get("ok") is not True:
            errors = verdict.get("errors") if isinstance(verdict, dict) else None
            code = (
                errors[0]
                if isinstance(errors, list) and errors
                else "E_V250_RELEASE_CONTROL_REQUIRED"
            )
            raise S4ExecutionError(str(code))
        if (
            release_control.get("repository") != REPOSITORY
            or release_control.get("version") != version
            or release_control.get("tag") != TAG
            or release_control.get("source_commit") != commit
            or release_control.get("source_tree") != verdict.get("source_tree")
            or not isinstance(release_control.get("asset_set_id"), str)
            or not isinstance(release_control.get("asset_set_digest"), str)
            or SHA256_RE.fullmatch(str(release_control["asset_set_digest"])) is None
        ):
            raise S4ExecutionError("E_V250_S4_CONTROL_IDENTITY")
        authorization = release_control.get("authorization_receipt")
        repository_identity = (
            authorization.get("repository") if isinstance(authorization, dict) else None
        )
        if not isinstance(repository_identity, dict):
            raise S4ExecutionError("E_V250_S4_AUTHORIZATION")
        expected_fetch = repository_identity.get("origin_fetch")
        expected_push = repository_identity.get("origin_push")
        if expected_fetch != CANONICAL_REMOTE or expected_push != CANONICAL_REMOTE:
            raise S4ExecutionError("E_V250_S4_AUTHORIZATION_REMOTE")

        root = repository_root.resolve()
        release_profile = _load_release_profile_contract(root)
        release_body = release_profile["release_body"]
        context["release_body"] = release_body
        paths, assets, record = _validate_local_assets(
            release_root=release_root,
            repository_root=root,
            control=release_control,
            version=version,
            commit=commit,
        )
        local_assets = {str(item["name"]): item for item in assets}
        context.update({"local_assets": local_assets, "record": record})
        selected_backend = backend or CommandBackend(root, runner)
        context["backend"] = selected_backend
        if (
            selected_backend.read_fetch_remote() != expected_fetch
            or selected_backend.read_push_remote() != expected_push
        ):
            raise S4ExecutionError("E_V250_S4_GIT_TRANSPORT_NOT_SSH")
        context["safe_remote"] = True
        boundary_validator = (
            prewrite_boundary_validator
            or _default_prewrite_boundary_validator
        )
        boundary_verdict = boundary_validator(
            repository_root=root,
            release_root=release_root,
            source_commit=commit,
            source_tree=str(release_control["source_tree"]),
            control=release_control,
            asset_paths=paths,
        )
        if (
            not isinstance(boundary_verdict, dict)
            or boundary_verdict.get("ok") is not True
            or boundary_verdict.get("passed") is not True
        ):
            raise S4ExecutionError("E_V250_S4_REPOSITORY_BOUNDARY_REVALIDATION")
        context["prewrite_boundary"] = boundary_verdict

        remote_tag = selected_backend.read_tag(TAG)
        _record_remote_tag_observation(
            context, remote_tag, existing=remote_tag is not None
        )
        if remote_tag is None:
            local_tag = selected_backend.read_local_tag(TAG)
            if local_tag is None:
                journal.attempt("tag_local_create")
                selected_backend.create_annotated_tag(TAG, commit, TITLE)
                local_tag = selected_backend.read_local_tag(TAG)
                local_tag = _validate_tag(local_tag, commit)
                journal.observe("tag_local_create", "exact")
            else:
                local_tag = _validate_tag(local_tag, commit)
                journal.observe("tag_local_create", "exact")
            journal.attempt("tag_push")
            selected_backend.push_tag(TAG, str(local_tag["object_sha"]))
            remote_tag = selected_backend.read_tag(TAG)
            _record_remote_tag_observation(context, remote_tag)
            tag_readback = _validate_tag(remote_tag, commit)
            journal.observe("tag_push", "exact")
        else:
            tag_readback = _validate_tag(remote_tag, commit)
            journal.observe("tag_push", "exact")
        context["tag_readback"] = tag_readback
        context["baseline_tag_readback"] = dict(tag_readback)

        release = selected_backend.read_release(REPOSITORY, TAG)
        _record_release_observation(
            context, release, existing=release is not None
        )
        if release is None:
            journal.attempt("release_create")
            selected_backend.create_draft_release(
                REPOSITORY,
                TAG,
                release_profile["release_title"],
                release_body,
            )
            release = selected_backend.read_release(REPOSITORY, TAG)
            _record_release_observation(context, release)
            release_value, remote_assets = _validate_release_identity(
                release,
                local_assets,
                release_body=release_body,
                require_complete=False,
                require_published=False,
            )
            journal.observe("release_create", "exact")
        else:
            release_value, remote_assets = _validate_release_identity(
                release,
                local_assets,
                release_body=release_body,
                require_complete=False,
                require_published=False,
            )
            journal.observe("release_create", "exact")
        context["remote_assets"] = remote_assets

        for name in CANONICAL_ASSET_NAMES:
            step_id = f"asset_upload:{name}"
            if name not in remote_assets:
                journal.attempt(step_id)
                selected_backend.upload_asset(REPOSITORY, TAG, paths[name])
            release_value, remote_assets = _verify_remote_asset(
                backend=selected_backend,
                name=name,
                local_assets=local_assets,
                release_body=release_body,
            )
            context["remote_assets"] = remote_assets
            journal.observe(step_id, "exact")

        release = selected_backend.read_release(REPOSITORY, TAG)
        release_value, remote_assets = _validate_release_identity(
            release,
            local_assets,
            release_body=release_body,
            require_complete=True,
            require_published=False,
        )
        context["remote_assets"] = remote_assets
        if release_value["draft"] is True:
            journal.attempt("release_publish")
            selected_backend.publish_release(REPOSITORY, TAG)
            release = selected_backend.read_release(REPOSITORY, TAG)
            release_value, remote_assets = _validate_release_identity(
                release,
                local_assets,
                release_body=release_body,
                require_complete=True,
                require_published=True,
            )
            journal.observe("release_publish", "exact")
        else:
            release_value, remote_assets = _validate_release_identity(
                release_value,
                local_assets,
                release_body=release_body,
                require_complete=True,
                require_published=True,
            )
            journal.observe("release_publish", "exact")
        context["remote_assets"] = remote_assets
        context["release_readback"] = {
            "release_id": release_value["id"],
            "url": release_value["html_url"],
            "state": "published",
            "draft": False,
            "prerelease": False,
        }
        context["baseline_release_readback"] = dict(
            context["release_readback"]
        )
        context["baseline_remote_assets"] = _asset_identity_projection(
            remote_assets
        )

        with tempfile.TemporaryDirectory(prefix="goal-teams-v250-s4-") as temp:
            work = Path(temp)
            bundle = work / "release-bundle"
            downloaded = _download_exact_bundle(
                backend=selected_backend,
                bundle=bundle,
                local_assets=local_assets,
                remote_assets=remote_assets,
            )
            context["downloaded"] = downloaded
            download_digest = canonical_sha256(
                [
                    {key: item[key] for key in ("name", "size", "sha256")}
                    for item in downloaded
                ]
            )
            if download_digest != release_control["asset_set_digest"]:
                raise S4ExecutionError("E_V250_S4_DOWNLOAD_DRIFT")
            context["download_asset_set_digest"] = download_digest
            identity_payload = _build_published_identity(
                release=release_value,
                downloaded=downloaded,
                control=release_control,
            )
            identity_bytes = _canonical_json_bytes(identity_payload)
            identity_sha256 = hashlib.sha256(identity_bytes).hexdigest()
            identity_path = work / "published-release-identity.json"
            identity_path.write_bytes(identity_bytes)
            package_files = _parse_release_file_manifest(bundle / "_files.sha256")
            _validate_release_file_binding(record, package_files)
            context.update(
                {
                    "identity": identity_payload,
                    "identity_sha256": identity_sha256,
                    "package_files": package_files,
                }
            )

            before_state = selected_backend.read_installed_state()
            before_version = selected_backend.read_installed_version()
            exact_before = _installed_state_matches(
                before_state,
                identity=identity_payload,
                identity_sha256=identity_sha256,
                record=record,
                installed_version=before_version,
            )
            if (
                isinstance(before_state, dict)
                and before_state.get("version") == VERSION
                and not exact_before
            ):
                raise S4ExecutionError("E_V250_S4_INSTALLED_IDENTITY_DRIFT")
            if exact_before:
                assert isinstance(before_state, dict)
                payload_readback = selected_backend.verify_installed_payload(
                    package_files, before_state
                )
                journal.observe("install", "exact")
            else:
                journal.attempt("install")
                selected_backend.install(bundle, identity_path)
                installed_after_write = selected_backend.read_installed_state()
                version_after_write = selected_backend.read_installed_version()
                if not _installed_state_matches(
                    installed_after_write,
                    identity=identity_payload,
                    identity_sha256=identity_sha256,
                    record=record,
                    installed_version=version_after_write,
                ):
                    raise S4ExecutionError("E_V250_S4_INSTALLED_IDENTITY_READBACK")
                assert isinstance(installed_after_write, dict)
                payload_readback = selected_backend.verify_installed_payload(
                    package_files, installed_after_write
                )
                journal.observe("install", "exact")
            installed = selected_backend.read_installed_state()
            installed_version = selected_backend.read_installed_version()
            if not _installed_state_matches(
                installed,
                identity=identity_payload,
                identity_sha256=identity_sha256,
                record=record,
                installed_version=installed_version,
            ):
                raise S4ExecutionError("E_V250_S4_INSTALLED_IDENTITY_READBACK")
            assert isinstance(installed, dict)
            final_payload_readback = selected_backend.verify_installed_payload(
                package_files, installed
            )
            if final_payload_readback != payload_readback:
                raise S4ExecutionError("E_V250_S4_INSTALLED_PACKAGE_DRIFT")
            context["install_readback"] = {
                "installed_state_sha256": canonical_sha256(installed),
                "release_identity_sha256": identity_sha256,
                "version": VERSION,
                "source_commit": commit,
                "source_tree": release_control["source_tree"],
                "installation_performed": journal._entry("install")[
                    "attempted_this_run"
                ],
                **payload_readback,
            }

        prior_tag_readback = context.get("tag_readback")
        terminal_tag_raw = selected_backend.read_tag(TAG)
        _record_remote_tag_observation(context, terminal_tag_raw)
        terminal_tag = _validate_tag(terminal_tag_raw, commit)
        if _receipt_tag_observation(terminal_tag) != prior_tag_readback:
            raise S4ExecutionError("E_V250_S4_TAG_DRIFT")
        context["tag_readback"] = terminal_tag
        terminal_release_raw = selected_backend.read_release(REPOSITORY, TAG)
        _record_release_observation(context, terminal_release_raw)
        terminal_release_value, terminal_assets = _validate_release_identity(
            terminal_release_raw,
            local_assets,
            release_body=release_body,
            require_complete=True,
            require_published=True,
        )
        if (
            terminal_release_value["id"] != release_value["id"]
            or _asset_identity_projection(terminal_assets)
            != _asset_identity_projection(remote_assets)
        ):
            raise S4ExecutionError("E_V250_S4_RELEASE_DRIFT")
        context["remote_assets"] = terminal_assets
        context["release_readback"] = {
            "release_id": terminal_release_value["id"],
            "url": terminal_release_value["html_url"],
            "state": "published",
            "draft": False,
            "prerelease": False,
        }

        metrics = _operation_metrics(journal)
        receipt: dict[str, Any] = {
            **_base_outcome(
                identity=identity,
                journal=journal,
                reconciliation={
                    "performed": False,
                    "trigger": "not_required",
                    "overall_state": "exact",
                    "entries": [],
                },
                control=release_control,
                context=context,
            ),
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "ok": True,
            "passed": True,
            "error_code": None,
            "failure_class": None,
            "execution_mode": (
                "executed_and_verified"
                if metrics["action_executed"]
                else "reconciled_existing"
            ),
        }
        return _finalize_receipt(receipt, validator)
    except Exception as raw:
        code = (
            raw.code
            if isinstance(raw, S4ExecutionError)
            else (
                "E_V250_S4_RUNTIME_OSERROR"
                if isinstance(raw, OSError)
                else "E_V250_S4_RUNTIME_EXCEPTION"
            )
        )
        reconciliation = _reconcile(journal, context)
        validator_error = (
            code
            if code
            in {
                "E_V250_S4_SCHEMA_VALIDATOR_UNAVAILABLE",
                "E_V250_S4_OUTCOME_SCHEMA_UNAVAILABLE",
            }
            else None
        )
        receipt = _failure_receipt(
            code=code,
            identity=identity,
            journal=journal,
            reconciliation=reconciliation,
            control=release_control,
            context=context,
            validator=validator,
            validator_error=validator_error,
        )
        error = S4ExecutionError(code, receipt=receipt)
        raise error from raw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-control-receipt", type=Path, required=True)
    parser.add_argument("--checkpoint-receipt", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--expected-workflow-run-id", required=True)
    parser.add_argument("--expected-workflow-run-attempt", required=True)
    return parser.parse_args()


def _read_control(path: Path) -> dict[str, object]:
    return _read_json_object(path, "E_V250_RELEASE_CONTROL_INPUT")


def main() -> int:
    args = parse_args()
    try:
        control = _read_control(args.release_control_receipt)
    except S4ExecutionError as exc:
        journal = OperationJournal()
        try:
            validator: OutcomeValidator | None = load_outcome_validator()
        except S4ExecutionError as validator_exc:
            validator = None
            validator_error = validator_exc.code
        else:
            validator_error = None
        receipt = _failure_receipt(
            code=exc.code,
            identity=_known_identity(args.version, args.commit, {}),
            journal=journal,
            reconciliation={
                "performed": True,
                "trigger": "exception",
                "overall_state": "not_required",
                "entries": [],
            },
            control={},
            context={},
            validator=validator,
            validator_error=validator_error,
        )
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 1
    try:
        receipt = execute_s4(
            version=args.version,
            commit=args.commit,
            release_control=control,
            release_root=args.release_root,
            checkpoint_receipt=args.checkpoint_receipt,
            receipt_root=args.receipt_root,
            expected_workflow_run_id=args.expected_workflow_run_id,
            expected_workflow_run_attempt=(
                args.expected_workflow_run_attempt
            ),
        )
    except S4ExecutionError as exc:
        print(json.dumps(exc.receipt, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
