from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = PACKAGE_ROOT / "runtime" / "validate_member.py"
SPEC = importlib.util.spec_from_file_location("validate_member_under_test", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ValidateMemberTests(unittest.TestCase):
    def copy_package(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        target = Path(temporary.name) / "release-engineer"
        shutil.copytree(PACKAGE_ROOT, target)
        return temporary, target

    def test_canonical_package_passes(self) -> None:
        report = validator.validate_package(PACKAGE_ROOT)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["language_adapter_count"], 10)
        self.assertEqual(report["environment_count"], 5)
        self.assertEqual(report["surface_count"], 4)

    def test_missing_required_file_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            (target / "workflow.md").unlink()
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_MEMBER_FILE_MISSING" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_required_file_symlink_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            prompt = target / "prompt.md"
            replacement = target / "prompt-real.md"
            prompt.rename(replacement)
            prompt.symlink_to(replacement.name)
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(
                any(
                    item["error_code"] == "E_V245_MEMBER_FILE_MISSING"
                    for item in report["errors"]
                )
            )
        finally:
            temporary.cleanup()

    def test_member_version_is_v245(self) -> None:
        temporary, target = self.copy_package()
        try:
            (target / "VERSION").write_text("V2.44\n", encoding="utf-8")
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_MEMBER_FILE_INVALID" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_duplicate_kit_id_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            catalog_path = target / "kits" / "catalog.json"
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog["language_adapters"][1]["id"] = catalog["language_adapters"][0]["id"]
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_KIT_ID_DUPLICATE" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_template_must_not_be_executable(self) -> None:
        temporary, target = self.copy_package()
        try:
            template = target / "kits" / "templates" / "common" / "00-preflight.sh.tpl"
            template.chmod(0o750)
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_RE_TEMPLATE_EXECUTION_FORBIDDEN" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_missing_environment_plan_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            (target / "kits" / "plans" / "environments" / "production.json").unlink()
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_KIT_PATH_UNSAFE" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_invalid_surface_plan_json_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            plan = target / "kits" / "plans" / "surfaces" / "wechat-miniprogram.json"
            plan.write_text("{", encoding="utf-8")
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_KIT_CATALOG_MISSING" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_fixed_member_id_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            prompt = target / "prompt.md"
            prompt.write_text(prompt.read_text(encoding="utf-8") + "\n默认 member id: fixed\n", encoding="utf-8")
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_MEMBER_IDENTITY_INVALID" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_full_test_command_in_template_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            template = target / "kits" / "templates" / "common" / "40-toolchain-build.sh.tpl"
            template.write_text(template.read_text(encoding="utf-8") + "\ncargo test\n", encoding="utf-8")
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["error_code"] == "E_V245_RE_FULL_TEST_EXECUTION_FORBIDDEN" for item in report["errors"]))
        finally:
            temporary.cleanup()

    def test_toolchain_action_semantic_drift_fails(self) -> None:
        temporary, target = self.copy_package()
        try:
            manifest_path = (
                target / "kits" / "plans" / "toolchain-actions-v1.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            action = next(
                item
                for item in manifest["actions"]
                if item["id"] == "prefetch-java-maven-v1"
            )
            action["language"] = "node"
            action["build_tool"] = "yarn"
            action["phase"] = "build"
            action["network_policy"] = "network_allowed"
            action["full_test_execution_count"] = 1
            manifest["execution_contract"]["network_policy"]["build"] = (
                "network_allowed"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = validator.validate_package(target)
            self.assertFalse(report["passed"])
            self.assertTrue(
                any(
                    item["error_code"] == "E_V245_KIT_CATALOG_MISSING"
                    for item in report["errors"]
                )
            )
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
