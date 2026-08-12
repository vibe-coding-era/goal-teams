from __future__ import annotations

import copy
import unittest

from scripts.v250.semantic_closure import (
    SemanticClosureError,
    compile_owner_closure,
    validate_route_controls,
)


class TestV263SemanticClosure(unittest.TestCase):
    def owners(self) -> list[dict[str, object]]:
        return [
            {
                "owner_id": "CORE",
                "path": "owners/core.md",
                "dependencies": [
                    {"kind": "required", "owner_id": "STATE"},
                    {
                        "kind": "phase_gated",
                        "owner_id": "RELEASE",
                        "phases": ["release"],
                    },
                    {
                        "kind": "fact_gated",
                        "owner_id": "RUNTIME",
                        "fact": "agent_runtime",
                        "equals": True,
                    },
                    {"kind": "optional", "owner_id": "UI"},
                ],
                "route_membership": ["ROUTE-DEV"],
            },
            {
                "owner_id": "STATE",
                "path": "owners/state.md",
                "dependencies": [],
                "route_membership": ["ROUTE-DEV"],
            },
            {
                "owner_id": "RUNTIME",
                "path": "owners/runtime.md",
                "dependencies": [],
                "route_membership": [],
            },
            {
                "owner_id": "RELEASE",
                "path": "owners/release.md",
                "dependencies": [],
                "route_membership": [],
            },
            {
                "owner_id": "UI",
                "path": "owners/ui.md",
                "dependencies": [],
                "route_membership": [],
            },
        ]

    def test_required_closure_and_bidirectional_membership_are_exact(self) -> None:
        value = compile_owner_closure(
            owners=self.owners(),
            route_id="ROUTE-DEV",
            phase="development",
            facts={"agent_runtime": False},
            ordered_refs=["owners/core.md", "owners/state.md"],
        )
        self.assertEqual(["CORE", "STATE"], value["ordered_owner_ids"])
        self.assertEqual("full", value["membership_check"])

        missing = self.owners()
        missing[1]["route_membership"] = []
        with self.assertRaises(SemanticClosureError) as required:
            compile_owner_closure(
                owners=missing,
                route_id="ROUTE-DEV",
                phase="development",
                facts={"agent_runtime": False},
                ordered_refs=["owners/core.md"],
            )
        self.assertEqual("E_V263_REQUIRED_DEPENDENCY", required.exception.code)

        extra_membership = self.owners()
        extra_membership[4]["route_membership"] = ["ROUTE-DEV"]
        with self.assertRaises(SemanticClosureError) as bidirectional:
            compile_owner_closure(
                owners=extra_membership,
                route_id="ROUTE-DEV",
                phase="development",
                facts={"agent_runtime": False},
                ordered_refs=["owners/core.md", "owners/state.md"],
            )
        self.assertEqual("E_V263_ROUTE_MEMBERSHIP", bidirectional.exception.code)

    def test_phase_and_fact_gated_dependencies_cannot_be_silently_omitted(self) -> None:
        owners = self.owners()
        owners[2]["route_membership"] = ["ROUTE-DEV"]
        with self.assertRaises(SemanticClosureError) as fact_gate:
            compile_owner_closure(
                owners=owners,
                route_id="ROUTE-DEV",
                phase="development",
                facts={"agent_runtime": True},
                ordered_refs=["owners/core.md", "owners/state.md"],
            )
        self.assertEqual("E_V263_FACT_DEPENDENCY", fact_gate.exception.code)

        release = copy.deepcopy(self.owners())
        release[0]["route_membership"] = ["ROUTE-RELEASE"]
        release[1]["route_membership"] = ["ROUTE-RELEASE"]
        release[3]["route_membership"] = ["ROUTE-RELEASE"]
        with self.assertRaises(SemanticClosureError) as phase_gate:
            compile_owner_closure(
                owners=release,
                route_id="ROUTE-RELEASE",
                phase="release",
                facts={"agent_runtime": False},
                ordered_refs=["owners/core.md", "owners/state.md"],
            )
        self.assertEqual("E_V263_PHASE_DEPENDENCY", phase_gate.exception.code)

    def test_unknown_dependency_kind_duplicate_ref_and_unknown_controls_fail(self) -> None:
        unknown = self.owners()
        unknown[0]["dependencies"][0]["kind"] = "sometimes"
        with self.assertRaises(SemanticClosureError) as kind:
            compile_owner_closure(
                owners=unknown,
                route_id="ROUTE-DEV",
                phase="development",
                facts={"agent_runtime": False},
                ordered_refs=["owners/core.md", "owners/state.md"],
            )
        self.assertEqual("E_V263_DEPENDENCY_KIND", kind.exception.code)

        with self.assertRaises(SemanticClosureError) as duplicate:
            compile_owner_closure(
                owners=self.owners(),
                route_id="ROUTE-DEV",
                phase="development",
                facts={"agent_runtime": False},
                ordered_refs=["owners/core.md", "owners/core.md"],
            )
        self.assertEqual("E_V263_ORDERED_REF_DUPLICATE", duplicate.exception.code)

        normalized = validate_route_controls(
            {
                "workflow_phase": "release",
                "required_gates": ["final_full_regression", "s2"],
                "conditional_gates": ["publish_readback"],
            }
        )
        self.assertEqual(["full_regression", "s2"], normalized["required_gates"])
        with self.assertRaises(SemanticClosureError):
            validate_route_controls(
                {
                    "workflow_phase": "ship_it",
                    "required_gates": ["unknown_gate"],
                    "conditional_gates": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
