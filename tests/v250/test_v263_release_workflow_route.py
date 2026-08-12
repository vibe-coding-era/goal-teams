from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/release-gate.yml"


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def release_route_step(workflow: str) -> str:
    start = workflow.index("      - name: Materialize the exact trusted Release route receipt")
    end = workflow.index("      - name:", start + 8)
    return workflow[start:end]


def project_route_fact_fields(step: str) -> set[str]:
    start = step.index("          project_route_facts = {")
    end = step.index("          }\n", start)
    return set(re.findall(r'^              "([^"]+)":', step[start:end], re.MULTILINE))


class TestV263ReleaseWorkflowRoute(unittest.TestCase):
    def test_release_route_is_derived_from_project_route_facts(self) -> None:
        step = release_route_step(workflow_text())

        self.assertIn(
            "from scripts.v250.route_derivation import derive_route",
            step,
        )
        self.assertIn(
            "from scripts.v250.route_closure import compile_derived_route_closure",
            step,
        )
        self.assertIn("facts_source = {", step)
        self.assertIn("project_route_facts = {", step)
        exact_fields = {
            "project_size",
            "workflow_phase",
            "stage",
            "release_intent",
            "implementation_scope_complete",
            "risk",
            "failure_consequence",
            "reversibility",
            "compliance",
            "external_write",
            "security_sensitive",
            "ui_or_desktop",
            "agent_runtime",
            "environment_check_required",
            "authorization_state",
            "facts_source_sha256",
        }
        self.assertEqual(exact_fields, project_route_fact_fields(step))
        self.assertIn('"stage": "released"', step)
        self.assertIn("derived_route = derive_route(project_route_facts)", step)
        self.assertIn(
            "receipt = compile_derived_route_closure(root, generation, derived_route)",
            step,
        )
        self.assertNotIn("compile_route_closure", step)
        self.assertNotIn("V250-ROUTE-MEDIUM-RELEASE", step)
        self.assertNotIn("V250-ROUTE-LARGE-RELEASE", step)

    def test_route_facts_and_derived_receipt_are_persisted(self) -> None:
        workflow = workflow_text()
        step = release_route_step(workflow)

        self.assertIn('"release-route-facts.json"', step)
        self.assertIn('"release-route-derived.json"', step)
        for receipt in (
            "release-route-facts.json",
            "release-route-derived.json",
            "release-route-receipt.json",
        ):
            self.assertIn(receipt, workflow)

    def test_installed_controller_handoff_identity_is_v262(self) -> None:
        workflow = workflow_text()
        self.assertIn(
            "Materialize the installed V2.62 host-issued V2.63 controller handoff",
            workflow,
        )
        self.assertNotIn(
            "Materialize the installed V2.6 host-issued V2.63 controller handoff",
            workflow,
        )

    def test_each_workflow_step_has_unique_mapping_keys(self) -> None:
        workflow = workflow_text()
        chunks = re.split(r"(?m)^      - (?=(?:name|uses):)", workflow)
        checked = 0
        for chunk in chunks[1:]:
            keys = re.findall(
                r"(?m)^        (id|if|env|run|uses|with|name|timeout-minutes|continue-on-error):",
                chunk,
            )
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            self.assertEqual([], duplicates, chunk[:160])
            checked += 1
        self.assertGreaterEqual(checked, 20)


if __name__ == "__main__":
    unittest.main()
