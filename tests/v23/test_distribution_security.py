"""Independent V2.3 distribution, context, pixel and security gates."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.v23.common import ROOT, gt, parse_envelope, run_cli


def load_script(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


context_budget = load_script("goalteams_context_budget_test", "scripts/checks/check-context-budget.py")
pixel_diff = load_script("goalteams_pixel_diff_test", "scripts/harness/pixel-diff.py")
install_lifecycle = load_script("goalteams_install_lifecycle_test", "scripts/checks/check-install-lifecycle.py")


def process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_process_group_exit(process_group_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_group_exists(process_group_id):
            return True
        time.sleep(0.05)
    return not process_group_exists(process_group_id)


def terminate_process_group(process: subprocess.Popen[str]) -> tuple[str, str]:
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    if not wait_for_process_group_exit(process_group_id, 1):
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"process group leader {process_group_id} survived SIGKILL"
            ) from exc
    if not wait_for_process_group_exit(process_group_id, 5):
        raise RuntimeError(f"process group {process_group_id} survived SIGKILL")
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired as exc:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        raise RuntimeError(
            f"process group {process_group_id} exited but captured pipes remained open"
        ) from exc


def communicate_bounded(
    process: subprocess.Popen[str],
    command: list[str],
    *,
    timeout: float,
) -> tuple[str, str]:
    try:
        return process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = terminate_process_group(process)
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from exc


def run_bounded_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr = communicate_bounded(process, command, timeout=timeout)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


class ContextAndCapabilityTests(unittest.TestCase):
    def test_startup_context_uses_the_v241_manifest_budget_and_routed_rules_are_separate(self) -> None:
        result = context_budget.evaluate(ROOT, context_budget.DEFAULT_LIMIT)
        self.assertTrue(result["passed"], result)
        self.assertLessEqual(result["base"]["bytes"], context_budget.DEFAULT_LIMIT)
        self.assertEqual(result["startup"]["limit_bytes"], context_budget.DEFAULT_LIMIT)
        self.assertIn("references/flow-clarification-protocol.md", result["startup"]["ordered_refs"])
        self.assertEqual(set(result["base"]["files"]), {"SKILL.md", "agents/openai.yaml", "RULES.md"})
        self.assertEqual(
            set(result["routed"]["files"]),
            {
                "references/invariants.md",
                "references/compat.md",
                "prompts/lead/core.md",
                "prompts/lead/planning.md",
                "prompts/packets/memory.md",
            },
        )

    def test_context_budget_fails_closed_when_limit_is_exceeded(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/checks/check-context-budget.py"),
                "--root",
                str(ROOT),
                "--limit-bytes",
                "1",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])

    def test_non_ui_route_does_not_load_pixel_rules(self) -> None:
        route = gt.route({"backend": True, "tests": True})
        self.assertNotIn("references/rules-ui.md", route["rule_set"])
        self.assertNotIn("references/ui-e2e-pixel-protocol.md", route["rule_set"])
        self.assertNotIn("references/ui-visual-contract-protocol.md", route["rule_set"])

    def test_full_restricted_and_privilege_escalation_capabilities(self) -> None:
        fixtures = ROOT / "tests/v23/fixtures/capability"
        full_proc = run_cli("capability", str(fixtures / "full.json"))
        restricted_proc = run_cli("capability", str(fixtures / "restricted.json"))
        escalation_proc = run_cli("capability", str(fixtures / "privilege-escalation.json"))
        self.assertEqual(full_proc.returncode, 0)
        self.assertEqual(restricted_proc.returncode, 0)
        self.assertNotEqual(escalation_proc.returncode, 0)
        full = parse_envelope(full_proc)["capability"]
        restricted = parse_envelope(restricted_proc)["capability"]
        self.assertEqual(full["dispatch_mode"], "goal_subagents")
        self.assertEqual(full["degraded_capability"], [])
        self.assertEqual(restricted["dispatch_mode"], "generic_subagent_or_serial")
        self.assertTrue(restricted["degraded_capability"])
        self.assertEqual(restricted["budget_metric"], "round_time_member_file_size")

    def test_empty_capability_manifest_is_blocked_not_silently_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.json"
            path.write_text("{}\n", encoding="utf-8")
            proc = run_cli("capability", str(path))
        self.assertNotEqual(proc.returncode, 0)
        envelope = parse_envelope(proc)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error_code"], "E_CAPABILITY_MANIFEST_REQUIRED")


class PixelDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.baseline = self.root / "baseline.ppm"
        self.actual = self.root / "actual.ppm"
        pixel_diff.write_ppm(self.baseline, 2, 2, [(0, 0, 0)] * 4)
        pixel_diff.write_ppm(self.actual, 2, 2, [(3, 3, 3), (255, 0, 0), (0, 0, 0), (0, 0, 0)])

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def compare(self, **kwargs):
        return pixel_diff.compare(
            self.baseline,
            self.actual,
            kwargs.pop("changed_ratio_threshold", 1.0),
            kwargs.pop("mae_threshold", 1.0),
            kwargs.pop("color_tolerance", 0),
            None,
            **kwargs,
        )

    def test_color_tolerance_ignores_antialiasing_but_not_real_regression(self) -> None:
        tolerated = self.compare(color_tolerance=3)
        self.assertEqual(tolerated["changed_pixels"], 1)
        self.assertGreater(tolerated["raw_mae"], tolerated["mae"])
        strict = self.compare(changed_ratio_threshold=0.0, color_tolerance=3)
        self.assertFalse(strict["passed"])

    def test_mask_and_mae_are_both_part_of_decision(self) -> None:
        mask = self.root / "mask.ppm"
        pixel_diff.write_ppm(mask, 2, 2, [(0, 0, 0), (255, 255, 255), (0, 0, 0), (0, 0, 0)])
        masked = self.compare(
            changed_ratio_threshold=0.0,
            mae_threshold=0.0,
            color_tolerance=3,
            mask_path=mask,
        )
        self.assertTrue(masked["passed"], masked)
        mae_blocked = self.compare(changed_ratio_threshold=1.0, mae_threshold=0.0, color_tolerance=3)
        self.assertFalse(mae_blocked["passed"])
        self.assertFalse(mae_blocked["global_passed"])

    def test_critical_region_overrides_permissive_global_threshold(self) -> None:
        regions = self.root / "regions.json"
        regions.write_text(
            json.dumps(
                [
                    {
                        "name": "critical-control",
                        "x": 1,
                        "y": 0,
                        "width": 1,
                        "height": 1,
                        "changed_ratio_threshold": 0.0,
                        "mae_threshold": 0.0,
                    }
                ]
            ),
            encoding="utf-8",
        )
        result = self.compare(regions_path=regions)
        self.assertTrue(result["global_passed"])
        self.assertFalse(result["critical_regions"][0]["passed"])
        self.assertFalse(result["passed"])

    def test_environment_mismatch_and_missing_baseline_approval_fail_closed(self) -> None:
        baseline_environment = self.root / "baseline-env.json"
        actual_environment = self.root / "actual-env.json"
        environment = {
            "browser": "Chromium",
            "browser_version": "1",
            "viewport": "2x2",
            "dpr": 1,
            "fonts": ["Test Sans"],
            "os": "test",
        }
        baseline_environment.write_text(json.dumps(environment), encoding="utf-8")
        actual_environment.write_text(json.dumps({**environment, "browser_version": "2"}), encoding="utf-8")
        mismatch = self.compare(
            baseline_environment_path=baseline_environment,
            actual_environment_path=actual_environment,
            require_environment=True,
        )
        self.assertFalse(mismatch["environment"]["comparable"])
        self.assertFalse(mismatch["passed"])
        no_approval = self.compare(require_baseline_approval=True)
        self.assertFalse(no_approval["baseline_approval"]["valid"])
        self.assertFalse(no_approval["passed"])

    def test_replica_mode_requires_environment_and_independent_baseline_approval_by_default(self) -> None:
        tool = ROOT / "scripts/harness/pixel-diff.py"
        missing = subprocess.run(
            [sys.executable, str(tool), str(self.baseline), str(self.actual), "--ui-mode", "replica"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        missing_report = json.loads(missing.stdout)
        self.assertFalse(missing_report["environment"]["comparable"])
        self.assertFalse(missing_report["baseline_approval"]["valid"])

        environment = {
            "browser": "Chromium",
            "browser_version": "1",
            "viewport": "2x2",
            "dpr": 1,
            "fonts": ["Test Sans"],
            "os": "test",
        }
        baseline_environment = self.root / "replica-baseline-env.json"
        actual_environment = self.root / "replica-actual-env.json"
        baseline_environment.write_text(json.dumps(environment), encoding="utf-8")
        actual_environment.write_text(json.dumps(environment), encoding="utf-8")
        approval = self.root / "replica-approval.json"
        approval.write_text(
            json.dumps(
                {
                    "reviewer_run_id": "RUN-INDEPENDENT-PIXEL-REVIEWER",
                    "approved_at": "2026-07-10T00:00:00Z",
                    "reason": "approved immutable replica baseline",
                    "baseline_sha256": pixel_diff.sha256(self.baseline),
                }
            ),
            encoding="utf-8",
        )
        replica_actual = self.root / "replica-actual.ppm"
        shutil.copy2(self.baseline, replica_actual)
        complete = subprocess.run(
            [
                sys.executable,
                str(tool),
                str(self.baseline),
                str(replica_actual),
                "--ui-mode",
                "replica",
                "--baseline-environment",
                str(baseline_environment),
                "--actual-environment",
                str(actual_environment),
                "--baseline-approval",
                str(approval),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)

        common = [
            "--ui-mode",
            "replica",
            "--baseline-environment",
            str(baseline_environment),
            "--actual-environment",
            str(actual_environment),
            "--baseline-approval",
            str(approval),
        ]
        same_path = subprocess.run(
            [sys.executable, str(tool), str(self.baseline), str(self.baseline), *common],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(same_path.returncode, 0)
        self.assertIn("distinct files", json.loads(same_path.stdout)["error"])

        hardlink = self.root / "replica-hardlink.ppm"
        os.link(self.baseline, hardlink)
        same_inode = subprocess.run(
            [sys.executable, str(tool), str(self.baseline), str(hardlink), *common],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(same_inode.returncode, 0)
        self.assertIn("distinct files", json.loads(same_inode.stdout)["error"])


class SecurityTests(unittest.TestCase):
    def test_redaction_and_prompt_injection_fixtures_pass(self) -> None:
        checker = ROOT / "scripts/checks/check-security-fixtures.py"
        proc = subprocess.run(
            [sys.executable, str(checker)], cwd=ROOT, text=True, capture_output=True, check=False
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_same_secret_has_stable_markers_and_raw_value_never_leaks(self) -> None:
        raw = "token=same-secret\nAuthorization: Bearer same-secret\nurl=https://example.test/?token=same-secret"
        redacted_first = gt.redact_text(raw)
        redacted_second = gt.redact_text(raw)
        self.assertEqual(redacted_first, redacted_second)
        self.assertNotIn("same-secret", redacted_first)
        self.assertGreaterEqual(redacted_first.count("[REDACTED"), 3)

    def test_hmac_redaction_correlates_same_secret_across_syntax_without_linking_different_secrets(self) -> None:
        raw = (
            "token=same-secret\n"
            "Authorization: Bearer same-secret\n"
            '{"password":"same-secret"}\n'
            "token=other-secret\n"
        )
        redacted = gt.redact_text(raw, hmac_key="test-audit-key")
        self.assertNotIn("same-secret", redacted)
        self.assertNotIn("other-secret", redacted)
        markers = re.findall(r"\[REDACTED:[0-9a-f]+\]", redacted)
        self.assertGreaterEqual(len(markers), 4)
        self.assertEqual(len(set(markers[:3])), 1, markers)
        self.assertNotEqual(markers[0], markers[3])


class InstallerLifecycleTests(unittest.TestCase):
    def test_bounded_runner_terminates_its_descendant_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            child_pid_path = Path(td) / "child.pid"
            parent_pid_path = Path(td) / "parent.pid"
            child_program = (
                "import pathlib,signal,sys,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "pathlib.Path(sys.argv[1]).write_text(str(__import__('os').getpid()),encoding='utf-8');"
                "time.sleep(60)"
            )
            parent_program = (
                "import os,pathlib,signal,subprocess,sys,time\n"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='utf-8')\n"
                "subprocess.Popen("
                "[sys.executable,'-c',sys.argv[3],sys.argv[2]],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                "deadline=time.monotonic()+5\n"
                "while not pathlib.Path(sys.argv[2]).exists() and time.monotonic()<deadline:\n"
                "    time.sleep(0.01)\n"
                "time.sleep(60)\n"
            )
            command = [
                sys.executable,
                "-c",
                parent_program,
                str(parent_pid_path),
                str(child_pid_path),
                child_program,
            ]
            with self.assertRaises(subprocess.TimeoutExpired):
                run_bounded_process(command, cwd=ROOT, timeout=1)
            self.assertTrue(parent_pid_path.is_file(), "parent process was not started")
            self.assertTrue(child_pid_path.is_file(), "descendant process was not started")
            process_group_id = int(parent_pid_path.read_text(encoding="utf-8"))
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            self.assertFalse(process_group_exists(process_group_id))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"descendant process {child_pid} survived bounded-runner cleanup")

    def test_installer_uses_the_explicit_installed_package_gate(self) -> None:
        checker = (ROOT / "scripts/checks/check.sh").read_text(encoding="utf-8")
        installer = (ROOT / "scripts/install/install-local.sh").read_text(encoding="utf-8")
        self.assertIn('CHECK_MODE="installed-package"', checker)
        self.assertIn('"--installed-package"', installer)
        self.assertIn('"scripts/check.sh --installed-package"', installer)

    def test_only_the_explicit_argument_can_select_installed_package_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_python = root / "fake-python"
            command_log = root / "commands.log"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$GOAL_TEAMS_TEST_COMMAND_LOG\"\n",
                encoding="utf-8",
            )
            os.chmod(fake_python, 0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "GOAL_TEAMS_INSTALL_VALIDATION": "1",
                    "GOAL_TEAMS_TEST_COMMAND_LOG": str(command_log),
                    "PYTHON": str(fake_python),
                }
            )
            checker = ROOT / "scripts/check.sh"
            full = subprocess.run(
                [str(checker)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
            full_commands = command_log.read_text(encoding="utf-8")
            self.assertIn("scripts/checks/check-v23.py", full_commands)
            self.assertIn("scripts/benchmark/benchmark-runner.py --check-only", full_commands)
            self.assertIn("scripts/checks/check-install-lifecycle.py", full_commands)

            command_log.unlink()
            package = subprocess.run(
                [str(checker), "--installed-package"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(package.returncode, 0, package.stdout + package.stderr)
            package_commands = command_log.read_text(encoding="utf-8")
            self.assertNotIn("scripts/checks/check-v23.py", package_commands)
            self.assertNotIn("scripts/benchmark/benchmark-runner.py", package_commands)
            self.assertNotIn("scripts/checks/check-install-lifecycle.py", package_commands)

            unknown = subprocess.run(
                [str(checker), "--unknown-mode"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(unknown.returncode, 2, unknown.stdout + unknown.stderr)

    @unittest.skipIf(
        os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1",
        "cross-Python installer check is not recursively executed inside staging validation",
    )
    def test_copied_pristine_source_validates_across_installer_python_versions(self) -> None:
        validation_python = shutil.which("python3")
        self.assertIsNotNone(validation_python)

        def version(executable: str) -> str:
            return subprocess.run(
                [executable, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()

        validation_version = version(str(validation_python))
        installer_python = next(
            (
                executable
                for name in ("python3.13", "python3.12", "python3.11")
                if (executable := shutil.which(name)) is not None
                and version(executable) != validation_version
            ),
            None,
        )
        if installer_python is None:
            self.skipTest("no second supported Python interpreter is available")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            home = root / "codex-home"
            report = root / "cross-python-report.json"
            install_lifecycle.make_clean_source(source)
            environment = dict(os.environ)
            environment.update(
                {
                    "CODEX_HOME": str(home),
                    "INSTALL_REPORT": str(report),
                    "PYTHON": installer_python,
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            command = [str(source / "scripts/install/install-local.sh"), "--dry-run"]
            proc = run_bounded_process(
                command,
                cwd=source,
                env=environment,
                timeout=240,
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["dependencies"]["python"]["version"], version(installer_python))
            self.assertNotEqual(payload["dependencies"]["python"]["version"], validation_version)
            validation = payload["validation"]
            self.assertEqual(
                [item["phase"] for item in validation],
                [
                    "source",
                    "prompt_identity_source",
                    "package_identity_copy",
                    "package_identity_generated_manifest",
                    "okf_package_tree_staging",
                    "staging",
                    "prompt_identity_staging",
                    "package_identity_post_staging_validation",
                ],
                payload,
            )
            self.assertTrue(all(item["status"] == "passed" for item in validation), payload)
            self.assertEqual(
                [
                    item["command"]
                    for item in validation
                    if item["phase"] in {"source", "staging"}
                ],
                [
                    "scripts/check.sh --installed-package",
                    "scripts/check.sh --installed-package",
                ],
                payload,
            )

    @unittest.skipIf(
        os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1",
        "installer lifecycle is not recursively executed inside staging validation",
    )
    def test_atomic_install_update_failure_rollback_and_uninstall(self) -> None:
        checker = ROOT / "scripts/checks/check-install-lifecycle.py"
        command = [sys.executable, str(checker)]
        proc = run_bounded_process(
            command,
            cwd=ROOT,
            timeout=900,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("failure/rollback/uninstall", proc.stdout)

    @unittest.skipIf(
        os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1",
        "installer source tests are not recursively executed inside staging validation",
    )
    def test_default_install_rejects_untracked_source_and_reports_without_switching(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            home = root / "codex-home"
            report = root / "untracked-report.json"
            install_lifecycle.make_clean_source(source)
            (source / "UNTRACKED-LOCAL-OUTPUT.txt").write_text("must not ship\n", encoding="utf-8")
            environment = dict(os.environ)
            environment.update(
                {
                    "CODEX_HOME": str(home),
                    "INSTALL_REPORT": str(report),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            proc = subprocess.run(
                [str(source / "scripts/install/install-local.sh"), "--dry-run"],
                cwd=source,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertTrue(payload["source"]["dirty"])
            self.assertIn("E_SOURCE_DIRTY", str(payload.get("error_code")))
            self.assertFalse((home / "skills/goal-teams").exists())
            self.assertNotIn("UNTRACKED-LOCAL-OUTPUT.txt", json.dumps(payload))

    @unittest.skipIf(
        os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1",
        "installer source mutation test is not recursively executed inside staging validation",
    )
    def test_concurrent_source_mutation_fails_without_switching_partial_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            home = root / "codex-home"
            report = root / "source-drift-report.json"
            marker = root / "source-validation-started"
            install_lifecycle.make_clean_source(source)
            check_entry = source / "scripts" / "check.sh"
            check_entry.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "ROOT=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")/..\" && pwd)\"\n"
                "if [[ -n \"${GOAL_TEAMS_TEST_SOURCE_MARKER:-}\" ]]; then\n"
                "  : > \"$GOAL_TEAMS_TEST_SOURCE_MARKER\"\n"
                "  sleep 1\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            os.chmod(check_entry, 0o755)
            subprocess.run(["git", "add", "scripts/check.sh"], cwd=source, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "add deterministic source validation marker"],
                cwd=source,
                check=True,
            )
            payload_path = source / "subagents" / "goal-unit-test-runner.toml"
            environment = dict(os.environ)
            environment.update(
                {
                    "CODEX_HOME": str(home),
                    "INSTALL_REPORT": str(report),
                    "GOAL_TEAMS_TEST_SOURCE_MARKER": str(marker),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            process = subprocess.Popen(
                [str(source / "scripts/install/install-local.sh"), "--dry-run"],
                cwd=source,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 5
                while process.poll() is None and not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(marker.exists(), "installer never entered source validation")
                payload_path.write_bytes(payload_path.read_bytes() + b"\n# concurrent source drift\n")
                stdout, stderr = communicate_bounded(
                    process,
                    [str(source / "scripts/install/install-local.sh"), "--dry-run"],
                    timeout=300,
                )
                self.assertNotEqual(process.returncode, 0, stdout + stderr)
                payload = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "failed")
                self.assertIn("E_PACKAGE_SOURCE_CHANGED", str(payload.get("error_code")))
                self.assertFalse((home / "skills/goal-teams").exists())
            finally:
                if process.poll() is None or process_group_exists(process.pid):
                    terminate_process_group(process)


if __name__ == "__main__":
    unittest.main()
