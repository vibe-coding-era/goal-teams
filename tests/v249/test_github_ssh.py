from __future__ import annotations

import unittest

from scripts.v249.test_gate import validate_git_transport


class TestV249GitHubSsh(unittest.TestCase):
    def test_scp_style_ssh_remote_passes(self) -> None:
        verdict = validate_git_transport("git@github.com:owner/repository.git")

        self.assertTrue(verdict["ok"])
        self.assertEqual("ssh", verdict["transport"])

    def test_ssh_url_passes(self) -> None:
        verdict = validate_git_transport(
            "ssh://git@github.com/owner/repository.git"
        )

        self.assertTrue(verdict["ok"])
        self.assertEqual("ssh", verdict["transport"])

    def test_https_remote_fails_closed(self) -> None:
        verdict = validate_git_transport(
            "https://github.com/owner/repository.git"
        )

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_GIT_TRANSPORT_NOT_SSH", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
