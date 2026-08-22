from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.v265 import test_graph_contract as fx


CONTRACT_SHA256 = "74ad11eccbac93d72d25d7395410a2634077f388249f83cbc49387aea4f4534e"
PLAN_REVISION = 3
TASK_EXACT_SET_SHA256 = "33a037088df9258e0d47435116514c6218e644fc70d1379b84fa6292ec73b635"
ORIGINAL_GRAPH_TEST_SHA256 = "b590c667335cb7cf2e5e69c27862bb415711ec431d5386576c6a061ccbb06175"
AJV_VERSION = "8.18.0"
AJV_2020_ENTRY_SHA256 = "908e9670b478b2ba126802a221b7e47006f50cf467e2c5dd7935d3dbef10a20a"


def _gate(kind: str, evidence_types: list[str]) -> dict[str, object]:
    return {
        "gate_id": "gate:join-evidence",
        "gate_type": kind,
        "authority_ref": "external-human-authority" if kind == "human_approval" else None,
        "required_evidence_types": evidence_types,
        "condition": (
            {
                "fact_ref": "fact:join-ready",
                "operator": "equals",
                "expected_value": True,
            }
            if kind == "condition"
            else None
        ),
        "timeout_seconds": 60,
        "on_timeout_outcome": "blocked",
    }


CASES = (
    ("evidence_empty", _gate("evidence", []), False),
    ("human_exact", _gate("human_approval", ["approval_receipt"]), True),
    ("human_wrong", _gate("human_approval", ["other_receipt"]), False),
    ("condition_empty", _gate("condition", []), True),
    ("condition_legacy_nonempty", _gate("condition", ["typed_fact_receipt"]), True),
    ("condition_duplicate", _gate("condition", ["typed_fact_receipt", "typed_fact_receipt"]), False),
)


class TestV265ConditionGateCompiler(unittest.TestCase):
    def setUp(self) -> None:
        self.source, self.compiled_plan, self.plan_validation = fx._authoritative_plan()
        self.document = fx._graph_document(
            self.source, self.compiled_plan, self.plan_validation
        )
        self.graph = fx._target("scripts.v265.graph_contract")

    def test_compiler_gate_type_cardinality_matrix(self) -> None:
        self.assertRegex(CONTRACT_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(3, PLAN_REVISION)
        self.assertRegex(TASK_EXACT_SET_SHA256, r"^[0-9a-f]{64}$")
        observed_original = hashlib.sha256(
            (Path(__file__).parent / "test_graph_contract.py").read_bytes()
        ).hexdigest()
        self.assertEqual(ORIGINAL_GRAPH_TEST_SHA256, observed_original)

        for name, gate, should_pass in CASES:
            document = copy.deepcopy(self.document)
            document["gates"][0] = copy.deepcopy(gate)
            with self.subTest(case=name):
                if should_pass:
                    try:
                        compiled = self.graph.compile_graph_contract(
                            document,
                            compiled_task_plan=self.compiled_plan,
                            task_plan_validation_receipt=self.plan_validation,
                        )
                    except self.graph.GraphContractError as exc:
                        self.fail(f"E_TEST_V265_CONDITION_GATE_REJECTED:{name}:{exc.code}")
                    self.assertEqual(gate["required_evidence_types"], compiled["gates"][0]["required_evidence_types"])
                else:
                    with self.assertRaises(self.graph.GraphContractError) as caught:
                        self.graph.compile_graph_contract(
                            document,
                            compiled_task_plan=self.compiled_plan,
                            task_plan_validation_receipt=self.plan_validation,
                        )
                    self.assertEqual("E_V265_GRAPH_GATE_BINDING", caught.exception.code)

    def test_real_draft2020_gate_schema_cardinality_matrix(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("E_TEST_V265_AJV2020_UNAVAILABLE:node")
        metadata_script = """
const fs=require('fs');
try {
  const entry=require.resolve('ajv/dist/2020');
  const version=require('ajv/package.json').version;
  const crypto=require('crypto');
  const digest=crypto.createHash('sha256').update(fs.readFileSync(entry)).digest('hex');
  process.stdout.write(JSON.stringify({version,digest}));
} catch (error) { process.stderr.write(String(error)); process.exit(91); }
"""
        metadata = subprocess.run(
            [node, "-e", metadata_script],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
            check=False,
        )
        if metadata.returncode != 0:
            self.fail(f"E_TEST_V265_AJV2020_UNAVAILABLE:{metadata.stderr}")
        identity = json.loads(metadata.stdout)
        self.assertEqual(AJV_VERSION, identity["version"])
        self.assertEqual(AJV_2020_ENTRY_SHA256, identity["digest"])

        schema = json.loads(
            Path("schemas/v2.65/graph-contract.schema.json").read_text(encoding="utf-8")
        )
        validator_script = """
const fs=require('fs');
let Ajv2020;
try { Ajv2020=require('ajv/dist/2020').default; }
catch (error) { process.stderr.write(String(error)); process.exit(91); }
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const wrapper={$schema:input.schema.$schema,$defs:input.schema.$defs,$ref:'#/$defs/gate'};
let validate;
try { validate=new Ajv2020({strict:true,allErrors:true,validateFormats:false}).compile(wrapper); }
catch (error) { process.stderr.write(String(error)); process.exit(92); }
process.stdout.write(JSON.stringify(input.instances.map((item)=>Boolean(validate(item)))));
"""
        run = subprocess.run(
            [node, "-e", validator_script],
            cwd=Path(__file__).resolve().parents[2],
            input=json.dumps(
                {
                    "schema": schema,
                    "instances": [gate for _name, gate, _expected in CASES],
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if run.returncode == 91:
            self.fail(f"E_TEST_V265_AJV2020_UNAVAILABLE:{run.stderr}")
        if run.returncode == 92:
            self.fail(f"E_TEST_V265_GRAPH_SCHEMA_INVALID:{run.stderr}")
        if run.returncode != 0:
            self.fail(f"E_TEST_V265_GRAPH_SCHEMA_RUNNER:{run.returncode}:{run.stderr}")
        self.assertEqual(
            [expected for _name, _gate_value, expected in CASES],
            json.loads(run.stdout),
        )


if __name__ == "__main__":
    unittest.main()
