#!/usr/bin/env python3
"""Fail-closed V2.44 API/E2E testing-capability score projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "references" / "testing-capability-manifest.json"
EVIDENCE_SCHEMA = "goal-teams-testing-capability-evidence-v2.44"
SCORE_SCHEMA = "goal-teams-testing-capability-score-v2.44"
ISSUE_SCHEMA = "goal-teams-testing-issue-event-v2.44"
ISSUE_RE = re.compile(r"^GT244-TEST-[0-9]{3}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PASS = "passed"
STATUSES = {"not_run", "failed", "partial", PASS}


class ScoreError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScoreError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ScoreError(f"expected JSON object: {path}")
    return value


def safe_relative_path(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str):
        raise ScoreError("evidence path must be a string")
    relative = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ScoreError(f"unsafe evidence path: {raw!r}")
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ScoreError(f"evidence path escapes root: {raw!r}") from exc
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ScoreError(f"evidence file missing or unsafe: {raw}") from exc
        if stat.S_ISLNK(mode):
            raise ScoreError(f"evidence path contains symlink: {raw}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise ScoreError(f"evidence parent is not a directory: {raw}")
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise ScoreError(f"evidence file missing or unsafe: {raw}")
    return candidate


def validate_ref(root: Path, value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ScoreError("evidence ref must contain exactly path and sha256")
    digest = value.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ScoreError("evidence ref has invalid sha256")
    path = safe_relative_path(root, value.get("path"))
    actual = file_sha256(path)
    if actual != digest:
        raise ScoreError(f"evidence digest drift: {value['path']}")
    return {"path": value["path"], "sha256": digest}


def load_issue_projection(
    evidence_root: Path, ledger_binding: Any, manifest: dict[str, Any]
) -> tuple[dict[str, str], dict[str, Any]]:
    if not isinstance(ledger_binding, dict) or set(ledger_binding) != {
        "path",
        "sha256",
    }:
        raise ScoreError("issue_ledger must contain exactly path and sha256")
    ledger_ref = validate_ref(evidence_root, ledger_binding)
    ledger_path = safe_relative_path(evidence_root, ledger_ref["path"])
    seen_events: set[str] = set()
    projection: dict[str, str] = {}
    resolved_evidence: dict[str, list[str]] = {}
    for line_number, raw in enumerate(
        ledger_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScoreError(f"invalid issue ledger JSONL line {line_number}") from exc
        if not isinstance(event, dict) or event.get("schema_version") != ISSUE_SCHEMA:
            raise ScoreError(f"invalid issue event at line {line_number}")
        event_id = event.get("event_id")
        issue_id = event.get("issue_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen_events:
            raise ScoreError(f"duplicate or missing event_id at line {line_number}")
        if not isinstance(issue_id, str) or not ISSUE_RE.fullmatch(issue_id):
            raise ScoreError(f"invalid issue_id at line {line_number}")
        status = event.get("status")
        if status not in {"open", "in_progress", "resolved", "waived"}:
            raise ScoreError(f"invalid issue status at line {line_number}")
        if status == "resolved":
            refs = event.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                raise ScoreError(f"resolved issue lacks evidence at line {line_number}")
            resolved_evidence[issue_id] = [str(item) for item in refs]
        seen_events.add(event_id)
        projection[issue_id] = status

    known = {
        item["id"]
        for item in manifest.get("known_issues", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if known - projection.keys():
        raise ScoreError(f"known issues missing from ledger: {sorted(known - projection.keys())}")
    unresolved = sorted(
        issue_id for issue_id, status in projection.items() if status != "resolved"
    )
    return projection, {
        "ref": ledger_ref,
        "event_count": len(seen_events),
        "issue_count": len(projection),
        "known_issue_count": len(known),
        "unresolved_issue_ids": unresolved,
        "resolved_evidence": resolved_evidence,
    }


def score(
    evidence: dict[str, Any],
    manifest: dict[str, Any],
    *,
    evidence_root: Path,
    manifest_digest: str,
) -> dict[str, Any]:
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ScoreError("unsupported evidence schema")
    if evidence.get("product_version") != manifest.get("product_version"):
        raise ScoreError("product version mismatch")
    if evidence.get("manifest_sha256") != manifest_digest:
        raise ScoreError("manifest digest mismatch")
    anti_gaming = manifest.get("anti_gaming")
    if not isinstance(anti_gaming, dict) or any(anti_gaming.values()):
        raise ScoreError("anti-gaming manifest must keep every bypass disabled")

    dimensions = manifest.get("dimensions")
    supplied = evidence.get("dimensions")
    if not isinstance(dimensions, list) or not isinstance(supplied, dict):
        raise ScoreError("dimensions missing")
    expected_ids = [item.get("id") for item in dimensions if isinstance(item, dict)]
    if len(expected_ids) != len(dimensions) or set(supplied) != set(expected_ids):
        raise ScoreError("dimension set mismatch")
    if sum(item.get("weight", 0) for item in dimensions) != manifest.get("target_score"):
        raise ScoreError("dimension weights do not equal target score")

    score_rows: list[dict[str, Any]] = []
    total = 0
    all_refs: list[dict[str, str]] = []
    for dimension in dimensions:
        dimension_id = dimension["id"]
        weight = dimension.get("weight")
        required = dimension.get("required_checks")
        provided = supplied[dimension_id]
        checks = provided.get("checks") if isinstance(provided, dict) else None
        if (
            not isinstance(weight, int)
            or weight <= 0
            or not isinstance(required, list)
            or not required
            or len(set(required)) != len(required)
            or not isinstance(checks, dict)
            or set(checks) != set(required)
        ):
            raise ScoreError(f"invalid dimension contract: {dimension_id}")
        check_rows: list[dict[str, Any]] = []
        for check_id in required:
            check = checks[check_id]
            if not isinstance(check, dict) or set(check) != {"status", "evidence_refs"}:
                raise ScoreError(f"invalid check shape: {dimension_id}.{check_id}")
            status = check.get("status")
            refs = check.get("evidence_refs")
            if status not in STATUSES or not isinstance(refs, list) or not refs:
                raise ScoreError(f"invalid check result: {dimension_id}.{check_id}")
            verified_refs = [validate_ref(evidence_root, item) for item in refs]
            all_refs.extend(verified_refs)
            check_rows.append(
                {
                    "check_id": check_id,
                    "status": status,
                    "evidence_refs": verified_refs,
                }
            )
        dimension_passed = all(row["status"] == PASS for row in check_rows)
        earned = weight if dimension_passed else 0
        total += earned
        score_rows.append(
            {
                "dimension_id": dimension_id,
                "name_zh": dimension.get("name_zh"),
                "status": PASS if dimension_passed else "failed",
                "earned": earned,
                "possible": weight,
                "checks": check_rows,
            }
        )

    projection, issue_summary = load_issue_projection(
        evidence_root, evidence.get("issue_ledger"), manifest
    )
    achieved = (
        total == manifest.get("target_score")
        and not issue_summary["unresolved_issue_ids"]
        and all(row["status"] == PASS for row in score_rows)
    )
    return {
        "schema_version": SCORE_SCHEMA,
        "product_version": manifest["product_version"],
        "status": "achieved" if achieved else "failed",
        "score": total,
        "target_score": manifest["target_score"],
        "dimensions": score_rows,
        "issue_projection": projection,
        "issue_summary": issue_summary,
        "verified_evidence_ref_count": len(all_refs),
        "manifest_sha256": manifest_digest,
        "anti_gaming": anti_gaming,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evidence-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="return zero even when the evidence does not achieve 100/100",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_json(args.manifest)
        manifest_digest = file_sha256(args.manifest)
        result = score(
            load_json(args.evidence),
            manifest,
            evidence_root=args.evidence_root.resolve(),
            manifest_digest=manifest_digest,
        )
    except ScoreError as exc:
        result = {
            "schema_version": SCORE_SCHEMA,
            "status": "failed",
            "score": 0,
            "error": str(exc),
        }
    rendered = canonical_bytes(result).decode("utf-8") + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result.get("status") == "achieved" or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
