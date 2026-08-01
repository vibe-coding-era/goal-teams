#!/usr/bin/env python3
"""Read-only structural validation for Current or Replay package manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
CURRENT_MANIFEST = ROOT / "scripts/install/package-manifest.txt"
REPLAY_MANIFEST = ROOT / "scripts/install/replay-package-manifest.txt"
FORBIDDEN_CURRENT_PREFIXES = {"references/", "schemas/", "scripts/", "tests/v23/"}
FORBIDDEN_CURRENT_PATH_MARKERS = (
    "references/legacy-replay/",
    "references/profiles/goal-teams-self-release-v2.36.md",
    "references/profiles/goal-teams-self-release-v2.48.md",
    "references/release-profiles/v2.48.json",
    "schemas/v2.36/",
    "schemas/v2.48/",
    "scripts/v23/",
    "tests/v23/",
)
ALLOWED_REPLAY_SHARED_PATHS = {
    "schemas/v2.49/legacy-replay-manifest.schema.json",
    "scripts/v249/replay_runner.py",
}


def _safe_path(value: str, *, prefix: bool) -> bool:
    path = PurePosixPath(value.rstrip("/"))
    return bool(
        value
        and (value.endswith("/") is prefix)
        and "\\" not in value
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _source_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return {
            item.decode("utf-8")
            for item in result.stdout.split(b"\0")
            if item
        }
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _selected_paths(root: Path, rules: list[tuple[str, str]]) -> tuple[set[str], list[str]]:
    source_paths = _source_paths(root)
    selected: set[str] = set()
    errors: list[str] = []
    for kind, value in rules:
        if kind == "generated":
            continue
        if kind == "file":
            if value not in source_paths:
                errors.append(f"E_PACKAGE_MANIFEST_FILE_MISSING:{value}")
            else:
                selected.add(value)
            continue
        matches = {path for path in source_paths if path.startswith(value)}
        if not matches:
            errors.append(f"E_PACKAGE_MANIFEST_PREFIX_EMPTY:{value}")
        selected.update(matches)
    return selected, errors


def _legacy_intersection(root: Path, selected: set[str]) -> list[str]:
    activation = root / "references/current/generations/V2.49/activation-manifest.json"
    try:
        value = json.loads(activation.read_text(encoding="utf-8"))
        classification = value["legacy_classification"]
        prefixes = classification["path_prefixes"]
        exact = set(classification["exact_paths"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return ["E_V249_LEGACY_CLASSIFICATION_UNAVAILABLE"]
    return sorted(
        path
        for path in selected
        if path in exact or any(path.startswith(prefix) for prefix in prefixes)
    )


def _replay_required_paths(root: Path) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    replay_path = root / "references/legacy-replay/manifest.json"
    active_path = root / "references/current/ACTIVE.json"
    required = {
        "references/legacy-replay/INDEX.md",
        "references/legacy-replay/manifest.json",
        "references/current/generations/V2.48/activation-manifest.json",
    }
    try:
        raw = replay_path.read_bytes()
        replay = json.loads(raw.decode("utf-8"))
        active = json.loads(active_path.read_text(encoding="utf-8"))
        activation_path = root / active["activation_manifest"]
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        expected_replay_sha = activation["legacy_classification"]["replay_manifest_sha256"]
        if hashlib.sha256(raw).hexdigest() != expected_replay_sha:
            errors.append("E_REPLAY_PACKAGE_ACTIVE_BINDING")
        allowlist = replay["optional_replay_allowlist"]
        if not isinstance(allowlist, list) or not all(isinstance(item, str) for item in allowlist):
            raise TypeError("optional replay allowlist")
        required.update(allowlist)
        for entry in replay["replays"]:
            for field in (
                "schema_paths",
                "validator_paths",
                "transitive_dependency_paths",
                "fixture_paths",
            ):
                values = entry.get(field, [])
                if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                    raise TypeError(field)
                required.update(values)
            profile_path = entry.get("profile_path")
            if not isinstance(profile_path, str):
                raise TypeError("profile_path")
            required.add(profile_path)
            for item in entry.get("content_digests", []):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    raise TypeError("content_digests")
                required.add(item["path"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        errors.append("E_REPLAY_PACKAGE_CONTRACT_UNAVAILABLE")

    try:
        baseline = json.loads(
            (root / "references/current/generations/V2.48/activation-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        if baseline.get("schema_version") != "goal-teams-baseline-activation-manifest-v2.49":
            raise TypeError("baseline schema")
        for field in ("semantic_owner_paths", "execution_identity_paths"):
            for item in baseline[field]:
                required.add(item["path"])
        required.update(baseline["subagent_config_digests"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        errors.append("E_REPLAY_PACKAGE_BASELINE_UNAVAILABLE")
    return required, errors


def validate_manifest(path: Path, *, replay: bool) -> dict[str, object]:
    errors: list[str] = []
    rules: list[tuple[str, str]] = []
    if not path.is_file() or path.is_symlink():
        return {"passed": False, "errors": ["E_PACKAGE_MANIFEST_MISSING"]}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or fields[0] not in {"file", "prefix", "generated"}:
            errors.append(f"E_PACKAGE_MANIFEST_ROW:{number}")
            continue
        kind, value = fields
        if not _safe_path(value, prefix=kind == "prefix"):
            errors.append(f"E_PACKAGE_MANIFEST_PATH:{number}")
            continue
        if value.startswith(("docs/", "develops/", "GoalTeamsWork-")):
            errors.append(f"E_PACKAGE_MANIFEST_LOCAL_ONLY:{number}")
        rules.append((kind, value))
    if len(rules) != len(set(rules)):
        errors.append("E_PACKAGE_MANIFEST_DUPLICATE")
    values = {value for _, value in rules}
    selected, selection_errors = _selected_paths(ROOT, rules)
    errors.extend(selection_errors)
    if replay:
        if not selected:
            errors.append("E_REPLAY_PACKAGE_MANIFEST_EMPTY")
        required, contract_errors = _replay_required_paths(ROOT)
        errors.extend(contract_errors)
        missing = sorted(required - selected)
        errors.extend(f"E_REPLAY_PACKAGE_REQUIRED_MISSING:{path}" for path in missing)
        unexpected = sorted(selected - required - ALLOWED_REPLAY_SHARED_PATHS)
        errors.extend(f"E_REPLAY_PACKAGE_UNDECLARED:{path}" for path in unexpected)
        current_leaks = sorted(
            path
            for path in selected
            if (
                path.startswith("references/current/generations/V2.49/")
                or path.startswith("references/profiles/goal-teams-self-release-v2.49")
                or path.startswith("references/release-profiles/v2.49")
                or path.startswith("scripts/v249/")
                or path.startswith("schemas/v2.49/")
            )
            and path not in ALLOWED_REPLAY_SHARED_PATHS
        )
        errors.extend(f"E_REPLAY_PACKAGE_CURRENT_LEAK:{path}" for path in current_leaks)
        legacy_intersection = sorted(selected - ALLOWED_REPLAY_SHARED_PATHS)
    else:
        required_rules = {
            ("file", "references/current/ACTIVE.json"),
            ("prefix", "references/current/generations/V2.49/"),
            ("prefix", "scripts/v249/"),
            ("prefix", "schemas/v2.49/"),
        }
        for required in sorted(required_rules):
            if required not in rules:
                errors.append(f"E_CURRENT_PACKAGE_MANIFEST_REQUIRED:{required[1]}")
        for kind, value in rules:
            if kind == "prefix" and value in FORBIDDEN_CURRENT_PREFIXES:
                errors.append(f"E_CURRENT_PACKAGE_MANIFEST_WIDE_PREFIX:{value}")
            if any(
                value == marker or value.startswith(marker)
                for marker in FORBIDDEN_CURRENT_PATH_MARKERS
            ):
                errors.append(f"E_CURRENT_PACKAGE_MANIFEST_LEGACY:{value}")
        for required_path in (
            "references/profiles/goal-teams-self-release-v2.49.md",
            "references/release-profiles/v2.49.json",
            "scripts/checks/check-v249.py",
            "scripts/install/install-local.sh",
        ):
            if ("file", required_path) not in rules:
                errors.append(f"E_CURRENT_PACKAGE_MANIFEST_REQUIRED:{required_path}")
        legacy_intersection = _legacy_intersection(ROOT, selected)
        if legacy_intersection:
            errors.extend(
                f"E_CURRENT_PACKAGE_LEGACY_REACHABLE:{path}"
                for path in legacy_intersection
            )
        try:
            activation = json.loads(
                (
                    ROOT
                    / "references/current/generations/V2.49/activation-manifest.json"
                ).read_text(encoding="utf-8")
            )
            required_current = set(activation["current_default_allowlist"])
            missing_current = sorted(required_current - selected)
            errors.extend(
                f"E_CURRENT_PACKAGE_REQUIRED_MISSING:{path}" for path in missing_current
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            errors.append("E_CURRENT_PACKAGE_ACTIVATION_UNAVAILABLE")
    return {
        "schema_version": "goal-teams-package-manifest-check-v2.49",
        "passed": not errors,
        "errors": errors,
        "manifest": path.relative_to(ROOT).as_posix(),
        "mode": "replay" if replay else "current",
        "rule_count": len(rules),
        "selected_path_count": len(selected),
        "legacy_intersection": legacy_intersection,
        "external_side_effect_count": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = (args.manifest or (REPLAY_MANIFEST if args.replay else CURRENT_MANIFEST)).resolve()
    result = validate_manifest(path, replay=args.replay)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
