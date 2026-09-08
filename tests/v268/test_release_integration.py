"""Current V2.68 release registration, denominator and installed-path contract."""

from __future__ import annotations

import importlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None: raise RuntimeError(relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV268ReleaseIntegration(unittest.TestCase):
    def test_profile_registers_target_predecessor_and_one_time_authorization(self) -> None:
        config = importlib.import_module("scripts.release.release_config")
        profile = config.release_config("V2.68")
        self.assertEqual("V2.68", config.ACTIVE_VERSION)
        self.assertEqual("V2.67", profile["published_before"])
        self.assertEqual("codex/develop-v2.68", profile["candidate_branch"])
        self.assertEqual("v2.68", profile["tag"])
        self.assertEqual("project_start_authorization_reused", profile["approval_model"])
        self.assertFalse(profile["external_writes_allowed"])
        self.assertEqual("V2.5", profile["core_policy_version"])
        self.assertEqual("V2.3", profile["legacy_data_schema_version"])
        with self.assertRaises(ValueError): config.release_config("V2.999")

    def test_identity_and_contract_use_published_v267_not_old_constant(self) -> None:
        from tests.v268.test_release_predecessor import EXPECTED_IDENTITY, canonical
        identity = importlib.import_module("scripts.v268.release_identity")
        self.assertEqual("V2.68", identity.TARGET_PRODUCT_VERSION)
        self.assertEqual("V2.67", identity.PREDECESSOR_PRODUCT_VERSION)
        contract = json.loads((ROOT / identity.PREDECESSOR_RELEASE_IDENTITY_PATH).read_text())
        self.assertEqual(EXPECTED_IDENTITY, contract["release_identity"])
        self.assertEqual(canonical(EXPECTED_IDENTITY), contract["release_identity_sha256"])

    def test_checker_and_flow_enforce_v268_denominator_without_predecessor_execution(self) -> None:
        checker = load("scripts/checks/check-v268.py", "_v268_test_checker")
        self.assertEqual(("tests/v250", "tests/v268"), checker.CURRENT_TEST_ROOTS)
        self.assertEqual(["tests/v267"], checker.PUBLISHED_PREDECESSOR_TEST_ROOTS)
        self.assertTrue(checker.validate_contracts()["passed"])
        manifest = json.loads((ROOT / "references/current/generations/V2.68/contracts/release-command-manifest.json").read_text())
        denominator = manifest["release"]["s1"]["current_full_regression_denominator"]
        self.assertEqual(["tests/v250", "tests/v268"], denominator["test_roots"])
        self.assertEqual(["tests/v267"], denominator["published_predecessor_test_roots"])
        self.assertEqual(0, denominator["predecessor_test_invocation_limit"])
        flow = importlib.import_module("scripts.v268.release_flow")
        self.assertEqual("V2.68", flow.CURRENT_RELEASE_VERSION)
        self.assertTrue(flow._validate_full_regression_receipt({}, "1" * 40, "2" * 40))

    def test_security_targets_bind_output_implementation_and_release_engine(self) -> None:
        runner = load("scripts/checks/run-v268-release-security-review.py", "_v268_test_security")
        flow = importlib.import_module("scripts.v268.release_flow")
        manifest = json.loads((ROOT / "references/current/generations/V2.68/contracts/release-security-review-manifest.json").read_text())
        targets = {row["path"] for row in manifest["review_targets"]}
        self.assertEqual(targets, set(runner.MANDATORY_REVIEW_TARGETS))
        self.assertEqual(targets, set(flow.V250_SECURITY_REQUIRED_TARGET_PATHS))
        for path in ("scripts/v268/output_gateway.py", "scripts/v268/output_dashboard.py", "scripts/v268/specification_delivery.py", "scripts/v268/installed_predecessor.py", "scripts/v268/runtime_transition.py", "scripts/v268/s4_executor.py"):
            self.assertIn(path, targets)

    def test_generic_builder_validator_and_flow_register_v268_without_changing_core(self) -> None:
        builder = load("scripts/release/build-release.py", "_v268_test_builder")
        validator = load("scripts/release/validate-release.py", "_v268_test_validator")
        release = importlib.import_module("scripts.release.skill_release")
        self.assertTrue(builder.validate_release_version("V2.68")["ok"])
        for module in (builder, validator):
            self.assertIn("V2.68", module.STRICT_SNAPSHOT_VERSIONS)
            self.assertEqual("v250", module.okf_runtime_generation("V2.68"))
        self.assertEqual("V2.68", release.ACTIVE_SIMPLE_VERSION)
        self.assertEqual("V2.68", release._release_flow_module("V2.68").CURRENT_RELEASE_VERSION)
        with self.assertRaises(release.SkillReleaseError): release._release_flow_module("V2.67")
        static = release.runtime_static_input_paths("V2.68")
        self.assertIn("scripts/v268/release_identity.py", static)
        self.assertIn("scripts/v268/runtime_transition.py", static)
        self.assertIn("schemas/v2.68/runtime-transition-receipt.schema.json", static)

    def test_installer_and_check_dispatch_have_explicit_v268_route(self) -> None:
        installer = (ROOT / "scripts/install/install-local.sh").read_text()
        dispatcher = (ROOT / "scripts/checks/check.sh").read_text()
        self.assertTrue('active_generation_id == "V2.68"' in installer, "V2.68 installer generation route missing")
        self.assertTrue('"check-v268.py"' in installer, "V2.68 installer checker missing")
        self.assertTrue('"V2.68"' in dispatcher, "V2.68 root dispatch missing")
        self.assertTrue("scripts/checks/check-v268.py" in dispatcher, "V2.68 root checker missing")
        self.assertTrue("--route-facts-receipt" in dispatcher, "root route triplet missing")


if __name__ == "__main__": unittest.main()
