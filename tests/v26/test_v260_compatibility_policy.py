from __future__ import annotations

import copy
import json
import pathlib
import tempfile
import unittest

from scripts.v26.compatibility import CompatibilityError, load_compatibility_metadata, resolve_route, validate_runtime_binding_receipt
from scripts.v26.role_projections import check_role_projections, project_role_projections


FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def fixture_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class TestV260CompatibilityMetadata(unittest.TestCase):
    def test_nodes_have_stable_identity_ordered_dependencies_and_explicit_states(self) -> None:
        metadata = load_compatibility_metadata(FIXTURES / "compatibility-metadata.json")
        self.assertEqual("goal-teams-compatibility-v2.6-v1", metadata["schema_version"])
        self.assertEqual(["portable-core", "host.codex", "host.claude-code", "provider.deepseek", "model.deepseek-flash", "model.deepseek-pro", "model.kimi-k3"], [node["id"] for node in metadata["nodes"]])
        for node in metadata["nodes"]:
            self.assertIsInstance(node["kind"], str)
            self.assertIsInstance(node["state"], str)
            self.assertEqual(len(node["capabilities"]), len(set(node["capabilities"])))
            self.assertEqual(len(node["depends_on"]), len(set(node["depends_on"])))

    def test_mixed_node_type_duplicate_identity_and_unsafe_path_fail_closed(self) -> None:
        baseline = fixture_json("compatibility-metadata.json")
        mutations = {"mixed-kind": lambda value: value["nodes"].__setitem__(1, {**value["nodes"][1], "kind": ["host"]}), "duplicate-id": lambda value: value["nodes"].__setitem__(1, {**value["nodes"][1], "id": "portable-core"}), "parent-path": lambda value: value["nodes"].__setitem__(1, {**value["nodes"][1], "path": "../escape.md"}), "absolute-path": lambda value: value["nodes"].__setitem__(1, {**value["nodes"][1], "path": "/escape.md"})}
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "compatibility.json"
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    value = copy.deepcopy(baseline); mutate(value); write_json(path, value)
                    with self.assertRaises(CompatibilityError) as raised: load_compatibility_metadata(path)
                    self.assertTrue(str(raised.exception).startswith("E_V26_"))


class TestV260Resolver(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = load_compatibility_metadata(FIXTURES / "compatibility-metadata.json")

    def test_codex_flash_is_direct_responses_and_deterministic(self) -> None:
        first = resolve_route(self.metadata, "host.codex", "provider.deepseek/flash")
        self.assertEqual(first, resolve_route(self.metadata, "host.codex", "provider.deepseek/flash"))
        self.assertEqual("direct_responses", first["connection_class"]); self.assertEqual("contract_mapped_not_runtime_verified", first["verification_state"])
        self.assertEqual("provider.deepseek/flash", first["requested_model"]); self.assertEqual("provider.deepseek/flash", first["resolved_model"])
        self.assertEqual(["portable-core", "host.codex", "provider.deepseek", "model.deepseek-flash"], first["route_refs"]); self.assertRegex(first["route_digest"], r"^[0-9a-f]{64}$")

    def test_codex_pro_is_unsupported_direct_and_blocked_without_fallback(self) -> None:
        route = resolve_route(self.metadata, "host.codex", "provider.deepseek/pro")
        self.assertEqual("unsupported_direct", route["connection_class"]); self.assertEqual("blocked", route["verification_state"])
        self.assertEqual("provider.deepseek/pro", route["requested_model"]); self.assertEqual("provider.deepseek/pro", route["resolved_model"])

    def test_claude_direct_anthropic_matrix_and_codex_k3_bridge_requirement(self) -> None:
        for requested_model, expected_refs in (("provider.deepseek/flash", ["portable-core", "host.claude-code", "provider.deepseek", "model.deepseek-flash"]), ("provider.deepseek/pro", ["portable-core", "host.claude-code", "provider.deepseek", "model.deepseek-pro"]), ("model.kimi-k3", ["portable-core", "host.claude-code", "model.kimi-k3"])):
            with self.subTest(requested_model=requested_model):
                route = resolve_route(self.metadata, "host.claude-code", requested_model)
                self.assertEqual("direct_anthropic", route["connection_class"]); self.assertEqual("contract_mapped_not_runtime_verified", route["verification_state"]); self.assertEqual(requested_model, route["resolved_model"]); self.assertEqual(expected_refs, route["route_refs"])
        bridge_required = resolve_route(self.metadata, "host.codex", "model.kimi-k3")
        self.assertEqual("bridge_required", bridge_required["connection_class"]); self.assertEqual("blocked", bridge_required["verification_state"]); self.assertNotIn("approved_bridge", bridge_required)


class TestV260RoleProjections(unittest.TestCase):
    def _projection_root(self, directory: str) -> pathlib.Path:
        root = pathlib.Path(directory); write_json(root / "references/compatibility/v2.6/role-projections.json", fixture_json("role-projections.json"))
        common = root / "references/runtime-adapters/common.md"; common.parent.mkdir(parents=True); common.write_text("PORTABLE_CORE_BODY_MUST_NOT_BE_COPIED\n", encoding="utf-8")
        roles = root / "references/compatibility/v2.6/roles"; roles.mkdir(parents=True); (roles / "goal-lead.md").write_text("canonical lead role\n", encoding="utf-8"); (roles / "goal-reviewer.md").write_text("canonical reviewer role\n", encoding="utf-8")
        return root

    def test_codex_toml_and_claude_agents_project_without_copying_portable_core(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._projection_root(directory); project_role_projections(root); verdict = check_role_projections(root)
            self.assertTrue(verdict["ok"], verdict); self.assertEqual({"subagents/goal-lead.toml", "subagents/goal-reviewer.toml", ".claude/agents/goal-lead.md", ".claude/agents/goal-reviewer.md"}, set(verdict["projected_paths"]))
            for path in verdict["projected_paths"]:
                rendered = (root / path).read_text(encoding="utf-8"); self.assertIn("canonical_ref", rendered); self.assertNotIn("PORTABLE_CORE_BODY_MUST_NOT_BE_COPIED", rendered)

    def test_check_detects_missing_orphaned_and_drifted_projection(self) -> None:
        mutations = {"missing": lambda root: (root / "subagents/goal-lead.toml").unlink(), "orphaned": lambda root: (root / "subagents/orphan.toml").write_text("name = 'orphan'\n", encoding="utf-8"), "drifted": lambda root: (root / ".claude/agents/goal-reviewer.md").write_text("mutated\n", encoding="utf-8")}
        expected_errors = {"missing": "E_V26_PROJECTION_MISSING", "orphaned": "E_V26_PROJECTION_ORPHAN", "drifted": "E_V26_PROJECTION_DRIFT"}
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = self._projection_root(directory); project_role_projections(root); mutate(root); verdict = check_role_projections(root)
                self.assertFalse(verdict["ok"]); self.assertIn(expected_errors[label], verdict["errors"])


class TestV260RuntimeBindingReceipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None: cls.metadata = load_compatibility_metadata(FIXTURES / "compatibility-metadata.json")

    def test_receipts_preserve_connection_class_and_verification_state(self) -> None:
        direct = {"schema_version": "goal-teams-runtime-binding-v2.6-v1", "binding_run_id": "RUN-V26-DIRECT", "captured_at": "2026-08-07T16:00:00+08:00", **resolve_route(self.metadata, "host.codex", "provider.deepseek/flash")}
        blocked_bridge = {"schema_version": "goal-teams-runtime-binding-v2.6-v1", "binding_run_id": "RUN-V26-BRIDGE", "captured_at": "2026-08-07T16:00:00+08:00", **resolve_route(self.metadata, "host.codex", "model.kimi-k3")}
        direct_verdict, bridge_verdict = validate_runtime_binding_receipt(direct, self.metadata), validate_runtime_binding_receipt(blocked_bridge, self.metadata)
        self.assertTrue(direct_verdict["ok"], direct_verdict); self.assertTrue(bridge_verdict["ok"], bridge_verdict); self.assertEqual("direct_responses", direct_verdict["connection_class"]); self.assertEqual("contract_mapped_not_runtime_verified", direct_verdict["verification_state"]); self.assertEqual("bridge_required", bridge_verdict["connection_class"]); self.assertEqual("blocked", bridge_verdict["verification_state"])

    def test_bridge_cannot_be_recorded_as_direct_or_rewrite_resolved_model(self) -> None:
        bridge = resolve_route(self.metadata, "host.codex", "model.kimi-k3")
        common = {"schema_version": "goal-teams-runtime-binding-v2.6-v1", "binding_run_id": "RUN-V26-FORGED", "captured_at": "2026-08-07T16:00:00+08:00"}
        forged_direct = {**common, **bridge, "connection_class": "direct_responses"}; rewritten_model = {**common, **bridge, "resolved_model": "provider.deepseek/flash"}
        for label, receipt, error in (("bridge-as-direct", forged_direct, "E_V26_RECEIPT_BRIDGE_AS_DIRECT"), ("resolved-model-rewrite", rewritten_model, "E_V26_RECEIPT_RESOLVED_MODEL_REWRITE")):
            with self.subTest(label=label):
                verdict = validate_runtime_binding_receipt(receipt, self.metadata); self.assertFalse(verdict["ok"]); self.assertIn(error, verdict["errors"])


if __name__ == "__main__": unittest.main()
