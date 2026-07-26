from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = PACKAGE_ROOT / "runtime" / "release_member.py"
SPEC = importlib.util.spec_from_file_location("release_member_under_test", RUNTIME_PATH)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def digest(path: Path) -> str:
    return runtime.file_digest(path)


def future_time() -> str:
    return (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ReleaseMemberFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.verify_patch = mock.patch.object(
            runtime.ED25519_VERIFY, "verify", return_value=True
        )
        self.verify_patch.start()
        self.toolchain_basename_patch = mock.patch.object(
            runtime,
            "APPROVED_TOOLCHAIN_HOST_COMMAND_BASENAME",
            "true",
        )
        self.toolchain_basename_patch.start()
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve()
        self.release_root = self.project / "release"
        self.release_root.mkdir()
        self.environments = {}
        for name in ("local", "development", "test", "staging", "production"):
            path = self.project / f"environment-{name}.md"
            path.write_text(f"# {name.title()}\n", encoding="utf-8")
            self.environments[name] = path
        self.environment = self.environments["production"]
        self.architecture_baseline_commit = "9" * 40
        self.environment_created_at = runtime.now_utc()
        self.artifact = self.project / "application.bin"
        self.artifact.write_bytes(b"verified-application-artifact\n")
        self.source_tree_digest = "a" * 64
        self.artifact_digest = digest(self.artifact)
        self.toolchain_host_path = Path("/usr/bin/true")
        self.toolchain_host_digest = digest(self.toolchain_host_path)
        self.candidate = {
            "release_identity": "example-v1",
            "source_commit": "c" * 40,
            "source_tree_digest": self.source_tree_digest,
            "artifact_digest": self.artifact_digest,
        }
        self.required_kinds = [
            "unit_test",
            "api_integration",
            "e2e",
            "review",
            "completion_audit",
            "artifact",
            "package",
            "sbom",
            "provenance",
            "signature",
        ]
        self.evidence = []
        for kind in self.required_kinds:
            path = self.project / f"{kind}.json"
            binding = (
                self.artifact_digest
                if kind in {"artifact", "package", "sbom", "provenance", "signature"}
                else self.source_tree_digest
            )
            observed_at = runtime.now_utc()
            issuer = {"role": f"{kind}-owner", "run_id": f"run-{kind}"}
            evidence_payload = {
                "schema_version": "goal-teams-release-evidence-item-v2.45",
                "kind": kind,
                "status": "passed",
                "candidate_binding": binding,
                "observed_at": observed_at,
                "issuer": issuer,
                "assertions": [{"name": f"{kind}-verified", "passed": True}],
            }
            evidence_bindings = {
                field: evidence_payload[field]
                for field in (
                    "schema_version",
                    "kind",
                    "status",
                    "candidate_binding",
                    "observed_at",
                    "issuer",
                    "assertions",
                )
            }
            evidence_payload["host_attestation"] = {
                "schema_version": "goal-teams-release-evidence-host-attestation-v2.45",
                "algorithm": "Ed25519",
                "issuer": "goal-teams-trusted-host",
                "key_id": runtime.TRUSTED_APPROVAL_KEY_ID,
                "evidence_kind": kind,
                "bindings_sha256": runtime.object_digest(evidence_bindings),
                "issued_at": runtime.now_utc(),
                "challenge_id": f"challenge-evidence-{kind}",
                "signa" + "ture": "00" * 64,
            }
            path.write_text(json.dumps(evidence_payload) + "\n", encoding="utf-8")
            self.evidence.append(
                {
                    "kind": kind,
                    "status": "passed",
                    "path": str(path),
                    "sha256": digest(path),
                    "candidate_binding": binding,
                    "observed_at": observed_at,
                    "issuer": issuer,
                }
            )
        self.adapters = {}
        for name in ("backup", "benchmark", "deploy", "verify", "rollback"):
            path = self.project / f"{name}-adapter.sh"
            path.write_text("#!/bin/bash\nset -euo pipefail\nexit 0\n", encoding="utf-8")
            path.chmod(0o750)
            self.adapters[name] = {
                "path": str(path),
                "sha256": digest(path),
                "capabilities": [f"{name}_capability"],
                "idempotent": name in {"benchmark", "verify"},
            }
        self.restore_proof = self.project / "restore-proof.json"
        self.backup_scope_digest = "b" * 64
        self.restore_proof.write_text(
            json.dumps(
                {
                    "status": "passed",
                    "target_environment": "production",
                    "environment_document_digest": digest(self.environment),
                    "backup_scope_digest": self.backup_scope_digest,
                    "restore_point_id": "restore-drill-1",
                    "verified_at": runtime.now_utc(),
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.toolchain_basename_patch.stop()
        self.verify_patch.stop()
        self.temporary.cleanup()

    def toolchain_host_command(self, language: str, build_tool: str) -> dict:
        kit_ids = {
            ("java", "maven"): "java-maven-v1",
            ("java", "gradle"): "java-gradle-v1",
            ("rust", "cargo"): "rust-cargo-v1",
            ("go", "go-modules"): "go-modules-v1",
            ("python", "pip"): "python-pip-v1",
            ("python", "uv"): "python-uv-v1",
            ("python", "poetry"): "python-poetry-v1",
            ("node", "npm"): "node-npm-v1",
            ("node", "pnpm"): "node-pnpm-v1",
            ("node", "yarn"): "node-yarn-v1",
        }
        kit_id = kit_ids[(language, build_tool)]
        manifest_sha256 = digest(
            runtime.catalog_path("plans/toolchain-actions-v1.json")
        )
        provenance = {
            "schema_version": "goal-teams-toolchain-provenance-v2.45",
            "source": "signed-release:fixture",
            "version": "fixture-v1",
            "manifest_sha256": manifest_sha256,
            "signature_status": "verified",
            "signer_identity": "goal-teams-trusted-toolchain-authority",
        }
        provenance_bindings = {
            "identity": "goal-teams-release-toolchain-host-v245",
            "executable_sha256": self.toolchain_host_digest,
            "prefetch_action": f"prefetch-{kit_id}",
            "build_action": f"build-{kit_id}",
            "manifest_sha256": manifest_sha256,
            "source": provenance["source"],
            "version": provenance["version"],
            "signer_identity": provenance["signer_identity"],
        }
        provenance["host_attestation"] = {
            "schema_version": "goal-teams-toolchain-provenance-attestation-v2.45",
            "algorithm": "Ed25519",
            "issuer": "goal-teams-trusted-host",
            "key_id": runtime.TRUSTED_APPROVAL_KEY_ID,
            "bindings_sha256": runtime.object_digest(provenance_bindings),
            "issued_at": runtime.now_utc(),
            "expires_at": future_time(),
            "challenge_id": f"toolchain-provenance-{kit_id}",
            "signa" + "ture": "00" * 64,
        }
        return {
            "path": str(self.toolchain_host_path),
            "sha256": self.toolchain_host_digest,
            "identity": "goal-teams-release-toolchain-host-v245",
            "prefetch_action": f"prefetch-{kit_id}",
            "build_action": f"build-{kit_id}",
            "provenance": provenance,
        }

    def evidence_request(self, target_name: str = "production") -> dict:
        documents = {
            name: {
                "schema_version": "goal-teams-environment-document-v2.45",
                "path": str(path),
                "sha256": digest(path),
                "created_at": self.environment_created_at,
                "architecture_baseline_commit": self.architecture_baseline_commit,
                "issuer": {
                    "role": "goal_architect",
                    "run_id": f"environment-{name}",
                },
            }
            for name, path in self.environments.items()
        }
        target = self.environments[target_name]
        return {
            "project_root": str(self.project),
            "candidate": self.candidate,
            "environment_documents": {
                "set_digest": runtime.object_digest(documents),
                "documents": documents,
                "target_name": target_name,
                "target_document_path": str(target),
                "target_document_digest": digest(target),
            },
            "required_evidence_kinds": self.required_kinds,
            "evidence": self.evidence,
            "release_intent_source": "explicit_user_prompt",
        }

    def write_ready_report(self, target_name: str = "production", suffix: str = "") -> Path:
        report = runtime.check_evidence(self.evidence_request(target_name))
        path = self.project / f"release-evidence-report{suffix}.json"
        runtime.write_json(path, report)
        return path

    def plan_request(self, run_id: str = "run-1", **changes: object) -> dict:
        environment = str(changes.get("environment", "production"))
        surface = str(changes.get("surface", "application"))
        language = str(changes.get("language", "java"))
        build_tool = str(changes.get("build_tool", "maven"))
        surface_identities = {
            "application": {"configuration_identity": "cfg-v1"},
            "container-kubernetes": {"namespace": "example", "workload": "example-api"},
            "wechat-miniprogram": {"appid": "wx-app", "code_version": "1.0.0"},
            "github-skill": {
                "repository": "example/release-skill",
                "tag": "v1.0.0",
                "expected_installed_tree_digest": "e" * 64,
            },
        }
        rollback_identities = {
            "application": {
                "artifact_digest": "1" * 64,
                "configuration_identity": "cfg-previous",
            },
            "container-kubernetes": {
                "oci_index_digest": "2" * 64,
                "namespace": "example",
                "workload": "example-api",
            },
            "wechat-miniprogram": {
                "appid": "wx-app",
                "code_version": "0.9.0",
            },
            "github-skill": {
                "repository": "example/release-skill",
                "tag": "v0.9.0",
                "tag_commit": "d" * 40,
                "asset_digest": "3" * 64,
                "expected_installed_tree_digest": "4" * 64,
            },
        }
        request = {
            "project_root": str(self.project),
            "release_root": str(self.release_root),
            "release_run_id": run_id,
            "evidence_report": str(self.write_ready_report(environment, f"-{run_id}")),
            "language": language,
            "build_tool": build_tool,
            "environment": environment,
            "surface": surface,
            "surface_identity": surface_identities[surface],
            "rollback_identity": rollback_identities[surface],
            "artifact_path": str(self.artifact),
            "adapters": self.adapters,
            "gates": {
                "restore_proof": {
                    "path": str(self.restore_proof),
                    "sha256": digest(self.restore_proof),
                    "status": "passed",
                },
                "backup_receipt": {"path": str(self.project / "backup-receipt.json")},
                "benchmark_baseline": {"path": str(self.project / "benchmark-baseline.json")},
                "post_release_verification": {"path": str(self.project / "post-release.json")},
            },
        }
        if environment in {"local", "development"}:
            request["toolchain_host_command"] = self.toolchain_host_command(
                language,
                build_tool,
            )
        request.update(changes)
        discovery = runtime.discover_scripts(
            {"project_root": str(self.project), "release_root": str(self.release_root)}
        )
        if discovery["clarification_required"] and "existing_script_decision" not in changes:
            request["existing_script_decision"] = {
                "action": "ignore",
                "discovery_report_digest": discovery["report_digest"],
                "confirmation_source": "test-human-confirmation",
            }
        return request

    def plan_approval(self, plan: dict) -> dict:
        approval = {
            "approval_type": "plan",
            "approval_id": "approval-plan-1",
            "plan_digest": plan["plan_digest"],
            "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
            "source_commit": plan["candidate"]["source_commit"],
            "source_tree_digest": plan["candidate"]["source_tree_digest"],
            "environment_document_digest": plan["environment_documents"]["target_document_digest"],
            "environment_document_set_digest": plan["environment_documents"]["set_digest"],
            "target_environment": plan["environment_kit"]["name"],
            "release_surface": plan["surface_kit"]["name"],
            "kit_selection_digest": plan["kit_selection_digest"],
            "surface_identity_digest": plan["surface_identity_digest"],
            "rollback_identity_digest": plan["rollback_identity_digest"],
            "release_root": plan["release_root"],
            "approver": "human-release-owner",
            "expires_at": future_time(),
        }
        expected = {
            "plan_digest": plan["plan_digest"],
            "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
            "source_commit": plan["candidate"]["source_commit"],
            "source_tree_digest": plan["candidate"]["source_tree_digest"],
            "environment_document_digest": plan["environment_documents"]["target_document_digest"],
            "environment_document_set_digest": plan["environment_documents"]["set_digest"],
            "target_environment": plan["environment_kit"]["name"],
            "release_surface": plan["surface_kit"]["name"],
            "kit_selection_digest": plan["kit_selection_digest"],
            "surface_identity_digest": plan["surface_identity_digest"],
            "rollback_identity_digest": plan["rollback_identity_digest"],
            "release_root": plan["release_root"],
        }
        approval["host_acceptance"] = self.host_acceptance(
            "plan", approval["approval_id"], approval["expires_at"], expected
        )
        return approval

    def compose_ready_bundle(self, run_id: str = "run-1") -> tuple[dict, Path, dict]:
        plan_result = runtime.plan_release(self.plan_request(run_id))
        plan = plan_result["plan"]
        approval_path = self.project / f"{run_id}-plan-approval.json"
        runtime.write_json(approval_path, self.plan_approval(plan))
        result = runtime.compose_bundle(
            {
                "plan_path": plan_result["plan_path"],
                "plan_approval_path": str(approval_path),
                "script_bundle_version": "v1.0.0",
            }
        )
        return plan, Path(plan_result["plan_path"]), result

    def execution_approval(
        self,
        plan: dict,
        manifest: dict,
        *,
        mode: str = "dry-run",
        operation: str = "release",
        execution_id: str = "execution-1",
    ) -> dict:
        approval = {
            "approval_type": "execution",
            "approval_id": "approval-exec-1",
            "execution_id": execution_id,
            "mode": mode,
            "operation": operation,
            "plan_approval_id": manifest["plan_approval_id"],
            "plan_digest": plan["plan_digest"],
            "script_bundle_digest": manifest["script_bundle_digest"],
            "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
            "source_commit": plan["candidate"]["source_commit"],
            "source_tree_digest": plan["candidate"]["source_tree_digest"],
            "environment_document_digest": plan["environment_documents"]["target_document_digest"],
            "environment_document_set_digest": plan["environment_documents"]["set_digest"],
            "target_environment": plan["environment_kit"]["name"],
            "release_surface": plan["surface_kit"]["name"],
            "kit_selection_digest": plan["kit_selection_digest"],
            "surface_identity_digest": plan["surface_identity_digest"],
            "rollback_identity_digest": plan["rollback_identity_digest"],
            "requested_capabilities": plan["requested_capabilities"],
            "approver": "human-release-owner",
            "expires_at": future_time(),
        }
        expected = {
            "execution_id": execution_id,
            "mode": mode,
            "operation": operation,
            "plan_approval_id": manifest["plan_approval_id"],
            "plan_digest": plan["plan_digest"],
            "script_bundle_digest": manifest["script_bundle_digest"],
            "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
            "source_commit": plan["candidate"]["source_commit"],
            "source_tree_digest": plan["candidate"]["source_tree_digest"],
            "environment_document_digest": plan["environment_documents"]["target_document_digest"],
            "environment_document_set_digest": plan["environment_documents"]["set_digest"],
            "target_environment": plan["environment_kit"]["name"],
            "release_surface": plan["surface_kit"]["name"],
            "kit_selection_digest": plan["kit_selection_digest"],
            "surface_identity_digest": plan["surface_identity_digest"],
            "rollback_identity_digest": plan["rollback_identity_digest"],
            "requested_capabilities": sorted(plan["requested_capabilities"]),
        }
        approval["host_acceptance"] = self.host_acceptance(
            "execution", approval["approval_id"], approval["expires_at"], expected
        )
        return approval

    def host_acceptance(
        self,
        approval_type: str,
        approval_id: str,
        expires_at: str,
        bindings: dict,
    ) -> dict:
        return {
            "schema_version": "goal-teams-release-engineer-host-approval-v2.45",
            "algorithm": "Ed25519",
            "issuer": "goal-teams-trusted-host",
            "key_id": runtime.TRUSTED_APPROVAL_KEY_ID,
            "approval_type": approval_type,
            "approval_id": approval_id,
            "issued_at": runtime.now_utc(),
            "expires_at": expires_at,
            "challenge_id": f"challenge-{approval_type}-1",
            "bindings_sha256": runtime.object_digest(bindings),
            "database_safety_attested": True,
            "least_privilege_attested": True,
            "human_confirmation_attested": True,
            "execution_isolation_attested": True,
            "credential_scrubbing_attested": True,
            "signa" + "ture": "00" * 64,
        }


class EvidenceTests(ReleaseMemberFixture):
    def test_final_evidence_checker_never_runs_full_suite(self) -> None:
        with mock.patch.object(runtime.subprocess, "run") as subprocess_run:
            report = runtime.check_evidence(self.evidence_request())
        subprocess_run.assert_not_called()
        self.assertEqual(report["evidence_status"], "ready")
        self.assertEqual(report["full_test_execution_count"], 0)

    def test_not_run_test_evidence_is_not_pass(self) -> None:
        request = self.evidence_request()
        request["evidence"][0] = dict(request["evidence"][0], status="not_run")
        report = runtime.check_evidence(request)
        self.assertEqual(report["evidence_status"], "not_ready")
        self.assertTrue(any(item["state"] == "status_not_run" for item in report["findings"]))

    def test_candidate_binding_drift_blocks_readiness(self) -> None:
        request = self.evidence_request()
        request["evidence"][0] = dict(request["evidence"][0], candidate_binding="f" * 64)
        report = runtime.check_evidence(request)
        self.assertEqual(report["evidence_status"], "not_ready")
        self.assertTrue(any(item["state"] == "candidate_binding_mismatch" for item in report["findings"]))

    def test_all_five_architecture_environment_documents_are_required(self) -> None:
        request = self.evidence_request()
        del request["environment_documents"]["documents"]["staging"]
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.check_evidence(request)
        self.assertEqual(caught.exception.code, "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED")

    def test_evidence_denominator_cannot_be_reduced(self) -> None:
        request = self.evidence_request()
        request["required_evidence_kinds"] = ["artifact"]
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.check_evidence(request)
        self.assertEqual(
            caught.exception.code, "E_V245_RE_EVIDENCE_DENOMINATOR_REDUCED"
        )

    def test_untyped_self_report_is_not_release_evidence(self) -> None:
        request = self.evidence_request()
        item = request["evidence"][0]
        path = Path(item["path"])
        path.write_text('{"kind":"unit_test","passed":true}\n', encoding="utf-8")
        item["sha256"] = digest(path)
        report = runtime.check_evidence(request)
        self.assertEqual(report["evidence_status"], "not_ready")
        self.assertTrue(
            any(
                finding["state"] == "typed_evidence_invalid"
                for finding in report["findings"]
            )
        )

    def test_unsigned_evidence_is_not_release_evidence(self) -> None:
        request = self.evidence_request()
        target = Path(request["evidence"][0]["path"])
        payload = runtime.load_json(target)
        payload.pop("host_attestation")
        runtime.write_json(target, payload)
        request["evidence"][0]["sha256"] = digest(target)
        report = runtime.check_evidence(request)
        self.assertEqual(report["evidence_status"], "not_ready")
        self.assertIn(
            "trusted_host_attestation_invalid",
            {finding["state"] for finding in report["findings"]},
        )

    def test_evidence_issuer_run_cannot_self_cover_multiple_kinds(self) -> None:
        request = self.evidence_request()
        first_run = request["evidence"][0]["issuer"]["run_id"]
        request["evidence"][1]["issuer"]["run_id"] = first_run
        target = Path(request["evidence"][1]["path"])
        payload = runtime.load_json(target)
        payload["issuer"]["run_id"] = first_run
        bindings = {
            field: payload[field]
            for field in (
                "schema_version",
                "kind",
                "status",
                "candidate_binding",
                "observed_at",
                "issuer",
                "assertions",
            )
        }
        payload["host_attestation"]["bindings_sha256"] = runtime.object_digest(bindings)
        runtime.write_json(target, payload)
        request["evidence"][1]["sha256"] = digest(target)
        report = runtime.check_evidence(request)
        self.assertEqual(report["evidence_status"], "not_ready")
        self.assertIn(
            "issuer_run_reused",
            {finding["state"] for finding in report["findings"]},
        )

    def test_environment_documents_require_architecture_provenance(self) -> None:
        request = self.evidence_request()
        request["environment_documents"]["documents"]["local"].pop(
            "architecture_baseline_commit"
        )
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.check_evidence(request)
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
        )


class PlanAndCompositionTests(ReleaseMemberFixture):
    def test_release_root_escape_has_zero_write(self) -> None:
        outside = self.project.parent / f"{self.project.name}-outside"
        request = self.plan_request(release_root=str(outside), run_id="escape")
        before = sorted(str(path) for path in self.project.rglob("*"))
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(caught.exception.code, "E_V245_RE_RELEASE_ROOT_ESCAPE")
        self.assertEqual(sorted(str(path) for path in self.project.rglob("*")), before)
        self.assertFalse(outside.exists())

    def test_plan_requires_all_production_adapters(self) -> None:
        adapters = dict(self.adapters)
        adapters.pop("backup")
        result = runtime.plan_release(self.plan_request("missing-adapter", adapters=adapters))
        self.assertEqual(result["plan"]["plan_state"], "blocked")
        self.assertIn("backup", result["plan"]["missing_requirements"])

    def test_missing_plan_approval_blocks_render(self) -> None:
        plan_result = runtime.plan_release(self.plan_request("no-approval"))
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.compose_bundle(
                {
                    "plan_path": plan_result["plan_path"],
                    "plan_approval_path": str(self.project / "missing.json"),
                    "script_bundle_version": "v1.0.0",
                }
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_INPUT_MISSING")
        self.assertFalse((Path(plan_result["plan"]["run_root"]) / "scripts").exists())

    def test_plan_approval_drift_blocks_render(self) -> None:
        plan_result = runtime.plan_release(self.plan_request("stale-approval"))
        plan = plan_result["plan"]
        approval = self.plan_approval(plan)
        approval["target_environment"] = "staging"
        approval_path = self.project / "stale-plan-approval.json"
        runtime.write_json(approval_path, approval)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.compose_bundle(
                {
                    "plan_path": plan_result["plan_path"],
                    "plan_approval_path": str(approval_path),
                    "script_bundle_version": "v1.0.0",
                }
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_PLAN_APPROVAL_STALE")

    def test_compose_writes_new_immutable_local_bundle(self) -> None:
        plan, _, result = self.compose_ready_bundle()
        bundle = Path(result["bundle_root"])
        self.assertTrue(runtime.is_within(bundle, self.release_root))
        self.assertTrue((bundle / "script-bundle-manifest.json").is_file())
        self.assertTrue((bundle / "index.md").is_file())
        self.assertEqual(runtime.validate_bundle_root(bundle)["passed"], True)
        with self.assertRaises(runtime.ReleaseError) as caught:
            approval_path = self.project / "duplicate-approval.json"
            runtime.write_json(approval_path, self.plan_approval(plan))
            runtime.compose_bundle(
                {
                    "plan_path": str(Path(plan["run_root"]) / "plan" / "release-plan.json"),
                    "plan_approval_path": str(approval_path),
                    "script_bundle_version": "v1.0.0",
                }
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_SCRIPT_VERSION_CONFLICT")

    def test_template_path_can_never_execute(self) -> None:
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.validate_bundle_root(runtime.KITS_ROOT / "templates")
        self.assertEqual(caught.exception.code, "E_V245_RE_TEMPLATE_EXECUTION_FORBIDDEN")

    def test_dangerous_project_adapter_is_rejected(self) -> None:
        dangerous = self.project / "dangerous.sh"
        dangerous.write_text("#!/bin/bash\npsql -c 'DROP TABLE users'\n", encoding="utf-8")
        dangerous.chmod(0o750)
        adapters = dict(self.adapters)
        adapters["deploy"] = {
            "path": str(dangerous),
            "sha256": digest(dangerous),
            "capabilities": ["deploy_target"],
        }
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(self.plan_request("dangerous", adapters=adapters))
        self.assertEqual(caught.exception.code, "E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION")

    def test_binary_project_adapter_is_rejected_before_planning(self) -> None:
        binary = self.project / "deploy-binary"
        binary.write_bytes(b"\x7fELF\x00\xff\x10")
        binary.chmod(0o750)
        adapters = dict(self.adapters)
        adapters["deploy"] = {
            "path": str(binary),
            "sha256": digest(binary),
            "capabilities": ["deploy_target"],
        }
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(self.plan_request("binary-adapter", adapters=adapters))
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
        )

    def test_full_test_project_adapter_is_rejected(self) -> None:
        full_test = self.project / "full-test.sh"
        full_test.write_text("#!/bin/bash\npytest\n", encoding="utf-8")
        full_test.chmod(0o750)
        adapters = dict(self.adapters)
        adapters["verify"] = {
            "path": str(full_test),
            "sha256": digest(full_test),
            "capabilities": ["post_release_verify"],
        }
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(self.plan_request("full-test-adapter", adapters=adapters))
        self.assertEqual(caught.exception.code, "E_V245_RE_FULL_TEST_EXECUTION_FORBIDDEN")

    def test_wildcard_permission_is_rejected(self) -> None:
        adapters = dict(self.adapters)
        adapters["deploy"] = dict(adapters["deploy"], capabilities=["*"])
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(self.plan_request("wildcard", adapters=adapters))
        self.assertEqual(caught.exception.code, "E_V245_RE_PERMISSION_EXCESS")

    def test_indirect_database_and_helper_adapters_are_rejected(self) -> None:
        for name, body in (
            ("database", "#!/bin/bash\npsql \"$DATABASE_URL\" -f migrations/release.sql\n"),
            ("helper", "#!/bin/bash\npython3 deploy_helper.py\n"),
        ):
            with self.subTest(name=name):
                path = self.project / f"{name}-adapter.sh"
                path.write_text(body, encoding="utf-8")
                path.chmod(0o750)
                adapters = dict(self.adapters)
                adapters["deploy"] = {
                    "path": str(path),
                    "sha256": digest(path),
                    "capabilities": ["deploy_capability"],
                }
                with self.assertRaises(runtime.ReleaseError) as caught:
                    runtime.plan_release(
                        self.plan_request(f"indirect-{name}", adapters=adapters)
                    )
                self.assertEqual(
                    caught.exception.code,
                    "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                )

    def test_dynamic_bash_cannot_assemble_database_or_destructive_tokens(self) -> None:
        attacks = {
            "command-wrapper": (
                "#!/bin/bash\n"
                "verb='DR''OP TA''BLE users'\n"
                "command psql -c \"$verb\"\n"
            ),
            "dynamic-client": (
                "#!/bin/bash\n"
                "client='ps''ql'\n"
                "verb='DR''OP TA''BLE users'\n"
                "\"$client\" -c \"$verb\"\n"
            ),
            "command-substitution": (
                "#!/bin/bash\n"
                "artifact=\"$(resolve-artifact)\"\n"
                "deployctl publish \"$artifact\"\n"
            ),
            "backslash-token-assembly": (
                "#!/bin/bash\n"
                "p\\sql -c DR\\OP\\ TA\\BLE\\ users\n"
            ),
            "quote-token-assembly": (
                "#!/bin/bash\n"
                "p'sql' -c 'DR'OP' TA'BLE' users'\n"
            ),
        }
        for name, body in attacks.items():
            with self.subTest(name=name):
                path = self.project / f"{name}-adapter.sh"
                path.write_text(body, encoding="utf-8")
                path.chmod(0o750)
                adapters = dict(self.adapters)
                adapters["deploy"] = {
                    "path": str(path),
                    "sha256": digest(path),
                    "capabilities": ["deploy_capability"],
                }
                with self.assertRaises(runtime.ReleaseError) as caught:
                    runtime.plan_release(
                        self.plan_request(f"dynamic-{name}", adapters=adapters)
                    )
                self.assertEqual(
                    caught.exception.code,
                    "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                )

    def test_env_bash_shebang_is_rejected(self) -> None:
        adapter = self.project / "env-bash-adapter.sh"
        adapter.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
            encoding="utf-8",
        )
        adapter.chmod(0o750)
        adapters = dict(self.adapters)
        adapters["deploy"] = {
            "path": str(adapter),
            "sha256": digest(adapter),
            "capabilities": ["deploy_capability"],
        }
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(
                self.plan_request("env-bash", adapters=adapters)
            )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
        )

    def test_project_local_helper_is_not_a_closed_adapter_command(self) -> None:
        helper = self.project / "reset-store"
        helper.write_text(
            "#!/bin/bash\npsql -c 'DROP TABLE users'\n",
            encoding="utf-8",
        )
        helper.chmod(0o750)
        adapter = self.project / "project-helper-adapter.sh"
        adapter.write_text(
            "#!/bin/bash\nset -euo pipefail\n./reset-store\n",
            encoding="utf-8",
        )
        adapter.chmod(0o750)
        adapters = dict(self.adapters)
        adapters["deploy"] = {
            "path": str(adapter),
            "sha256": digest(adapter),
            "capabilities": ["deploy_capability"],
        }
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(
                self.plan_request("project-helper", adapters=adapters)
            )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
        )

    def test_host_mediated_command_is_digest_bound_and_revalidated(self) -> None:
        host_command = Path("/usr/bin/true").resolve(strict=True)
        adapter = self.project / "host-mediated-adapter.sh"
        adapter.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            f"{host_command} deploy\n",
            encoding="utf-8",
        )
        adapter.chmod(0o750)
        adapters = dict(self.adapters)
        adapters["deploy"] = {
            "path": str(adapter),
            "sha256": digest(adapter),
            "capabilities": ["deploy_capability"],
            "host_commands": [
                {
                    "path": str(host_command),
                    "sha256": digest(host_command),
                    "capability": "deploy",
                    "action_id": "deploy",
                }
            ],
        }
        with mock.patch.object(
            runtime,
            "APPROVED_HOST_COMMAND_BASENAME",
            host_command.name,
        ):
            result = runtime.plan_release(
                self.plan_request("host-mediated", adapters=adapters)
            )
        self.assertEqual(result["plan"]["plan_state"], "awaiting_plan_approval")
        drifted = dict(result["plan"]["adapters"]["deploy"])
        drifted["host_commands"] = [dict(drifted["host_commands"][0])]
        drifted["host_commands"][0]["sha256"] = "0" * 64
        with mock.patch.object(
            runtime,
            "APPROVED_HOST_COMMAND_BASENAME",
            host_command.name,
        ), self.assertRaises(runtime.ReleaseError) as caught:
            runtime.validate_adapter_spec(drifted, self.project, "deploy")
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_ADAPTER_DIGEST_DRIFT",
        )

    def test_generic_root_owned_trampolines_are_not_host_commands(self) -> None:
        for executable, arguments in (
            (Path("/usr/bin/env").resolve(strict=True), "dropdb production"),
            (Path("/usr/bin/find").resolve(strict=True), "/tmp/example -delete"),
        ):
            with self.subTest(executable=str(executable)):
                adapter = self.project / f"{executable.name}-adapter.sh"
                adapter.write_text(
                    "#!/bin/bash\n"
                    "set -euo pipefail\n"
                    f"{executable} {arguments}\n",
                    encoding="utf-8",
                )
                adapter.chmod(0o750)
                adapters = dict(self.adapters)
                adapters["deploy"] = {
                    "path": str(adapter),
                    "sha256": digest(adapter),
                    "capabilities": ["deploy_capability"],
                    "host_commands": [
                        {
                            "path": str(executable),
                            "sha256": digest(executable),
                            "capability": "deploy",
                            "action_id": "deploy",
                        }
                    ],
                }
                with self.assertRaises(runtime.ReleaseError) as caught:
                    runtime.plan_release(
                        self.plan_request(
                            f"trampoline-{executable.name}",
                            adapters=adapters,
                        )
                    )
                self.assertEqual(
                    caught.exception.code,
                    "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                )

    def test_receipt_redaction_uses_shared_security_boundary(self) -> None:
        raw = (
            "Cook" + "ie: session=secret-" + "cookie\n"
            + "post" + "gresql://user:db-" + "password@example.invalid/db\n"
            + "machine example.invalid login user pass" + "word netrc-" + "password\n"
        )
        redacted = runtime.redact(raw)
        self.assertNotIn("secret-cookie", redacted)
        self.assertNotIn("db-password", redacted)
        self.assertNotIn("netrc-password", redacted)

    def test_unsigned_plan_approval_is_rejected(self) -> None:
        plan_result = runtime.plan_release(self.plan_request("unsigned-plan"))
        approval = self.plan_approval(plan_result["plan"])
        approval.pop("host_acceptance")
        approval_path = self.project / "unsigned-plan-approval.json"
        runtime.write_json(approval_path, approval)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.compose_bundle(
                {
                    "plan_path": plan_result["plan_path"],
                    "plan_approval_path": str(approval_path),
                    "script_bundle_version": "v1.0.0",
                }
            )
        self.assertEqual(
            caught.exception.code, "E_V245_RE_TRUSTED_APPROVAL_REQUIRED"
        )

    def test_production_bundle_promotes_artifact_without_prefetch_or_build(self) -> None:
        _, _, result = self.compose_ready_bundle("production-promotion")
        names = [step["filename"] for step in result["manifest"]["steps"]]
        self.assertIn("30-artifact-identity.sh", names)
        self.assertNotIn("20-prefetch-dependencies.sh", names)
        self.assertNotIn("40-build.sh", names)

    def test_local_bundle_prefetches_before_build(self) -> None:
        plan_result = runtime.plan_release(
            self.plan_request(
                "local-build",
                environment="local",
                adapters={
                    "benchmark": self.adapters["benchmark"],
                    "deploy": self.adapters["deploy"],
                    "verify": self.adapters["verify"],
                },
                gates={
                    "benchmark_baseline": {"path": str(self.project / "benchmark-baseline.json")},
                    "post_release_verification": {"path": str(self.project / "post-release.json")},
                },
            )
        )
        plan = plan_result["plan"]
        approval_path = self.project / "local-plan-approval.json"
        runtime.write_json(approval_path, self.plan_approval(plan))
        bundle = runtime.compose_bundle(
            {
                "plan_path": plan_result["plan_path"],
                "plan_approval_path": str(approval_path),
                "script_bundle_version": "v1.0.0",
            }
        )
        names = [step["filename"] for step in bundle["manifest"]["steps"]]
        self.assertLess(names.index("20-prefetch-dependencies.sh"), names.index("40-build.sh"))
        self.assertLess(names.index("40-build.sh"), names.index("45-artifact-identity.sh"))
        self.assertEqual(
            plan["toolchain_host_command"]["provenance"]["signature_status"],
            "verified",
        )
        self.assertEqual(
            {
                step["template_path"]
                for step in bundle["manifest"]["steps"]
                if step["filename"]
                in {"20-prefetch-dependencies.sh", "40-build.sh"}
            },
            {
                "templates/common/20-toolchain-prefetch.sh.tpl",
                "templates/common/40-toolchain-build.sh.tpl",
            },
        )
        self.assertIn(
            "plans/toolchain-actions-v1.json",
            {item["path"] for item in plan["selected_templates"]},
        )
        rendered_prefetch = (
            Path(bundle["bundle_root"]) / "20-prefetch-dependencies.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("GOAL_TEAMS_RELEASE_DEPENDENCY_BUNDLE", rendered_prefetch)
        self.assertIn("prefetch-java-maven-v1", rendered_prefetch)
        self.assertIn("goal-teams-toolchain-action-receipt-v2.45", rendered_prefetch)
        rendered_build = (
            Path(bundle["bundle_root"]) / "40-build.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("offline_required", rendered_build)
        self.assertIn("full_test_execution_count", rendered_build)
        self.assertIn("dependency_bundle_digest", rendered_build)

    def test_build_enabled_plan_requires_exact_toolchain_host(self) -> None:
        request = self.plan_request("missing-toolchain", environment="local")
        request.pop("toolchain_host_command")
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(caught.exception.code, "E_V245_RE_TOOLCHAIN_HOST_REQUIRED")

    def test_toolchain_host_provenance_and_actions_are_closed(self) -> None:
        request = self.plan_request("bad-toolchain-provenance", environment="local")
        request["toolchain_host_command"]["provenance"]["signature_status"] = "unchecked"
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
        )

        request = self.plan_request("bad-toolchain-manifest", environment="local")
        request["toolchain_host_command"]["provenance"]["manifest_sha256"] = "0" * 64
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
        )

        request = self.plan_request("bad-toolchain-action", environment="local")
        request["toolchain_host_command"]["build_action"] = "build-node-npm-v1"
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(caught.exception.code, "E_V245_RE_PERMISSION_EXCESS")

    def test_toolchain_provenance_requires_trusted_signer_and_signature(self) -> None:
        request = self.plan_request("self-asserted-toolchain", environment="local")
        toolchain = request["toolchain_host_command"]
        provenance = toolchain["provenance"]
        provenance["source"] = "signed-release:attacker-self-asserted"
        provenance["signer_identity"] = "attacker-self-asserted-signer"
        bindings = {
            "identity": toolchain["identity"],
            "executable_sha256": toolchain["sha256"],
            "prefetch_action": toolchain["prefetch_action"],
            "build_action": toolchain["build_action"],
            "manifest_sha256": provenance["manifest_sha256"],
            "source": provenance["source"],
            "version": provenance["version"],
            "signer_identity": provenance["signer_identity"],
        }
        provenance["host_attestation"]["bindings_sha256"] = runtime.object_digest(
            bindings
        )
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
        )

    def test_toolchain_host_in_user_owned_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.project.parent) as outside:
            hardlink = Path(outside) / "true"
            hardlink.write_bytes(self.toolchain_host_path.read_bytes())
            hardlink.chmod(0o755)
            self.assertNotEqual(hardlink.parent.stat().st_uid, 0)
            request = self.plan_request(
                "untrusted-toolchain-parent",
                environment="local",
            )
            request["toolchain_host_command"]["path"] = str(hardlink)
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.plan_release(request)
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_TOOLCHAIN_HOST_UNTRUSTED",
        )
        self.assertEqual(caught.exception.path, str(hardlink.parent))

        request = self.plan_request("bad-toolchain-signature", environment="local")
        with mock.patch.object(runtime.ED25519_VERIFY, "verify", return_value=False):
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.plan_release(request)
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
        )

    def test_non_build_environment_rejects_toolchain_authority(self) -> None:
        request = self.plan_request("production-toolchain")
        request["toolchain_host_command"] = self.toolchain_host_command(
            "java",
            "maven",
        )
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(caught.exception.code, "E_V245_RE_PERMISSION_EXCESS")

    def test_environment_evidence_must_match_target(self) -> None:
        request = self.plan_request("environment-mismatch")
        request["environment"] = "test"
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(request)
        self.assertEqual(caught.exception.code, "E_V245_RE_ENVIRONMENT_BINDING_INVALID")

    def test_existing_bundle_discovery_requires_clarification(self) -> None:
        _, _, bundle = self.compose_ready_bundle("discover-existing")
        report = runtime.discover_scripts(
            {"project_root": str(self.project), "release_root": str(self.release_root)}
        )
        self.assertTrue(report["clarification_required"])
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(
            report["candidates"][0]["script_bundle_digest"],
            bundle["script_bundle_digest"],
        )
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(
                self.plan_request(
                    "discovery-blocked",
                    existing_script_decision=None,
                )
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_SCRIPT_REUSE_CONFIRMATION_REQUIRED")

    def test_unmanaged_local_script_requires_explicit_decision(self) -> None:
        old_script = self.release_root / "legacy-release"
        old_script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        old_script.chmod(0o750)
        report = runtime.discover_scripts(
            {"project_root": str(self.project), "release_root": str(self.release_root)}
        )
        self.assertTrue(report["clarification_required"])
        self.assertEqual(report["unmanaged_scripts"][0]["path"], str(old_script))
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.plan_release(
                self.plan_request(
                    "unmanaged-script",
                    existing_script_decision=None,
                )
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_SCRIPT_REUSE_CONFIRMATION_REQUIRED")

    def test_extensionless_symlink_is_always_unsafe(self) -> None:
        target = self.release_root / "managed-elsewhere.sh"
        target.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        link = self.release_root / "deploy-current"
        link.symlink_to(target.name)
        report = runtime.discover_scripts(
            {"project_root": str(self.project), "release_root": str(self.release_root)}
        )
        findings = {item["path"]: item["state"] for item in report["unmanaged_scripts"]}
        self.assertEqual(findings[str(link)], "unsafe_symlink")
        self.assertTrue(report["clarification_required"])

    def test_every_language_build_tool_combination_composes(self) -> None:
        pairs = (
            ("java", "maven", "java-maven-v1"),
            ("java", "gradle", "java-gradle-v1"),
            ("rust", "cargo", "rust-cargo-v1"),
            ("go", "go-modules", "go-modules-v1"),
            ("python", "pip", "python-pip-v1"),
            ("python", "uv", "python-uv-v1"),
            ("python", "poetry", "python-poetry-v1"),
            ("node", "npm", "node-npm-v1"),
            ("node", "pnpm", "node-pnpm-v1"),
            ("node", "yarn", "node-yarn-v1"),
        )
        for index, (language, build_tool, expected_kit_id) in enumerate(pairs):
            with self.subTest(language=language, build_tool=build_tool):
                run_id = f"matrix-{index}"
                plan_result = runtime.plan_release(
                    self.plan_request(
                        run_id,
                        language=language,
                        build_tool=build_tool,
                        environment="local",
                        adapters={
                            "benchmark": self.adapters["benchmark"],
                            "deploy": self.adapters["deploy"],
                            "verify": self.adapters["verify"],
                        },
                        gates={
                            "benchmark_baseline": {"path": str(self.project / f"benchmark-{index}.json")},
                            "post_release_verification": {"path": str(self.project / f"post-release-{index}.json")},
                        },
                    )
                )
                plan = plan_result["plan"]
                approval_path = self.project / f"{run_id}-plan-approval.json"
                runtime.write_json(approval_path, self.plan_approval(plan))
                bundle = runtime.compose_bundle(
                    {
                        "plan_path": plan_result["plan_path"],
                        "plan_approval_path": str(approval_path),
                        "script_bundle_version": "v1.0.0",
                    }
                )
                self.assertEqual(bundle["manifest"]["language_kit_id"], expected_kit_id)


class ExecutionTests(ReleaseMemberFixture):
    def write_toolchain_action_receipts(
        self,
        plan: dict,
        *,
        execution_id: str = "execution-1",
    ) -> tuple[Path, Path]:
        receipt_root = Path(plan["run_root"]) / "toolchain-receipts"
        receipt_root.mkdir(mode=0o700, exist_ok=True)
        toolchain = plan["toolchain_host_command"]
        manifest_sha256 = digest(
            runtime.catalog_path("plans/toolchain-actions-v1.json")
        )
        dependency_digest = "8" * 64

        def signed(payload: dict, challenge: str) -> dict:
            payload = dict(payload)
            payload["host_attestation"] = {
                "schema_version": "goal-teams-toolchain-action-receipt-attestation-v2.45",
                "algorithm": "Ed25519",
                "issuer": "goal-teams-trusted-host",
                "key_id": runtime.TRUSTED_APPROVAL_KEY_ID,
                "bindings_sha256": runtime.object_digest(payload),
                "issued_at": runtime.now_utc(),
                "challenge_id": challenge,
                "signa" + "ture": "00" * 64,
            }
            return payload

        common = {
            "schema_version": "goal-teams-toolchain-action-receipt-v2.45",
            "status": "passed",
            "execution_id": execution_id,
            "plan_digest": plan["plan_digest"],
            "host_executable_sha256": toolchain["sha256"],
            "action_manifest_sha256": manifest_sha256,
            "full_test_execution_count": 0,
            "dependency_bundle_digest": dependency_digest,
            "observed_at": runtime.now_utc(),
        }
        prefetch = signed(
            {
                **common,
                "action_id": toolchain["prefetch_action"],
                "network_policy": "prefetch_only",
            },
            "toolchain-prefetch-receipt",
        )
        build = signed(
            {
                **common,
                "action_id": toolchain["build_action"],
                "network_policy": "offline_required",
                "artifact_digest": plan["candidate"]["artifact_digest"],
            },
            "toolchain-build-receipt",
        )
        prefetch_path = receipt_root / f"{toolchain['prefetch_action']}.json"
        build_path = receipt_root / f"{toolchain['build_action']}.json"
        runtime.write_json(prefetch_path, prefetch)
        runtime.write_json(build_path, build)
        return prefetch_path, build_path

    def write_bound_gate_receipts(
        self,
        plan: dict,
        *,
        surface_state: str,
        surface_readback: dict,
        execution_id: str = "execution-1",
        operation: str = "release",
    ) -> None:
        for gate_name, filename in (
            ("backup_receipt", "backup-receipt.json"),
            ("benchmark_baseline", "benchmark-baseline.json"),
            ("post_release_verification", "post-release.json"),
        ):
            path = self.project / filename
            payload = {
                "schema_version": "goal-teams-release-gate-receipt-v2.45",
                "gate": gate_name,
                "status": "passed",
                "execution_id": execution_id,
                "operation": operation,
                "target_environment": plan["environment_kit"]["name"],
                "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
                "environment_document_digest": plan["environment_documents"]["target_document_digest"],
                "observed_at": runtime.now_utc(),
                "assertions": [{"name": f"{gate_name}-verified", "passed": True}],
            }
            if gate_name == "backup_receipt":
                payload["backup_scope_digest"] = self.backup_scope_digest
            if gate_name == "post_release_verification":
                payload["surface_state"] = surface_state
                payload["surface_readback"] = surface_readback
            if gate_name == "benchmark_baseline":
                payload["baseline_data_digest"] = "5" * 64
            runtime.write_json(path, payload)

    def test_dry_run_has_zero_external_writes(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle()
        manifest = bundle["manifest"]
        approval = self.execution_approval(plan, manifest)
        approval_path = self.project / "execution-approval.json"
        runtime.write_json(approval_path, approval)
        with mock.patch.object(runtime.subprocess, "run") as subprocess_run:
            result = runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                    "mode": "dry-run",
                }
            )
        subprocess_run.assert_not_called()
        self.assertEqual(result["result"]["external_write_count"], 0)
        self.assertEqual(result["result"]["execution_state"], "dry_run_validated")

    def test_script_drift_invalidates_execution_before_subprocess(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle()
        approval = self.execution_approval(plan, bundle["manifest"])
        approval_path = self.project / "execution-approval.json"
        runtime.write_json(approval_path, approval)
        deploy = Path(bundle["bundle_root"]) / "70-deploy.sh"
        deploy.write_text(deploy.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
        with mock.patch.object(runtime.subprocess, "run") as subprocess_run:
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": str(plan_path),
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        subprocess_run.assert_not_called()
        self.assertEqual(caught.exception.code, "E_V245_RE_SCRIPT_DIGEST_DRIFT")

    def test_execution_approval_target_drift_is_rejected(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle()
        approval = self.execution_approval(plan, bundle["manifest"])
        approval["target_environment"] = "staging"
        approval_path = self.project / "execution-approval.json"
        runtime.write_json(approval_path, approval)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                }
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_EXEC_APPROVAL_STALE")

    def test_execution_approval_cannot_escalate_dry_run_to_live(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("mode-binding")
        approval = self.execution_approval(plan, bundle["manifest"], mode="dry-run")
        approval_path = self.project / "mode-binding-execution-approval.json"
        runtime.write_json(approval_path, approval)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                    "mode": "live",
                }
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_EXEC_APPROVAL_STALE")

    def test_execution_approval_cannot_change_release_to_rollback(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("operation-binding")
        approval = self.execution_approval(
            plan,
            bundle["manifest"],
            mode="dry-run",
            operation="release",
        )
        approval_path = self.project / "operation-binding-execution-approval.json"
        runtime.write_json(approval_path, approval)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                    "mode": "dry-run",
                    "operation": "rollback",
                }
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_EXEC_APPROVAL_STALE")

    def test_execution_id_is_covered_by_trusted_host_binding(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("execution-id-binding")
        approval = self.execution_approval(plan, bundle["manifest"])
        approval["execution_id"] = "execution-forged"
        approval_path = self.project / "execution-id-binding-approval.json"
        runtime.write_json(approval_path, approval)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                }
            )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_TRUSTED_APPROVAL_INVALID",
        )

    def test_execution_approval_cannot_be_replayed(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("no-replay")
        approval = self.execution_approval(plan, bundle["manifest"])
        approval_path = self.project / "replay-execution-approval.json"
        runtime.write_json(approval_path, approval)
        request = {
            "bundle_root": bundle["bundle_root"],
            "plan_path": str(plan_path),
            "execution_approval_path": str(approval_path),
            "mode": "dry-run",
        }
        runtime.execute_bundle(request)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.execute_bundle(request)
        self.assertEqual(caught.exception.code, "E_V245_RE_EXEC_APPROVAL_REPLAY")

    def test_bundle_must_bind_exact_plan(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("bundle-binding")
        manifest_path = Path(bundle["bundle_root"]) / "script-bundle-manifest.json"
        manifest = runtime.load_json(manifest_path)
        manifest["target_environment"] = "staging"
        manifest["script_bundle_digest"] = runtime.object_digest(
            {key: value for key, value in manifest.items() if key != "script_bundle_digest"}
        )
        runtime.write_json(manifest_path, manifest)
        approval = self.execution_approval(plan, manifest)
        approval_path = self.project / "binding-execution-approval.json"
        runtime.write_json(approval_path, approval)
        with self.assertRaises(runtime.ReleaseError) as caught:
            runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                    "mode": "dry-run",
                }
            )
        self.assertEqual(caught.exception.code, "E_V245_RE_SCRIPT_DIGEST_DRIFT")

    def test_restore_proof_drift_blocks_before_subprocess(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("restore-drift")
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "restore-execution-approval.json"
        runtime.write_json(approval_path, approval)
        self.restore_proof.write_text('{"status":"stale"}\n', encoding="utf-8")
        with mock.patch.object(runtime.subprocess, "run") as subprocess_run:
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": str(plan_path),
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        subprocess_run.assert_not_called()
        self.assertEqual(caught.exception.code, "E_V245_RE_BACKUP_RESTORE_UNVERIFIED")

    def test_environment_document_drift_blocks_before_subprocess(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("environment-drift")
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "environment-execution-approval.json"
        runtime.write_json(approval_path, approval)
        self.environments["staging"].write_text("# drift\n", encoding="utf-8")
        with mock.patch.object(runtime.subprocess, "run") as subprocess_run:
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": str(plan_path),
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        subprocess_run.assert_not_called()
        self.assertEqual(caught.exception.code, "E_V245_RE_ENVIRONMENT_BINDING_INVALID")

    def test_live_release_requires_and_records_bound_gate_receipts(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("live-gates")
        self.write_bound_gate_receipts(
            plan,
            surface_state="verified",
            surface_readback={
                "artifact_digest": plan["candidate"]["artifact_digest"],
                "configuration_identity": "cfg-v1",
                "external_health": "passed",
                "business_invariants": "passed",
            },
        )
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "live-gates-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            result = runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                    "mode": "live",
                }
            )
        self.assertEqual(result["result"]["execution_state"], "completed")
        self.assertEqual(len(result["result"]["gate_receipts"]), 3)
        self.assertEqual(result["result"]["independent_validation_state"], "pending")

    def test_gate_receipt_from_an_old_execution_window_is_rejected(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("stale-gate")
        self.write_bound_gate_receipts(
            plan,
            surface_state="verified",
            surface_readback={
                "artifact_digest": plan["candidate"]["artifact_digest"],
                "configuration_identity": "cfg-v1",
                "external_health": "passed",
                "business_invariants": "passed",
            },
        )
        backup_path = self.project / "backup-receipt.json"
        backup = runtime.load_json(backup_path)
        backup["observed_at"] = "2020-01-01T00:00:00Z"
        runtime.write_json(backup_path, backup)
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "stale-gate-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": str(plan_path),
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        self.assertEqual(caught.exception.code, "E_V245_RE_GATE_BINDING_INVALID")

    def test_failed_application_health_cannot_pass_post_release_review(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("failed-health")
        self.write_bound_gate_receipts(
            plan,
            surface_state="verified",
            surface_readback={
                "artifact_digest": plan["candidate"]["artifact_digest"],
                "configuration_identity": "cfg-v1",
                "external_health": "failed",
                "business_invariants": "passed",
            },
        )
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "failed-health-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": str(plan_path),
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_PLATFORM_READBACK_PENDING",
        )

    def test_rollback_verifies_the_previous_good_identity(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("rollback-identity")
        self.write_bound_gate_receipts(
            plan,
            execution_id="execution-rollback",
            operation="rollback",
            surface_state="verified",
            surface_readback={
                "artifact_digest": plan["rollback_identity"]["artifact_digest"],
                "configuration_identity": plan["rollback_identity"][
                    "configuration_identity"
                ],
                "external_health": "passed",
                "business_invariants": "passed",
            },
        )
        approval = self.execution_approval(
            plan,
            bundle["manifest"],
            mode="live",
            operation="rollback",
            execution_id="execution-rollback",
        )
        approval_path = self.project / "rollback-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            result = runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": str(plan_path),
                    "execution_approval_path": str(approval_path),
                    "mode": "live",
                    "operation": "rollback",
                }
            )
        self.assertEqual(result["result"]["operation"], "rollback")
        self.assertEqual(
            [receipt["step"] for receipt in result["result"]["receipts"]],
            ["90-rollback.sh", "80-post-release-verify.sh"],
        )

    def test_local_live_build_includes_approved_artifact_identity_step(self) -> None:
        plan_result = runtime.plan_release(
            self.plan_request(
                "local-live",
                environment="local",
                adapters={
                    "benchmark": self.adapters["benchmark"],
                    "deploy": self.adapters["deploy"],
                    "verify": self.adapters["verify"],
                },
                gates={
                    "benchmark_baseline": {"path": str(self.project / "benchmark-baseline.json")},
                    "post_release_verification": {"path": str(self.project / "post-release.json")},
                },
            )
        )
        plan = plan_result["plan"]
        plan_approval_path = self.project / "local-live-plan-approval.json"
        runtime.write_json(plan_approval_path, self.plan_approval(plan))
        bundle = runtime.compose_bundle(
            {
                "plan_path": plan_result["plan_path"],
                "plan_approval_path": str(plan_approval_path),
                "script_bundle_version": "v1.0.0",
            }
        )
        self.write_toolchain_action_receipts(plan)
        self.write_bound_gate_receipts(
            plan,
            surface_state="verified",
            surface_readback={
                "artifact_digest": plan["candidate"]["artifact_digest"],
                "configuration_identity": plan["surface_identity"]["configuration_identity"],
                "external_health": "passed",
                "business_invariants": "passed",
            },
        )
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "local-live-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            result = runtime.execute_bundle(
                {
                    "bundle_root": bundle["bundle_root"],
                    "plan_path": plan_result["plan_path"],
                    "execution_approval_path": str(approval_path),
                    "mode": "live",
                }
            )
        self.assertEqual(result["result"]["execution_state"], "completed")
        self.assertIn(
            "45-artifact-identity.sh",
            [receipt["step"] for receipt in result["result"]["receipts"]],
        )
        self.assertEqual(
            [item["phase"] for item in result["result"]["toolchain_action_receipts"]],
            ["prefetch", "build"],
        )

    def test_toolchain_action_receipt_requires_host_signature(self) -> None:
        plan_result = runtime.plan_release(
            self.plan_request("receipt-signature", environment="local")
        )
        plan = plan_result["plan"]
        self.write_toolchain_action_receipts(plan)
        with mock.patch.object(runtime.ED25519_VERIFY, "verify", return_value=False):
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.validate_toolchain_action_receipt(
                    plan,
                    execution_id="execution-1",
                    phase="prefetch",
                )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
        )

    def test_wechat_review_pending_never_completes(self) -> None:
        plan_result = runtime.plan_release(
            self.plan_request("wechat-pending", surface="wechat-miniprogram")
        )
        plan = plan_result["plan"]
        plan_approval_path = self.project / "wechat-pending-plan-approval.json"
        runtime.write_json(plan_approval_path, self.plan_approval(plan))
        bundle = runtime.compose_bundle(
            {
                "plan_path": plan_result["plan_path"],
                "plan_approval_path": str(plan_approval_path),
                "script_bundle_version": "v1.0.0",
            }
        )
        self.write_bound_gate_receipts(
            plan,
            surface_state="review_pending",
            surface_readback={
                "appid": "wx-app",
                "robot": "1",
                "upload_receipt": "upload-1",
                "review_id": "review-1",
                "review_status": "pending",
                "online_version": "not_available",
            },
        )
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "wechat-pending-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": plan_result["plan_path"],
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        self.assertEqual(caught.exception.code, "E_V245_RE_PLATFORM_READBACK_PENDING")

    def test_wechat_online_version_must_match_approved_identity(self) -> None:
        plan_result = runtime.plan_release(
            self.plan_request("wechat-version-drift", surface="wechat-miniprogram")
        )
        plan = plan_result["plan"]
        plan_approval_path = self.project / "wechat-version-plan-approval.json"
        runtime.write_json(plan_approval_path, self.plan_approval(plan))
        bundle = runtime.compose_bundle(
            {
                "plan_path": plan_result["plan_path"],
                "plan_approval_path": str(plan_approval_path),
                "script_bundle_version": "v1.0.0",
            }
        )
        self.write_bound_gate_receipts(
            plan,
            surface_state="online_version_readback",
            surface_readback={
                "appid": plan["surface_identity"]["appid"],
                "robot": "1",
                "upload_receipt": "upload-1",
                "review_id": "review-1",
                "review_status": "passed",
                "online_version": "different-version",
            },
        )
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "wechat-version-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": plan_result["plan_path"],
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        self.assertEqual(caught.exception.code, "E_V245_RE_PLATFORM_READBACK_PENDING")

    def test_github_requires_redownload_and_installed_identity(self) -> None:
        plan_result = runtime.plan_release(
            self.plan_request("github-readback", surface="github-skill")
        )
        plan = plan_result["plan"]
        plan_approval_path = self.project / "github-plan-approval.json"
        runtime.write_json(plan_approval_path, self.plan_approval(plan))
        bundle = runtime.compose_bundle(
            {
                "plan_path": plan_result["plan_path"],
                "plan_approval_path": str(plan_approval_path),
                "script_bundle_version": "v1.0.0",
            }
        )
        self.write_bound_gate_receipts(
            plan,
            surface_state="installed_identity_verified",
            surface_readback={
                "tag_commit": plan["candidate"]["source_commit"],
                "repository": plan["surface_identity"]["repository"],
                "tag": plan["surface_identity"]["tag"],
                "release_id": "release-1",
                "asset_digest": plan["candidate"]["artifact_digest"],
                "download_digest": plan["candidate"]["artifact_digest"],
                "installed_tree_digest": "f" * 64,
            },
        )
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "github-execution-approval.json"
        runtime.write_json(approval_path, approval)
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": plan_result["plan_path"],
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        self.assertEqual(caught.exception.code, "E_V245_RE_GATE_BINDING_INVALID")

    def test_plan_approval_drift_blocks_execution_before_subprocess(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("plan-approval-drift")
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "plan-drift-execution-approval.json"
        runtime.write_json(approval_path, approval)
        stored_plan_approval = Path(bundle["manifest"]["plan_approval_path"])
        stored_plan_approval.write_text(stored_plan_approval.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with mock.patch.object(runtime.subprocess, "run") as subprocess_run:
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": str(plan_path),
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        subprocess_run.assert_not_called()
        self.assertEqual(caught.exception.code, "E_V245_RE_PLAN_APPROVAL_STALE")

    def test_safe_step_loops_to_max_attempts_without_external_write(self) -> None:
        plan, plan_path, bundle = self.compose_ready_bundle("loop-safe")
        approval = self.execution_approval(plan, bundle["manifest"], mode="live")
        approval_path = self.project / "loop-execution-approval.json"
        runtime.write_json(approval_path, approval)
        failed = mock.Mock(returncode=7, stdout="", stderr="transient")
        with mock.patch.object(runtime.subprocess, "run", return_value=failed) as subprocess_run:
            with self.assertRaises(runtime.ReleaseError) as caught:
                runtime.execute_bundle(
                    {
                        "bundle_root": bundle["bundle_root"],
                        "plan_path": str(plan_path),
                        "execution_approval_path": str(approval_path),
                        "mode": "live",
                    }
                )
        self.assertEqual(caught.exception.code, "E_V245_RE_LOOP_MAX_ATTEMPTS")
        self.assertEqual(subprocess_run.call_count, 3)
        loop_state = runtime.load_json(Path(plan["run_root"]) / "loop" / "loop-state.json")
        self.assertEqual(loop_state["run_outcome"], "blocked")
        self.assertEqual(loop_state["stop_reason"], "max_attempts")


class ExecutionInterpreterTests(unittest.TestCase):
    def merged_usr_stat(self, owner_uid: int):
        return mock.Mock(
            st_mode=runtime.stat.S_IFLNK | 0o777,
            st_uid=owner_uid,
        )

    def test_current_host_interpreter_is_frozen_with_resolved_identity(self) -> None:
        binding = runtime.validate_execution_interpreter()
        self.assertEqual(binding["path"], "/bin/bash")
        self.assertEqual(
            binding["resolved_path"],
            str(Path("/bin/bash").resolve(strict=True)),
        )
        self.assertIn(binding["layout"], {"canonical", "merged_usr"})
        self.assertEqual(runtime.validate_execution_interpreter(binding), binding)

    def test_standard_root_owned_merged_usr_alias_is_permitted(self) -> None:
        with mock.patch.object(Path, "is_symlink", return_value=False):
            with mock.patch.object(Path, "lstat", return_value=self.merged_usr_stat(0)):
                with mock.patch.object(runtime.os, "readlink", return_value="usr/bin"):
                    layout = runtime.validate_execution_interpreter_layout(
                        Path("/bin/bash"),
                        Path("/usr/bin/bash"),
                    )
        self.assertEqual(layout, "merged_usr")

    def test_merged_usr_alias_rejects_arbitrary_target(self) -> None:
        with mock.patch.object(Path, "is_symlink", return_value=False):
            with mock.patch.object(Path, "lstat", return_value=self.merged_usr_stat(0)):
                with mock.patch.object(runtime.os, "readlink", return_value="/opt/bin"):
                    with self.assertRaises(runtime.ReleaseError) as caught:
                        runtime.validate_execution_interpreter_layout(
                            Path("/bin/bash"),
                            Path("/usr/bin/bash"),
                        )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
        )

    def test_merged_usr_alias_rejects_non_root_owner(self) -> None:
        with mock.patch.object(Path, "is_symlink", return_value=False):
            with mock.patch.object(Path, "lstat", return_value=self.merged_usr_stat(501)):
                with mock.patch.object(runtime.os, "readlink", return_value="/usr/bin"):
                    with self.assertRaises(runtime.ReleaseError) as caught:
                        runtime.validate_execution_interpreter_layout(
                            Path("/bin/bash"),
                            Path("/usr/bin/bash"),
                        )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
        )

    def test_merged_usr_alias_rejects_unexpected_resolved_executable(self) -> None:
        with mock.patch.object(Path, "is_symlink", return_value=False):
            with mock.patch.object(Path, "lstat", return_value=self.merged_usr_stat(0)):
                with mock.patch.object(runtime.os, "readlink", return_value="/usr/bin"):
                    with self.assertRaises(runtime.ReleaseError) as caught:
                        runtime.validate_execution_interpreter_layout(
                            Path("/bin/bash"),
                            Path("/usr/local/bin/bash"),
                        )
        self.assertEqual(
            caught.exception.code,
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
        )


class CatalogTests(unittest.TestCase):
    def test_all_requested_language_environment_and_surface_kits_exist(self) -> None:
        catalog = runtime.load_catalog()
        pairs = {
            (item["language"], item["build_tool"])
            for item in catalog["language_adapters"]
        }
        self.assertEqual(
            pairs,
            {
                ("java", "maven"),
                ("java", "gradle"),
                ("rust", "cargo"),
                ("go", "go-modules"),
                ("python", "pip"),
                ("python", "uv"),
                ("python", "poetry"),
                ("node", "npm"),
                ("node", "pnpm"),
                ("node", "yarn"),
            },
        )
        self.assertEqual(
            {item["name"] for item in catalog["environments"]},
            {"local", "development", "test", "staging", "production"},
        )
        self.assertEqual(
            {item["name"] for item in catalog["surfaces"]},
            {"application", "container-kubernetes", "wechat-miniprogram", "github-skill"},
        )
        self.assertEqual(
            set(catalog["toolchain_host_command"]["action_ids"]),
            {
                action
                for item in catalog["language_adapters"]
                for action in (item["prefetch_action"], item["build_action"])
            },
        )

    def test_surface_recipes_keep_async_and_readback_states_separate(self) -> None:
        catalog = runtime.load_catalog()
        surfaces = {item["name"]: item for item in catalog["surfaces"]}
        wechat = runtime.load_kit_json(surfaces["wechat-miniprogram"]["plan"])
        github = runtime.load_kit_json(surfaces["github-skill"]["plan"])
        self.assertTrue(wechat["async_external"])
        self.assertIn("review_pending", wechat["states"])
        self.assertIn("online_version_readback", wechat["states"])
        self.assertIn("asset_redownloaded", github["states"])
        self.assertIn("installed_identity_verified", github["states"])


if __name__ == "__main__":
    unittest.main()
