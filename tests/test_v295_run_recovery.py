"""An interrupted command is explicitly settled, never silently treated as a pass."""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from tests.test_gt import GT, HAS_GIT
from tests import test_v295_completion as completion_tests


@unittest.skipUnless(HAS_GIT and os.name == "posix", "POSIX process and git fixture required")
class RunRecoveryTests(unittest.TestCase):
    def test_dead_run_recovery_retains_a_gap_until_the_same_command_really_passes(self):
        repo = completion_tests.CompletionCLITests.ready_repo(self)
        ready = repo.path / ".goal-teams" / "child-pid"
        release = repo.path / ".goal-teams" / "release-child"
        command = ("from pathlib import Path; import os,time; "
                   "Path('.goal-teams/child-pid').write_text(str(os.getpid())); "
                   "deadline=time.monotonic()+30; "
                   "exec(\"while not Path('.goal-teams/release-child').exists() and time.monotonic()<deadline: time.sleep(.02)\"); "
                   "print('completed controlled check')")
        argv = [sys.executable, "-c", command]
        proc = subprocess.Popen([sys.executable, str(GT), "run", "T1", "--kind", "affected", "--name", "recoverable", "--", *argv],
                                cwd=repo.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        try:
            deadline = time.monotonic()+10
            while not ready.exists() and proc.poll() is None and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists())
            started = [e for e in repo.events() if e["type"] == "run.started"][-1]["seq"]
            args = ["recover-run", str(started), "--reason", "controlled worker killed; descendants stopped", "--confirm-stopped"]
            alive = repo.gt(*args)
            self.assertNotEqual(alive.returncode, 0, "cannot settle a live worker")
            os.killpg(int(ready.read_text()), signal.SIGKILL)
            proc.kill()
            proc.communicate(timeout=10)
            self.assertNotEqual(repo.gt("--json", "finish").returncode, 0, "dead PID alone never erases the gap")
            no_confirmation = repo.gt("recover-run", str(started), "--reason", "controlled worker killed")
            self.assertNotEqual(no_confirmation.returncode, 0)
            recovered = repo.gt(*args)
            self.assertEqual(recovered.returncode, 0, recovered.stdout+recovered.stderr)
            self.assertEqual(repo.gt(*args, env={"GT_SUBSESSION": "1"}).returncode, 3)
            self.assertNotEqual(repo.gt(*args).returncode, 0, "one start cannot be settled twice")
            check = json.loads(repo.gt("--json", "check").stdout)
            self.assertFalse(check["ok"], check)
            repo.ok("run", "T1", "--kind", "affected", "--name", "unrelated", "--", sys.executable, "-c", "pass")
            self.assertFalse(json.loads(repo.gt("--json", "check").stdout)["ok"], "an unrelated success cannot close this gap")
            release.write_text("continue")
            repo.ok("run", "T1", "--kind", "affected", "--name", "recoverable", "--", *argv)
            repo.ok("finish")
            settled = [e for e in repo.events() if e["type"] == "run.interrupted"]
            self.assertEqual(len(settled), 1)
            self.assertFalse(settled[0]["data"]["passed"])
        finally:
            release.write_text("continue")
            if proc.poll() is None:
                if ready.exists():
                    try:
                        os.killpg(int(ready.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                proc.kill()
                proc.communicate(timeout=10)
