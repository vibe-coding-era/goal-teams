from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.v250.freeze_v248_snapshot import SOURCE_PATHS, materialize
from scripts.v250.generation_runtime import (
    GenerationLoadError,
    V250_CONTROL_SCHEMA_PATHS,
    V250_REQUIRED_CONTROL_PATHS,
    load_generation,
)


REPO = Path(__file__).resolve().parents[2]
HAS_REPLAY_SUPPLEMENT = (
    REPO / "references/current/generations/V2.48/activation-manifest.json"
).is_file() and (REPO / "references/legacy-replay/generations/V2.48/snapshot").is_dir()


class TestV250GenerationIsolation(unittest.TestCase):
    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional V2.48 rollback supplement is not installed")
    def test_v248_rollback_generation_loads_only_isolated_snapshot_members(self) -> None:
        generation = load_generation(REPO, generation_id="V2.48")

        self.assertEqual("V2.48", generation["generation_id"])
        self.assertTrue(generation["activation_digest_verified"])
        self.assertEqual(len(SOURCE_PATHS), len(generation["member_paths"]))
        self.assertTrue(
            all(
                path.startswith("references/legacy-replay/generations/V2.48/snapshot/")
                for path in generation["member_paths"]
            )
        )

    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional V2.48 rollback supplement is not installed")
    def test_v248_snapshot_is_byte_identical_to_frozen_git_tree(self) -> None:
        receipt = materialize(REPO, write=False)

        self.assertTrue(receipt["passed"])
        self.assertEqual(38, receipt["member_count"])
        self.assertEqual([], receipt["errors"])

    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional V2.48 rollback supplement is not installed")
    def test_active_pointer_can_be_atomically_switched_to_v248_snapshot(self) -> None:
        current = load_generation(REPO)
        baseline = load_generation(REPO, generation_id="V2.48")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            required = {
                current["activation_manifest_path"],
                baseline["activation_manifest_path"],
                *current["member_paths"],
                *baseline["member_paths"],
            }
            for relative in required:
                source = REPO / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            manifest_raw = (root / baseline["activation_manifest_path"]).read_bytes()
            active = {
                "schema_version": "goal-teams-active-generation-v1",
                "generation_id": "V2.48",
                "activation_manifest": baseline["activation_manifest_path"],
                "activation_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                "state": "active_rollback",
                "updated_at": "2026-08-01T00:00:00+08:00",
            }
            active_path = root / "references/current/ACTIVE.json"
            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_path.write_text(
                json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            restored = load_generation(root)

            self.assertEqual("V2.48", restored["generation_id"])
            self.assertTrue(restored["selected_via_active_pointer"])
            shutil.copy2(REPO / "references/current/ACTIVE.json", active_path)

            resumed = load_generation(root)

            self.assertEqual("V2.51", resumed["generation_id"])
            self.assertTrue(resumed["selected_via_active_pointer"])

    def test_active_generation_binds_all_declared_current_control_assets(self) -> None:
        generation = load_generation(REPO)

        self.assertTrue(set(V250_REQUIRED_CONTROL_PATHS).issubset(generation["member_digests"]))
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
