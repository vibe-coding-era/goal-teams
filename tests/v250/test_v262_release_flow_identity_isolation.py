from __future__ import annotations

import unittest

from scripts.v250 import release_flow


class TestV262ReleaseFlowIdentityIsolation(unittest.TestCase):
    def test_low_level_authorization_rejects_predecessor_version(self) -> None:
        verdict = release_flow.validate_project_start_authorization(
            {},
            repository="vibe-coding-era/goal-teams",
            version="V2.6",
            candidate_branch="codex/develop-v2.6",
            tag="v2.6",
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_RELEASE_VERSION", verdict["errors"])

    def test_low_level_control_builder_rejects_predecessor_before_chain(self) -> None:
        with self.assertRaisesRegex(ValueError, "E_V250_RELEASE_VERSION"):
            release_flow.build_release_control_receipt(
                repository="vibe-coding-era/goal-teams",
                version="V2.6",
                project_size="large",
                candidate_branch="codex/develop-v2.6",
                tag="v2.6",
                source_commit="1" * 40,
                source_tree="2" * 40,
                authorization_receipt={},
                released_runtime_transition={},
                s0={},
                full_regression={},
                release_security_review={},
                s1={},
                s2={},
                asset_integrity_validation={},
                s3={},
                repository_boundary={},
                external_anchor_validation={},
            )

    def test_low_level_control_validator_rejects_predecessor_expectation(self) -> None:
        verdict = release_flow.validate_release_control_receipt(
            {},
            expected_repository="vibe-coding-era/goal-teams",
            expected_version="V2.6",
            expected_candidate_branch="codex/develop-v2.6",
            expected_tag="v2.6",
            expected_source_commit="1" * 40,
            expected_source_tree="2" * 40,
        )
        self.assertFalse(verdict["ok"])
        self.assertFalse(verdict["publish_allowed"])
        self.assertIn("E_V250_RELEASE_VERSION", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
