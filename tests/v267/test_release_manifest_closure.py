"""V2.67 release-only identity and manifest closure Red denominator."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.release import release_config


ROOT = Path(__file__).resolve().parents[2]
TARGET = "V2.67"
PREDECESSOR = "V2.66"
GENERATION = ROOT / "references/current/generations/V2.67"
PUBLISHED_V266_IDENTITY = {
    "tag": "v2.66",
    "release_id": 377935171,
    "state": "published",
    "source_commit": "a9925d787afaf428e20caa2058641da49c6d89d4",
    "source_tree": "8d62a263584c9772d8f94d85cf9d5272efd2ec29",
    "public_assets": [
        "goal-teams-V2.66.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    ],
}
V267_ASSETS = [
    "goal-teams-V2.67.tar.gz",
    "SHA256SUMS",
    "_release.json",
    "_files.sha256",
]


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class TestV267ReleaseManifestClosure(unittest.TestCase):
    def _json(self, relative: str) -> dict[str, object]:
        path = ROOT / relative
        self.assertTrue(path.is_file(), f"E_TEST_V267_RELEASE_FILE_MISSING:{relative}")
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(value, dict, relative)
        return value

    def test_release_profile_and_predecessor_identity_are_registered(self) -> None:
        profile_path = ROOT / "references/release-profiles/v2.67.json"
        self.assertTrue(
            profile_path.is_file(), "E_TEST_V267_RELEASE_PROFILE_MISSING"
        )
        try:
            profile = release_config.release_config(TARGET)
        except ValueError as exc:
            self.fail(f"E_TEST_V267_RELEASE_PROFILE_UNREGISTERED:{exc}")

        self.assertEqual(TARGET, profile["version"])
        self.assertEqual(PREDECESSOR, profile["published_before"])
        self.assertEqual("v2.67", profile["tag"])
        self.assertEqual("codex/develop-v2.67", profile["candidate_branch"])
        self.assertEqual("V2.5", profile["core_policy_version"])
        self.assertEqual("V2.3", profile["legacy_data_schema_version"])
        self.assertFalse(profile["external_writes_allowed"])

        predecessor = self._json(
            "references/current/generations/V2.67/contracts/"
            "predecessor-release-identity.json"
        )
        self.assertEqual(
            "goal-teams-predecessor-release-identity-v2.67",
            predecessor["schema_version"],
        )
        self.assertEqual(TARGET, predecessor["generation_id"])
        self.assertEqual(PREDECESSOR, predecessor["predecessor_product_version"])
        self.assertEqual(PUBLISHED_V266_IDENTITY, predecessor["release_identity"])
        self.assertEqual(
            _canonical_sha256(PUBLISHED_V266_IDENTITY),
            predecessor["release_identity_sha256"],
        )

    def test_release_manifests_define_exact_v267_s0_s4_contract(self) -> None:
        public = self._json(
            "references/current/generations/V2.67/contracts/public-asset-map.json"
        )
        command = self._json(
            "references/current/generations/V2.67/contracts/"
            "release-command-manifest.json"
        )
        route = self._json(
            "references/current/generations/V2.67/contracts/"
            "release-route-manifest.json"
        )
        security = self._json(
            "references/current/generations/V2.67/contracts/"
            "release-security-review-manifest.json"
        )

        self.assertEqual(TARGET, public["version"])
        self.assertEqual(4, public["asset_count"])
        self.assertEqual(V267_ASSETS, [item["name"] for item in public["assets"]])
        self.assertEqual("release/versions/V2.67", public["source_root"])
        self.assertFalse(public["additional_public_assets_allowed"])

        self.assertEqual(TARGET, command["generation_id"])
        denominator = command["release"]["s1"]["current_full_regression_denominator"]
        self.assertEqual(["tests/v250", "tests/v267"], denominator["test_roots"])
        self.assertEqual(
            ["tests/v266"], denominator["published_predecessor_test_roots"]
        )
        self.assertEqual(0, denominator["predecessor_test_invocation_limit"])
        self.assertEqual(1, command["release"]["s2"]["build_invocation_limit_per_asset_set"])
        self.assertEqual(0, command["release"]["s2"]["security_check_invocation_limit"])
        self.assertEqual(
            0,
            command["release"]["s2"]["reproducibility_comparison_invocation_limit"],
        )
        self.assertEqual(0, command["release"]["s4"]["external_write_invocation_count"])

        self.assertEqual(TARGET, route["generation_id"])
        self.assertEqual(
            "V2.67_current_generation_only",
            route["release_readiness"]["s1_full_regression_scope"],
        )
        self.assertTrue(route["repository_boundary"]["required_before_s4"])
        self.assertEqual(TARGET, security["generation_id"])
        self.assertEqual("release", security["workflow_phase"])
        self.assertEqual(1, security["invocation_limit_per_released_identity"])
        self.assertFalse(security["s2_security_substitute"])

    def test_current_projection_is_v267_candidate_or_final_without_prebuild(self) -> None:
        current = self._json("release/current/manifest.json")
        if current.get("product_version") == PREDECESSOR:
            self.assertEqual(TARGET, current.get("candidate_product_version"))
            self.assertEqual(
                "development_candidate_not_published",
                current.get("candidate_release_state"),
            )
            self.assertEqual(
                "references/release-profiles/v2.67.json",
                current.get("candidate_profile"),
            )
            self.assertEqual(PUBLISHED_V266_IDENTITY, current["release_identity"])
        else:
            self.assertEqual(TARGET, current.get("product_version"))
            self.assertEqual(
                "goal-teams-release-manifest-v2.67", current.get("schema_version")
            )
            self.assertEqual("v2.67", current["release_identity"]["tag"])
            self.assertEqual("published", current["release_identity"]["state"])

        self.assertFalse(
            (ROOT / "release/versions/V2.67").exists(),
            "Development must not prebuild the formal V2.67 S2 snapshot",
        )


if __name__ == "__main__":
    unittest.main()
