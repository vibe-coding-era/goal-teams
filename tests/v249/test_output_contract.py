from __future__ import annotations

import unittest

from scripts.v249.output_contract import validate_output


class TestV249OutputContract(unittest.TestCase):
    def test_continue_requires_exact_six_fields(self) -> None:
        value = {
            "任务": "任务",
            "成员": "成员",
            "进度": "进度",
            "结果": "结果",
            "Banchmark": "指标",
            "下一轮 LOOP": "继续",
        }
        verdict = validate_output(value, loop_decision="continue")
        self.assertTrue(verdict["ok"])
        self.assertEqual(
            "contract_mapped_static_tests_passed", verdict["assurance_state"]
        )
        self.assertFalse(verdict["host_runtime_verified"])
        self.assertEqual("unavailable", verdict["provider_prompt_assembly"])
        self.assertIsNone(verdict["runtime_receipt_sha256"])
        self.assertFalse(verdict["visible_reasoning_field_present"])

    def test_stop_requires_next_task_only(self) -> None:
        value = {
            "任务": "任务",
            "成员": "成员",
            "进度": "进度",
            "结果": "结果",
            "Banchmark": "指标",
            "下一个任务": "停止",
        }
        self.assertTrue(validate_output(value, loop_decision="stop")["ok"])

    def test_reasoning_or_both_terminal_fields_are_rejected(self) -> None:
        value = {
            "任务": "任务",
            "成员": "成员",
            "进度": "进度",
            "结果": "结果",
            "Banchmark": "指标",
            "下一轮 LOOP": "继续",
            "下一个任务": "停止",
            "推理过程": "不得输出",
        }
        verdict = validate_output(value, loop_decision="continue")
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_OUTPUT_ENVELOPE", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
