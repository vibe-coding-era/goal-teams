from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "v23" / "engineering_metrics.py"
SPEC = importlib.util.spec_from_file_location("engineering_metrics", MODULE_PATH)
assert SPEC and SPEC.loader
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def event(event_id: str, kind: str, **values: object) -> dict[str, object]:
    return {"event_id": event_id, "type": kind, "evidence_refs": [f"EVD-{event_id}"], **values}


def payload(run_id: str = "RUN-1", completed_at: str = "2026-07-22T10:00:00+08:00") -> dict[str, object]:
    return {
        "run": {
            "run_id": run_id,
            "completed_at": completed_at,
            "repository_or_project_id": "goal-teams",
            "work_type": "implementation",
            "execution_profile": "standard",
            "project_version": "V2.43",
            "artifact_version": "A1",
            "goal_teams_version": "V2.43",
        },
        "events": [
            event("E01", "change_unit_declared", change_unit_id="C1"),
            event("E02", "change_unit_declared", change_unit_id="C2"),
            event("E03", "acceptance_attempt", change_unit_id="C1", attempt=1, outcome="passed", independent_validator=True),
            event("E04", "acceptance_attempt", change_unit_id="C2", attempt=1, outcome="failed", independent_validator=True),
            event("E05", "acceptance_attempt", change_unit_id="C2", attempt=2, outcome="passed", independent_validator=True),
            event("E06", "repair_loop_completed", loop_id="L1"),
            event("E07", "goal_converged"),
            event("E08", "human_escalation", reason_type="flow_selection"),
            event("E09", "human_escalation", reason_type="risk_acceptance"),
            event("E10", "spec_ambiguity", blocked=True),
            event("E11", "cost_observed", model_cost=8, compute_cost=1, currency="USD", coverage=1, source_trust="trusted"),
            event("E12", "change_deployed", change_unit_id="C1"),
            event("E13", "change_deployed", change_unit_id="C2"),
            event("E14", "defect_escaped", change_unit_id="C2", independently_confirmed=True),
            event("E15", "change_rolled_back", change_unit_id="C1"),
            event("E16", "production_observation_closed"),
            event("E17", "context_segment_loaded", segment_id="S1", weight=40, weight_basis="tokens"),
            event("E18", "context_segment_loaded", segment_id="S2", weight=60, weight_basis="tokens"),
            event("E19", "context_segment_used", segment_id="S1"),
            event("E20", "ssot_drift", fingerprint="DRIFT-A"),
            event("E21", "ssot_drift", fingerprint="DRIFT-A"),
            event("E22", "failure_detected", failure_id="F1", signature="api:timeout", detected_at="2026-07-22T01:00:00Z"),
            event("E23", "failure_recovered", failure_id="F1", active_seconds=30),
            event("E24", "failure_detected", failure_id="F2", signature="api:timeout", detected_at="2026-07-22T01:02:00Z"),
            event("E25", "failure_recovered", failure_id="F2", active_seconds=10),
            event("E26", "review_defect_caught", defect_id="D1", independent_reviewer=True, before_acceptance=True),
            event("E27", "review_defect_missed", defect_id="D2"),
            event("E28", "review_observation_closed"),
            event(
                "ECOV",
                "telemetry_coverage",
                complete=True,
                domains=["human_escalation", "spec_ambiguity", "ssot_drift", "failure"],
            ),
        ],
    }


class EngineeringMetricsTests(unittest.TestCase):
    def test_manifest_is_complete_machine_ssot(self) -> None:
        manifest = metrics.load_manifest()
        self.assertEqual(len(manifest["metrics"]), 12)
        self.assertEqual(
            [item["metric_id"] for item in manifest["metrics"]],
            ["FPAR", "LCC", "HER", "SAR", "CPAC", "DER", "RRR", "CWR", "SDI", "RFR", "ARCR", "MRT"],
        )
        self.assertRegex(metrics.manifest_digest(manifest), r"^[0-9a-f]{64}$")
        self.assertEqual(
            metrics.manifest_digest(manifest),
            hashlib.sha256((ROOT / "references" / "engineering-metrics-manifest.json").read_bytes()).hexdigest(),
        )

    def test_all_metric_algorithms_and_deduplication(self) -> None:
        result = metrics.calculate_metrics(payload())
        current = result["current"]
        self.assertEqual(set(current), {"FPAR", "LCC", "HER", "SAR", "CPAC", "DER", "RRR", "CWR", "SDI", "RFR", "ARCR", "MRT"})
        self.assertEqual(current["FPAR"]["value"], 0.5)
        self.assertEqual(current["LCC"]["value"], 1.0)
        self.assertEqual(current["HER"]["value"], 1.0)
        self.assertEqual(current["SAR"]["value"], 1.0)
        self.assertEqual(current["CPAC"]["value"], 4.5)
        self.assertEqual(current["DER"]["value"], 0.5)
        self.assertEqual(current["RRR"]["value"], 0.5)
        self.assertEqual(current["CWR"]["value"], 0.6)
        self.assertEqual(current["SDI"]["value"], 1.0)
        self.assertEqual(current["RFR"]["value"], 0.5)
        self.assertEqual(current["ARCR"]["value"], 0.5)
        self.assertEqual(current["MRT"]["value"], 20.0)
        self.assertNotIn("api:timeout", json.dumps(result))
        self.assertEqual(len(result["comparison_facts"]["failure_signature_hashes"]), 1)
        self.assertIn("E22", current["RFR"]["event_ids"])
        self.assertIn("EVD-E22", current["RFR"]["evidence_refs"])
        self.assertNotIn("E22", current["RFR"]["evidence_refs"])

    def test_pending_unavailable_and_not_applicable_are_not_zero(self) -> None:
        minimal = payload("MIN")
        minimal["events"] = [
            event("M1", "change_unit_declared", change_unit_id="C1"),
            event("M2", "failure_detected", failure_id="F1", signature="build:failed", detected_at="2026-07-22T01:00:00Z"),
        ]
        current = metrics.calculate_metrics(minimal)["current"]
        self.assertEqual(current["FPAR"]["status"], "pending")
        self.assertIsNone(current["FPAR"]["value"])
        self.assertEqual(current["FPAR"]["coverage"], 0.0)
        self.assertEqual(current["LCC"]["status"], "pending")
        self.assertIsNone(current["LCC"]["value"])
        self.assertEqual(current["CPAC"]["status"], "unavailable")
        self.assertIsNone(current["CPAC"]["value"])
        self.assertEqual(current["DER"]["status"], "not_applicable")
        self.assertIsNone(current["DER"]["value"])
        self.assertEqual(current["MRT"]["status"], "pending")
        self.assertIsNone(current["MRT"]["value"])

    def test_context_use_must_bind_to_a_loaded_segment(self) -> None:
        invalid = payload("BAD-CONTEXT")
        invalid["events"] = [event("E1", "context_segment_used", segment_id="missing")]
        with self.assertRaisesRegex(metrics.EngineeringMetricsError, "E_METRICS_CONTEXT_USE_BINDING"):
            metrics.calculate_metrics(invalid)

    def test_same_schema_history_must_bind_the_same_manifest(self) -> None:
        historical = metrics.calculate_metrics(payload("OLD"))
        historical["algorithm_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(metrics.EngineeringMetricsError, "E_METRICS_HISTORY_MANIFEST_DRIFT"):
            metrics.calculate_metrics(payload("NOW"), [historical])

    def test_missing_coverage_cannot_be_reported_as_zero(self) -> None:
        empty = payload("NO-COVERAGE")
        empty["events"] = []
        current = metrics.calculate_metrics(empty)["current"]
        for metric_id in ("HER", "SAR", "SDI", "RFR", "MRT"):
            self.assertEqual(current[metric_id]["status"], "unavailable")
            self.assertIsNone(current[metric_id]["value"])
            self.assertEqual(current[metric_id]["unavailable_reason"], "missing_telemetry_coverage")

    def test_closed_failure_coverage_with_no_failures_makes_mrt_not_applicable(self) -> None:
        closed = payload("NO-FAILURES-CLOSED")
        closed["events"] = [
            event("COV", "telemetry_coverage", complete=True, domains=["failure"]),
        ]
        current = metrics.calculate_metrics(closed)["current"]
        self.assertEqual(current["RFR"]["status"], "final")
        self.assertEqual(current["RFR"]["value"], 0.0)
        self.assertEqual(current["MRT"]["status"], "not_applicable")
        self.assertEqual(current["MRT"]["coverage"], 1.0)

    def test_unknown_event_type_fails_closed(self) -> None:
        unknown = payload("UNKNOWN")
        unknown["events"].append(event("E-UNKNOWN", "future_unregistered_event"))
        with self.assertRaisesRegex(metrics.EngineeringMetricsError, "E_METRICS_UNKNOWN_EVENT_TYPE"):
            metrics.calculate_metrics(unknown)

    def test_acceptance_outcome_and_attempt_fail_closed(self) -> None:
        invalid_outcome = payload("BAD-OUTCOME")
        invalid_outcome["events"][2]["outcome"] = "bogus"
        with self.assertRaisesRegex(metrics.EngineeringMetricsError, "E_METRICS_ACCEPTANCE_OUTCOME"):
            metrics.calculate_metrics(invalid_outcome)

        invalid_attempt = payload("BAD-ATTEMPT")
        invalid_attempt["events"][2]["attempt"] = 0
        with self.assertRaisesRegex(metrics.EngineeringMetricsError, "E_METRICS_ACCEPTANCE_ATTEMPT"):
            metrics.calculate_metrics(invalid_attempt)

    def test_trusted_cost_requires_explicit_cost_components(self) -> None:
        missing_model_cost = payload("BAD-COST")
        missing_model_cost["events"][10].pop("model_cost")
        with self.assertRaisesRegex(metrics.EngineeringMetricsError, "E_METRICS_MODEL_COST"):
            metrics.calculate_metrics(missing_model_cost)

        missing_compute_cost = payload("BAD-COMPUTE-COST")
        missing_compute_cost["events"][10].pop("compute_cost")
        with self.assertRaisesRegex(metrics.EngineeringMetricsError, "E_METRICS_COMPUTE_COST"):
            metrics.calculate_metrics(missing_compute_cost)

    def test_previous_and_recent_use_final_pooled_values(self) -> None:
        old1 = metrics.calculate_metrics(payload("OLD-1", "2026-07-20T10:00:00+08:00"))
        old2_input = payload("OLD-2", "2026-07-21T10:00:00+08:00")
        old2_input["events"] = [
            item for item in old2_input["events"]
            if item.get("event_id") not in {"E04", "E05"}
        ]
        old2_input["events"].append(
            event("E29", "acceptance_attempt", change_unit_id="C2", attempt=1, outcome="passed", independent_validator=True)
        )
        old2 = metrics.calculate_metrics(old2_input, [old1])
        current = metrics.calculate_metrics(payload("NOW", "2026-07-22T10:00:00+08:00"), [old2, old1])
        self.assertEqual(current["previous"]["FPAR"]["source_run_id"], "OLD-2")
        self.assertEqual(current["previous"]["FPAR"]["value"], 1.0)
        self.assertEqual(current["recent"]["FPAR"]["numerator"], 3.0)
        self.assertEqual(current["recent"]["FPAR"]["denominator"], 4.0)
        self.assertEqual(current["recent"]["FPAR"]["value"], 0.75)
        self.assertEqual(current["recent"]["FPAR"]["status"], "insufficient_sample")
        self.assertEqual(current["recent"]["FPAR"]["sample_count"], 2)

    def test_correction_replaces_prior_event_without_overwrite(self) -> None:
        corrected = payload("CORRECTED")
        corrected["events"].append(
            event(
                "E-CORR",
                "correction",
                target_event_id="E11",
                replacement={
                    "type": "cost_observed",
                    "model_cost": 10,
                    "compute_cost": 2,
                    "currency": "USD",
                    "coverage": 1,
                    "source_trust": "trusted",
                    "evidence_refs": ["EVD-COST-CORRECTED"],
                },
            )
        )
        result = metrics.calculate_metrics(corrected)
        self.assertEqual(result["current"]["CPAC"]["numerator"], 12.0)
        self.assertEqual(result["current"]["CPAC"]["value"], 6.0)
        self.assertIn("E11", result["current"]["CPAC"]["event_ids"])
        self.assertEqual(result["current"]["CPAC"]["evidence_refs"], ["EVD-COST-CORRECTED"])

    def test_okf_report_is_self_contained_and_uses_required_table(self) -> None:
        manifest = metrics.load_manifest()
        result = metrics.calculate_metrics(payload(), manifest=manifest)
        report = metrics.render_okf_report(result, manifest)
        self.assertTrue(report.startswith("---\ntype: Engineering Metrics Report\n"))
        self.assertIn("| 指标 | 本次任务数值 | 上一次的数值 | 近期平均值 |", report)
        self.assertIn("source_ssot: versions/A1/metrics/metric-summary.json", report)
        self.assertIn("# 算法与统计口径", report)
        self.assertIn(metrics.manifest_digest(manifest), report)
        for item in manifest["metrics"]:
            self.assertIn(f"{item['metric_id']} — {item['full_name']} — {item['chinese_name']}", report)
            self.assertIn(item["formula"], report)
            self.assertIn(item["recent_aggregation_rule"], report)

    def test_cli_writes_summary_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            input_path = tmp / "events.json"
            summary_path = tmp / "metric-summary.json"
            report_path = tmp / "engineering-metrics.md"
            input_path.write_text(json.dumps(payload(), ensure_ascii=False), encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "metrics" / "engineering-metrics.py"),
                    "--input", str(input_path),
                    "--summary", str(summary_path),
                    "--report", str(report_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(summary_path.read_text())["schema_version"], metrics.SCHEMA_VERSION)
            self.assertIn("Engineering Metrics Report", report_path.read_text())

    def test_cli_accepts_append_only_jsonl_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            input_path = tmp / "metric-events.jsonl"
            summary_path = tmp / "metric-summary.json"
            report_path = tmp / "engineering-metrics.md"
            source = payload("JSONL")
            records = [{"type": "run_identity", "run": source["run"]}, *source["events"]]
            input_path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "metrics" / "engineering-metrics.py"),
                    "--input", str(input_path),
                    "--summary", str(summary_path),
                    "--report", str(report_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(summary_path.read_text())["run"]["run_id"], "JSONL")

    def test_single_run_identity_jsonl_record_is_valid_empty_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            input_path = Path(raw_tmp) / "metric-events.jsonl"
            input_path.write_text(
                json.dumps({"type": "run_identity", "run": payload("EMPTY")["run"]}) + "\n",
                encoding="utf-8",
            )
            loaded = metrics.load_input_payload(input_path)
            self.assertEqual(loaded["run"]["run_id"], "EMPTY")
            self.assertEqual(loaded["events"], [])

    def test_write_outputs_restores_first_target_if_second_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            summary_path = tmp / "metric-summary.json"
            report_path = tmp / "engineering-metrics.md"
            summary_path.write_text("old-summary", encoding="utf-8")
            report_path.write_text("old-report", encoding="utf-8")
            real_replace = metrics.os.replace
            calls = 0

            def fail_second(source: object, target: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected report replace failure")
                real_replace(source, target)

            with mock.patch.object(metrics.os, "replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected report replace failure"):
                    metrics.write_outputs(payload("ATOMIC"), [], summary_path, report_path)
            self.assertEqual(summary_path.read_text(encoding="utf-8"), "old-summary")
            self.assertEqual(report_path.read_text(encoding="utf-8"), "old-report")
            self.assertEqual(list(tmp.glob(".*.tmp")), [])

    def test_output_conforms_to_v243_schema_when_jsonschema_is_available(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")
        schema = json.loads((ROOT / "schemas" / "v2.43" / "engineering-metrics.schema.json").read_text())
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
            metrics.calculate_metrics(payload())
        )


if __name__ == "__main__":
    unittest.main()
