#!/usr/bin/env python3
"""Deterministic Google OKF conformance primitives for Goal Teams V2.39.

The implementation intentionally uses only the Python standard library.  It
parses a small, documented YAML subset instead of constructing arbitrary YAML
objects, and it never edits the files it audits.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import stat
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote


POLICY_SCHEMA = "goal-teams-okf-conformance-policy-v1"
SCAN_REPORT_SCHEMA = "goal-teams-okf-scan-report-v1"
SCAN_MANIFEST_SCHEMA = "goal-teams-okf-scan-manifest-v1"
PACKAGE_MANIFEST_SCHEMA = "goal-teams-okf-conformance-manifest-v2.39"
DEFAULT_POLICY_PATH = "references/okf-conformance-policy.json"
DEFAULT_PACKAGE_MANIFEST_PATH = "references/okf-conformance-manifest.json"


class OkfError(ValueError):
    """A stable, safely reportable conformance error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        field: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.path = path
        self.field = field
        super().__init__(f"{code}: {message}")

    def finding(self, *, fallback_path: str | None = None) -> dict[str, Any]:
        value: dict[str, Any] = {
            "error_code": self.code,
            "message": self.message,
        }
        path = self.path or fallback_path
        if path:
            value["path"] = path
        if self.field:
            value["field"] = self.field
        return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _safe_relative(value: str) -> str:
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise OkfError("E_OKF_PATH_ESCAPE", "path must be a safe relative POSIX path")
    return pure.as_posix()


def _glob_matches(path: str, pattern: str) -> bool:
    """Case-sensitive matching with predictable root handling for ``**/``."""

    candidates = [pattern]
    if pattern.startswith("**/"):
        candidates.append(pattern[3:])
    return any(fnmatch.fnmatchcase(path, candidate) for candidate in candidates)


def _validate_policy(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OkfError("E_OKF_POLICY", "policy root must be an object")
    if payload.get("schema_version") != POLICY_SCHEMA:
        raise OkfError("E_OKF_POLICY", "unsupported policy schema_version")
    if payload.get("unknown_action", "fail") != "fail":
        raise OkfError("E_OKF_POLICY", "unknown_action must be fail")
    if payload.get("overlap_action", "fail") != "fail":
        raise OkfError("E_OKF_POLICY", "overlap_action must be fail")
    maximum = payload.get("max_document_bytes", 65536)
    if not isinstance(maximum, int) or maximum < 1024 or maximum > 4 * 1024 * 1024:
        raise OkfError("E_OKF_POLICY", "max_document_bytes is outside the safe range")
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        raise OkfError("E_OKF_POLICY", "policy rules must be a non-empty array")
    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise OkfError("E_OKF_POLICY", "every rule must be an object")
        rule_id = rule.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen:
            raise OkfError("E_OKF_POLICY", "rule_id must be non-empty and unique")
        seen.add(rule_id)
        if rule.get("class") not in {"A", "B", "C"}:
            raise OkfError("E_OKF_POLICY", f"invalid class in rule {rule_id}")
        globs = rule.get("globs")
        if not isinstance(globs, list) or not globs or not all(
            isinstance(value, str) and value for value in globs
        ):
            raise OkfError("E_OKF_POLICY", f"invalid globs in rule {rule_id}")
        excludes = rule.get("exclude_globs", [])
        if not isinstance(excludes, list) or not all(
            isinstance(value, str) and value for value in excludes
        ):
            raise OkfError("E_OKF_POLICY", f"invalid exclude_globs in rule {rule_id}")
    package = payload.get("package_manifest")
    if package is not None:
        if not isinstance(package, dict):
            raise OkfError("E_OKF_POLICY", "package_manifest must be an object")
        _safe_relative(str(package.get("path", "")))
        if package.get("schema_version") != PACKAGE_MANIFEST_SCHEMA:
            raise OkfError("E_OKF_POLICY", "package manifest schema is unsupported")
    return payload


def load_policy(root: str | Path) -> dict[str, Any]:
    """Load and hash the policy below ``root`` without accepting YAML."""

    base = Path(root).resolve()
    path = base / DEFAULT_POLICY_PATH
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OkfError("E_OKF_POLICY", "conformance policy is unavailable") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OkfError("E_OKF_POLICY", "conformance policy is not valid UTF-8 JSON") from exc
    policy = dict(_validate_policy(payload))
    policy["policy_sha256"] = _sha256_bytes(raw)
    # Internal-only provenance.  Reports strip underscore-prefixed values.
    policy["_policy_root"] = str(base)
    return policy


def classify_path(path: str | Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Return the unique A/B/C leaf classification for a relative path."""

    candidate = _safe_relative(str(path))
    matches: list[Mapping[str, Any]] = []
    for rule in policy.get("rules", []):
        includes = any(_glob_matches(candidate, value) for value in rule["globs"])
        excludes = any(
            _glob_matches(candidate, value) for value in rule.get("exclude_globs", [])
        )
        if includes and not excludes:
            matches.append(rule)
    if not matches:
        raise OkfError(
            "E_OKF_CLASS_UNKNOWN", f"no classification rule matched {candidate}", path=candidate
        )
    if len(matches) != 1:
        rule_ids = ",".join(sorted(str(value["rule_id"]) for value in matches))
        raise OkfError(
            "E_OKF_CLASS_OVERLAP",
            f"multiple classification rules matched {candidate}: {rule_ids}",
            path=candidate,
        )
    rule = matches[0]
    return {
        "class": rule["class"],
        "rule_id": rule["rule_id"],
        "contract_id": rule.get("contract_id", "unspecified"),
    }


_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_UNSAFE_YAML_RE = re.compile(
    r"(?:!!|!<|(?:^|[\s:\[,])&[A-Za-z0-9_-]+|(?:^|[\s:\[,])\*[A-Za-z0-9_-]+)",
    re.MULTILINE,
)


def _parse_quoted(value: str) -> str:
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "invalid quoted scalar") from exc
        if not isinstance(parsed, str):
            raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "quoted scalar must be text")
        return parsed
    if not value.endswith("'"):
        raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "invalid quoted scalar")
    return value[1:-1].replace("''", "'")


def _split_inline_list(value: str) -> list[str]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    result: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for char in inner:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote == '"':
            current.append(char)
            escaped = True
            continue
        if char in {'"', "'"}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            current.append(char)
            continue
        if char == "," and quote is None:
            result.append(str(_parse_scalar("".join(current).strip())))
            current = []
            continue
        current.append(char)
    if quote is not None:
        raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "unterminated inline list quote")
    result.append(str(_parse_scalar("".join(current).strip())))
    return result


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value.startswith(("|", ">", "{")):
        raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "complex YAML values are not supported")
    if value.startswith("["):
        if not value.endswith("]"):
            raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "invalid inline list")
        return _split_inline_list(value)
    if value.startswith(('"', "'")):
        return _parse_quoted(value)
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
        try:
            return int(value)
        except ValueError:
            pass
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)\.[0-9]+", value):
        try:
            return float(value)
        except ValueError:
            pass
    return value


def _parse_frontmatter(lines: Sequence[str]) -> dict[str, Any]:
    if any("\t" in line for line in lines):
        raise OkfError("E_OKF_FRONTMATTER_UNSAFE", "tabs are not allowed in frontmatter")
    joined = "\n".join(lines)
    if _UNSAFE_YAML_RE.search(joined):
        raise OkfError("E_OKF_FRONTMATTER_UNSAFE", "YAML tags, anchors and aliases are forbidden")
    if next((line for line in lines if line.strip() and not line.lstrip().startswith("#")), "").lstrip().startswith("-"):
        raise OkfError("E_OKF_FRONTMATTER_MAPPING", "frontmatter root must be a mapping")

    result: dict[str, Any] = {}
    pending_list: str | None = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - "):
            if pending_list is None:
                raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "orphan block list item")
            current = result[pending_list]
            if not isinstance(current, list):
                raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "invalid block list")
            current.append(_parse_scalar(line[4:]))
            continue
        if line.startswith((" ", "-")):
            raise OkfError("E_OKF_FRONTMATTER_UNSUPPORTED", "nested YAML is not supported")
        pending_list = None
        if ":" not in line:
            raise OkfError("E_OKF_FRONTMATTER_MAPPING", "mapping entry is missing a colon")
        key, raw_value = line.split(":", 1)
        if not _KEY_RE.fullmatch(key):
            raise OkfError("E_OKF_FRONTMATTER_MAPPING", "frontmatter key is invalid")
        if key in result:
            raise OkfError(
                "E_OKF_FRONTMATTER_DUPLICATE_KEY",
                f"duplicate frontmatter key: {key}",
                field=key,
            )
        if not raw_value.strip():
            result[key] = []
            pending_list = key
        else:
            result[key] = _parse_scalar(raw_value)
    return result


def parse_okf_document(path: str | Path, *, max_bytes: int = 65536) -> dict[str, Any]:
    """Safely parse the V2.39-supported OKF Markdown subset."""

    target = Path(path)
    if target.is_symlink():
        raise OkfError("E_OKF_PATH_SYMLINK", "symlinked documents are not accepted")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise OkfError("E_OKF_PATH", "document is unavailable") from exc
    if len(raw) > max_bytes:
        raise OkfError("E_OKF_FILE_SIZE", "document exceeds the policy size limit")
    if not (raw.startswith(b"---\n") or raw.startswith(b"---\r\n")):
        raise OkfError("E_OKF_FRONTMATTER_START", "frontmatter must start at byte zero")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OkfError("E_OKF_UTF8", "document is not valid UTF-8") from exc
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise OkfError("E_OKF_FRONTMATTER_END", "frontmatter closing marker is missing") from exc
    frontmatter_text = "\n".join(lines[1:closing])
    frontmatter = _parse_frontmatter(lines[1:closing])
    body = "\n".join(lines[closing + 1 :]).strip()
    value_type = frontmatter.get("type")
    if not isinstance(value_type, str) or not value_type.strip():
        raise OkfError("E_OKF_TYPE", "frontmatter type must be non-empty", field="type")
    if not body:
        raise OkfError("E_OKF_BODY_EMPTY", "document body must be non-empty")
    return {
        "frontmatter": frontmatter,
        "body": body,
        "artifact_sha256": _sha256_bytes(raw),
        "frontmatter_sha256": _sha256_bytes(frontmatter_text.encode("utf-8")),
    }


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise OkfError("E_OKF_PATH_ESCAPE", "document escapes the scan root") from exc
    return _safe_relative(relative.as_posix())


def _legacy_exemption(
    policy: Mapping[str, Any], path: str, artifact_sha256: str, missing: Sequence[str]
) -> bool:
    expected = set(missing)
    for item in policy.get("legacy_field_exemptions", []):
        if not isinstance(item, dict):
            continue
        if (
            item.get("path") == path
            and item.get("sha256") == artifact_sha256
            and set(item.get("missing_fields", [])) == expected
        ):
            return True
    return False


def _validate_a_fields(
    parsed: Mapping[str, Any], policy: Mapping[str, Any], relative: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    frontmatter = parsed["frontmatter"]
    required = list(policy.get("required_fields", ["type"]))
    enhanced = list(policy.get("enhanced_required_fields", []))
    missing: list[str] = []
    for field in required + enhanced:
        value = frontmatter.get(field)
        if value is None or (isinstance(value, str) and not value.strip()) or value == []:
            missing.append(field)
    enhanced_missing = [value for value in missing if value in enhanced]
    exempt = bool(enhanced_missing) and _legacy_exemption(
        policy, relative, str(parsed["artifact_sha256"]), enhanced_missing
    )
    for field in missing:
        if field in enhanced and exempt:
            continue
        findings.append(
            {
                "error_code": "E_OKF_FIELD_REQUIRED",
                "path": relative,
                "field": field,
                "message": f"required OKF field is missing: {field}",
            }
        )
    timestamp = frontmatter.get("timestamp")
    if timestamp is not None:
        try:
            datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            findings.append(
                {
                    "error_code": "E_OKF_FIELD_REQUIRED",
                    "path": relative,
                    "field": "timestamp",
                    "message": "timestamp must be ISO 8601",
                }
            )
    expected_okf = policy.get("okf_version")
    if expected_okf is not None and frontmatter.get("okf_version") not in {
        expected_okf,
        None if exempt and "okf_version" in enhanced_missing else object(),
    }:
        findings.append(
            {
                "error_code": "E_OKF_FIELD_REQUIRED",
                "path": relative,
                "field": "okf_version",
                "message": f"okf_version must be {expected_okf}",
            }
        )
    return findings


def _matched_completion_claims(
    frontmatter: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[tuple[str, str]]:
    claim_fields = policy.get("claim_fields", {})
    if not isinstance(claim_fields, dict):
        return []
    matches: list[tuple[str, str]] = []
    for field, accepted in claim_fields.items():
        value = frontmatter.get(field)
        normalized = value.casefold() if isinstance(value, str) else None
        if normalized is not None and normalized in {
            str(item).lower() for item in accepted if isinstance(item, str)
        }:
            matches.append((str(field), normalized))
    return matches


def _claim_is_complete(frontmatter: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    return bool(_matched_completion_claims(frontmatter, policy))


def _find_identity(registry: Any, expected: Mapping[str, str]) -> bool:
    if not isinstance(registry, dict) or not isinstance(registry.get("runs"), list):
        return False
    for value in registry["runs"]:
        if not isinstance(value, dict):
            continue
        if all(value.get(key) == item for key, item in expected.items()):
            return True
    return False


def validate_completion_claim(
    document: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate an identity-, hash- and Evidence-bound completion claim."""

    findings: list[dict[str, Any]] = []
    frontmatter = document.get("frontmatter")
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    path_value = str(document.get("path", ""))
    try:
        relative = _safe_relative(path_value)
    except OkfError as exc:
        return {"passed": False, "errors": [exc.finding()]}

    owner = {
        "agent_type": frontmatter.get("owner_agent_type"),
        "member_id": frontmatter.get("owner_member_id"),
        "agent_run_id": frontmatter.get("owner_agent_run_id"),
        "canonical_task_path": frontmatter.get("owner_canonical_task_path"),
    }
    validator = {
        "agent_type": frontmatter.get("validator_agent_type"),
        "member_id": frontmatter.get("validator_member_id"),
        "agent_run_id": frontmatter.get("validator_agent_run_id"),
        "canonical_task_path": frontmatter.get("validator_canonical_task_path"),
    }
    if (
        not all(isinstance(value, str) and value for value in owner.values())
        or not all(isinstance(value, str) and value for value in validator.values())
        or owner["agent_run_id"] == validator["agent_run_id"]
        or (owner["agent_type"], owner["member_id"], owner["agent_run_id"])
        == (validator["agent_type"], validator["member_id"], validator["agent_run_id"])
    ):
        findings.append(
            {
                "error_code": "E_OKF_OWNER_VALIDATOR",
                "path": relative,
                "message": "Owner and Validator must be complete, independent identities",
            }
        )

    registry = context.get("identity_registry")
    if not _find_identity(registry, owner) or not _find_identity(registry, validator):
        findings.append(
            {
                "error_code": "E_OKF_IDENTITY",
                "path": relative,
                "message": "Owner or Validator is not bound in the identity registry",
            }
        )

    root = Path(context.get("root", ".")).resolve()
    artifact = root / relative
    declared_hash = document.get("artifact_sha256")
    current_hash: str | None = None
    if artifact.is_file() and not artifact.is_symlink():
        current_hash = _sha256_file(artifact)
    if not isinstance(declared_hash, str) or current_hash != declared_hash:
        findings.append(
            {
                "error_code": "E_OKF_ARTIFACT_HASH_STALE",
                "path": relative,
                "message": "completion claim is not bound to the current artifact hash",
            }
        )

    evidence_values = context.get("evidence_records", [])
    evidence_match: Mapping[str, Any] | None = None
    if isinstance(evidence_values, list):
        for evidence in evidence_values:
            if not isinstance(evidence, dict):
                continue
            if (
                evidence.get("artifact_ref") == relative
                and evidence.get("artifact_sha256") == declared_hash
                and evidence.get("validator_agent_run_id")
                == validator.get("agent_run_id")
                and evidence.get("check_state") in {"passed", "accepted"}
            ):
                evidence_match = evidence
                break
    machine_trust = {"local_verified", "external_verified"}
    if evidence_match is None or evidence_match.get("trust_level") not in machine_trust:
        findings.append(
            {
                "error_code": "E_OKF_EVIDENCE",
                "path": relative,
                "message": "current external machine-verifiable Evidence is required",
            }
        )

    policy = context.get("policy")
    if not isinstance(policy, Mapping):
        # Direct API callers may omit the scan policy; keep the public
        # completion gate closed for every canonical alias.
        fields = (
            "audit_state",
            "run_outcome",
            "validation_state",
            "status",
            "review_state",
            "semantic_review_state",
            "check_state",
        )
        policy = {
            "claim_fields": {
                field: (
                    ["accepted", "achieved", "complete", "completed"]
                    if field == "status"
                    else ["accepted", "achieved"]
                )
                for field in fields
            }
        }
    claim_values = {
        value for _field, value in _matched_completion_claims(frontmatter, policy)
    }
    if claim_values.intersection({"accepted", "achieved", "complete", "completed"}):
        audit = context.get("completion_audit")
        if not isinstance(audit, dict) or not (
            audit.get("audit_state") in {"passed", "accepted"}
            and audit.get("validator_agent_run_id") == validator.get("agent_run_id")
            and audit.get("artifact_ref") == relative
            and audit.get("artifact_sha256") == declared_hash
        ):
            findings.append(
                {
                    "error_code": "E_OKF_COMPLETION_AUDIT",
                    "path": relative,
                    "message": "accepted/achieved/complete claims require a current completion audit",
                }
            )
    return {"passed": not findings, "errors": findings}


_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _validate_links(
    path: Path,
    relative: str,
    parsed: Mapping[str, Any],
    root: Path,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    candidates: list[tuple[str, str]] = []
    source = parsed["frontmatter"].get("source_ssot")
    if isinstance(source, str) and source.strip():
        candidates.append(("E_OKF_SOURCE_SSOT", source.strip()))
    for match in _MARKDOWN_LINK_RE.finditer(str(parsed["body"])):
        candidates.append(("E_OKF_LINK", match.group(1).strip()))
    for error_code, raw_target in candidates:
        target = raw_target.split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target = unquote(target.split("#", 1)[0])
        if not target:
            continue
        options = [root / target.lstrip("/"), path.parent / target]
        resolved = None
        for option in options:
            try:
                option.resolve(strict=False).relative_to(root.resolve())
            except ValueError:
                continue
            if option.exists():
                resolved = option
                break
        if resolved is None:
            findings.append(
                {
                    "error_code": error_code,
                    "path": relative,
                    "message": "local document reference does not resolve",
                }
            )
    return findings


def scan_paths(
    paths: Iterable[str | Path],
    policy: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify and validate explicit paths under a declared root."""

    root = Path(context.get("root", ".")).resolve()
    mode = str(context.get("mode", "explicit"))
    maximum = int(policy.get("max_document_bytes", 65536))
    files: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for item in sorted((Path(value) for value in paths), key=lambda value: value.as_posix()):
        try:
            relative = _relative_to_root(item, root)
        except OkfError as exc:
            findings.append(exc.finding())
            continue
        if item.is_symlink():
            findings.append(
                {
                    "error_code": "E_OKF_PATH_SYMLINK",
                    "path": relative,
                    "message": "symlinked scan inputs are forbidden",
                }
            )
            continue
        if not item.is_file():
            findings.append(
                {
                    "error_code": "E_OKF_PATH",
                    "path": relative,
                    "message": "scan input is not a regular file",
                }
            )
            continue
        try:
            classification = classify_path(relative, policy)
        except OkfError as exc:
            findings.append(exc.finding(fallback_path=relative))
            continue
        entry = {
            "path": relative,
            **classification,
            "sha256": _sha256_file(item),
        }
        files.append(entry)
        if classification["class"] != "A":
            continue
        try:
            parsed = parse_okf_document(item, max_bytes=maximum)
        except OkfError as exc:
            finding = exc.finding(fallback_path=relative)
            finding.update(
                {"rule_id": classification["rule_id"], "class": classification["class"]}
            )
            findings.append(finding)
            continue
        field_findings = _validate_a_fields(parsed, policy, relative)
        for finding in field_findings:
            finding.update(
                {"rule_id": classification["rule_id"], "class": classification["class"]}
            )
        findings.extend(field_findings)
        if context.get("validate_links"):
            findings.extend(_validate_links(item, relative, parsed, root))
        if _claim_is_complete(parsed["frontmatter"], policy):
            claim_context = dict(context)
            claim_context["root"] = root
            claim_context["policy"] = policy
            claim_result = validate_completion_claim(
                {
                    "path": relative,
                    "frontmatter": parsed["frontmatter"],
                    "artifact_sha256": parsed["artifact_sha256"],
                },
                claim_context,
            )
            findings.extend(claim_result["errors"])
    return {
        "schema_version": SCAN_REPORT_SCHEMA,
        "mode": mode,
        "policy_sha256": policy.get("policy_sha256"),
        "passed": not findings,
        "files": files,
        "findings": findings,
        "errors": findings,
        "summary": {
            "file_count": len(files),
            "a_count": sum(value["class"] == "A" for value in files),
            "b_count": sum(value["class"] == "B" for value in files),
            "c_count": sum(value["class"] == "C" for value in files),
            "finding_count": len(findings),
        },
    }


def _timeline_is_ordered(body: str) -> bool:
    values: list[datetime] = []
    for match in re.finditer(
        r"\b(20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2}))\b",
        body,
    ):
        try:
            values.append(datetime.fromisoformat(match.group(1).replace("Z", "+00:00")))
        except ValueError:
            return False
    return all(left <= right for left, right in zip(values, values[1:]))


def scan_bundle(bundle_root: str | Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an explicit ignored or tracked OKF bundle recursively."""

    root = Path(bundle_root)
    findings: list[dict[str, Any]] = []
    if root.is_symlink() or not root.is_dir():
        finding = {
            "error_code": "E_OKF_PATH_SYMLINK" if root.is_symlink() else "E_OKF_PATH",
            "path": ".",
            "message": "bundle root must be a real directory",
        }
        return {
            "schema_version": SCAN_REPORT_SCHEMA,
            "mode": "bundle-root",
            "policy_sha256": policy.get("policy_sha256"),
            "passed": False,
            "files": [],
            "findings": [finding],
            "errors": [finding],
            "bundle": {},
        }
    root = root.resolve()
    names = [path.name for path in root.iterdir()]
    lowercase_index = root / "index.md"
    if not lowercase_index.is_file() or any(name == "INDEX.md" for name in names):
        findings.append(
            {
                "error_code": "E_OKF_BUNDLE_INDEX",
                "path": "index.md",
                "message": "bundle requires lowercase index.md and forbids INDEX.md",
            }
        )
    lower_names: dict[str, list[str]] = {}
    for path in root.rglob("*.md"):
        relative = path.relative_to(root).as_posix()
        lower_names.setdefault(relative.lower(), []).append(relative)
    for values in lower_names.values():
        if len(values) > 1:
            findings.append(
                {
                    "error_code": "E_OKF_BUNDLE_INDEX",
                    "path": sorted(values)[0],
                    "message": "case-colliding Markdown paths are forbidden",
                }
            )
    memory = root / "memory.md"
    memory_author = None
    timeline_order = None
    if not memory.is_file():
        findings.append(
            {
                "error_code": "E_OKF_BUNDLE_MEMORY",
                "path": "memory.md",
                "message": "bundle requires memory.md",
            }
        )
    else:
        try:
            parsed_memory = parse_okf_document(
                memory, max_bytes=int(policy.get("max_document_bytes", 65536))
            )
            memory_author = parsed_memory["frontmatter"].get("author")
            timeline_order = parsed_memory["frontmatter"].get("timeline_order")
            if (
                memory_author != "GoalTeams"
                or timeline_order != "old_to_new"
                or not _timeline_is_ordered(parsed_memory["body"])
            ):
                raise OkfError("E_OKF_BUNDLE_MEMORY", "memory timeline contract is invalid")
        except OkfError as exc:
            findings.append(exc.finding(fallback_path="memory.md"))

    markdown = [path for path in root.rglob("*.md")]
    report = scan_paths(
        markdown,
        policy,
        {"root": root, "mode": "bundle-root", "validate_links": True},
    )
    findings.extend(report["findings"])
    report["findings"] = findings
    report["errors"] = findings
    report["passed"] = not findings
    report["summary"]["finding_count"] = len(findings)
    report["bundle"] = {
        "index_path": "index.md" if lowercase_index.is_file() else None,
        "memory_path": "memory.md" if memory.is_file() else None,
        "memory_author": memory_author,
        "timeline_order": timeline_order,
    }
    return report


def _forbidden_roots(policy: Mapping[str, Any]) -> list[str]:
    values = policy.get(
        "forbidden_package_roots", ["docs", "develops", "GoalTeamsWork-*"]
    )
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise OkfError("E_OKF_POLICY", "forbidden_package_roots must be strings")
    return list(values)


def _is_forbidden_path(relative: str, policy: Mapping[str, Any]) -> bool:
    first = PurePosixPath(relative).parts[0] if PurePosixPath(relative).parts else ""
    return any(fnmatch.fnmatchcase(first, pattern) for pattern in _forbidden_roots(policy))


def _load_package_allowlist(root: Path) -> list[tuple[str, str]] | None:
    path = root / "scripts" / "install" / "package-manifest.txt"
    if not path.is_file():
        return None
    rules: list[tuple[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise OkfError("E_OKF_MANIFEST_SOURCE_BINDING", "package allowlist is unreadable") from exc
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        parts = value.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in {"file", "prefix", "generated"}:
            raise OkfError("E_OKF_MANIFEST_SOURCE_BINDING", "package allowlist entry is invalid")
        kind, raw_relative = parts
        if (kind == "prefix") != raw_relative.endswith("/"):
            raise OkfError(
                "E_OKF_MANIFEST_SOURCE_BINDING",
                "package prefix entries must end with slash and file/generated entries must not",
            )
        relative = _safe_relative(raw_relative.rstrip("/"))
        rules.append((parts[0], relative))
    return rules


def _allowlisted(relative: str, rules: list[tuple[str, str]] | None) -> bool:
    if rules is None:
        return True
    for kind, value in rules:
        if kind == "file" and relative == value:
            return True
        if kind == "prefix" and (relative == value or relative.startswith(value + "/")):
            return True
    return False


def _payload_paths(root: Path, policy: Mapping[str, Any]) -> list[Path]:
    rules = _load_package_allowlist(root)
    values: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        parts = PurePosixPath(relative).parts
        if (
            relative == DEFAULT_PACKAGE_MANIFEST_PATH
            or not parts
            or ".git" in parts
            or "__pycache__" in parts
            or path.name in {".DS_Store"}
            or (len(parts) >= 2 and parts[:2] == ("release", "versions"))
            or _is_forbidden_path(relative, policy)
            or not _allowlisted(relative, rules)
        ):
            continue
        values.append(path)
    return sorted(values, key=lambda value: value.relative_to(root).as_posix())


def _complete_package_paths(root: Path) -> list[Path]:
    """Enumerate every non-directory package entry except the manifest itself.

    Source preview intentionally projects the installer allowlist.  A frozen
    release or installed package, however, must prove that no additional file,
    symlink, or special entry exists outside that projection.
    """

    values: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative == DEFAULT_PACKAGE_MANIFEST_PATH:
            continue
        try:
            mode = path.lstat().st_mode
        except OSError:
            values.append(path)
            continue
        if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
            continue
        values.append(path)
    return sorted(values, key=lambda value: value.relative_to(root).as_posix())


def _forbidden_payload_paths(root: Path, policy: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if _is_forbidden_path(relative, policy):
            values.append(relative)
    return sorted(values)


def _payload_entry(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    if path.is_symlink():
        raise OkfError(
            "E_OKF_PACKAGE_FORBIDDEN_PATH",
            "symlinked package entries are forbidden",
            path=relative,
        )
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise OkfError(
            "E_OKF_PACKAGE_FORBIDDEN_PATH",
            "package entries must be regular files",
            path=relative,
        )
    return {
        "path": relative,
        "type": "regular_file",
        "mode": format(stat.S_IMODE(info.st_mode), "04o"),
        "size": info.st_size,
        "sha256": _sha256_file(path),
    }


def _payload_tree_digest(entries: Sequence[Mapping[str, Any]]) -> str:
    normalized = [
        {
            "path": value.get("path"),
            "type": value.get("type"),
            "mode": value.get("mode"),
            "size": value.get("size"),
            "sha256": value.get("sha256"),
        }
        for value in sorted(entries, key=lambda item: str(item.get("path", "")))
    ]
    return _sha256_bytes(
        b"goal-teams-package-payload-tree-v1\0" + _canonical_json(normalized)
    )


def _payload_paths_digest(entries: Sequence[Mapping[str, Any]]) -> str:
    paths = [str(value.get("path")) for value in sorted(entries, key=lambda item: str(item.get("path", "")))]
    return _sha256_bytes(
        b"goal-teams-package-payload-paths-v1\0" + "\n".join(paths).encode("utf-8")
    )


def _git_binding(root: Path, expression: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", expression],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "unavailable"


def build_package_manifest(
    root: str | Path,
    policy: Mapping[str, Any],
    source_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Revision 2 package-bound conformance manifest in memory."""

    base = Path(root).resolve()
    paths = _payload_paths(base, policy)
    payload_entries = [_payload_entry(path, base) for path in paths]
    markdown_paths = [path for path in paths if path.suffix == ".md"]
    report = scan_paths(markdown_paths, policy, {"root": base, "mode": "package-preview"})
    if not report["passed"]:
        raise OkfError("E_OKF_PACKAGE_TREE", "package Markdown has conformance findings")
    by_path = {value["path"]: value for value in report["files"]}
    markdown_entries = [
        {
            "path": entry["path"],
            "class": by_path[entry["path"]]["class"],
            "rule_id": by_path[entry["path"]]["rule_id"],
            "contract_id": by_path[entry["path"]]["contract_id"],
            "size": entry["size"],
            "sha256": entry["sha256"],
        }
        for entry in payload_entries
        if entry["path"].endswith(".md")
    ]
    source = dict(source_binding or {})
    package_allowlist = base / "scripts" / "install" / "package-manifest.txt"
    source.setdefault("commit_sha256", _git_binding(base, "HEAD"))
    source.setdefault("git_tree_id", _git_binding(base, "HEAD^{tree}"))
    source.setdefault(
        "package_manifest_sha256",
        _sha256_file(package_allowlist) if package_allowlist.is_file() else "unavailable",
    )
    policy_path = base / DEFAULT_POLICY_PATH
    checker_paths = [
        "scripts/v23/okf_conformance.py",
        "scripts/checks/check-okf.py",
    ]
    checkers: list[dict[str, Any]] = []
    for relative in checker_paths:
        path = base / relative
        if not path.is_file() or path.is_symlink():
            raise OkfError("E_OKF_PACKAGE_MISSING", "required OKF checker is missing", path=relative)
        checkers.append({"path": relative, "sha256": _sha256_file(path)})
    version_path = base / "VERSION"
    product_version = (
        version_path.read_text(encoding="utf-8").strip()
        if version_path.is_file()
        else "V2.39"
    )
    manifest_scope = (
        "installed_package_complete" if source_binding is not None else "source_preview_unfrozen"
    )
    return {
        "schema_version": PACKAGE_MANIFEST_SCHEMA,
        "canonicalization": "utf8-lf-json-sort-keys-compact-v1",
        "product_version": product_version,
        "manifest_scope": manifest_scope,
        "source": {
            "commit_sha256": source.get("commit_sha256", "unavailable"),
            "git_tree_id": source.get("git_tree_id", "unavailable"),
            "package_manifest_sha256": source.get(
                "package_manifest_sha256", "unavailable"
            ),
        },
        "package": {
            "payload_tree_sha256": _payload_tree_digest(payload_entries),
            "payload_file_count": len(payload_entries),
            "payload_paths_sha256": _payload_paths_digest(payload_entries),
            "tree_digest_algorithm": "goal-teams-package-payload-tree-v1",
            "tree_digest_excludes": [DEFAULT_PACKAGE_MANIFEST_PATH],
            "full_tree_binding": "release_or_install_identity_receipt",
            "payload_entries": payload_entries,
        },
        "policy": {"path": DEFAULT_POLICY_PATH, "sha256": _sha256_file(policy_path)},
        "checkers": checkers,
        "markdown_entries": markdown_entries,
        "forbidden_roots": _forbidden_roots(policy),
        "generation": {
            "builder_id": "goal-teams-release-builder",
            "builder_version": "V2.39",
        },
    }


def validate_manifest(
    root: str | Path,
    policy: Mapping[str, Any],
    manifest_path: str | Path,
    *,
    require_complete_package: bool = False,
) -> dict[str, Any]:
    base = Path(root).resolve()
    target = Path(manifest_path)
    if not target.is_absolute():
        target = base / target
    if require_complete_package:
        try:
            mode = target.lstat().st_mode
            target.resolve(strict=True).relative_to(base)
            valid_target = stat.S_ISREG(mode) and not stat.S_ISLNK(mode)
        except (OSError, RuntimeError, ValueError):
            valid_target = False
        if not valid_target:
            finding = {
                "error_code": "E_OKF_PACKAGE_FORBIDDEN_PATH",
                "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                "message": "canonical package manifest must be a regular in-tree file",
            }
            return {
                "schema_version": SCAN_REPORT_SCHEMA,
                "mode": "manifest",
                "passed": False,
                "package_completeness_state": "failed",
                "files": [],
                "findings": [finding],
                "errors": [finding],
                "policy_sha256": policy.get("policy_sha256"),
            }
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        finding = {
            "error_code": "E_OKF_MANIFEST_SCHEMA",
            "path": target.name,
            "message": "manifest is unavailable or invalid",
        }
        return {
            "schema_version": SCAN_REPORT_SCHEMA,
            "mode": "manifest",
            "passed": False,
            "files": [],
            "findings": [finding],
            "errors": [finding],
            "policy_sha256": policy.get("policy_sha256"),
        }
    if not isinstance(payload, dict) or payload.get("schema_version") not in {
        SCAN_MANIFEST_SCHEMA,
        PACKAGE_MANIFEST_SCHEMA,
    }:
        finding = {
            "error_code": "E_OKF_MANIFEST_SCHEMA",
            "path": target.name,
            "message": "manifest schema is unsupported",
        }
        return {
            "schema_version": SCAN_REPORT_SCHEMA,
            "mode": "manifest",
            "passed": False,
            "files": [],
            "findings": [finding],
            "errors": [finding],
            "policy_sha256": policy.get("policy_sha256"),
        }
    findings: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    is_package = payload.get("schema_version") == PACKAGE_MANIFEST_SCHEMA
    if require_complete_package and not is_package:
        findings.append(
            {
                "error_code": "E_OKF_MANIFEST_SCHEMA",
                "path": target.name,
                "message": "package-tree requires the V2.39 canonical manifest schema",
            }
        )

    if is_package:
        if require_complete_package:
            source_binding = payload.get("source")
            package_binding = payload.get("package")
            policy_binding = payload.get("policy")
            checker_values = payload.get("checkers")
            markdown_values = payload.get("markdown_entries")
            generation = payload.get("generation")
            expected_top_fields = {
                "schema_version",
                "canonicalization",
                "product_version",
                "manifest_scope",
                "source",
                "package",
                "policy",
                "checkers",
                "markdown_entries",
                "forbidden_roots",
                "generation",
            }
            closed_schema_valid = (
                set(payload) == expected_top_fields
                and payload.get("canonicalization")
                == "utf8-lf-json-sort-keys-compact-v1"
                and isinstance(source_binding, dict)
                and set(source_binding)
                == {"commit_sha256", "git_tree_id", "package_manifest_sha256"}
                and isinstance(package_binding, dict)
                and set(package_binding)
                == {
                    "payload_tree_sha256",
                    "payload_file_count",
                    "payload_paths_sha256",
                    "tree_digest_algorithm",
                    "tree_digest_excludes",
                    "full_tree_binding",
                    "payload_entries",
                }
                and package_binding.get("full_tree_binding")
                == "release_or_install_identity_receipt"
                and isinstance(policy_binding, dict)
                and set(policy_binding) == {"path", "sha256"}
                and isinstance(checker_values, list)
                and all(
                    isinstance(value, dict)
                    and set(value) == {"path", "sha256"}
                    for value in checker_values
                )
                and isinstance(markdown_values, list)
                and all(
                    isinstance(value, dict)
                    and set(value)
                    == {"path", "class", "rule_id", "contract_id", "size", "sha256"}
                    for value in markdown_values
                )
                and generation
                == {
                    "builder_id": "goal-teams-release-builder",
                    "builder_version": "V2.39",
                }
            )
            if not closed_schema_valid:
                findings.append(
                    {
                        "error_code": "E_OKF_MANIFEST_SCHEMA",
                        "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                        "message": "canonical package manifest is not a closed V2.39 object",
                    }
                )
            current_allowlist = base / "scripts" / "install" / "package-manifest.txt"
            current_version = base / "VERSION"
            source_binding_valid = isinstance(source_binding, dict)
            if source_binding_valid:
                commit = source_binding.get("commit_sha256")
                tree_id = source_binding.get("git_tree_id")
                manifest_hash = source_binding.get("package_manifest_sha256")
                source_binding_valid = bool(
                    isinstance(commit, str)
                    and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit)
                    and isinstance(tree_id, str)
                    and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree_id)
                    and isinstance(manifest_hash, str)
                    and re.fullmatch(r"[0-9a-f]{64}", manifest_hash)
                    and current_allowlist.is_file()
                    and not current_allowlist.is_symlink()
                    and manifest_hash == _sha256_file(current_allowlist)
                )
            if (
                not source_binding_valid
                or payload.get("manifest_scope") != "installed_package_complete"
                or not current_version.is_file()
                or current_version.is_symlink()
                or payload.get("product_version")
                != current_version.read_text(encoding="utf-8").strip()
                or payload.get("generation")
                != {
                    "builder_id": "goal-teams-release-builder",
                    "builder_version": "V2.39",
                }
            ):
                findings.append(
                    {
                        "error_code": "E_OKF_MANIFEST_SOURCE_BINDING",
                        "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                        "message": "canonical manifest source, scope, version or builder binding is invalid",
                    }
                )
        policy_binding = payload.get("policy")
        if not isinstance(policy_binding, dict) or (
            policy_binding.get("path") != DEFAULT_POLICY_PATH
            or policy_binding.get("sha256") != policy.get("policy_sha256")
        ):
            findings.append(
                {
                    "error_code": "E_OKF_PACKAGE_POLICY_DRIFT",
                    "path": DEFAULT_POLICY_PATH,
                    "message": "manifest policy binding differs from the package policy",
                }
            )
        checker_values = payload.get("checkers")
        checker_map = {
            value.get("path"): value
            for value in checker_values
            if isinstance(value, dict) and isinstance(value.get("path"), str)
        } if isinstance(checker_values, list) else {}
        for relative in (
            "scripts/v23/okf_conformance.py",
            "scripts/checks/check-okf.py",
        ):
            path = base / relative
            value = checker_map.get(relative)
            if (
                not path.is_file()
                or path.is_symlink()
                or not isinstance(value, dict)
                or value.get("sha256") != _sha256_file(path)
            ):
                findings.append(
                    {
                        "error_code": "E_OKF_PACKAGE_CHECKER_DRIFT",
                        "path": relative,
                        "message": "manifest checker binding differs from the package checker",
                    }
                )
        if require_complete_package and (
            len(checker_map) != 2 or len(checker_values or []) != 2
        ):
            findings.append(
                {
                    "error_code": "E_OKF_MANIFEST_SCHEMA",
                    "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                    "message": "canonical checker bindings must be unique and complete",
                }
            )
        entries = payload.get("markdown_entries")
    else:
        if payload.get("policy_sha256") != policy.get("policy_sha256"):
            findings.append(
                {
                    "error_code": "E_OKF_PACKAGE_POLICY_DRIFT",
                    "path": target.name,
                    "message": "manifest policy hash does not match the current policy",
                }
            )
        entries = payload.get("files")

    if not isinstance(entries, list):
        entries = []
        findings.append(
            {
                "error_code": "E_OKF_MANIFEST_SCHEMA",
                "path": target.name,
                "message": "manifest Markdown entries must be an array",
            }
        )
    seen: set[str] = set()
    for value in entries:
        if not isinstance(value, dict):
            findings.append(
                {
                    "error_code": "E_OKF_MANIFEST_SCHEMA",
                    "path": target.name,
                    "message": "manifest Markdown entry must be an object",
                }
            )
            continue
        try:
            relative = _safe_relative(str(value.get("path", "")))
        except OkfError as exc:
            findings.append(exc.finding(fallback_path=target.name))
            continue
        if relative in seen:
            findings.append(
                {
                    "error_code": "E_OKF_MANIFEST_SCHEMA",
                    "path": relative,
                    "message": "manifest contains a duplicate Markdown path",
                }
            )
            continue
        seen.add(relative)
        path = base / relative
        if not path.is_file() or path.is_symlink():
            findings.append(
                {
                    "error_code": "E_OKF_ARTIFACT_HASH_STALE",
                    "path": relative,
                    "message": "manifest Markdown artifact is missing",
                }
            )
            continue
        current_hash = _sha256_file(path)
        if current_hash != value.get("sha256") or path.stat().st_size != value.get(
            "size", path.stat().st_size
        ):
            findings.append(
                {
                    "error_code": "E_OKF_ARTIFACT_HASH_STALE",
                    "path": relative,
                    "message": "manifest Markdown artifact hash is stale",
                }
            )
        try:
            classification = classify_path(relative, policy)
            if (
                classification["class"] != value.get("class")
                or classification["rule_id"] != value.get("rule_id")
                or classification["contract_id"] != value.get("contract_id")
            ):
                findings.append(
                    {
                        "error_code": "E_OKF_MANIFEST_CLASS_STALE",
                        "path": relative,
                        "message": "manifest classification is stale",
                    }
                )
        except OkfError as exc:
            findings.append(exc.finding(fallback_path=relative))
            classification = {
                "class": value.get("class"),
                "rule_id": value.get("rule_id"),
                "contract_id": value.get("contract_id", "unspecified"),
            }
        files.append({"path": relative, **classification, "sha256": current_hash})

    completeness = "unavailable"
    package_data = payload.get("package") if is_package else None
    payload_entries = (
        package_data.get("payload_entries") if isinstance(package_data, dict) else None
    )
    if require_complete_package:
        canonical = base / DEFAULT_PACKAGE_MANIFEST_PATH
        if target.resolve() != canonical.resolve():
            findings.append(
                {
                    "error_code": "E_OKF_MANIFEST_SCHEMA",
                    "path": target.name,
                    "message": "package-tree only accepts the canonical manifest path",
                }
            )
        for relative in _forbidden_payload_paths(base, policy):
            findings.append(
                {
                    "error_code": "E_OKF_PACKAGE_FORBIDDEN_PATH",
                    "path": relative,
                    "message": "local-only path is forbidden in an installed package",
                }
            )
        if not isinstance(payload_entries, list):
            payload_entries = []
            findings.append(
                {
                    "error_code": "E_OKF_MANIFEST_SCHEMA",
                    "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                    "message": "canonical package manifest requires payload_entries",
                }
            )
        declared: dict[str, Mapping[str, Any]] = {}
        for value in payload_entries:
            if not isinstance(value, dict):
                findings.append(
                    {
                        "error_code": "E_OKF_MANIFEST_SCHEMA",
                        "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                        "message": "payload entry must be an object",
                    }
                )
                continue
            if set(value) != {"path", "type", "mode", "size", "sha256"}:
                findings.append(
                    {
                        "error_code": "E_OKF_MANIFEST_SCHEMA",
                        "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                        "message": "payload entry is not a closed object",
                    }
                )
                continue
            try:
                relative = _safe_relative(str(value.get("path", "")))
            except OkfError as exc:
                findings.append(exc.finding(fallback_path=DEFAULT_PACKAGE_MANIFEST_PATH))
                continue
            if relative == DEFAULT_PACKAGE_MANIFEST_PATH or relative in declared:
                findings.append(
                    {
                        "error_code": "E_OKF_MANIFEST_SCHEMA",
                        "path": relative,
                        "message": "payload entry is self-referential or duplicated",
                    }
                )
                continue
            declared[relative] = value
        actual_paths = _complete_package_paths(base)
        actual = {path.relative_to(base).as_posix(): path for path in actual_paths}
        for relative, path in sorted(actual.items()):
            try:
                mode = path.lstat().st_mode
            except OSError:
                mode = 0
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                findings.append(
                    {
                        "error_code": "E_OKF_PACKAGE_FORBIDDEN_PATH",
                        "path": relative,
                        "message": "package entries must be regular files",
                    }
                )
        for relative in sorted(set(declared) - set(actual)):
            findings.append(
                {
                    "error_code": "E_OKF_PACKAGE_MISSING",
                    "path": relative,
                    "message": "declared package entry is missing",
                }
            )
        for relative in sorted(set(actual) - set(declared)):
            findings.append(
                {
                    "error_code": "E_OKF_PACKAGE_EXTRA",
                    "path": relative,
                    "message": "package contains an undeclared entry",
                }
            )
        for relative in sorted(set(actual) & set(declared)):
            try:
                current = _payload_entry(actual[relative], base)
            except OkfError as exc:
                findings.append(exc.finding(fallback_path=relative))
                continue
            expected = declared[relative]
            if any(
                current.get(field) != expected.get(field)
                for field in ("type", "mode", "size", "sha256")
            ):
                findings.append(
                    {
                        "error_code": "E_OKF_PACKAGE_HASH_DRIFT",
                        "path": relative,
                        "message": "package entry type, mode, size or hash drifted",
                    }
                )
        if isinstance(package_data, dict) and isinstance(payload_entries, list):
            if (
                package_data.get("payload_file_count") != len(payload_entries)
                or package_data.get("payload_tree_sha256")
                != _payload_tree_digest(payload_entries)
                or package_data.get("payload_paths_sha256")
                != _payload_paths_digest(payload_entries)
                or package_data.get("tree_digest_algorithm")
                != "goal-teams-package-payload-tree-v1"
                or package_data.get("tree_digest_excludes")
                != [DEFAULT_PACKAGE_MANIFEST_PATH]
                or package_data.get("full_tree_binding")
                != "release_or_install_identity_receipt"
            ):
                findings.append(
                    {
                        "error_code": "E_OKF_PACKAGE_HASH_DRIFT",
                        "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                        "message": "package payload tree binding is stale",
                    }
                )
        declared_markdown = {
            value.get("path") for value in entries if isinstance(value, dict)
        }
        payload_markdown = {
            value.get("path")
            for value in payload_entries
            if isinstance(value, dict) and str(value.get("path", "")).endswith(".md")
        }
        if declared_markdown != payload_markdown:
            findings.append(
                {
                    "error_code": "E_OKF_MANIFEST_SCHEMA",
                    "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                    "message": "markdown_entries do not cover every package Markdown file",
                }
            )
        expected_forbidden = _forbidden_roots(policy)
        if payload.get("forbidden_roots") != expected_forbidden:
            findings.append(
                {
                    "error_code": "E_OKF_MANIFEST_SCHEMA",
                    "path": DEFAULT_PACKAGE_MANIFEST_PATH,
                    "message": "forbidden_roots differ from policy",
                }
            )
        completeness = "complete" if not findings else "failed"
    return {
        "schema_version": SCAN_REPORT_SCHEMA,
        "mode": "manifest",
        "policy_sha256": policy.get("policy_sha256"),
        "passed": not findings,
        "package_completeness_state": completeness,
        "files": files,
        "findings": findings,
        "errors": findings,
        "manifest": {
            "schema_version": payload.get("schema_version"),
            "package_tree_sha256": package_data.get("payload_tree_sha256")
            if isinstance(package_data, dict)
            else None,
            "file_count": len(entries),
        },
    }


def discover_tracked(root: str | Path) -> list[Path]:
    base = Path(root).resolve()
    proc = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        cwd=base,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise OkfError("E_OKF_GIT_REQUIRED", "tracked mode requires a Git worktree")
    return [base / value for value in proc.stdout.splitlines() if value]


def discover_changed(root: str | Path) -> tuple[list[Path], list[str]]:
    base = Path(root).resolve()
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=base,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        raise OkfError("E_OKF_GIT_REQUIRED", "changed mode requires a Git worktree")

    active: set[str] = set()
    deleted: set[str] = set()
    for args in (
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "--", "*.md"],
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB", "--", "*.md"],
        ["git", "ls-files", "--others", "--exclude-standard", "--", "*.md"],
    ):
        proc = subprocess.run(args, cwd=base, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            raise OkfError("E_OKF_GIT_REQUIRED", "Git discovery failed")
        active.update(value for value in proc.stdout.splitlines() if value)
    for args in (
        ["git", "diff", "--name-only", "--diff-filter=D", "--", "*.md"],
        ["git", "diff", "--cached", "--name-only", "--diff-filter=D", "--", "*.md"],
    ):
        proc = subprocess.run(args, cwd=base, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            raise OkfError("E_OKF_GIT_REQUIRED", "Git discovery failed")
        deleted.update(value for value in proc.stdout.splitlines() if value)
    active.difference_update(deleted)
    return [base / value for value in sorted(active)], sorted(deleted)


__all__ = [
    "OkfError",
    "build_package_manifest",
    "classify_path",
    "discover_changed",
    "discover_tracked",
    "load_policy",
    "parse_okf_document",
    "scan_bundle",
    "scan_paths",
    "validate_completion_claim",
    "validate_manifest",
]
