#!/usr/bin/env python3
"""Validate the standalone V2.45 Release Engineer member package."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
DEFAULT_PACKAGE_ROOT = SCRIPT.parents[1]
REQUIRED_FILES = (
    "VERSION",
    "CHANGELOG.txt",
    "INDEX.md",
    "prompt.md",
    "template.md",
    "workflow.md",
    "scripts.md",
    "references/10-final-release-evidence-check.txt",
    "references/20-plan-and-approvals.txt",
    "references/30-security-policy.txt",
    "references/40-release-kits.txt",
    "references/50-loop-and-recovery.txt",
    "kits/index.md",
    "kits/catalog.json",
    "runtime/release_member.py",
    "runtime/validate_member.py",
)
INDEX_FIELDS = (
    "role:",
    "description:",
    "triggers:",
    "rules:",
    "forbidden:",
    "inputs:",
    "outputs:",
    "validator:",
)
INDEX_REFERENCES = (
    "prompt.md",
    "template.md",
    "workflow.md",
    "scripts.md",
    "references/10-final-release-evidence-check.txt",
    "references/20-plan-and-approvals.txt",
    "references/30-security-policy.txt",
    "references/40-release-kits.txt",
    "references/50-loop-and-recovery.txt",
    "kits/catalog.json",
)
REQUIRED_MARKERS = (
    "不运行全量",
    "full_test_execution_count: 0",
    "plan approval",
    "execution approval",
    "删除库",
    "删除表",
    "删除数据",
    "restore proof",
    "Benchmark",
    "独立完成审计",
    "Gather → Reason → Act → Verify → Repeat",
    "主 `SKILL.md`",
)
FULL_TEST_PATTERNS = (
    re.compile(r"\bpytest\b", re.I),
    re.compile(r"\bcargo\s+test\b", re.I),
    re.compile(r"\bgo\s+test\b", re.I),
    re.compile(r"\bnpm\s+test\b", re.I),
    re.compile(r"\bpnpm\s+test\b", re.I),
    re.compile(r"\byarn\s+test\b", re.I),
    re.compile(r"\b(?:mvn|mvnw)\b[^\n]*\btest\b", re.I),
    re.compile(r"\bgradle\w*\b[^\n]*\btest\b", re.I),
)


def finding(code: str, message: str, path: str = "") -> dict[str, str]:
    return {"error_code": code, "message": message, "path": path}


def safe_relative(root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = (root / candidate).resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, RuntimeError, ValueError):
        return None
    return resolved


def load_catalog(path: Path, errors: list[dict[str, str]]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "catalog is not valid UTF-8 JSON", str(path)))
        return {}
    if not isinstance(value, dict):
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "catalog root must be an object", str(path)))
        return {}
    return value


def validate_package(root: Path) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if not root.is_absolute():
        root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        return {
            "schema_version": "goal-teams-release-engineer-validation-v2.45",
            "passed": False,
            "errors": [finding("E_V245_MEMBER_FILE_MISSING", "package root is missing or unsafe", str(root))],
        }
    resolved_root = root.resolve(strict=True)

    version_path = resolved_root / "VERSION"
    if version_path.is_file() and version_path.read_text(encoding="utf-8").strip() != "V2.45":
        errors.append(finding("E_V245_MEMBER_FILE_INVALID", "member VERSION must be V2.45", "VERSION"))

    for relative in REQUIRED_FILES:
        path = safe_relative(resolved_root, relative)
        if path is None or not path.is_file():
            errors.append(finding("E_V245_MEMBER_FILE_MISSING", "required member file is missing or unsafe", relative))

    index_path = resolved_root / "INDEX.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    if index_path.is_file() and index_path.stat().st_size > 4096:
        errors.append(finding("E_V245_MEMBER_INDEX_TOO_LARGE", "INDEX.md exceeds 4096 bytes", "INDEX.md"))
    for marker in INDEX_FIELDS:
        if marker not in index_text:
            errors.append(finding("E_V245_MEMBER_MARKER_MISSING", f"INDEX.md missing {marker}", "INDEX.md"))
    for reference in INDEX_REFERENCES:
        if f"`{reference}`" not in index_text:
            errors.append(finding("E_V245_MEMBER_REFERENCE_MISSING", f"INDEX.md missing route reference {reference}", "INDEX.md"))

    documentation_text = []
    for path in sorted([*resolved_root.rglob("*.md"), *resolved_root.rglob("*.txt")]):
        if path.is_symlink():
            errors.append(finding("E_V245_KIT_PATH_UNSAFE", "symlink markdown is forbidden", str(path.relative_to(resolved_root))))
            continue
        if path.stat().st_size > 64 * 1024:
            errors.append(finding("E_V245_MEMBER_INDEX_TOO_LARGE", "shipped markdown exceeds 64 KiB", str(path.relative_to(resolved_root))))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(finding("E_V245_MEMBER_FILE_INVALID", "markdown is not UTF-8", str(path.relative_to(resolved_root))))
            continue
        if "\r\n" in text:
            errors.append(finding("E_V245_MEMBER_FILE_INVALID", "markdown must use LF", str(path.relative_to(resolved_root))))
        documentation_text.append(text)
    combined = "\n".join(documentation_text)
    for marker in REQUIRED_MARKERS:
        if marker not in combined:
            errors.append(finding("E_V245_MEMBER_MARKER_MISSING", f"member contract missing marker: {marker}"))
    if "默认 member id" in combined:
        errors.append(finding("E_V245_MEMBER_IDENTITY_INVALID", "agent_type must not be a fixed project member_id"))
    if "delivery_outcome: accepted" in combined:
        errors.append(finding("E_V245_MEMBER_SELF_APPROVAL", "member must not self-assign accepted delivery outcome"))

    workflow_path = resolved_root / "workflow.md"
    workflow = workflow_path.read_text(encoding="utf-8") if workflow_path.is_file() else ""
    ordered_markers = (
        "check-evidence",
        "用户确认",
        "生成 draft plan",
        "plan approval",
        "compose",
        "execution approval",
        "execute",
        "独立完成审计",
    )
    cursor = -1
    for marker in ordered_markers:
        position = workflow.find(marker, cursor + 1)
        if position < 0:
            errors.append(finding("E_V245_MEMBER_WORKFLOW_ORDER", f"workflow missing or misordered marker: {marker}", "workflow.md"))
            break
        cursor = position

    catalog_path = resolved_root / "kits" / "catalog.json"
    catalog = load_catalog(catalog_path, errors) if catalog_path.is_file() else {}
    if catalog.get("schema_version") != "goal-teams-release-kit-catalog-v2.45":
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "unsupported catalog schema", "kits/catalog.json"))
    host_command = catalog.get("host_command")
    if (
        not isinstance(host_command, dict)
        or host_command.get("identity") != "goal-teams-release-host-v245"
        or host_command.get("invocation_schema") != "absolute_path action_id"
        or sorted(host_command.get("action_ids", []))
        != ["backup", "benchmark", "deploy", "rollback", "verify"]
    ):
        errors.append(
            finding(
                "E_V245_KIT_CATALOG_MISSING",
                "host_command identity/action schema is missing or drifted",
                "kits/catalog.json",
            )
        )

    toolchain_host = catalog.get("toolchain_host_command")
    expected_toolchain_actions = {
        f"{operation}-{kit_id}"
        for kit_id in {
            "java-maven-v1",
            "java-gradle-v1",
            "rust-cargo-v1",
            "go-modules-v1",
            "python-pip-v1",
            "python-uv-v1",
            "python-poetry-v1",
            "node-npm-v1",
            "node-pnpm-v1",
            "node-yarn-v1",
        }
        for operation in ("prefetch", "build")
    }
    if (
        not isinstance(toolchain_host, dict)
        or set(toolchain_host)
        != {
            "identity",
            "invocation_schema",
            "provenance_schema",
            "action_manifest",
            "action_ids",
        }
        or toolchain_host.get("identity")
        != "goal-teams-release-toolchain-host-v245"
        or toolchain_host.get("invocation_schema") != "absolute_path action_id"
        or toolchain_host.get("provenance_schema")
        != "goal-teams-toolchain-provenance-v2.45"
        or toolchain_host.get("action_manifest")
        != "plans/toolchain-actions-v1.json"
        or set(toolchain_host.get("action_ids", []))
        != expected_toolchain_actions
    ):
        errors.append(
            finding(
                "E_V245_KIT_CATALOG_MISSING",
                "toolchain host identity/action/provenance schema is missing or drifted",
                "kits/catalog.json",
            )
        )

    toolchain_manifest_path = (
        resolved_root / "kits" / "plans" / "toolchain-actions-v1.json"
    )
    try:
        toolchain_manifest = json.loads(
            toolchain_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        toolchain_manifest = {}
    toolchain_actions = toolchain_manifest.get("actions")
    expected_kit_matrix = {
        "java-maven-v1": ("java", "maven"),
        "java-gradle-v1": ("java", "gradle"),
        "rust-cargo-v1": ("rust", "cargo"),
        "go-modules-v1": ("go", "go-modules"),
        "python-pip-v1": ("python", "pip"),
        "python-uv-v1": ("python", "uv"),
        "python-poetry-v1": ("python", "poetry"),
        "node-npm-v1": ("node", "npm"),
        "node-pnpm-v1": ("node", "pnpm"),
        "node-yarn-v1": ("node", "yarn"),
    }
    expected_prefetch_inputs = [
        "approved_plan_path",
        "approved_plan_digest",
        "working_directory",
        "dependency_bundle",
        "dependency_requirements",
    ]
    expected_build_inputs = [
        *expected_prefetch_inputs,
        "artifact_path",
        "prefetch_receipt",
    ]
    expected_prefetch_receipt_fields = [
        "action_id",
        "action_manifest_sha256",
        "dependency_bundle_digest",
        "execution_id",
        "full_test_execution_count",
        "host_attestation",
        "host_executable_sha256",
        "network_policy",
        "observed_at",
        "plan_digest",
        "schema_version",
        "status",
    ]
    expected_build_receipt_fields = [
        "action_id",
        "action_manifest_sha256",
        "artifact_digest",
        "dependency_bundle_digest",
        "execution_id",
        "full_test_execution_count",
        "host_attestation",
        "host_executable_sha256",
        "network_policy",
        "observed_at",
        "plan_digest",
        "schema_version",
        "status",
    ]
    expected_execution_contract = {
        "approved_plan_path": "GOAL_TEAMS_RELEASE_PLAN_PATH",
        "approved_plan_digest": "GOAL_TEAMS_RELEASE_PLAN_DIGEST",
        "working_directory": "GOAL_TEAMS_RELEASE_PROJECT_ROOT",
        "dependency_bundle": "GOAL_TEAMS_RELEASE_DEPENDENCY_BUNDLE",
        "dependency_requirements": "GOAL_TEAMS_RELEASE_DEPENDENCY_REQUIREMENTS",
        "artifact_path": "GOAL_TEAMS_RELEASE_ARTIFACT_PATH",
        "prefetch_receipt": "GOAL_TEAMS_RELEASE_PREFETCH_RECEIPT",
        "action_receipt": "GOAL_TEAMS_RELEASE_TOOLCHAIN_RECEIPT",
        "receipt_schema": "goal-teams-toolchain-action-receipt-v2.45",
        "network_policy": {
            "prefetch": "prefetch_only",
            "build": "offline_required",
        },
        "full_test_execution_count": 0,
    }
    if (
        toolchain_manifest.get("schema_version")
        != "goal-teams-toolchain-action-manifest-v2.45"
        or toolchain_manifest.get("manifest_version") != "1.0.0"
        or toolchain_manifest.get("execution_contract")
        != expected_execution_contract
        or not isinstance(toolchain_actions, list)
        or len(toolchain_actions) != 20
        or {
            item.get("id")
            for item in toolchain_actions
            if isinstance(item, dict)
        }
        != expected_toolchain_actions
        or any(
            not isinstance(item, dict)
            or set(item)
            != {
                "id",
                "language",
                "build_tool",
                "phase",
                "strategy",
                "required_inputs",
                "network_policy",
                "full_test_execution_count",
                "required_receipt_fields",
            }
            or not isinstance(item.get("strategy"), str)
            or not item["strategy"]
            for item in (toolchain_actions or [])
        )
    ):
        errors.append(
            finding(
                "E_V245_KIT_CATALOG_MISSING",
                "toolchain action manifest must define the exact closed 20-action matrix",
                "kits/plans/toolchain-actions-v1.json",
            )
        )
    if isinstance(toolchain_actions, list):
        for item in toolchain_actions:
            if not isinstance(item, dict):
                continue
            phase, separator, kit_id = str(item.get("id", "")).partition("-")
            pair = expected_kit_matrix.get(kit_id)
            expected_inputs = (
                expected_prefetch_inputs
                if phase == "prefetch"
                else expected_build_inputs
            )
            expected_receipts = (
                expected_prefetch_receipt_fields
                if phase == "prefetch"
                else expected_build_receipt_fields
            )
            if (
                separator != "-"
                or pair is None
                or phase not in {"prefetch", "build"}
                or (item.get("language"), item.get("build_tool")) != pair
                or item.get("phase") != phase
                or item.get("required_inputs") != expected_inputs
                or item.get("required_receipt_fields") != expected_receipts
                or item.get("network_policy")
                != (
                    "prefetch_only"
                    if phase == "prefetch"
                    else "offline_required"
                )
                or item.get("full_test_execution_count") != 0
            ):
                errors.append(
                    finding(
                        "E_V245_KIT_CATALOG_MISSING",
                        "toolchain action tuple/input/receipt/network/test contract drifted",
                        f"kits/plans/toolchain-actions-v1.json#{item.get('id')}",
                    )
                )
    ids: set[str] = set()
    template_refs: list[str] = []
    common = catalog.get("common_templates", {})
    if isinstance(common, dict):
        template_refs.extend(value for value in common.values() if isinstance(value, str))
    if isinstance(toolchain_host, dict) and isinstance(
        toolchain_host.get("action_manifest"), str
    ):
        template_refs.append(toolchain_host["action_manifest"])
    adapters = catalog.get("language_adapters", [])
    if not isinstance(adapters, list):
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "language_adapters must be a list", "kits/catalog.json"))
        adapters = []
    observed_pairs = set()
    for entry in adapters:
        if not isinstance(entry, dict):
            errors.append(finding("E_V245_KIT_CATALOG_MISSING", "language adapter must be an object", "kits/catalog.json"))
            continue
        kit_id = entry.get("id")
        if not isinstance(kit_id, str) or not kit_id:
            errors.append(finding("E_V245_KIT_CATALOG_MISSING", "language adapter id is required", "kits/catalog.json"))
        elif kit_id in ids:
            errors.append(finding("E_V245_KIT_ID_DUPLICATE", "duplicate kit id", kit_id))
        else:
            ids.add(kit_id)
        if entry.get("lifecycle") != "approved":
            errors.append(finding("E_V245_KIT_NOT_APPROVED", "shipped language kit must be approved", str(kit_id)))
        observed_pairs.add((entry.get("language"), entry.get("build_tool")))
        for field in ("prefetch_template", "build_template"):
            if isinstance(entry.get(field), str):
                template_refs.append(entry[field])
            else:
                errors.append(finding("E_V245_KIT_CATALOG_MISSING", f"{field} is required", str(kit_id)))
        if (
            entry.get("prefetch_action") != f"prefetch-{kit_id}"
            or entry.get("build_action") != f"build-{kit_id}"
            or entry.get("prefetch_action") not in expected_toolchain_actions
            or entry.get("build_action") not in expected_toolchain_actions
        ):
            errors.append(
                finding(
                    "E_V245_KIT_CATALOG_MISSING",
                    "language adapter toolchain actions must be exact and catalog-defined",
                    str(kit_id),
                )
            )

    expected_pairs = {
        ("java", "maven"),
        ("java", "gradle"),
        ("rust", "cargo"),
        ("go", "go-modules"),
        ("python", "pip"),
        ("python", "uv"),
        ("python", "poetry"),
        ("node", "npm"),
        ("node", "pnpm"),
        ("node", "yarn"),
    }
    if observed_pairs != expected_pairs:
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "language/build tool matrix is incomplete", "kits/catalog.json"))
    environment_entries = catalog.get("environments", [])
    if not isinstance(environment_entries, list):
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "environments must be a list", "kits/catalog.json"))
        environment_entries = []
    environments = {
        item.get("name")
        for item in environment_entries
        if isinstance(item, dict)
    }
    if environments != {"local", "development", "test", "staging", "production"}:
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "environment matrix is incomplete", "kits/catalog.json"))
    for entry in environment_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("plan"), str):
            errors.append(finding("E_V245_KIT_CATALOG_MISSING", "environment plan is required", "kits/catalog.json"))
            continue
        template_refs.append(entry["plan"])

    surface_entries = catalog.get("surfaces", [])
    if not isinstance(surface_entries, list):
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "surfaces must be a list", "kits/catalog.json"))
        surface_entries = []
    surfaces = {
        item.get("name")
        for item in surface_entries
        if isinstance(item, dict)
    }
    if surfaces != {"application", "container-kubernetes", "wechat-miniprogram", "github-skill"}:
        errors.append(finding("E_V245_KIT_CATALOG_MISSING", "release surface matrix is incomplete", "kits/catalog.json"))
    for entry in surface_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("plan"), str):
            errors.append(finding("E_V245_KIT_CATALOG_MISSING", "surface plan is required", "kits/catalog.json"))
            continue
        template_refs.append(entry["plan"])

    for relative in sorted(set(template_refs)):
        path = safe_relative(resolved_root / "kits", relative)
        if path is None or not path.is_file():
            errors.append(finding("E_V245_KIT_PATH_UNSAFE", "catalog template path is missing or unsafe", relative))
            continue
        if path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            errors.append(finding("E_V245_RE_TEMPLATE_EXECUTION_FORBIDDEN", "kit templates must be non-executable", relative))
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                errors.append(finding("E_V245_KIT_CATALOG_MISSING", "referenced plan is not valid JSON", relative))
                continue
            if not isinstance(parsed, dict):
                errors.append(finding("E_V245_KIT_CATALOG_MISSING", "referenced plan must be an object", relative))
            continue
        if not text.startswith("#!/bin/bash\n"):
            errors.append(
                finding(
                    "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
                    "generated Bash template must use exact /bin/bash shebang",
                    relative,
                )
            )
        for pattern in FULL_TEST_PATTERNS:
            if pattern.search(text):
                errors.append(finding("E_V245_RE_FULL_TEST_EXECUTION_FORBIDDEN", "kit template must not run full tests", relative))
                break

    runtime_path = resolved_root / "runtime" / "release_member.py"
    runtime_text = runtime_path.read_text(encoding="utf-8") if runtime_path.is_file() else ""
    for command in ("check-evidence", "discover-scripts", "plan", "compose", "validate-bundle", "execute", "status"):
        if f'"{command}"' not in runtime_text:
            errors.append(finding("E_V245_MEMBER_SCRIPT_UNIMPLEMENTED", f"runtime command is not implemented: {command}", "runtime/release_member.py"))
    if "subprocess.run" not in runtime_text or "full_test_execution_count" not in runtime_text:
        errors.append(finding("E_V245_MEMBER_SCRIPT_UNIMPLEMENTED", "runtime execution/evidence boundaries are incomplete", "runtime/release_member.py"))

    errors = sorted(errors, key=lambda item: (item["path"], item["error_code"], item["message"]))
    return {
        "schema_version": "goal-teams-release-engineer-validation-v2.45",
        "package_root": str(resolved_root),
        "member_file_count": len([path for path in resolved_root.rglob("*") if path.is_file()]),
        "language_adapter_count": len(adapters),
        "environment_count": len(environments),
        "surface_count": len(surfaces),
        "passed": not errors,
        "errors": errors,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
    result.add_argument("--self-test", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    report = validate_package(args.package_root)
    if args.self_test:
        report["self_test"] = True
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
