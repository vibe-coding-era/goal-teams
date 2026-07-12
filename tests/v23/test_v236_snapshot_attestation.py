"""V2.36 protected tree snapshot and host-attestation negative coverage."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.v23 import v236_trust as trust


TOOL = Path(__file__).resolve().parents[2] / "scripts" / "v23" / "goalteams_v23.py"


def _run(root: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *argv],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _rehash_receipt(receipt: dict) -> None:
    receipt["change_manifest_sha256"] = hashlib.sha256(
        _canonical(receipt["change_manifest"])
    ).hexdigest()
    receipt["receipt_sha256"] = hashlib.sha256(
        _canonical({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    ).hexdigest()


class GitFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        _run(root, "init", "-q")
        _run(root, "config", "user.email", "v236@example.invalid")
        _run(root, "config", "user.name", "V236 Test")

    def commit(self, message: str = "baseline") -> str:
        _run(self.root, "add", "-A")
        _run(self.root, "commit", "-qm", message)
        return _run(self.root, "rev-parse", "HEAD").stdout.decode().strip()

    def object_state(self) -> tuple[int, str]:
        object_root = Path(
            _run(self.root, "rev-parse", "--git-path", "objects").stdout.decode().strip()
        )
        if not object_root.is_absolute():
            object_root = self.root / object_root
        rows: list[dict] = []
        for path in sorted(item for item in object_root.rglob("*") if item.is_file()):
            metadata = path.stat()
            rows.append(
                {
                    "path": path.relative_to(object_root).as_posix(),
                    "size": metadata.st_size,
                    "mtime_ns": metadata.st_mtime_ns,
                    "mode": stat.S_IMODE(metadata.st_mode),
                }
            )
        return len(rows), hashlib.sha256(_canonical(rows)).hexdigest()

    def protected_state(self) -> dict:
        index_path = Path(
            _run(self.root, "rev-parse", "--git-path", "index").stdout.decode().strip()
        )
        if not index_path.is_absolute():
            index_path = self.root / index_path
        return {
            "head": _run(self.root, "rev-parse", "HEAD").stdout,
            "refs": _run(
                self.root, "for-each-ref", "--format=%(refname)%00%(objectname)"
            ).stdout,
            "index": index_path.read_bytes(),
            "status": _run(self.root, "status", "--porcelain=v1", "-z").stdout,
            "objects": self.object_state(),
        }


class ProtectedGitTreeSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.fixture = GitFixture(self.root)
        _write(self.root / ".gitignore", "ignored.tmp\n")
        _write(self.root / "modified.txt", "before\n")
        _write(self.root / "deleted.txt", "delete me\n")
        _write(self.root / "stable.txt", "stable\n")
        self.baseline = self.fixture.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _dirty(self) -> None:
        _write(self.root / "modified.txt", "after\n")
        (self.root / "deleted.txt").unlink()
        _write(self.root / "new.txt", "untracked\n")
        _write(self.root / "ignored.tmp", "not part of snapshot\n")

    def test_snapshot_covers_modified_deleted_and_untracked_without_repo_mutation(self) -> None:
        self._dirty()
        before = self.fixture.protected_state()
        receipt_path = Path(self.temporary.name) / "receipt.json"
        result = trust.create_protected_git_tree_snapshot(
            self.root,
            receipt_path=receipt_path,
            now=datetime(2026, 7, 12, 3, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(result["ok"], result)
        receipt = result["receipt"]
        changes = {entry["path"]: entry["change_type"] for entry in receipt["change_manifest"]}
        self.assertEqual(
            changes,
            {"deleted.txt": "deleted", "modified.txt": "modified", "new.txt": "added"},
        )
        self.assertEqual(receipt["untracked_paths"], ["new.txt"])
        self.assertNotIn("ignored.tmp", receipt["changed_paths"])
        self.assertEqual(before, self.fixture.protected_state())
        self.assertEqual(
            receipt["repo_state_before"]["objects"],
            receipt["repo_state_after"]["objects"],
        )
        self.assertEqual(
            receipt["repo_state_before"]["objects"]["file_count"], before["objects"][0]
        )
        # The isolated tree is deliberately unreachable from the repository.
        self.assertNotEqual(
            _run(self.root, "cat-file", "-e", receipt["snapshot_tree"], check=False).returncode,
            0,
        )
        self.assertTrue(receipt_path.is_file())
        validated = trust.validate_protected_git_tree_snapshot(self.root, receipt)
        self.assertTrue(validated["ok"], validated)
        self.assertEqual(before, self.fixture.protected_state())

    def test_snapshot_validation_rejects_a_rehashed_manifest_omission(self) -> None:
        self._dirty()
        result = trust.create_protected_git_tree_snapshot(self.root)
        self.assertTrue(result["ok"], result)
        forged = copy.deepcopy(result["receipt"])
        forged["change_manifest"] = forged["change_manifest"][:-1]
        forged["changed_paths"] = [entry["path"] for entry in forged["change_manifest"]]
        _rehash_receipt(forged)
        validated = trust.validate_protected_git_tree_snapshot(self.root, forged)
        self.assertFalse(validated["ok"], validated)
        self.assertEqual(validated["error_code"], "E_V236_SNAPSHOT_INCOMPLETE")

    def test_empty_delta_is_not_a_release_snapshot(self) -> None:
        before = self.fixture.protected_state()
        result = trust.create_protected_git_tree_snapshot(self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V236_SNAPSHOT_EMPTY_DELTA")
        self.assertEqual(before, self.fixture.protected_state())

    def test_non_ancestor_baseline_fails_closed(self) -> None:
        baseline_branch = _run(self.root, "symbolic-ref", "--short", "HEAD").stdout.decode().strip()
        _run(self.root, "checkout", "--orphan", "unrelated")
        for path in list(self.root.iterdir()):
            if path.name != ".git":
                if path.is_dir():
                    raise AssertionError("unexpected directory in fixture")
                path.unlink()
        _write(self.root / "unrelated.txt", "unrelated\n")
        unrelated = self.fixture.commit("unrelated")
        _run(self.root, "checkout", "-q", baseline_branch)
        _write(self.root / "new.txt", "delta\n")
        result = trust.create_protected_git_tree_snapshot(self.root, baseline=unrelated)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V236_SNAPSHOT_BASELINE_NOT_ANCESTOR")

    def test_symlink_submodule_and_unsafe_path_are_rejected(self) -> None:
        cases = []
        os.symlink("stable.txt", self.root / "link.txt")
        cases.append(("symlink", "E_V236_SNAPSHOT_SYMLINK"))
        for name, expected in cases:
            with self.subTest(name=name):
                result = trust.create_protected_git_tree_snapshot(self.root)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error_code"], expected)
        (self.root / "link.txt").unlink()

        _run(
            self.root,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{self.baseline},submodule",
        )
        result = trust.create_protected_git_tree_snapshot(self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V236_SNAPSHOT_SUBMODULE")
        _run(self.root, "update-index", "--force-remove", "submodule")

        _write(self.root / "bad\nname.txt", "unsafe\n")
        result = trust.create_protected_git_tree_snapshot(self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V236_SNAPSHOT_UNSAFE_PATH")


class HostAttestationTests(unittest.TestCase):
    KEY = b"V2.36-host-trust-key-material!!!"  # 32 bytes, never stored in a registry.
    WRONG_KEY = b"untrusted-host-key-material-0000"
    ISSUER = "codex-host-primary"
    NOW = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)

    @staticmethod
    def identity(number: int) -> dict:
        return {
            "agent_type": "goal_backend" if number == 1 else "goal_reviewer",
            "agent_run_id": f"RUN-V236-{number}",
            "member_id": f"member-{number}",
            "display_name": f"Member {number}",
            "transport_handle": f"agent-{number}",
        }

    def test_snapshot_cli_creates_and_validates_complete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            fixture = GitFixture(root)
            _write(root / "tracked.txt", "before\n")
            fixture.commit()
            _write(root / "tracked.txt", "after\n")
            _write(root / "untracked.txt", "new\n")
            receipt = Path(directory) / "snapshot.json"
            created = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    "v236-snapshot-create",
                    str(root),
                    "--receipt",
                    str(receipt),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
            payload = json.loads(created.stdout)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["snapshot"]["mutation_count"], 1)
            self.assertEqual(
                set(payload["snapshot"]["receipt"]["changed_paths"]),
                {"tracked.txt", "untracked.txt"},
            )
            validated = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    "v236-snapshot-validate",
                    str(root),
                    str(receipt),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
            )
            self.assertEqual(validated.returncode, 0, validated.stderr + validated.stdout)
            self.assertTrue(json.loads(validated.stdout)["ok"])

    def test_attested_identity_cli_fails_without_host_key_and_hides_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            key = b"V2.36-host-trust-key-material!!!"
            identity = HostAttestationTests.identity(1)
            issued = trust.issue_agent_host_attestation(
                identity,
                trust_key=key,
                issuer=HostAttestationTests.ISSUER,
                nonce="cli-nonce-1",
                issued_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                ttl_seconds=300,
            )
            self.assertTrue(issued["ok"], issued)
            identity["host_attestation"] = issued["attestation"]
            path.write_text(
                json.dumps(
                    {
                        "schema_version": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
                        "identities": [identity],
                    }
                ),
                encoding="utf-8",
            )
            argv = [
                sys.executable,
                str(TOOL),
                "v236-validate-attested-identities",
                str(path),
                "--expected-issuer",
                HostAttestationTests.ISSUER,
                "--trust-key-env",
                "V236_TEST_HOST_KEY",
            ]
            missing = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
                env={key: value for key, value in os.environ.items() if key != "V236_TEST_HOST_KEY"},
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(json.loads(missing.stdout)["error_code"], "E_V236_TRUST_KEY")
            environment = dict(os.environ)
            environment["V236_TEST_HOST_KEY"] = key.decode("ascii")
            valid = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
                env=environment,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr + valid.stdout)
            combined = valid.stdout + valid.stderr
            self.assertNotIn(key.decode("ascii"), combined)
            result = json.loads(valid.stdout)
            self.assertEqual(result["validation"]["run_ids"], ["RUN-V236-1"])
            self.assertFalse(result["validation"]["acceptance_eligible"])

    def test_machine_schemas_match_runtime_contract_ids(self) -> None:
        schema_root = TOOL.parents[2] / "schemas" / "v2.36"
        expected = {
            "protected-git-tree-snapshot.schema.json": trust.SNAPSHOT_RECEIPT_SCHEMA_VERSION,
            "agent-host-attestation.schema.json": trust.HOST_ATTESTATION_SCHEMA_VERSION,
            "attested-identity-registry.schema.json": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
            "host-route-receipt.schema.json": trust.HOST_ROUTE_RECEIPT_SCHEMA_VERSION,
            "persistent-challenge-state.schema.json": trust.PERSISTENT_CHALLENGE_STATE_SCHEMA_VERSION,
        }
        for name, schema_id in expected.items():
            with self.subTest(schema=name):
                document = json.loads((schema_root / name).read_text(encoding="utf-8"))
                self.assertEqual(
                    document["properties"]["schema_version"]["const"], schema_id
                )

    def issue(self, identity: dict, nonce: str, *, expires: datetime | None = None) -> dict:
        result = trust.issue_agent_host_attestation(
            identity,
            trust_key=self.KEY,
            issuer=self.ISSUER,
            nonce=nonce,
            issued_at=self.NOW - timedelta(seconds=10),
            expires_at=expires or self.NOW + timedelta(minutes=5),
        )
        self.assertTrue(result["ok"], result)
        return result["attestation"]

    @staticmethod
    def route(**updates) -> dict:
        request = {
            "schema_version": "goal-teams-project-route-v2.36",
            "product_version": "V2.36",
            "target_kind": "generic_project",
            "project_size": "small",
            "work_type": "bugfix",
            "release": False,
            "ui": False,
            "backend": False,
            "api": False,
            "cli": True,
            "tests": True,
            "risk": "low",
            "security_sensitive": False,
            "external_write": False,
            "auth": False,
            "payment": False,
            "migration": False,
            "destructive": False,
            "ui_mode": "none",
            "specialist_requests": [],
        }
        request.update(updates)
        return request

    def issue_route(
        self,
        route: dict,
        nonce: str,
        *,
        target_kind: str = "generic_project",
        target_fingerprint: str = "a" * 64,
        release_base: str = "b" * 40,
        expires: datetime | None = None,
    ) -> dict:
        result = trust.issue_v236_host_route_receipt(
            route,
            actual_target_fingerprint=target_fingerprint,
            actual_target_kind=target_kind,
            trusted_release_base=release_base,
            trust_key=self.KEY,
            issuer=self.ISSUER,
            nonce=nonce,
            issued_at=self.NOW - timedelta(seconds=10),
            expires_at=expires or self.NOW + timedelta(minutes=5),
        )
        self.assertTrue(result["ok"], result)
        return result["receipt"]

    def test_registry_requires_valid_host_proof_and_never_embeds_trust_key(self) -> None:
        identities = [self.identity(1), self.identity(2)]
        for index, identity in enumerate(identities, 1):
            identity["host_attestation"] = self.issue(identity, f"nonce-{index}")
        document = {
            "schema_version": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
            "identities": identities,
        }
        self.assertNotIn(self.KEY.decode(), json.dumps(document, sort_keys=True))
        result = trust.validate_attested_identity_registry(
            document,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["attestation_count"], 2)
        self.assertEqual(result["consumed_nonces"], ["nonce-1", "nonce-2"])

        leaked = copy.deepcopy(document)
        leaked["trust_key"] = self.KEY.decode()
        rejected = trust.validate_attested_identity_registry(
            leaked,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
        )
        self.assertEqual(rejected["error_code"], "E_V236_ATTESTED_REGISTRY_SECRET")

    def test_self_report_forgery_wrong_key_tamper_and_expiry_fail_closed(self) -> None:
        identity = self.identity(1)
        proof = self.issue(identity, "nonce-valid")

        forged = copy.deepcopy(proof)
        forged["signature"] = "0" * 64
        result = trust.verify_agent_host_attestation(
            identity,
            forged,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
        )
        self.assertEqual(result["error_code"], "E_V236_ATTESTATION_SIGNATURE")

        result = trust.verify_agent_host_attestation(
            identity,
            proof,
            trust_key=self.WRONG_KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
        )
        self.assertEqual(result["error_code"], "E_V236_ATTESTATION_SIGNATURE")

        tampered_identity = copy.deepcopy(identity)
        tampered_identity["display_name"] = "Forged Member"
        result = trust.verify_agent_host_attestation(
            tampered_identity,
            proof,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
        )
        self.assertEqual(result["error_code"], "E_V236_ATTESTATION_IDENTITY")

        expired = self.issue(identity, "nonce-expired", expires=self.NOW - timedelta(seconds=1))
        result = trust.verify_agent_host_attestation(
            identity,
            expired,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
        )
        self.assertEqual(result["error_code"], "E_V236_ATTESTATION_EXPIRED")

    def test_nonce_replay_is_rejected_for_one_proof_and_across_registry(self) -> None:
        first = self.identity(1)
        proof = self.issue(first, "nonce-replay")
        used: set = set()
        accepted = trust.verify_agent_host_attestation(
            first,
            proof,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
            used_nonces=used,
        )
        self.assertTrue(accepted["ok"], accepted)
        replayed = trust.verify_agent_host_attestation(
            first,
            proof,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
            used_nonces=used,
        )
        self.assertEqual(replayed["error_code"], "E_V236_ATTESTATION_NONCE_REPLAY")

        second = self.identity(2)
        first["host_attestation"] = proof
        second["host_attestation"] = self.issue(second, "nonce-replay")
        document = {
            "schema_version": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
            "identities": [first, second],
        }
        result = trust.validate_attested_identity_registry(
            document,
            trust_key=self.KEY,
            expected_issuer=self.ISSUER,
            now=self.NOW,
        )
        self.assertEqual(result["error_code"], "E_V236_ATTESTATION_NONCE_REPLAY")

    def test_persistent_registry_replay_is_rejected_across_independent_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = self.identity(1)
            identity["host_attestation"] = self.issue(identity, "persistent-id-nonce")
            document = {
                "schema_version": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
                "identities": [identity],
            }
            # The historical pure verifier remains compatible but explicitly
            # cannot support V2.36 acceptance.
            pure = trust.validate_attested_identity_registry(
                document,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                now=self.NOW,
            )
            self.assertTrue(pure["ok"], pure)
            self.assertFalse(pure["acceptance_eligible"])

            state_path = Path(directory) / "challenge-state.json"
            first = trust._host_reference_validate_attested_identity_registry(
                document,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=state_path,
                now=self.NOW,
            )
            self.assertTrue(first["ok"], first)
            self.assertFalse(first["acceptance_eligible"])
            self.assertTrue(first["host_reference_only"])
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
            persisted = state_path.read_text(encoding="utf-8")
            self.assertNotIn(self.KEY.decode(), persisted)
            self.assertNotIn("persistent-id-nonce", persisted)

            # This is a separate API invocation with no shared in-memory set.
            replay = trust._host_reference_validate_attested_identity_registry(
                document,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=state_path,
                now=self.NOW,
            )
            self.assertEqual(replay["error_code"], "E_V236_ATTESTATION_NONCE_REPLAY")

    def test_persistent_state_symlink_and_mac_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = self.identity(1)
            identity["host_attestation"] = self.issue(identity, "unsafe-state-nonce")
            document = {
                "schema_version": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
                "identities": [identity],
            }
            target = Path(directory) / "target.json"
            target.write_text("{}", encoding="utf-8")
            os.chmod(target, 0o600)
            state_path = Path(directory) / "state.json"
            state_path.symlink_to(target)
            unsafe = trust._host_reference_validate_attested_identity_registry(
                document,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=state_path,
                now=self.NOW,
            )
            self.assertEqual(unsafe["error_code"], "E_V236_REPLAY_STATE_UNSAFE")

            state_path.unlink()
            accepted = trust._host_reference_validate_attested_identity_registry(
                document,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=state_path,
                now=self.NOW,
            )
            self.assertTrue(accepted["ok"], accepted)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["generation"] += 1
            state_path.write_text(json.dumps(state), encoding="utf-8")
            os.chmod(state_path, 0o600)
            tampered = trust._host_reference_validate_attested_identity_registry(
                document,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=state_path,
                now=self.NOW,
            )
            self.assertEqual(tampered["error_code"], "E_V236_REPLAY_STATE_MAC")

    def test_public_candidate_acceptance_apis_never_touch_state(self) -> None:
        identity = self.identity(1)
        identity["host_attestation"] = self.issue(identity, "candidate-blocked")
        registry = {
            "schema_version": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
            "identities": [identity],
        }
        route = self.route()
        receipt = self.issue_route(route, "candidate-route-blocked")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "must-not-exist.json"
            calls = (
                trust.validate_attested_identity_registry_for_acceptance(
                    registry,
                    trust_key=self.KEY,
                    expected_issuer=self.ISSUER,
                    state_path=state,
                    now=self.NOW,
                ),
                trust.validate_v236_host_route_receipt_for_acceptance(
                    route,
                    receipt,
                    actual_target_fingerprint="a" * 64,
                    actual_target_kind="generic_project",
                    trusted_release_base="b" * 40,
                    trust_key=self.KEY,
                    expected_issuer=self.ISSUER,
                    state_path=state,
                    now=self.NOW,
                ),
                trust.validate_v236_acceptance_bundle(
                    route,
                    receipt,
                    registry,
                    actual_target_fingerprint="a" * 64,
                    actual_target_kind="generic_project",
                    trusted_release_base="b" * 40,
                    trust_key=self.KEY,
                    expected_issuer=self.ISSUER,
                    state_path=state,
                    now=self.NOW,
                ),
            )
            for result in calls:
                self.assertFalse(result["ok"])
                self.assertEqual(
                    result["error_code"], "E_V236_HOST_ADAPTER_REQUIRED"
                )
                self.assertFalse(result["acceptance_eligible"])
            self.assertFalse(state.exists())

    def test_host_route_receipt_rederives_and_rejects_wrong_key_tamper_and_expiry(self) -> None:
        route = self.route()
        receipt = self.issue_route(route, "route-negative-nonce")
        common = {
            "actual_target_fingerprint": "a" * 64,
            "actual_target_kind": "generic_project",
            "trusted_release_base": "b" * 40,
            "expected_issuer": self.ISSUER,
            "now": self.NOW,
        }
        preflight = trust.verify_v236_host_route_receipt(
            route,
            receipt,
            trust_key=self.KEY,
            **common,
        )
        self.assertTrue(preflight["ok"], preflight)
        self.assertFalse(preflight["acceptance_eligible"])
        self.assertEqual(preflight["actual_target_fingerprint"], "a" * 64)
        self.assertEqual(preflight["actual_target_kind"], "generic_project")
        self.assertEqual(receipt["execution_profile"], "lite")
        self.assertEqual(receipt["required_review_class"], "semantic")
        self.assertEqual(len(receipt["gates"]), 15)
        self.assertEqual(
            preflight["execution_contract_sha256"],
            receipt["execution_contract_sha256"],
        )
        with tempfile.TemporaryDirectory() as directory:
            wrong_key = trust._host_reference_validate_v236_host_route_receipt(
                route,
                receipt,
                trust_key=self.WRONG_KEY,
                state_path=Path(directory) / "wrong-key.json",
                **common,
            )
            self.assertEqual(wrong_key["error_code"], "E_V236_ROUTE_SIGNATURE")

            tampered = copy.deepcopy(receipt)
            tampered["state_gate_profile"] = "goal-teams-self-release-v2.36"
            rejected = trust._host_reference_validate_v236_host_route_receipt(
                route,
                tampered,
                trust_key=self.KEY,
                state_path=Path(directory) / "tampered.json",
                **common,
            )
            self.assertEqual(rejected["error_code"], "E_V236_ROUTE_SIGNATURE")

            resigned_tier = copy.deepcopy(receipt)
            resigned_tier["execution_profile"] = "standard"
            resigned_tier["signature"] = hmac.new(
                self.KEY,
                _canonical(
                    {
                        key: value
                        for key, value in resigned_tier.items()
                        if key != "signature"
                    }
                ),
                hashlib.sha256,
            ).hexdigest()
            rejected_tier = trust._host_reference_validate_v236_host_route_receipt(
                route,
                resigned_tier,
                trust_key=self.KEY,
                state_path=Path(directory) / "resigned-tier.json",
                **common,
            )
            self.assertEqual(
                rejected_tier["error_code"],
                "E_V236_ROUTE_DERIVATION_MISMATCH",
            )

            resigned_gates = copy.deepcopy(receipt)
            del resigned_gates["gates"]["completion_audit"]
            resigned_gates["signature"] = hmac.new(
                self.KEY,
                _canonical(
                    {
                        key: value
                        for key, value in resigned_gates.items()
                        if key != "signature"
                    }
                ),
                hashlib.sha256,
            ).hexdigest()
            rejected_gates = trust._host_reference_validate_v236_host_route_receipt(
                route,
                resigned_gates,
                trust_key=self.KEY,
                state_path=Path(directory) / "resigned-gates.json",
                **common,
            )
            self.assertEqual(
                rejected_gates["error_code"],
                "E_V236_ROUTE_DERIVATION_MISMATCH",
            )

            relabeled_route = copy.deepcopy(route)
            relabeled_route["project_size"] = "medium"
            relabeled = trust._host_reference_validate_v236_host_route_receipt(
                relabeled_route,
                receipt,
                trust_key=self.KEY,
                state_path=Path(directory) / "relabeled.json",
                **common,
            )
            self.assertEqual(relabeled["error_code"], "E_V236_ROUTE_DIGEST_MISMATCH")

            wrong_base = trust._host_reference_validate_v236_host_route_receipt(
                route,
                receipt,
                trust_key=self.KEY,
                state_path=Path(directory) / "wrong-base.json",
                **{**common, "trusted_release_base": "c" * 40},
            )
            self.assertEqual(wrong_base["error_code"], "E_V236_ROUTE_RELEASE_BASE")

            release_route = self.route(
                target_kind="goal_teams_repository",
                project_size="large",
                work_type="feature",
                release=True,
                cli=False,
                backend=True,
            )
            release_receipt = self.issue_route(
                release_route,
                "self-release-route-nonce",
                target_kind="goal_teams_repository",
            )
            self.assertEqual(
                release_receipt["state_gate_profile"],
                "goal-teams-self-release-v2.36",
            )
            maintenance_route = copy.deepcopy(release_route)
            maintenance_route["release"] = False
            relabeled_release = trust._host_reference_validate_v236_host_route_receipt(
                maintenance_route,
                release_receipt,
                actual_target_fingerprint="a" * 64,
                actual_target_kind="goal_teams_repository",
                trusted_release_base="b" * 40,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=Path(directory) / "release-relabeled.json",
                now=self.NOW,
            )
            self.assertEqual(
                relabeled_release["error_code"],
                "E_V236_ROUTE_DERIVATION_MISMATCH",
            )

            expired_receipt = self.issue_route(
                route,
                "route-expired-nonce",
                expires=self.NOW - timedelta(seconds=1),
            )
            expired = trust._host_reference_validate_v236_host_route_receipt(
                route,
                expired_receipt,
                trust_key=self.KEY,
                state_path=Path(directory) / "expired.json",
                **common,
            )
            self.assertEqual(expired["error_code"], "E_V236_ROUTE_EXPIRED")

    def test_route_receipt_replay_and_atomic_acceptance_bundle(self) -> None:
        route = self.route()
        route_receipt = self.issue_route(route, "bundle-route-nonce")
        identity = self.identity(1)
        identity["host_attestation"] = self.issue(identity, "bundle-identity-nonce")
        registry = {
            "schema_version": trust.ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
            "identities": [identity],
        }
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "acceptance-state.json"
            accepted = trust._host_reference_validate_v236_acceptance_bundle(
                route,
                route_receipt,
                registry,
                actual_target_fingerprint="a" * 64,
                actual_target_kind="generic_project",
                trusted_release_base="b" * 40,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=state_path,
                now=self.NOW,
            )
            self.assertTrue(accepted["ok"], accepted)
            self.assertFalse(accepted["acceptance_eligible"])
            self.assertTrue(accepted["host_reference_only"])
            self.assertEqual(accepted["state_generation"], 1)
            self.assertEqual(len(accepted["consumed_challenge_sha256"]), 2)
            self.assertEqual(accepted["trusted_release_base"], "b" * 40)

            # The route proof is consumed by the same transaction and cannot
            # be accepted by a later independent call.
            replay = trust._host_reference_validate_v236_host_route_receipt(
                route,
                route_receipt,
                actual_target_fingerprint="a" * 64,
                actual_target_kind="generic_project",
                trusted_release_base="b" * 40,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=state_path,
                now=self.NOW,
            )
            self.assertEqual(replay["error_code"], "E_V236_ROUTE_NONCE_REPLAY")

            # A failing bundle does not create or partially consume its state.
            clean_route_receipt = self.issue_route(route, "bad-bundle-route")
            invalid_registry = copy.deepcopy(registry)
            invalid_registry["identities"][0]["display_name"] = "Tampered"
            unused_state = Path(directory) / "unused-state.json"
            rejected = trust._host_reference_validate_v236_acceptance_bundle(
                route,
                clean_route_receipt,
                invalid_registry,
                actual_target_fingerprint="a" * 64,
                actual_target_kind="generic_project",
                trusted_release_base="b" * 40,
                trust_key=self.KEY,
                expected_issuer=self.ISSUER,
                state_path=unused_state,
                now=self.NOW,
            )
            self.assertEqual(rejected["error_code"], "E_V236_ATTESTATION_IDENTITY")
            self.assertFalse(unused_state.exists())


if __name__ == "__main__":
    unittest.main()
