from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.release import skill_release
from tests.v250.test_release_control import SOURCE, TREE, checkpoint_fixture


class TestV263ContinuationRouteTriplet(unittest.TestCase):
    def test_formal_receipt_set_is_version_aware_without_predecessor_drift(
        self,
    ) -> None:
        predecessor = skill_release.V249_CONTINUATION_FORMAL_RECEIPTS
        self.assertEqual(predecessor, skill_release.V250_CONTINUATION_FORMAL_RECEIPTS)
        for version in ("V2.49", "V2.50", "V2.52", "V2.6"):
            with self.subTest(version=version):
                self.assertEqual(
                    predecessor,
                    skill_release.continuation_formal_receipts(version),
                )

        for version in ("V2.63", "V2.66"):
            current = skill_release.continuation_formal_receipts(version)
            self.assertEqual(current, skill_release.V263_CONTINUATION_FORMAL_RECEIPTS)
            self.assertEqual(
                (
                    "release-route-facts.json",
                    "release-route-derived.json",
                    "release-route-receipt.json",
                ),
                tuple(name for name in current if name.startswith("release-route-")),
            )
            self.assertEqual(set(current), set(predecessor) | {
                "release-route-facts.json",
                "release-route-derived.json",
            })
        self.assertEqual(
            set(skill_release.V267_CONTINUATION_FORMAL_RECEIPTS),
            set(skill_release.V263_CONTINUATION_FORMAL_RECEIPTS)
            - {"controller-handoff.json", "github-owner-key-validation.json"},
        )

    def test_ready_checkpoint_exactly_binds_all_three_route_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt_root, release_root, outcomes = checkpoint_fixture(Path(temp))
            with (
                mock.patch.object(
                    skill_release,
                    "_read_identity",
                    return_value={"source_git_tree": TREE},
                ),
                mock.patch.object(
                    skill_release,
                    "validate_v250_s4_control",
                    return_value={"ok": True, "errors": []},
                ) as control_validator,
            ):
                checkpoint = skill_release.build_v250_continuation_checkpoint(
                    "V2.67",
                    SOURCE,
                    project_size="large",
                    job_status="success",
                    workflow_run_id="26301",
                    workflow_run_attempt="1",
                    gate_outcomes=outcomes,
                    receipt_source_root=receipt_root,
                    release_root=release_root,
                )
                control_validator.assert_called_once()
                control_validator.reset_mock()
                self.assertEqual("ready_for_s4", checkpoint["state"])
                self.assertEqual(
                    set(skill_release.V267_CONTINUATION_FORMAL_RECEIPTS),
                    set(checkpoint["formal_files"]),
                )

                (receipt_root / "_checkpoint.json").write_text(
                    json.dumps(checkpoint, sort_keys=True), encoding="utf-8"
                )
                route_facts_path = receipt_root / "release-route-facts.json"
                route_facts = json.loads(route_facts_path.read_text(encoding="utf-8"))
                route_facts["tampered"] = True
                route_facts_path.write_text(
                    json.dumps(route_facts, sort_keys=True), encoding="utf-8"
                )
                forged = copy.deepcopy(checkpoint)
                forged["formal_files"][route_facts_path.name] = {
                    "size": route_facts_path.stat().st_size,
                    "sha256": hashlib.sha256(route_facts_path.read_bytes()).hexdigest(),
                }
                forged.pop("checkpoint_sha256")
                forged["checkpoint_sha256"] = (
                    skill_release._release_flow_module("V2.67").canonical_sha256(
                        forged
                    )
                )
                verdict = skill_release.validate_v250_continuation_checkpoint(
                    "V2.67",
                    SOURCE,
                    forged,
                    receipt_root=receipt_root,
                    release_root=release_root,
                    expected_workflow_run_id="26301",
                    expected_workflow_run_attempt="1",
                )
                control_validator.assert_called_once()

            self.assertFalse(verdict["passed"])
            self.assertIn(
                "E_V263_CONTINUATION_ROUTE_TRIPLET_BINDING",
                verdict["errors"],
            )


if __name__ == "__main__":
    unittest.main()
