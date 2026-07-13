#!/usr/bin/env python3
"""Exercise the V2.3 installer lifecycle and transactional failure paths."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts" / "install" / "package-manifest.txt"
INSTALLER_REL = Path("scripts/install/install-local.sh")


def run(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None, expected: int = 0
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode != expected:
        print(result.stdout, end="", file=sys.stderr)
        print(result.stderr, end="", file=sys.stderr)
        raise AssertionError(f"command returned {result.returncode}, expected {expected}: {command}")
    return result


def parse_manifest() -> tuple[set[str], list[str], set[str]]:
    files: set[str] = set()
    prefixes: list[str] = []
    generated: set[str] = set()
    for raw_line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        kind, value = line.split(maxsplit=1)
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise AssertionError(f"unsafe package manifest path: {value}")
        if kind == "file":
            files.add(value)
        elif kind == "prefix" and value.endswith("/"):
            prefixes.append(value)
        elif kind == "generated" and not value.endswith("/"):
            generated.add(value)
        else:
            raise AssertionError(f"invalid package manifest line: {line}")
    if generated != {"references/okf-conformance-manifest.json"}:
        raise AssertionError(f"invalid generated-required package paths: {generated}")
    return files, prefixes, generated


def source_candidates() -> Iterable[tuple[Path, str]]:
    files, prefixes, _generated = parse_manifest()
    seen: set[str] = set()
    for relative in sorted(files):
        source = ROOT / relative
        if source.is_file() and not source.is_symlink():
            seen.add(relative)
            yield source, relative
    for prefix in sorted(prefixes):
        directory = ROOT / prefix
        if not directory.is_dir():
            continue
        for source in sorted(directory.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            relative = source.relative_to(ROOT).as_posix()
            if relative in seen or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            seen.add(relative)
            yield source, relative


def make_clean_source(destination: Path) -> None:
    destination.mkdir(parents=True)
    for source, relative in source_candidates():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    run(["git", "init", "-q"], cwd=destination)
    run(["git", "config", "user.email", "goal-teams-test@example.invalid"], cwd=destination)
    run(["git", "config", "user.name", "Goal Teams Installer Test"], cwd=destination)
    run(["git", "add", "-A"], cwd=destination)
    run(["git", "commit", "-qm", "installer lifecycle fixture v1"], cwd=destination)


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_tree(path: Path) -> str:
    records: list[tuple[str, int, str]] = []
    if not path.exists():
        return "missing"
    for child in sorted(path.rglob("*")):
        if child.is_file() and not child.is_symlink():
            records.append((child.relative_to(path).as_posix(), stat.S_IMODE(child.stat().st_mode), digest_file(child)))
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode("utf-8")).hexdigest()


def no_bytecode_environment(**updates: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    environment.update(updates)
    return environment


def assert_no_python_bytecode(root: Path, phase: str) -> None:
    polluted = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.name == "__pycache__" or path.suffix == ".pyc"
    )
    if polluted:
        raise AssertionError(f"{phase} created Python bytecode: {polluted}")


def install_run(
    source: Path,
    home: Path,
    report: Path,
    *arguments: str,
    expected: int = 0,
    fail_at: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = no_bytecode_environment(
        CODEX_HOME=str(home),
        INSTALL_REPORT=str(report),
    )
    if fail_at:
        environment["GOAL_TEAMS_INSTALL_FAIL_AT"] = fail_at
    return run(
        [str(source / INSTALLER_REL), *arguments],
        cwd=source,
        env=environment,
        expected=expected,
    )


def load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return payload


def assert_report_minimized(report: Path, temporary_root: Path) -> dict:
    payload = load_json(report)
    serialized = report.read_text(encoding="utf-8")
    if str(temporary_root) in serialized:
        raise AssertionError("install report disclosed an absolute temporary/source path")
    if payload.get("source", {}).get("tree_digest") is None and payload.get("status") not in {"failed"}:
        raise AssertionError("successful report omitted source tree digest")
    if payload.get("status") in {"installed", "dry_run"} and not payload.get("package_files"):
        raise AssertionError("successful report omitted package file hashes")
    forbidden_prefixes = (".github/", ".git/", ".codex/", "GoalTeamsWork-", "outputs/")
    packaged_paths = [entry.get("path", "") for entry in payload.get("package_files", [])]
    leaked_paths = [
        path for path in packaged_paths
        if any(path.startswith(prefix) for prefix in forbidden_prefixes)
    ]
    if leaked_paths:
        raise AssertionError(f"package manifest included repository/runtime-only paths: {leaked_paths}")
    return payload


def main() -> None:
    if os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1":
        print("Installer lifecycle skipped during nested staging validation.")
        return
    current_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    with tempfile.TemporaryDirectory(prefix="goal-teams-install-lifecycle-") as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "source"
        home = temporary_root / "codex-home"
        reports = temporary_root / "reports"
        reports.mkdir(parents=True)
        make_clean_source(source)

        old_skill = home / "skills" / "goal-teams"
        old_agent = home / "agents" / "goal-backend.toml"
        fallback_agent = home / "agents" / "team-qa.toml"
        old_skill.mkdir(parents=True)
        old_agent.parent.mkdir(parents=True)
        (old_skill / "user-install.txt").write_text("pre-install skill\n", encoding="utf-8")
        old_agent.write_text("name = 'user-backend'\n", encoding="utf-8")
        fallback_agent.write_text(
            "name = 'team_qa'\nnickname_candidates = ['User QA']\n", encoding="utf-8"
        )
        original_skill_digest = digest_tree(old_skill)
        original_agent_digest = digest_file(old_agent)
        original_fallback_digest = digest_file(fallback_agent)

        changelog = source / "release" / "current" / "README.md"
        original_changelog = changelog.read_text(encoding="utf-8")
        changelog.write_text(original_changelog + "\ndirty lifecycle fixture\n", encoding="utf-8")
        dirty_report = reports / "dirty.json"
        install_run(source, home, dirty_report, "--dry-run", expected=1)
        dirty_payload = assert_report_minimized(dirty_report, temporary_root)
        if dirty_payload["status"] != "failed" or dirty_payload["source"]["dirty"] is not True:
            raise AssertionError("dirty source was not rejected and reported")
        changelog.write_text(original_changelog, encoding="utf-8")

        dry_report = reports / "dry-run.json"
        install_run(source, home, dry_report, "--dry-run")
        dry_payload = assert_report_minimized(dry_report, temporary_root)
        if dry_payload["status"] != "dry_run" or digest_tree(old_skill) != original_skill_digest:
            raise AssertionError("dry-run changed the live target")
        assert_no_python_bytecode(temporary_root, "no-env dry-run")

        install_report = reports / "install.json"
        install_run(source, home, install_report)
        install_payload = assert_report_minimized(install_report, temporary_root)
        if install_payload["status"] != "installed" or install_payload["action"] != "install":
            raise AssertionError("initial install report status is incorrect")
        if not {"skill", "agent:goal-backend.toml"} <= set(install_payload.get("backed_up_components", [])):
            raise AssertionError("install report omitted pre-existing skill/agent backup components")
        state_path = home / "state" / "goal-teams" / "current.json"
        state_v1 = load_json(state_path)
        v1_skill_digest = digest_tree(old_skill)
        v1_agent_digest = digest_file(old_agent)
        if not (old_skill / "VERSION").is_file() or old_agent.read_text(encoding="utf-8") == "name = 'user-backend'\n":
            raise AssertionError("initial install did not switch both skill and agent targets")
        if not (old_skill / "scripts" / "checks" / "check-ci-pins.py").is_file():
            raise AssertionError("Round2 CI pin checker was omitted from the install package manifest")
        if (old_skill / "VERSION").read_text(encoding="utf-8").strip() != current_version:
            raise AssertionError(f"{current_version} VERSION was not installed")
        canonical_okf = old_skill / "references" / "okf-conformance-manifest.json"
        if not canonical_okf.is_file():
            raise AssertionError("installer did not generate the canonical OKF manifest")
        okf_manifest = load_json(canonical_okf)
        if (
            okf_manifest.get("manifest_scope") != "installed_package_complete"
            or okf_manifest.get("source", {}).get("commit_sha256")
            != install_payload.get("source", {}).get("commit")
            or install_payload.get("source", {}).get("okf_conformance_manifest_sha256")
            != digest_file(canonical_okf)
            or install_payload.get("source", {}).get("okf_policy_sha256")
            != okf_manifest.get("policy", {}).get("sha256")
            or install_payload.get("source", {}).get("okf_payload_tree_sha256")
            != okf_manifest.get("package", {}).get("payload_tree_sha256")
            or install_payload.get("source", {}).get("okf_package_completeness_state")
            != "complete"
        ):
            raise AssertionError("install report did not bind the canonical OKF manifest identity")
        for field in (
            "package_manifest_sha256",
            "okf_conformance_manifest_sha256",
            "okf_payload_tree_sha256",
            "okf_policy_sha256",
            "okf_checker_hashes",
            "okf_package_completeness_state",
        ):
            if state_v1.get(field) != install_payload.get("source", {}).get(field):
                raise AssertionError(f"install report/state OKF identity mismatch: {field}")
        canonical_bytes = canonical_okf.read_bytes()
        canonical_okf.unlink()
        missing_check = run(
            [
                sys.executable,
                str(old_skill / "scripts" / "checks" / "check-okf.py"),
                "--root",
                str(old_skill),
                "--package-tree",
                str(old_skill),
            ],
            cwd=old_skill,
            env=no_bytecode_environment(),
            expected=2,
        )
        missing_payload = json.loads(missing_check.stdout)
        if missing_payload.get("error_code") != "E_OKF_PACKAGE_MISSING":
            raise AssertionError("gitless package check did not fail closed on missing canonical manifest")
        canonical_okf.write_bytes(canonical_bytes)
        canonical_okf.chmod(0o644)
        direct_gitless_checks = (
            (
                "okf-wrapper",
                [
                    sys.executable,
                    str(old_skill / "scripts" / "check-okf.py"),
                    "--root",
                    str(old_skill),
                    "--package-tree",
                    str(old_skill),
                ],
            ),
            (
                "prompt-cache-checker",
                [
                    sys.executable,
                    str(old_skill / "scripts" / "checks" / "check-prompt-cache.py"),
                ],
            ),
            (
                "prompt-cache-wrapper",
                [
                    sys.executable,
                    str(old_skill / "scripts" / "check-prompt-cache.py"),
                ],
            ),
            (
                "context-budget-checker",
                [
                    sys.executable,
                    str(old_skill / "scripts" / "checks" / "check-context-budget.py"),
                    "--root",
                    str(old_skill),
                ],
            ),
        )
        for label, command in direct_gitless_checks:
            result = run(
                command,
                cwd=old_skill,
                env=no_bytecode_environment(),
            )
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"{label} did not emit a JSON result: {result.stdout!r}"
                ) from exc
            if payload.get("passed") is not True:
                raise AssertionError(f"{label} did not pass: {payload}")
            assert_no_python_bytecode(old_skill, f"no-env direct {label}")
        v236_skill_paths = (
            "references/goal-teams-core-v2.5.md",
            "references/profiles/goal-teams-self-release-v2.36.md",
            "scripts/v23/v236_security.py",
            "scripts/v23/v236_trust.py",
            "scripts/v23/v236_acceptance.py",
            "schemas/v2.36/project-route.schema.json",
            "schemas/v2.36/execution-contract.schema.json",
            "schemas/v2.36/protected-git-tree-snapshot.schema.json",
            "schemas/v2.36/agent-host-attestation.schema.json",
            "schemas/v2.36/host-route-receipt.schema.json",
            "schemas/v2.36/persistent-challenge-state.schema.json",
            "schemas/v2.36/acceptance-binding.schema.json",
            "schemas/v2.36/acceptance-core-binding.schema.json",
            "schemas/v2.36/acceptance-input-snapshot.schema.json",
            "schemas/v2.36/policy-profile-selector.schema.json",
            "schemas/v2.36/attested-identity-registry.schema.json",
            "references/profiles/goal-teams-self-release-v2.38.md",
            "references/prompt-cache-manifest.json",
            "references/prompt-cache-protocol.md",
            "references/okf-conformance-policy.json",
            "references/okf-conformance-manifest.json",
            "scripts/v23/prompt_cache.py",
            "scripts/v23/okf_conformance.py",
            "scripts/checks/check-prompt-cache.py",
            "scripts/checks/check-okf.py",
            "release/current/README.md",
            "release/current/manifest.json",
        )
        missing_v236 = [path for path in v236_skill_paths if not (old_skill / path).is_file()]
        if missing_v236:
            raise AssertionError(f"V2.36 install package omitted files: {missing_v236}")
        prompt_fields = (
            "skill_source_path",
            "prompt_identity_version",
            "runtime_prompt_route",
            "runtime_prompt_refs",
            "prefix_manifest_sha256",
            "route_static_digest",
            "prompt_manifest_status",
            "prompt_digest_scope",
            "skill_tree_digest",
        )
        missing_prompt_fields = [field for field in prompt_fields if not state_v1.get(field)]
        if missing_prompt_fields:
            raise AssertionError(f"V2.38 install state omitted prompt identity: {missing_prompt_fields}")
        if state_v1.get("runtime_prompt_digest") is not None or state_v1.get("stable_prefix_digest") is not None:
            raise AssertionError("installer route plan impersonated a host-observed runtime prompt digest")
        if state_v1["route_static_digest"] == state_v1["skill_tree_digest"]:
            raise AssertionError("route static digest collapsed into full skill tree digest")
        if state_v1["prompt_manifest_status"] != "unavailable" or state_v1["prompt_digest_scope"] != "partial":
            raise AssertionError("installer prompt visibility boundary is not explicit")
        for field in (
            "prompt_identity_version",
            "runtime_prompt_route",
            "runtime_prompt_refs",
            "prefix_manifest_sha256",
            "route_static_digest",
            "prompt_manifest_status",
            "prompt_digest_scope",
            "stable_prefix_digest",
            "runtime_prompt_digest",
        ):
            if install_payload["source"].get(field) != state_v1.get(field):
                raise AssertionError(f"install report/state prompt identity mismatch: {field}")
        assert_no_python_bytecode(temporary_root, "no-env install")
        v235_skill_paths = (
            "schemas/v2.35/project-route.schema.json",
            "schemas/v2.35/test-case.schema.json",
            "schemas/v2.35/version-binding.schema.json",
            "scripts/checks/validate-test-case-contract.py",
            "scripts/validate-test-case-contract.py",
        )
        missing_v235 = [path for path in v235_skill_paths if not (old_skill / path).is_file()]
        if missing_v235:
            raise AssertionError(f"V2.35 install package omitted files: {missing_v235}")
        for role in ("security", "performance", "refactor", "sqa"):
            if not (old_skill / "subagents" / f"goal-{role}.toml").is_file():
                raise AssertionError(f"V2.35 skill omitted goal-{role}.toml")
            if not (home / "agents" / f"goal-{role}.toml").is_file():
                raise AssertionError(f"V2.35 live agent omitted goal-{role}.toml")
        if digest_file(fallback_agent) != original_fallback_digest:
            raise AssertionError("default install modified fallback agent without opt-in")

        changelog.write_text(original_changelog + "\ninstaller update fixture v2\n", encoding="utf-8")
        run(["git", "add", "release/current/README.md"], cwd=source)
        run(["git", "commit", "-qm", "installer lifecycle fixture v2"], cwd=source)
        update_report = reports / "update.json"
        install_run(source, home, update_report, "--update-team-fallback")
        update_payload = assert_report_minimized(update_report, temporary_root)
        if update_payload["action"] != "update" or digest_tree(old_skill) == v1_skill_digest:
            raise AssertionError("update did not install a distinct tracked tree")
        state_v2 = load_json(state_path)
        v2_skill_digest = digest_tree(old_skill)
        v2_agent_digest = digest_file(old_agent)
        v2_fallback_digest = digest_file(fallback_agent)
        if v2_fallback_digest == original_fallback_digest:
            raise AssertionError("opt-in update did not modify fallback agent")

        changelog.write_text(changelog.read_text(encoding="utf-8") + "\nfault fixture v3\n", encoding="utf-8")
        run(["git", "add", "release/current/README.md"], cwd=source)
        run(["git", "commit", "-qm", "installer lifecycle fixture v3"], cwd=source)
        fault_report = reports / "fault.json"
        install_run(source, home, fault_report, expected=1, fail_at="after_agent_switch")
        fault_payload = assert_report_minimized(fault_report, temporary_root)
        if fault_payload["status"] != "failed_rolled_back":
            raise AssertionError("post-switch failure did not report automatic rollback")
        if (
            digest_tree(old_skill) != v2_skill_digest
            or digest_file(old_agent) != v2_agent_digest
            or digest_file(fallback_agent) != v2_fallback_digest
        ):
            raise AssertionError("post-switch failure did not restore skill and agents byte-equivalently")
        if load_json(state_path) != state_v2:
            raise AssertionError("post-switch failure changed the install state")

        rollback_backup = home / "state" / "goal-teams" / "backups" / state_v2["backup_id"]
        backup_version = rollback_backup / "snapshot" / "skill" / "VERSION"
        backup_version_bytes = backup_version.read_bytes()
        backup_version.write_bytes(backup_version_bytes + b"tampered")
        unsafe_report = reports / "unsafe-rollback.json"
        install_run(source, home, unsafe_report, "--rollback", expected=1)
        if (
            digest_tree(old_skill) != v2_skill_digest
            or digest_file(old_agent) != v2_agent_digest
            or digest_file(fallback_agent) != v2_fallback_digest
        ):
            raise AssertionError("invalid backup changed live targets before validation")
        backup_version.write_bytes(backup_version_bytes)

        rollback_report = reports / "rollback.json"
        install_run(source, home, rollback_report, "--rollback")
        rollback_payload = assert_report_minimized(rollback_report, temporary_root)
        if rollback_payload["status"] != "restored":
            raise AssertionError("rollback report status is incorrect")
        if (
            digest_tree(old_skill) != v1_skill_digest
            or digest_file(old_agent) != v1_agent_digest
            or digest_file(fallback_agent) != original_fallback_digest
        ):
            raise AssertionError("rollback did not restore the previous version")
        if load_json(state_path) != state_v1:
            raise AssertionError("rollback did not restore the previous install state")

        (old_skill / "user-after-install.txt").write_text("preserve this skill edit\n", encoding="utf-8")
        old_agent.write_text(old_agent.read_text(encoding="utf-8") + "# preserve this agent edit\n", encoding="utf-8")
        uninstall_report = reports / "uninstall.json"
        install_run(source, home, uninstall_report, "--uninstall")
        uninstall_payload = assert_report_minimized(uninstall_report, temporary_root)
        if uninstall_payload["status"] != "uninstalled" or not uninstall_payload["preserved_user_changes"]:
            raise AssertionError("uninstall did not archive and report user modifications")
        if (
            digest_tree(old_skill) != original_skill_digest
            or digest_file(old_agent) != original_agent_digest
            or digest_file(fallback_agent) != original_fallback_digest
        ):
            raise AssertionError("uninstall did not restore the pre-install skill and agent")
        if state_path.exists():
            raise AssertionError("uninstall left an active install state")
        for item in uninstall_payload["preserved_user_changes"]:
            archive_ref = item.get("archive_ref")
            if archive_ref != "not_applicable" and not (home / archive_ref).exists():
                raise AssertionError(f"preserved user change archive is missing: {archive_ref}")

    print("Installer lifecycle checks passed: dirty/dry-run/install/update/failure/rollback/uninstall.")


if __name__ == "__main__":
    main()
