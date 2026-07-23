#!/usr/bin/env python3
"""Fail-closed behavior and provenance scorer for GT-BENCH-005."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import stat
import struct
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MANIFEST = (
    ROOT / "benchmarks" / "fixtures" / "v2.44" / "testing-capability-cases.json"
)
CANONICAL_MANIFEST_SHA256 = (
    "3ace7d9b01e3ca08daf7eef294a5dbfc1c482805faf2426087e223c17bfb6cfe"
)
REFERENCE_APP = ROOT / "benchmarks" / "tasks" / "GT-BENCH-005" / "reference_app.py"
STATIC_UI = ROOT / "benchmarks" / "tasks" / "GT-BENCH-005" / "static" / "index.html"
RUNNER = ROOT / "scripts" / "benchmark" / "v244_testing_capability_runner.py"
BROWSER_RUNNER = ROOT / "scripts" / "benchmark" / "v244_testing_capability_browser.cjs"
SCORER = Path(__file__).resolve()
EVIDENCE_SCHEMA = "goal-teams-testing-capability-evidence-v2.44"
RAW_SCHEMA = "goal-teams-testing-capability-raw-observation-v2.44"
RUN_SCHEMA = "goal-teams-testing-capability-run-v2.44"
SCORE_SCHEMA = "goal-teams-testing-capability-score-v2.44"
VALID_STATUSES = {"passed", "failed", "not_run"}

EXPECTED_CASES = (
    ("API-AUTH-001", "api", 1.5),
    ("API-IDEMPOTENCY-001", "api", 1.5),
    ("API-CONCURRENCY-001", "api", 1.5),
    ("API-CONSISTENCY-001", "api", 1.5),
    ("E2E-SESSION-001", "e2e", 1.0),
    ("E2E-DOUBLE-CLICK-001", "e2e", 1.0),
    ("E2E-REFRESH-001", "e2e", 1.0),
    ("E2E-RECOVERY-001", "e2e", 1.0),
)
EXPECTED_MODES = (
    ("reference", "positive_baseline", ()),
    ("api_auth_bypass", "authorization", ("API-AUTH-001",)),
    ("api_idempotency_broken", "idempotency", ("API-IDEMPOTENCY-001",)),
    ("api_concurrency_race", "concurrency", ("API-CONCURRENCY-001",)),
    (
        "api_eventual_consistency_stale",
        "eventual_consistency",
        ("API-CONSISTENCY-001",),
    ),
    ("e2e_session_lost", "session", ("E2E-SESSION-001",)),
    ("e2e_double_click", "duplicate_submission", ("E2E-DOUBLE-CLICK-001",)),
    ("e2e_refresh_drops_state", "state_recovery", ("E2E-REFRESH-001",)),
    ("e2e_error_no_recovery", "error_recovery", ("E2E-RECOVERY-001",)),
)
SOURCE_FILES = {
    "manifest": CANONICAL_MANIFEST,
    "runner": RUNNER,
    "scorer": SCORER,
    "reference_app": REFERENCE_APP,
    "browser_runner": BROWSER_RUNNER,
    "static_ui": STATIC_UI,
}


class ScoreError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoreError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScoreError(f"{path} must contain a JSON object")
    return value


def validate_canonical_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != "goal-teams-testing-capability-benchmark-v2.44":
        raise ScoreError("canonical manifest schema mismatch")
    if manifest.get("benchmark_id") != "GT-BENCH-005":
        raise ScoreError("canonical manifest benchmark_id mismatch")
    if manifest.get("maximum_score") != 10.0:
        raise ScoreError("canonical manifest maximum must be 10")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != len(EXPECTED_CASES):
        raise ScoreError("canonical manifest must contain exactly 8 cases")
    simplified_cases = [
        (item.get("case_id"), item.get("layer"), item.get("weight"))
        for item in cases
        if isinstance(item, dict)
    ]
    if simplified_cases != list(EXPECTED_CASES):
        raise ScoreError("canonical case ids, layers, order, or weights changed")
    api_max = sum(weight for _case, layer, weight in EXPECTED_CASES if layer == "api")
    e2e_max = sum(weight for _case, layer, weight in EXPECTED_CASES if layer == "e2e")
    if (api_max, e2e_max) != (6.0, 4.0):
        raise ScoreError("canonical layer weights must remain API 6 and E2E 4")

    modes = manifest.get("candidate_modes")
    if not isinstance(modes, list) or len(modes) != len(EXPECTED_MODES):
        raise ScoreError("canonical manifest must contain reference plus 8 defects")
    simplified_modes = [
        (
            item.get("mode"),
            item.get("risk"),
            tuple(item.get("expected_detected_by", [])),
        )
        for item in modes
        if isinstance(item, dict)
    ]
    if simplified_modes != list(EXPECTED_MODES):
        raise ScoreError("canonical risks or expected defect bindings changed")
    return manifest


def load_canonical_manifest() -> dict[str, Any]:
    if not CANONICAL_MANIFEST.is_file() or CANONICAL_MANIFEST.is_symlink():
        raise ScoreError("canonical manifest must be a regular non-symlink file")
    observed_digest = sha256_file(CANONICAL_MANIFEST)
    if observed_digest != CANONICAL_MANIFEST_SHA256:
        raise ScoreError("canonical manifest digest mismatch")
    return validate_canonical_manifest(load_object(CANONICAL_MANIFEST))


def expected_source_digests() -> dict[str, str]:
    rows: dict[str, str] = {}
    for name, path in SOURCE_FILES.items():
        if not path.is_file() or path.is_symlink():
            raise ScoreError(f"source file unavailable or symlinked: {name}")
        rows[name] = sha256_file(path)
    return rows


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _safe_artifact(
    evidence_root: Path,
    binding: Any,
    *,
    expected_media_type: str,
) -> Path:
    if not isinstance(binding, dict):
        raise ScoreError("artifact binding must be an object")
    relative = binding.get("path")
    if not isinstance(relative, str) or not relative:
        raise ScoreError("artifact path must be a non-empty relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise ScoreError(f"unsafe artifact path: {relative}")
    if binding.get("media_type") != expected_media_type:
        raise ScoreError(f"artifact media type mismatch: {relative}")
    expected_size = binding.get("size")
    expected_hash = binding.get("sha256")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size < 0
        or not isinstance(expected_hash, str)
        or len(expected_hash) != 64
    ):
        raise ScoreError(f"invalid artifact size or digest: {relative}")

    root = evidence_root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise ScoreError("evidence root must be a regular directory, not a symlink")
    current = root
    for component in pure.parts[:-1]:
        current = current / component
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ScoreError(f"artifact ancestor unavailable: {relative}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ScoreError(f"artifact ancestor must be a real directory: {relative}")
    path = root.joinpath(*pure.parts)
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ScoreError(f"artifact unavailable: {relative}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ScoreError(f"artifact must be a regular non-symlink file: {relative}")
    if path.stat().st_size != expected_size:
        raise ScoreError(f"artifact size mismatch: {relative}")
    if sha256_file(path) != expected_hash:
        raise ScoreError(f"artifact sha256 mismatch: {relative}")
    return path


def _verify_raw_observation(
    item: dict[str, Any], evidence_root: Path, run_id: str
) -> dict[str, Any]:
    path = _safe_artifact(
        evidence_root,
        item.get("raw_artifact"),
        expected_media_type="application/json",
    )
    raw = load_object(path)
    if raw.get("schema_version") != RAW_SCHEMA:
        raise ScoreError(f"raw observation schema mismatch: {item.get('case_id')}")
    if raw.get("run_id") != run_id:
        raise ScoreError(f"raw observation run identity mismatch: {item.get('case_id')}")
    if raw.get("case_id") != item.get("case_id"):
        raise ScoreError(f"raw observation case identity mismatch: {item.get('case_id')}")
    observation = raw.get("observation")
    if not isinstance(observation, dict) or observation != item.get("evidence"):
        raise ScoreError(f"embedded observation differs from bound raw artifact: {item.get('case_id')}")
    return observation


def _trace_binds_screenshot(
    evidence: dict[str, Any],
    evidence_root: Path,
    *,
    case_id: str,
    run_id: str,
    screenshot_sha256: str,
) -> bool:
    trace_path = _safe_artifact(
        evidence_root,
        evidence.get("browser_trace"),
        expected_media_type="application/zip",
    )
    try:
        with zipfile.ZipFile(trace_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                len(infos) < 4
                or len(names) != len(set(names))
                or "trace.trace" not in names
                or "trace.network" not in names
                or not any(name.startswith("resources/") for name in names)
                or sum(info.file_size for info in infos) > 100 * 1024 * 1024
                or any(
                    info.filename.startswith("/")
                    or ".." in PurePosixPath(info.filename).parts
                    or stat.S_ISLNK(info.external_attr >> 16)
                    for info in infos
                )
            ):
                return False
            trace_lines = archive.read("trace.trace").decode("utf-8").splitlines()
            network = archive.read("trace.network").decode("utf-8")
            events = [json.loads(line) for line in trace_lines if line.strip()]
            context = next(
                (event for event in events if event.get("type") == "context-options"),
                None,
            )
            frames = [
                event for event in events if event.get("type") == "screencast-frame"
            ]
            console_events = [
                event
                for event in events
                if event.get("type") == "console"
                and event.get("messageType") == "info"
                and isinstance(event.get("text"), str)
                and event["text"].startswith("GT_BENCH_BROWSER_PROVENANCE ")
            ]
            if (
                not isinstance(context, dict)
                or context.get("browserName") != "chromium"
                or context.get("title") != f"GT-BENCH-005:{run_id}:{case_id}"
                or context.get("options", {}).get("viewport")
                != {"width": 1280, "height": 720}
                or len(frames) < 2
                or any(
                    frame.get("width") != 1280
                    or frame.get("height") != 720
                    or f"resources/{frame.get('sha1')}" not in names
                    for frame in frames
                )
                or '"type":"resource-snapshot"' not in network
                or "http://127.0.0.1:" not in network
                or len(console_events) != 1
            ):
                return False
            marker = json.loads(
                console_events[0]["text"].split(" ", 1)[1]
            )
            return marker == {
                "schema_version": "goal-teams-browser-trace-marker-v2.44",
                "run_id": run_id,
                "case_id": case_id,
                "screenshot_sha256": screenshot_sha256,
                "page_url": marker.get("page_url"),
            } and re.fullmatch(
                r"http://127\.0\.0\.1:[0-9]+/", marker.get("page_url", "")
            ) is not None
    except (
        OSError,
        ScoreError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        KeyError,
    ):
        return False


def _screenshot_observed(
    case_id: str,
    evidence: dict[str, Any],
    evidence_root: Path,
    run_id: str,
) -> bool:
    try:
        screenshot_binding = evidence.get("screenshot")
        path = _safe_artifact(
            evidence_root,
            screenshot_binding,
            expected_media_type="image/png",
        )
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return False
        offset = 8
        chunks: list[tuple[bytes, bytes]] = []
        while offset < len(data):
            if offset + 12 > len(data):
                return False
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            end = offset + 12 + length
            if end > len(data):
                return False
            payload = data[offset + 8 : offset + 8 + length]
            expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
            if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
                return False
            chunks.append((chunk_type, payload))
            offset = end
            if chunk_type == b"IEND":
                break
        if offset != len(data) or not chunks or chunks[0][0] != b"IHDR":
            return False
        ihdr = chunks[0][1]
        if len(ihdr) != 13:
            return False
        width, height, bit_depth, color_type, compression, filtering, interlace = (
            struct.unpack(">IIBBBBB", ihdr)
        )
        channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
        if (
            (width, height) != (1280, 720)
            or bit_depth != 8
            or channels is None
            or compression != 0
            or filtering != 0
            or interlace != 0
            or chunks[-1] != (b"IEND", b"")
        ):
            return False
        compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
        if not compressed:
            return False
        decoded = zlib.decompress(compressed)
        return (
            len(decoded) == height * (1 + width * channels)
            and isinstance(screenshot_binding, dict)
            and _trace_binds_screenshot(
                evidence,
                evidence_root,
                case_id=case_id,
                run_id=run_id,
                screenshot_sha256=screenshot_binding.get("sha256", ""),
            )
        )
    except (OSError, ScoreError, struct.error, zlib.error):
        return False


def oracle_pass(
    case_id: str,
    evidence: dict[str, Any],
    evidence_root: Path,
    run_id: str,
) -> bool:
    """Recompute outcomes from bound raw observations."""

    if case_id == "API-AUTH-001":
        before = evidence.get("count_before")
        after = evidence.get("count_after")
        return (
            evidence.get("unauthenticated_status") == 401
            and _number(before)
            and _number(after)
            and after == before
        )
    if case_id == "API-IDEMPOTENCY-001":
        statuses = evidence.get("statuses")
        order_ids = evidence.get("order_ids")
        return (
            statuses == [201, 200]
            and isinstance(order_ids, list)
            and len(order_ids) == 2
            and order_ids[0] is not None
            and order_ids[0] == order_ids[1]
            and evidence.get("replay_header") == "true"
            and evidence.get("count_delta") == 1
        )
    if case_id == "API-CONCURRENCY-001":
        statuses = evidence.get("statuses")
        order_ids = evidence.get("order_ids")
        return (
            isinstance(statuses, list)
            and len(statuses) == 4
            and all(status in {200, 201} for status in statuses)
            and sum(status == 201 for status in statuses) == 1
            and isinstance(order_ids, list)
            and len(order_ids) == 4
            and all(order_id is not None for order_id in order_ids)
            and len(set(order_ids)) == 1
            and evidence.get("unique_order_ids") == 1
            and evidence.get("count_delta") == 1
        )
    if case_id == "API-CONSISTENCY-001":
        polls = evidence.get("polls")
        return (
            evidence.get("create_status") == 201
            and evidence.get("created_order_id") is not None
            and evidence.get("observed_within_window") is True
            and isinstance(polls, list)
            and len(polls) > 0
        )
    if case_id == "E2E-SESSION-001":
        return (
            evidence.get("auth_state_after_reload") == "signed in"
            and _screenshot_observed(case_id, evidence, evidence_root, run_id)
        )
    if case_id == "E2E-DOUBLE-CLICK-001":
        return evidence.get("delta") == 1 and _screenshot_observed(
            case_id, evidence, evidence_root, run_id
        )
    if case_id == "E2E-REFRESH-001":
        before = evidence.get("count_before_reload")
        after = evidence.get("count_after_reload")
        return (
            _number(before)
            and before > 0
            and _number(after)
            and after == before
            and _screenshot_observed(case_id, evidence, evidence_root, run_id)
        )
    if case_id == "E2E-RECOVERY-001":
        return (
            evidence.get("retry_visible_after_failure") is True
            and evidence.get("delta") == 1
            and _screenshot_observed(case_id, evidence, evidence_root, run_id)
        )
    raise ScoreError(f"oracle is not defined for {case_id}")


def _validate_run_provenance(
    evidence: dict[str, Any],
    evidence_root: Path,
    manifest: dict[str, Any],
) -> str:
    run = evidence.get("run")
    if not isinstance(run, dict) or run.get("schema_version") != RUN_SCHEMA:
        raise ScoreError("run provenance is missing or has the wrong schema")
    run_id = run.get("run_id")
    try:
        parsed_run_id = uuid.UUID(str(run_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ScoreError("run_id must be a UUID") from exc
    if str(parsed_run_id) != run_id:
        raise ScoreError("run_id must use canonical UUID form")
    if run.get("manifest_sha256") != CANONICAL_MANIFEST_SHA256:
        raise ScoreError("evidence is not bound to the canonical manifest digest")
    if run.get("source_digests") != expected_source_digests():
        raise ScoreError("source provenance digest mismatch")
    candidate = evidence.get("candidate")
    mode = candidate.get("mode") if isinstance(candidate, dict) else None
    canonical_modes = {item["mode"] for item in manifest["candidate_modes"]}
    if (
        mode not in canonical_modes
        or candidate.get("source") != "local_reference_candidate_with_seeded_defect"
        or run.get("candidate_mode") != mode
    ):
        raise ScoreError("candidate source or mode provenance mismatch")
    browser = evidence.get("browser")
    if not isinstance(browser, dict) or browser.get("run_id") != run_id:
        raise ScoreError("browser runtime is not bound to run_id")

    database = _safe_artifact(
        evidence_root,
        run.get("database_artifact"),
        expected_media_type="application/vnd.sqlite3",
    )
    _safe_artifact(
        evidence_root,
        run.get("service_log_artifact"),
        expected_media_type="text/plain",
    )
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        row = connection.execute(
            "SELECT run_id, candidate_mode FROM benchmark_run WHERE singleton = 1"
        ).fetchone()
        connection.close()
    except sqlite3.Error as exc:
        raise ScoreError("database provenance cannot be read") from exc
    if row != (run_id, mode):
        raise ScoreError("database run identity or candidate mode mismatch")
    return run_id


def score_evidence(
    evidence: dict[str, Any],
    *,
    evidence_root: Path,
) -> dict[str, Any]:
    manifest = load_canonical_manifest()
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ScoreError("unsupported evidence schema")
    if evidence.get("benchmark_id") != manifest["benchmark_id"]:
        raise ScoreError("benchmark_id does not match canonical manifest")
    run_id = _validate_run_provenance(evidence, evidence_root, manifest)
    raw_cases = evidence.get("cases")
    if not isinstance(raw_cases, list):
        raise ScoreError("evidence.cases must be an array")

    expected = {item["case_id"]: item for item in manifest["cases"]}
    observed: dict[str, dict[str, Any]] = {}
    for item in raw_cases:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise ScoreError("every evidence case must be an object with case_id")
        case_id = item["case_id"]
        if case_id in observed:
            raise ScoreError(f"duplicate evidence case: {case_id}")
        if case_id not in expected:
            raise ScoreError(f"unexpected evidence case: {case_id}")
        if item.get("layer") != expected[case_id]["layer"]:
            raise ScoreError(f"evidence layer mismatch for {case_id}")
        status_value = item.get("status")
        if status_value not in VALID_STATUSES:
            raise ScoreError(f"invalid status for {case_id}: {status_value!r}")
        behavior_observed = item.get("behavior_observed")
        if not isinstance(behavior_observed, bool):
            raise ScoreError(f"behavior_observed must be boolean for {case_id}")
        if status_value in {"passed", "failed"} and not behavior_observed:
            raise ScoreError(f"{case_id} claims a behavior result without behavior evidence")
        observation = _verify_raw_observation(item, evidence_root, run_id)
        if status_value in {"passed", "failed"}:
            derived = (
                "passed"
                if oracle_pass(case_id, observation, evidence_root, run_id)
                else "failed"
            )
            if status_value != derived:
                raise ScoreError(
                    f"{case_id} declared {status_value} but behavior oracle derived {derived}"
                )
        observed[case_id] = item

    missing = sorted(set(expected) - set(observed))
    if missing:
        raise ScoreError(f"missing evidence cases: {', '.join(missing)}")

    scored_cases: list[dict[str, Any]] = []
    earned = 0.0
    by_layer: dict[str, dict[str, float | int]] = {}
    for case_id, contract in expected.items():
        result = observed[case_id]
        weight = float(contract["weight"])
        layer = contract["layer"]
        case_earned = weight if result["status"] == "passed" else 0.0
        earned += case_earned
        layer_row = by_layer.setdefault(
            layer, {"earned": 0.0, "maximum": 0.0, "not_run": 0}
        )
        layer_row["earned"] = float(layer_row["earned"]) + case_earned
        layer_row["maximum"] = float(layer_row["maximum"]) + weight
        if result["status"] == "not_run":
            layer_row["not_run"] = int(layer_row["not_run"]) + 1
        scored_cases.append(
            {
                "case_id": case_id,
                "layer": layer,
                "status": result["status"],
                "weight": weight,
                "earned": case_earned,
                "behavior_observed": result["behavior_observed"],
                "oracle_recomputed": result["status"] != "not_run",
                "raw_artifact_sha256": result["raw_artifact"]["sha256"],
            }
        )

    not_run = sum(item["status"] == "not_run" for item in observed.values())
    return {
        "schema_version": SCORE_SCHEMA,
        "benchmark_id": manifest["benchmark_id"],
        "run_id": run_id,
        "canonical_manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "candidate": evidence.get("candidate"),
        "score": round(earned, 2),
        "maximum_score": 10.0,
        "status": "complete" if not_run == 0 else "partial",
        "not_run_count": not_run,
        "by_layer": by_layer,
        "cases": scored_cases,
        "scoring_basis": "bound_raw_api_and_browser_behavior_only",
        "non_behavior_inputs_counted": False,
        "declared_status_trusted_without_oracle": False,
        "provenance_verified": True,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        evidence_path = args.evidence.absolute()
        if evidence_path.is_symlink() or not evidence_path.is_file():
            raise ScoreError("evidence must be a regular non-symlink file")
        result = score_evidence(
            load_object(evidence_path),
            evidence_root=evidence_path.parent,
        )
    except ScoreError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
