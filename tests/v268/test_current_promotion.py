"""Frozen Current-promotion contract for the bounded V2.68 output release.

Historical products are oracles, not templates whose identities follow VERSION.
The final activation/closure assertions become Green only after Lead's writer.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
GENERATION = ROOT / "references/current/generations/V2.68"
EXACT_V267 = {
    "scripts/v267/__init__.py",
    "scripts/v267/output_dashboard.py",
    "schemas/v2.67/output-dashboard.schema.json",
}
BASELINE = "24f522a87b1aa74b6b127962ab88522ddc1f489d"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_paths() -> set[str]:
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    )
    sources = {
        item.decode() for item in listing.stdout.split(b"\0") if item
        and (ROOT / item.decode()).is_file()
        and not (ROOT / item.decode()).is_symlink()
    }
    selected = set()
    for line in (ROOT / "scripts/install/package-manifest.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        kind, value = line.split(maxsplit=1)
        if kind == "file":
            selected.add(value)
        elif kind == "prefix":
            selected.update(path for path in sources if path.startswith(value))
    return selected


def route_facts(phase: str = "development") -> dict:
    return {
        "project_size": "medium", "workflow_phase": phase,
        "stage": "released" if phase == "release" else "candidate",
        "release_intent": phase == "release",
        "implementation_scope_complete": phase == "release",
        "risk": "low", "failure_consequence": "low",
        "reversibility": "reversible", "compliance": "none",
        "external_write": phase == "release", "security_sensitive": False,
        "ui_or_desktop": False, "agent_runtime": False,
        "environment_check_required": False,
        "authorization_state": "granted", "facts_source_sha256": "a" * 64,
    }


class TestCurrentPromotion(unittest.TestCase):
    def test_default_identity_and_gateway_entry_are_v268(self) -> None:
        self.assertEqual("V2.68", (ROOT / "VERSION").read_text().strip())
        for relative in (
            "SKILL.md", "RULES.md", "AGENTS.md", "agents/openai.yaml",
            ".agents/skills/goal-teams/SKILL.md",
        ):
            with self.subTest(path=relative):
                text = (ROOT / relative).read_text()
                self.assertIn("V2.68", text)
                self.assertNotIn("本地输出候选入口", text)
        for relative in ("SKILL.md", "RULES.md", "agents/openai.yaml"):
            with self.subTest(gateway=relative):
                self.assertIn("scripts.v268.output_gateway", (ROOT / relative).read_text())

    def test_official_output_owner_preserves_typed_document_and_host_boundaries(self) -> None:
        owner = (GENERATION / "contracts/output-dashboard.md").read_text()
        for marker in (
            "specification_delivery", "prepare", "observe", "render",
            "development_admitted", "host_enforcement=unavailable",
            "本轮全部完成；当前无进行中或剩余任务。",
            "validate_output", "serialize_output", "◆ Goal-Teams 任务执行看板",
        ):
            self.assertIn(marker, owner)
        for relative in ("SKILL.md", "goal-teams.md"):
            with self.subTest(path=relative):
                self.assertIn("specification_delivery", (ROOT / relative).read_text())
        self.assertIn("specification_delivery", (GENERATION / "core.md").read_text())

    def test_current_manifest_has_no_old_owner_or_candidate_prompt(self) -> None:
        activation = load_json(GENERATION / "activation-manifest.json")
        prompt = load_json(GENERATION / "prompt-manifest.json")
        rule = load_json(GENERATION / "rule-manifest.json")
        self.assertEqual("V2.68", activation["generation_id"])
        self.assertEqual("V2.65", activation["identity"]["execution_asset_generation"])
        output = "references/current/generations/V2.68/contracts/output-dashboard.md"
        self.assertIn(output, prompt["current_rule_allowlist"])
        self.assertTrue(prompt["routes"])
        for route in prompt["routes"].values():
            self.assertIn(output, route["ordered_refs"])
            self.assertEqual(len(route["ordered_refs"]), len(set(route["ordered_refs"])))
            self.assertTrue(all(path.startswith("references/current/generations/V2.68/")
                                for path in route["ordered_refs"]))
        self.assertTrue(all(owner["path"].startswith("references/current/generations/V2.68/")
                            for owner in rule["owners"]))

    def test_modern_route_derivation_does_not_fall_back_to_legacy(self) -> None:
        from scripts.v250.route_derivation import derive_route
        from scripts.v250.route_closure import compile_route_closure
        for phase in ("development", "release"):
            with self.subTest(phase=phase):
                receipt = derive_route(route_facts(phase), generation_id="V2.68")
                self.assertEqual("V2.68", receipt["derivation_version"])
                self.assertEqual(phase, receipt["workflow_phase"])
        with self.assertRaisesRegex(RuntimeError, "E_V263_ROUTE_FACTS_REQUIRED"):
            compile_route_closure(ROOT, {"generation_id": "V2.68"}, "V250-ROUTE-DISCUSSION")

    def test_modern_generation_control_paths_are_v268(self) -> None:
        from scripts.v250.generation_runtime import (
            _generation_dynamic_control_globs, _generation_required_control_paths,
        )
        paths = _generation_required_control_paths("V2.68")
        self.assertIn("references/current/generations/V2.68/contracts/release-route-manifest.json", paths)
        self.assertNotIn("release/current/manifest.json", paths)
        self.assertFalse(any("V2.62" in path for path in paths))
        globs = _generation_dynamic_control_globs("V2.68")
        self.assertIn("references/current/generations/V2.68/contracts/*.json", globs)

    def test_writer_supports_exact_shared_execution_without_legacy_overlap(self) -> None:
        from scripts.v250 import refresh_generation_manifests as refresh
        self.assertEqual("V2.65", refresh.EXECUTION_ASSET_GENERATION_BY_POLICY.get("V2.68"))
        previous = load_json(ROOT / "references/current/generations/V2.67/activation-manifest.json")
        legacy = refresh._legacy_classification(previous, "V2.68", "V2.67")
        def classified(path: str) -> bool:
            return path in legacy["exact_paths"] or any(
                path.startswith(prefix) for prefix in legacy["path_prefixes"])
        for path in EXACT_V267:
            self.assertFalse(classified(path), path)
        for path in (
            "scripts/v267/runtime_transition.py", "schemas/v2.67/runtime-transition-receipt.schema.json",
            "tests/v267/test_output_contract.py", "references/current/generations/V2.67/core.md",
        ):
            self.assertTrue(classified(path), path)

    def test_schema_and_rule_id_validator_accept_v268_without_deleting_history(self) -> None:
        schema = load_json(ROOT / "schemas/v2.50/activation-manifest.schema.json")
        self.assertIn("V2.68", schema["properties"]["generation_id"]["enum"])
        self.assertIn("V2.67", schema["properties"]["generation_id"]["enum"])
        path = ROOT / "scripts/checks/validate-v250-generation.py"
        spec = importlib.util.spec_from_file_location("_promotion_generation_checker", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(["GT268-OUTPUT-GATEWAY"], module.RULE_RE.findall(
            "- `GT268-OUTPUT-GATEWAY`: all final responses use the gateway.\n"))

    def test_default_package_contains_only_exact_v267_output_dependencies(self) -> None:
        selected = selected_paths()
        self.assertTrue({"scripts/v268/output_gateway.py", "scripts/v268/output_dashboard.py",
                         "scripts/v268/specification_delivery.py"} <= selected)
        old_product = {path for path in selected if path.startswith(("scripts/v267/", "schemas/v2.67/"))}
        self.assertEqual(EXACT_V267, old_product)
        forbidden = ("tests/v267/", "references/current/generations/V2.67/",
                     "references/compatibility/v2.67/", "references/candidates/",
                     ".agents/skills/goal-teams-output-candidate/", "docs/", "develops/")
        self.assertFalse(any(path.startswith(forbidden) for path in selected))

    def test_package_only_cli_renders_without_candidate_or_predecessor_tests(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".v268-package-promotion-", dir=ROOT) as temp:
            package = Path(temp)
            for relative in selected_paths():
                if not relative.startswith(("scripts/", "schemas/")):
                    continue
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            request = {
                "schema_version": "goal-teams-output-request-v2.68",
                "facts": {"activity": "discussion", "persistent_write": False, "development_admitted": False},
                "project": "goal-teams", "current_round": 1, "estimated_total_rounds": 1,
                "loop_decision": "stop", "task": "检查安装闭包", "members": "test runner",
                "result": "本地调用链验证。LOOP 改进建议：保持 Host 能力边界。",
                "banchmark": "本地测试。", "next_action": "结束。", "dashboard": None,
                "specification_record": None,
            }
            request_path = package / "request.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False))
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": ""}
            result = subprocess.run(
                [sys.executable, "-B", "-m", "scripts.v268.output_gateway", "render",
                 "--request", str(request_path), "--repo-root", str(package)],
                cwd=package, env=environment, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            rendered = json.loads(result.stdout)
            self.assertTrue(rendered["ok"])
            self.assertEqual("unavailable", rendered["host_enforcement"])
            self.assertTrue(rendered["body"].startswith("任务："))

    def test_v268_output_tests_do_not_import_predecessor_test_helpers(self) -> None:
        for name in ("test_output_gateway.py", "test_dashboard_completion.py"):
            self.assertNotIn("from tests.v267", (ROOT / "tests/v268" / name).read_text())
        helper = importlib.import_module("tests.v268.dashboard_fixture")
        view = helper._view()
        self.assertEqual("goal-teams-output-dashboard-v2.67", view["schema_version"])
        self.assertTrue(view["dashboard"]["tasklist_ref"]["href"].startswith("tests/v268/"))

    def test_member_and_host_projections_are_synchronized(self) -> None:
        result = subprocess.run([sys.executable, "-B", "scripts/v250/generate_subagents.py", "--check"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        members = sorted((ROOT / "subagents").glob("goal-*.toml"))
        self.assertGreater(len(members), 10)
        for path in members:
            self.assertIn('# common_prefix_generation = "V2.68"', path.read_text())
        projector = importlib.import_module("scripts.v268.role_projections")
        self.assertTrue(projector.check_role_projections(ROOT)["ok"])
        plan = load_json(ROOT / "references/compatibility/v2.68/role-projections.json")
        self.assertEqual("references/current/generations/V2.68/core.md", plan["portable_core_ref"])

    def test_shared_predecessor_code_and_human_readmes_are_unchanged(self) -> None:
        for relative in sorted(EXACT_V267 | {"README.md", "README.en.md"}):
            previous = subprocess.run(["git", "show", f"{BASELINE}:{relative}"],
                                      cwd=ROOT, capture_output=True, check=True).stdout
            self.assertEqual(hashlib.sha256(previous).hexdigest(),
                             hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), relative)


if __name__ == "__main__":
    unittest.main()
