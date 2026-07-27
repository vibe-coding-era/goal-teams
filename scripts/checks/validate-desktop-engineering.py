#!/usr/bin/env python3
"""Fail-closed validator for the Goal Teams V2.46 desktop contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "schemas" / "v2.46" / "desktop-engineering.schema.json"
DEFAULT_MANIFEST = ROOT / "references" / "desktop-capability-manifest.json"
SCHEMA_VERSION = "goal-teams-desktop-engineering-v2.46"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEVEL = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
PROFILE = {"lite": 1, "standard": 2, "full": 3, "regulated": 4}
BLOCKING = {"failed", "blocked", "not_run", "flaky", "unavailable"}


class DesktopError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DesktopError("E_V246_DESKTOP_SCHEMA", f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} is not an object")
    return value


def _resolve(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise DesktopError("E_V246_DESKTOP_SCHEMA", "external schema ref forbidden")
    value: Any = root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"unresolved ref: {ref}")
        value = value[key]
    if not isinstance(value, dict):
        raise DesktopError("E_V246_DESKTOP_SCHEMA", f"non-object ref: {ref}")
    return value


def _schema_validate(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str = "$",
) -> None:
    if "$ref" in schema:
        _schema_validate(value, _resolve(root, str(schema["$ref"])), root, path)
        return
    choices = schema.get("oneOf")
    if isinstance(choices, list):
        matches = 0
        for choice in choices:
            try:
                _schema_validate(value, choice, root, path)
            except DesktopError:
                continue
            matches += 1
        if matches != 1:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} does not match oneOf")
        return
    if "const" in schema and value != schema["const"]:
        raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} differs from const")
    if "enum" in schema and value not in schema["enum"]:
        raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} is outside enum")
    kind = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(str(kind), True)
    if not valid:
        raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} has wrong type")
    if isinstance(value, dict) and kind == "object":
        required = schema.get("required", [])
        if any(key not in value for key in required):
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} lacks required field")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} has unknown field")
        for key, nested in value.items():
            if isinstance(properties.get(key), dict):
                _schema_validate(nested, properties[key], root, f"{path}/{key}")
        if len(value) < int(schema.get("minProperties", 0)):
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} has too few fields")
    if isinstance(value, list) and kind == "array":
        if len(value) < int(schema.get("minItems", 0)):
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} has too few items")
        if schema.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} has duplicates")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _schema_validate(item, schema["items"], root, f"{path}/{index}")
    if isinstance(value, str) and kind == "string":
        if len(value) < int(schema.get("minLength", 0)):
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} is empty")
        if schema.get("pattern") and re.search(str(schema["pattern"]), value) is None:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} pattern mismatch")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} is not date-time") from exc
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{path} below exclusive minimum")


def _artifact_refs(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            yield value
        for nested in value.values():
            yield from _artifact_refs(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _artifact_refs(nested)


def _evidence_refs(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, dict):
        required = {
            "evidence_id",
            "level",
            "artifact",
            "code_revision",
            "contract_revision",
            "environment_id",
        }
        if required <= set(value):
            yield value
        for nested in value.values():
            yield from _evidence_refs(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _evidence_refs(nested)


def _verify_artifacts(document: Mapping[str, Any], fixture_root: Path | None) -> int:
    count = 0
    for ref in _artifact_refs(document):
        count += 1
        pure = PurePosixPath(str(ref.get("path", "")))
        digest = str(ref.get("sha256", ""))
        if pure.is_absolute() or ".." in pure.parts or SHA256_RE.fullmatch(digest) is None:
            raise DesktopError("E_V246_DESKTOP_ARTIFACT", "artifact ref is unsafe")
        if fixture_root is None:
            continue
        root = fixture_root.resolve()
        path = (root / pure).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise DesktopError("E_V246_DESKTOP_ARTIFACT", "artifact escaped root") from exc
        if not path.is_file() or path.is_symlink():
            raise DesktopError("E_V246_DESKTOP_ARTIFACT", f"missing artifact: {pure}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise DesktopError("E_V246_DESKTOP_ARTIFACT", f"digest mismatch: {pure}")
    return count


def _validate_typed_evidence(
    document: Mapping[str, Any],
    fixture_root: Path | None,
    manifest: Mapping[str, Any],
) -> int:
    count = 0
    fields = {
        "evidence_id",
        "level",
        "code_revision",
        "contract_revision",
        "environment_id",
        "evidence_type",
        "result",
        "producer_run_id",
        "reviewer_run_id",
        "subject_id",
        "command",
        "tuple_id",
        "assertion_ids",
    }
    for evidence in _evidence_refs(document):
        count += 1
        if fixture_root is None:
            continue
        artifact = evidence["artifact"]
        receipt = _load_json(
            fixture_root.resolve() / PurePosixPath(str(artifact["path"]))
        )
        expected = {key: evidence[key] for key in fields}
        expected["schema_version"] = manifest["typed_evidence_contract"][
            "schema_version"
        ]
        if receipt != expected:
            raise DesktopError(
                "E_V246_DESKTOP_EVIDENCE_LEVEL",
                "typed Evidence artifact does not match its declared binding",
            )
    return count


def _require_evidence_binding(
    evidence: Mapping[str, Any],
    *,
    evidence_type: str,
    subject_id: str,
    producer: str,
    reviewer: str,
    level: str | None = None,
    command: str | None = None,
    tuple_id: str | None = None,
    expected_result: str | None = "passed",
) -> None:
    if (
        evidence.get("evidence_type") != evidence_type
        or (
            expected_result is not None
            and evidence.get("result") != expected_result
        )
        or evidence.get("subject_id") != subject_id
        or evidence.get("producer_run_id") != producer
        or evidence.get("reviewer_run_id") != reviewer
        or evidence.get("command") != command
        or evidence.get("tuple_id") != tuple_id
        or not evidence.get("assertion_ids")
        or (level is not None and evidence.get("level") != level)
    ):
        raise DesktopError(
            "E_V246_DESKTOP_EVIDENCE_LEVEL",
            f"typed Evidence binding drift: {evidence_type}:{subject_id}",
        )


def _validate_approval_artifact(
    artifact_ref: Mapping[str, Any],
    expected: Mapping[str, Any],
    fixture_root: Path | None,
    manifest: Mapping[str, Any],
) -> None:
    if fixture_root is None:
        return
    receipt = _load_json(
        fixture_root.resolve() / PurePosixPath(str(artifact_ref["path"]))
    )
    canonical = {
        "schema_version": manifest["typed_approval_contract"]["schema_version"],
        **dict(expected),
    }
    if receipt != canonical:
        raise DesktopError(
            "E_V246_DESKTOP_NA",
            "typed approval artifact does not match its declared scope",
        )


def _unique(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value or value in result:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", f"{key} is missing or reused")
        result[value] = row
    return result


def _validate_rust(
    document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    fixture_root: Path | None,
) -> list[str]:
    rust = document["rust_backend_contract"]
    roles = document["roles"]
    role_ids = {value for value in roles.values() if isinstance(value, str)}
    for contract_name in manifest["rust_contract_applicability"]["contracts"]:
        contract = rust[contract_name]
        if contract["applicable"] is True:
            if any(
                value is not True
                for key, value in contract.items()
                if key != "applicable"
            ):
                raise DesktopError(
                    "E_V246_DESKTOP_ROUTE",
                    f"applicable Rust contract is incomplete: {contract_name}",
                )
            continue
        approval = contract.get("na_approval")
        if (
            not isinstance(approval, dict)
            or approval.get("approver_run_id") in role_ids
        ):
            raise DesktopError(
                "E_V246_DESKTOP_NA",
                f"Rust contract N/A is not independently approved: {contract_name}",
            )
        _validate_approval_artifact(
            approval["artifact"],
            {
                "approval_type": "rust_contract_na",
                "bundle_id": document["bundle_id"],
                "bundle_revision": document["revision"],
                "contract_type": contract_name,
                "reason": approval["reason"],
                "approver_run_id": approval["approver_run_id"],
                "decision": "approved",
            },
            fixture_root,
            manifest,
        )
    nodes = _unique(rust["crate_nodes"], "node_id")
    edges = rust["crate_edges"]
    graph: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        source, target = edge.get("from"), edge.get("to")
        if source not in nodes or target not in nodes or source == target:
            raise DesktopError("E_V246_DESKTOP_DAG", "crate edge is unknown or self-referential")
        graph[str(source)].append(str(target))
        source_layer = nodes[str(source)]["layer"]
        target_layer = nodes[str(target)]["layer"]
        allowed_dependencies = {
            "domain": {"domain"},
            "application": {"domain", "application"},
            "infrastructure": {"domain", "application", "infrastructure"},
            "tauri_adapter": {"domain", "application", "tauri_adapter"},
            "composition_root": set(manifest["rust_layers"]),
        }
        if target_layer not in allowed_dependencies[source_layer]:
            raise DesktopError(
                "E_V246_DESKTOP_DAG",
                f"forbidden layer dependency: {source_layer}->{target_layer}",
            )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise DesktopError("E_V246_DESKTOP_DAG", "crate/module dependency cycle")
        if node in visited:
            return
        visiting.add(node)
        for target in graph[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    gates = _unique(rust["gates"], "gate_id")
    required = set(manifest["required_rust_gates"])
    if not required <= set(gates):
        raise DesktopError("E_V246_DESKTOP_DENOMINATOR", "required Rust gate missing")
    blockers: list[str] = []
    for gate_id in required:
        gate = gates[gate_id]
        command_tokens = shlex.split(str(gate.get("command", "")))
        expected_tokens = manifest["rust_gate_commands"].get(gate_id)
        command_ok = (
            command_tokens in manifest["rust_gate_commands"]["dependency_security_any"]
            if gate_id == "dependency_security"
            else command_tokens == expected_tokens
        )
        if not command_ok:
            raise DesktopError(
                "E_V246_DESKTOP_EVIDENCE_LEVEL",
                f"Rust gate command drift: {gate_id}",
            )
        evidence = gate.get("evidence")
        if gate.get("state") == "passed" and not isinstance(evidence, dict):
            raise DesktopError(
                "E_V246_DESKTOP_EVIDENCE_LEVEL",
                "passed Rust command is not Evidence",
            )
        if gate.get("state") != "passed":
            blockers.append(f"rust_gate:{gate_id}:{gate.get('state')}")
        if isinstance(evidence, dict):
            _require_evidence_binding(
                evidence,
                evidence_type="rust_gate",
                subject_id=gate_id,
                producer=document["roles"]["test_runner_run_id"],
                reviewer=document["roles"]["reviewer_run_id"],
                level="L1",
                command=gate["command"],
                expected_result=(
                    gate.get("state")
                    if gate.get("state") in {"passed", "failed"}
                    else None
                ),
            )
        if gate.get("state") == "passed" and evidence.get("level") != "L1":
            raise DesktopError("E_V246_DESKTOP_EVIDENCE_LEVEL", "Rust gate must bind L1")
        if (
            gate.get("state") == "passed"
            and evidence.get("contract_revision") != document["revision"]
        ):
            raise DesktopError("E_V246_DESKTOP_EVIDENCE_LEVEL", "Rust Evidence revision drift")
    return blockers


def _expected_levels(route: Mapping[str, Any]) -> set[str]:
    levels = {"L1"}
    if route.get("tauri") is True:
        levels.update({"L2", "L3"})
    if route.get("desktop_package") is True:
        levels.add("L4")
    return levels


def _validate_source_and_replica(
    document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    fixture_root: Path | None,
) -> list[str]:
    route = document["route"]
    source = document.get("source_contract")
    replica = document.get("ui_replica_contract")
    blockers: list[str] = []
    if (route.get("desktop") or route.get("tauri")) and not isinstance(source, dict):
        raise DesktopError("E_V246_DESKTOP_ROUTE", "desktop/Tauri route lacks source contract")
    if route.get("prd_only") and (
        not isinstance(source, dict)
        or source.get("mode") != "prd_only"
        or source.get("prd_ref") is None
        or source.get("route_revision") != "replica"
        or source.get("baseline_approval", {}).get("decision") != "approved"
    ):
        raise DesktopError("E_V246_DESKTOP_ROUTE", "PRD-only route lacks approved prototype chain")
    if isinstance(source, dict):
        approval = source["baseline_approval"]
        roles = document["roles"]
        if (
            approval["author_run_id"] == approval["reviewer_run_id"]
            or approval["reviewer_run_id"]
            not in {roles["reviewer_run_id"], roles["qa_run_id"]}
            or approval["reviewer_run_id"] == roles["implementer_run_id"]
        ):
            raise DesktopError("E_V246_DESKTOP_INDEPENDENCE", "baseline was self-approved")
        _validate_approval_artifact(
            approval["artifact"],
            {
                "approval_type": "baseline",
                "bundle_id": document["bundle_id"],
                "bundle_revision": document["revision"],
                "approval_id": approval["approval_id"],
                "author_run_id": approval["author_run_id"],
                "reviewer_run_id": approval["reviewer_run_id"],
                "decision": approval["decision"],
            },
            fixture_root,
            manifest,
        )
    if route.get("replica") is True:
        if not isinstance(replica, dict) or not isinstance(source, dict):
            raise DesktopError("E_V246_DESKTOP_ROUTE", "replica route lacks source/UI contract")
        coverage = replica["coverage_complete"]
        roles = document["roles"]
        _require_evidence_binding(
            coverage["evidence"],
            evidence_type="coverage_metric",
            subject_id="coverage_complete",
            producer=roles["test_runner_run_id"],
            reviewer=roles["reviewer_run_id"],
            expected_result=(
                coverage["state"]
                if coverage["state"] in {"passed", "failed"}
                else None
            ),
        )
        expected_surface_denominator = sum(
            len(surface["state_ids"])
            for surface in replica["surfaces"]
            if surface["required"]
        )
        if not (
            coverage["state"] == "passed"
            and coverage["denominator"] > 0
            and coverage["denominator"] == expected_surface_denominator
            and coverage["covered"] == coverage["denominator"]
        ):
            blockers.append("replica:coverage_complete")
        native = replica["native_semantic_match"]
        _require_evidence_binding(
            native["evidence"],
            evidence_type="native_metric",
            subject_id="native_semantic_match",
            producer=roles["test_runner_run_id"],
            reviewer=roles["reviewer_run_id"],
            expected_result=(
                native["state"] if native["state"] in {"passed", "failed"} else None
            ),
        )
        if not (
            native["state"] == "passed"
            and native["denominator"] > 0
            and native["passed"] == native["denominator"]
        ):
            blockers.append("replica:native_semantic_match")
        for metric in replica["pixel_exact"]:
            _require_evidence_binding(
                metric["evidence"],
                evidence_type="pixel_metric",
                subject_id="pixel_exact",
                producer=roles["test_runner_run_id"],
                reviewer=roles["reviewer_run_id"],
                tuple_id=metric["tuple_id"],
                expected_result=(
                    metric["state"]
                    if metric["state"] in {"passed", "failed"}
                    else None
                ),
            )
            if not (
                metric["state"] == "passed"
                and metric["changed_pixels"] == 0
                and metric["tolerance"] == 0
                and metric["mask_count"] == 0
            ):
                blockers.append(f"replica:pixel_exact:{metric['tuple_id']}")
        for metric in replica["high_fidelity"]:
            _require_evidence_binding(
                metric["evidence"],
                evidence_type="high_fidelity_metric",
                subject_id="high_fidelity",
                producer=roles["test_runner_run_id"],
                reviewer=roles["reviewer_run_id"],
                tuple_id=metric["tuple_id"],
                expected_result=(
                    metric["state"]
                    if metric["state"] in {"passed", "failed"}
                    else None
                ),
            )
            if not (
                metric["state"] == "passed"
                and metric["actual_score"] >= metric["approved_threshold"]
            ):
                blockers.append(f"replica:high_fidelity:{metric['tuple_id']}")
    elif replica is not None:
        raise DesktopError("E_V246_DESKTOP_ROUTE", "UI replica contract exists outside replica route")
    return blockers


def _validate_desktop_tests(
    document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    fixture_root: Path | None,
) -> tuple[list[str], int, int]:
    route = document["route"]
    contract = document.get("desktop_test_contract")
    expected_levels = _expected_levels(route)
    needs_desktop = any(
        route.get(key) is True
        for key in (
            "desktop",
            "tauri",
            "desktop_package",
            "native_surface",
            "cross_platform_desktop_test",
        )
    )
    if not needs_desktop:
        if contract is not None:
            raise DesktopError("E_V246_DESKTOP_ROUTE", "rust-only route must not require L2/L3")
        return [], 0, 0
    if not isinstance(contract, dict):
        raise DesktopError("E_V246_DESKTOP_ROUTE", "desktop route lacks test contract")
    if set(contract["required_evidence_levels"]) != expected_levels:
        raise DesktopError("E_V246_DESKTOP_ROUTE", "evidence levels differ from route derivation")
    tuples = _unique(contract["platform_denominator"], "tuple_id")
    required_tuples = {key: value for key, value in tuples.items() if value["required"]}
    if not required_tuples:
        raise DesktopError("E_V246_DESKTOP_DENOMINATOR", "required platform tuple missing")
    if route.get("cross_platform_desktop_test") and {
        row["os"] for row in required_tuples.values()
    } != {"macos", "windows", "linux"}:
        raise DesktopError("E_V246_DESKTOP_DENOMINATOR", "cross-platform route lacks three OS tuples")
    tuple_contracts = {
        "macos": ({"wkwebview"}, {"app", "dmg", "pkg"}, {"quartz"}),
        "windows": ({"webview2"}, {"msi", "nsis"}, {"win32"}),
        "linux": ({"webkitgtk"}, {"deb", "rpm", "appimage"}, {"x11", "wayland"}),
    }
    for platform in tuples.values():
        webviews, packages, displays = tuple_contracts[platform["os"]]
        if (
            platform["webview"] not in webviews
            or platform["package_format"] not in packages
            or platform["display_server"] not in displays
        ):
            raise DesktopError(
                "E_V246_DESKTOP_DENOMINATOR", "platform tuple fields are inconsistent"
            )
    cases = _unique(contract["cases"], "case_id")
    required_cases = {key: value for key, value in cases.items() if value["required"]}
    if needs_desktop:
        if not set(manifest["required_native_risks"]) <= {
            case["risk_id"] for case in cases.values()
        }:
            raise DesktopError("E_V246_DESKTOP_DENOMINATOR", "native risk denominator was reduced")
    runs = _unique(contract["runs"], "run_id")
    roles = document["roles"]
    blockers: list[str] = []
    covered_pairs: set[tuple[str, str]] = set()
    passed_levels: set[str] = set()
    allowed_drivers = manifest["driver_rules"]
    for run in runs.values():
        case = cases.get(run["case_id"])
        platform = tuples.get(run["tuple_id"])
        if case is None or platform is None:
            raise DesktopError("E_V246_DESKTOP_DENOMINATOR", "run is outside case/tuple denominator")
        if (
            run["runner_run_id"] != roles["test_runner_run_id"]
            or run["reviewer_run_id"] != roles["reviewer_run_id"]
            or run["runner_run_id"] == run["reviewer_run_id"]
        ):
            raise DesktopError("E_V246_DESKTOP_INDEPENDENCE", "run/review identity drift")
        driver = run["driver"]
        os_name = platform["os"]
        if driver not in allowed_drivers[os_name]["allowed"] and driver not in {
            "mock_runtime",
            "browser_only",
        }:
            raise DesktopError("E_V246_DESKTOP_DRIVER", f"driver forbidden on {os_name}")
        level = run["evidence_level"]
        if driver in {"mock_runtime", "browser_only"} and level != "L2":
            raise DesktopError("E_V246_DESKTOP_DRIVER", "mock/browser driver can only prove L2")
        if level == "L4" and driver not in manifest[
            "evidence_level_driver_rules"
        ]["L4"]:
            raise DesktopError(
                "E_V246_DESKTOP_DRIVER",
                "L4 production package cannot carry an instrumented Tauri driver",
            )
        if LEVEL[level] < LEVEL[case["minimum_evidence_level"]]:
            raise DesktopError("E_V246_DESKTOP_EVIDENCE_LEVEL", "run is below case minimum")
        evidence = run.get("evidence")
        if isinstance(evidence, dict):
            _require_evidence_binding(
                evidence,
                evidence_type="desktop_run",
                subject_id=run["run_id"],
                producer=run["runner_run_id"],
                reviewer=run["reviewer_run_id"],
                level=level,
                tuple_id=run["tuple_id"],
                expected_result=(
                    run["status"]
                    if run["status"] in {"passed", "failed"}
                    else None
                ),
            )
        if run["status"] == "passed":
            if not isinstance(evidence, dict) or evidence.get("level") != level:
                raise DesktopError("E_V246_DESKTOP_EVIDENCE_LEVEL", "passed run lacks matching Evidence")
            if (
                evidence.get("contract_revision") != document["revision"]
                or evidence.get("evidence_id") == ""
            ):
                raise DesktopError("E_V246_DESKTOP_EVIDENCE_LEVEL", "Evidence revision is stale")
            covered_pairs.add((run["case_id"], run["tuple_id"]))
            passed_levels.add(level)
        elif run["status"] == "not_applicable":
            approval = case.get("na_approval")
            if (
                case["required"]
                or not isinstance(approval, dict)
                or approval["approver_run_id"]
                in {
                    roles["implementer_run_id"],
                    roles["test_designer_run_id"],
                    roles["test_runner_run_id"],
                    roles["reviewer_run_id"],
                }
            ):
                raise DesktopError("E_V246_DESKTOP_NA", "N/A lacks independent approval")
            _validate_approval_artifact(
                approval["artifact"],
                {
                    "approval_type": "na",
                    "bundle_id": document["bundle_id"],
                    "bundle_revision": document["revision"],
                    "case_id": case["case_id"],
                    "approver_run_id": approval["approver_run_id"],
                    "decision": "approved",
                },
                fixture_root,
                manifest,
            )
        elif run["status"] in BLOCKING:
            blockers.append(f"run:{run['run_id']}:{run['status']}")
    for case_id in required_cases:
        for tuple_id in required_tuples:
            if (case_id, tuple_id) not in covered_pairs:
                blockers.append(f"missing_run:{case_id}:{tuple_id}")
    desktop_required_levels = expected_levels - {"L1"}
    if not desktop_required_levels <= passed_levels:
        blockers.extend(
            f"missing_level:{level}"
            for level in sorted(desktop_required_levels - passed_levels)
        )
    if route.get("desktop_package"):
        isolation = contract["production_isolation"]
        _require_evidence_binding(
            isolation["evidence"],
            evidence_type="production_isolation",
            subject_id="production_isolation",
            producer=roles["test_runner_run_id"],
            reviewer=roles["reviewer_run_id"],
            level="L4",
            expected_result=(
                isolation["state"]
                if isolation["state"] in {"passed", "failed"}
                else None
            ),
        )
        if isolation["state"] != "passed" or not all(
            isolation[key]
            for key in (
                "test_plugin_absent",
                "debug_port_absent",
                "mock_hook_absent",
                "broad_test_capability_absent",
            )
        ) or isolation["evidence"]["level"] != "L4":
            blockers.append("production_package_isolation")
    return blockers, len(required_cases), len(required_tuples)


def _validate_roles(document: Mapping[str, Any]) -> None:
    roles = document["roles"]
    base = [
        roles["implementer_run_id"],
        roles["test_designer_run_id"],
        roles["test_runner_run_id"],
        roles["reviewer_run_id"],
    ]
    if len(set(base)) != 4:
        raise DesktopError("E_V246_DESKTOP_INDEPENDENCE", "core roles are not independent")
    if document["profile"] in {"full", "regulated"}:
        all_roles = base + [roles["qa_run_id"], roles["completion_auditor_run_id"]]
        if None in all_roles or len(set(all_roles)) != 6:
            raise DesktopError("E_V246_DESKTOP_INDEPENDENCE", "Full roles are incomplete")


def _derive_run_outcome(
    document: Mapping[str, Any],
    blockers: list[str],
    manifest: Mapping[str, Any],
) -> str:
    states: list[str] = []
    required_gates = set(manifest["required_rust_gates"])
    states.extend(
        str(gate["state"])
        for gate in document["rust_backend_contract"]["gates"]
        if gate["gate_id"] in required_gates
    )
    replica = document.get("ui_replica_contract")
    if isinstance(replica, dict):
        states.extend(
            [
                str(replica["coverage_complete"]["state"]),
                str(replica["native_semantic_match"]["state"]),
            ]
        )
        states.extend(str(row["state"]) for row in replica["pixel_exact"])
        states.extend(str(row["state"]) for row in replica["high_fidelity"])
    contract = document.get("desktop_test_contract")
    if isinstance(contract, dict):
        required_cases = {
            row["case_id"] for row in contract["cases"] if row["required"]
        }
        required_tuples = {
            row["tuple_id"]
            for row in contract["platform_denominator"]
            if row["required"]
        }
        states.extend(
            str(row["status"])
            for row in contract["runs"]
            if row["case_id"] in required_cases
            and row["tuple_id"] in required_tuples
        )
        if document["route"].get("desktop_package"):
            states.append(str(contract["production_isolation"]["state"]))
    if "failed" in states:
        return "failed"
    if any(state in {"blocked", "unavailable"} for state in states):
        return "blocked"
    if "not_run" in states:
        return "not_run"
    if "flaky" in states or blockers:
        return "partial"
    return "achieved"


def _validate_desktop_completion_receipts(
    document: Mapping[str, Any],
    fixture_root: Path | None,
    manifest: Mapping[str, Any],
    evidence_ids: set[str],
) -> None:
    if document["profile"] not in {"full", "regulated"}:
        return
    contract = manifest.get("typed_completion_receipt_contract")
    decision = document["decision"]
    roles = document["roles"]
    if not isinstance(contract, dict) or fixture_root is None:
        raise DesktopError(
            "E_V246_DESKTOP_COMPLETION",
            "Full achieved requires readable typed completion receipts",
        )
    required_fields = set(contract.get("required_fields", []))
    for field, receipt_type, role_field in (
        ("qa_review_ref", "qa_review", "qa_run_id"),
        (
            "completion_audit_ref",
            "completion_audit",
            "completion_auditor_run_id",
        ),
    ):
        ref = decision.get(field)
        actor = roles.get(role_field)
        if not isinstance(ref, dict) or not isinstance(actor, str):
            raise DesktopError(
                "E_V246_DESKTOP_COMPLETION",
                f"Full achieved lacks typed {receipt_type}",
            )
        try:
            payload = _load_json(
                fixture_root.resolve()
                / PurePosixPath(str(ref.get("path", "")))
            )
        except DesktopError as exc:
            raise DesktopError(
                "E_V246_DESKTOP_COMPLETION",
                f"typed {receipt_type} is unreadable",
            ) from exc
        if (
            set(payload) != required_fields
            or payload.get("schema_version") != contract.get("schema_version")
            or payload.get("receipt_type") != receipt_type
            or payload.get("bundle_id") != document["bundle_id"]
            or payload.get("bundle_revision") != document["revision"]
            or payload.get("actor_run_id") != actor
            or set(payload.get("evidence_ids", [])) != evidence_ids
            or payload.get("completion_predicates")
            != contract.get("completion_predicates")
            or payload.get("conclusion") != contract.get("passing_conclusion")
        ):
            raise DesktopError(
                "E_V246_DESKTOP_COMPLETION",
                f"typed {receipt_type} is not bound to completion facts",
            )


def validate_document(
    document: Any,
    fixture_root: str | os.PathLike[str] | None = None,
    *,
    manifest_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    try:
        if not isinstance(document, dict):
            raise DesktopError("E_V246_DESKTOP_SCHEMA", "document must be an object")
        manifest = _load_json(Path(manifest_path) if manifest_path else DEFAULT_MANIFEST)
        schema = _load_json(DEFAULT_SCHEMA)
        if (
            manifest.get("schema_version") != "goal-teams-desktop-capability-v2.46"
            or document.get("schema_version") != SCHEMA_VERSION
        ):
            raise DesktopError("E_V246_DESKTOP_SCHEMA", "version identity drift")
        _schema_validate(document, schema, schema)
        root = Path(fixture_root) if fixture_root is not None else None
        if document["decision"]["contract_achieved"] and root is None:
            raise DesktopError("E_V246_DESKTOP_ARTIFACT", "achieved requires artifact root")
        artifact_count = _verify_artifacts(document, root)
        evidence_count = 0
        evidence_ids: set[str] = set()
        for evidence in _evidence_refs(document):
            evidence_count += 1
            evidence_ids.add(str(evidence["evidence_id"]))
            if (
                evidence.get("contract_revision") != document["revision"]
                or evidence.get("level") not in LEVEL
            ):
                raise DesktopError(
                    "E_V246_DESKTOP_EVIDENCE_LEVEL",
                    "Evidence is stale or has an unknown level",
                )
        _validate_typed_evidence(document, root, manifest)
        route = document["route"]
        for escalation in manifest.get("profile_escalation", []):
            when = str(escalation.get("when", ""))
            fact = when[:-5] if when.endswith("=true") else when
            minimum_profile = str(escalation.get("minimum_profile"))
            if (
                route.get(fact) is True
                and PROFILE[document["profile"]] < PROFILE[minimum_profile]
            ):
                raise DesktopError(
                    "E_V246_DESKTOP_ROUTE",
                    f"{fact} route is below its minimum profile",
                )
        if (
            (route.get("tauri") and not route.get("desktop"))
            or (route.get("desktop_package") and not route.get("desktop"))
            or (route.get("native_surface") and not route.get("desktop"))
            or (
                route.get("cross_platform_desktop_test")
                and not route.get("desktop")
            )
            or (route.get("replica") and not route.get("desktop"))
            or (route.get("prd_only") and not route.get("replica"))
        ):
            raise DesktopError(
                "E_V246_DESKTOP_ROUTE", "desktop route facts are contradictory"
            )
        _validate_roles(document)
        blockers = _validate_rust(document, manifest, root)
        if route.get("tauri") and (
            not document["rust_backend_contract"].get("ipc_commands")
            or document["rust_backend_contract"]["security_contract"][
                "deny_paths_tested"
            ]
            is not True
        ):
            raise DesktopError(
                "E_V246_DESKTOP_ROUTE",
                "Tauri route lacks typed IPC denial-path contract",
            )
        blockers.extend(_validate_source_and_replica(document, manifest, root))
        desktop_blockers, case_count, tuple_count = _validate_desktop_tests(
            document, manifest, root
        )
        blockers.extend(desktop_blockers)
        if route.get("replica") and isinstance(
            document.get("desktop_test_contract"), dict
        ):
            required_tuple_ids = {
                row["tuple_id"]
                for row in document["desktop_test_contract"]["platform_denominator"]
                if row["required"]
            }
            replica = document["ui_replica_contract"]
            if (
                {row["tuple_id"] for row in replica["pixel_exact"]}
                != required_tuple_ids
                or {row["tuple_id"] for row in replica["high_fidelity"]}
                != required_tuple_ids
            ):
                raise DesktopError(
                    "E_V246_DESKTOP_DENOMINATOR",
                    "replica tuple fidelity denominator is incomplete",
                )
        achieved = not blockers
        derived_run_outcome = _derive_run_outcome(
            document,
            blockers,
            manifest,
        )
        decision = document["decision"]
        if (
            decision["contract_achieved"] is not achieved
            or decision["run_outcome"] != derived_run_outcome
            or (not achieved and not decision["reason_codes"])
        ):
            raise DesktopError("E_V246_DESKTOP_COMPLETION", "decision is not derived from predicates")
        if achieved:
            _validate_desktop_completion_receipts(
                document,
                root,
                manifest,
                evidence_ids,
            )
        return {
            "ok": True,
            "error_code": "OK",
            "errors": [],
            "summary": {
                "bundle_id": document["bundle_id"],
                "profile": document["profile"],
                "required_levels": sorted(_expected_levels(route)),
                "required_case_count": case_count,
                "required_platform_count": tuple_count,
                "artifact_count": artifact_count,
                "evidence_count": evidence_count,
                "blocking_reasons": sorted(set(blockers)),
                "contract_achieved": achieved,
            },
        }
    except DesktopError as exc:
        return {"ok": False, "error_code": exc.code, "errors": [exc.code], "summary": {}}
    except (KeyError, TypeError, ValueError):
        return {
            "ok": False,
            "error_code": "E_V246_DESKTOP_SCHEMA",
            "errors": ["E_V246_DESKTOP_SCHEMA"],
            "summary": {},
        }
    except Exception:
        return {
            "ok": False,
            "error_code": "E_V246_DESKTOP_INTERNAL",
            "errors": ["E_V246_DESKTOP_INTERNAL"],
            "summary": {},
        }


def _self_test_document() -> dict[str, Any]:
    evidence = {
        "evidence_id": "EV-L1",
        "level": "L1",
        "artifact": {"path": "EV-L1.json", "sha256": "0" * 64},
        "code_revision": "1" * 64,
        "contract_revision": 1,
        "environment_id": "ENV-RUST",
        "evidence_type": "rust_gate",
        "result": "passed",
        "producer_run_id": "RUN-RUNNER",
        "reviewer_run_id": "RUN-REVIEWER",
        "subject_id": "placeholder",
        "command": "placeholder",
        "tuple_id": None,
        "assertion_ids": ["ASSERT-PASSED"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": "DESKTOP-SELFTEST",
        "revision": 1,
        "profile": "lite",
        "project_id": "PROJECT-RUST",
        "generated_at": "2026-07-27T00:00:00Z",
        "route": {
            "desktop": False,
            "tauri": False,
            "rust": True,
            "desktop_package": False,
            "native_surface": False,
            "cross_platform_desktop_test": False,
            "replica": False,
            "prd_only": False,
        },
        "source_contract": None,
        "ui_replica_contract": None,
        "rust_backend_contract": {
            "crate_nodes": [{"node_id": "domain", "layer": "domain"}],
            "crate_edges": [],
            "ipc_commands": [],
            "recoverable_error_type": "DomainError",
            "panic_policy": "invariant_only",
            "async_contract": {
                "applicable": True,
                "ownership": True, "cancellation": True, "timeouts": True,
                "shutdown": True, "blocking_isolation": True,
            },
            "persistence_contract": {
                "applicable": True,
                "schema_versioned": True, "migration_tested": True,
                "atomicity_defined": True, "crash_recovery_tested": True,
                "idempotency_defined": True,
            },
            "security_contract": {
                "least_privilege_capabilities": True, "deny_paths_tested": False,
                "input_limits_defined": True, "sensitive_log_redaction": True,
            },
            "toolchain": {
                "channel": "stable", "rust_version": "1.88.0", "msrv": "1.80.0",
                "lockfile_sha256": "2" * 64,
            },
            "gates": [
                {
                    "gate_id": gate,
                    "command": command,
                    "state": "passed",
                    "evidence": {
                        **evidence,
                        "evidence_id": f"EV-{gate.upper()}",
                        "artifact": {
                            "path": f"EV-{gate.upper()}.json",
                            "sha256": "0" * 64,
                        },
                        "subject_id": gate,
                        "command": command,
                    },
                }
                for gate, command in (
                    ("fmt", "cargo fmt --all -- --check"),
                    (
                        "clippy",
                        "cargo clippy --workspace --all-targets --all-features -- -D warnings",
                    ),
                    ("test", "cargo test --workspace --all-features"),
                    ("dependency_security", "cargo audit"),
                )
            ],
        },
        "desktop_test_contract": None,
        "roles": {
            "implementer_run_id": "RUN-IMPLEMENTER",
            "test_designer_run_id": "RUN-DESIGNER",
            "test_runner_run_id": "RUN-RUNNER",
            "reviewer_run_id": "RUN-REVIEWER",
            "qa_run_id": None,
            "completion_auditor_run_id": None,
        },
        "decision": {
            "run_outcome": "achieved",
            "contract_achieved": True,
            "reason_codes": [],
            "qa_review_ref": None,
            "completion_audit_ref": None,
        },
    }


def self_test() -> dict[str, Any]:
    document = _self_test_document()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for typed in _evidence_refs(document):
            artifact = root / str(typed["artifact"]["path"])
            content = {
                "schema_version": "goal-teams-desktop-evidence-v1",
                **{
                    key: value
                    for key, value in typed.items()
                    if key != "artifact"
                },
            }
            artifact.write_text(
                json.dumps(content, sort_keys=True), encoding="utf-8"
            )
            typed["artifact"]["sha256"] = hashlib.sha256(
                artifact.read_bytes()
            ).hexdigest()
        positive = validate_document(document, fixture_root=root)
        if not positive["ok"]:
            raise DesktopError("E_V246_DESKTOP_SELF_TEST", str(positive))
        negative = json.loads(json.dumps(document))
        negative["rust_backend_contract"]["crate_edges"] = [
            {"from": "domain", "to": "domain"}
        ]
        rejected = validate_document(negative, fixture_root=root)
        if rejected["error_code"] != "E_V246_DESKTOP_DAG":
            raise DesktopError("E_V246_DESKTOP_SELF_TEST", "DAG negative missed")
    return {
        "ok": True,
        "passed": True,
        "error_code": "OK",
        "errors": [],
        "valid_cases_executed": 1,
        "invalid_cases_executed": 1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            result = self_test()
        elif args.input:
            result = validate_document(
                _load_json(args.input),
                fixture_root=args.fixture_root,
                manifest_path=args.manifest,
            )
        else:
            raise DesktopError("E_V246_DESKTOP_SCHEMA", "--input or --self-test required")
    except DesktopError as exc:
        result = {"ok": False, "error_code": exc.code, "errors": [exc.code], "summary": {}}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
