from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from tests.v23.common import ROOT


class V245ReleaseEngineerMemberTests(unittest.TestCase):
    def test_member_validator_and_behavior_suite_are_root_gated(self) -> None:
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        validator = subprocess.run(
            [
                sys.executable,
                "prompts/members/release-engineer/runtime/validate_member.py",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(validator.returncode, 0, validator.stdout + validator.stderr)
        report = json.loads(validator.stdout)
        self.assertTrue(report["passed"])

        behavior = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "prompts/members/release-engineer/tests",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(behavior.returncode, 0, behavior.stdout + behavior.stderr)
        self.assertIn("Ran 78 tests", behavior.stderr)

    def test_member_is_packaged_but_not_in_main_prompt_routes(self) -> None:
        manifest = json.loads(
            (ROOT / "references" / "prompt-cache-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        serialized_routes = json.dumps(
            manifest.get("routes", {}), ensure_ascii=False, sort_keys=True
        )
        self.assertNotIn("release-engineer", serialized_routes)
        package_manifest = (
            ROOT / "scripts" / "install" / "package-manifest.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("prefix prompts/", package_manifest)
        self.assertTrue(
            (ROOT / "prompts" / "members" / "release-engineer" / "INDEX.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
