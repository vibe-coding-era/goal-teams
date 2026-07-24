from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock
from urllib.request import ProxyHandler, build_opener


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


def black_png(width: int = 1280, height: int = 720) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + (b"\x00" * (width * 3)) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


class TestingCapabilityBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = scorer.load_canonical_manifest()

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

    def test_reference_app_readiness_allows_slow_ci_startup(self) -> None:
        process = mock.Mock()
        process.poll.return_value = None
        with (
            mock.patch.object(
                runner.time,
                "monotonic",
                side_effect=[0.0, 0.0, 6.0],
            ),
            mock.patch.object(runner.time, "sleep"),
            mock.patch.object(
                runner,
                "http_json",
                side_effect=[
                    runner.URLError("warming up"),
                    {"status": 200},
                ],
            ),
        ):
            runner.wait_ready("http://127.0.0.1:1", process)

    def test_loopback_http_client_ignores_environment_proxies(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"http_proxy": "http://127.0.0.1:9"},
            clear=False,
        ):
            default_opener = build_opener()
        self.assertTrue(
            any(isinstance(handler, ProxyHandler) for handler in default_opener.handlers)
        )
        self.assertFalse(
            any(
                isinstance(handler, ProxyHandler)
                for handler in runner.LOOPBACK_OPENER.handlers
            )
        )

    def test_readiness_failure_includes_service_diagnostic(self) -> None:
        process = mock.Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temporary:
            service_log = Path(temporary) / "service.log"
            service_log.write_text("bind diagnostic\n", encoding="utf-8")
            with (
                mock.patch.object(
                    runner.time,
                    "monotonic",
                    side_effect=[0.0, 1.0],
                ),
                mock.patch.object(runner.time, "sleep"),
                mock.patch.object(
                    runner,
                    "http_json",
                    side_effect=runner.URLError("not ready"),
                ),
                self.assertRaisesRegex(RuntimeError, "bind diagnostic"),
            ):
                runner.wait_ready(
                    "http://127.0.0.1:1",
                    process,
                    timeout_seconds=0.5,
                    service_log=service_log,
                )

    def test_reference_process_uses_macos_safe_spawn_conditions(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            (Path(temporary) / "service.log").open("w", encoding="utf-8") as log_handle,
            mock.patch.object(
                runner.subprocess,
                "Popen",
                return_value=mock.sentinel.process,
            ) as popen,
        ):
            process = runner.start_reference_process(
                port=12345,
                db_path=Path(temporary) / "orders.sqlite3",
                mode="reference",
                browser_read_delay_ms=0,
                run_id="run-id",
                log_handle=log_handle,
            )
        self.assertIs(mock.sentinel.process, process)
        _args, kwargs = popen.call_args
        self.assertNotIn("cwd", kwargs)
        self.assertIs(False, kwargs["close_fds"])

    def test_scorer_rejects_shrunken_ten_point_manifest(self) -> None:
        shrunken = {
            "schema_version": "goal-teams-testing-capability-benchmark-v2.44",
            "benchmark_id": "GT-BENCH-005",
            "maximum_score": 10.0,
            "cases": [
                {
                    "case_id": "API-AUTH-001",
                    "layer": "api",
                    "title": "self reported",
                    "weight": 10.0,
                }
            ],
            "candidate_modes": [],
        }
        with self.assertRaises(scorer.ScoreError):
            scorer.validate_canonical_manifest(shrunken)

    def test_scorer_cli_rejects_manifest_override(self) -> None:
        process = subprocess.run(
            [
                sys.executable,
                str(SCORER_PATH),
                "missing-evidence.json",
                "--manifest",
                str(MANIFEST_PATH),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, process.returncode)
        self.assertIn("unrecognized arguments: --manifest", process.stderr)

    def test_scorer_rejects_prose_or_exit_code_without_case_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence, _score = runner.run_candidate(
                "reference",
                Path(temporary),
                browser_mode="off",
            )
            evidence["exit_code"] = 0
            evidence["summary"] = "all tests passed"
            evidence["cases"] = []
            with self.assertRaisesRegex(scorer.ScoreError, "missing evidence cases"):
                scorer.score_evidence(
                    evidence,
                    evidence_root=Path(temporary) / "reference",
                )

    def test_scorer_recomputes_declared_status_from_raw_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence, _score = runner.run_candidate(
                "reference",
                Path(temporary),
                browser_mode="off",
            )
            auth_case = next(
                item for item in evidence["cases"] if item["case_id"] == "API-AUTH-001"
            )
            auth_case["evidence"]["unauthenticated_status"] = 200
            with self.assertRaisesRegex(scorer.ScoreError, "bound raw artifact"):
                scorer.score_evidence(
                    evidence,
                    evidence_root=Path(temporary) / "reference",
                )

    def test_not_run_browser_cases_receive_zero_points(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence, score = runner.run_candidate(
                "reference",
                Path(temporary),
                browser_mode="off",
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
                    )
                    service_log = (
                        Path(temporary) / mode / "service.log"
                    ).read_text(encoding="utf-8")
                    self.assertIn('"event": "starting"', service_log)
                    self.assertIn('"event": "ready"', service_log)
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
                browser_read_delay_ms=500,
            )
        recovery = next(
            item for item in evidence["cases"] if item["case_id"] == "E2E-RECOVERY-001"
        )
        self.assertEqual("passed", recovery["status"])
        self.assertEqual(1, recovery["evidence"]["delta"])
        self.assertGreater(recovery["evidence"]["count_before"], 0)
        self.assertEqual(10.0, score["score"])

    def test_scorer_rejects_missing_or_forged_run_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="off"
            )
            missing = json.loads(json.dumps(evidence))
            missing.pop("run")
            with self.assertRaisesRegex(scorer.ScoreError, "run provenance"):
                scorer.score_evidence(missing, evidence_root=root / "reference")

            wrong_manifest = json.loads(json.dumps(evidence))
            wrong_manifest["run"]["manifest_sha256"] = "0" * 64
            with self.assertRaisesRegex(scorer.ScoreError, "canonical manifest"):
                scorer.score_evidence(
                    wrong_manifest, evidence_root=root / "reference"
                )

            wrong_source = json.loads(json.dumps(evidence))
            wrong_source["run"]["source_digests"]["runner"] = "0" * 64
            with self.assertRaisesRegex(scorer.ScoreError, "source provenance"):
                scorer.score_evidence(wrong_source, evidence_root=root / "reference")

    def test_scorer_rejects_tampered_raw_observation_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="off"
            )
            binding = evidence["cases"][0]["raw_artifact"]
            raw = root / "reference" / binding["path"]
            raw.write_text(raw.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(scorer.ScoreError, "artifact size mismatch"):
                scorer.score_evidence(evidence, evidence_root=root / "reference")

    def test_scorer_rejects_raw_artifact_ancestor_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="off"
            )
            run_dir = root / "reference"
            raw = run_dir / "raw"
            real_raw = run_dir / "raw-real"
            raw.rename(real_raw)
            os.symlink(real_raw.name, raw)
            with self.assertRaisesRegex(scorer.ScoreError, "ancestor"):
                scorer.score_evidence(evidence, evidence_root=run_dir)

    def test_scorer_rejects_tampered_or_symlinked_screenshot(self) -> None:
        available, _chrome, reason = runner.browser_capability()
        if not available:
            self.skipTest(reason)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="required"
            )
            session = next(
                item for item in evidence["cases"] if item["case_id"] == "E2E-SESSION-001"
            )
            binding = session["evidence"]["screenshot"]
            screenshot = root / "reference" / binding["path"]
            original = screenshot.read_bytes()
            screenshot.write_bytes(original + b"tamper")
            with self.assertRaisesRegex(
                scorer.ScoreError, "behavior oracle derived failed"
            ):
                scorer.score_evidence(evidence, evidence_root=root / "reference")
            screenshot.write_bytes(original)

            backup = screenshot.with_name("real-session.png")
            shutil.copyfile(screenshot, backup)
            screenshot.unlink()
            os.symlink(backup.name, screenshot)
            with self.assertRaisesRegex(
                scorer.ScoreError, "behavior oracle derived failed"
            ):
                scorer.score_evidence(evidence, evidence_root=root / "reference")

    def test_scorer_rejects_png_magic_only_even_when_rebound(self) -> None:
        available, _chrome, reason = runner.browser_capability()
        if not available:
            self.skipTest(reason)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="required"
            )
            session = next(
                item for item in evidence["cases"] if item["case_id"] == "E2E-SESSION-001"
            )
            binding = session["evidence"]["screenshot"]
            screenshot = root / "reference" / binding["path"]
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
            binding["size"] = screenshot.stat().st_size
            binding["sha256"] = scorer.sha256_file(screenshot)
            raw_binding = session["raw_artifact"]
            raw_path = root / "reference" / raw_binding["path"]
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_payload["observation"] = session["evidence"]
            raw_path.write_text(
                json.dumps(raw_payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raw_binding["size"] = raw_path.stat().st_size
            raw_binding["sha256"] = scorer.sha256_file(raw_path)
            with self.assertRaisesRegex(
                scorer.ScoreError, "behavior oracle derived failed"
            ):
                scorer.score_evidence(evidence, evidence_root=root / "reference")

    def test_scorer_rejects_valid_black_png_not_bound_to_browser_trace(self) -> None:
        available, _chrome, reason = runner.browser_capability()
        if not available:
            self.skipTest(reason)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="required"
            )
            session = next(
                item for item in evidence["cases"] if item["case_id"] == "E2E-SESSION-001"
            )
            binding = session["evidence"]["screenshot"]
            screenshot = root / "reference" / binding["path"]
            screenshot.write_bytes(black_png())
            binding["size"] = screenshot.stat().st_size
            binding["sha256"] = scorer.sha256_file(screenshot)
            raw_binding = session["raw_artifact"]
            raw_path = root / "reference" / raw_binding["path"]
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_payload["observation"] = session["evidence"]
            raw_path.write_text(
                json.dumps(raw_payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raw_binding["size"] = raw_path.stat().st_size
            raw_binding["sha256"] = scorer.sha256_file(raw_path)
            with self.assertRaisesRegex(
                scorer.ScoreError, "behavior oracle derived failed"
            ):
                scorer.score_evidence(evidence, evidence_root=root / "reference")

    def test_scorer_rejects_rebound_trace_with_forged_frame_content(self) -> None:
        available, _chrome, reason = runner.browser_capability()
        if not available:
            self.skipTest(reason)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="required"
            )
            session = next(
                item for item in evidence["cases"] if item["case_id"] == "E2E-SESSION-001"
            )
            trace_binding = session["evidence"]["browser_trace"]
            trace_path = root / "reference" / trace_binding["path"]
            with zipfile.ZipFile(trace_path) as archive:
                entries = {
                    info.filename: archive.read(info.filename)
                    for info in archive.infolist()
                }
            frame_name = next(
                name
                for name in entries
                if name.startswith("resources/") and name.endswith(".jpeg")
            )
            entries[frame_name] = b"forged"
            with zipfile.ZipFile(
                trace_path, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for name, content in entries.items():
                    archive.writestr(name, content)
            trace_binding["size"] = trace_path.stat().st_size
            trace_binding["sha256"] = scorer.sha256_file(trace_path)
            raw_binding = session["raw_artifact"]
            raw_path = root / "reference" / raw_binding["path"]
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_payload["observation"] = session["evidence"]
            raw_path.write_text(
                json.dumps(raw_payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raw_binding["size"] = raw_path.stat().st_size
            raw_binding["sha256"] = scorer.sha256_file(raw_path)
            with self.assertRaisesRegex(
                scorer.ScoreError, "behavior oracle derived failed"
            ):
                scorer.score_evidence(evidence, evidence_root=root / "reference")

    def test_scorer_rejects_run_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence, _score = runner.run_candidate(
                "reference", root, browser_mode="off"
            )
            evidence["run"]["run_id"] = "00000000-0000-4000-8000-000000000000"
            with self.assertRaises(scorer.ScoreError):
                scorer.score_evidence(evidence, evidence_root=root / "reference")


if __name__ == "__main__":
    unittest.main()
