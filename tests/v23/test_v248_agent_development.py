"""Regression coverage for the V2.48 Agent-development contract."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("v248_agent_development", ROOT / "scripts/checks/validate-v248-agent-development.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class V248AgentDevelopmentTests(unittest.TestCase):
    def test_current_contract_passes(self) -> None:
        result = MODULE.validate()
        self.assertEqual(result["role_count"], 11)
        self.assertEqual(result["pattern_count"], 3)

    def test_rejects_tool_order_drift(self) -> None:
        source = json.loads((ROOT / "references/agent-development-capability-manifest.json").read_text(encoding="utf-8"))
        source["tool_execution_order"] = list(reversed(source["tool_execution_order"]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.validate(path)

    def test_rejects_schema_denominator_drift(self) -> None:
        schema_path = ROOT / "schemas/v2.48/agent-development-capability.schema.json"
        source = schema_path.read_text(encoding="utf-8")
        changed = source.replace('"validator", "reference_index"', '"reference_index"', 1)
        self.assertNotEqual(source, changed)
        with tempfile.TemporaryDirectory() as directory:
            drifted_schema = Path(directory) / "schema.json"
            drifted_schema.write_text(changed, encoding="utf-8")
            with mock.patch.object(MODULE, "SCHEMA", drifted_schema):
                with self.assertRaises(SystemExit):
                    MODULE.validate()
