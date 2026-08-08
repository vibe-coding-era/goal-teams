from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "b" * 64
PROFILE_SHA256 = "c" * 64


def _target(testcase: unittest.TestCase):
    try:
        return importlib.import_module("scripts.v250.okf_document_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v250.okf_document_graph":
            testcase.fail("E_KG262_TARGET_MISSING: scripts.v250.okf_document_graph")
        raise


def _quality_graph(kg):
    return kg.load_current_graph(
        FIXTURES / "quality",
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


class TestV262KnowledgeGraphObservations(unittest.TestCase):
    def test_quality_findings_are_complete_observations_not_business_gates(self) -> None:
        kg = _target(self)
        graph = _quality_graph(kg)

        self.assertEqual("partial", graph.coverage_state)
        self.assertIsInstance(graph.observations, tuple)
        rules = {item["rule_id"] for item in graph.observations}
        self.assertTrue(
            {
                "duplicate_map_member",
                "member_identity_mismatch",
                "invalid_timestamp",
                "dangling_or_mismatched_target",
                "conflict_candidate",
            }.issubset(rules),
            rules,
        )
        for observation in graph.observations:
            self.assertEqual("record", observation["current_action"])
            self.assertEqual("undecided", observation["future_action"])
            self.assertIn("finding_id", observation)
            self.assertIn("observation_state", observation)
            self.assertNotIn("gate_status", observation)
            self.assertNotIn("enforce", json.dumps(observation).lower())

    def test_dangling_row_is_not_fabricated_as_a_direct_or_reified_statement(self) -> None:
        kg = _target(self)
        graph = _quality_graph(kg)
        rendered_triples = json.dumps(
            [
                {
                    "subject": item.subject,
                    "predicate": item.predicate,
                    "object": item.object,
                }
                for item in graph.triples
            ]
        )
        rendered_statements = json.dumps(graph.statements)
        self.assertNotIn("AC-MISSING", rendered_triples)
        self.assertNotIn("REL-BROKEN-001", rendered_statements)

        unresolved = [
            item
            for item in graph.observations
            if item["rule_id"] == "dangling_or_mismatched_target"
        ]
        self.assertTrue(unresolved)
        self.assertIn("AC-MISSING", json.dumps(unresolved))

    def test_observe_returns_findings_even_though_shacl_engine_is_not_claimed(self) -> None:
        kg = _target(self)
        graph = _quality_graph(kg)
        receipt = graph.observe()
        self.assertEqual("completed", receipt["run_status"])
        self.assertEqual("record", receipt["current_action"])
        self.assertEqual("not_run", receipt["persistence"])
        self.assertEqual(
            "not_implemented", graph.capabilities["shacl_engine_state"]
        )
        self.assertNotIn("shacl_conforms", receipt)
        for result in receipt["results"]:
            if result.get("validation_state") == "nonconforms":
                self.assertEqual("record", result["current_action"])
                self.assertNotEqual("failed", result.get("run_status"))


if __name__ == "__main__":
    unittest.main()
