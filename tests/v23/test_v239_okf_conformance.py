"""Independent unit contracts for the V2.39 Google OKF governance core."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from tests.v23.common import ROOT


FIXTURES = ROOT / "tests" / "v23" / "fixtures" / "v239" / "okf"
RUNTIME_PATH = ROOT / "scripts" / "v23" / "okf_conformance.py"


def _load_optional(name: str, path: Path):
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


okf = _load_optional("goalteams_v239_okf_conformance_test", RUNTIME_PATH)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _error_codes(result: dict[str, Any]) -> set[str]:
    values = result.get("errors", result.get("findings", []))
    codes: set[str] = set()
    for value in values or []:
        if isinstance(value, dict) and value.get("error_code"):
            codes.add(str(value["error_code"]))
        elif isinstance(value, str):
            codes.add(value.split(":", 1)[0])
    return codes


@contextmanager
def _policy_root(policy_name: str = "policy.json") -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = root / "references" / "okf-conformance-policy.json"
        target.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURES / policy_name, target)
        yield root


class V239OkfConformanceTests(unittest.TestCase):
    def api(self, name: str) -> Callable[..., Any]:
        self.assertIsNotNone(okf, "scripts/v23/okf_conformance.py is required")
        value = getattr(okf, name, None)
        self.assertTrue(callable(value), f"missing public API okf_conformance.{name}")
        return value

    def policy(self, root: Path) -> dict[str, Any]:
        result = self.api("load_policy")(root)
        self.assertEqual(
            result["schema_version"], "goal-teams-okf-conformance-policy-v1"
        )
        self.assertRegex(result["policy_sha256"], r"^[0-9a-f]{64}$")
        return result

    def test_required_okf_public_apis_exist(self) -> None:
        for name in (
            "load_policy",
            "classify_path",
            "parse_okf_document",
            "scan_paths",
            "scan_bundle",
            "validate_completion_claim",
        ):
            with self.subTest(name=name):
                self.api(name)

    def test_policy_classifies_a_b_c_and_packet_is_a(self) -> None:
        with _policy_root() as root:
            policy = self.policy(root)
            cases = {
                "prompts/packets/member-goal-packet.md": ("A", "A_PACKET"),
                "references/runtime.md": ("A", "A_REFERENCE"),
                "prompts/lead/core.md": ("B", "B_PROMPT"),
                "SKILL.md": ("B", "B_RESERVED"),
                "tests/fixture.json": ("C", "C_NATIVE"),
            }
            for path, expected in cases.items():
                with self.subTest(path=path):
                    result = self.api("classify_path")(path, policy)
                    self.assertEqual((result["class"], result["rule_id"]), expected)

    def test_unknown_and_overlap_classification_fail_closed(self) -> None:
        with _policy_root() as root:
            policy = self.policy(root)
            with self.assertRaisesRegex(Exception, "E_OKF_CLASS_UNKNOWN"):
                self.api("classify_path")("unclassified.md", policy)
        with _policy_root("overlap-policy.json") as root:
            policy = self.policy(root)
            with self.assertRaisesRegex(Exception, "E_OKF_CLASS_OVERLAP"):
                self.api("classify_path")("folder/document.md", policy)

    def test_safe_parser_accepts_valid_document_and_reports_hashes(self) -> None:
        result = self.api("parse_okf_document")(FIXTURES / "valid.md")
        self.assertEqual(result["frontmatter"]["type"], "Test Fixture")
        self.assertEqual(result["frontmatter"]["okf_version"], "0.1")
        self.assertIn("# Valid OKF fixture", result["body"])
        self.assertEqual(result["artifact_sha256"], _sha256(FIXTURES / "valid.md"))
        self.assertRegex(result["frontmatter_sha256"], r"^[0-9a-f]{64}$")

    def test_parser_rejects_non_byte_zero_frontmatter_and_bom(self) -> None:
        parse = self.api("parse_okf_document")
        valid = (FIXTURES / "valid.md").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            for name, data in (
                ("space.md", b" " + valid),
                ("bom.md", b"\xef\xbb\xbf" + valid),
                ("preamble.md", b"comment\n" + valid),
            ):
                path = Path(td) / name
                path.write_bytes(data)
                with self.subTest(name=name), self.assertRaisesRegex(
                    Exception, "E_OKF_FRONTMATTER_START"
                ):
                    parse(path)

    def test_parser_rejects_duplicate_non_mapping_and_nested_yaml(self) -> None:
        parse = self.api("parse_okf_document")
        cases = (
            ("duplicate-key.md", "E_OKF_FRONTMATTER_DUPLICATE_KEY"),
            ("non-mapping.md", "E_OKF_FRONTMATTER_MAPPING"),
            ("nested-mapping.md", "E_OKF_FRONTMATTER_UNSUPPORTED"),
        )
        for name, code in cases:
            with self.subTest(name=name), self.assertRaisesRegex(Exception, code):
                parse(FIXTURES / name)

    def test_parser_rejects_yaml_tags_anchors_aliases_and_invalid_utf8(self) -> None:
        parse = self.api("parse_okf_document")
        with self.assertRaisesRegex(Exception, "E_OKF_FRONTMATTER_UNSAFE"):
            parse(FIXTURES / "dangerous-yaml.md")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invalid-utf8.md"
            path.write_bytes(b"---\ntype: Test\n---\n\n" + b"\xff")
            with self.assertRaisesRegex(Exception, "E_OKF_UTF8"):
                parse(path)

    def test_parser_rejects_empty_type_and_empty_body(self) -> None:
        parse = self.api("parse_okf_document")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty_type = root / "empty-type.md"
            empty_type.write_text(
                "---\ntype: \ntitle: T\ndescription: D\n"
                "timestamp: 2026-07-13T10:00:00Z\nokf_version: \"0.1\"\n---\n\nBody.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "E_OKF_TYPE"):
                parse(empty_type)
            empty_body = root / "empty-body.md"
            empty_body.write_text(
                "---\ntype: Test\ntitle: T\ndescription: D\n"
                "timestamp: 2026-07-13T10:00:00Z\nokf_version: \"0.1\"\n---\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "E_OKF_BODY_EMPTY"):
                parse(empty_body)

    def test_parser_rejects_symlink_and_oversized_document(self) -> None:
        parse = self.api("parse_okf_document")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            symlink = root / "linked.md"
            symlink.symlink_to(FIXTURES / "valid.md")
            with self.assertRaisesRegex(Exception, "E_OKF_PATH_SYMLINK"):
                parse(symlink)
            large = root / "large.md"
            large.write_text(
                "---\ntype: Test\ntitle: T\ndescription: D\n"
                "timestamp: 2026-07-13T10:00:00Z\nokf_version: \"0.1\"\n---\n\n"
                + ("x" * 70000),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "E_OKF_FILE_SIZE"):
                parse(large)

    def test_scan_paths_emits_class_rule_hash_and_relative_path(self) -> None:
        with _policy_root() as policy_root, tempfile.TemporaryDirectory() as td:
            policy = self.policy(policy_root)
            root = Path(td)
            target = root / "references" / "valid.md"
            target.parent.mkdir(parents=True)
            shutil.copyfile(FIXTURES / "valid.md", target)
            report = self.api("scan_paths")(
                [target], policy, {"root": root, "mode": "manifest"}
            )
            self.assertTrue(report["passed"])
            self.assertEqual(report["files"][0]["path"], "references/valid.md")
            self.assertEqual(report["files"][0]["class"], "A")
            self.assertEqual(report["files"][0]["rule_id"], "A_REFERENCE")
            self.assertEqual(report["files"][0]["sha256"], _sha256(target))
            self.assertNotIn(str(root), json.dumps(report, ensure_ascii=False))

    def test_scan_paths_rejects_root_escape(self) -> None:
        with _policy_root() as policy_root, tempfile.TemporaryDirectory() as td:
            policy = self.policy(policy_root)
            root = Path(td) / "root"
            root.mkdir()
            outside = Path(td) / "outside.md"
            shutil.copyfile(FIXTURES / "valid.md", outside)
            report = self.api("scan_paths")(
                [outside], policy, {"root": root, "mode": "manifest"}
            )
            self.assertFalse(report["passed"])
            self.assertIn("E_OKF_PATH_ESCAPE", _error_codes(report))

    def test_actual_team_completion_field_aliases_cannot_bypass_evidence_gate(self) -> None:
        with _policy_root() as policy_root, tempfile.TemporaryDirectory() as td:
            policy = self.policy(policy_root)
            root = Path(td)
            target = root / "references" / "claim.md"
            target.parent.mkdir(parents=True)
            template = (
                "---\n"
                "type: Review\n"
                "title: Claim\n"
                "description: Completion alias test.\n"
                "timestamp: 2026-07-13T10:00:00Z\n"
                "okf_version: \"0.1\"\n"
                "{field}: {value}\n"
                "---\n\nBody.\n"
            )
            for field, value in (
                ("status", "accepted"),
                ("review_state", "accepted"),
                ("audit_state", "accepted"),
                ("semantic_review_state", "passed"),
                ("validation_state", "passed_independent_semantic_review"),
            ):
                with self.subTest(field=field):
                    target.write_text(
                        template.format(field=field, value=value), encoding="utf-8"
                    )
                    report = self.api("scan_paths")(
                        [target], policy, {"root": root, "mode": "explicit"}
                    )
                    self.assertFalse(report["passed"])
                    self.assertIn("E_OKF_OWNER_VALIDATOR", _error_codes(report))

    def test_valid_mini_bundle_has_lowercase_index_and_chronological_memory(self) -> None:
        with _policy_root() as policy_root:
            policy = self.policy(policy_root)
            report = self.api("scan_bundle")(FIXTURES / "mini-valid", policy)
            self.assertTrue(report["passed"], report.get("findings"))
            self.assertEqual(report["bundle"]["index_path"], "index.md")
            self.assertEqual(report["bundle"]["memory_author"], "GoalTeams")
            self.assertEqual(report["bundle"]["timeline_order"], "old_to_new")

    def test_invalid_bundle_rejects_uppercase_index_and_bad_memory(self) -> None:
        with _policy_root() as policy_root:
            policy = self.policy(policy_root)
            report = self.api("scan_bundle")(FIXTURES / "mini-invalid", policy)
            self.assertFalse(report["passed"])
            codes = _error_codes(report)
            self.assertIn("E_OKF_BUNDLE_INDEX", codes)
            self.assertIn("E_OKF_BUNDLE_MEMORY", codes)

    def _claim_fixture(
        self, root: Path, *, outcome: str = "passed", trust_level: str = "local_verified"
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        artifact = root / "review.md"
        artifact.write_text(
            "---\ntype: Review\ntitle: Review\ndescription: Claim fixture.\n"
            "timestamp: 2026-07-13T10:00:00Z\nokf_version: \"0.1\"\n---\n\n# Review\n",
            encoding="utf-8",
        )
        metadata = {
            "audit_state": outcome,
            "owner_agent_type": "goal_backend",
            "owner_member_id": "owner",
            "owner_agent_run_id": "root/owner",
            "owner_canonical_task_path": "/root/owner",
            "validator_agent_type": "goal_reviewer",
            "validator_member_id": "validator",
            "validator_agent_run_id": "root/validator",
            "validator_canonical_task_path": "/root/validator",
        }
        document = {
            "path": "review.md",
            "frontmatter": metadata,
            "artifact_sha256": _sha256(artifact),
        }
        context = {
            "root": root,
            "identity_registry": {
                "runs": [
                    {
                        "agent_type": "goal_backend",
                        "member_id": "owner",
                        "agent_run_id": "root/owner",
                        "canonical_task_path": "/root/owner",
                    },
                    {
                        "agent_type": "goal_reviewer",
                        "member_id": "validator",
                        "agent_run_id": "root/validator",
                        "canonical_task_path": "/root/validator",
                    },
                ]
            },
            "evidence_records": [
                {
                    "evidence_id": "EVD-V239-CLAIM",
                    "artifact_ref": "review.md",
                    "artifact_sha256": _sha256(artifact),
                    "validator_agent_run_id": "root/validator",
                    "check_state": "passed",
                    "trust_level": trust_level,
                }
            ],
            "completion_audit": {
                "audit_state": "passed",
                "validator_agent_run_id": "root/validator",
                "artifact_ref": "review.md",
                "artifact_sha256": _sha256(artifact),
            },
        }
        return document, context

    def test_completion_claim_requires_independent_identity_and_external_evidence(self) -> None:
        validate = self.api("validate_completion_claim")
        with tempfile.TemporaryDirectory() as td:
            document, context = self._claim_fixture(Path(td))
            self.assertTrue(validate(document, context)["passed"])

            same_run = copy.deepcopy(document)
            same_run["frontmatter"]["validator_agent_run_id"] = "root/owner"
            result = validate(same_run, context)
            self.assertFalse(result["passed"])
            self.assertIn("E_OKF_OWNER_VALIDATOR", _error_codes(result))

            no_evidence = copy.deepcopy(context)
            no_evidence["evidence_records"] = []
            result = validate(document, no_evidence)
            self.assertFalse(result["passed"])
            self.assertIn("E_OKF_EVIDENCE", _error_codes(result))

    def test_completion_claim_fails_after_artifact_hash_mutation(self) -> None:
        validate = self.api("validate_completion_claim")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            document, context = self._claim_fixture(root)
            (root / "review.md").write_text(
                (root / "review.md").read_text(encoding="utf-8") + "mutation\n",
                encoding="utf-8",
            )
            result = validate(document, context)
            self.assertFalse(result["passed"])
            self.assertIn("E_OKF_ARTIFACT_HASH_STALE", _error_codes(result))

    def test_achieved_claim_requires_local_verified_and_completion_audit(self) -> None:
        validate = self.api("validate_completion_claim")
        with tempfile.TemporaryDirectory() as td:
            document, context = self._claim_fixture(
                Path(td), outcome="achieved", trust_level="manual_observation"
            )
            result = validate(document, context)
            self.assertFalse(result["passed"])
            self.assertIn("E_OKF_EVIDENCE", _error_codes(result))
            local = copy.deepcopy(context)
            local["evidence_records"][0]["trust_level"] = "local_verified"
            local["completion_audit"] = None
            result = validate(document, local)
            self.assertFalse(result["passed"])
            self.assertIn("E_OKF_COMPLETION_AUDIT", _error_codes(result))

    def test_every_accepted_or_achieved_alias_requires_completion_audit(self) -> None:
        validate = self.api("validate_completion_claim")
        aliases = (
            "audit_state",
            "run_outcome",
            "validation_state",
            "status",
            "review_state",
            "semantic_review_state",
            "check_state",
        )
        for alias in aliases:
            for value in ("accepted", "achieved"):
                with self.subTest(alias=alias, value=value), tempfile.TemporaryDirectory() as td:
                    document, context = self._claim_fixture(Path(td), outcome="passed")
                    document["frontmatter"].pop("audit_state", None)
                    document["frontmatter"][alias] = value
                    context["completion_audit"] = None
                    result = validate(document, context)
                    self.assertFalse(result["passed"])
                    self.assertIn("E_OKF_COMPLETION_AUDIT", _error_codes(result))

        for value in ("complete", "completed"):
            with self.subTest(alias="status", value=value), tempfile.TemporaryDirectory() as td:
                document, context = self._claim_fixture(Path(td), outcome="passed")
                document["frontmatter"].pop("audit_state", None)
                document["frontmatter"]["status"] = value
                context["completion_audit"] = None
                result = validate(document, context)
                self.assertFalse(result["passed"])
                self.assertIn("E_OKF_COMPLETION_AUDIT", _error_codes(result))


if __name__ == "__main__":
    unittest.main()
