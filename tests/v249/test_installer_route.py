from __future__ import annotations

import unittest

from scripts.v249.test_gate import derive_installer_route


class TestV249InstallerRoute(unittest.TestCase):
    def test_development_without_release_intent_never_schedules_s3(self) -> None:
        for size in ("small", "medium", "large"):
            with self.subTest(size=size):
                route = derive_installer_route(
                    size,
                    release_intent=False,
                    s1_current=True,
                )

                self.assertEqual("not_required", route["gate_requirement"])
                self.assertEqual(0, route["s3_process_invocation_count"])
                self.assertEqual([], route["child_argv"])

    def test_large_release_with_current_s1_schedules_s3(self) -> None:
        route = derive_installer_route(
            "large",
            release_intent=True,
            s1_current=True,
        )

        self.assertEqual("required", route["gate_requirement"])
        self.assertEqual(0, route["s3_process_invocation_count"])
        self.assertEqual([], route["child_argv"])

    def test_medium_release_does_not_schedule_s3(self) -> None:
        route = derive_installer_route(
            "medium",
            release_intent=True,
            s1_current=True,
        )

        self.assertEqual("not_required", route["gate_requirement"])


if __name__ == "__main__":
    unittest.main()
