"""Predecessor observation and fresh launch are distinct V2.68 time axes."""

from __future__ import annotations

import copy
import datetime as dt
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.v268.test_release_predecessor import EXPECTED_IDENTITY, authorization, canonical, installed_fixture, trusted_test_payload_policy


ROOT = Path(__file__).resolve().parents[2]


class TestV268ReleaseRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = importlib.import_module("scripts.v268.runtime_transition")
        self.target = importlib.import_module("scripts.v268.installed_predecessor")
        self.enterContext(trusted_test_payload_policy())
        self.temp = tempfile.TemporaryDirectory(prefix=".v268-runtime-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installation, self.state_path, _ = installed_fixture(self.root)
        self.auth = authorization()
        contract_path = self.root / self.runtime.PREDECESSOR_RELEASE_IDENTITY_PATH
        contract_path.parent.mkdir(parents=True)
        contract_path.write_text(json.dumps({"schema_version": "goal-teams-predecessor-release-identity-v2.68", "generation_id": "V2.68", "predecessor_product_version": "V2.67", "release_identity": EXPECTED_IDENTITY, "release_identity_sha256": canonical(EXPECTED_IDENTITY)}))

    def observation(self) -> dict:
        return self.target.capture_installed_predecessor(installation_root=self.installation, state_path=self.state_path, authorization=self.auth, expected_identity=EXPECTED_IDENTITY, captured_at="2026-09-08T00:01:00+00:00")

    def handoff(self, observation) -> dict:
        return self.runtime.build_authorized_local_predecessor_observation(source_commit="1" * 40, source_tree="2" * 40, authorization=self.auth, authorization_receipt_sha256="b" * 64, predecessor_observation=observation, root=self.root, issued_at="2026-09-08T02:00:00+00:00")

    def test_missing_observation_cannot_fall_back_to_repository_identity(self) -> None:
        with self.assertRaises(ValueError): self.handoff(None)

    def test_old_capture_and_fresh_launch_keep_separate_timestamps_and_binding(self) -> None:
        observation = self.observation()
        before = copy.deepcopy(observation)
        receipt = self.handoff(observation)
        self.assertEqual(before, observation)
        payload = receipt["signed_payload"]
        self.assertEqual("V2.67", payload["previous_controller_product_version"])
        self.assertEqual(observation, payload["installed_predecessor_observation"])
        self.assertEqual("2026-09-08T00:01:00+00:00", payload["installed_predecessor_observation"]["captured_at"])
        self.assertEqual("2026-09-08T02:00:00+00:00", payload["issued_at"])
        verdict = self.runtime.validate_controller_handoff(receipt, expected_source_commit="1" * 40, expected_source_tree="2" * 40, expected_authorization_id=self.auth["authorization_id"], expected_authorization_receipt_sha256="b" * 64, expected_authorization_intent_sha256=self.auth["intent_sha256"], validation_time=dt.datetime(2026, 9, 8, 2, 5, tzinfo=dt.timezone.utc), root=self.root)
        self.assertTrue(verdict["ok"], verdict)
        self.assertTrue(verdict["local_observation"])

    def test_resealed_foreign_observation_is_rejected(self) -> None:
        observation = self.observation()
        for field, value in (("authorization_id", "OTHER"), ("target_product_version", "V2.67"), ("extra_file_count", 1)):
            with self.subTest(field=field):
                changed = {**observation, field: value}
                changed["receipt_sha256"] = canonical({key: item for key, item in changed.items() if key != "receipt_sha256"})
                with self.assertRaises(ValueError): self.handoff(changed)

    def test_adapter_and_schema_require_predecessor_input_and_exact_v268_static_paths(self) -> None:
        adapter = (ROOT / "scripts/v268/runtime_host_adapter.py").read_text()
        self.assertIn("--predecessor-observation-receipt", adapter)
        self.assertEqual("V2.68", self.runtime.LOADED_RUNTIME_PRODUCT_VERSION)
        self.assertEqual("V2.67", self.runtime.PREVIOUS_CONTROLLER_PRODUCT_VERSION)
        self.assertIn("scripts/v268/release_identity.py", self.runtime.REQUIRED_STATIC_INPUT_PATHS)
        self.assertIn("scripts/checks/check-v268.py", self.runtime.REQUIRED_STATIC_INPUT_PATHS)
        schema = json.loads((ROOT / "schemas/v2.68/runtime-transition-receipt.schema.json").read_text())
        self.assertEqual({"const": "V2.68"}, schema["properties"]["generation_id"])
        local = schema["$defs"]["localPredecessorObservation"]["properties"]["signed_payload"]
        self.assertIn("installed_predecessor_observation", local["required"])


if __name__ == "__main__": unittest.main()
