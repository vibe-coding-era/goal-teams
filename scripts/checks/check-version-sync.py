#!/usr/bin/env python3
"""Check V2.39 identity, profile routing, and local-doc release boundaries."""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCT, CORE, LEGACY = "V2.39", "V2.5", "V2.3"
PROFILE = "goal-teams-self-release-v2.39"

def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)

def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")

def main() -> None:
    if read("VERSION").strip() != PRODUCT:
        fail(f"VERSION must be {PRODUCT}")
    startup = f"我是 Goal Teams Lead {PRODUCT}。"
    for path in ("SKILL.md", "README.md", "README.en.md", "agents/openai.yaml", "prompts/lead/core.md", "examples/mini-goal-run/README.md", "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md"):
        text = read(path)
        if PRODUCT not in text or startup not in text:
            fail(f"{path} missing current product/startup identity")
    skill = read("SKILL.md")
    for marker in (CORE, LEGACY, PROFILE, "references/profiles/goal-teams-self-release-v2.39.md", "references/prompt-cache-manifest.json", "requirements-analyst/INDEX.md", "product/INDEX.md", "members/<role>/INDEX.md"):
        if marker not in skill:
            fail(f"SKILL.md missing current route marker: {marker}")
    profile = read("references/profiles/goal-teams-self-release-v2.39.md")
    if PROFILE not in profile or PRODUCT not in profile:
        fail("current self-release profile identity mismatch")
    manifest = read("scripts/install/package-manifest.txt")
    for marker in ("docs/", "develops/", "GoalTeams-PRD-V2.", "GoalTeamsWork-", "v2.34-completion", "v2.35-release-summary", "v2.36-release-summary"):
        if marker in manifest:
            fail(f"package manifest contains history/local marker: {marker}")
    for marker in ("file release/current/README.md", "file release/current/manifest.json", "prefix prompts/", "prefix references/"):
        if marker not in manifest:
            fail(f"package manifest missing current runtime marker: {marker}")
    tracked_docs = ""
    if (ROOT / ".git").exists():
        tracked_docs = subprocess.run(["git", "ls-files", "docs", "develops", "release/versions"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    elif any((ROOT / path).exists() for path in ("docs", "develops", "release/versions")):
        fail("gitless install package contains local-only workspace data")
    if tracked_docs:
        fail("docs/develops/release versions must be local-only")
    release = json.loads(read("release/current/manifest.json"))
    if release.get("product_version") != PRODUCT or release.get("docs_policy") != "local-only":
        fail("current release manifest mismatch")
    expected_cache_state = {
        "structural_delivery_state": "passed",
        "host_integration_state": "unavailable",
        "live_cache_validation_state": "not_authorized",
        "request_hit_rate_support_state": "unavailable",
    }
    if release.get("cache_evidence") != expected_cache_state or release.get("claim_scope") != "structural_governance":
        fail("current release manifest cache evidence/claim scope mismatch")
    if re.search(r"references/profiles/goal-teams-self-release-v2\.(?:36|37)\.md", skill):
        fail("SKILL routes to stale self-release profile")
    if "V2.38 Profile 仅用于历史 replay" not in skill:
        fail("SKILL must keep V2.38 profile replay-only boundary")
    print(f"Version synchronization passed: product={PRODUCT}, core={CORE}, legacy={LEGACY}, docs=local-only.")

if __name__ == "__main__":
    main()
