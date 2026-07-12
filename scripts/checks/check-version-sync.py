#!/usr/bin/env python3
"""Check version and startup identity synchronization."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERAL_CORE_POLICY_VERSION = "V2.5"
LEGACY_DATA_SCHEMA_VERSION = "V2.3"
CORE_POLICY_PROFILE = "goal-teams-core-v2.5"
SELF_RELEASE_POLICY_PROFILE = "goal-teams-self-release-v2.36"

VERSION_FILES = [
    "SKILL.md",
    "goal-teams.md",
    "references/goal-teams-runtime.md",
    "prompts/lead/core.md",
    "agents/openai.yaml",
    "README.md",
    "README.en.md",
    "examples/mini-goal-run/README.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md",
]


SPLIT_PUBLICATION_FILES = {
    "release_zh": "docs/release-contents.md",
    "release_en": "docs/release-contents.en.md",
    "history_zh": "docs/change-history.md",
    "history_en": "docs/change-history.en.md",
}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def version_at_least(version: str, floor: tuple[int, int]) -> bool:
    match = re.fullmatch(r"V(\d+)\.(\d+)", version)
    return bool(match and (int(match.group(1)), int(match.group(2))) >= floor)


def check_split_publication_sync(version: str) -> None:
    """Require the bilingual publication/history split for V2.33 and later.

    Keeping this gate version-conditional lets older installed packages remain
    verifiable while making current releases fail closed if they restore the
    publication list or changelog to either README.
    """
    if not version_at_least(version, (2, 33)):
        return

    missing = [path for path in SPLIT_PUBLICATION_FILES.values() if not (ROOT / path).is_file()]
    if missing:
        fail(f"{version} publication/history files are missing: " + ", ".join(missing))

    required_markers = {
        "release_zh": ("发布内容", version),
        "release_en": ("Release Contents", version),
        "history_zh": ("版本变更记录", version),
        "history_en": ("Change History", version),
    }
    for key, markers in required_markers.items():
        path = SPLIT_PUBLICATION_FILES[key]
        text = read(path)
        for marker in markers:
            if marker not in text:
                fail(f"{path} missing {version} publication/history marker {marker!r}")
        roadmap_path = "docs/后续版本规划 V3.3-3.5.md"
        if roadmap_path not in text:
            fail(f"{path} must identify the local-only planning source {roadmap_path}")
        if any(
            "后续版本规划" in line and re.search(r"\[[^\]]+\]\([^)]+\)", line)
            for line in text.splitlines()
        ):
            fail(
                f"{path} must not link to the untracked local planning source; "
                "use a non-clickable code path"
            )

    readme_links = {
        "README.md": (SPLIT_PUBLICATION_FILES["release_zh"], SPLIT_PUBLICATION_FILES["history_zh"]),
        "README.en.md": (SPLIT_PUBLICATION_FILES["release_en"], SPLIT_PUBLICATION_FILES["history_en"]),
    }
    for path, links in readme_links.items():
        text = read(path)
        for link in links:
            if link not in text:
                fail(f"{path} must link to {version} split publication/history document {link}")
    if re.search(r"^## 发布内容\s*$", read("README.md"), flags=re.M):
        fail("README.md must not contain the split publication-content section")
    if re.search(r"^## (?:Release Contents|发布内容)\s*$", read("README.en.md"), flags=re.M):
        fail("README.en.md must not contain the split publication-content section")


def check_v234_compatibility_assets(version: str) -> None:
    if not version_at_least(version, (2, 34)):
        return
    required_files = (
        "scripts/v23/v234_state.py",
        "docs/v2.34-completion.md",
        "docs/v2.34-completion.en.md",
    )
    missing = [path for path in required_files if not (ROOT / path).is_file()]
    if missing:
        fail(f"{version} V2.34 compatibility assets are missing: " + ", ".join(missing))
    required_markers = {
        ".gitignore": ("/GoalTeamsWork-*/", "/.goalteams-state/", "/.goalteams-quarantine/"),
        "scripts/install/package-manifest.txt": ("prefix docs/archive/",),
    }
    for path, markers in required_markers.items():
        text = read(path)
        for marker in markers:
            if marker not in text:
                fail(f"{path} missing V2.34 compatibility marker {marker!r}")
    if "GoalTeamsWork" in read("scripts/install/package-manifest.txt"):
        fail("package manifest must not include GoalTeamsWork process bundles")


def check_v235_protocol_sync(version: str) -> None:
    if not version_at_least(version, (2, 35)):
        return
    required_files = (
        "references/rules-project-sizing.md",
        "references/rules-specialists.md",
        "references/test-case-assertion-protocol.md",
        "scripts/v23/v235_policy.py",
        "scripts/v23/version_binding.py",
        "scripts/checks/validate-test-case-contract.py",
        "scripts/validate-test-case-contract.py",
        "schemas/v2.35/project-route.schema.json",
        "schemas/v2.35/test-case.schema.json",
        "schemas/v2.35/version-binding.schema.json",
        "docs/v2.35-release-summary.md",
        "docs/v2.35-release-summary.en.md",
    )
    missing = [path for path in required_files if not (ROOT / path).is_file()]
    if missing:
        fail(f"{version} protocol files are missing: " + ", ".join(missing))
    for role in ("security", "performance", "refactor", "sqa"):
        for name in ("prompt.md", "template.md", "workflow.md", "scripts.md"):
            relative = f"prompts/members/{role}/{name}"
            if not (ROOT / relative).is_file():
                fail(f"{version} specialist package file is missing: {relative}")
        if not (ROOT / "subagents" / f"goal-{role}.toml").is_file():
            fail(f"{version} specialist subagent is missing: goal-{role}.toml")
    skill = read("SKILL.md")
    for marker in (
        "references/rules-project-sizing.md",
        "references/rules-specialists.md",
    ):
        if marker not in skill:
            fail(f"SKILL.md missing V2.35 conditional route {marker!r}")
    for path in ("docs/v2.35-release-summary.md", "docs/v2.35-release-summary.en.md"):
        text = read(path)
        if "V2.35" not in text or "Completion Audit" not in text:
            fail(f"{path} missing V2.35 pre-audit identity")
        if re.search(r"Completion Audit.{0,20}(?:passed|通过)", text, flags=re.I | re.S):
            fail(f"{path} must not claim the graph-external Completion Audit passed")
    manifest = read("scripts/install/package-manifest.txt")
    for path in ("docs/v2.35-release-summary.md", "docs/v2.35-release-summary.en.md"):
        if f"file {path}" not in manifest:
            fail(f"package manifest missing {path}")


def check_v236_protocol_sync(version: str) -> None:
    if not version_at_least(version, (2, 36)):
        return
    required_files = (
        "references/goal-teams-core-v2.5.md",
        "references/profiles/goal-teams-self-release-v2.36.md",
        "scripts/v23/v236_security.py",
        "scripts/v23/v236_trust.py",
        "scripts/v23/v236_acceptance.py",
        "schemas/v2.36/project-route.schema.json",
        "schemas/v2.36/policy-profile-selector.schema.json",
        "schemas/v2.36/execution-contract.schema.json",
        "schemas/v2.36/protected-git-tree-snapshot.schema.json",
        "schemas/v2.36/agent-host-attestation.schema.json",
        "schemas/v2.36/attested-identity-registry.schema.json",
        "schemas/v2.36/host-route-receipt.schema.json",
        "schemas/v2.36/persistent-challenge-state.schema.json",
        "schemas/v2.36/acceptance-binding.schema.json",
        "schemas/v2.36/acceptance-core-binding.schema.json",
        "schemas/v2.36/acceptance-input-snapshot.schema.json",
        "docs/v2.36-release-summary.md",
        "docs/v2.36-release-summary.en.md",
    )
    missing = [path for path in required_files if not (ROOT / path).is_file()]
    if missing:
        fail(f"{version} protocol files are missing: " + ", ".join(missing))

    version_markers = {
        "SKILL.md": (
            version,
            GENERAL_CORE_POLICY_VERSION,
            LEGACY_DATA_SCHEMA_VERSION,
            CORE_POLICY_PROFILE,
            SELF_RELEASE_POLICY_PROFILE,
            "references/goal-teams-core-v2.5.md",
            "references/profiles/goal-teams-self-release-v2.36.md",
        ),
        "README.md": (version, GENERAL_CORE_POLICY_VERSION, LEGACY_DATA_SCHEMA_VERSION),
        "README.en.md": (version, GENERAL_CORE_POLICY_VERSION, LEGACY_DATA_SCHEMA_VERSION),
        "references/goal-teams-core-v2.5.md": (
            CORE_POLICY_PROFILE,
            "gate_profile",
            "`lite`",
            "`standard`",
            "显式提供时必须与派生值完全一致",
            "goal-teams-v2.36-acceptance-binding-v1",
            "acceptance-input snapshot",
            "execution-contract digest",
        ),
        "references/profiles/goal-teams-self-release-v2.36.md": (
            SELF_RELEASE_POLICY_PROFILE,
            "52",
            "iteration 9",
            "iteration 11",
            "c91e33737cc13c68bb5cb34c572fa05e7849f1e4",
        ),
        "prompts/packets/harness-contract.md": (
            "v236_execution_contract",
            "v236_gate_checks",
            "completion_audit",
        ),
        "prompts/members/completion-auditor/template.md": (
            "acceptance_input_snapshot_sha256",
            "execution_contract_sha256",
            "v236_gate_results",
        ),
    }
    for path, markers in version_markers.items():
        text = read(path)
        for marker in markers:
            if marker not in text:
                fail(f"{path} missing V2.36 version/profile marker {marker!r}")

    runtime_text = read("references/goal-teams-runtime.md")
    if "我是 Goal Teams Lead V2.35" in runtime_text:
        fail("references/goal-teams-runtime.md contains stale V2.35 startup identity")

    tool_text = read("scripts/v23/goalteams_v23.py")
    trusted_base = "c91e33737cc13c68bb5cb34c572fa05e7849f1e4"
    if f'V236_GOAL_TEAMS_TRUSTED_RELEASE_BASE = "{trusted_base}"' not in tool_text:
        fail("V2.36 runtime missing immutable accepted V2.35 release base")
    if re.search(r"def _dispatch\([^)]*v236_host_context", tool_text, flags=re.S):
        fail("candidate _dispatch must not expose a V2.36 host context success path")
    if "E_V236_HOST_ADAPTER_REQUIRED" not in tool_text:
        fail("candidate runtime must fail closed at the external host boundary")

    trust_text = read("scripts/v23/v236_trust.py")
    if "acceptance_eligible=True" in trust_text:
        fail("candidate trust helpers must never grant V2.36 acceptance authority")
    for marker in (
        "def _host_adapter_required()",
        "host_reference_only=True",
        "E_V236_HOST_ADAPTER_REQUIRED",
    ):
        if marker not in trust_text:
            fail(f"V2.36 trust boundary missing fail-closed marker {marker!r}")

    rules_loop = read("references/rules-loop.md")
    for self_release_marker in (".goalteams-candidates/<candidate_id>", "iteration 11"):
        if self_release_marker in rules_loop:
            fail(
                "references/rules-loop.md must not retain self-release-only marker "
                f"{self_release_marker!r}"
            )

    summaries = ("docs/v2.36-release-summary.md", "docs/v2.36-release-summary.en.md")
    for path in summaries:
        text = read(path)
        for marker in (version, GENERAL_CORE_POLICY_VERSION, LEGACY_DATA_SCHEMA_VERSION, "Completion Audit"):
            if marker not in text:
                fail(f"{path} missing V2.36 pre-audit marker {marker!r}")
        if re.search(r"Completion Audit.{0,20}(?:passed|通过)", text, flags=re.I | re.S):
            fail(f"{path} must not claim the graph-external Completion Audit passed")

    manifest = read("scripts/install/package-manifest.txt")
    for path in summaries:
        if f"file {path}" not in manifest:
            fail(f"package manifest missing {path}")


def main() -> None:
    version = read("VERSION").strip()
    if not re.fullmatch(r"V\d+\.\d+", version):
        fail(f"VERSION must look like Vx.y, got {version!r}")

    startup = f"我是 Goal Teams Lead {version}。"
    compatibility_marker = (
        f"我是 Goal Teams Leader {version}，使用 Goal + Plan 模式帮你完成规划、执行和交付，"
        "并使用 Harness + SPEC 做为过程与结果产物的约束："
    )
    skill_versions = set(re.findall(r"\bV\d+(?:\.\d+)+\b", read("SKILL.md")))
    allowed_skill_versions = {version, GENERAL_CORE_POLICY_VERSION, LEGACY_DATA_SCHEMA_VERSION}
    missing_skill_versions = sorted(allowed_skill_versions - skill_versions)
    if missing_skill_versions:
        fail("SKILL.md missing required version identities: " + ", ".join(missing_skill_versions))
    unexpected_skill_versions = sorted(skill_versions - allowed_skill_versions)
    if unexpected_skill_versions:
        fail(
            "SKILL.md version strings must be product/core/legacy identities "
            f"{sorted(allowed_skill_versions)!r}; unexpected: {', '.join(unexpected_skill_versions)}"
        )
    for path in VERSION_FILES:
        text = read(path)
        if version not in text:
            fail(f"{path} does not mention current version {version}")
        if startup not in text:
            fail(f"{path} missing current startup line")
        if path not in {"SKILL.md", "prompts/lead/core.md"} and compatibility_marker in text:
            fail(f"{path} exposes the non-user-visible compatibility marker as startup text")

    for path in ("SKILL.md", "prompts/lead/core.md"):
        if compatibility_marker not in read(path):
            fail(f"{path} missing the explicitly non-user-visible compatibility marker")

    history_policy_surfaces = {
        "agents/openai.yaml": "只有缺少历史资料会改变执行时才询问",
        "goal-teams.md": "只有缺少历史资料会改变执行时",
        "prompts/lead/core.md": "只有缺少历史资料会改变执行时才询问",
        "references/goal-teams-runtime.md": "只有历史资料缺失会改变方案时才询问",
    }
    for path, marker in history_policy_surfaces.items():
        if marker not in read(path):
            fail(f"{path} missing the conditional history-input policy")

    check_split_publication_sync(version)
    check_v234_compatibility_assets(version)
    check_v235_protocol_sync(version)
    check_v236_protocol_sync(version)

    openai = read("agents/openai.yaml")
    if f'Goal Teams {version}' not in openai:
        fail("agents/openai.yaml display_name is not synchronized")
    if f"使用 $goal-teams {version}" not in openai:
        fail("agents/openai.yaml default prompt is not synchronized")

    print(f"Version synchronization passed for {version}.")


if __name__ == "__main__":
    main()
