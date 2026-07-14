"""V2.35 tests-first contract for specialists, routing, assertions and gates.

The V2.35 policy module is loaded lazily.  Before implementation, a missing
module or missing product artifact is therefore a deterministic RED assertion
instead of a unittest discovery/import failure.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import Any

from tests.v23.common import ROOT, gt, parse_envelope, run_cli
from tests.v23.test_v234_state_loop import require_v234, synthetic_contract_text


FIXTURE_ROOT = ROOT / "tests" / "v23" / "fixtures" / "v235"
POLICY_PATH = ROOT / "scripts" / "v23" / "v235_policy.py"
ROUTING_FIXTURE = FIXTURE_ROOT / "routing.json"
TEST_CASE_FIXTURE = FIXTURE_ROOT / "test-cases.json"
ROADMAP_BASENAME = "后续版本规划 V3.3-3.5.md"
ROADMAP_SHA256 = "e14d90c75a8da3bcd884c6262006ce839a47adfd45d095c40a003bcfaeef9fa4"
SPECIALISTS = ("security", "performance", "refactor", "sqa")
ROUTE_REQUIRED_FIELDS = (
    "schema_version",
    "project_size",
    "work_type",
    "release",
    "ui",
    "backend",
    "api",
    "cli",
    "tests",
    "risk",
    "security_sensitive",
    "external_write",
    "auth",
    "payment",
    "migration",
    "destructive",
    "specialist_requests",
)
REQUIRED_POLICY_APIS = (
    "normalize_project_route",
    "validate_test_case_contract",
    "validate_specialist_capability_registry",
    "validate_specialist_action",
    "validate_specialist_proposal",
    "validate_specialist_improvement_lifecycle",
    "evaluate_port_scan_request",
    "evaluate_implementation_gate",
    "evaluate_green_gate",
    "evaluate_release_audit_gate",
    "evaluate_package_selection",
)
ALLOWED_COMPARATORS = {
    "equals",
    "not_equals",
    "contains",
    "member_of",
    "less_than",
    "less_than_or_equal",
    "greater_than",
    "greater_than_or_equal",
    "json_subset",
    "sequence_equals",
    "sha256_equals",
    "exit_code_equals",
    "status_code_equals",
}


_POLICY: Any | None = None
_POLICY_LOAD_ERROR: BaseException | None = None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def filesystem_digest(root: Path) -> str:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            data = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            )
    return hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def require_policy(test: unittest.TestCase) -> Any:
    global _POLICY, _POLICY_LOAD_ERROR
    if _POLICY is None and _POLICY_LOAD_ERROR is None:
        try:
            if not POLICY_PATH.is_file():
                raise FileNotFoundError(POLICY_PATH)
            spec = importlib.util.spec_from_file_location(
                "goalteams_v235_policy_under_test", POLICY_PATH
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {POLICY_PATH}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            _POLICY = module
        except BaseException as exc:
            _POLICY_LOAD_ERROR = exc
    if _POLICY_LOAD_ERROR is not None:
        test.fail(
            "V2.35 policy implementation is not available yet: "
            f"{type(_POLICY_LOAD_ERROR).__name__}: {_POLICY_LOAD_ERROR}"
        )
    return _POLICY


def assert_subset(test: unittest.TestCase, expected: dict[str, Any], actual: Any) -> None:
    test.assertIsInstance(actual, dict, actual)
    for key, value in expected.items():
        test.assertIn(key, actual, actual)
        if isinstance(value, dict):
            assert_subset(test, value, actual[key])
        else:
            test.assertEqual(actual[key], value, actual)


def deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def remove_dotted_path(target: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    current: Any = target
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def materialize_matrix_case(base: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(base)
    deep_merge(value, copy.deepcopy(spec.get("patch", {})))
    for dotted in spec.get("remove_paths", []):
        remove_dotted_path(value, dotted)
    return value


def assert_policy_rejection(
    test: unittest.TestCase, result: Any, expected_code: str
) -> None:
    test.assertIsInstance(result, dict, result)
    test.assertFalse(result.get("ok"), result)
    test.assertEqual(result.get("error_code"), expected_code, result)
    test.assertIn("mutation_count", result, result)
    test.assertEqual(result["mutation_count"], 0, result)


def materialize_invalid_case(spec: dict[str, Any], fixtures: dict[str, Any]) -> dict[str, Any]:
    base = next(
        item for item in fixtures["valid_cases"] if item["case_id"] == spec["base_case_id"]
    )
    case = copy.deepcopy(base)
    if "patch" in spec:
        case.update(copy.deepcopy(spec["patch"]))
    for key in spec.get("remove", []):
        case.pop(key, None)
    for dotted in spec.get("remove_paths", []):
        remove_dotted_path(case, dotted)
    if "assertion_patch" in spec:
        case["assertions"][0].update(copy.deepcopy(spec["assertion_patch"]))
    if "replace_assertions" in spec:
        case["assertions"] = copy.deepcopy(spec["replace_assertions"])
    return case


class V235DeltaIsolationTests(unittest.TestCase):
    def test_delta_contract_has_exactly_36_continuous_ids_in_test_map(self) -> None:
        """ASSERT-V235-001 through ASSERT-V235-036 coverage ledger."""
        expected = {f"ASSERT-V235-{number:03d}" for number in range(1, 37)}
        self.assertEqual(set(ASSERTION_TEST_MAP), expected)
        for assertion_id, test_names in ASSERTION_TEST_MAP.items():
            self.assertTrue(test_names, assertion_id)
            for qualified in test_names:
                class_name, method_name = qualified.split(".", 1)
                test_class = globals().get(class_name)
                if test_class is None:
                    external = importlib.import_module(
                        "tests.v23.test_v235_versioned_runtime"
                    )
                    test_class = getattr(external, class_name, None)
                self.assertIsNotNone(test_class, qualified)
                self.assertTrue(hasattr(test_class, method_name), qualified)

    def test_roadmap_is_local_only_and_not_distributed(self) -> None:
        """ASSERT-V235-001: real selection keeps immutable source and process data out."""
        policy = require_policy(self)
        if (ROOT / ".git").exists():
            tracked = subprocess.run(
                ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
            ).stdout.decode("utf-8").split("\0")
            self.assertFalse(
                any(Path(item).name == ROADMAP_BASENAME for item in tracked if item)
            )
        else:
            package_manifest = ROOT / "scripts" / "install" / "package-manifest.txt"
            self.assertTrue(package_manifest.is_file(), package_manifest)
            manifest_entries = [
                line.strip()
                for line in package_manifest.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            self.assertFalse(
                any(ROADMAP_BASENAME in entry for entry in manifest_entries),
                manifest_entries,
            )
            self.assertFalse(
                any("GoalTeamsWork-" in entry for entry in manifest_entries),
                manifest_entries,
            )
            staged_paths = [
                path.relative_to(ROOT)
                for path in ROOT.rglob("*")
                if path.is_file() or path.is_symlink()
            ]
            self.assertFalse(
                any(path.name == ROADMAP_BASENAME for path in staged_paths), staged_paths
            )
            self.assertFalse(
                any(
                    any(part.startswith("GoalTeamsWork-") for part in path.parts)
                    for path in staged_paths
                ),
                staged_paths,
            )
        self.assertRegex(ROADMAP_SHA256, r"^[0-9a-f]{64}$")
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            outside = Path(directory) / "outside"
            (repo / "docs").mkdir(parents=True)
            (repo / "GoalTeamsWork-V2.35" / "private").mkdir(parents=True)
            outside.mkdir()
            (repo / "VERSION").write_text("V2.35\n", encoding="utf-8")
            (repo / "docs" / "v2.35-release-summary.md").write_text(
                "# Release\n", encoding="utf-8"
            )
            roadmap = repo / "docs" / ROADMAP_BASENAME
            roadmap.write_text("# immutable local roadmap fixture\n", encoding="utf-8")
            (repo / "GoalTeamsWork-V2.35" / "private" / "ledger.jsonl").write_text(
                "{}\n", encoding="utf-8"
            )
            manifest = repo / "package-manifest.txt"
            manifest.write_text(
                "file VERSION\nprefix docs/\nprefix GoalTeamsWork-V2.35/\n",
                encoding="utf-8",
            )
            roadmap_hash = hashlib.sha256(roadmap.read_bytes()).hexdigest()
            candidate_paths = [
                "VERSION",
                "docs/v2.35-release-summary.md",
                f"docs/{ROADMAP_BASENAME}",
                "GoalTeamsWork-V2.35/private/ledger.jsonl",
            ]
            request = {
                "repo_root": str(repo),
                "manifest_path": "package-manifest.txt",
                "candidate_paths": candidate_paths,
                "immutable_sources": [
                    {"path": f"docs/{ROADMAP_BASENAME}", "sha256": roadmap_hash}
                ],
            }
            before = filesystem_digest(repo)
            caller_variants = (
                ("missing-caller-denylist", copy.deepcopy(request)),
                (
                    "empty-caller-denylist",
                    {
                        **copy.deepcopy(request),
                        "deny_path_parts": [],
                        "deny_basenames": [],
                    },
                ),
                (
                    "attempted-allow-override",
                    {
                        **copy.deepcopy(request),
                        "deny_path_parts": [],
                        "deny_basenames": [],
                        "allow_paths": [
                            f"docs/{ROADMAP_BASENAME}",
                            "GoalTeamsWork-V2.35/private/ledger.jsonl",
                        ],
                    },
                ),
            )
            for name, candidate_request in caller_variants:
                selected = policy.evaluate_package_selection(candidate_request)
                with self.subTest(denylist_variant=name):
                    self.assertTrue(selected["ok"], selected)
                    self.assertEqual(selected["deny_policy_source"], "builtin_l0")
                    self.assertEqual(
                        selected["selected_paths"],
                        ["VERSION", "docs/v2.35-release-summary.md"],
                    )
                    self.assertEqual(
                        set(selected["denied_paths"]),
                        {
                            f"docs/{ROADMAP_BASENAME}",
                            "GoalTeamsWork-V2.35/private/ledger.jsonl",
                        },
                    )
                    self.assertEqual(
                        selected["immutable_sources"][0]["before_sha256"],
                        roadmap_hash,
                    )
                    self.assertEqual(
                        selected["immutable_sources"][0]["after_sha256"],
                        roadmap_hash,
                    )
                    self.assertEqual(selected["mutation_count"], 0)
                    self.assertEqual(filesystem_digest(repo), before)
            stale = copy.deepcopy(request)
            stale["immutable_sources"][0]["sha256"] = "0" * 64
            assert_policy_rejection(
                self,
                policy.evaluate_package_selection(stale),
                "E_V235_PACKAGE_IMMUTABLE_SOURCE",
            )
            self.assertEqual(filesystem_digest(repo), before)
            external = outside / "external.md"
            external.write_text("outside\n", encoding="utf-8")
            link = repo / "docs" / "linked.md"
            link.symlink_to(external)
            symlink_request = copy.deepcopy(request)
            symlink_request["candidate_paths"].append("docs/linked.md")
            repo_before = filesystem_digest(repo)
            outside_before = filesystem_digest(outside)
            assert_policy_rejection(
                self,
                policy.evaluate_package_selection(symlink_request),
                "E_V235_PACKAGE_PATH",
            )
            self.assertEqual(filesystem_digest(repo), repo_before)
            self.assertEqual(filesystem_digest(outside), outside_before)

    def test_v234_control_contract_remains_52_assertions(self) -> None:
        """ASSERT-V235-002: V2.35 does not redefine ASSERT-V234."""
        result = require_v234(self).validate_contract_document(synthetic_contract_text())
        self.assertTrue(result["ok"], result)
        self.assertEqual(int(result["metadata"]["required_assertion_count"]), 52)
        self.assertEqual(len(result["assertions"]), 52)
        self.assertFalse(
            any(item["id"].startswith("ASSERT-V235-") for item in result["assertions"])
        )

    def test_v235_schemas_are_separate_from_v23_schema(self) -> None:
        """ASSERT-V235-002/021/026: additive schemas, no V2.3 mutation."""
        schema_root = ROOT / "schemas" / "v2.35"
        for name in (
            "project-route.schema.json",
            "test-case.schema.json",
            "version-binding.schema.json",
        ):
            with self.subTest(name=name):
                path = schema_root / name
                self.assertTrue(path.is_file(), path)
                value = load_json(path)
                self.assertIsInstance(value, dict)
                self.assertIn("$schema", value)
        self.assertEqual(gt.SCHEMA_VERSION, "goal-teams-v2.3")

    def test_v235_policy_api_surface_is_callable_not_document_markers(self) -> None:
        """Executable surface shared by ASSERT-V235-001/005/006/013/021/024/026/036."""
        policy = require_policy(self)
        for name in REQUIRED_POLICY_APIS:
            with self.subTest(api=name):
                self.assertTrue(callable(getattr(policy, name, None)), name)


class V235SpecialistPackageTests(unittest.TestCase):
    def test_four_specialist_packages_and_tomls_are_complete(self) -> None:
        """ASSERT-V235-007/008/009/010/011."""
        agent_names: set[str] = set()
        for role in SPECIALISTS:
            member_root = ROOT / "prompts" / "members" / role
            for filename in ("prompt.md", "template.md", "workflow.md", "scripts.md"):
                self.assertTrue((member_root / filename).is_file(), f"{role}/{filename}")
            toml_path = ROOT / "subagents" / f"goal-{role}.toml"
            self.assertTrue(toml_path.is_file(), toml_path)
            config = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            self.assertEqual(config["name"], f"goal_{role}")
            self.assertEqual(config["sandbox_mode"], "read-only")
            self.assertNotIn(config["name"], agent_names)
            agent_names.add(config["name"])
            candidates = config.get("nickname_candidates")
            self.assertIsInstance(candidates, list)
            self.assertTrue(candidates)
            self.assertTrue(all(re.search(r"[\u4e00-\u9fff]", item) for item in candidates))

    def test_specialist_capability_registry_identity_and_permissions(self) -> None:
        """ASSERT-V235-006/011/013: identities and capabilities are executable facts."""
        policy = require_policy(self)
        registry = load_json(TEST_CASE_FIXTURE)["specialist_registry"]
        accepted = policy.validate_specialist_capability_registry(copy.deepcopy(registry))
        self.assertTrue(accepted["ok"], accepted)
        identities = registry["identities"]
        for field in ("agent_run_id", "member_id", "display_name", "transport_handle"):
            candidate = copy.deepcopy(registry)
            candidate["identities"][1][field] = identities[0][field]
            with self.subTest(duplicate=field):
                assert_policy_rejection(
                    self,
                    policy.validate_specialist_capability_registry(candidate),
                    "E_V235_SPECIALIST_IDENTITY_DUPLICATE",
                )
        wrong_agent = copy.deepcopy(registry)
        wrong_agent["identities"][0]["agent_type"] = "goal_performance"
        assert_policy_rejection(
            self,
            policy.validate_specialist_capability_registry(wrong_agent),
            "E_V235_SPECIALIST_CAPABILITY",
        )
        wrong_capability = copy.deepcopy(registry)
        wrong_capability["identities"][2]["capabilities"] = ["security_assessment"]
        assert_policy_rejection(
            self,
            policy.validate_specialist_capability_registry(wrong_capability),
            "E_V235_SPECIALIST_CAPABILITY",
        )
        missing_role = copy.deepcopy(registry)
        missing_role["identities"].pop()
        assert_policy_rejection(
            self,
            policy.validate_specialist_capability_registry(missing_role),
            "E_V235_SPECIALIST_CAPABILITY",
        )
        for field, value in (
            ("can_dispatch", True),
            ("can_spawn_subagents", True),
            ("coordination_depth", 2),
            ("sandbox_mode", "workspace-write"),
            ("handoff_mode", "direct_apply"),
        ):
            candidate = copy.deepcopy(registry)
            candidate["identities"][0][field] = value
            with self.subTest(permission=field):
                assert_policy_rejection(
                    self,
                    policy.validate_specialist_capability_registry(candidate),
                    "E_V235_SPECIALIST_PERMISSION",
                )

    def test_specialist_actions_forbid_dispatch_nested_write_and_self_transition(self) -> None:
        """ASSERT-V235-013/014: specialists can submit proposals only."""
        policy = require_policy(self)
        allowed = policy.validate_specialist_action(
            {
                "role": "security",
                "specialist_run_id": "RUN-V235-SECURITY-TEST",
                "action": "submit_proposal",
                "target": "goal_lead",
                "mutation_count": 0,
            }
        )
        self.assertTrue(allowed["ok"], allowed)
        proposal_negatives = (
            {
                "role": "security",
                "specialist_run_id": "RUN-V235-SECURITY-TEST",
                "action": "submit_proposal",
                "target": "product",
            },
            {
                "role": "security",
                "specialist_run_id": "RUN-V235-SECURITY-TEST",
                "action": "submit_proposal",
                "target": "goal_reviewer",
            },
            {
                "role": "security",
                "specialist_run_id": "RUN-V235-SECURITY-TEST",
                "action": "submit_proposal",
            },
            {
                "role": "security",
                "specialist_run_id": "RUN-V235-SECURITY-TEST",
                "action": "unknown_action",
                "target": "goal_lead",
            },
        )
        for request in proposal_negatives:
            with self.subTest(action=request.get("action"), target=request.get("target")):
                assert_policy_rejection(
                    self,
                    policy.validate_specialist_action(request),
                    "E_V235_SPECIALIST_ACTION_FORBIDDEN",
                )
        for action in (
            "dispatch",
            "spawn_subagent",
            "write_product",
            "write_central_tasklist",
            "self_apply",
            "self_verify",
        ):
            with self.subTest(action=action):
                assert_policy_rejection(
                    self,
                    policy.validate_specialist_action(
                        {
                            "role": "security",
                            "specialist_run_id": "RUN-V235-SECURITY-TEST",
                            "action": action,
                            "target": "product",
                        }
                    ),
                    "E_V235_SPECIALIST_ACTION_FORBIDDEN",
                )

    def test_specialist_l2_cannot_relax_l0_or_l1(self) -> None:
        """ASSERT-V235-012: priority is a deterministic proposal invariant."""
        policy = require_policy(self)
        base = load_json(TEST_CASE_FIXTURE)["specialist_proposals"]["performance"]
        valid_l2 = copy.deepcopy(base)
        valid_l2["priority_level"] = "L2"
        self.assertTrue(policy.validate_specialist_proposal(valid_l2)["ok"])
        for relaxes in (["L0:no_external_active_scan"], ["L1:independent_review"]):
            candidate = copy.deepcopy(valid_l2)
            candidate["relaxes"] = relaxes
            with self.subTest(relaxes=relaxes):
                assert_policy_rejection(
                    self,
                    policy.validate_specialist_proposal(candidate),
                    "E_V235_SPECIALIST_PRIORITY",
                )

    def test_specialist_improvement_lifecycle_requires_independent_holdout(self) -> None:
        """ASSERT-V235-014."""
        policy = require_policy(self)
        valid = [
            {"state": "proposed", "actor_run_id": "RUN-SPECIALIST-01"},
            {"state": "reviewed", "actor_run_id": "RUN-REVIEW-01"},
            {"state": "applied", "actor_run_id": "RUN-IMPLEMENT-01"},
            {
                "state": "verified",
                "actor_run_id": "RUN-QA-01",
                "regression_evidence_id": "EVID-REGRESSION-01",
                "holdout_evidence_id": "EVID-HOLDOUT-01",
            },
        ]
        result = policy.validate_specialist_improvement_lifecycle(valid)
        self.assertTrue(result["ok"], result)
        for invalid in (
            [valid[0], valid[2]],
            [*valid[:3], {**valid[3], "actor_run_id": "RUN-IMPLEMENT-01"}],
            [*valid[:3], {**valid[3], "holdout_evidence_id": ""}],
            [*valid[:3], {**valid[3], "state": "accepted"}],
        ):
            with self.subTest(invalid=invalid):
                rejected = policy.validate_specialist_improvement_lifecycle(invalid)
                assert_policy_rejection(
                    self, rejected, "E_V235_SPECIALIST_LIFECYCLE"
                )

    def test_security_scope_and_external_active_scan_fail_closed(self) -> None:
        """ASSERT-V235-015/016/028."""
        policy = require_policy(self)
        blocked = policy.evaluate_port_scan_request(
            {
                "target_scope": "external",
                "scan_mode": "active",
                "target": "example.invalid",
                "fresh_exact_authorization": False,
            }
        )
        assert_policy_rejection(
            self, blocked, "E_V235_EXTERNAL_PORT_SCAN_AUTH_REQUIRED"
        )
        self.assertTrue(blocked["blocked"], blocked)
        self.assertEqual(blocked["stop_reason"], "authorization_required")
        self.assertIsNone(blocked.get("command"))
        passive = policy.evaluate_port_scan_request(
            {
                "target_scope": "local",
                "scan_mode": "passive",
                "target": "localhost",
                "fresh_exact_authorization": False,
            }
        )
        self.assertTrue(passive["ok"], passive)
        self.assertEqual(passive["record"]["target"], "localhost")
        self.assertEqual(passive["record"]["outbound_connections"], 0)
        authorized = policy.evaluate_port_scan_request(
            {
                "target_scope": "external",
                "scan_mode": "active",
                "target": "example.invalid",
                "fresh_exact_authorization": True,
                "authorization_target": "example.invalid",
            }
        )
        self.assertTrue(authorized["ok"], authorized)
        self.assertEqual(authorized["handoff_mode"], "proposal_only")
        self.assertIsNone(authorized.get("command"), authorized)
        self.assertFalse(authorized.get("executed", False), authorized)
        self.assertEqual(authorized["mutation_count"], 0)
        self.assertEqual(authorized["dispatch_request"]["target"], "example.invalid")
        self.assertEqual(authorized["dispatch_request"]["scan_mode"], "active")
        self.assertEqual(
            authorized["dispatch_request"]["required_review_class"], "safety"
        )
        security = load_json(TEST_CASE_FIXTURE)["specialist_proposals"]["security"]
        self.assertTrue(policy.validate_specialist_proposal(copy.deepcopy(security))["ok"])
        missing_port = copy.deepcopy(security)
        missing_port["coverage"].remove("ports")
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(missing_port),
            "E_V235_SECURITY_SCOPE",
        )
        weak_review = copy.deepcopy(security)
        weak_review["required_review_class"] = "structural"
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(weak_review),
            "E_V235_SECURITY_REVIEW_CLASS",
        )
        write_scope = copy.deepcopy(security)
        write_scope["write_scope"] = ["src/security.py"]
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(write_scope),
            "E_V235_SPECIALIST_PERMISSION",
        )

    def test_performance_refactor_and_sqa_domain_contracts_are_complete(self) -> None:
        """ASSERT-V235-017/018/019/020."""
        policy = require_policy(self)
        proposals = load_json(TEST_CASE_FIXTURE)["specialist_proposals"]
        for role in ("performance", "refactor", "sqa"):
            with self.subTest(valid_role=role):
                self.assertTrue(
                    policy.validate_specialist_proposal(copy.deepcopy(proposals[role]))["ok"]
                )
        performance = proposals["performance"]
        for dotted in (
            "benchmark.environment_digest",
            "benchmark.data_scale",
            "benchmark.command",
            "benchmark.candidate_digest",
            "benchmark_evidence",
        ):
            candidate = copy.deepcopy(performance)
            remove_dotted_path(candidate, dotted)
            with self.subTest(performance_missing=dotted):
                assert_policy_rejection(
                    self,
                    policy.validate_specialist_proposal(candidate),
                    "E_V235_PERFORMANCE_BENCHMARK_REQUIRED",
                )
        for patch in (
            {"benchmark_evidence": {"current": False}},
            {"benchmark_evidence": {"candidate_digest": "e" * 64}},
            {"benchmark_evidence": {"environment_digest": "e" * 64}},
            {"benchmark_evidence": {"data_scale": {"rows": 1, "pages": 1}}},
        ):
            candidate = deep_merge(copy.deepcopy(performance), patch)
            assert_policy_rejection(
                self,
                policy.validate_specialist_proposal(candidate),
                "E_V235_PERFORMANCE_EVIDENCE_STALE",
            )
        refactor = proposals["refactor"]
        refactor_requirements = (
            ("equivalence_contract", "E_V235_REFACTOR_EQUIVALENCE"),
            ("regression_evidence", "E_V235_REFACTOR_EVIDENCE"),
            ("holdout_evidence", "E_V235_REFACTOR_EVIDENCE"),
            ("rollback_boundary", "E_V235_REFACTOR_ROLLBACK"),
        )
        for field, code in refactor_requirements:
            candidate = copy.deepcopy(refactor)
            candidate.pop(field)
            with self.subTest(refactor_missing=field):
                assert_policy_rejection(
                    self, policy.validate_specialist_proposal(candidate), code
                )
        for field in ("regression_evidence", "holdout_evidence"):
            for patch in ({"current": False}, {"state": "failed"}):
                candidate = copy.deepcopy(refactor)
                candidate[field].update(patch)
                with self.subTest(refactor_evidence=field, patch=patch):
                    assert_policy_rejection(
                        self,
                        policy.validate_specialist_proposal(candidate),
                        "E_V235_REFACTOR_EVIDENCE",
                    )
        empty_rollback = copy.deepcopy(refactor)
        empty_rollback["rollback_boundary"] = {}
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(empty_rollback),
            "E_V235_REFACTOR_ROLLBACK",
        )
        sqa = proposals["sqa"]
        for field in (
            "version_record",
            "index_ref",
            "classifications",
            "version_directory",
        ):
            candidate = copy.deepcopy(sqa)
            candidate.pop(field)
            with self.subTest(sqa_missing=field):
                assert_policy_rejection(
                    self,
                    policy.validate_specialist_proposal(candidate),
                    "E_V235_SQA_ARCHIVE_CONTRACT",
                )
        unsanitized = deep_merge(
            copy.deepcopy(sqa), {"public_copy": {"sanitized": False}}
        )
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(unsanitized),
            "E_V235_SQA_PUBLIC_SANITIZATION",
        )
        for public_patch in (
            {"secret_count": 1},
            {"absolute_home_path_count": 1},
        ):
            candidate = deep_merge(
                copy.deepcopy(sqa), {"public_copy": public_patch}
            )
            assert_policy_rejection(
                self,
                policy.validate_specialist_proposal(candidate),
                "E_V235_SQA_PUBLIC_SANITIZATION",
            )
        wrong_directory = copy.deepcopy(sqa)
        wrong_directory["version_directory"] = "docs/archive/V2.35-run2"
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(wrong_directory),
            "E_V235_SQA_ARCHIVE_CONTRACT",
        )
        incomplete_classes = copy.deepcopy(sqa)
        incomplete_classes["classifications"] = ["release"]
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(incomplete_classes),
            "E_V235_SQA_ARCHIVE_CONTRACT",
        )
        no_provenance = copy.deepcopy(sqa)
        no_provenance.pop("private_provenance")
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(no_provenance),
            "E_V235_SQA_PROVENANCE",
        )
        stale_provenance = deep_merge(
            copy.deepcopy(sqa), {"private_provenance": {"retained": False}}
        )
        assert_policy_rejection(
            self,
            policy.validate_specialist_proposal(stale_provenance),
            "E_V235_SQA_PROVENANCE",
        )


class V235RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_json(ROUTING_FIXTURE)

    def test_three_by_two_axes_and_default_matrix(self) -> None:
        """ASSERT-V235-026/027/029/030/031/032."""
        seen_axes: set[tuple[str, str]] = set()
        for fixture in self.fixtures["valid_cases"][:6]:
            output = gt.route(copy.deepcopy(fixture["input"]))
            self.assertEqual(output["schema_version"], "goal-teams-project-route-v2.35")
            expected = copy.deepcopy(fixture["expected"])
            reasons = expected.pop("reason_codes_contains", [])
            assert_subset(self, expected, output)
            for reason in reasons:
                self.assertIn(reason, output["reason_codes"])
            seen_axes.add((fixture["input"]["project_size"], fixture["input"]["work_type"]))
        self.assertEqual(
            seen_axes,
            {
                (size, work_type)
                for size in ("large", "medium", "small")
                for work_type in ("feature", "bugfix")
            },
        )

    def test_risk_flags_force_regulated_safety_without_rewriting_size(self) -> None:
        """ASSERT-V235-028/030/031."""
        base = copy.deepcopy(self.fixtures["valid_cases"][2]["input"])
        for flag in self.fixtures["risk_override_flags"]:
            request = copy.deepcopy(base)
            request[flag] = True
            output = gt.route(request)
            with self.subTest(flag=flag):
                self.assertIn("project_size", output, output)
                self.assertEqual(output["project_size"], "medium")
                self.assertEqual(output["profile"], "regulated")
                self.assertEqual(output["required_review_class"], "safety")
                self.assertEqual(output["specialists"]["security"], "required")

    def test_high_and_critical_risk_fixtures_execute_safety_override(self) -> None:
        """ASSERT-V235-028: risk enum overrides are executed, not dead fixtures."""
        by_id = {item["case_id"]: item for item in self.fixtures["valid_cases"]}
        for case_id in (
            "ROUTE-SMALL-HIGH-RISK-OVERRIDE",
            "ROUTE-SMALL-CRITICAL-RISK-OVERRIDE",
        ):
            fixture = by_id[case_id]
            output = gt.route(copy.deepcopy(fixture["input"]))
            expected = copy.deepcopy(fixture["expected"])
            reasons = expected.pop("reason_codes_contains", [])
            with self.subTest(case_id=case_id):
                assert_subset(self, expected, output)
                for reason in reasons:
                    self.assertIn(reason, output["reason_codes"])

    def test_ui_override_covers_full_three_by_two_matrix(self) -> None:
        """ASSERT-V235-030/032: every size/work type UI route requires E2E."""
        for fixture in self.fixtures["valid_cases"][:6]:
            request = copy.deepcopy(fixture["input"])
            request["ui"] = True
            output = gt.route(request)
            with self.subTest(
                project_size=request["project_size"], work_type=request["work_type"]
            ):
                self.assertIn("gates", output, output)
                self.assertEqual(output["gates"]["e2e"], "required")
                self.assertEqual(output["gates"]["architecture"], "required")
                self.assertEqual(output["gates"]["environment"], "required")
                self.assertEqual(output["gates"]["independent_tests"], "required")
                self.assertEqual(output["gates"]["evidence"], "required")
                if request["work_type"] == "bugfix":
                    self.assertEqual(output["gates"]["tdd"], "required")
                    self.assertEqual(output["gates"]["integration"], "required")

    def test_medium_and_small_never_drop_independent_tests_or_evidence(self) -> None:
        """ASSERT-V235-030/031/032."""
        for fixture in self.fixtures["valid_cases"][:6]:
            if fixture["input"]["project_size"] == "large":
                continue
            output = gt.route(copy.deepcopy(fixture["input"]))
            with self.subTest(case_id=fixture["case_id"]):
                self.assertIn("gates", output, output)
                self.assertEqual(output["gates"]["architecture"], "required")
                self.assertEqual(output["gates"]["environment"], "required")
                self.assertEqual(output["gates"]["independent_tests"], "required")
                self.assertEqual(output["gates"]["evidence"], "required")

    def test_explicit_specialist_only_adds_and_output_is_deterministic(self) -> None:
        """ASSERT-V235-027/030/033."""
        fixture = self.fixtures["valid_cases"][8]
        first = gt.route(copy.deepcopy(fixture["input"]))
        second = gt.route(copy.deepcopy(fixture["input"]))
        self.assertEqual(first, second)
        self.assertIn("specialists", first, first)
        self.assertEqual(first["specialists"]["performance"], "required")
        self.assertEqual(first["specialists"]["security"], "not_loaded")
        self.assertEqual(first["rule_set"], sorted(set(first["rule_set"])))

    def test_unknown_missing_conflicting_and_wrong_typed_inputs_fail_closed(self) -> None:
        """ASSERT-V235-026/027."""
        policy = require_policy(self)
        base = copy.deepcopy(self.fixtures["valid_cases"][2]["input"])
        for fixture in self.fixtures["invalid_cases"]:
            request = copy.deepcopy(base)
            request.update(copy.deepcopy(fixture.get("patch", {})))
            for key in fixture.get("remove", []):
                request.pop(key, None)
            result = policy.normalize_project_route(request)
            with self.subTest(case=fixture["case_id"]):
                assert_policy_rejection(self, result, fixture["error_code"])

    def test_every_required_route_field_and_type_fails_closed(self) -> None:
        """ASSERT-V235-026/027: complete schema boundary, no sampled fields only."""
        policy = require_policy(self)
        base = copy.deepcopy(self.fixtures["valid_cases"][2]["input"])
        for field in ROUTE_REQUIRED_FIELDS:
            missing = copy.deepcopy(base)
            missing.pop(field)
            result = policy.normalize_project_route(missing)
            with self.subTest(missing=field):
                assert_policy_rejection(self, result, "E_V235_ROUTE_REQUIRED")
        wrong_values: dict[str, Any] = {
            "schema_version": 235,
            "project_size": ["medium"],
            "work_type": {"value": "feature"},
            "risk": ["low"],
            "specialist_requests": "performance",
        }
        for field in (
            "release",
            "ui",
            "backend",
            "api",
            "cli",
            "tests",
            "security_sensitive",
            "external_write",
            "auth",
            "payment",
            "migration",
            "destructive",
        ):
            wrong_values[field] = "false"
        for field, wrong in wrong_values.items():
            request = copy.deepcopy(base)
            request[field] = wrong
            result = policy.normalize_project_route(request)
            with self.subTest(wrong_type=field):
                assert_policy_rejection(self, result, "E_V235_ROUTE_TYPE")

    def test_public_route_and_cli_delegate_every_invalid_error_family(self) -> None:
        """ASSERT-V235-026/027/035: public adapter cannot bypass canonical policy."""
        policy = require_policy(self)
        base = copy.deepcopy(self.fixtures["valid_cases"][2]["input"])
        by_error: dict[str, dict[str, Any]] = {}
        for fixture in self.fixtures["invalid_cases"]:
            by_error.setdefault(fixture["error_code"], fixture)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-route.json"
            for expected_code, fixture in sorted(by_error.items()):
                request = copy.deepcopy(base)
                request.update(copy.deepcopy(fixture.get("patch", {})))
                for key in fixture.get("remove", []):
                    request.pop(key, None)
                canonical = policy.normalize_project_route(copy.deepcopy(request))
                assert_policy_rejection(self, canonical, expected_code)
                public = gt.route(copy.deepcopy(request))
                with self.subTest(error_code=expected_code, surface="gt.route"):
                    assert_policy_rejection(self, public, expected_code)
                    self.assertEqual(public["error_code"], canonical["error_code"])
                path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
                proc = run_cli("route", str(path))
                with self.subTest(error_code=expected_code, surface="cli"):
                    self.assertEqual(proc.returncode, 1, proc.stderr)
                    envelope = parse_envelope(proc)
                    self.assertFalse(envelope["ok"], envelope)
                    self.assertEqual(envelope["error_code"], expected_code)
                    self.assertEqual(envelope.get("mutation_count"), 0, envelope)
                    self.assertEqual(len(proc.stdout.strip().splitlines()), 1)


class V235TestCaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_json(TEST_CASE_FIXTURE)

    def test_all_seven_test_kinds_have_executable_four_part_contracts(self) -> None:
        """ASSERT-V235-021/022/024/025."""
        policy = require_policy(self)
        kinds: set[str] = set()
        case_ids: set[str] = set()
        assertion_ids: set[str] = set()
        for case in self.fixtures["valid_cases"]:
            result = policy.validate_test_case_contract(copy.deepcopy(case))
            self.assertTrue(result["ok"], (case["case_id"], result))
            kinds.add(case["test_kind"])
            self.assertNotIn(case["case_id"], case_ids)
            case_ids.add(case["case_id"])
            for key in ("input", "processing", "expected_output", "assertions"):
                self.assertTrue(case[key], (case["case_id"], key))
            for assertion in case["assertions"]:
                self.assertNotIn(assertion["assertion_id"], assertion_ids)
                assertion_ids.add(assertion["assertion_id"])
                self.assertIn(assertion["comparator"], ALLOWED_COMPARATORS)
        self.assertEqual(
            kinds, {"unit", "tdd", "integration", "e2e", "cli", "api", "fixture"}
        )

    def test_allowed_comparator_set_is_exact_and_non_executable(self) -> None:
        """ASSERT-V235-022/023."""
        policy = require_policy(self)
        self.assertEqual(set(policy.ALLOWED_COMPARATORS), ALLOWED_COMPARATORS)
        joined = " ".join(policy.ALLOWED_COMPARATORS).casefold()
        for forbidden in ("eval", "python", "shell", "jsonpath", "import"):
            self.assertNotIn(forbidden, joined)

    def test_invalid_contracts_have_stable_specific_error_codes(self) -> None:
        """ASSERT-V235-021/022/023/024/025."""
        policy = require_policy(self)
        for spec in self.fixtures["invalid_cases"]:
            case = materialize_invalid_case(spec, self.fixtures)
            result = policy.validate_test_case_contract(case)
            with self.subTest(case=spec["case_id"]):
                assert_policy_rejection(self, result, spec["error_code"])

    def test_duplicate_assertion_ids_and_bad_refs_are_rejected(self) -> None:
        """ASSERT-V235-022."""
        policy = require_policy(self)
        case = copy.deepcopy(self.fixtures["valid_cases"][0])
        duplicate = copy.deepcopy(case["assertions"][0])
        case["assertions"].append(duplicate)
        result = policy.validate_test_case_contract(case)
        assert_policy_rejection(self, result, "E_V235_ASSERTION_ID")
        bad_ref = copy.deepcopy(self.fixtures["valid_cases"][0])
        bad_ref["assertions"][0]["actual_ref"] = "observed_output.unknown"
        assert_policy_rejection(
            self,
            policy.validate_test_case_contract(bad_ref),
            "E_V235_ASSERTION_REF",
        )

    def test_exit_and_status_only_are_rejected_for_every_test_kind(self) -> None:
        """ASSERT-V235-023/025: transport success never substitutes business output."""
        policy = require_policy(self)
        for case in self.fixtures["valid_cases"]:
            candidate = copy.deepcopy(case)
            candidate["assertions"] = [
                {
                    "assertion_id": f"A-{case['case_id']}-EXIT-ONLY",
                    "actual_ref": "execution.exit_code",
                    "comparator": "exit_code_equals",
                    "expected_value": 0,
                }
            ]
            with self.subTest(test_kind=case["test_kind"], transport="exit"):
                assert_policy_rejection(
                    self,
                    policy.validate_test_case_contract(candidate),
                    "E_V235_EXIT_CODE_ONLY",
                )
            status = copy.deepcopy(case)
            status["assertions"] = [
                {
                    "assertion_id": f"A-{case['case_id']}-STATUS-ONLY",
                    "actual_ref": "execution.status_code",
                    "comparator": "status_code_equals",
                    "expected_value": 200,
                }
            ]
            with self.subTest(test_kind=case["test_kind"], transport="status"):
                assert_policy_rejection(
                    self,
                    policy.validate_test_case_contract(status),
                    "E_V235_STATUS_CODE_ONLY",
                )

    def test_integration_contract_binds_input_processing_and_business_output(self) -> None:
        """ASSERT-V235-025."""
        policy = require_policy(self)
        integration = next(
            case for case in self.fixtures["valid_cases"] if case["test_kind"] == "integration"
        )
        accepted = policy.validate_test_case_contract(copy.deepcopy(integration))
        self.assertTrue(accepted["ok"], accepted)
        for dotted in (
            "processing.consumed_input_refs",
            "expected_output.input_bindings",
        ):
            candidate = copy.deepcopy(integration)
            remove_dotted_path(candidate, dotted)
            with self.subTest(missing=dotted):
                assert_policy_rejection(
                    self,
                    policy.validate_test_case_contract(candidate),
                    "E_V235_INTEGRATION_COMPARISON",
                )
        correspondence_cases: list[tuple[str, dict[str, Any]]] = []
        consumed_missing = copy.deepcopy(integration)
        consumed_missing["processing"]["consumed_input_refs"] = [
            "input.values.missing_case_id"
        ]
        correspondence_cases.append(("consumed-input-missing", consumed_missing))
        binding_input_mismatch = copy.deepcopy(integration)
        binding_input_mismatch["expected_output"]["input_bindings"][0][
            "input_ref"
        ] = "input.values.missing_case_id"
        correspondence_cases.append(("binding-input-mismatch", binding_input_mismatch))
        binding_observable_mismatch = copy.deepcopy(integration)
        binding_observable_mismatch["expected_output"]["input_bindings"][0][
            "observable_ref"
        ] = "observed_output.validation.foreign_result"
        correspondence_cases.append(
            ("binding-observable-mismatch", binding_observable_mismatch)
        )
        unasserted = copy.deepcopy(integration)
        unasserted["expected_output"]["value"]["passed"] = True
        unasserted["expected_output"]["observable_refs"].append(
            "observed_output.validation.passed"
        )
        unasserted["assertions"][0] = {
            "assertion_id": "A-INTEGRATION-UNRELATED-BUSINESS-01",
            "actual_ref": "observed_output.validation.passed",
            "comparator": "equals",
            "expected_ref": "expected_output.value.passed",
        }
        correspondence_cases.append(("bound-observable-unasserted", unasserted))
        duplicate_binding = copy.deepcopy(integration)
        duplicate_binding["expected_output"]["input_bindings"].append(
            copy.deepcopy(duplicate_binding["expected_output"]["input_bindings"][0])
        )
        correspondence_cases.append(("duplicate-binding", duplicate_binding))
        foreign_binding = copy.deepcopy(integration)
        foreign_binding["expected_output"]["input_bindings"].append(
            {
                "input_ref": "input.values.foreign",
                "observable_ref": "observed_output.validation.validated_case_ids",
            }
        )
        correspondence_cases.append(("foreign-binding", foreign_binding))
        for name, candidate in correspondence_cases:
            with self.subTest(correspondence=name):
                assert_policy_rejection(
                    self,
                    policy.validate_test_case_contract(candidate),
                    "E_V235_INTEGRATION_COMPARISON",
                )

    def test_cli_and_canonical_validator_expose_one_envelope_and_self_test(self) -> None:
        """ASSERT-V235-023/035."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            path.write_text(
                json.dumps(self.fixtures["valid_cases"][0], sort_keys=True),
                encoding="utf-8",
            )
            proc = run_cli("validate-test-case", str(path))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = parse_envelope(proc)
        self.assertTrue(envelope["ok"], envelope)
        invalid_spec = next(
            item
            for item in self.fixtures["invalid_cases"]
            if item["case_id"] == "INVALID-EMPTY-ASSERTIONS"
        )
        invalid_case = materialize_invalid_case(invalid_spec, self.fixtures)
        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "invalid-case.json"
            invalid_path.write_text(
                json.dumps(invalid_case, sort_keys=True), encoding="utf-8"
            )
            invalid_proc = run_cli("validate-test-case", str(invalid_path))
        self.assertEqual(invalid_proc.returncode, 1, invalid_proc.stderr)
        invalid_envelope = parse_envelope(invalid_proc)
        self.assertFalse(invalid_envelope["ok"], invalid_envelope)
        self.assertEqual(
            invalid_envelope["error_code"], "E_V235_ASSERTIONS_EMPTY"
        )
        self.assertEqual(invalid_envelope.get("mutation_count"), 0)
        self.assertEqual(len(invalid_proc.stdout.strip().splitlines()), 1)
        canonical = ROOT / "scripts" / "checks" / "validate-test-case-contract.py"
        self.assertTrue(canonical.is_file(), canonical)
        self_test = subprocess.run(
            [sys.executable, str(canonical), "--self-test"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(self_test.returncode, 0, (self_test.stdout, self_test.stderr))
        payload = json.loads(self_test.stdout)
        self.assertTrue(payload["passed"], payload)
        self.assertGreaterEqual(
            payload.get("negative_cases_executed", 0),
            len(self.fixtures["invalid_cases"]),
            payload,
        )
        expected_codes = {item["error_code"] for item in self.fixtures["invalid_cases"]}
        self.assertTrue(expected_codes <= set(payload.get("observed_error_codes", [])), payload)


class V235GateAndCompletionTests(unittest.TestCase):
    def test_mini_goal_run_keeps_completion_audit_graph_external(self) -> None:
        """ASSERT-V235-005/036: blocked sample state cannot pre-claim its auditor."""
        sample = ROOT / "examples" / "mini-goal-run" / ".codex" / "goal-teams"
        state = json.loads((sample / "team-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["team"]["status"], "blocked", state["team"])
        audit = state["team"]["completion_audit"]
        self.assertIs(audit["graph_external"], True, audit)
        self.assertEqual(audit["status"], "not_started", audit)
        for member in state["members"]:
            self.assertNotEqual(
                member.get("skill_or_subagent"), "goal_completion_auditor", member
            )
            self.assertNotIn("GT-008", member.get("claimed_tasks", []), member)

        tasklist = (
            sample / "versions" / "V0.1" / "tasklist.md"
        ).read_text(encoding="utf-8")
        handoff = tasklist.split("## Handoff Artifact Ledger", 1)[1].split(
            "## Graph-external Completion Audit", 1
        )[0]
        row = next(line for line in handoff.splitlines() if line.startswith("| GT-007 |"))
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        self.assertEqual(cells[4], "not applicable", row)
        self.assertEqual(cells[6], "not applicable", row)
        self.assertNotIn("goal_completion_auditor", cells[4], row)

    def test_required_gate_order_is_strict_and_preimplementation_is_three_gates(self) -> None:
        """ASSERT-V235-024/035: implementation and green gates reject every bypass."""
        policy = require_policy(self)
        fixtures = load_json(TEST_CASE_FIXTURE)
        implementation = fixtures["implementation_gate"]
        opened = policy.evaluate_implementation_gate(copy.deepcopy(implementation["valid"]))
        self.assertTrue(opened["ok"], opened)
        self.assertEqual(opened["gate_state"], "open")
        self.assertEqual(opened["mutation_count"], 0)
        for spec in implementation["invalid_cases"]:
            candidate = materialize_matrix_case(implementation["valid"], spec)
            with self.subTest(implementation_case=spec["case_id"]):
                assert_policy_rejection(
                    self,
                    policy.evaluate_implementation_gate(candidate),
                    spec["error_code"],
                )
        green = fixtures["green_gate"]
        accepted = policy.evaluate_green_gate(copy.deepcopy(green["valid"]))
        self.assertTrue(accepted["ok"], accepted)
        self.assertEqual(accepted["gate_state"], "accepted")
        self.assertEqual(accepted["mutation_count"], 0)
        for spec in green["invalid_cases"]:
            candidate = materialize_matrix_case(green["valid"], spec)
            with self.subTest(green_case=spec["case_id"]):
                assert_policy_rejection(
                    self,
                    policy.evaluate_green_gate(candidate),
                    spec["error_code"],
                )

    def test_completion_audit_is_graph_external_and_self_reference_stays_rejected(self) -> None:
        """ASSERT-V235-005/036: release then remote/local then post-release then Audit."""
        policy = require_policy(self)
        matrix = load_json(TEST_CASE_FIXTURE)["release_audit_gate"]
        allowed = policy.evaluate_release_audit_gate(copy.deepcopy(matrix["valid"]))
        self.assertTrue(allowed["ok"], allowed)
        self.assertTrue(allowed["audit_allowed"], allowed)
        self.assertEqual(allowed["mutation_count"], 0)
        for spec in matrix["invalid_cases"]:
            candidate = materialize_matrix_case(matrix["valid"], spec)
            with self.subTest(release_audit_case=spec["case_id"]):
                result = policy.evaluate_release_audit_gate(candidate)
                assert_policy_rejection(self, result, spec["error_code"])
                self.assertFalse(result.get("audit_allowed", False), result)

    def test_public_release_summary_is_pre_audit_and_private_audit_is_not_packaged(self) -> None:
        """ASSERT-V235-005/020/034/036."""
        manifest = (ROOT / "scripts" / "install" / "package-manifest.txt").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("docs/", manifest)
        self.assertIn("release/current/README.md", manifest)
        self.assertNotIn("GoalTeamsWork-V2.35", manifest)


class V235DistributionTests(unittest.TestCase):
    def test_startup_routing_and_role_byte_budgets(self) -> None:
        """ASSERT-V235-033."""
        startup = ("SKILL.md", "agents/openai.yaml", "RULES.md")
        startup_total = sum((ROOT / item).stat().st_size for item in startup)
        self.assertLessEqual(startup_total, 12032)
        routed_limits = {
            "references/rules-project-sizing.md": 6144,
            "references/rules-specialists.md": 6144,
            "references/test-case-assertion-protocol.md": 8192,
        }
        for relative, limit in routed_limits.items():
            path = ROOT / relative
            self.assertTrue(path.is_file(), path)
            self.assertLessEqual(path.stat().st_size, limit, relative)
        for role in SPECIALISTS:
            member_root = ROOT / "prompts" / "members" / role
            self.assertLessEqual((member_root / "prompt.md").stat().st_size, 3072, role)
            total = sum(
                (member_root / name).stat().st_size
                for name in ("prompt.md", "template.md", "workflow.md", "scripts.md")
            )
            self.assertLessEqual(total, 10240, role)

    def test_context_checker_reports_startup_routing_and_each_specialist(self) -> None:
        """ASSERT-V235-033."""
        path = ROOT / "scripts" / "checks" / "check-context-budget.py"
        spec = importlib.util.spec_from_file_location("v235_context_budget_under_test", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        result = module.evaluate(ROOT, 12032)
        self.assertTrue(result["passed"], result)
        self.assertIn("startup", result)
        self.assertIn("routing", result)
        self.assertIn("specialists", result)
        self.assertGreaterEqual(result["startup"]["remaining_bytes"], 0)
        self.assertEqual(set(result["specialists"]), set(SPECIALISTS))

    def test_specialist_references_are_conditional_not_startup_preloads(self) -> None:
        """ASSERT-V235-013/033."""
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/rules-project-sizing.md", skill)
        self.assertIn("references/rules-specialists.md", skill)
        self.assertRegex(skill, r"按需|条件|route|路由")
        for role in SPECIALISTS:
            self.assertNotIn(f"prompts/members/{role}/prompt.md", skill)

    def test_version_and_bilingual_release_surfaces_are_v235(self) -> None:
        """ASSERT-V235-034/035: keep V2.35 assets after the product advances."""
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "V2.40")
        current_markers = {
            "SKILL.md": "Goal Teams Lead V2.40",
            "goal-teams.md": "V2.40",
            "agents/openai.yaml": "Goal Teams V2.40",
            "README.md": "V2.40",
            "README.en.md": "V2.40",
            "release/current/README.md": "V2.40",
        }
        for relative, marker in current_markers.items():
            with self.subTest(relative=relative):
                self.assertIn(marker, (ROOT / relative).read_text(encoding="utf-8"))
        for relative in (
            "schemas/v2.35/project-route.schema.json",
            "schemas/v2.35/test-case.schema.json",
            "schemas/v2.35/version-binding.schema.json",
        ):
            with self.subTest(compatibility_asset=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)
        self.assertEqual(gt.PRODUCT_VERSION, "V2.40")


ASSERTION_TEST_MAP: dict[str, tuple[str, ...]] = {
    "ASSERT-V235-001": (
        "V235DeltaIsolationTests.test_roadmap_is_local_only_and_not_distributed",
    ),
    "ASSERT-V235-002": (
        "V235DeltaIsolationTests.test_v234_control_contract_remains_52_assertions",
        "V235DeltaIsolationTests.test_v235_schemas_are_separate_from_v23_schema",
    ),
    "ASSERT-V235-003": (
        "V235VersionBindingTests.test_default_and_explicit_binding",
        "V235VersionBindingTests.test_review_body_is_current_independent_and_contract_bound",
    ),
    "ASSERT-V235-004": (
        "V235VersionBindingTests.test_public_archive_path_uses_release_not_artifact",
        "V235VersionBindingTests.test_invalid_bindings_and_paths_are_zero_mutation",
        "V235VersionBindingTests.test_contract_semantic_mutation_is_rejected_even_when_all_hashes_rebind",
        "V235VersionBindingTests.test_review_symlink_is_rejected_without_repo_or_target_mutation",
    ),
    "ASSERT-V235-005": (
        "V235GateAndCompletionTests.test_completion_audit_is_graph_external_and_self_reference_stays_rejected",
    ),
    "ASSERT-V235-006": (
        "V235SpecialistPackageTests.test_specialist_capability_registry_identity_and_permissions",
    ),
    "ASSERT-V235-007": ("V235SpecialistPackageTests.test_four_specialist_packages_and_tomls_are_complete",),
    "ASSERT-V235-008": ("V235SpecialistPackageTests.test_four_specialist_packages_and_tomls_are_complete",),
    "ASSERT-V235-009": ("V235SpecialistPackageTests.test_four_specialist_packages_and_tomls_are_complete",),
    "ASSERT-V235-010": ("V235SpecialistPackageTests.test_four_specialist_packages_and_tomls_are_complete",),
    "ASSERT-V235-011": ("V235SpecialistPackageTests.test_four_specialist_packages_and_tomls_are_complete",),
    "ASSERT-V235-012": ("V235SpecialistPackageTests.test_specialist_l2_cannot_relax_l0_or_l1",),
    "ASSERT-V235-013": (
        "V235SpecialistPackageTests.test_specialist_capability_registry_identity_and_permissions",
        "V235SpecialistPackageTests.test_specialist_actions_forbid_dispatch_nested_write_and_self_transition",
    ),
    "ASSERT-V235-014": (
        "V235SpecialistPackageTests.test_specialist_improvement_lifecycle_requires_independent_holdout",
        "V235SpecialistPackageTests.test_specialist_actions_forbid_dispatch_nested_write_and_self_transition",
    ),
    "ASSERT-V235-015": ("V235SpecialistPackageTests.test_security_scope_and_external_active_scan_fail_closed",),
    "ASSERT-V235-016": ("V235SpecialistPackageTests.test_security_scope_and_external_active_scan_fail_closed",),
    "ASSERT-V235-017": ("V235SpecialistPackageTests.test_performance_refactor_and_sqa_domain_contracts_are_complete",),
    "ASSERT-V235-018": ("V235SpecialistPackageTests.test_performance_refactor_and_sqa_domain_contracts_are_complete",),
    "ASSERT-V235-019": ("V235SpecialistPackageTests.test_performance_refactor_and_sqa_domain_contracts_are_complete",),
    "ASSERT-V235-020": (
        "V235SpecialistPackageTests.test_performance_refactor_and_sqa_domain_contracts_are_complete",
        "V235GateAndCompletionTests.test_public_release_summary_is_pre_audit_and_private_audit_is_not_packaged",
    ),
    "ASSERT-V235-021": ("V235TestCaseContractTests.test_all_seven_test_kinds_have_executable_four_part_contracts",),
    "ASSERT-V235-022": ("V235TestCaseContractTests.test_duplicate_assertion_ids_and_bad_refs_are_rejected",),
    "ASSERT-V235-023": (
        "V235TestCaseContractTests.test_invalid_contracts_have_stable_specific_error_codes",
        "V235TestCaseContractTests.test_exit_and_status_only_are_rejected_for_every_test_kind",
    ),
    "ASSERT-V235-024": (
        "V235TestCaseContractTests.test_all_seven_test_kinds_have_executable_four_part_contracts",
        "V235GateAndCompletionTests.test_required_gate_order_is_strict_and_preimplementation_is_three_gates",
    ),
    "ASSERT-V235-025": (
        "V235TestCaseContractTests.test_integration_contract_binds_input_processing_and_business_output",
        "V235TestCaseContractTests.test_exit_and_status_only_are_rejected_for_every_test_kind",
    ),
    "ASSERT-V235-026": (
        "V235RoutingTests.test_unknown_missing_conflicting_and_wrong_typed_inputs_fail_closed",
        "V235RoutingTests.test_every_required_route_field_and_type_fails_closed",
        "V235RoutingTests.test_public_route_and_cli_delegate_every_invalid_error_family",
    ),
    "ASSERT-V235-027": ("V235RoutingTests.test_three_by_two_axes_and_default_matrix",),
    "ASSERT-V235-028": (
        "V235RoutingTests.test_risk_flags_force_regulated_safety_without_rewriting_size",
        "V235RoutingTests.test_high_and_critical_risk_fixtures_execute_safety_override",
    ),
    "ASSERT-V235-029": ("V235RoutingTests.test_three_by_two_axes_and_default_matrix",),
    "ASSERT-V235-030": (
        "V235RoutingTests.test_ui_override_covers_full_three_by_two_matrix",
        "V235RoutingTests.test_medium_and_small_never_drop_independent_tests_or_evidence",
    ),
    "ASSERT-V235-031": (
        "V235RoutingTests.test_three_by_two_axes_and_default_matrix",
        "V235RoutingTests.test_medium_and_small_never_drop_independent_tests_or_evidence",
    ),
    "ASSERT-V235-032": (
        "V235RoutingTests.test_ui_override_covers_full_three_by_two_matrix",
        "V235RoutingTests.test_medium_and_small_never_drop_independent_tests_or_evidence",
    ),
    "ASSERT-V235-033": ("V235DistributionTests.test_startup_routing_and_role_byte_budgets",),
    "ASSERT-V235-034": ("V235DistributionTests.test_version_and_bilingual_release_surfaces_are_v235",),
    "ASSERT-V235-035": (
        "V235TestCaseContractTests.test_cli_and_canonical_validator_expose_one_envelope_and_self_test",
        "V235RoutingTests.test_public_route_and_cli_delegate_every_invalid_error_family",
        "V235GateAndCompletionTests.test_required_gate_order_is_strict_and_preimplementation_is_three_gates",
        "V235DistributionTests.test_version_and_bilingual_release_surfaces_are_v235",
    ),
    "ASSERT-V235-036": (
        "V235GateAndCompletionTests.test_required_gate_order_is_strict_and_preimplementation_is_three_gates",
        "V235GateAndCompletionTests.test_completion_audit_is_graph_external_and_self_reference_stays_rejected",
        "V235GateAndCompletionTests.test_public_release_summary_is_pre_audit_and_private_audit_is_not_packaged",
    ),
}


if __name__ == "__main__":
    unittest.main()
