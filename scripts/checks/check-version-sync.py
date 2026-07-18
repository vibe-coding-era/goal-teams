#!/usr/bin/env python3
"""Validate development/candidate version projections derived from VERSION.

Stable release identity is deliberately outside this local checker: it must be
reconstructed by the independent live release auditor.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = "V2.5"
LEGACY = "V2.3"
README_START = "<!-- goal-teams-release:start -->"
README_END = "<!-- goal-teams-release:end -->"
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CURRENT_RELEASE_RE = re.compile(
    r"(?:Current release|当前发行)[^\n]*?(V[0-9]+\.[0-9]+)"
)
CURRENT_PRODUCT_RE = re.compile(
    r"(?:Current version|当前版本)[^\n]*?(V[0-9]+\.[0-9]+)"
)
STALE_ACTIVE_CURRENT_PATTERNS = (
    re.compile(r"我是 Goal Teams Lead V2\.(?:38|39)。"),
    re.compile(r"当前\s+`?goal-teams-self-release-v2\.(?:38|39)"),
    re.compile(r"当前 self-release refs 指向 V2\.(?:38|39) Profile"),
    re.compile(
        r"当前详细专项门见 `references/profiles/"
        r"goal-teams-self-release-v2\.(?:38|39)\.md`"
    ),
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def require_supported_python() -> None:
    if sys.version_info < (3, 11):
        fail(
            "check-version-sync requires Python 3.11+; set PYTHON to an "
            "explicit compatible interpreter before running release commands"
        )


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def product_version() -> str:
    product = read("VERSION").strip()
    if not VERSION_RE.fullmatch(product):
        fail(f"VERSION must match {VERSION_RE.pattern}: {product!r}")
    return product


def profile_identity(product: str) -> tuple[str, str]:
    suffix = product.removeprefix("V").lower()
    profile = f"goal-teams-self-release-v{suffix}"
    return profile, f"references/profiles/{profile}.md"


def expected_release_block(path: str, version: str) -> str:
    tag = version.lower()
    if path == "README.md":
        label = "当前发行："
        github_label = "GitHub 发行页"
        current_label = "发行说明"
    elif path == "README.en.md":
        label = "Current release: "
        github_label = "GitHub Release"
        current_label = "release/current/README.md"
    else:
        fail(f"unsupported root README projection: {path}")
    return (
        f"{README_START}\n"
        f"{label}**{version}** · "
        f"[{github_label}](https://github.com/vibe-coding-era/goal-teams/releases/tag/{tag}) "
        f"· [{current_label}](release/current/README.md)\n"
        f"{README_END}"
    )


def read_release_block(path: str, expected_version: str) -> dict[str, str]:
    text = read(path)
    if text.count(README_START) != 1 or text.count(README_END) != 1:
        fail(f"{path} must contain exactly one controlled release marker block")
    start = text.index(README_START)
    end = text.index(README_END, start) + len(README_END)
    block = text[start:end]
    if block != expected_release_block(path, expected_version):
        fail(f"{path} controlled release block does not match {expected_version}")
    release_versions = set(CURRENT_RELEASE_RE.findall(text))
    if release_versions != {expected_version}:
        fail(
            f"{path} current release markers must be exactly {expected_version}: "
            f"{sorted(release_versions)}"
        )
    tag = expected_version.lower()
    return {
        "version": expected_version,
        "release_url": (
            "https://github.com/vibe-coding-era/goal-teams/releases/tag/" + tag
        ),
        "current_url": "release/current/README.md",
    }


def validate_runtime_identity(product: str) -> tuple[str, str]:
    profile, profile_path = profile_identity(product)
    startup = f"我是 Goal Teams Lead {product}。"
    compatibility = f"我是 Goal Teams Leader {product}，使用 Goal + Plan 模式帮你完成规划、执行和交付"
    required_identity = {
        "SKILL.md": (product, startup, compatibility, CORE, LEGACY, profile, profile_path),
        "agents/openai.yaml": (product, startup),
        "prompts/lead/core.md": (product, startup, compatibility),
        "examples/mini-goal-run/README.md": (product, startup),
        "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md": (product, startup),
    }
    for path, markers in required_identity.items():
        text = read(path)
        for marker in markers:
            if marker not in text:
                fail(f"{path} missing current runtime identity marker: {marker}")

    active_runtime_markers = {
        "references/runtime/01-v2-36-core-trust.md": (
            startup,
            f"当前 `{profile}`",
            profile_path,
            "V2.39/V2.38 Profile 只用于历史 replay",
        ),
        "references/runtime/03-goal-loop.md": (
            startup,
            f"{product} 继续按 V2.38-compatible prompt-cache manifest",
            f"当前 self-release refs 指向 {product} Profile",
            "V2.39/V2.38 只读 replay",
        ),
    }
    for path, markers in active_runtime_markers.items():
        text = read(path)
        for marker in markers:
            if marker not in text:
                fail(f"{path} missing active runtime identity marker: {marker}")
        for pattern in STALE_ACTIVE_CURRENT_PATTERNS:
            if pattern.search(text):
                fail(
                    f"{path} promotes a V2.39/V2.38 replay identity to current: "
                    f"{pattern.pattern}"
                )

    skill = read("SKILL.md")
    for marker in (
        "references/prompt-cache-manifest.json",
        "requirements-analyst/INDEX.md",
        "product/INDEX.md",
        "members/<role>/INDEX.md",
        "Profile 仅用于历史 replay",
    ):
        if marker not in skill:
            fail(f"SKILL.md missing current route marker: {marker}")

    profile_text = read(profile_path)
    if profile not in profile_text or product not in profile_text:
        fail("current self-release profile identity mismatch")

    prompt_manifest = json.loads(read("references/prompt-cache-manifest.json"))
    active_refs = prompt_manifest.get("routes", {}).get(
        "self_release_execution_repository", {}
    ).get("ordered_refs", [])
    if profile_path not in active_refs:
        fail("prompt-cache manifest does not route current self-release Profile")
    stale_active = [
        path
        for path in active_refs
        if path.startswith("references/profiles/goal-teams-self-release-")
        and path != profile_path
    ]
    if stale_active:
        fail(f"active self-release route contains replay-only Profiles: {stale_active}")
    return profile, profile_path


def validate_package_boundary(product: str) -> None:
    manifest = read("scripts/install/package-manifest.txt")
    if f"product {product}, core policy {CORE}, legacy data schema {LEGACY}" not in manifest:
        fail("package manifest header does not match VERSION/core/legacy identity")
    for marker in (
        "docs/",
        "develops/",
        "GoalTeams-PRD-V2.",
        "GoalTeamsWork-",
        "v2.34-completion",
        "v2.35-release-summary",
        "v2.36-release-summary",
    ):
        if marker in manifest:
            fail(f"package manifest contains history/local marker: {marker}")
    for marker in (
        "file release/current/README.md",
        "file release/current/manifest.json",
        "prefix prompts/",
        "prefix references/",
    ):
        if marker not in manifest:
            fail(f"package manifest missing current runtime marker: {marker}")

    tracked_local = ""
    if (ROOT / ".git").exists():
        tracked_local = subprocess.run(
            ["git", "ls-files", "docs", "develops", "release/versions"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    elif any((ROOT / path).exists() for path in ("docs", "develops", "release/versions")):
        fail("gitless install package contains local-only workspace data")
    if tracked_local:
        fail("docs/develops/release versions must be local-only")


def validate_release_projection(expected_version: str, product: str) -> None:
    zh_projection = read_release_block("README.md", expected_version)
    en_projection = read_release_block("README.en.md", expected_version)
    if zh_projection != en_projection:
        fail("README.md and README.en.md controlled release semantics differ")
    for path in ("README.md", "README.en.md"):
        product_versions = set(CURRENT_PRODUCT_RE.findall(read(path)))
        if product_versions != {product}:
            fail(
                f"{path} current product markers must be exactly {product}: "
                f"{sorted(product_versions)}"
            )

    release_note = read("release/current/README.md")
    if f"# Goal Teams {expected_version} Release" not in release_note:
        fail("release/current/README.md does not match projected release version")
    for marker in ("Tokens consumed", "Tokens 消耗", "Cache hit rate", "Cache 命中率", "Unavailable", "未获取到"):
        if marker not in release_note:
            fail(f"release/current/README.md missing honest telemetry marker: {marker}")

    release = json.loads(read("release/current/manifest.json"))
    if release.get("product_version") != expected_version:
        fail("release/current manifest product version mismatch")
    if release.get("schema_version") != f"goal-teams-release-manifest-{expected_version.lower()}":
        fail("release/current manifest schema version mismatch")
    if release.get("docs_policy") != "local-only":
        fail("release/current manifest docs policy mismatch")
    expected_cache_state = {
        "structural_delivery_state": "passed",
        "host_integration_state": "unavailable",
        "live_cache_validation_state": "not_authorized",
        "request_hit_rate_support_state": "unavailable",
    }
    if release.get("cache_evidence") != expected_cache_state:
        fail("release/current manifest cache evidence mismatch")
    if release.get("claim_scope") != "structural_governance":
        fail("release/current manifest claim scope mismatch")
    telemetry = release.get("completion_telemetry", {})
    for field in ("tokens_consumed", "cache_hit_rate"):
        record = telemetry.get(field)
        if record != {
            "status": "unavailable",
            "value": None,
            "display_zh": "未获取到",
            "display_en": "Unavailable",
        }:
            fail(f"release/current manifest {field} must be explicitly unavailable")
    if telemetry.get("claim_policy") != "no_estimation_without_trusted_host_usage_evidence":
        fail("release/current manifest telemetry claim policy mismatch")


def validate_candidate_commit(commit: str | None) -> None:
    if commit is None:
        return
    if not COMMIT_RE.fullmatch(commit):
        fail("--candidate-commit must be an exact lowercase 40-hex commit")
    if (ROOT / ".git").exists():
        proc = subprocess.run(
            ["git", "cat-file", "-t", commit],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or proc.stdout.strip() != "commit":
            fail("--candidate-commit does not resolve to a commit object")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate VERSION-derived development or candidate identity."
    )
    parser.add_argument(
        "--mode",
        choices=("development", "candidate", "stable"),
        default="candidate",
    )
    parser.add_argument(
        "--published-version",
        help="Required in development mode; exact live-published version to project in README/current.",
    )
    parser.add_argument(
        "--candidate-commit",
        help="Optional frozen 40-hex commit identity for candidate mode.",
    )
    return parser.parse_args()


def main() -> None:
    require_supported_python()
    args = parse_args()
    product = product_version()
    if args.mode == "stable":
        print(
            "[DELEGATED] stable identity requires scripts/release/audit-release.py "
            f"live audit for {product}; local version sync cannot pass it."
        )
        raise SystemExit(2)

    validate_runtime_identity(product)
    validate_package_boundary(product)
    if args.mode == "development":
        published = args.published_version
        if published is None or not VERSION_RE.fullmatch(published):
            fail("development mode requires --published-version V<major>.<minor>")
        validate_release_projection(published, product)
    else:
        if args.published_version is not None:
            fail("--published-version is only valid in development mode")
        validate_candidate_commit(args.candidate_commit)
        validate_release_projection(product, product)

    print(
        "Version synchronization passed: "
        f"mode={args.mode}, product={product}, core={CORE}, legacy={LEGACY}, docs=local-only."
    )


if __name__ == "__main__":
    main()
