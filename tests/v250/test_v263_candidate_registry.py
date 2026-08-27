from __future__ import annotations

import inspect
import hashlib
import json
import pathlib
import unittest
from unittest import mock

from scripts.v250 import generation_runtime
from scripts.v250.control_registry import (
    ControlRegistryError,
    is_control_asset_applicable,
    resolve_control_term,
)
from scripts.v250.generation_runtime import (
    ACTIVE_PATH,
    GenerationLoadError,
    load_candidate_generation,
    load_generation,
)
from tests.v250.v266_candidate_fixture import inactive_candidate_fixture


REPO = pathlib.Path(__file__).resolve().parents[2]
V266_ACTIVATION_PATH = (
    "references/current/generations/V2.66/activation-manifest.json"
)
V266_FOUNDATION_ASSETS = (
    "scripts/v250/control_registry.py",
    "scripts/v250/discovery_policy.py",
    "tests/v250/test_v263_candidate_registry.py",
    "tests/v250/test_v263_discovery_snapshot.py",
)


class TestV263CandidateRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._candidate_context = inactive_candidate_fixture(REPO)
        cls.candidate_fixture = cls._candidate_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._candidate_context.close()

    def test_registry_normalizes_declared_alias_and_rejects_unknown_vocabulary(self) -> None:
        self.assertEqual(
            "full_regression",
            resolve_control_term("gate", "final_full_regression"),
        )
        self.assertEqual("release", resolve_control_term("phase", "release"))

        for vocabulary, value in (
            ("gate", "surprise_gate"),
            ("phase", "shipping"),
            ("unknown_vocabulary", "release"),
        ):
            with self.subTest(vocabulary=vocabulary, value=value):
                with self.assertRaises(ControlRegistryError) as caught:
                    resolve_control_term(vocabulary, value)
                self.assertEqual("E_CONTROL_REGISTRY_UNKNOWN_TERM", caught.exception.code)

    def test_candidate_loader_requires_expected_digest_and_never_reads_active(self) -> None:
        fixture = self.candidate_fixture
        candidate_raw = (fixture.root / fixture.activation_path).read_bytes()
        candidate_digest = hashlib.sha256(candidate_raw).hexdigest()
        self.assertEqual(fixture.activation_sha256, candidate_digest)
        signature = inspect.signature(load_candidate_generation)
        self.assertEqual(
            inspect.Parameter.KEYWORD_ONLY,
            signature.parameters["expected_activation_sha256"].kind,
        )
        self.assertIs(
            inspect.Parameter.empty,
            signature.parameters["expected_activation_sha256"].default,
        )

        with self.assertRaises(TypeError):
            load_candidate_generation(
                fixture.root,
                generation_id="V2.66",
                activation_manifest_path=fixture.activation_path,
            )

        observed_paths: list[str] = []
        original = generation_runtime._read_json_file

        def recording_read(root: pathlib.Path, relative_path: str):
            observed_paths.append(relative_path)
            return original(root, relative_path)

        with mock.patch.object(
            generation_runtime,
            "_read_json_file",
            side_effect=recording_read,
        ):
            candidate = load_candidate_generation(
                fixture.root,
                generation_id="V2.66",
                activation_manifest_path=fixture.activation_path,
                expected_activation_sha256=candidate_digest,
            )

        self.assertEqual("candidate_expected_digest", candidate["selection_mode"])
        self.assertFalse(candidate["selected_via_active_pointer"])
        self.assertNotIn(ACTIVE_PATH, observed_paths)

        with self.assertRaises(GenerationLoadError) as caught:
            load_candidate_generation(
                fixture.root,
                generation_id="V2.66",
                activation_manifest_path=fixture.activation_path,
                expected_activation_sha256="0" * 64,
            )
        self.assertEqual("E_V250_CANDIDATE_DIGEST_MISMATCH", caught.exception.code)

        live_raw = (REPO / V266_ACTIVATION_PATH).read_bytes()
        with self.assertRaises(GenerationLoadError) as live_state:
            load_candidate_generation(
                REPO,
                generation_id="V2.66",
                activation_manifest_path=V266_ACTIVATION_PATH,
                expected_activation_sha256=hashlib.sha256(live_raw).hexdigest(),
            )
        self.assertEqual("E_V250_CANDIDATE_STATE", live_state.exception.code)

    def test_default_loader_uses_active_only_and_predecessor_window_is_closed(self) -> None:
        active = json.loads((REPO / ACTIVE_PATH).read_text(encoding="utf-8"))
        self.assertIn(active["generation_id"], {"V2.65", "V2.66"})
        if active["generation_id"] == "V2.66":
            generation = load_generation(REPO)
            self.assertEqual("V2.66", generation["generation_id"])
            self.assertEqual("active_pointer", generation["selection_mode"])
            self.assertTrue(generation["selected_via_active_pointer"])
            unreachable = "V2.65"
        else:
            prepared = json.loads(
                (REPO / V266_ACTIVATION_PATH).read_text(encoding="utf-8")
            )
            self.assertIn(prepared["generation_state"], {"inactive_candidate", "active"})
            unreachable = "V2.66"

        with self.assertRaises(GenerationLoadError) as caught:
            load_generation(REPO, generation_id=unreachable)
        self.assertEqual("E_V250_GENERATION_NOT_REACHABLE", caught.exception.code)

    def test_v263_assets_are_bound_to_an_explicit_v263_control_closure(self) -> None:
        fixture = self.candidate_fixture
        generation = load_candidate_generation(
            fixture.root,
            generation_id="V2.66",
            activation_manifest_path=fixture.activation_path,
            expected_activation_sha256=fixture.activation_sha256,
        )
        self.assertEqual("V2.66", generation["generation_id"])

        for relative_path in V266_FOUNDATION_ASSETS:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((fixture.root / relative_path).is_file())
                self.assertTrue(
                    is_control_asset_applicable(relative_path, generation_id="V2.65")
                )
                self.assertTrue(
                    is_control_asset_applicable(relative_path, generation_id="V2.66")
                )
                self.assertIn(relative_path, generation["member_digests"])


if __name__ == "__main__":
    unittest.main()
