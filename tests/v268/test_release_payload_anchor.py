"""OB-R04-001: production captures and transport bind the published V2.67 payload.

These cases deliberately use the unpatched production policy. They are not
mechanism fixtures and must not inherit the small-file TEST anchor override.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from tests.v268.test_release_predecessor import EXPECTED_IDENTITY, authorization, canonical, installed_fixture


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ANCHOR = {
    "package_file_count": 344,
    "package_files_sha256": "c7d15802c74c6d75802aed3806426610a470da31b69169ca25af6e574f941670",
    "package_manifest_sha256": "a73f9ce1b0f0177391f74dcab21735930d10a45ae4d0ff5d54ce71a1f5625a9a",
}


def transport_receipt() -> dict:
    """Synthetic transport data with independently fixed public payload digests."""
    auth = authorization()
    value = {
        "schema_version": "goal-teams-v2.68-installed-predecessor-observation-v1",
        "repository": "vibe-coding-era/goal-teams", "repository_id": "1249985345",
        "target_product_version": "V2.68", "predecessor_product_version": "V2.67",
        "release_identity": EXPECTED_IDENTITY, "authorization_id": auth["authorization_id"],
        "authorization_intent_sha256": auth["intent_sha256"], "captured_at": "2026-09-08T00:01:00+00:00",
        "state_raw_sha256": "a" * 64, "package_manifest_sha256": EXPECTED_ANCHOR["package_manifest_sha256"],
        "expected_file_set_sha256": EXPECTED_ANCHOR["package_files_sha256"],
        "observed_file_set_sha256": EXPECTED_ANCHOR["package_files_sha256"],
        "package_file_count": 344, "extra_file_count": 0, "strict_payload_check": "passed",
        "observation_source": "observed_on_authorized_local_host", "actor_assurance": "I1", "actor_relationship": "correlated",
    }
    value["receipt_sha256"] = canonical(value)
    return value


class TestPublishedPayloadAnchor(unittest.TestCase):
    def setUp(self) -> None:
        self.target = importlib.import_module("scripts.v268.installed_predecessor")
        self.temp = tempfile.TemporaryDirectory(prefix=".v268-public-payload-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installation, self.state_path, self.state = installed_fixture(self.root)

    def capture(self) -> dict:
        return self.target.capture_installed_predecessor(installation_root=self.installation, state_path=self.state_path, authorization=authorization(), expected_identity=EXPECTED_IDENTITY, captured_at="2026-09-08T00:01:00+00:00")

    def test_default_policy_is_the_fixed_immutable_published_payload(self) -> None:
        self.assertEqual(EXPECTED_ANCHOR, dict(self.target.PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR))
        with self.assertRaises(TypeError): self.target.PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_file_count"] = 2
        self.assertNotIn("payload_anchor", inspect.signature(self.target.capture_installed_predecessor).parameters)
        self.assertNotIn("payload_anchor", inspect.signature(self.target.validate_installed_predecessor).parameters)

    def test_two_files_and_arbitrary_allowlist_digest_cannot_claim_production_payload(self) -> None:
        with self.assertRaises(ValueError): self.capture()

    def test_matching_state_and_modified_payload_are_still_rejected(self) -> None:
        target = self.installation / "SKILL.md"
        target.write_text("# Replaced payload\n", encoding="utf-8")
        row = next(row for row in self.state["package_files"] if row["path"] == "SKILL.md")
        row.update(sha256=hashlib.sha256(target.read_bytes()).hexdigest(), size=target.stat().st_size)
        self.state["package_manifest_sha256"] = EXPECTED_ANCHOR["package_manifest_sha256"]
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        with self.assertRaises(ValueError): self.capture()

    def test_deleted_file_and_deleted_state_entry_do_not_shrink_the_oracle(self) -> None:
        # A caller leaves just the two mandatory names and removes the declared
        # remainder; a self-consistent subset must not count as the release.
        removed = self.installation / "removed.md"
        removed.write_bytes(b"was part of the claimed payload")
        self.state["package_files"].append({"path": "removed.md", "mode": 0o644, "size": removed.stat().st_size, "sha256": hashlib.sha256(removed.read_bytes()).hexdigest()})
        removed.unlink()
        self.state["package_files"] = [row for row in self.state["package_files"] if row["path"] != "removed.md"]
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        with self.assertRaises(ValueError): self.capture()

    def test_production_shaped_transport_is_accepted_as_correlated_only(self) -> None:
        verdict = self.target.validate_installed_predecessor(transport_receipt(), authorization=authorization(), expected_identity=EXPECTED_IDENTITY)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual("I1", verdict["actor_assurance"])
        self.assertEqual("correlated", verdict["actor_relationship"])

    def test_resealed_transport_cannot_override_published_digest_count_or_allowlist(self) -> None:
        variations = [
            {"package_file_count": 2},
            {"package_manifest_sha256": "b" * 64},
            {"expected_file_set_sha256": "b" * 64, "observed_file_set_sha256": "b" * 64},
            {"package_file_count": 2, "expected_file_set_sha256": "b" * 64, "observed_file_set_sha256": "b" * 64, "package_manifest_sha256": "b" * 64},
        ]
        for change in variations:
            with self.subTest(change=change):
                value = {**copy.deepcopy(transport_receipt()), **change}
                value["receipt_sha256"] = canonical({key: item for key, item in value.items() if key != "receipt_sha256"})
                verdict = self.target.validate_installed_predecessor(value, authorization=authorization(), expected_identity=EXPECTED_IDENTITY)
                self.assertFalse(verdict["ok"], "self-sealing cannot supply the production payload oracle")


if __name__ == "__main__": unittest.main()
