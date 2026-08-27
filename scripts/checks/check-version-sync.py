#!/usr/bin/env python3
"""Validate development/candidate version projections derived from VERSION.

Stable release identity is deliberately outside this local checker: it must be
reconstructed by the independent live release auditor.
"""

from __future__ import annotations

import argparse
import hashlib
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
REPLAY_PROFILE_LINE = "V2.47 及更早 Profile 只用于历史 replay"
REPLAY_RUNTIME_LINE = "V2.47 及更早只读 replay"
V262_README_SHA256 = {
    "README.md": "b41fe4de55832b561b077fff0a4c41659bc11058c560ba6b01f982003c6089af",
    "README.en.md": "b31c0a6d58375282f0ec60e06d74bb7a33179828e0f2def65c4c5c3743f33ec3",
}


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


def expected_release_block(
    path: str, displayed_version: str, release_tag_version: str | None = None
) -> str:
    tag = (release_tag_version or displayed_version).lower()
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
        f"{label}**{displayed_version}** · "
        f"[{github_label}](https://github.com/vibe-coding-era/goal-teams/releases/tag/{tag}) "
        f"· [{current_label}](release/current/README.md)\n"
        f"{README_END}"
    )


def read_release_block(
    path: str, expected_version: str, displayed_version: str | None = None
) -> dict[str, str]:
    displayed = displayed_version or expected_version
    text = read(path)
    if text.count(README_START) != 1 or text.count(README_END) != 1:
        fail(f"{path} must contain exactly one controlled release marker block")
    start = text.index(README_START)
    end = text.index(README_END, start) + len(README_END)
    block = text[start:end]
    if block != expected_release_block(path, displayed, expected_version):
        fail(f"{path} controlled release block does not match the user-owned projection")
    release_versions = set(CURRENT_RELEASE_RE.findall(text))
    if release_versions != {displayed}:
        fail(
            f"{path} current release markers must be exactly {displayed}: "
            f"{sorted(release_versions)}"
        )
    tag = expected_version.lower()
    return {
        "version": displayed,
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
            REPLAY_PROFILE_LINE,
        ),
        "references/runtime/03-goal-loop.md": (
            startup,
            f"{product} 按 prompt-cache manifest",
            f"当前 self-release refs 指向 {product} Profile",
            REPLAY_RUNTIME_LINE,
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
        "Profile 仅历史 replay",
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
    # The release block projects the actually published asset. The separate
    # current-version marker carries the development product identity.
    displayed_version = expected_version
    zh_projection = read_release_block("README.md", expected_version, displayed_version)
    en_projection = read_release_block("README.en.md", expected_version, displayed_version)
    if zh_projection != en_projection:
        fail("README.md and README.en.md controlled release semantics differ")
    for path in ("README.md", "README.en.md"):
        text = read(path)
        product_versions = set(CURRENT_PRODUCT_RE.findall(text))
        if product == "V2.41" and expected_version == "V2.40":
            heading = "## V2.41 版本改动" if path == "README.md" else "## V2.41 Changes"
            if text.count(heading) != 1 or text.rfind(heading) <= text.rfind("## V2.3"):
                fail(f"{path} must append exactly one V2.41 change list at EOF")
            if product_versions != {expected_version}:
                fail(f"{path} V2.41 development must retain its V2.40 published marker")
        elif product_versions != {product}:
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
    version_tuple = tuple(map(int, expected_version[1:].split(".")))
    expected_claim_scope = (
        "agent_product_development_and_verification_governance_desktop_contracts"
        if version_tuple >= (2, 48)
        else (
            "verification_governance_and_rust_tauri_desktop_contracts"
            if version_tuple >= (2, 46)
            else (
                "structural_governance_and_test_contracts"
                if version_tuple >= (2, 44)
                else "structural_governance"
            )
        )
    )
    if release.get("claim_scope") != expected_claim_scope:
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


def validate_v250_current(args: argparse.Namespace, product: str) -> None:
    """Validate the thin Current projection."""

    suffix = product.removeprefix("V").lower()
    compact = suffix.replace(".", "")
    startup = f"我是 Goal Teams Lead {product}。"
    identity_markers = {
        "SKILL.md": (f"Goal Teams {product}", startup),
        ".agents/skills/goal-teams/SKILL.md": (f"Goal Teams {product}",),
        "AGENTS.md": (
            f"产品版本：`{product}`",
            "通用核心策略：`V2.5`",
            "Legacy 机器数据 schema：`V2.3`",
            "scripts/v250/",
            "schemas/v2.50/",
        ),
        "agents/openai.yaml": (f"Goal Teams {product}", startup),
    }
    for path, markers in identity_markers.items():
        text = read(path)
        for marker in markers:
            if marker not in text:
                fail(f"{path} missing {product} Current identity marker: {marker}")

    for path, expected in V262_README_SHA256.items():
        observed = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        if observed != expected:
            fail(f"human-owned {path} changed from its protected V2.62 baseline")

    expected_activation = f"references/current/generations/{product}/activation-manifest.json"
    active = json.loads(read("references/current/ACTIVE.json"))
    predecessor_by_product = {
        "V2.63": "V2.62",
        "V2.65": "V2.63",
        "V2.66": "V2.65",
    }
    expected_predecessor = predecessor_by_product.get(product)
    candidate_before_active = (
        expected_predecessor is not None
        and args.mode == "development"
        and active.get("generation_id") == expected_predecessor
        and active.get("activation_manifest")
        == f"references/current/generations/{expected_predecessor}/activation-manifest.json"
        and active.get("state") == "active_current"
    )
    if not candidate_before_active and (
        active.get("generation_id") != product
        or active.get("activation_manifest") != expected_activation
        or active.get("state") != "active_current"
    ):
        fail(f"ACTIVE does not select the exact {product} Current generation")
    activation_raw = (ROOT / expected_activation).read_bytes()
    if not candidate_before_active and hashlib.sha256(activation_raw).hexdigest() != active.get(
        "activation_manifest_sha256"
    ):
        fail("ACTIVE activation manifest digest mismatch")
    activation = json.loads(activation_raw)
    identity = activation.get("identity", {})
    if (
        activation.get("generation_id") != product
        or identity.get("loaded_runtime_product_version") != product
        or identity.get("target_policy_generation") != product
        or identity.get("route_contract_schema_version")
        != "goal-teams-project-route-v2.50"
    ):
        fail("activation manifest mixes product, policy, or execution identity")
    if product == "V2.66" and identity.get("execution_asset_generation") != "V2.65":
        fail("V2.66 activation must bind the V2.65 Graph execution contract")
    if candidate_before_active and activation.get("generation_state") != "inactive_candidate":
        fail(f"{product} pre-activation projection must remain inactive_candidate")

    for path in (
        f"references/profiles/goal-teams-self-release-v{suffix}.md",
        f"references/release-profiles/v{suffix}.json",
    ):
        if not (ROOT / path).is_file():
            fail(f"missing {product} release profile: {path}")

    package = read("scripts/install/package-manifest.txt")
    package_markers = [
        f"prefix references/current/generations/{product}/",
        f"prefix references/compatibility/v{suffix}/",
        f"references/profiles/goal-teams-self-release-v{suffix}.md",
        f"references/release-profiles/v{suffix}.json",
        "prefix scripts/v250/",
        "prefix schemas/v2.50/",
        f"prefix scripts/v{compact}/",
        f"prefix schemas/v{suffix}/",
        f"prefix tests/v{compact}/",
    ]
    if product == "V2.66":
        package_markers.extend(
            [
                "file scripts/v265/graph_runtime.py",
                "file scripts/v265/runtime_controller.py",
                "file schemas/v2.65/graph-runtime.schema.json",
                "Graph execution contract V2.65",
            ]
        )
    for marker in package_markers:
        if marker not in package:
            fail(f"package manifest missing {product} Current marker: {marker}")
    for forbidden in ("docs/", "develops/", "references/legacy-replay"):
        if forbidden in package:
            fail(f"package manifest includes forbidden Current path: {forbidden}")

    release = json.loads(read("release/current/manifest.json"))
    if (
        release.get("core_policy_version") != CORE
        or release.get("legacy_data_schema_version") != LEGACY
        or release.get("status") != "release"
    ):
        fail("release/current mixes core, Legacy, or release status identity")
    published = release.get("product_version")
    identity = release.get("release_identity")
    if not isinstance(identity, dict):
        fail("release/current release_identity must be an object")

    def expected_public_assets(version: str) -> list[str]:
        return [
            f"goal-teams-{version}.tar.gz",
            "SHA256SUMS",
            "_release.json",
            "_files.sha256",
        ]

    def validate_published_identity(version: str) -> None:
        if (
            identity.get("tag") != version.lower()
            or identity.get("state") != "published"
            or isinstance(identity.get("release_id"), bool)
            or not isinstance(identity.get("release_id"), int)
            or identity["release_id"] <= 0
            or not COMMIT_RE.fullmatch(str(identity.get("source_commit", "")))
            or not COMMIT_RE.fullmatch(str(identity.get("source_tree", "")))
            or identity.get("public_assets") != expected_public_assets(version)
        ):
            fail(f"release/current {version} published identity is invalid")

    candidate_keys = {
        "candidate_product_version",
        "candidate_release_state",
        "candidate_profile",
    }
    if published == product:
        if release.get("schema_version") != f"goal-teams-release-manifest-{product.lower()}":
            fail(f"final {product} release/current schema is invalid")
        retained_candidate_keys = candidate_keys.intersection(release)
        if retained_candidate_keys:
            fail(
                f"final {product} release/current retains candidate keys: "
                f"{sorted(retained_candidate_keys)}"
            )
        validate_published_identity(product)
    else:
        predecessor = predecessor_by_product.get(product, "V2.6")
        candidate_states = (
            {"development_candidate_not_published", "v250_release_readiness"}
            if product in {"V2.63", "V2.65", "V2.66"}
            else {"v250_release_readiness"}
        )
        unchanged_published_predecessor = (
            product in {"V2.65", "V2.66"}
            and published == predecessor
            and candidate_keys.isdisjoint(release)
        )
        if not unchanged_published_predecessor and not (
            published == predecessor
            and release.get("schema_version")
            == f"goal-teams-release-manifest-{predecessor.lower()}"
            and release.get("candidate_product_version") == product
            and release.get("candidate_release_state") in candidate_states
            and release.get("candidate_profile")
            == f"references/release-profiles/v{suffix}.json"
        ):
            fail(f"release/current is neither the {product} candidate nor final projection")
        validate_published_identity(predecessor)
    release_readme = read("release/current/README.md")
    if product not in release_readme and not (
        product in {"V2.65", "V2.66"}
        and published == predecessor_by_product[product]
    ):
        fail(f"release/current README does not describe {product}")
    if not release_readme.startswith(f"# Goal Teams {published} Release\n"):
        fail("release/current README heading does not match published product")

    if args.mode == "development":
        if args.published_version != published:
            fail("development --published-version must match release/current")
    elif args.published_version is not None:
        fail("--published-version is only valid in development mode")
    validate_candidate_commit(args.candidate_commit)


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

    if product in {"V2.62", "V2.63", "V2.65", "V2.66"}:
        validate_v250_current(args, product)
        execution = "v2.50+v2.65-graph" if product == "V2.66" else "v2.50"
        print(
            "Version synchronization passed: "
            "mode="
            f"{args.mode}, product={product}, core=V2.5, execution={execution}, "
            "legacy=V2.3, docs=local-only."
        )
        return

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
