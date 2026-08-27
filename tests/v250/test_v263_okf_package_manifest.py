"""V2.65 OKF package-manifest runtime identity contracts."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_conformance


MODERN_RUNTIME_VERSIONS = (
    "V2.50",
    "V2.52",
    "V2.6",
    "V2.63",
    "V2.65",
    "V2.66",
)
ROOT = Path(__file__).resolve().parents[2]


class V265OkfPackageManifestTests(unittest.TestCase):
    def _staged_tree(
        self,
        root: Path,
        version: str,
        *,
        include_v23: bool = True,
    ) -> Path:
        policy = root / "references" / "okf-conformance-policy.json"
        policy.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "references" / "okf-conformance-policy.json", policy)
        (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")

        checker_paths = [
            "scripts/v250/okf_conformance.py",
            "scripts/checks/check-okf.py",
        ]
        if include_v23:
            checker_paths.insert(0, "scripts/v23/okf_conformance.py")
        for relative in checker_paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"# synthetic {relative}\n", encoding="utf-8")

        package_manifest = root / "scripts" / "install" / "package-manifest.txt"
        package_manifest.parent.mkdir(parents=True, exist_ok=True)
        package_manifest.write_text(
            "\n".join(
                [
                    "file VERSION",
                    "file references/okf-conformance-policy.json",
                    *(f"file {relative}" for relative in checker_paths),
                    "file scripts/install/package-manifest.txt",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return package_manifest

    def _build(
        self,
        root: Path,
        version: str,
        *,
        include_v23: bool = True,
    ) -> dict[str, object]:
        package_manifest = self._staged_tree(
            root,
            version,
            include_v23=include_v23,
        )
        return okf_conformance.build_package_manifest(
            root,
            okf_conformance.load_policy(root),
            source_binding={
                "commit_sha256": "1" * 40,
                "git_tree_id": "2" * 40,
                "package_manifest_sha256": hashlib.sha256(
                    package_manifest.read_bytes()
                ).hexdigest(),
            },
        )

    def _write_and_validate(
        self,
        root: Path,
        manifest: dict[str, object],
    ) -> dict[str, object]:
        target = root / okf_conformance.DEFAULT_PACKAGE_MANIFEST_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return okf_conformance.validate_manifest(
            root,
            okf_conformance.load_policy(root),
            target,
            require_complete_package=True,
        )

    def test_build_manifest_selects_v250_for_every_modern_product_identity(self) -> None:
        for version in MODERN_RUNTIME_VERSIONS:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                manifest = self._build(Path(td), version)
                self.assertEqual(version, manifest["product_version"])
                self.assertEqual(
                    {
                        "builder_id": "goal-teams-release-builder",
                        "builder_version": version,
                    },
                    manifest["generation"],
                )
                self.assertEqual(
                    [
                        "scripts/v250/okf_conformance.py",
                        "scripts/checks/check-okf.py",
                    ],
                    [entry["path"] for entry in manifest["checkers"]],
                )

    def test_build_manifest_keeps_v239_on_the_frozen_v23_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest = self._build(Path(td), "V2.39")
        self.assertEqual("V2.39", manifest["product_version"])
        self.assertEqual("V2.39", manifest["generation"]["builder_version"])
        self.assertEqual(
            ["scripts/v23/okf_conformance.py", "scripts/checks/check-okf.py"],
            [entry["path"] for entry in manifest["checkers"]],
        )

    def test_build_manifest_rejects_an_unmapped_product_instead_of_falling_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(
                okf_conformance.OkfError,
                "E_OKF_PRODUCT_VERSION",
            ):
                self._build(Path(td), "V9.99")

    def test_build_manifest_rejects_a_missing_product_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._staged_tree(root, "V2.65")
            (root / "VERSION").unlink()
            with self.assertRaisesRegex(
                okf_conformance.OkfError,
                "E_OKF_PRODUCT_VERSION",
            ):
                okf_conformance.build_package_manifest(
                    root,
                    okf_conformance.load_policy(root),
                )

    def test_complete_package_round_trip_uses_the_registered_runtime(self) -> None:
        for version in (*MODERN_RUNTIME_VERSIONS, "V2.39"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                verdict = self._write_and_validate(root, self._build(root, version))
                self.assertTrue(verdict["passed"], verdict["findings"])
                self.assertEqual("complete", verdict["package_completeness_state"])

    def test_v265_current_only_package_does_not_require_the_v23_checker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._build(root, "V2.65", include_v23=False)
            verdict = self._write_and_validate(root, manifest)
        self.assertTrue(verdict["passed"], verdict["findings"])

    def test_validation_rejects_unknown_or_missing_product_identity(self) -> None:
        for require_complete_package in (False, True):
            for version in ("V2.51", None):
                with (
                    self.subTest(
                        version=version,
                        require_complete_package=require_complete_package,
                    ),
                    tempfile.TemporaryDirectory() as td,
                ):
                    root = Path(td)
                    manifest = self._build(root, "V2.65")
                    if version is None:
                        (root / "VERSION").unlink()
                    else:
                        (root / "VERSION").write_text(
                            f"{version}\n", encoding="utf-8"
                        )
                        manifest["product_version"] = version
                        manifest["generation"] = {
                            "builder_id": "goal-teams-release-builder",
                            "builder_version": None,
                        }
                    target = root / okf_conformance.DEFAULT_PACKAGE_MANIFEST_PATH
                    self._write_and_validate(root, manifest)
                    verdict = okf_conformance.validate_manifest(
                        root,
                        okf_conformance.load_policy(root),
                        target,
                        require_complete_package=require_complete_package,
                    )
                    self.assertFalse(verdict["passed"])
                    self.assertIn(
                        "E_OKF_PRODUCT_VERSION",
                        {finding["error_code"] for finding in verdict["findings"]},
                    )

    def test_manifest_mode_round_trip_uses_the_registered_runtime(self) -> None:
        for version in ("V2.65", "V2.39"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                manifest = self._build(
                    root,
                    version,
                    include_v23=version == "V2.39",
                )
                target = root / okf_conformance.DEFAULT_PACKAGE_MANIFEST_PATH
                self._write_and_validate(root, manifest)
                verdict = okf_conformance.validate_manifest(
                    root,
                    okf_conformance.load_policy(root),
                    target,
                    require_complete_package=False,
                )
                self.assertTrue(verdict["passed"], verdict["findings"])


if __name__ == "__main__":
    unittest.main()
