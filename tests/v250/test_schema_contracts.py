from __future__ import annotations

import json
import pathlib
import unittest


REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO / "schemas/v2.50"
RELEASE_SCHEMA_ROOT = REPO / "schemas/v2.66"


def walk_schema(value: object, path: str = "$"):
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from walk_schema(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_schema(item, f"{path}/{index}")


class TestV250SchemaContracts(unittest.TestCase):
    def test_predecessor_release_identity_contract_is_strict_and_valid(self) -> None:
        schema = json.loads(
            (SCHEMA_ROOT / "predecessor-release-identity.schema.json").read_text(
                encoding="utf-8"
            )
        )
        contract = json.loads(
            (
                REPO
                / "references/current/generations/V2.66/contracts/"
                "predecessor-release-identity.json"
            ).read_text(encoding="utf-8")
        )
        try:
            from jsonschema import Draft202012Validator
        except ModuleNotFoundError:
            Draft202012Validator = None
        if Draft202012Validator is not None:
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(contract)
        self.assertEqual("V2.66", contract["generation_id"])
        self.assertEqual("V2.65", contract["predecessor_product_version"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))

    def test_activation_and_runtime_identity_versions_are_unambiguous(self) -> None:
        activation = json.loads(
            (SCHEMA_ROOT / "activation-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        identity = activation["properties"]["identity"]
        self.assertEqual(
            {
                "loaded_runtime_product_version",
                "route_contract_schema_version",
                "target_policy_generation",
            },
            set(identity["required"]),
        )
        self.assertEqual(
            {"enum": ["V2.62", "V2.63", "V2.65", "V2.66"]},
            identity["properties"]["loaded_runtime_product_version"],
        )
        self.assertNotIn("controller_product_version", identity["properties"])

        runtime = json.loads(
            (RELEASE_SCHEMA_ROOT / "runtime-transition-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("loaded_runtime_product_version", runtime["required"])
        for forbidden in (
            "controller_version",
            "previous_controller_product_version",
            "previous_run_id",
            "new_run_id",
        ):
            self.assertNotIn(forbidden, runtime["required"])
            self.assertNotIn(forbidden, runtime["properties"])
        self.assertEqual(
            {"const": "V2.66"},
            runtime["properties"]["loaded_runtime_product_version"],
        )
        handoff = runtime["$defs"]["controllerHandoffReceipt"]
        signed_payload = handoff["properties"]["signed_payload"]
        self.assertEqual(
            {"const": "V2.65"},
            signed_payload["properties"]["previous_controller_product_version"],
        )
        self.assertIn("previous_run_id", signed_payload["required"])
        self.assertIn("installed_v265_current_state", signed_payload["required"])
        self.assertNotIn("installed_v26_current_state", signed_payload["properties"])
        self.assertNotIn("installed_v250_current_state", signed_payload["properties"])
        self.assertNotIn("controller_version", signed_payload["properties"])

    def test_required_fields_are_locally_declared_for_strict_draft202012_compilers(self) -> None:
        schema_files = sorted(SCHEMA_ROOT.glob("*.schema.json"))
        self.assertGreaterEqual(len(schema_files), 19)

        for schema_file in schema_files:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            self.assertEqual(
                "https://json-schema.org/draft/2020-12/schema", schema.get("$schema")
            )
            for node_path, node in walk_schema(schema):
                required = node.get("required")
                if required is None:
                    continue
                # A property map may itself contain a data field named
                # ``required``; it is not the JSON Schema keyword of the
                # surrounding object.
                if not isinstance(required, list) and node_path.endswith("/properties"):
                    continue
                self.assertIsInstance(required, list, f"{schema_file}:{node_path}")
                properties = node.get("properties")
                self.assertIsInstance(properties, dict, f"{schema_file}:{node_path}")
                self.assertTrue(
                    set(required).issubset(properties),
                    f"{schema_file}:{node_path} has undeclared required fields",
                )

    def test_release_engine_profile_is_strict_compiler_and_instance_aligned(self) -> None:
        schema_path = REPO / "schemas/release-engine-profile.schema.json"
        profile_path = REPO / "references/release-profiles/v2.66.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        profile = json.loads(profile_path.read_text(encoding="utf-8"))

        for node_path, node in walk_schema(schema):
            required = node.get("required")
            if required is None:
                continue
            properties = node.get("properties")
            self.assertIsInstance(properties, dict, f"{schema_path}:{node_path}")
            self.assertTrue(
                set(required).issubset(properties),
                f"{schema_path}:{node_path} has undeclared required fields",
            )

        v250_then = schema["allOf"][2]["then"]
        expected_gates = v250_then["properties"]["release_gates"]["const"]
        self.assertEqual(expected_gates, profile["release_gates"])
        self.assertLess(
            expected_gates.index("repository_boundary_compliance"),
            expected_gates.index("large_release_install"),
        )
        for field in ("s2_policy", "s3_policy"):
            self.assertEqual(
                schema["properties"][field]["const"], profile[field]
            )
            self.assertEqual(
                v250_then["properties"][field]["const"], profile[field]
            )

    def test_release_control_uses_the_full_runtime_transition_schema(self) -> None:
        control = json.loads(
            (RELEASE_SCHEMA_ROOT / "release-control.schema.json").read_text(encoding="utf-8")
        )
        runtime = json.loads(
            (RELEASE_SCHEMA_ROOT / "runtime-transition-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            runtime["$id"],
            control["properties"]["released_runtime_transition"]["$ref"],
        )
        authorization = control["properties"]["authorization_receipt"]
        self.assertTrue(set(authorization["required"]).issubset(authorization["properties"]))
        self.assertFalse(authorization["additionalProperties"])
        self.assertFalse(
            authorization["properties"]["repository"]["additionalProperties"]
        )
        self.assertFalse(
            authorization["properties"]["intent"]["additionalProperties"]
        )

    def test_s4_outcome_has_three_strict_terminal_branches_and_exact_assets(self) -> None:
        control = json.loads(
            (RELEASE_SCHEMA_ROOT / "release-control.schema.json").read_text(encoding="utf-8")
        )
        outcome = control["$defs"]["s4_outcome_receipt"]
        self.assertEqual(3, len(outcome["oneOf"]))
        self.assertEqual(
            [None, "blocked_before_write", ["failed_after_write", "partial_or_uncertain"]],
            [
                branch["properties"]["failure_class"].get(
                    "const", branch["properties"]["failure_class"].get("enum")
                )
                for branch in outcome["oneOf"]
            ],
        )
        assets = outcome["properties"]["asset_readback"]
        self.assertEqual(4, assets["minItems"])
        self.assertEqual(4, assets["maxItems"])
        self.assertIs(False, assets["items"])
        self.assertEqual(
            ["SHA256SUMS", "_files.sha256", "_release.json", "goal-teams-V2.66.tar.gz"],
            [item["properties"]["name"]["const"] for item in assets["prefixItems"]],
        )
        journal = outcome["properties"]["operation_journal"]
        self.assertEqual(
            ["not_started", "attempted", "confirmed", "uncertain"],
            control["$defs"]["operation_journal_entry"]["properties"]["state"]["enum"],
        )
        self.assertEqual(9, journal["minItems"])
        self.assertEqual(9, journal["maxItems"])
        schema_validation = outcome["properties"]["schema_validation"]
        self.assertIn(
            "runtime_transition_schema_sha256",
            schema_validation["required"],
        )
        self.assertIn(
            "state_package_files_sha256",
            outcome["properties"]["install_readback"]["anyOf"][1][
                "required"
            ],
        )

    def test_user_output_terminal_branches_declare_and_exclude_opposites(self) -> None:
        schema = json.loads(
            (SCHEMA_ROOT / "user-output.schema.json").read_text(encoding="utf-8")
        )
        continue_branch, stop_branch = schema["oneOf"]

        self.assertEqual(["下一轮 LOOP"], continue_branch["required"])
        self.assertIs(False, continue_branch["properties"]["下一个任务"])
        self.assertEqual(["下一个任务"], stop_branch["required"])
        self.assertIs(False, stop_branch["properties"]["下一轮 LOOP"])


if __name__ == "__main__":
    unittest.main()
