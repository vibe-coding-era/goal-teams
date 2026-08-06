from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.v250.output_contract import validate_output


ROOT = Path(__file__).resolve().parents[2]


class TestV251SmallIteration(unittest.TestCase):
    def _output(self, *, stop: bool = False) -> dict[str, str]:
        value = {
            "任务": "V2.51 小迭代",
            "成员": "Goal Lead",
            "进度": "实现与验证（第 2 轮/共 4 轮）",
            "结果": "当前切片完成",
            "Banchmark": "4/4 assertions passed",
        }
        if stop:
            value["结果"] += (
                "；LOOP 改进建议：Skill、上下文、资料三个方面均已复盘，暂无新增建议"
            )
            value["下一个任务"] = "等待新任务"
        else:
            value["下一轮 LOOP"] = "继续"
        return value

    def test_product_identity_and_current_generation_are_v251(self) -> None:
        self.assertEqual("V2.51", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        active = json.loads(
            (ROOT / "references/current/ACTIVE.json").read_text(encoding="utf-8")
        )
        self.assertEqual("V2.51", active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.51/activation-manifest.json",
            active["activation_manifest"],
        )

    def test_limited_source_available_license_requires_author_permission(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Limited Source-Available License", license_text)
        self.assertIn("prior written permission", license_text)
        self.assertIn("肉山@TGO 杭州", license_text)
        self.assertIn("not an Open Source license", license_text)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")
        self.assertIn("[LICENSE](LICENSE)", readme)
        self.assertIn("[LICENSE](LICENSE)", readme_en)

    def test_every_loop_requires_current_and_total_iteration(self) -> None:
        valid = validate_output(self._output(), loop_decision="continue")
        self.assertTrue(valid["ok"], valid)

        missing_iteration = self._output()
        missing_iteration["进度"] = "实现与验证"
        verdict = validate_output(missing_iteration, loop_decision="continue")
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V251_OUTPUT_LOOP_PROGRESS", verdict["errors"])

    def test_final_output_requires_loop_improvement_suggestions(self) -> None:
        valid = validate_output(self._output(stop=True), loop_decision="stop")
        self.assertTrue(valid["ok"], valid)

        missing_suggestions = self._output(stop=True)
        missing_suggestions["结果"] = "全部完成"
        verdict = validate_output(missing_suggestions, loop_decision="stop")
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V251_OUTPUT_LOOP_IMPROVEMENTS", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
