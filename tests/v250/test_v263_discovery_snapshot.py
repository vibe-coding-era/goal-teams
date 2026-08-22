from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

from scripts.v250 import generation_runtime
from scripts.v250.discovery_policy import (
    DiscoveryCandidateSpec,
    DiscoveryPolicyError,
    discover_and_select,
    load_discovery_candidate,
)
from scripts.v250.generation_runtime import (
    ACTIVE_PATH,
    GenerationLoadError,
    GenerationRuntimeSession,
)


REPO = pathlib.Path(__file__).resolve().parents[2]


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write_candidate(
    root: pathlib.Path,
    *,
    generation_id: str,
    skill_name: str = "goal-teams",
    marker: str = "fixture",
) -> str:
    root.mkdir(parents=True, exist_ok=True)
    skill_raw = (
        "---\n"
        f"name: {skill_name}\n"
        f"description: {generation_id} {marker}\n"
        "---\n\n"
        f"# {generation_id}\n"
    ).encode("utf-8")
    (root / "SKILL.md").write_bytes(skill_raw)

    prompt_path = f"references/current/generations/{generation_id}/prompt-manifest.json"
    prompt_raw = _json_bytes(
        {
            "schema_version": "goal-teams-prompt-manifest-v2.50",
            "generation_id": generation_id,
            "marker": marker,
        }
    )
    prompt_file = root / prompt_path
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_bytes(prompt_raw)

    activation_path = (
        f"references/current/generations/{generation_id}/activation-manifest.json"
    )
    activation_raw = _json_bytes(
        {
            "schema_version": "goal-teams-activation-manifest-v2.50",
            "generation_id": generation_id,
            "identity": {
                "loaded_runtime_product_version": generation_id,
                "target_policy_generation": generation_id,
            },
            "prompt_manifest_path": prompt_path,
            "prompt_plan_digest": hashlib.sha256(prompt_raw).hexdigest(),
            "marker": marker,
        }
    )
    activation_file = root / activation_path
    activation_file.write_bytes(activation_raw)
    activation_digest = hashlib.sha256(activation_raw).hexdigest()

    active_file = root / ACTIVE_PATH
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_bytes(
        _json_bytes(
            {
                "schema_version": "goal-teams-active-generation-v1",
                "generation_id": generation_id,
                "activation_manifest": activation_path,
                "activation_manifest_sha256": activation_digest,
                "state": "active_current",
            }
        )
    )
    return activation_digest


class TestV263DiscoverySnapshot(unittest.TestCase):
    def test_candidate_identity_is_digest_bound_and_selection_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "canonical"
            activation_digest = _write_candidate(root, generation_id="V2.65")
            spec = DiscoveryCandidateSpec(
                root=root,
                root_kind="canonical_install",
                expected_activation_sha256=activation_digest,
                discovery_order=7,
                source_commit="1" * 40,
                source_tree="2" * 40,
            )

            candidate = load_discovery_candidate(spec)
            decision = discover_and_select((spec,))

            self.assertEqual(root.resolve().as_posix(), candidate.root_realpath)
            self.assertEqual("goal-teams", candidate.discovery_name)
            self.assertEqual("V2.65", candidate.generation_id)
            self.assertEqual(activation_digest, candidate.activation_sha256)
            self.assertEqual(candidate, decision.selected)
            self.assertEqual("canonical_install", decision.selection_rule)
            self.assertEqual((candidate,), decision.candidates)

    def test_duplicate_old_replay_and_mirror_candidates_all_fail_closed(self) -> None:
        cases = (
            ("workspace", "V2.6", "old"),
            ("replay", "V2.48", "replay"),
            ("mirror", "V2.65", "mirror"),
        )
        for root_kind, generation_id, marker in cases:
            with self.subTest(root_kind=root_kind, generation_id=generation_id):
                with tempfile.TemporaryDirectory() as directory:
                    base = pathlib.Path(directory)
                    current_root = base / "current"
                    duplicate_root = base / marker
                    current_digest = _write_candidate(
                        current_root, generation_id="V2.65", marker="current"
                    )
                    duplicate_digest = _write_candidate(
                        duplicate_root,
                        generation_id=generation_id,
                        marker=marker,
                    )
                    specs = (
                        DiscoveryCandidateSpec(
                            root=current_root,
                            root_kind="canonical_install",
                            expected_activation_sha256=current_digest,
                            discovery_order=0,
                        ),
                        DiscoveryCandidateSpec(
                            root=duplicate_root,
                            root_kind=root_kind,
                            expected_activation_sha256=duplicate_digest,
                            discovery_order=1,
                        ),
                    )

                    with self.assertRaises(DiscoveryPolicyError) as caught:
                        discover_and_select(specs)
                    self.assertEqual(
                        "E_DISCOVERY_MULTIPLE_ACTIVE",
                        caught.exception.code,
                    )

    def test_invalid_first_candidate_never_falls_back_to_valid_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            bad_root = base / "workspace"
            good_root = base / "canonical"
            _write_candidate(bad_root, generation_id="V2.65", marker="bad")
            good_digest = _write_candidate(
                good_root, generation_id="V2.65", marker="good"
            )
            specs = (
                DiscoveryCandidateSpec(
                    root=bad_root,
                    root_kind="workspace",
                    expected_activation_sha256="0" * 64,
                    discovery_order=0,
                ),
                DiscoveryCandidateSpec(
                    root=good_root,
                    root_kind="canonical_install",
                    expected_activation_sha256=good_digest,
                    discovery_order=1,
                ),
            )

            with self.assertRaises(DiscoveryPolicyError) as caught:
                discover_and_select(specs)
            self.assertEqual(
                "E_DISCOVERY_ACTIVATION_DIGEST_MISMATCH",
                caught.exception.code,
            )

    def test_session_reads_active_once_is_immutable_and_change_event_requires_restart(self) -> None:
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
            session = GenerationRuntimeSession.initialize(
                REPO,
                session_id="session-v263-test",
                source_commit="1" * 40,
                source_tree="2" * 40,
                captured_at="2026-08-12T12:00:00+08:00",
            )
            first = session.snapshot
            second = session.snapshot
            generation = session.generation
            session.notify_active_change(first.active_sha256)
            third = session.snapshot

        self.assertEqual(1, observed_paths.count(ACTIVE_PATH))
        self.assertIs(first, second)
        self.assertIs(second, third)
        self.assertEqual("V2.65", generation["generation_id"])
        self.assertEqual(tuple(sorted(generation["member_digests"].items())), first.member_digests)
        with self.assertRaises(FrozenInstanceError):
            first.generation_id = "V2.65"  # type: ignore[misc]

        session.notify_active_change("f" * 64)
        for accessor in (lambda: session.snapshot, lambda: session.generation):
            with self.subTest(accessor=accessor):
                with self.assertRaises(GenerationLoadError) as caught:
                    accessor()
                self.assertEqual(
                    "E_ACTIVE_CHANGED_RESTART_REQUIRED",
                    caught.exception.code,
                )
        self.assertEqual(1, observed_paths.count(ACTIVE_PATH))


if __name__ == "__main__":
    unittest.main()
