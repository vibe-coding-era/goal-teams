from __future__ import annotations

import unittest

from scripts.v250.output_contract import serialize_output, validate_output


class TestV263OutputContract(unittest.TestCase):
    def _payload(self) -> dict[str, str]:
        return {
            "任务": "实施 V2.63",
            "成员": "Goal Lead",
            "进度": "第 1 轮/共 2 轮",
            "结果": "候选实现，host runtime 未验证。LOOP 改进建议：保持证明强度。",
            "Banchmark": "1/1",
            "下一个任务": "继续验证",
        }

    def test_serializer_emits_exact_ordered_six_field_envelope(self) -> None:
        payload = self._payload()
        result = validate_output(payload, loop_decision="stop")
        self.assertTrue(result["ok"])
        rendered = serialize_output(payload, loop_decision="stop")
        labels = [line.split("：", 1)[0] for line in rendered.splitlines() if line]
        self.assertEqual(
            ["任务", "成员", "进度", "结果", "Banchmark", "下一个任务"],
            labels,
        )
        self.assertNotIn("root=", rendered)
        self.assertNotIn("source=", rendered)
        self.assertNotIn("active=", rendered)

    def test_serializer_rejects_terminal_drift_and_keeps_host_state_unverified(self) -> None:
        payload = self._payload()
        payload["下一轮 LOOP"] = "wrong terminal"
        with self.assertRaises(ValueError):
            serialize_output(payload, loop_decision="stop")
        payload.pop("下一轮 LOOP")
        result = validate_output(payload, loop_decision="stop")
        self.assertFalse(result["host_runtime_verified"])
        self.assertEqual("unavailable", result["provider_prompt_assembly"])


if __name__ == "__main__":
    unittest.main()
