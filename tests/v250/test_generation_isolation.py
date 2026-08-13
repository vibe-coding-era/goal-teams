from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.v250.freeze_v248_snapshot import materialize
from scripts.v250.generation_runtime import (
    GenerationLoadError,
    V250_CONTROL_SCHEMA_PATHS,
    _generation_required_control_paths,
    load_generation,
)


REPO = Path(__file__).resolve().parents[2]
HAS_REPLAY_SUPPLEMENT = (
    REPO / "references/current/generations/V2.48/activation-manifest.json"
).is_file() and (REPO / "references/legacy-replay/generations/V2.48/snapshot").is_dir()


class TestV250GenerationIsolation(unittest.TestCase):
    def test_closed_rollback_cannot_load_v248_through_current_loader(self) -> None:
        current = load_generation(REPO)
        self.assertEqual("closed", current["activation_manifest"]["rollback"]["window_status"])

        with self.assertRaises(GenerationLoadError) as caught:
            load_generation(REPO, generation_id="V2.48")

        self.assertEqual("E_V250_GENERATION_NOT_REACHABLE", caught.exception.code)

    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional V2.48 rollback supplement is not installed")
    def test_v248_snapshot_is_byte_identical_to_frozen_git_tree(self) -> None:
        receipt = materialize(REPO, write=False)

        self.assertTrue(receipt["passed"])
        self.assertEqual(38, receipt["member_count"])
        self.assertEqual([], receipt["errors"])

    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional V2.48 rollback supplement is not installed")
    def test_active_pointer_cannot_select_v248_baseline_snapshot(self) -> None:
        baseline_path = Path(
            "references/current/generations/V2.48/activation-manifest.json"
        )
        baseline_raw = (REPO / baseline_path).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / baseline_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(baseline_raw)
            active = {
                "schema_version": "goal-teams-active-generation-v1",
                "generation_id": "V2.48",
                "activation_manifest": baseline_path.as_posix(),
                "activation_manifest_sha256": hashlib.sha256(baseline_raw).hexdigest(),
                "state": "active_current",
                "updated_at": "2026-08-01T00:00:00+08:00",
            }
            active_path = root / "references/current/ACTIVE.json"
            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_path.write_text(
                json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            with self.assertRaises(GenerationLoadError) as caught:
                load_generation(root)

            self.assertEqual("E_V250_ACTIVE_STATE", caught.exception.code)

    def test_active_generation_binds_all_declared_current_control_assets(self) -> None:
        generation = load_generation(REPO)

        required = _generation_required_control_paths(generation["generation_id"])
        self.assertEqual(80, len(required))
        self.assertTrue(required.issubset(generation["member_digests"]))
        expected_schemas = {
            path.relative_to(REPO).as_posix()
            for path in (REPO / "schemas/v2.50").glob("*.json")
        }
        self.assertTrue(set(V250_CONTROL_SCHEMA_PATHS).issubset(expected_schemas))
        self.assertEqual(expected_schemas, set(generation["control_schemas"]))
        self.assertEqual(
            {"type": "boolean"},
            generation["control_schemas"]["schemas/v2.50/project-route.schema.json"][
                "properties"
            ]["s1_current"],
        )

    def test_bound_execution_asset_drift_fails_closed(self) -> None:
        generation = load_generation(REPO)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            required = {
                "references/current/ACTIVE.json",
                generation["activation_manifest_path"],
                *generation["member_paths"],
            }
            for relative in required:
                source = REPO / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            target = root / "scripts/v250/output_contract.py"
            target.write_bytes(target.read_bytes() + b"\n# drift\n")

            with self.assertRaises(GenerationLoadError) as caught:
                load_generation(root)

            self.assertEqual("E_V250_MEMBER_DIGEST_MISMATCH", caught.exception.code)

    def test_new_unbound_dynamic_control_asset_fails_closed(self) -> None:
        generation = load_generation(REPO)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            required = {
                "references/current/ACTIVE.json",
                generation["activation_manifest_path"],
                *generation["member_paths"],
            }
            for relative in required:
                source = REPO / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            unbound = root / "scripts/v250/unbound_control.py"
            unbound.parent.mkdir(parents=True, exist_ok=True)
            unbound.write_text("UNBOUND = True\n", encoding="utf-8")

            with self.assertRaises(GenerationLoadError) as caught:
                load_generation(root)

            self.assertEqual("E_V250_CONTROL_ASSET_UNBOUND", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
