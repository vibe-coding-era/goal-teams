"""Adversarial binding checks added without modifying the frozen first tests."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.v268 import specification_delivery as spec
from scripts.v268.output_gateway import render_response
from tests.v268.test_output_gateway import ROOT, request_for


class TestOutputBindings(unittest.TestCase):
    def test_equal_bytes_in_another_repository_cannot_reuse_a_record(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as a, tempfile.TemporaryDirectory(dir=ROOT) as b:
            record = spec.prepare_record(a, record_id="same-file", user_request="写PRD",
                                         paths=["PRD.md"], owner="author", reviewer="reviewer")
            for directory in (a, b):
                (Path(directory) / "PRD.md").write_text("# PRD\n", encoding="utf-8")
            review = {"path": "PRD.md", "sha256": hashlib.sha256((Path(a) / "PRD.md").read_bytes()).hexdigest(),
                      "reviewer": "reviewer", "verdict": "passed", "note": "已读取a中的PRD。"}
            observed = spec.observe_record(record, a, reviews=[review], reflection="按仓库身份绑定。")
            with self.assertRaises(spec.SpecificationError):
                spec.validate_record(observed, b)

    def test_blocked_output_keeps_a_link_to_an_already_delivered_document(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            artifact = Path(directory) / "PRD.md"
            record = spec.prepare_record(directory, record_id="delivery", user_request="写PRD",
                                         paths=["PRD.md"], owner="author", reviewer="reviewer")
            artifact.write_text("# PRD\n", encoding="utf-8")
            review = {"path": "PRD.md", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                      "reviewer": "reviewer", "verdict": "passed", "note": "读取复核通过。"}
            observed = spec.observe_record(record, directory, reviews=[review], reflection="保留交付。")
            request = request_for("document")
            request.update(result="", specification_record=observed, current_round=0)
            response = render_response(request, directory)
            self.assertFalse(response["ok"])
            self.assertEqual("completed", response["artifact_delivery"])
            self.assertIn(str(artifact), response["body"])


if __name__ == "__main__":
    unittest.main()
