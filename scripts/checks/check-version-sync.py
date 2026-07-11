#!/usr/bin/env python3
"""Check version and startup identity synchronization."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

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


V233_PUBLICATION_FILES = {
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


def check_v233_publication_sync(version: str) -> None:
    """Require V2.33's bilingual publication/history split only for V2.33.

    Keeping this gate version-conditional lets older installed packages remain
    verifiable while making a V2.33 release fail closed if it restores the
    publication list or changelog to either README.
    """
    if version != "V2.33":
        return

    missing = [path for path in V233_PUBLICATION_FILES.values() if not (ROOT / path).is_file()]
    if missing:
        fail("V2.33 publication/history files are missing: " + ", ".join(missing))

    required_markers = {
        "release_zh": ("发布内容", version),
        "release_en": ("Release Contents", version),
        "history_zh": ("版本变更记录", version),
        "history_en": ("Change History", version),
    }
    for key, markers in required_markers.items():
        path = V233_PUBLICATION_FILES[key]
        text = read(path)
        for marker in markers:
            if marker not in text:
                fail(f"{path} missing V2.33 publication/history marker {marker!r}")
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
        "README.md": (V233_PUBLICATION_FILES["release_zh"], V233_PUBLICATION_FILES["history_zh"]),
        "README.en.md": (V233_PUBLICATION_FILES["release_en"], V233_PUBLICATION_FILES["history_en"]),
    }
    for path, links in readme_links.items():
        text = read(path)
        for link in links:
            if link not in text:
                fail(f"{path} must link to V2.33 split publication/history document {link}")
    if re.search(r"^## 发布内容\s*$", read("README.md"), flags=re.M):
        fail("README.md must not contain the V2.33 publication-content section")
    if re.search(r"^## (?:Release Contents|发布内容)\s*$", read("README.en.md"), flags=re.M):
        fail("README.en.md must not contain the V2.33 publication-content section")


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
    unexpected_skill_versions = sorted(found for found in skill_versions if found != version)
    if unexpected_skill_versions:
        fail(
            "SKILL.md version strings must match VERSION "
            f"{version!r}; unexpected: {', '.join(unexpected_skill_versions)}"
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

    check_v233_publication_sync(version)

    openai = read("agents/openai.yaml")
    if f'Goal Teams {version}' not in openai:
        fail("agents/openai.yaml display_name is not synchronized")
    if f"使用 $goal-teams {version}" not in openai:
        fail("agents/openai.yaml default prompt is not synchronized")

    print(f"Version synchronization passed for {version}.")


if __name__ == "__main__":
    main()
