"""Capability statuses describe observations, never infer a headless launch from --version."""
from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch

from tests.test_gt import SCRIPTS
sys.path.insert(0, str(SCRIPTS))
from goalteams.adapters.base import HostAdapter


class VersionOnlyAdapter(HostAdapter):
    name = "version-only"
    binary = "version-only"


class HostProbeTests(unittest.TestCase):
    def test_version_success_proves_only_command_availability(self):
        completed = subprocess.CompletedProcess(["version-only", "--version"], 0, "1.0\n", "")
        with patch("goalteams.adapters.base.shutil.which", return_value="/synthetic/version-only"), \
                patch("goalteams.adapters.base.subprocess.run", return_value=completed) as run:
            report = VersionOnlyAdapter().probe()
        self.assertNotEqual(report["items"]["headless_launch"]["status"], "probe_passed")
        self.assertEqual(report["items"]["command_available"]["status"], "probe_passed")
        self.assertEqual(report["items"]["cancel"]["status"], "documented")
        self.assertEqual(run.call_count, 1, "probe must not start a paid model session")
        self.assertEqual(run.call_args.args[0], ["/synthetic/version-only", "--version"])

    def test_error_text_from_nonzero_version_is_not_availability(self):
        completed = subprocess.CompletedProcess(["version-only", "--version"], 1, "", "fatal: config missing")
        with patch("goalteams.adapters.base.shutil.which", return_value="/synthetic/version-only"), \
                patch("goalteams.adapters.base.subprocess.run", return_value=completed):
            report = VersionOnlyAdapter().probe()
        self.assertIsNone(report["version"])
        self.assertEqual(report["items"]["command_available"]["status"], "unavailable")
        self.assertEqual(report["items"]["headless_launch"]["status"], "unavailable")

    def test_missing_binary_does_not_claim_launch_or_cancel_probe(self):
        with patch("goalteams.adapters.base.shutil.which", return_value=None):
            report = VersionOnlyAdapter().probe()
        self.assertEqual(report["items"]["headless_launch"]["status"], "unavailable")
        self.assertEqual(report["items"]["cancel"]["status"], "documented")
