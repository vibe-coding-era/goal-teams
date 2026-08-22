from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/checks/validate-v250-generation.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("v265_generation_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV265GenerationDependencyValidator(unittest.TestCase):
    def test_validator_recomputes_owner_dependency_projection_from_markdown(self) -> None:
        validator = _load_validator()
        check = getattr(validator, "validate_owner_dependency_projection")
        manifest = json.loads(
            (
                ROOT
                / "references/current/generations/V2.65/rule-manifest.json"
            ).read_text(encoding="utf-8")
        )
        owner = next(
            item
            for item in manifest["owners"]
            if item["owner_id"] == "FUNCTION-GRAPH-ENGINEERING-V265"
        )
        source = (ROOT / owner["path"]).read_text(encoding="utf-8")

        self.assertEqual([], check(source, owner))

        tampered = copy.deepcopy(owner)
        tampered["dependencies"] = []
        self.assertEqual(
            ["E_V250_OWNER_DEPENDENCY_PROJECTION"],
            check(source, tampered),
        )


if __name__ == "__main__":
    unittest.main()
