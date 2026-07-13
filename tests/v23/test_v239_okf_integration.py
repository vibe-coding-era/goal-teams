"""CLI, Git discovery, bundle, install and package-boundary tests for V2.39 OKF."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v23.common import ROOT


FIXTURES = ROOT / "tests" / "v23" / "fixtures" / "v239" / "okf"
CHECKER = ROOT / "scripts" / "checks" / "check-okf.py"
WRAPPER = ROOT / "scripts" / "check-okf.py"
RUNTIME = ROOT / "scripts" / "v23" / "okf_conformance.py"


def _load_runtime():
    spec = importlib.util.spec_from_file_location("goalteams_v239_okf_integration", RUNTIME)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load OKF runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


okf_runtime = _load_runtime()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_policy(root: Path) -> None:
    target = root / "references" / "okf-conformance-policy.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "policy.json", target)


def _prepare_package_tree(root: Path) -> Path:
    _write_policy(root)
    (root / "VERSION").write_text("V2.39\n", encoding="utf-8")
    for relative in (
        "scripts/v23/okf_conformance.py",
        "scripts/checks/check-okf.py",
        "scripts/check-okf.py",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    install_manifest = root / "scripts" / "install" / "package-manifest.txt"
    install_manifest.parent.mkdir(parents=True, exist_ok=True)
    install_manifest.write_text(
        "file VERSION\nprefix references/\nprefix scripts/\n",
        encoding="utf-8",
    )
    shutil.copyfile(FIXTURES / "valid.md", root / "references" / "valid.md")
    policy = okf_runtime.load_policy(root)
    try:
        manifest = okf_runtime.build_package_manifest(
            root,
            policy,
            source_binding={
                "commit_sha256": "1" * 64,
                "git_tree_id": "2" * 40,
                "package_manifest_sha256": _sha256(install_manifest),
            },
        )
    except TypeError as exc:
        raise AssertionError(
            "build_package_manifest must accept the Revision 2 source_binding contract"
        ) from exc
    if manifest.get("schema_version") != "goal-teams-okf-conformance-manifest-v2.39":
        raise AssertionError(f"wrong canonical manifest schema: {manifest.get('schema_version')}")
    target = root / "references" / "okf-conformance-manifest.json"
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return target


def _run(*args: str, cwd: Path | None = None) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"checker must emit one JSON object: rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise AssertionError("checker output must be an object")
    return proc, payload


def _no_bytecode_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    return environment


def _bytecode_paths(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.name == "__pycache__" or path.suffix == ".pyc"
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )


def _init_repo(root: Path) -> None:
    self_check = _git(root, "init", "-q")
    if self_check.returncode != 0:
        raise AssertionError(self_check.stderr)
    _git(root, "config", "user.email", "v239-test@example.invalid")
    _git(root, "config", "user.name", "V239 Test")


class V239OkfIntegrationTests(unittest.TestCase):
    def require_checker(self) -> None:
        self.assertTrue(CHECKER.is_file(), "scripts/checks/check-okf.py is required")

    def test_checker_wrapper_and_check_sh_integration_exist(self) -> None:
        self.require_checker()
        self.assertTrue(WRAPPER.is_file(), "root scripts/check-okf.py wrapper is required")
        check = (ROOT / "scripts" / "checks" / "check.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/checks/check-okf.py", check)
        self.assertIn("--tracked", check)
        self.assertIn("--bundle-root", check)

    def test_cli_exit_codes_are_zero_one_two_and_include_stable_paths(self) -> None:
        self.require_checker()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_policy(root)
            bundle = root / "bundle"
            shutil.copytree(FIXTURES / "mini-valid", bundle)
            proc, payload = _run("--root", str(root), "--bundle-root", str(bundle))
            self.assertEqual(proc.returncode, 0, payload)
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["mode"], "bundle-root")

            (bundle / "plan.md").write_text("# missing frontmatter\n", encoding="utf-8")
            proc, payload = _run("--root", str(root), "--bundle-root", str(bundle))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertFalse(payload["passed"])
            self.assertTrue(
                any(
                    finding.get("path") == "plan.md"
                    and finding.get("error_code") == "E_OKF_FRONTMATTER_START"
                    for finding in payload["findings"]
                )
            )

            proc, payload = _run("--root", str(root), "--tracked")
            self.assertEqual(proc.returncode, 2, payload)
            self.assertEqual(payload["error_code"], "E_OKF_GIT_REQUIRED")

    def test_tracked_mode_scans_every_tracked_markdown(self) -> None:
        self.require_checker()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            _write_policy(root)
            shutil.copyfile(FIXTURES / "valid.md", root / "references" / "valid.md")
            (root / "SKILL.md").write_text("special skill format\n", encoding="utf-8")
            self.assertEqual(_git(root, "add", ".").returncode, 0)
            self.assertEqual(_git(root, "commit", "-qm", "fixture").returncode, 0)
            proc, payload = _run("--root", str(root), "--tracked")
            self.assertEqual(proc.returncode, 0, payload)
            files = {entry["path"]: entry for entry in payload["files"]}
            self.assertEqual(files["references/valid.md"]["class"], "A")
            self.assertEqual(files["SKILL.md"]["class"], "B")

    def test_changed_mode_includes_staged_unstaged_untracked_and_reports_deleted(self) -> None:
        self.require_checker()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            _write_policy(root)
            for name in ("staged.md", "unstaged.md", "deleted.md"):
                shutil.copyfile(FIXTURES / "valid.md", root / "references" / name)
            self.assertEqual(_git(root, "add", ".").returncode, 0)
            self.assertEqual(_git(root, "commit", "-qm", "fixture").returncode, 0)

            (root / "references" / "staged.md").write_text(
                "# staged missing frontmatter\n", encoding="utf-8"
            )
            self.assertEqual(_git(root, "add", "references/staged.md").returncode, 0)
            (root / "references" / "unstaged.md").write_text(
                "# unstaged missing frontmatter\n", encoding="utf-8"
            )
            (root / "references" / "untracked.md").write_text(
                "# untracked missing frontmatter\n", encoding="utf-8"
            )
            (root / "references" / "deleted.md").unlink()

            proc, payload = _run("--root", str(root), "--changed")
            self.assertEqual(proc.returncode, 1, payload)
            changed = set(payload["discovery"]["changed"])
            self.assertTrue(
                {
                    "references/staged.md",
                    "references/unstaged.md",
                    "references/untracked.md",
                }
                <= changed
            )
            self.assertIn("references/deleted.md", payload["discovery"]["deleted"])
            self.assertTrue(payload["discovery"]["deleted_nonblocking"])

    def test_bundle_root_scans_ignored_local_docs_and_mini_bundle(self) -> None:
        self.require_checker()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_policy(root)
            docs = root / "docs" / "V2.34"
            mini = root / "GoalTeamsWork-V2.39" / "versions" / "V2.39"
            shutil.copytree(FIXTURES / "mini-valid", docs)
            shutil.copytree(FIXTURES / "mini-valid", mini)
            for bundle in (docs, mini):
                with self.subTest(bundle=bundle):
                    proc, payload = _run(
                        "--root", str(root), "--bundle-root", str(bundle)
                    )
                    self.assertEqual(proc.returncode, 0, payload)
                    self.assertEqual(payload["mode"], "bundle-root")
                    self.assertEqual(payload["bundle"]["index_path"], "index.md")

    def test_manifest_mode_replays_frozen_hash_and_detects_mutation(self) -> None:
        self.require_checker()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_policy(root)
            target = root / "references" / "valid.md"
            shutil.copyfile(FIXTURES / "valid.md", target)
            for relative in (
                "scripts/v23/okf_conformance.py",
                "scripts/checks/check-okf.py",
            ):
                copied = root / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, copied)
            manifest = root / "okf-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-okf-conformance-manifest-v2.39",
                        "canonicalization": "utf8-lf-json-sort-keys-compact-v1",
                        "product_version": "V2.39",
                        "manifest_scope": "installed_package_complete",
                        "source": {
                            "commit_sha256": "1" * 64,
                            "git_tree_id": "2" * 40,
                            "package_manifest_sha256": "3" * 64,
                        },
                        "package": {
                            "payload_tree_sha256": "4" * 64,
                            "payload_file_count": 4,
                            "payload_paths_sha256": "5" * 64,
                            "tree_digest_algorithm": "goal-teams-package-payload-tree-v1",
                            "tree_digest_excludes": [
                                "references/okf-conformance-manifest.json"
                            ],
                            "full_tree_binding": "release_or_install_identity_receipt",
                        },
                        "policy": {
                            "path": "references/okf-conformance-policy.json",
                            "sha256": _sha256(
                                root / "references" / "okf-conformance-policy.json"
                            ),
                        },
                        "checkers": [
                            {
                                "path": "scripts/v23/okf_conformance.py",
                                "sha256": _sha256(root / "scripts/v23/okf_conformance.py"),
                            },
                            {
                                "path": "scripts/checks/check-okf.py",
                                "sha256": _sha256(root / "scripts/checks/check-okf.py"),
                            },
                        ],
                        "markdown_entries": [
                            {
                                "path": "references/valid.md",
                                "class": "A",
                                "rule_id": "A_REFERENCE",
                                "contract_id": "unspecified",
                                "size": target.stat().st_size,
                                "sha256": _sha256(target),
                            }
                        ],
                        "forbidden_roots": ["docs", "develops", "GoalTeamsWork-*"],
                        "generation": {
                            "builder_id": "goal-teams-release-builder",
                            "builder_version": "V2.39",
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            proc, payload = _run("--root", str(root), "--manifest", str(manifest))
            self.assertEqual(proc.returncode, 0, payload)
            self.assertEqual(payload["package_completeness_state"], "unavailable")
            target.write_text(
                target.read_text(encoding="utf-8") + "mutation\n", encoding="utf-8"
            )
            proc, payload = _run("--root", str(root), "--manifest", str(manifest))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertTrue(
                any(
                    finding.get("error_code") == "E_OKF_ARTIFACT_HASH_STALE"
                    and finding.get("path") == "references/valid.md"
                    for finding in payload["findings"]
                )
            )

    def test_package_tree_requires_canonical_manifest_and_detects_missing_extra_hash_forbidden(self) -> None:
        self.require_checker()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_package_tree(root)
            self.assertFalse((root / ".git").exists())
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertEqual(proc.returncode, 0, payload)
            self.assertEqual(payload["package_completeness_state"], "complete")

            (root / "references" / "valid.md").unlink()
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertTrue(
                any(item.get("error_code") == "E_OKF_PACKAGE_MISSING" for item in payload["findings"])
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_package_tree(root)
            (root / "references" / "extra.md").write_text(
                (FIXTURES / "valid.md").read_text(encoding="utf-8"), encoding="utf-8"
            )
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertTrue(
                any(item.get("error_code") == "E_OKF_PACKAGE_EXTRA" for item in payload["findings"])
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_package_tree(root)
            (root / "evil.bin").write_bytes(b"not in the installer allowlist\n")
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertTrue(
                any(
                    item.get("error_code") == "E_OKF_PACKAGE_EXTRA"
                    and item.get("path") == "evil.bin"
                    for item in payload["findings"]
                )
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_package_tree(root)
            (root / "undeclared-link").symlink_to(root / "VERSION")
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertTrue(
                any(
                    item.get("error_code") == "E_OKF_PACKAGE_FORBIDDEN_PATH"
                    and item.get("path") == "undeclared-link"
                    for item in payload["findings"]
                )
            )

        with tempfile.TemporaryDirectory() as td:
            container = Path(td)
            root = container / "package"
            manifest = _prepare_package_tree(root)
            outside = container / "outside-manifest.json"
            outside.write_bytes(manifest.read_bytes())
            manifest.unlink()
            manifest.symlink_to(outside)
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertNotEqual(proc.returncode, 0, payload)
            self.assertIn(
                payload.get("error_code")
                or next(
                    (item.get("error_code") for item in payload.get("findings", [])),
                    None,
                ),
                {"E_OKF_PACKAGE_MISSING", "E_OKF_PACKAGE_FORBIDDEN_PATH"},
            )

        for mutation in (
            "unknown_top",
            "canonicalization",
            "full_tree_binding",
            "markdown_contract_id",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                manifest_path = _prepare_package_tree(root)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if mutation == "unknown_top":
                    manifest["attacker_claim"] = True
                elif mutation == "canonicalization":
                    manifest["canonicalization"] = "not-canonical"
                elif mutation == "full_tree_binding":
                    manifest["package"]["full_tree_binding"] = "none"
                else:
                    manifest["markdown_entries"][0]["contract_id"] = "attacker-contract"
                manifest_path.write_text(
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n",
                    encoding="utf-8",
                )
                proc, payload = _run(
                    "--root", str(root), "--package-tree", str(root)
                )
                self.assertEqual(proc.returncode, 1, payload)
                expected_code = (
                    "E_OKF_MANIFEST_CLASS_STALE"
                    if mutation == "markdown_contract_id"
                    else "E_OKF_MANIFEST_SCHEMA"
                )
                self.assertTrue(
                    any(
                        item.get("error_code") == expected_code
                        for item in payload["findings"]
                    )
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_package_tree(root)
            target = root / "references" / "valid.md"
            target.write_text(target.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertTrue(
                any(item.get("error_code") == "E_OKF_PACKAGE_HASH_DRIFT" for item in payload["findings"])
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_package_tree(root)
            forbidden = root / "docs" / "secret.md"
            forbidden.parent.mkdir()
            forbidden.write_text("secret\n", encoding="utf-8")
            proc, payload = _run("--root", str(root), "--package-tree", str(root))
            self.assertEqual(proc.returncode, 1, payload)
            self.assertTrue(
                any(item.get("error_code") == "E_OKF_PACKAGE_FORBIDDEN_PATH" for item in payload["findings"])
            )

    def test_gitless_direct_okf_checker_and_wrapper_do_not_write_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_package_tree(root)
            self.assertFalse((root / ".git").exists())
            for relative in ("scripts/checks/check-okf.py", "scripts/check-okf.py"):
                with self.subTest(relative=relative):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(root / relative),
                            "--root",
                            str(root),
                            "--package-tree",
                            str(root),
                        ],
                        cwd=root,
                        env=_no_bytecode_environment(),
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    try:
                        payload = json.loads(result.stdout)
                    except json.JSONDecodeError as exc:
                        raise AssertionError(
                            f"checker must emit JSON: {result.stdout!r} {result.stderr!r}"
                        ) from exc
                    self.assertEqual(result.returncode, 0, payload)
                    self.assertTrue(payload.get("passed"), payload)
                    self.assertEqual(_bytecode_paths(root), [])

    def test_install_manifest_excludes_local_only_surfaces(self) -> None:
        self.require_checker()

        package_manifest = (
            ROOT / "scripts" / "install" / "package-manifest.txt"
        ).read_text(encoding="utf-8")
        forbidden = ("docs/", "develops/", "GoalTeamsWork-", "release/versions/")
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, package_manifest)
        self.assertIn("prefix references/", package_manifest)
        self.assertIn("prefix scripts/", package_manifest)
        self.assertIn("prefix tests/v23/", package_manifest)


if __name__ == "__main__":
    unittest.main()
