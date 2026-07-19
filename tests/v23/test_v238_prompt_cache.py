"""V2.38 prompt-cache observability and stable-prefix TDD regressions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT, gt


PROMPT_CACHE_PATH = ROOT / "scripts" / "v23" / "prompt_cache.py"
PROMPT_MANIFEST_PATH = ROOT / "references" / "prompt-cache-manifest.json"
TEST_BUDGET_POLICY = {
    "schema_version": "goal-teams-route-context-budget-v1",
    "minimum_headroom_bytes": 128,
    "minimum_headroom_ratio": 0.01,
    "dynamic_packet_max_bytes": 2048,
    "max_segment_count": 16,
    "max_file_count": 8,
    "token_budget_status": "unavailable",
    "max_estimated_tokens": None,
    "budget_source": "v238-test",
    "exceed_action": "replan",
}


def _load_module(name: str, path: Path):
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prompt_cache = _load_module("goalteams_v238_prompt_cache_test", PROMPT_CACHE_PATH)
context_budget = _load_module(
    "goalteams_v238_context_budget_test",
    ROOT / "scripts" / "checks" / "check-context-budget.py",
)
benchmark_runner = _load_module(
    "goalteams_v238_benchmark_runner_test",
    ROOT / "scripts" / "benchmark" / "benchmark-runner.py",
)


class V238PromptCacheContractTests(unittest.TestCase):
    def test_prompt_cache_runtime_module_and_ordered_manifest_exist(self) -> None:
        self.assertTrue(
            PROMPT_CACHE_PATH.is_file(),
            "V2.38 red: scripts/v23/prompt_cache.py is not implemented",
        )
        self.assertTrue(
            PROMPT_MANIFEST_PATH.is_file(),
            "V2.38 red: references/prompt-cache-manifest.json is missing",
        )

    @unittest.skipUnless(prompt_cache is not None, "V2.38 prompt-cache runtime not implemented")
    def test_manifest_order_and_digest_are_stable_and_order_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "SKILL.md").write_text("stable skill\n", encoding="utf-8")
            (root / "RULES.md").write_text("stable rules\n", encoding="utf-8")
            manifest_path = root / "references" / "prompt-cache-manifest.json"
            manifest = {
                "schema_version": "goal-teams-prompt-cache-v2.38",
                "budget_policy": TEST_BUDGET_POLICY,
                "routes": {
                    "probe": {
                        "ordered_refs": ["SKILL.md", "RULES.md"],
                        "limit_bytes": 4096,
                    }
                },
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            first = prompt_cache.build_prompt_identity(root, "probe")
            second = prompt_cache.build_prompt_identity(root, "probe")
            self.assertEqual(first, second)
            self.assertEqual(first["ordered_refs"], ["SKILL.md", "RULES.md"])
            self.assertRegex(first["prefix_manifest_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(first["route_static_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(first["manifest_status"], "unavailable")
            self.assertEqual(first["digest_scope"], "partial")
            self.assertIsNone(first["stable_prefix_digest"])
            self.assertIsNone(first["runtime_prompt_digest"])

            manifest["routes"]["probe"]["ordered_refs"].reverse()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            reordered = prompt_cache.build_prompt_identity(root, "probe")
            self.assertNotEqual(
                reordered["prefix_manifest_sha256"], first["prefix_manifest_sha256"]
            )
            self.assertNotEqual(
                reordered["route_static_digest"], first["route_static_digest"]
            )

    @unittest.skipUnless(prompt_cache is not None, "V2.38 prompt-cache runtime not implemented")
    def test_route_static_digest_ignores_readme_but_changes_with_prompt_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "SKILL.md").write_text("stable skill\n", encoding="utf-8")
            (root / "RULES.md").write_text("stable rules\n", encoding="utf-8")
            (root / "README.md").write_text("release note A\n", encoding="utf-8")
            (root / "references" / "prompt-cache-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-prompt-cache-v2.38",
                        "budget_policy": TEST_BUDGET_POLICY,
                        "routes": {
                            "probe": {
                                "ordered_refs": ["SKILL.md", "RULES.md"],
                                "limit_bytes": 4096,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            baseline = prompt_cache.build_prompt_identity(root, "probe")
            (root / "README.md").write_text("release note B\n", encoding="utf-8")
            readme_only = prompt_cache.build_prompt_identity(root, "probe")
            self.assertEqual(
                baseline["route_static_digest"], readme_only["route_static_digest"]
            )
            (root / "RULES.md").write_text("changed runtime rule\n", encoding="utf-8")
            runtime_changed = prompt_cache.build_prompt_identity(root, "probe")
            self.assertNotEqual(
                baseline["route_static_digest"], runtime_changed["route_static_digest"]
            )
            self.assertEqual(
                baseline["prefix_manifest_sha256"], runtime_changed["prefix_manifest_sha256"]
            )

    def test_host_ordered_manifest_separates_stable_and_runtime_digests(self) -> None:
        def manifest(stable: bytes, dynamic: bytes) -> dict[str, object]:
            return {
                "schema_version": "goal-teams-ordered-prompt-manifest-v1",
                "manifest_id": "PM-R1-T1",
                "product_version": "V2.38",
                "agent_run_id": "R1",
                "turn_id": "T1",
                "route_id": "backend",
                "policy_profile": "core",
                "manifest_status": "available",
                "digest_scope": "complete",
                "missing_segment_classes": [],
                "stable_segment_count": 1,
                "dynamic_segment_count": 1,
                "platform_managed_segment_count": 0,
                "canonicalization": "utf8-lf-json-jcs-v1",
                "segments": [
                    {
                        "order": 0,
                        "segment_id": "stable",
                        "segment_class": "stable",
                        "source_type": "file",
                        "source_ref": "SKILL.md",
                        "content_sha256": hashlib.sha256(stable).hexdigest(),
                        "byte_count": len(stable),
                        "token_count": None,
                        "token_count_status": "unavailable",
                        "inclusion_reason": "route_rule",
                        "inclusion_state": "included",
                        "redaction_state": "content_not_persisted",
                    },
                    {
                        "order": 1,
                        "segment_id": "dynamic",
                        "segment_class": "dynamic",
                        "source_type": "user",
                        "source_ref": "redacted:user_request",
                        "content_sha256": hashlib.sha256(dynamic).hexdigest(),
                        "byte_count": len(dynamic),
                        "token_count": None,
                        "token_count_status": "unavailable",
                        "inclusion_reason": "current_request",
                        "inclusion_state": "included",
                        "redaction_state": "content_not_persisted",
                    },
                ],
            }

        baseline = prompt_cache.build_ordered_prompt_identity(manifest(b"stable", b"A"))
        dynamic_changed = prompt_cache.build_ordered_prompt_identity(manifest(b"stable", b"B"))
        stable_changed = prompt_cache.build_ordered_prompt_identity(manifest(b"changed", b"A"))
        self.assertEqual(
            baseline["stable_prefix_digest"], dynamic_changed["stable_prefix_digest"]
        )
        self.assertNotEqual(
            baseline["runtime_prompt_digest"], dynamic_changed["runtime_prompt_digest"]
        )
        self.assertNotEqual(
            baseline["stable_prefix_digest"], stable_changed["stable_prefix_digest"]
        )
        self.assertNotEqual(
            baseline["runtime_prompt_digest"], stable_changed["runtime_prompt_digest"]
        )
        invalid = manifest(b"stable", b"A")
        invalid["segments"].reverse()  # type: ignore[union-attr]
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(invalid)

    @unittest.skipUnless(prompt_cache is not None, "V2.38 prompt-cache runtime not implemented")
    def test_usage_is_token_weighted_reports_coverage_and_no_request_hit_rate(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "turn.completed",
                        "event_id": "turn-1",
                        "usage": {"input_tokens": 1000, "cached_input_tokens": 900, "reasoning_output_tokens": 7},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "event_id": "turn-2",
                        "usage": {"input_tokens": 100, "cached_input_tokens": 0},
                    }
                ),
                json.dumps(
                    {"type": "turn.completed", "event_id": "turn-3", "usage": {"input_tokens": 900}}
                ),
                json.dumps({"type": "item.completed", "usage": {"input_tokens": 9999}}),
            ]
        )
        result = prompt_cache.aggregate_usage_events(jsonl)
        self.assertEqual(result["completed_turns"], 3)
        self.assertEqual(result["telemetry_turns"], 2)
        self.assertEqual(result["input_tokens"], 1100)
        self.assertEqual(result["covered_input_tokens"], 1100)
        self.assertEqual(result["cached_input_tokens"], 900)
        self.assertEqual(result["uncached_input_tokens"], 200)
        self.assertEqual(result["reasoning_output_tokens"], 7)
        self.assertAlmostEqual(result["cached_input_share"], 900 / 1100)
        self.assertAlmostEqual(result["telemetry_coverage"], 2 / 3)
        self.assertIsNone(result["request_hit_rate"])
        self.assertEqual(
            result["request_hit_rate_reason"],
            "turn_aggregate_cannot_estimate_request_hit_rate",
        )
        self.assertNotIn("cache_hit_rate", result)

    def test_manifest_rejects_duplicate_and_traversal_refs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "SKILL.md").write_text("stable\n", encoding="utf-8")
            manifest_path = root / "references" / "prompt-cache-manifest.json"
            base = {
                "schema_version": "goal-teams-prompt-cache-v2.38",
                "budget_policy": TEST_BUDGET_POLICY,
                "routes": {
                    "probe": {
                        "ordered_refs": ["SKILL.md", "SKILL.md"],
                        "limit_bytes": 4096,
                    }
                },
            }
            manifest_path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaises(prompt_cache.PromptCacheContractError):
                prompt_cache.load_prompt_manifest(root)
            base["routes"]["probe"]["ordered_refs"] = ["../SKILL.md"]
            manifest_path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaises(prompt_cache.PromptCacheContractError):
                prompt_cache.load_prompt_manifest(root)

    def test_route_budget_enforces_headroom_and_emits_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            payload = b"x" * 200
            (root / "RULES.md").write_bytes(payload)
            path = root / "references" / "prompt-cache-manifest.json"
            manifest = {
                "schema_version": "goal-teams-prompt-cache-v2.38",
                "budget_policy": TEST_BUDGET_POLICY,
                "routes": {
                    "probe": {
                        "ordered_refs": ["RULES.md"],
                        "limit_bytes": 300,
                        "dynamic_tail_labels": ["request"],
                    }
                },
            }
            path.write_text(json.dumps(manifest), encoding="utf-8")
            failed = prompt_cache.build_prompt_identity(root, "probe")
            self.assertFalse(failed["passed"])
            self.assertIn(
                "minimum_headroom", failed["budget_receipt"]["violations"]
            )
            self.assertEqual(
                failed["budget_receipt"]["actual"]["dynamic_packet_status"],
                "unavailable_until_final_assembly",
            )
            manifest["routes"]["probe"]["limit_bytes"] = 512
            path.write_text(json.dumps(manifest), encoding="utf-8")
            passed = prompt_cache.build_prompt_identity(root, "probe")
            self.assertTrue(passed["passed"])
            self.assertEqual(passed["budget_receipt"]["violations"], [])

    def test_invalid_usage_is_not_aggregated_and_observer_cannot_drive_budget(self) -> None:
        invalid = prompt_cache.aggregate_usage_events(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {"input_tokens": 10, "cached_input_tokens": 11},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {"input_tokens": -1, "cached_input_tokens": 0},
                        }
                    ),
                    "{not-json",
                ]
            )
        )
        self.assertEqual(invalid["status"], "unavailable")
        self.assertEqual(invalid["telemetry_turns"], 0)
        self.assertEqual(invalid["invalid_events"], 2)
        self.assertEqual(invalid["malformed_lines"], 1)
        self.assertIsNone(invalid["cached_input_share"])

        capability_manifest = json.loads(
            (ROOT / "tests/v23/fixtures/capability/full.json").read_text(
                encoding="utf-8"
            )
        )
        capability_manifest["telemetry"] = "unavailable"
        capability_manifest["subject_visible_telemetry"] = "unavailable"
        capability_manifest["observer_telemetry"] = "available"
        capability = gt.capability(capability_manifest)
        self.assertTrue(capability["valid"], capability)
        self.assertEqual(capability["observer_telemetry"], "available")
        self.assertEqual(capability["budget_telemetry_source"], "subject_visible_telemetry")
        self.assertEqual(capability["budget_metric"], "round_time_member_file_size")

    def test_usage_parser_rejects_unknown_and_invalid_and_flags_duplicate_identity(self) -> None:
        keyed = {
            "type": "turn.completed",
            "event_id": "T1",
            "event_schema_version": "codex-turn-completed-v1",
            "adapter_version": "codex-cli-jsonl-v1",
            "usage": {"input_tokens": 100, "cached_input_tokens": 80},
        }
        unkeyed = {
            "type": "turn.completed",
            "usage": {"input_tokens": 20, "cached_input_tokens": 6},
        }
        result = prompt_cache.aggregate_usage_events(
            "\n".join(
                [
                    json.dumps(keyed),
                    json.dumps(keyed),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "event_id": "T2",
                            "event_schema_version": "future-v99",
                            "usage": {"input_tokens": 9000, "cached_input_tokens": 9000},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "event_id": "T3",
                            "usage": {"input_tokens": 10, "cached_input_tokens": 11},
                        }
                    ),
                    json.dumps(unkeyed),
                    json.dumps(unkeyed),
                ]
            )
        )
        self.assertEqual(result["terminal_events_observed"], 6)
        self.assertEqual(result["completed_turns"], 5)
        self.assertEqual(result["telemetry_turns"], 3)
        self.assertEqual(result["duplicate_events"], 1)
        self.assertEqual(result["unsupported_events"], 1)
        self.assertEqual(result["invalid_events"], 1)
        self.assertEqual(result["ambiguous_duplicate_candidates"], 1)
        self.assertEqual(result["input_tokens"], 140)
        self.assertEqual(result["cached_input_tokens"], 92)
        self.assertEqual(result["status"], "partial")
        self.assertRegex(result["raw_jsonl_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["duplicate_detection_status"], "partial")

    def test_cache_probe_is_explicitly_plan_only_with_first_seen_plus_repeats(self) -> None:
        plan = prompt_cache.build_cache_probe_plan(ROOT, "benchmark")
        self.assertEqual(plan["execution_state"], "planned_not_executed")
        self.assertEqual(plan["live_ab_status"], "unavailable")
        self.assertEqual(plan["cache_namespace_control"], "unavailable")
        self.assertEqual(plan["warm_repeats_per_cohort"], 5)
        self.assertEqual(
            [cohort["cohort_id"] for cohort in plan["cohorts"]],
            ["baseline_current", "dynamic_suffix_change", "stable_prefix_candidate"],
        )
        for cohort in plan["cohorts"]:
            self.assertEqual(len(cohort["invocations"]), 6)
            self.assertEqual(
                cohort["invocations"][0]["repetition_state"], "first_seen_reference"
            )
            self.assertTrue(
                all(
                    item["repetition_state"] == "immediate_repeat"
                    for item in cohort["invocations"][1:]
                )
            )
        self.assertIn("model", plan["fixed_controls"])
        self.assertIn("effective_config_manifest_sha256", plan["fixed_controls"])
        self.assertFalse(plan["request_hit_rate_supported"])

    def test_benchmark_record_and_summary_keep_request_hit_rate_explicitly_null(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 10, "cached_input_tokens": 4},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 20, "cached_input_tokens": 6},
                    }
                ),
            ]
        )
        record_telemetry = benchmark_runner._observer_telemetry(jsonl)
        self.assertIsNone(record_telemetry["request_hit_rate"])
        self.assertEqual(
            record_telemetry["request_hit_rate_reason"],
            "turn_aggregate_cannot_estimate_request_hit_rate",
        )
        summary = benchmark_runner._summarize_observer_telemetry(
            [{"scenario_id": "S1", "result": "passed", "observer_telemetry": record_telemetry}]
        )
        self.assertIsNone(summary["request_hit_rate"])
        self.assertEqual(
            summary["request_hit_rate_reason"],
            "turn_aggregate_cannot_estimate_request_hit_rate",
        )
        self.assertEqual(summary["cache_analytics_status"], "unsupported")
        self.assertIsNone(summary["cached_input_share"])

    def test_benchmark_observer_preserves_parser_evidence_and_raw_hash(self) -> None:
        valid = {
            "type": "turn.completed",
            "event_id": "turn-valid",
            "event_schema_version": "codex-turn-completed-v1",
            "adapter_version": "codex-cli-jsonl-v1",
            "usage": {"input_tokens": 10, "cached_input_tokens": 4},
        }
        conflict_a = {
            "type": "turn.completed",
            "event_id": "turn-conflict",
            "adapter_version": "codex-cli-jsonl-v1",
            "usage": {"input_tokens": 10, "cached_input_tokens": 1},
        }
        conflict_b = {
            **conflict_a,
            "usage": {"input_tokens": 10, "cached_input_tokens": 2},
        }
        unsupported = {
            "type": "turn.completed",
            "event_id": "turn-unsupported",
            "adapter_version": "future-adapter-v9",
            "usage": {"input_tokens": 10, "cached_input_tokens": 0},
        }
        invalid = {
            "type": "turn.completed",
            "event_id": "turn-invalid",
            "adapter_version": "codex-cli-jsonl-v1",
            "usage": {"input_tokens": 10, "cached_input_tokens": 11},
        }
        jsonl = "\n".join(
            [
                json.dumps(valid),
                json.dumps(valid),
                json.dumps(conflict_a),
                json.dumps(conflict_b),
                json.dumps(unsupported),
                json.dumps(invalid),
                "{malformed",
            ]
        )
        telemetry = benchmark_runner._observer_telemetry(jsonl)
        parser_result = prompt_cache.aggregate_usage_events(jsonl)

        for field in (
            "parser_version",
            "adapter_registry_version",
            "raw_jsonl_sha256",
            "invalid_events",
            "malformed_lines",
            "unsupported_events",
            "duplicate_events",
            "conflicting_events",
            "turn_cache_presence",
        ):
            self.assertEqual(telemetry[field], parser_result[field], field)
        self.assertEqual(
            telemetry["raw_jsonl_sha256"],
            hashlib.sha256(jsonl.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            telemetry["observed_adapter_versions"],
            ["codex-cli-jsonl-v1", "future-adapter-v9"],
        )
        self.assertEqual(
            telemetry["observed_event_schema_versions"],
            ["codex-turn-completed-v1", "legacy-unversioned"],
        )
        summarized = benchmark_runner._summarize_identity_group(
            [{"scenario_id": "S", "result": "passed", "observer_telemetry": telemetry}]
        )
        self.assertEqual(summarized["unavailable_turns"], 3)
        self.assertEqual(summarized["ambiguous_duplicate_candidates"], 0)
        self.assertEqual(summarized["events_without_stable_id"], 0)

    def test_benchmark_identity_binds_model_and_missing_model_is_unsupported(self) -> None:
        self.assertEqual(
            benchmark_runner._command_model_identity(
                ["codex", "exec", "--model", "gpt-5.4", "-"]
            )["model"],
            "gpt-5.4",
        )
        self.assertEqual(
            benchmark_runner._command_model_identity(["codex", "exec", "-"])[
                "status"
            ],
            "unsupported",
        )

        with tempfile.TemporaryDirectory() as td:
            staged_root = Path(td)
            (staged_root / "VERSION").write_text("V2.38\n", encoding="utf-8")
            telemetry = benchmark_runner._observer_telemetry(
                json.dumps(
                    {
                        "type": "turn.completed",
                        "event_id": "turn-1",
                        "event_schema_version": "codex-turn-completed-v1",
                        "adapter_version": "codex-cli-jsonl-v1",
                        "usage": {"input_tokens": 10, "cached_input_tokens": 5},
                    }
                )
            )
            kwargs = {
                "staged_root": staged_root,
                "manifest": {
                    "policy_profile": "goal-teams-core-v2.5",
                    "gate_profile": "benchmark-standard",
                },
                "scenario": {"scenario_class": "core"},
                "adapter": {
                    "type": "codex_cli",
                    "provider": "openai-codex-cli",
                    "command": ["codex", "exec", "--model", "gpt-5.4", "-"],
                },
                "prompt_identity": {
                    "route_id": "benchmark",
                    "prefix_manifest_sha256": "1" * 64,
                    "route_static_digest": "2" * 64,
                    "stable_prefix_digest": "3" * 64,
                    "runtime_prompt_digest": "4" * 64,
                    "manifest_status": "complete",
                    "digest_scope": "complete",
                },
                "provider_version": "codex-cli 1.2.3",
                "executable_sha256": "5" * 64,
                "staged_package_sha256": "6" * 64,
                "effective_config": {
                    "effective_manifest_sha256": "7" * 64,
                    "verification_status": "complete",
                    "effective_config_verified": True,
                    "trace_proof_status": "available",
                    "trace_proof_sha256": "8" * 64,
                },
                "observer_telemetry": telemetry,
            }
            forged_config_identity = benchmark_runner._build_cache_record_identity(
                command=["codex", "exec", "--model", "gpt-5.4", "-"],
                **kwargs,
            )
            self.assertEqual(
                forged_config_identity["cache_analytics_status"], "unsupported"
            )
            self.assertEqual(
                forged_config_identity["cache_analytics_reason"],
                "effective_config_verification_incomplete",
            )
            self.assertIsNone(forged_config_identity["identity_sha256"])
            self.assertIn(
                "digest_identity.effective_config_verification",
                forged_config_identity["missing_identity_fields"],
            )
            config_verification = forged_config_identity["digest_identity"][
                "effective_config_verification"
            ]
            self.assertFalse(config_verification["effective_config_verified"])
            self.assertEqual(
                config_verification["trace_proof_status"], "invalid_untrusted"
            )
            self.assertIsNone(config_verification["trace_proof_sha256"])
            config_blocked_telemetry = benchmark_runner._bind_observer_cache_identity(
                telemetry, forged_config_identity
            )
            self.assertEqual(
                config_blocked_telemetry["cache_conclusion"]["status"],
                "unsupported",
            )
            self.assertIsNone(
                config_blocked_telemetry["cache_conclusion"]["cached_input_share"]
            )
            self.assertIsNone(
                config_blocked_telemetry["cache_conclusion"]["turn_cache_presence"]
            )
            for field in (
                "product_version",
                "policy_profile",
                "gate_profile",
                "agent_identity",
                "route_identity",
                "model_identity",
                "adapter_identity",
                "parser_identity",
                "digest_identity",
            ):
                self.assertIn(field, forged_config_identity)

            unsupported_identity = benchmark_runner._build_cache_record_identity(
                command=["codex", "exec", "-"],
                **kwargs,
            )
            self.assertEqual(
                unsupported_identity["cache_analytics_status"], "unsupported"
            )
            self.assertIsNone(unsupported_identity["identity_sha256"])
            self.assertIn(
                "model_identity.model",
                unsupported_identity["missing_identity_fields"],
            )

            adversarial_events = {
                "future_adapter": {
                    "type": "turn.completed",
                    "event_id": "future-adapter",
                    "event_schema_version": "codex-turn-completed-v1",
                    "adapter_version": "future-adapter-v99",
                    "usage": {"input_tokens": 10, "cached_input_tokens": 5},
                },
                "invalid_usage": {
                    "type": "turn.completed",
                    "event_id": "invalid-usage",
                    "event_schema_version": "codex-turn-completed-v1",
                    "adapter_version": "codex-cli-jsonl-v1",
                    "usage": {"input_tokens": 10, "cached_input_tokens": 11},
                },
                "missing_stable_id": {
                    "type": "turn.completed",
                    "event_schema_version": "codex-turn-completed-v1",
                    "adapter_version": "codex-cli-jsonl-v1",
                    "usage": {"input_tokens": 10, "cached_input_tokens": 5},
                },
                "legacy_schema": {
                    "type": "turn.completed",
                    "event_id": "legacy-schema",
                    "adapter_version": "codex-cli-jsonl-v1",
                    "usage": {"input_tokens": 10, "cached_input_tokens": 5},
                },
                "legacy_adapter": {
                    "type": "turn.completed",
                    "event_id": "legacy-adapter",
                    "event_schema_version": "codex-turn-completed-v1",
                    "usage": {"input_tokens": 10, "cached_input_tokens": 5},
                },
            }
            for case, event in adversarial_events.items():
                with self.subTest(case=case):
                    partial_telemetry = benchmark_runner._observer_telemetry(
                        json.dumps(event)
                    )
                    blocked = benchmark_runner._build_cache_record_identity(
                        command=["codex", "exec", "--model", "gpt-5.4", "-"],
                        **{**kwargs, "observer_telemetry": partial_telemetry},
                    )
                    self.assertEqual(
                        blocked["cache_analytics_status"], "unsupported"
                    )
                    self.assertIsNone(blocked["identity_sha256"])
                    self.assertEqual(
                        blocked["cache_analytics_reason"],
                        "observer_telemetry_incomplete",
                    )
                    self.assertNotEqual(
                        blocked["observer_telemetry_verification"]["failure_fields"],
                        [],
                    )
                    expected_failure = {
                        "future_adapter": "observed_adapter_versions",
                        "invalid_usage": "invalid_events",
                        "missing_stable_id": "events_without_stable_id",
                        "legacy_schema": "observed_event_schema_versions",
                        "legacy_adapter": "observed_adapter_versions",
                    }[case]
                    self.assertIn(
                        expected_failure,
                        blocked["observer_telemetry_verification"]["failure_fields"],
                    )
                    bound = benchmark_runner._bind_observer_cache_identity(
                        partial_telemetry, blocked
                    )
                    self.assertEqual(
                        bound["cache_conclusion"]["status"], "unsupported"
                    )
                    self.assertIsNone(
                        bound["cache_conclusion"]["cached_input_share"]
                    )
                    self.assertIsNone(
                        bound["cache_conclusion"]["turn_cache_presence"]
                    )

    def test_benchmark_summary_groups_distinct_cache_identities(self) -> None:
        def record(scenario_id: str, identity_sha256: str, input_tokens: int) -> dict:
            telemetry = benchmark_runner._observer_telemetry(
                json.dumps(
                    {
                        "type": "turn.completed",
                        "event_id": scenario_id,
                        "event_schema_version": "codex-turn-completed-v1",
                        "adapter_version": "codex-cli-jsonl-v1",
                        "usage": {
                            "input_tokens": input_tokens,
                            "cached_input_tokens": input_tokens // 2,
                        },
                    }
                )
            )
            identity = {
                "schema_version": "goal-teams-cache-identity-v2.38",
                "cache_analytics_status": "supported",
                "cache_analytics_reason": "complete_identity",
                "identity_sha256": identity_sha256,
                "partial_identity_sha256": identity_sha256,
                "missing_identity_fields": [],
            }
            return {
                "scenario_id": scenario_id,
                "result": "passed",
                "cache_identity": identity,
                "observer_telemetry": benchmark_runner._bind_observer_cache_identity(
                    telemetry, identity
                ),
            }

        summary = benchmark_runner._summarize_observer_telemetry(
            [record("S1", "a" * 64, 10), record("S2", "b" * 64, 20)]
        )
        self.assertEqual(summary["cache_analytics_status"], "grouped")
        self.assertFalse(summary["cross_identity_aggregation"])
        self.assertEqual(summary["identity_group_count"], 2)
        self.assertIsNone(summary["input_tokens"])
        self.assertIsNone(summary["cached_input_share"])
        self.assertEqual(
            sorted(group["input_tokens"] for group in summary["identity_groups"]),
            [10, 20],
        )

        single_identity = benchmark_runner._summarize_observer_telemetry(
            [record("S1", "a" * 64, 10), record("S2", "a" * 64, 20)]
        )
        self.assertEqual(single_identity["cache_analytics_status"], "supported")
        self.assertEqual(single_identity["identity_group_count"], 1)
        self.assertEqual(single_identity["input_tokens"], 30)
        self.assertEqual(single_identity["cached_input_share"], 0.5)

        missing = benchmark_runner._summarize_observer_telemetry(
            [
                {
                    "scenario_id": "missing",
                    "result": "passed",
                    "observer_telemetry": benchmark_runner._observer_telemetry(
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "usage": {
                                    "input_tokens": 10,
                                    "cached_input_tokens": 5,
                                },
                            }
                        )
                    ),
                }
            ]
        )
        self.assertEqual(missing["cache_analytics_status"], "unsupported")
        self.assertIsNone(missing["cached_input_share"])
        self.assertEqual(
            missing["identity_groups"][0]["cache_analytics_status"],
            "unsupported",
        )

    def test_effective_config_honors_ignore_and_hashes_all_config_classes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            codex_home = Path(td)
            files = {
                "config.toml": "model='private-model'\n",
                "agents/private-agent.toml": "name='agent'\n",
                "skills/private-skill/SKILL.md": "secret skill name\n",
                "plugins/private-plugin/plugin.json": "{}\n",
            }
            for relative, content in files.items():
                path = codex_home / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            ignored = benchmark_runner._effective_codex_config_identity(
                ["codex", "exec", "--ignore-user-config", "-"],
                codex_home=codex_home,
            )
            self.assertTrue(ignored["user_config_ignored"])
            self.assertFalse(ignored["local_config_scanned"])
            self.assertEqual(ignored["file_count"], 0)
            self.assertEqual(ignored["entries"], [])
            self.assertEqual(ignored["declaration_status"], "declared")
            self.assertEqual(ignored["verification_status"], "partial")
            self.assertFalse(ignored["effective_config_verified"])
            self.assertFalse(ignored["isolation_verified"])
            self.assertEqual(ignored["trace_proof_status"], "unavailable")

            forged = benchmark_runner._effective_codex_config_identity(
                ["codex", "exec", "--ignore-user-config", "-"],
                codex_home=codex_home,
                trace_proof={
                    "verification_status": "complete",
                    "effective_config_verified": True,
                    "user_config_ignored": True,
                    "trace_sha256": "a" * 64,
                },
            )
            self.assertEqual(forged["verification_status"], "partial")
            self.assertFalse(forged["effective_config_verified"])
            self.assertFalse(forged["isolation_verified"])
            self.assertEqual(forged["trace_proof_status"], "invalid_untrusted")
            self.assertIsNone(forged["trace_proof_sha256"])

            observed = benchmark_runner._effective_codex_config_identity(
                ["codex", "exec", "-"], codex_home=codex_home
            )
            self.assertFalse(observed["user_config_ignored"])
            self.assertTrue(observed["local_config_scanned"])
            self.assertEqual(observed["verification_status"], "partial")
            self.assertFalse(observed["effective_config_verified"])
            self.assertEqual(observed["file_count"], 4)
            self.assertEqual(
                observed["class_counts"],
                {"config": 1, "agents": 1, "skills": 1, "plugins": 1},
            )
            self.assertTrue(
                all(
                    "path_sha256" in entry
                    and "class" in entry
                    and "path" not in entry
                    for entry in observed["entries"]
                )
            )
            serialized = json.dumps(observed, sort_keys=True)
            for name in (
                "private-agent.toml",
                "private-skill",
                "private-plugin",
                str(codex_home),
            ):
                self.assertNotIn(name, serialized)

    def test_benchmark_subject_identity_uses_staged_bytes_and_reports_source_mismatch(self) -> None:
        def write_prompt_root(root: Path, rules: str) -> None:
            (root / "references").mkdir(parents=True)
            (root / "RULES.md").write_text(rules, encoding="utf-8")
            (root / "references" / "prompt-cache-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-prompt-cache-v2.38",
                        "budget_policy": TEST_BUDGET_POLICY,
                        "routes": {
                            "benchmark": {
                                "ordered_refs": ["RULES.md"],
                                "limit_bytes": 4096,
                                "dynamic_tail_labels": ["scenario_input"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_root = root / "source"
            staged_root = root / "staged"
            write_prompt_root(source_root, "source working-tree rules\n")
            write_prompt_root(staged_root, "actual staged subject rules\n")

            subject_identity, comparison = (
                benchmark_runner._build_benchmark_prompt_identity_report(
                    source_root, staged_root
                )
            )
            expected_staged = prompt_cache.build_prompt_identity(staged_root, "benchmark")
            source_identity = prompt_cache.build_prompt_identity(source_root, "benchmark")

            self.assertEqual(subject_identity, expected_staged)
            self.assertNotEqual(
                subject_identity["route_static_digest"],
                source_identity["route_static_digest"],
            )
            self.assertEqual(comparison["subject_identity_scope"], "staged_package")
            self.assertEqual(
                comparison["diagnostic_identity_scope"], "source_repository"
            )
            self.assertFalse(comparison["identities_match"])
            self.assertIn("route_static_digest", comparison["mismatch_fields"])
            self.assertEqual(
                comparison["staged_route_static_digest"],
                subject_identity["route_static_digest"],
            )
            self.assertEqual(
                comparison["source_route_static_digest"],
                source_identity["route_static_digest"],
            )
            self.assertNotIn("source_route_static_digest", subject_identity)

    def test_context_budget_includes_repo_wrapper_and_route_budgets(self) -> None:
        self.assertIsNotNone(context_budget)
        result = context_budget.evaluate(ROOT, context_budget.DEFAULT_LIMIT)
        wrapper = ROOT / ".agents" / "skills" / "goal-teams" / "SKILL.md"
        if wrapper.is_file():
            self.assertIn(
                ".agents/skills/goal-teams/SKILL.md", result["startup"]["files"]
            )
        else:
            self.assertNotIn(
                ".agents/skills/goal-teams/SKILL.md", result["startup"]["files"]
            )
            self.assertEqual(result["startup"]["ordered_refs"], result["base"]["ordered_refs"])
        self.assertLessEqual(result["startup"]["bytes"], context_budget.DEFAULT_LIMIT)
        required_routes = {
            "runtime",
            "capability",
            "telemetry",
            "benchmark",
            "production",
        }
        self.assertTrue(required_routes <= set(result["routes"]))
        for route_id in required_routes:
            route = result["routes"][route_id]
            self.assertEqual(route["ordered_refs"], route["manifest_ordered_refs"])
            self.assertLessEqual(route["bytes"], route["limit_bytes"])
            self.assertTrue(route["passed"])

    def test_legacy_router_keeps_sorted_membership_and_sibling_compiles_order(self) -> None:
        self.assertTrue(PROMPT_MANIFEST_PATH.is_file(), PROMPT_MANIFEST_PATH)
        request = {"backend": True, "tests": True, "risk": "medium"}
        policy_route = gt.route(request)
        actual = policy_route["rule_set"]
        expected_legacy = sorted(
            {
                "RULES.md",
                "references/invariants.md",
                "references/compat.md",
                "references/rules-testing.md",
            }
        )
        self.assertEqual(actual, expected_legacy)
        self.assertEqual(len(actual), len(set(actual)))
        compiled = gt.prompt_plan_for_features(request)
        self.assertEqual(compiled["policy_route"], policy_route)
        self.assertEqual(
            compiled["prompt_plan"]["ordered_refs"],
            prompt_cache.order_prompt_refs(ROOT, expected_legacy),
        )
        self.assertIn("references/prompt-cache-manifest.json", (ROOT / "SKILL.md").read_text(encoding="utf-8"))

    def test_structured_route_keeps_signed_membership_but_compiles_manifest_order(self) -> None:
        request = {
            "schema_version": "goal-teams-project-route-v2.36",
            "product_version": "V2.36",
            "target_kind": "generic_project",
            "project_size": "medium",
            "work_type": "feature",
            "release": False,
            "ui": False,
            "backend": True,
            "api": False,
            "cli": False,
            "tests": True,
            "risk": "high",
            "security_sensitive": True,
            "external_write": False,
            "auth": False,
            "payment": False,
            "migration": False,
            "destructive": False,
            "ui_mode": "none",
            "specialist_requests": [],
        }
        original = gt.route(request)
        compiled = gt.prompt_plan_for_features(request)
        self.assertEqual(compiled["policy_route"], original)
        self.assertTrue(compiled["policy_route_byte_compatible"])
        self.assertEqual(
            compiled["rule_set_semantics"],
            "signed_policy_membership_not_prompt_order",
        )
        ordered = compiled["prompt_plan"]["ordered_refs"]
        self.assertEqual(ordered, prompt_cache.order_prompt_refs(ROOT, original["rule_set"]))
        self.assertEqual(set(ordered), set(original["rule_set"]))
        self.assertNotEqual(ordered, original["rule_set"])
        self.assertTrue(compiled["prompt_plan"]["passed"])

    def test_prompt_plan_features_rejects_duplicate_structured_keys(self) -> None:
        request = {
            "schema_version": "goal-teams-project-route-v2.36",
            "product_version": "V2.36",
            "target_kind": "generic_project",
            "project_size": "medium",
            "work_type": "feature",
            "release": False,
            "ui": False,
            "backend": True,
            "api": False,
            "cli": False,
            "tests": True,
            "risk": "low",
            "security_sensitive": False,
            "external_write": False,
            "auth": False,
            "payment": False,
            "migration": False,
            "destructive": False,
            "ui_mode": "none",
            "specialist_requests": [],
        }
        raw = json.dumps(request, separators=(",", ":"))
        raw = raw.replace(
            '"project_size":"medium"',
            '"project_size":"small","project_size":"medium"',
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "features.json"
            path.write_text(raw, encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "v23" / "goalteams_v23.py"),
                    "prompt-plan",
                    "--features",
                    str(path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result["error_code"], "E_V235_ROUTE_CONFLICT")

    def test_subagent_developer_instructions_have_a_shared_exact_prefix(self) -> None:
        instructions: list[str] = []
        for path in sorted((ROOT / "subagents").glob("goal-*.toml")):
            match = re.search(
                r'developer_instructions = """\n(.*?)\n"""',
                path.read_text(encoding="utf-8"),
                re.DOTALL,
            )
            self.assertIsNotNone(match, path)
            instructions.append(match.group(1))
        self.assertGreaterEqual(len(instructions), 18)
        common_prefix = os.path.commonprefix(instructions)
        self.assertGreaterEqual(
            len(common_prefix.encode("utf-8")),
            512,
            f"shared exact prefix is only {len(common_prefix.encode('utf-8'))} bytes",
        )
        self.assertEqual(len(instructions), len(set(instructions)))

    def test_member_goal_packet_puts_dynamic_instance_at_the_tail(self) -> None:
        packet = (ROOT / "prompts" / "packets" / "member-goal-packet.md").read_text(
            encoding="utf-8"
        )
        marker = "<!-- goal-teams-dynamic-tail -->"
        offset = packet.find(marker)
        self.assertGreaterEqual(offset, 0, "dynamic-tail marker is missing")
        self.assertGreaterEqual(offset / len(packet), 0.80)
        self.assertGreaterEqual(packet.find("<"), offset)
        tail = packet[offset:]
        for field in ("agent_run_id", "member_id", "goal", "locked_scope"):
            self.assertIn(field, tail)


if __name__ == "__main__":
    unittest.main()
