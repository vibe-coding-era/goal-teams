"""Frozen regression for the independent review's valid-label collision."""

import unittest

from tests.v268 import test_dashboard_completion as fixtures


class TestCompletionHeadingBoundary(unittest.TestCase):
    def test_context_title_inside_link_label_is_not_a_section_boundary(self):
        fixture = fixtures.TestDashboardCompletion()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for field in ("tasklist_ref", "state_machine_ref"):
            with self.subTest(field=field):
                view = fixture.execution_view()
                label = "**◆ Context / Knowledge / Tools：** 说明"
                view["dashboard"][field]["label"] = label
                response = fixture.execute(view)
                self.assertTrue(response["ok"], response["errors"])
                self.assertIn("本轮全部完成", response["body"])
                self.assertIn(label, response["body"])
                self.assertNotIn(fixtures.TABLE_HEADER, response["body"])


if __name__ == "__main__":
    unittest.main()
