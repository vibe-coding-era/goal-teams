from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV263ValidatorCallers(unittest.TestCase):
    def test_current_callers_select_active_generation_explicitly(self) -> None:
        shell = (ROOT / "scripts/checks/check.sh").read_text(encoding="utf-8")
        self.assertIn(
            "validate-v250-generation.py --generation-id V2.65 --selection active",
            shell,
        )

        validator = (ROOT / "scripts/checks/validate.py").read_text(encoding="utf-8")
        marker = '"scripts/checks/validate-v250-generation.py",'
        start = validator.index(marker)
        call = validator[start : start + 220]
        self.assertIn('"--selection",', call)
        self.assertIn('"active",', call)


if __name__ == "__main__":
    unittest.main()
