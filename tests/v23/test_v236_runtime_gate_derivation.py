"""V2.36 ledger gate derivation regressions."""

from __future__ import annotations

import json
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import (
    ROOT,
    gt,
    parse_envelope,
    requires_trusted_goal_teams_checkout,
    run_cli,
    task_event,
)


def implementation_events(
    *,
    state_gate_profile: str | None = None,
    product_version: str | None = "V2.36",
    target_kind: str | None = "generic_project",
    task_type: str | None = "cli",
    release: bool | None = False,
) -> list[dict[str, object]]:
    facts = {
        key: value
        for key, value in {
            "product_version": product_version,
            "target_kind": target_kind,
            "task_type": task_type,
            "release": release,
        }.items()
        if value is not None
    }
    planned_payload: dict[str, object] = {
        "execution_class": "implementation",
        **facts,
    }
    if state_gate_profile is not None:
        planned_payload["state_gate_profile"] = state_gate_profile
    return [
        {
            "event_id": "EVT-V236-PLAN",
            "task_id": "TASK-V236-IMPLEMENT",
            "payload": planned_payload,
        },
        {
            "event_id": "EVT-V236-RUN",
            "task_id": "TASK-V236-IMPLEMENT",
            "payload": {"task_state": "running"},
        },
    ]


def cli_implementation_events(
    *, target_kind: str = "generic_project", task_type: str = "cli",
    release: bool = False,
) -> list[dict[str, object]]:
    task_id = "TASK-V236-CLI-IMPLEMENT"
    return [
        task_event(
            "EVT-V236-CLI-PLAN",
            task_id,
            0,
            "planned",
            payload={
                "execution_class": "implementation",
                "product_version": "V2.36",
                "target_kind": target_kind,
                "task_type": task_type,
                "release": release,
            },
        ),
        task_event(
            "EVT-V236-CLI-RUN",
            task_id,
            1,
            "running",
        ),
    ]


class V236RuntimeGateDerivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._generic_repo_tmp = tempfile.TemporaryDirectory()
        cls.generic_repo = Path(cls._generic_repo_tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=cls.generic_repo, check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._generic_repo_tmp.cleanup()

    def test_omitted_state_gate_is_derived_for_core_task(self) -> None:
        errors = gt._validate_v234_implementation_events(
            implementation_events(),
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertEqual(errors, [])

    def test_explicit_state_gate_is_only_a_matching_assertion(self) -> None:
        matching = gt._validate_v234_implementation_events(
            implementation_events(state_gate_profile="goal-teams-core-v2.5"),
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertEqual(matching, [])
        mismatch = gt._validate_v234_implementation_events(
            implementation_events(
                state_gate_profile="goal-teams-self-release-v2.36"
            ),
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertIn("E_V236_STATE_GATE_PROFILE_MISMATCH", mismatch)

    def test_omitting_profile_and_derivation_facts_fails_closed(self) -> None:
        errors = gt._validate_v234_implementation_events(
            implementation_events(
                product_version=None, target_kind=None, task_type=None
            ),
            None,
            candidate_event_id="EVT-V236-RUN",
        )
        self.assertEqual(errors, ["E_V236_PROFILE_REQUIRED"])

    def test_omitting_release_fact_fails_closed(self) -> None:
        errors = gt._validate_v234_implementation_events(
            implementation_events(release=None),
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertEqual(errors, ["E_V236_PROFILE_REQUIRED"])

    def test_release_fact_is_strict_boolean(self) -> None:
        events = implementation_events()
        events[0]["payload"]["release"] = "false"
        errors = gt._validate_v234_implementation_events(
            events,
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertEqual(errors, ["E_V236_PROFILE_TYPE"])

    @requires_trusted_goal_teams_checkout
    def test_self_release_omission_still_reaches_disk_gate(self) -> None:
        events = implementation_events(
            target_kind="goal_teams_repository",
            task_type="goal_teams_self_release",
            release=True,
        )
        errors = gt._validate_v234_implementation_events(
            events,
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(ROOT),
        )
        self.assertEqual(errors, ["E_V234_IMPLEMENTATION_GATE_BINDING"])

    def test_v236_direct_validation_without_source_root_fails_closed(self) -> None:
        errors = gt._validate_v234_implementation_events(
            implementation_events(), None, candidate_event_id="EVT-V236-RUN"
        )
        self.assertEqual(errors, ["E_V236_SOURCE_ROOT_REQUIRED"])

    def test_self_release_requires_verified_repository_target(self) -> None:
        events = implementation_events(
            target_kind="goal_teams_repository",
            task_type="goal_teams_self_release",
            release=True,
        )
        errors = gt._validate_v234_implementation_events(
            events,
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertEqual(errors, ["E_V236_PROFILE_TARGET_UNVERIFIED"])

    @requires_trusted_goal_teams_checkout
    def test_verified_goal_teams_non_release_maintenance_uses_core(self) -> None:
        for task_type in ("cli", "backend"):
            with self.subTest(task_type=task_type):
                errors = gt._validate_v234_implementation_events(
                    implementation_events(
                        target_kind="goal_teams_repository",
                        task_type=task_type,
                        release=False,
                    ),
                    None,
                    candidate_event_id="EVT-V236-RUN",
                    source_root_value=str(ROOT),
                )
                self.assertEqual(errors, [])

    @requires_trusted_goal_teams_checkout
    def test_goal_teams_release_cannot_claim_cli_or_backend_task_type(self) -> None:
        for task_type in ("cli", "backend"):
            with self.subTest(task_type=task_type):
                errors = gt._validate_v234_implementation_events(
                    implementation_events(
                        target_kind="goal_teams_repository",
                        task_type=task_type,
                        release=True,
                    ),
                    None,
                    candidate_event_id="EVT-V236-RUN",
                    source_root_value=str(ROOT),
                )
                self.assertEqual(
                    errors, ["E_V236_RELEASE_TASK_TYPE_MISMATCH"]
                )

    @requires_trusted_goal_teams_checkout
    def test_goal_teams_self_release_task_cannot_claim_release_false(self) -> None:
        errors = gt._validate_v234_implementation_events(
            implementation_events(
                target_kind="goal_teams_repository",
                task_type="goal_teams_self_release",
                release=False,
            ),
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(ROOT),
        )
        self.assertEqual(errors, ["E_V236_RELEASE_TASK_TYPE_MISMATCH"])

    @requires_trusted_goal_teams_checkout
    def test_verified_self_release_target_cannot_be_relabelled_as_core(self) -> None:
        errors = gt._validate_v234_implementation_events(
            implementation_events(
                target_kind="generic_project",
                task_type="cli",
                release=False,
            ),
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(ROOT),
        )
        self.assertEqual(errors, ["E_V236_PROFILE_TARGET_MISMATCH"])

    def test_mutable_version_and_skill_bytes_cannot_hide_trusted_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
            (root / "VERSION").write_text("V2.35\n", encoding="utf-8")
            (root / "SKILL.md").write_text(
                "---\nname: goal-teams\ndescription: fixture\n---\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "VERSION", "SKILL.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "trusted base"], cwd=root, check=True)
            anchor = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            (root / "VERSION").write_text("V0\n", encoding="utf-8")
            (root / "SKILL.md").write_text(
                "---\nname: disguised-project\ndescription: fixture\n---\n",
                encoding="utf-8",
            )
            with mock.patch.object(gt, "V236_GOAL_TEAMS_TRUSTED_RELEASE_BASE", anchor):
                self.assertTrue(gt._verified_v236_goal_teams_target(root))
                errors = gt._validate_v234_implementation_events(
                    implementation_events(target_kind="generic_project", task_type="cli"),
                    None,
                    candidate_event_id="EVT-V236-RUN",
                    source_root_value=str(root),
                )
        self.assertEqual(errors, ["E_V236_PROFILE_TARGET_MISMATCH"])

    def test_gate_facts_are_immutable_across_events(self) -> None:
        events = implementation_events()
        events[1]["payload"] = {
            "task_state": "running",
            "task_type": "goal_teams_self_release",
        }
        errors = gt._validate_v234_implementation_events(
            events,
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertEqual(errors, ["E_V236_PROFILE_FACT_CONFLICT"])

    def test_release_fact_is_immutable_across_events(self) -> None:
        events = implementation_events()
        events[1]["payload"] = {"task_state": "running", "release": True}
        errors = gt._validate_v234_implementation_events(
            events,
            None,
            candidate_event_id="EVT-V236-RUN",
            source_root_value=str(self.generic_repo),
        )
        self.assertEqual(errors, ["E_V236_PROFILE_FACT_CONFLICT"])

    @requires_trusted_goal_teams_checkout
    def test_cli_commands_auto_observe_goal_teams_root_when_option_omitted(self) -> None:
        events = cli_implementation_events()
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            events_path = root / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            reduced = run_cli("reduce-ledger", str(events_path))
            self.assertNotEqual(reduced.returncode, 0, reduced.stdout)
            self.assertEqual(
                parse_envelope(reduced)["error_code"],
                "E_V236_PROFILE_TARGET_MISMATCH",
            )

            ledger = root / "ledger.jsonl"
            ledger.write_text(json.dumps(events[0]) + "\n", encoding="utf-8")
            event_path = root / "running.json"
            event_path.write_text(json.dumps(events[1]), encoding="utf-8")
            appended = run_cli(
                "append-event",
                str(ledger),
                str(event_path),
                "--ledger-owner-run-id",
                "RUN-LEDGER-OWNER",
            )
            self.assertNotEqual(appended.returncode, 0, appended.stdout)
            self.assertEqual(
                parse_envelope(appended)["error_code"],
                "E_V236_PROFILE_TARGET_MISMATCH",
            )

    def test_explicit_source_root_conflicting_with_ledger_repo_is_rejected(self) -> None:
        events = cli_implementation_events()
        with tempfile.TemporaryDirectory() as directory:
            observed_repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=observed_repo, check=True)
            events_path = observed_repo / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            proc = run_cli(
                "reduce-ledger",
                str(events_path),
                "--source-root",
                str(self.generic_repo),
            )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(
            parse_envelope(proc)["error_code"], "E_V236_SOURCE_ROOT_CONFLICT"
        )

    def test_non_git_core_uses_explicit_contained_filesystem_root(self) -> None:
        events = cli_implementation_events()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events_path = root / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            omitted = run_cli("reduce-ledger", str(events_path))
            self.assertNotEqual(omitted.returncode, 0, omitted.stdout)
            self.assertEqual(
                parse_envelope(omitted)["error_code"],
                "E_V236_SOURCE_ROOT_REQUIRED",
            )
            explicit = run_cli(
                "reduce-ledger",
                str(events_path),
                "--source-root",
                str(root),
            )
            self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)

    def test_external_ledger_cannot_select_unrelated_explicit_git_root(self) -> None:
        events = cli_implementation_events()
        with tempfile.TemporaryDirectory() as directory:
            events_path = Path(directory) / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            proc = run_cli(
                "reduce-ledger",
                str(events_path),
                "--source-root",
                str(self.generic_repo),
            )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(
            parse_envelope(proc)["error_code"],
            "E_V236_SOURCE_ROOT_UNVERIFIED",
        )

    def test_non_git_source_root_rejects_intermediate_symlink(self) -> None:
        events = cli_implementation_events()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / "actual"
            actual.mkdir()
            events_path = actual / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            alias = root / "alias"
            alias.symlink_to(actual, target_is_directory=True)
            proc = run_cli(
                "reduce-ledger",
                str(alias / "events.jsonl"),
                "--source-root",
                str(root),
            )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(
            parse_envelope(proc)["error_code"],
            "E_V236_SOURCE_ROOT_UNVERIFIED",
        )

    def test_system_alias_allowlist_is_darwin_only_and_exact(self) -> None:
        if gt.sys.platform == "darwin":
            for alias in (Path("/etc"), Path("/tmp"), Path("/var")):
                with self.subTest(alias=alias):
                    self.assertTrue(gt._v236_is_allowed_system_symlink(alias))
        with mock.patch.object(gt.sys, "platform", "linux"):
            self.assertFalse(gt._v236_is_allowed_system_symlink(Path("/var")))

    @requires_trusted_goal_teams_checkout
    def test_nested_generic_repo_cannot_hide_outer_goal_teams_root(self) -> None:
        events = cli_implementation_events()
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            nested = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
            events_path = nested / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            proc = run_cli("reduce-ledger", str(events_path))
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertEqual(
                parse_envelope(proc)["error_code"],
                "E_V236_PROFILE_TARGET_MISMATCH",
            )
            explicit_nested = run_cli(
                "reduce-ledger",
                str(events_path),
                "--source-root",
                str(nested),
            )
            self.assertNotEqual(explicit_nested.returncode, 0, explicit_nested.stdout)
            self.assertEqual(
                parse_envelope(explicit_nested)["error_code"],
                "E_V236_SOURCE_ROOT_CONFLICT",
            )

    def test_git_auto_discovery_rejects_intermediate_ledger_symlink(self) -> None:
        events_path = self.generic_repo / "symlink-events.jsonl"
        events_path.write_text(
            "".join(json.dumps(event) + "\n" for event in cli_implementation_events()),
            encoding="utf-8",
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            alias = Path(directory) / "external-alias"
            alias.symlink_to(self.generic_repo, target_is_directory=True)
            proc = run_cli("reduce-ledger", str(alias / events_path.name))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(
            parse_envelope(proc)["error_code"],
            "E_V236_SOURCE_ROOT_UNVERIFIED",
        )

    def test_explicit_legacy_v234_profile_remains_replayable(self) -> None:
        events = implementation_events(
            state_gate_profile="goal-teams-v2.34-state-v1",
            product_version=None,
            target_kind=None,
            task_type=None,
            release=None,
        )
        errors = gt._validate_v234_implementation_events(
            events, None, candidate_event_id="EVT-V236-RUN"
        )
        self.assertEqual(errors, ["E_V234_IMPLEMENTATION_GATE_BINDING"])


if __name__ == "__main__":
    unittest.main()
