#!/usr/bin/env python3
"""Check V1.94 member prompt package layout."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ROLES = [
    "requirements-analyst",
    "product",
    "backend",
    "frontend",
    "unit-test-designer",
    "unit-test-runner",
    "api-integration-test-designer",
    "api-integration-test-runner",
    "e2e-test-designer",
    "e2e-test-runner",
    "qa",
    "docs",
    "reviewer",
    "completion-auditor",
    "security",
    "performance",
    "refactor",
    "sqa",
]
REQUIRED_MEMBER_FILES = ["INDEX.md", "prompt.md", "template.md", "workflow.md", "scripts.md"]
SPECIALIST_ROLES = {"security", "performance", "refactor", "sqa"}
SPECIALIST_COMMON_MARKERS = (
    "L0 不可变原则",
    "L1 必需流程",
    "L2 可选优化",
    "coordination_depth: 1",
    "can_spawn_subagents: false",
    "can_dispatch: false",
    "dispatch_owner_agent_type: goal_lead",
    "handoff_mode: proposal_only",
    "proposed",
    "reviewed",
    "applied",
    "verified",
    "reverted",
    "holdout",
    "Lead",
)
SPECIALIST_ROLE_MARKERS = {
    "security": (
        "security_assessment",
        "E_V235_EXTERNAL_PORT_SCAN_AUTH_REQUIRED",
        "required_review_class=safety",
    ),
    "performance": (
        "performance_benchmark_proposal",
        "environment_digest",
        "candidate_digest",
        "current",
    ),
    "refactor": (
        "refactor_equivalence_proposal",
        "equivalence_contract",
        "rollback_boundary",
        "regression",
    ),
    "sqa": (
        "sqa_process_archive_proposal",
        "version_record",
        "index_ref",
        "classifications",
        "version_directory",
        "private_provenance",
    ),
}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def main() -> None:
    members_root = ROOT / "prompts" / "members"
    if not (members_root / "shared.md").is_file():
        fail("prompts/members/shared.md is required")
    for role in ROLES:
        role_dir = members_root / role
        if not role_dir.is_dir():
            fail(f"Missing member directory: {role_dir}")
        for filename in REQUIRED_MEMBER_FILES:
            path = role_dir / filename
            if not path.is_file():
                fail(f"Missing member package file: {path}")
            text = path.read_text(encoding="utf-8")
            if len(text.strip()) < 40:
                fail(f"Member package file is too small: {path}")
            if filename == "INDEX.md" and any(f"`{name}`" not in text for name in ("prompt.md", "template.md", "workflow.md", "scripts.md")):
                fail(f"Member index must route all progressive files: {path}")
            if filename == "scripts.md" and "scripts/" not in text:
                fail(f"Member scripts file must reference deterministic scripts: {path}")
        if role in SPECIALIST_ROLES:
            files = [role_dir / filename for filename in REQUIRED_MEMBER_FILES]
            combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
            for marker in SPECIALIST_COMMON_MARKERS + SPECIALIST_ROLE_MARKERS[role]:
                if marker not in combined:
                    fail(f"Specialist package {role} missing protocol marker: {marker}")
            prompt_size = (role_dir / "prompt.md").stat().st_size
            package_size = sum(path.stat().st_size for path in files)
            if prompt_size > 3072:
                fail(f"Specialist prompt exceeds 3072-byte budget: {role}={prompt_size}")
            if package_size > 10240:
                fail(f"Specialist package exceeds 10240-byte budget: {role}={package_size}")
        flat_file = members_root / f"{role}.md"
        if flat_file.exists():
            fail(f"Flat member prompt should be migrated into directory package: {flat_file}")
    print(
        f"Member layout validation passed for {len(ROLES)} roles; "
        "V2.35 specialist priority/capability/byte budgets passed."
    )


if __name__ == "__main__":
    main()
