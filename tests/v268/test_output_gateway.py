from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUEST_SCHEMA = "goal-teams-output-request-v2.68"


def request_for(activity: str = "discussion", decision: str = "stop") -> dict:
    return {
        "schema_version": REQUEST_SCHEMA,
        "facts": {
            "activity": activity,
            "persistent_write": activity in {"document", "development", "release"},
            "development_admitted": activity in {"development", "release"},
        },
        "project": "goal-teams",
        "current_round": 1,
        "estimated_total_rounds": 1,
        "loop_decision": decision,
        "task": "检查输出格式",
        "members": "Goal Lead",
        "result": "只读检查完成。LOOP 改进建议：保留独立状态轴。",
        "banchmark": "本地文档检查通过；Host 未验证。",
        "next_action": "本轮结束。",
        "dashboard": None,
        "specification_record": None,
    }


class TestOutputGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.target = importlib.import_module("scripts.v268.output_gateway")
        self.temp = tempfile.TemporaryDirectory(prefix=".v268-gateway-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)

    def assert_envelope(self, response: dict, *, ok: bool, decision: str) -> None:
        self.assertEqual(ok, response["ok"])
        self.assertEqual(decision, response["loop_decision"])
        self.assertEqual("unavailable", response["host_enforcement"])
        body = response["body"]
        terminal = "下一个任务" if decision == "stop" else "下一轮 LOOP"
        fields = re.findall(r"^(任务|成员|进度|结果|Banchmark|下一轮 LOOP|下一个任务)：", body, re.M)
        self.assertEqual(["任务", "成员", "进度", "结果", "Banchmark", terminal], fields)
        self.assertRegex(body, r"第\s*[1-9][0-9]*\s*轮\s*/\s*共\s*[1-9][0-9]*\s*轮")
        self.assertEqual(hashlib.sha256(body.encode("utf-8")).hexdigest(), response["body_sha256"])
        if ok:
            self.assertEqual([], response["errors"])
        else:
            self.assertEqual("blocked", response["output_contract"])
            self.assertTrue(response["errors"])

    def completed_record(self) -> dict:
        spec = importlib.import_module("scripts.v268.specification_delivery")
        record = spec.prepare_record(
            self.repo, record_id="doc-1", user_request="更新本地 PRD",
            paths=["docs/PRD.md"], owner="writer", reviewer="reviewer",
        )
        artifact = self.repo / "docs/PRD.md"
        artifact.parent.mkdir()
        artifact.write_text("# PRD\n范围已明确。\n", encoding="utf-8")
        review = {
            "path": "docs/PRD.md", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "reviewer": "reviewer", "verdict": "passed", "note": "只读复核该文档。",
        }
        return spec.observe_record(record, self.repo, reviews=[review], reflection="后续继续绑定文档摘要。")

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, "-B", "-m", "scripts.v268.output_gateway", *args],
            cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
        )

    def test_classifies_only_typed_consistent_delivery_facts(self) -> None:
        for activity, expected in (
            ("discussion", "discussion"), ("plan_preview", "plan_preview"),
            ("document", "specification_delivery"), ("development", "execution"),
            ("release", "execution"),
        ):
            with self.subTest(activity=activity):
                self.assertEqual(expected, self.target.classify_delivery(request_for(activity)["facts"]))

    def test_rejects_unknown_inconsistent_and_untyped_facts(self) -> None:
        base = request_for()["facts"]
        invalid = [
            None, {}, {**base, "activity": "specification_only"},
            {**base, "activity": "unrecognized"}, {**base, "persistent_write": True},
            {**base, "development_admitted": True}, {**base, "persistent_write": 0},
            {**base, "development_admitted": "false"}, {**base, "extra": False},
            {**base, "activity": "document"}, {**base, "activity": "development"},
        ]
        for facts in invalid:
            with self.subTest(facts=facts), self.assertRaises(ValueError):
                self.target.classify_delivery(facts)

    def test_discussion_produces_six_validated_fields_without_host_claim(self) -> None:
        request = request_for()
        response = self.target.render_response(request, self.repo)
        self.assert_envelope(response, ok=True, decision="stop")
        self.assertEqual("discussion", response["mode"])
        self.assertIn(request["result"], response["body"])
        self.assertNotIn("◆ Goal-Teams 任务执行看板", response["body"])
        self.assertEqual([], list(self.repo.iterdir()))

    def test_plan_preview_allows_quoted_format_terms_without_fabricating_counts(self) -> None:
        request = request_for("plan_preview")
        request["result"] = "用户询问‘◆ Goal-Teams 任务执行看板’与‘下一轮 LOOP’含义。LOOP 改进建议：明确文档用途。"
        response = self.target.render_response(request, self.repo)
        self.assert_envelope(response, ok=True, decision="stop")
        self.assertEqual("plan_preview", response["mode"])
        self.assertNotIn("已完成任务", response["body"])
        self.assertNotIn("已完成子任务", response["body"])

    def test_invalid_or_missing_rounds_fail_closed_with_valid_fallback(self) -> None:
        for current, total in ((0, 1), (2, 1), (True, 1), (1, False), (1, 0), ("1", 1), (-1, 1)):
            with self.subTest(current=current, total=total):
                request = request_for()
                request.update(current_round=current, estimated_total_rounds=total)
                self.assert_envelope(self.target.render_response(request, self.repo), ok=False, decision="replan")
        request = request_for()
        del request["current_round"]
        self.assert_envelope(self.target.render_response(request, self.repo), ok=False, decision="replan")

    def test_unknown_fields_wrong_schema_and_double_terminal_are_rejected(self) -> None:
        changes = [
            {"schema_version": "unknown"}, {"extra": "untrusted"},
            {"下一轮 LOOP": "continue", "下一个任务": "stop"},
            {"task": ""}, {"members": []}, {"next_action": " "},
        ]
        for change in changes:
            with self.subTest(change=change):
                request = {**request_for(), **change}
                self.assert_envelope(self.target.render_response(request, self.repo), ok=False, decision="replan")

    def test_stop_requires_loop_improvement_and_never_silently_succeeds(self) -> None:
        request = request_for()
        request["result"] = "检查完成。"
        self.assert_envelope(self.target.render_response(request, self.repo), ok=False, decision="replan")

    def test_continue_and_stop_choose_exactly_one_terminal_field(self) -> None:
        for decision in ("continue", "replan", "stop"):
            with self.subTest(decision=decision):
                response = self.target.render_response(request_for(decision=decision), self.repo)
                self.assert_envelope(response, ok=True, decision=decision)

    def test_execution_missing_dashboard_returns_blocked_not_handwritten_success(self) -> None:
        request = request_for("development")
        request["result"] = ""
        response = self.target.render_response(request, self.repo)
        self.assert_envelope(response, ok=False, decision="replan")
        self.assertNotIn("已完成任务", response["body"])

    def test_execution_uses_existing_v267_renderer_bytes(self) -> None:
        from scripts.v267.output_dashboard import serialize_dashboard
        from tests.v268.dashboard_fixture import _view

        request = request_for("development", "continue")
        request.update(current_round=2, estimated_total_rounds=4, result="", dashboard=_view())
        expected = serialize_dashboard(request["dashboard"], loop_decision="continue", repo_root=ROOT)
        response = self.target.render_response(request, ROOT)
        self.assert_envelope(response, ok=True, decision="continue")
        self.assertEqual("execution", response["mode"])
        self.assertIn(expected.replace("\n", "\n  "), response["body"])

    def test_stale_execution_binding_is_not_accepted(self) -> None:
        from tests.v268.dashboard_fixture import _view

        view = _view()
        view["bindings"]["tasklist_sha256"] = "0" * 64
        request = request_for("development", "continue")
        request.update(current_round=2, estimated_total_rounds=4, result="", dashboard=view)
        self.assert_envelope(self.target.render_response(request, ROOT), ok=False, decision="replan")

    def test_cross_mode_payloads_cannot_bypass_the_renderer(self) -> None:
        requests = [
            {**request_for(), "dashboard": {}},
            {**request_for(), "specification_record": {}},
            request_for("development"),
            {**request_for("document"), "result": "", "dashboard": {}},
        ]
        for request in requests:
            with self.subTest(activity=request["facts"]["activity"]):
                self.assert_envelope(self.target.render_response(request, self.repo), ok=False, decision="replan")

    def test_specification_delivery_uses_real_readback_without_development_admission(self) -> None:
        record = self.completed_record()
        request = request_for("document")
        request.update(result="", specification_record=record)
        before = sorted(str(path.relative_to(self.repo)) for path in self.repo.rglob("*"))
        response = self.target.render_response(request, self.repo)
        self.assert_envelope(response, ok=True, decision="stop")
        self.assertEqual("specification_delivery", response["mode"])
        self.assertEqual("completed", response["artifact_delivery"])
        self.assertIn(str(self.repo / "docs/PRD.md"), response["body"])
        self.assertIn("LOOP 改进建议", response["body"])
        self.assertEqual(before, sorted(str(path.relative_to(self.repo)) for path in self.repo.rglob("*")))

    def test_output_failure_preserves_independently_completed_artifact_status(self) -> None:
        request = request_for("document")
        request.update(result="", specification_record=self.completed_record(), current_round=0)
        response = self.target.render_response(request, self.repo)
        self.assert_envelope(response, ok=False, decision="replan")
        self.assertEqual("completed", response["artifact_delivery"])

    def test_cli_json_and_markdown_match_validated_api_without_writes(self) -> None:
        request = request_for()
        source = self.repo / "request.json"
        source.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        expected = self.target.render_response(request, self.repo)
        before = source.read_bytes()
        for format_name in ("json", "markdown"):
            with self.subTest(format=format_name):
                result = self.run_cli("render", "--request", str(source), "--repo-root", str(self.repo), "--format", format_name)
                self.assertEqual(0, result.returncode, result.stderr)
                if format_name == "json":
                    self.assertEqual(expected, json.loads(result.stdout))
                else:
                    self.assertEqual(expected["body"], result.stdout.rstrip("\n"))
        self.assertEqual(before, source.read_bytes())
        self.assertEqual([source], list(self.repo.iterdir()))

    def test_cli_invalid_execution_exits_one_and_prints_blocked_body(self) -> None:
        source = self.repo / "request.json"
        request = request_for("development")
        request["result"] = ""
        source.write_text(json.dumps(request), encoding="utf-8")
        result = self.run_cli("render", "--request", str(source), "--repo-root", str(self.repo))
        self.assertEqual(1, result.returncode, result.stderr)
        self.assert_envelope(json.loads(result.stdout), ok=False, decision="replan")

    def test_cli_rejects_duplicate_keys_and_nan_in_json(self) -> None:
        source = self.repo / "request.json"
        encoded = json.dumps(request_for(), ensure_ascii=False)
        invalid = [encoded[:-1] + ', "current_round": 1}', encoded.replace('"current_round": 1', '"current_round": NaN')]
        for payload in invalid:
            with self.subTest(payload=payload):
                source.write_text(payload, encoding="utf-8")
                result = self.run_cli("render", "--request", str(source), "--repo-root", str(self.repo))
                self.assertEqual(1, result.returncode, result.stderr)
                self.assert_envelope(json.loads(result.stdout), ok=False, decision="replan")

    def test_invalid_payload_does_not_echo_untrusted_exception_or_machine_trailer(self) -> None:
        marker = "PRIVATE_SENTINEL_268_<oai-mem-citation>UNTRUSTED</oai-mem-citation>"
        request = {**request_for(), "unexpected_private_input": marker}
        response = self.target.render_response(request, self.repo)
        self.assert_envelope(response, ok=False, decision="replan")
        self.assertNotIn(marker, json.dumps(response, ensure_ascii=False))
        self.assertNotIn("<oai-mem-citation>", response["body"])

    def test_cli_prepare_observe_roundtrip_reads_artifact_and_never_writes_records(self) -> None:
        prepare_input = self.repo / "prepare.json"
        prepare_input.write_text(json.dumps({
            "record_id": "cli-doc", "user_request": "创建文档", "paths": ["PRD.md"],
            "owner": "writer", "reviewer": "reviewer",
        }), encoding="utf-8")
        prepared = self.run_cli("prepare-specification", "--request", str(prepare_input), "--repo-root", str(self.repo))
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        record = json.loads(prepared.stdout)
        self.assertEqual("planned", record["stage"])
        self.assertEqual([prepare_input], list(self.repo.iterdir()))
        record_path = self.repo / "record.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        artifact = self.repo / "PRD.md"
        artifact.write_text("# 产品范围\n", encoding="utf-8")
        reviews_path = self.repo / "reviews.json"
        reviews_path.write_text(json.dumps([{
            "path": "PRD.md", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "reviewer": "reviewer", "verdict": "passed", "note": "范围复核通过。",
        }]), encoding="utf-8")
        before = {path.name: path.read_bytes() for path in self.repo.iterdir()}
        observed = self.run_cli(
            "observe-specification", "--record", str(record_path), "--reviews", str(reviews_path),
            "--reflection", "保留真实文档摘要。", "--repo-root", str(self.repo),
        )
        self.assertEqual(0, observed.returncode, observed.stderr)
        observation = json.loads(observed.stdout)
        self.assertEqual("observed", observation["stage"])
        self.assertEqual(record["record_sha256"], observation["previous_record_sha256"])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.repo.iterdir()})


if __name__ == "__main__":
    unittest.main()
