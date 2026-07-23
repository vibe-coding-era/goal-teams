from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "benchmark" / "v244_testing_capability_runner.py"
SCORER_PATH = ROOT / "scripts" / "benchmark" / "v244_testing_capability_scorer.py"
MANIFEST_PATH = (
    ROOT / "benchmarks" / "fixtures" / "v2.44" / "testing-capability-cases.json"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_module("v244_testing_capability_runner_test", RUNNER_PATH)
scorer = load_module("v244_testing_capability_scorer_test", SCORER_PATH)


class TestingCapabilityBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = runner.load_json(MANIFEST_PATH)

    def test_manifest_reserves_exactly_ten_behavior_points(self) -> None:
        cases = self.manifest["cases"]
        self.assertEqual(8, len(cases))
        self.assertEqual(10.0, sum(case["weight"] for case in cases))
        self.assertEqual(
            {"api": 6.0, "e2e": 4.0},
            {
                layer: sum(case["weight"] for case in cases if case["layer"] == layer)
                for layer in ("api", "e2e")
            },
        )

    def test_scorer_rejects_prose_or_exit_code_without_case_behavior(self) -> None:
        fake = {
            "schema_version": scorer.EVIDENCE_SCHEMA,
            "benchmark_id": "GT-BENCH-005",
            "candidate": {"mode": "fake"},
            "exit_code": 0,
            "summary": "all tests passed",
            "cases": [],
        }
        with self.assertRaisesRegex(scorer.ScoreError, "missing evidence cases"):
            scorer.score_evidence(fake, self.manifest)

    def test_scorer_recomputes_declared_status_from_raw_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence, _score = runner.run_candidate(
                "reference",
                Path(temporary),
                browser_mode="off",
                manifest=self.manifest,
            )
            auth_case = next(
                item for item in evidence["cases"] if item["case_id"] == "API-AUTH-001"
            )
            auth_case["evidence"]["unauthenticated_status"] = 200
            with self.assertRaisesRegex(
                scorer.ScoreError, "behavior oracle derived failed"
            ):
                scorer.score_evidence(evidence, self.manifest)

    def test_not_run_browser_cases_receive_zero_points(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence, score = runner.run_candidate(
                "reference",
                Path(temporary),
                browser_mode="off",
                manifest=self.manifest,
            )
        self.assertEqual("not_run", evidence["browser"]["status"])
        self.assertEqual(4, score["not_run_count"])
        self.assertEqual(6.0, score["score"])
        self.assertEqual(0.0, score["by_layer"]["e2e"]["earned"])

    def test_api_seeded_defects_are_detected_by_behavior(self) -> None:
        expectations = {
            "api_auth_bypass": "API-AUTH-001",
            "api_idempotency_broken": "API-IDEMPOTENCY-001",
            "api_concurrency_race": "API-CONCURRENCY-001",
            "api_eventual_consistency_stale": "API-CONSISTENCY-001",
        }
        with tempfile.TemporaryDirectory() as temporary:
            for mode, expected_case in expectations.items():
                with self.subTest(mode=mode):
                    evidence, _score = runner.run_candidate(
                        mode,
                        Path(temporary),
                        browser_mode="off",
                        manifest=self.manifest,
                    )
                    outcomes = {
                        item["case_id"]: item["status"] for item in evidence["cases"]
                    }
                    self.assertEqual("failed", outcomes[expected_case])

    def test_reference_candidate_executes_real_browser_when_available(self) -> None:
        available, _chrome, reason = runner.browser_capability()
        if not available:
            self.skipTest(reason)
        with tempfile.TemporaryDirectory() as temporary:
            evidence, score = runner.run_candidate(
                "reference",
                Path(temporary),
                browser_mode="required",
                manifest=self.manifest,
            )
        self.assertEqual("executed", evidence["browser"]["status"])
        self.assertEqual(10.0, score["score"])
        self.assertEqual(0, score["not_run_count"])

    def test_recovery_waits_for_delayed_initial_browser_count_sync(self) -> None:
        available, _chrome, reason = runner.browser_capability()
        if not available:
            self.skipTest(reason)
        with tempfile.TemporaryDirectory() as temporary:
            evidence, score = runner.run_candidate(
                "reference",
                Path(temporary),
                browser_mode="required",
                manifest=self.manifest,
                browser_read_delay_ms=500,
            )
        recovery = next(
            item for item in evidence["cases"] if item["case_id"] == "E2E-RECOVERY-001"
        )
        self.assertEqual("passed", recovery["status"])
        self.assertEqual(1, recovery["evidence"]["delta"])
        self.assertGreater(recovery["evidence"]["count_before"], 0)
        self.assertEqual(10.0, score["score"])


if __name__ == "__main__":
    unittest.main()
