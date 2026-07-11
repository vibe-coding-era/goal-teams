#!/usr/bin/env python3
"""Validate Goal Teams Harness contracts and V2.3 evidence bindings."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "v23" / "goalteams_v23.py"
REQUIRED_KEYS = {"checks", "evidence_paths", "failure_report"}
OPTIONAL_KEYS = {"commands", "artifact_checks", "e2e_checks", "pixel_diff_checks", "not_applicable_reason", "evidence_records"}

def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)

def load_contract(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ModuleNotFoundError:
            fail(f"{path} is YAML but PyYAML is unavailable; use JSON or install PyYAML")
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        fail(f"{path} must contain a mapping/object")
    return data

def validate_evidence_record(record_path: Path, root: Path) -> None:
    proc = subprocess.run([sys.executable, str(TOOL), "validate-evidence", str(record_path), "--root", str(root)], text=True, capture_output=True)
    if proc.returncode != 0:
        fail(proc.stdout.strip() or proc.stderr.strip())

def validate_contract(data: dict[str, Any], label: str, root: Path) -> None:
    contract = data.get("harness_contract", data)
    if not isinstance(contract, dict):
        fail(f"{label}: harness_contract must be an object")
    missing = sorted(REQUIRED_KEYS - set(contract))
    if missing:
        fail(f"{label}: missing required Harness keys: {', '.join(missing)}")
    for key in REQUIRED_KEYS | OPTIONAL_KEYS:
        if key in contract and contract[key] in (None, "", []):
            fail(f"{label}: {key} must not be empty when present")
    checks = contract.get("checks", [])
    if not isinstance(checks, list):
        fail(f"{label}: checks must be a list")
    for check in checks:
        if isinstance(check, dict) and check.get("required", True) and not check.get("acceptance_criteria_refs"):
            fail(f"{label}: required check missing acceptance_criteria_refs")
    task_type = str(data.get("task_type", contract.get("task_type", ""))).lower()
    is_ui = bool(data.get("ui_level") or contract.get("ui_level") or task_type in {"ui", "frontend", "html", "browser"})
    is_replica = bool(data.get("replica") or contract.get("replica") or task_type in {"replica", "recreation", "clone"})
    not_applicable = str(contract.get("not_applicable_reason", ""))
    if is_ui and "e2e_checks" not in contract and "E2E" not in not_applicable:
        fail(f"{label}: UI-level tasks require e2e_checks or explicit E2E not_applicable_reason")
    if is_replica and "pixel_diff_checks" not in contract and "像素" not in not_applicable and "pixel" not in not_applicable.lower():
        fail(f"{label}: replica tasks require pixel_diff_checks or explicit pixel not_applicable_reason")
    for evidence in contract.get("evidence_records", []):
        evidence_path = root / evidence
        if not evidence_path.exists():
            fail(f"{label}: evidence record not found: {evidence}")
        validate_evidence_record(evidence_path, root)

def self_test() -> None:
    validate_contract({"task_type":"ui", "harness_contract":{"checks":[{"check_id":"CHECK-1","acceptance_criteria_refs":["AC-1"]}], "e2e_checks":["desktop"], "evidence_paths":["progress.md"], "failure_report":{"failing_check":"required"}}}, "self-test-ui", ROOT)
    validate_contract({"task_type":"replica", "harness_contract":{"checks":[{"check_id":"CHECK-2","acceptance_criteria_refs":["AC-2"]}], "pixel_diff_checks":[{"threshold":0.01}], "evidence_paths":["artifacts/diff.ppm"], "failure_report":{"failing_check":"required"}}}, "self-test-replica", ROOT)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    for item in args.paths:
        validate_contract(load_contract(Path(item)), item, Path(args.root))
    if not args.paths and not args.self_test:
        parser.print_help(); return
    print("Harness validation passed.")
if __name__ == "__main__":
    main()
