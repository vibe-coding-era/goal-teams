from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


class TestV265SchemaStrictness(unittest.TestCase):
    def test_array_keywords_have_an_explicit_array_type(self) -> None:
        violations: list[str] = []

        def inspect(value: Any, location: str) -> None:
            if isinstance(value, dict):
                if (
                    {"minItems", "maxItems", "uniqueItems"}.intersection(value)
                    and value.get("type") != "array"
                    and "$ref" not in value
                ):
                    violations.append(location)
                for key, child in value.items():
                    inspect(child, f"{location}/{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    inspect(child, f"{location}/{index}")

        for schema_path in sorted((ROOT / "schemas" / "v2.65").glob("*.json")):
            inspect(
                json.loads(schema_path.read_text(encoding="utf-8")),
                schema_path.relative_to(ROOT).as_posix(),
            )

        self.assertEqual([], violations)
