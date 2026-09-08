from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.v267.output_dashboard import serialize_dashboard, validate_dashboard
from scripts.v268.output_gateway import render_response
from scripts.v268.specification_delivery import observe_record, prepare_record
from tests.v268.dashboard_fixture import _view
from tests.v268.test_output_gateway import request_for


ROOT = Path(__file__).resolve().parents[2]
TABLE_HEADER = "| 优先级 | 任务 / 子任务 | Subagent 成员 | 进度 |"


class TestDashboardCompletion(unittest.TestCase):
    """Completion is a presentation of bound facts, never empty-row inference."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix=".v268-completion-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)

    def execution_view(
        self, *, empty: bool = True, counts: tuple[int, int, int, int] = (4, 4, 14, 14),
        gap: int = 0, blocked: int = 0, decision: str = "stop",
    ) -> dict:
        view = _view()
        dashboard, context, loop = view["dashboard"], view["context"], view["loop"]
        links = [dashboard["tasklist_ref"], dashboard["state_machine_ref"],
                 *context["core_rules"], *context["project_knowledge"], *context["tools"],
                 loop["evidence_ref"], loop["banchmark_ref"], loop["loop_review_ref"]]
        for link in links:
            destination = self.repo / link["href"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / link["href"], destination)
        if empty:
            for key, count in zip(
                ("completed_tasks", "total_tasks", "completed_subtasks", "total_subtasks"), counts,
            ):
                dashboard[key] = count
            dashboard["active_rows"] = []
            completed, total, completed_subtasks, total_subtasks = counts
            tasklist = ["# Completion fixture TaskList", ""]
            tasklist.extend(f"- T{index}: {'completed' if index <= completed else 'pending'}"
                            for index in range(1, total + 1))
            tasklist.extend(f"  - S{index}: {'completed' if index <= completed_subtasks else 'pending'}"
                            for index in range(1, total_subtasks + 1))
            (self.repo / dashboard["tasklist_ref"]["href"]).write_text("\n".join(tasklist), encoding="utf-8")
        loop.update(gap_count=gap, blocked_count=blocked, decision=decision)
        state_path = self.repo / dashboard["state_machine_ref"]["href"]
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for key in ("completed_tasks", "total_tasks", "completed_subtasks", "total_subtasks"):
            state["dashboard"][key] = dashboard[key]
        state["dashboard"]["active_rows"] = [
            {key: value for key, value in row.items() if key != "parallel"}
            for row in dashboard["active_rows"]
        ]
        if empty:
            state["dashboard"]["ready_layers"] = []
        state["loop"] = {key: loop[key] for key in state["loop"]}
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        for key, link in (
            ("tasklist_sha256", dashboard["tasklist_ref"]),
            ("state_machine_sha256", dashboard["state_machine_ref"]),
            ("evidence_sha256", loop["evidence_ref"]),
            ("banchmark_sha256", loop["banchmark_ref"]),
            ("loop_review_sha256", loop["loop_review_ref"]),
        ):
            view["bindings"][key] = hashlib.sha256((self.repo / link["href"]).read_bytes()).hexdigest()
        self.assertTrue(validate_dashboard(view, loop_decision=decision, repo_root=self.repo)["ok"])
        return view

    def execute(self, view: dict) -> dict:
        request = request_for("development", view["loop"]["decision"])
        request.update(result="", dashboard=view, current_round=view["loop"]["current_round"],
                       estimated_total_rounds=view["loop"]["estimated_total_rounds"])
        return render_response(request, self.repo)

    def assert_completed_presentation(self, response: dict) -> None:
        self.assertTrue(response["ok"], response["errors"])
        body = response["body"]
        self.assertIn("本轮全部完成", body)
        self.assertRegex(body, r"(?:暂无|没有|无).{0,20}进行中.{0,20}剩余|进行中\s*0.{0,10}剩余\s*0")
        self.assertNotIn(TABLE_HEADER, body)
        labels = ["◆ Goal-Teams 任务执行看板", "◆ Context / Knowledge / Tools", "◆ LOOP："]
        self.assertEqual(sorted(body.index(label) for label in labels), [body.index(label) for label in labels])
        for label in ("P ｜ 计划 / 下一轮目标", "D ｜ 执行 / 本轮执行", "C ｜ 检查 / 执行结果", "A ｜ 改进 / 调整行动"):
            self.assertIn(label, body)
        self.assertEqual(hashlib.sha256(body.encode("utf-8")).hexdigest(), response["body_sha256"])
        self.assertEqual("unavailable", response["host_enforcement"])

    def test_bound_completed_execution_replaces_empty_table_and_preserves_links(self) -> None:
        for decision in ("continue", "stop"):
            with self.subTest(decision=decision):
                view = self.execution_view(decision=decision)
                response = self.execute(view)
                self.assert_completed_presentation(response)
                self.assertIn("已完成任务 4/4｜已完成子任务 14/14", response["body"])
                for name in ("tasklist_ref", "state_machine_ref"):
                    self.assertIn(str(self.repo / view["dashboard"][name]["href"]), response["body"])

    def test_completed_execution_without_subtasks_keeps_truthful_zero_denominator(self) -> None:
        response = self.execute(self.execution_view(counts=(4, 4, 0, 0)))
        self.assert_completed_presentation(response)
        self.assertIn("已完成任务 4/4｜已完成子任务 0/0", response["body"])

    def test_active_execution_keeps_v267_renderer_bytes(self) -> None:
        view = self.execution_view(empty=False, gap=3, blocked=1, decision="continue")
        expected = serialize_dashboard(view, loop_decision="continue", repo_root=self.repo)
        response = self.execute(view)
        self.assertTrue(response["ok"], response["errors"])
        self.assertIn(expected.replace("\n", "\n  "), response["body"])
        self.assertIn(TABLE_HEADER, response["body"])
        self.assertNotIn("本轮全部完成", response["body"])

    def test_empty_execution_rows_do_not_make_incomplete_counts_complete(self) -> None:
        for counts in ((3, 4, 14, 14), (4, 4, 13, 14)):
            with self.subTest(counts=counts):
                response = self.execute(self.execution_view(counts=counts, decision="continue"))
                self.assertNotIn("本轮全部完成", response["body"])

    def test_zero_task_execution_does_not_report_all_complete(self) -> None:
        response = self.execute(self.execution_view(counts=(0, 0, 0, 0), decision="continue"))
        self.assertNotIn("本轮全部完成", response["body"])

    def test_gap_or_blocker_prevents_all_complete_notice(self) -> None:
        for gap, blocked in ((1, 0), (0, 1), (1, 1)):
            with self.subTest(gap=gap, blocked=blocked):
                response = self.execute(self.execution_view(gap=gap, blocked=blocked, decision="continue"))
                self.assertNotIn("本轮全部完成", response["body"])

    def test_stale_completed_view_remains_blocked(self) -> None:
        view = self.execution_view()
        before = copy.deepcopy(view)
        with (self.repo / view["dashboard"]["tasklist_ref"]["href"]).open("a", encoding="utf-8") as handle:
            handle.write("\nLater unbound task revision\n")
        response = self.execute(view)
        self.assertFalse(response["ok"])
        self.assertEqual("blocked", response["output_contract"])
        self.assertEqual("replan", response["loop_decision"])
        self.assertNotIn("本轮全部完成", response["body"])
        self.assertNotIn("◆ Goal-Teams 任务执行看板", response["body"])
        self.assertEqual(before, view)

    def document_record(self, stage: str) -> dict:
        record = prepare_record(self.repo, record_id=f"doc-{stage}", user_request="记录完成态验收范围",
                                paths=["docs/Completion.md"], owner="writer", reviewer="reviewer")
        if stage == "pending":
            return record
        artifact = self.repo / "docs/Completion.md"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text("# Completion fixture\n只验证本地完成态呈现。\n", encoding="utf-8")
        reviews = [] if stage == "partial" else [{
            "path": "docs/Completion.md", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "reviewer": "reviewer", "verdict": "passed", "note": "独立测试夹具中的范围审核事实。",
        }]
        return observe_record(record, self.repo, reviews=reviews, reflection="保持真实读回与审核绑定。")

    def test_completed_document_has_notice_without_empty_table_and_retains_artifact(self) -> None:
        request = request_for("document")
        request.update(result="", specification_record=self.document_record("completed"))
        response = render_response(request, self.repo)
        self.assert_completed_presentation(response)
        self.assertEqual("completed", response["artifact_delivery"])
        self.assertIn(str(self.repo / "docs/Completion.md"), response["body"])
        self.assertNotIn("TaskList.md", response["body"])

    def test_pending_and_partial_documents_keep_real_unfinished_rows(self) -> None:
        for stage in ("pending", "partial"):
            with self.subTest(stage=stage):
                request = request_for("document", "continue")
                request.update(result="", specification_record=self.document_record(stage))
                response = render_response(request, self.repo)
                self.assertTrue(response["ok"], response["errors"])
                self.assertEqual(stage, response["artifact_delivery"])
                self.assertNotIn("本轮全部完成", response["body"])
                self.assertIn(TABLE_HEADER, response["body"])
                task_section = response["body"].split("◆ Context / Knowledge / Tools", 1)[0]
                self.assertRegex(task_section, r"\| P[0-9] \| .+ \| .+ \| .+ \|")


if __name__ == "__main__":
    unittest.main()
