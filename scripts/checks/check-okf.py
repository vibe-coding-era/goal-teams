#!/usr/bin/env python3
"""CLI for Goal Teams V2.39 Google OKF conformance gates."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRODUCT_ROOT = SCRIPT.parents[2]
V23 = PRODUCT_ROOT / "scripts" / "v23"
if str(V23) not in sys.path:
    sys.path.insert(0, str(V23))

_previous_dont_write_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    from okf_conformance import (  # noqa: E402
        OkfError,
        build_package_manifest,
        discover_changed,
        discover_tracked,
        load_policy,
        scan_bundle,
        scan_paths,
        validate_manifest,
    )
finally:
    sys.dont_write_bytecode = _previous_dont_write_bytecode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PRODUCT_ROOT)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--tracked", action="store_true")
    modes.add_argument("--changed", action="store_true")
    modes.add_argument("--bundle-root", type=Path)
    modes.add_argument("--manifest", type=Path)
    modes.add_argument("--package-tree", type=Path)
    modes.add_argument("--preview-package-manifest", action="store_true")
    modes.add_argument("--write-package-manifest", action="store_true")
    return parser


def _error_payload(exc: OkfError) -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-okf-scan-report-v1",
        "mode": "runtime-error",
        "passed": False,
        "error_code": exc.code,
        "message": exc.message,
        "findings": [exc.finding()],
        "files": [],
    }


def _canonical_manifest_path(root: Path, policy: dict[str, Any]) -> Path:
    package = policy.get("package_manifest")
    relative = "references/okf-conformance-manifest.json"
    if isinstance(package, dict) and isinstance(package.get("path"), str):
        relative = package["path"]
    return root / relative


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = args.root.resolve()
    policy = load_policy(root)
    if args.tracked:
        paths = discover_tracked(root)
        report = scan_paths(paths, policy, {"root": root, "mode": "tracked"})
    elif args.changed:
        paths, deleted = discover_changed(root)
        report = scan_paths(paths, policy, {"root": root, "mode": "changed"})
        report["discovery"] = {
            "changed": [path.relative_to(root).as_posix() for path in paths],
            "deleted": deleted,
            "deleted_nonblocking": True,
        }
    elif args.bundle_root is not None:
        bundle = args.bundle_root
        if not bundle.is_absolute():
            bundle = root / bundle
        report = scan_bundle(bundle, policy)
    elif args.manifest is not None:
        report = validate_manifest(root, policy, args.manifest)
    elif args.package_tree is not None:
        tree = args.package_tree.resolve()
        canonical = _canonical_manifest_path(tree, policy)
        canonical_valid = False
        try:
            mode = canonical.lstat().st_mode
            canonical.resolve(strict=True).relative_to(tree)
            canonical_valid = stat.S_ISREG(mode) and not stat.S_ISLNK(mode)
        except (OSError, RuntimeError, ValueError):
            canonical_valid = False
        if canonical_valid:
            report = validate_manifest(
                tree, policy, canonical, require_complete_package=True
            )
            report["mode"] = "package-tree"
        else:
            raise OkfError(
                "E_OKF_PACKAGE_MISSING",
                "package-tree requires the canonical frozen conformance manifest",
                path=canonical.relative_to(tree).as_posix(),
            )
    elif args.preview_package_manifest:
        manifest = build_package_manifest(root, policy)
        report = {
            "schema_version": "goal-teams-okf-scan-report-v1",
            "mode": "preview-package-manifest",
            "passed": True,
            "package_completeness_state": "unavailable",
            "policy_sha256": policy["policy_sha256"],
            "files": manifest["markdown_entries"],
            "findings": [],
            "manifest": {
                "schema_version": manifest["schema_version"],
                "manifest_scope": manifest["manifest_scope"],
                "payload_file_count": manifest["package"]["payload_file_count"],
                "payload_tree_sha256": manifest["package"]["payload_tree_sha256"],
            },
        }
    else:
        manifest = build_package_manifest(root, policy)
        target = _canonical_manifest_path(root, policy)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        report = {
            "schema_version": "goal-teams-okf-scan-report-v1",
            "mode": "write-package-manifest",
            "passed": True,
            "policy_sha256": policy["policy_sha256"],
            "package_completeness_state": "unavailable",
            "files": manifest["markdown_entries"],
            "findings": [],
            "manifest": {
                "path": target.relative_to(root).as_posix(),
                "schema_version": manifest["schema_version"],
                "file_count": manifest["package"]["payload_file_count"],
                "package_tree_sha256": manifest["package"]["payload_tree_sha256"],
            },
        }
    return report, 0 if report.get("passed") else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        report, code = _run(args)
    except OkfError as exc:
        report, code = _error_payload(exc), 2
    except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
        report = {
            "schema_version": "goal-teams-okf-scan-report-v1",
            "mode": "runtime-error",
            "passed": False,
            "error_code": "E_OKF_RUNTIME",
            "message": type(exc).__name__,
            "findings": [],
            "files": [],
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
