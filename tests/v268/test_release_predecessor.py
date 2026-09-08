"""V2.68 predecessor capture uses real local files, with I1-only transport."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_IDENTITY = {
    "tag": "v2.67", "release_id": 379771898, "state": "published",
    "source_commit": "24f522a87b1aa74b6b127962ab88522ddc1f489d",
    "source_tree": "a09be8a212b583cc489125bf2ff3b4e6cbbf9b71",
    "public_assets": ["goal-teams-V2.67.tar.gz", "SHA256SUMS", "_release.json", "_files.sha256"],
}


def canonical(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


# Explicit TEST-only oracle for the fixed mechanism fixture. This is never
# selected by production input, environment, or installation path.
TEST_PAYLOAD_BYTES = {"VERSION": b"V2.67\n", "SKILL.md": b"# Goal Teams V2.67\nPRIVATE_TEST_DOCUMENT_MARKER\n"}
TEST_PAYLOAD_ANCHOR = MappingProxyType({
    "package_file_count": 2,
    "package_files_sha256": canonical([
        {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "mode": 0o644}
        for path, raw in sorted(TEST_PAYLOAD_BYTES.items())
    ]),
    "package_manifest_sha256": "a" * 64,
})


def trusted_test_payload_policy():
    target = importlib.import_module("scripts.v268.installed_predecessor")
    return mock.patch.object(target, "PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR", TEST_PAYLOAD_ANCHOR)


def authorization() -> dict:
    value = {
        "schema_version": "goal-teams-project-start-authorization-v2.50",
        "receipt_id": "AUTH-V268-TEST", "authorization_id": "AUTH-V268-TEST",
        "authorization_state": "granted_once_at_project_start", "authorization_lineage_preserved": True,
        "issued_at": "2026-09-08T00:00:00+00:00", "expires_at": None,
        "repository": {"id": "1249985345", "name_with_owner": "vibe-coding-era/goal-teams", "origin_fetch": "git@github.com:vibe-coding-era/goal-teams.git", "origin_push": "git@github.com:vibe-coding-era/goal-teams.git", "default_branch": "main"},
        "version": "V2.68", "candidate_branch": "codex/develop-v2.68", "tag": "v2.68",
        "locked_scope": "V2.68 output release integration",
        "action_allowlist": ["formal_install_update_rollback_uninstall", "fresh_runtime_transition", "github_pr_actions_merge_release_api", "release_asset_build_and_readback", "ssh_fetch_pull_ls_remote_branch_push_tag_push"],
        "validity_conditions": ["not_revoked_by_user", "repository_version_locked_scope_target_branch_tag_and_action_classes_unchanged", "run_state_running_replan_or_same_checkpoint_resumable_blocked"],
    }
    value["intent"] = {"repository_id": "1249985345", "repository": "vibe-coding-era/goal-teams", **{key: value[key] for key in ("version", "candidate_branch", "tag", "locked_scope", "action_allowlist", "validity_conditions")}}
    value["intent_sha256"] = canonical(value["intent"])
    return value


def installed_fixture(root: Path) -> tuple[Path, Path, dict]:
    installation = root / "installed"
    installation.mkdir()
    rows = []
    for relative, content in {"VERSION": "V2.67\n", "SKILL.md": "# Goal Teams V2.67\nPRIVATE_TEST_DOCUMENT_MARKER\n"}.items():
        path = installation / relative
        path.write_text(content, encoding="utf-8")
        path.chmod(0o644)
        raw = path.read_bytes()
        rows.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "mode": 0o644})
    state = {
        "schema_version": "goal-teams-install-v2.3", "version": "V2.67",
        "repository": "vibe-coding-era/goal-teams", "source_kind": "github_release_asset", "source_dirty": False,
        "release_tag": EXPECTED_IDENTITY["tag"], "release_id": EXPECTED_IDENTITY["release_id"], "release_state": "published",
        "source_commit": EXPECTED_IDENTITY["source_commit"], "source_git_tree_id": EXPECTED_IDENTITY["source_tree"],
        "package_manifest_sha256": "a" * 64, "package_files": sorted(rows, key=lambda item: item["path"]),
    }
    state_path = root / "current.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return installation, state_path, state


class TestV268InstalledPredecessor(unittest.TestCase):
    def setUp(self) -> None:
        self.target = importlib.import_module("scripts.v268.installed_predecessor")
        self.enterContext(trusted_test_payload_policy())
        self.temp = tempfile.TemporaryDirectory(prefix=".v268-predecessor-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installation, self.state_path, self.state = installed_fixture(self.root)

    def capture(self, **overrides) -> dict:
        values = {"installation_root": self.installation, "state_path": self.state_path, "authorization": authorization(), "expected_identity": EXPECTED_IDENTITY, "captured_at": "2026-09-08T00:01:00+00:00"}
        values.update(overrides)
        return self.target.capture_installed_predecessor(**values)

    def test_capture_reads_actual_bytes_without_writing_or_exporting_content(self) -> None:
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        observed = self.capture()
        self.assertEqual("goal-teams-v2.68-installed-predecessor-observation-v1", observed["schema_version"])
        self.assertEqual("V2.67", observed["predecessor_product_version"])
        self.assertEqual("V2.68", observed["target_product_version"])
        self.assertEqual(EXPECTED_IDENTITY, observed["release_identity"])
        self.assertEqual(2, observed["package_file_count"])
        self.assertEqual(0, observed["extra_file_count"])
        self.assertEqual("passed", observed["strict_payload_check"])
        self.assertEqual("I1", observed["actor_assurance"])
        self.assertEqual("correlated", observed["actor_relationship"])
        self.assertEqual("observed_on_authorized_local_host", observed["observation_source"])
        self.assertEqual(observed["expected_file_set_sha256"], observed["observed_file_set_sha256"])
        self.assertEqual(hashlib.sha256(self.state_path.read_bytes()).hexdigest(), observed["state_raw_sha256"])
        self.assertEqual(canonical({key: value for key, value in observed.items() if key != "receipt_sha256"}), observed["receipt_sha256"])
        encoded = json.dumps(observed)
        self.assertNotIn("PRIVATE_TEST_DOCUMENT_MARKER", encoded)
        self.assertNotIn(str(self.installation), encoded)
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_missing_changed_extra_and_wrong_mode_files_are_rejected(self) -> None:
        for variant in ("missing", "changed", "extra", "mode"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(dir=self.root) as name:
                installation, state_path, _ = installed_fixture(Path(name))
                target = installation / "SKILL.md"
                if variant == "missing": target.unlink()
                elif variant == "changed": target.write_text("changed", encoding="utf-8")
                elif variant == "extra": (installation / "extra.pyc").write_bytes(b"extra")
                else: target.chmod(0o755)
                with self.assertRaises(ValueError): self.capture(installation_root=installation, state_path=state_path)

    def test_symlink_file_state_root_and_parent_are_rejected(self) -> None:
        target = self.installation / "VERSION"
        raw = target.read_bytes()
        target.unlink()
        actual = self.root / "actual-version"
        actual.write_bytes(raw)
        target.symlink_to(actual)
        with self.assertRaises(ValueError): self.capture()
        target.unlink()
        target.write_bytes(raw)
        target.chmod(0o644)
        linked_state = self.root / "linked-state.json"
        linked_state.symlink_to(self.state_path)
        with self.assertRaises(ValueError): self.capture(state_path=linked_state)
        linked_root = self.root / "linked-installation"
        linked_root.symlink_to(self.installation, target_is_directory=True)
        with self.assertRaises(ValueError): self.capture(installation_root=linked_root)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): self.capture(installation_root=linked_parent / "installed")

    def test_duplicate_traversal_absolute_and_untyped_manifest_entries_are_rejected(self) -> None:
        for variant in ("duplicate", "traversal", "absolute", "boolean-size"):
            with self.subTest(variant=variant):
                state = copy.deepcopy(self.state)
                if variant == "duplicate": state["package_files"].append(copy.deepcopy(state["package_files"][0]))
                elif variant == "traversal": state["package_files"][0]["path"] = "../outside"
                elif variant == "absolute": state["package_files"][0]["path"] = str(self.installation / "SKILL.md")
                else: state["package_files"][0]["size"] = True
                self.state_path.write_text(json.dumps(state))
                with self.assertRaises(ValueError): self.capture()

    def test_wrong_state_identity_and_wrong_actual_version_are_rejected(self) -> None:
        for key, value in (("version", "V2.66"), ("release_id", 1), ("source_dirty", True), ("source_kind", "worktree"), ("source_git_tree_id", "f" * 40)):
            with self.subTest(key=key):
                self.state_path.write_text(json.dumps({**self.state, key: value}))
                with self.assertRaises(ValueError): self.capture()
        self.state_path.write_text(json.dumps(self.state))
        target = self.installation / "VERSION"
        target.write_text("V2.66\n")
        state = copy.deepcopy(self.state)
        next(item for item in state["package_files"] if item["path"] == "VERSION")["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        self.state_path.write_text(json.dumps(state))
        with self.assertRaises(ValueError): self.capture()

    def test_transport_validates_authorization_identity_digest_and_exact_fields(self) -> None:
        observed = self.capture()
        verdict = self.target.validate_installed_predecessor(observed, authorization=authorization(), expected_identity=EXPECTED_IDENTITY)
        self.assertTrue(verdict["ok"], verdict)
        for field, value in (("authorization_id", "OTHER"), ("predecessor_product_version", "V2.66"), ("strict_payload_check", "failed"), ("actor_relationship", "external_independent"), ("extra_file_count", 1), ("package_file_count", True), ("observed_file_set_sha256", "0" * 64), ("unknown", True)):
            with self.subTest(field=field):
                changed = {**observed, field: value}
                changed["receipt_sha256"] = canonical({key: item for key, item in changed.items() if key != "receipt_sha256"})
                self.assertFalse(self.target.validate_installed_predecessor(changed, authorization=authorization(), expected_identity=EXPECTED_IDENTITY)["ok"])

    def test_capture_rejects_wrong_or_revoked_authorization(self) -> None:
        for change in ({"version": "V2.67"}, {"revoked": True}, {"authorization_lineage_preserved": False}, {"intent_sha256": "0" * 64}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.capture(authorization={**authorization(), **change})


if __name__ == "__main__": unittest.main()
