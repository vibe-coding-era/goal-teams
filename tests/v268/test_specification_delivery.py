from __future__ import annotations

import copy
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def canonical_record_sha256(record: dict) -> str:
    payload = {key: value for key, value in record.items() if key != "record_sha256"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TestSpecificationDelivery(unittest.TestCase):
    def setUp(self) -> None:
        self.target = importlib.import_module("scripts.v268.specification_delivery")
        self.temp = tempfile.TemporaryDirectory(prefix=".v268-spec-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)

    def prepare(self, paths: list[str] | None = None) -> dict:
        return self.target.prepare_record(
            self.repo, record_id="prd-output-fix", user_request="更新输出格式 PRD",
            paths=["PRD.md"] if paths is None else paths, owner="writer", reviewer="reviewer",
        )

    def write_artifact(self, path: str = "PRD.md", content: str = "# PRD\n输出格式范围\n") -> Path:
        artifact = self.repo / path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(content, encoding="utf-8")
        return artifact

    def review(self, path: str = "PRD.md", verdict: str = "passed") -> dict:
        return {
            "path": path, "sha256": hashlib.sha256((self.repo / path).read_bytes()).hexdigest(),
            "reviewer": "reviewer", "verdict": verdict, "note": "对该文档的范围进行复核。",
        }

    def observe(self, record: dict, reviews: list[dict] | None = None) -> dict:
        return self.target.observe_record(
            record, self.repo, reviews=[self.review()] if reviews is None else reviews,
            reflection="后续核对原始文档与摘要，保持状态边界。",
        )

    def completed(self) -> dict:
        record = self.prepare()
        self.write_artifact()
        return self.observe(record)

    def test_prepare_new_artifact_is_pending_and_does_not_write(self) -> None:
        record = self.prepare()
        self.assertEqual("goal-teams-specification-delivery-v2.68", record["schema_version"])
        self.assertEqual("planned", record["stage"])
        self.assertIs(False, record["product_development_admitted"])
        self.assertIsNone(record["previous_record_sha256"])
        self.assertEqual(["PRD.md"], record["authorized_paths"])
        self.assertEqual([], record["artifacts"])
        self.assertEqual([], record["reviews"])
        self.assertEqual("", record["reflection"])
        self.assertEqual(canonical_record_sha256(record), record["record_sha256"])
        self.assertEqual("pending", self.target.validate_record(record, self.repo)["artifact_delivery"])
        self.assertEqual([], list(self.repo.iterdir()))

    def test_prepare_existing_artifact_binds_baseline_bytes_without_mutating_them(self) -> None:
        artifact = self.write_artifact(content="# 旧 PRD\n")
        baseline = artifact.read_bytes()
        record = self.prepare()
        expected = hashlib.sha256(baseline).hexdigest()
        self.assertIn(expected, json.dumps(record["inputs"]))
        self.assertEqual(baseline, artifact.read_bytes())
        self.assertEqual([artifact], list(self.repo.iterdir()))

    def test_rejects_empty_duplicate_absolute_and_traversal_authorization_paths(self) -> None:
        invalid = [[], ["PRD.md", "PRD.md"], ["../PRD.md"], [str(self.repo / "PRD.md")], [""], ["a/../../PRD.md"]]
        for paths in invalid:
            with self.subTest(paths=paths), self.assertRaises(self.target.SpecificationError) as failure:
                self.prepare(paths)
            self.assertTrue(failure.exception.code)

    def test_owner_cannot_approve_own_document(self) -> None:
        with self.assertRaises(self.target.SpecificationError):
            self.target.prepare_record(
                self.repo, record_id="doc", user_request="写文档", paths=["PRD.md"],
                owner="same-member", reviewer="same-member",
            )

    def test_prepare_rejects_file_and_parent_symlinks(self) -> None:
        self.write_artifact("actual/PRD.md")
        (self.repo / "linked.md").symlink_to(self.repo / "actual/PRD.md")
        (self.repo / "linked-directory").symlink_to(self.repo / "actual", target_is_directory=True)
        for path in ("linked.md", "linked-directory/PRD.md", "linked-directory/new.md"):
            with self.subTest(path=path), self.assertRaises(self.target.SpecificationError):
                self.prepare([path])

    def test_observe_binds_real_artifact_review_and_parent_digest_without_mutation(self) -> None:
        record = self.prepare()
        original = copy.deepcopy(record)
        artifact = self.write_artifact()
        observed = self.observe(record)
        self.assertEqual(original, record)
        self.assertEqual("observed", observed["stage"])
        self.assertEqual(record["record_sha256"], observed["previous_record_sha256"])
        self.assertEqual(canonical_record_sha256(observed), observed["record_sha256"])
        self.assertEqual(1, len(observed["artifacts"]))
        receipt = observed["artifacts"][0]
        self.assertEqual("PRD.md", receipt["path"])
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), receipt["sha256"])
        self.assertEqual(len(artifact.read_bytes()), receipt["bytes"])
        validation = self.target.validate_record(observed, self.repo)
        self.assertTrue(validation["ok"])
        self.assertEqual("completed", validation["artifact_delivery"])
        self.assertEqual([artifact], list(self.repo.iterdir()))

    def test_missing_or_failed_reviews_remain_partial(self) -> None:
        for variant in ("missing", "failed", "one-of-two"):
            with self.subTest(variant=variant):
                paths = ["PRD.md", "Notes.md"] if variant == "one-of-two" else ["PRD.md"]
                record = self.prepare(paths)
                for path in paths:
                    self.write_artifact(path)
                reviews = [] if variant == "missing" else [self.review(verdict="failed" if variant == "failed" else "passed")]
                observed = self.observe(record, reviews)
                self.assertEqual("partial", self.target.validate_record(observed, self.repo)["artifact_delivery"])

    def test_rejects_reviews_with_wrong_file_hash_reviewer_verdict_or_shape(self) -> None:
        record = self.prepare()
        self.write_artifact()
        valid = self.review()
        invalid = [
            {**valid, "path": "another.md"}, {**valid, "sha256": "0" * 64},
            {**valid, "reviewer": "writer"}, {**valid, "reviewer": "someone-else"},
            {**valid, "verdict": "approved"}, {**valid, "external_independence": True},
        ]
        for review in invalid:
            with self.subTest(review=review), self.assertRaises(self.target.SpecificationError):
                self.observe(record, [review])

    def test_observe_rejects_missing_artifact_or_missing_reflection(self) -> None:
        record = self.prepare()
        with self.assertRaises(self.target.SpecificationError):
            self.observe(record, [])
        self.write_artifact()
        with self.assertRaises(self.target.SpecificationError):
            self.target.observe_record(record, self.repo, reviews=[self.review()], reflection="")

    def test_record_tampering_is_rejected_before_claiming_completion(self) -> None:
        observed = self.completed()
        for field, value in (("owner", "intruder"), ("authorized_paths", ["Other.md"]), ("record_sha256", "0" * 64)):
            with self.subTest(field=field):
                tampered = {**observed, field: value}
                with self.assertRaises(self.target.SpecificationError):
                    self.target.validate_record(tampered, self.repo)

    def test_changed_or_deleted_artifacts_invalidate_completed_observation(self) -> None:
        observed = self.completed()
        artifact = self.repo / "PRD.md"
        original = artifact.read_bytes()
        artifact.write_text("# Later revision\n", encoding="utf-8")
        with self.assertRaises(self.target.SpecificationError):
            self.target.validate_record(observed, self.repo)
        artifact.write_bytes(original)
        self.assertEqual("completed", self.target.validate_record(observed, self.repo)["artifact_delivery"])
        artifact.unlink()
        with self.assertRaises(self.target.SpecificationError):
            self.target.validate_record(observed, self.repo)

    def test_same_bytes_behind_replaced_symlink_are_not_current_evidence(self) -> None:
        observed = self.completed()
        artifact = self.repo / "PRD.md"
        other = self.repo / "other.md"
        other.write_bytes(artifact.read_bytes())
        artifact.unlink()
        artifact.symlink_to(other)
        with self.assertRaises(self.target.SpecificationError):
            self.target.validate_record(observed, self.repo)

    def test_observe_accepts_only_the_planned_record_and_valid_parent_digest(self) -> None:
        observed = self.completed()
        with self.assertRaises(self.target.SpecificationError):
            self.observe(observed)
        planned = self.prepare()
        planned["record_sha256"] = "0" * 64
        with self.assertRaises(self.target.SpecificationError):
            self.observe(planned)

    def test_document_renderer_has_real_links_ordered_sections_and_no_raw_body(self) -> None:
        record = self.prepare()
        marker = "PRIVATE_DOCUMENT_BODY_268_DO_NOT_PRINT"
        self.write_artifact(content=f"# PRD\n{marker}\n")
        observed = self.observe(record)
        result = self.target.render_document_result(
            observed, self.repo, project="goal-teams", current_round=1,
            estimated_total_rounds=1, loop_decision="stop",
        )
        sections = ["◆ Goal-Teams 任务执行看板", "◆ Context / Knowledge / Tools", "◆ LOOP：第 1 轮 / 预计 1 轮"]
        self.assertEqual(sorted(result.index(label) for label in sections), [result.index(label) for label in sections])
        for label in ("P ｜ 计划 / 下一轮目标", "D ｜ 执行 / 本轮执行", "C ｜ 检查 / 执行结果", "A ｜ 改进 / 调整行动"):
            self.assertIn(label, result)
        self.assertIn("| 优先级 | 任务 / 子任务 | Subagent 成员 | 进度 |", result)
        self.assertIn(str(self.repo / "PRD.md"), result)
        self.assertIn(observed["reflection"], result)
        self.assertIn("LOOP 改进建议", result)
        self.assertNotIn(marker, result)
        self.assertNotIn("TaskList.md", result)
        self.assertNotIn("memory.md", result)
        self.assertEqual([self.repo / "PRD.md"], list(self.repo.iterdir()))

    def test_document_renderer_refuses_stop_when_review_is_incomplete(self) -> None:
        record = self.prepare()
        self.write_artifact()
        observed = self.observe(record, [])
        with self.assertRaises(self.target.SpecificationError):
            self.target.render_document_result(
                observed, self.repo, project="goal-teams", current_round=1,
                estimated_total_rounds=1, loop_decision="stop",
            )


if __name__ == "__main__":
    unittest.main()
