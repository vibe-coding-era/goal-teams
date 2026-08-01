from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v249 import release_flow, s4_executor


SOURCE = "1" * 40
TREE = "2" * 40
REPOSITORY = "vibe-coding-era/goal-teams"
VERSION = "V2.49"
TAG = "v2.49"
RELEASE_BODY = "Goal Teams V2.49. See release/current/README.md in the tagged source."
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas/v2.49/release-control.schema.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def make_release_tree(root: Path) -> tuple[Path, list[dict[str, object]]]:
    profile = root / "references/release-profiles/v2.49.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps(
            {
                "version": VERSION,
                "status": "active",
                "tag": TAG,
                "release_title": "Goal Teams V2.49",
                "release_body": RELEASE_BODY,
                "tag_message": "Goal Teams V2.49",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    release_root = root / "release" / "versions"
    snapshot = release_root / VERSION
    artifacts = snapshot / "_artifacts"
    artifacts.mkdir(parents=True)
    package_payloads = {
        "SKILL.md": b"---\nname: goal-teams\n---\n",
        "subagents/goal-backend.toml": b'name = "goal-backend"\n',
    }
    package_files = [
        {
            "path": name,
            "sha256": sha256_bytes(data),
            "size": len(data),
            "mode": 0o644,
        }
        for name, data in sorted(package_payloads.items())
    ]
    files_manifest = "".join(
        f"{item['sha256']}\t100644\t{item['size']}\t{item['path']}\n"
        for item in package_files
    ).encode()
    tree_digest_input = b"".join(
        (
            f"{item['path']}\0"
            f"{('100755' if item['mode'] == 0o755 else '100644')}\0"
            f"{item['size']}\0{item['sha256']}\n"
        ).encode()
        for item in package_files
    )
    payloads = {
        f"goal-teams-{VERSION}.tar.gz": b"archive-v249",
        "SHA256SUMS": b"placeholder sums\n",
        "_release.json": json.dumps(
            {
                "version": VERSION,
                "source_commit": SOURCE,
                "source_git_tree_id": TREE,
                "tree_sha256": sha256_bytes(tree_digest_input),
                "file_count": len(package_files),
                "total_bytes": sum(item["size"] for item in package_files),
            },
            sort_keys=True,
        ).encode(),
        "_files.sha256": files_manifest,
    }
    paths = {
        f"goal-teams-{VERSION}.tar.gz": artifacts / f"goal-teams-{VERSION}.tar.gz",
        "SHA256SUMS": artifacts / "SHA256SUMS",
        "_release.json": snapshot / "_release.json",
        "_files.sha256": snapshot / "_files.sha256",
    }
    for name, path in paths.items():
        path.write_bytes(payloads[name])
    assets = [
        {
            "name": name,
            "size": len(payloads[name]),
            "sha256": sha256_bytes(payloads[name]),
        }
        for name in sorted(payloads)
    ]
    return release_root, assets


def make_control(assets: list[dict[str, object]]) -> dict[str, object]:
    asset_set_digest = release_flow.canonical_sha256(assets)
    return {
        "schema_version": "goal-teams-v2.49-release-control-receipt-v1",
        "repository": REPOSITORY,
        "version": VERSION,
        "candidate_branch": "codex/v2.49-simplification",
        "tag": TAG,
        "source_commit": SOURCE,
        "source_tree": TREE,
        "asset_set_id": f"V249-ASSET-{asset_set_digest[:20]}",
        "asset_set_digest": asset_set_digest,
        "intent_sha256": "4" * 64,
        "authorization_receipt": {
            "authorization_id": "AUTH-V249-TEST",
            "repository": {
                "origin_fetch": "git@github.com:vibe-coding-era/goal-teams.git",
                "origin_push": "git@github.com:vibe-coding-era/goal-teams.git",
            },
        },
        "s2": {"assets": assets},
        "release_control_sha256": "5" * 64,
    }


def accepted_control(_: str, __: str, control: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "errors": [],
        "source_tree": control["source_tree"],
        "authorization_id": control["authorization_receipt"]["authorization_id"],
        "release_control_sha256": control["release_control_sha256"],
    }


def accepted_prewrite_boundary(**kwargs: object) -> dict[str, object]:
    control = kwargs["control"]
    assert isinstance(control, dict)
    return {
        "ok": True,
        "passed": True,
        "source_commit": kwargs["source_commit"],
        "source_tree": kwargs["source_tree"],
        "asset_set_id": control["asset_set_id"],
        "asset_set_digest": control["asset_set_digest"],
    }


def assert_schema_instance(
    case: unittest.TestCase,
    instance: object,
    schema: dict[str, object],
    root_schema: dict[str, object],
) -> None:
    """Validate the standard-library subset used by the S4 outcome contract."""

    reference = schema.get("$ref")
    if isinstance(reference, str):
        case.assertTrue(reference.startswith("#/"))
        target: object = root_schema
        for part in reference[2:].split("/"):
            case.assertIsInstance(target, dict)
            target = target[part]
        case.assertIsInstance(target, dict)
        assert_schema_instance(case, instance, target, root_schema)
        return
    for branch in schema.get("allOf", []):
        case.assertIsInstance(branch, dict)
        assert_schema_instance(case, instance, branch, root_schema)
    if "const" in schema:
        case.assertEqual(schema["const"], instance)
    if "enum" in schema:
        case.assertIn(instance, schema["enum"])
    kind = schema.get("type")
    if kind == "object":
        case.assertIsInstance(instance, dict)
        required = schema.get("required", [])
        case.assertTrue(set(required).issubset(instance))
        properties = schema.get("properties", {})
        case.assertIsInstance(properties, dict)
        if schema.get("additionalProperties") is False:
            case.assertEqual(set(), set(instance) - set(properties))
        for key, value in instance.items():
            child = properties.get(key)
            if isinstance(child, dict):
                assert_schema_instance(case, value, child, root_schema)
    elif kind == "array":
        case.assertIsInstance(instance, list)
        if "minItems" in schema:
            case.assertGreaterEqual(len(instance), schema["minItems"])
        if "maxItems" in schema:
            case.assertLessEqual(len(instance), schema["maxItems"])
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True) for item in instance]
            case.assertEqual(len(encoded), len(set(encoded)))
        child = schema.get("items")
        if isinstance(child, dict):
            for value in instance:
                assert_schema_instance(case, value, child, root_schema)
    elif kind == "string":
        case.assertIsInstance(instance, str)
        if "minLength" in schema:
            case.assertGreaterEqual(len(instance), schema["minLength"])
        if "pattern" in schema:
            case.assertRegex(instance, schema["pattern"])
    elif kind == "integer":
        case.assertIsInstance(instance, int)
        case.assertNotIsInstance(instance, bool)
        if "minimum" in schema:
            case.assertGreaterEqual(instance, schema["minimum"])
        if "maximum" in schema:
            case.assertLessEqual(instance, schema["maximum"])
    elif kind == "boolean":
        case.assertIsInstance(instance, bool)
    elif kind == "null":
        case.assertIsNone(instance)


class FakeBackend:
    def __init__(self) -> None:
        self.remote_url = "git@github.com:vibe-coding-era/goal-teams.git"
        self.tag: dict[str, object] | None = None
        self.local_tag: dict[str, object] | None = None
        self.release: dict[str, object] | None = None
        self.blobs: dict[str, bytes] = {}
        self.installed_state: dict[str, object] | None = None
        self.install_bundle_paths: list[str] = []
        self.install_payload_verified = True
        self.fail_after_mutation: str | None = None
        self.fail_without_mutation: str | None = None
        self.reconciliation_read_error: str | None = None
        self.write_counts = {
            "tag_create": 0,
            "tag_push": 0,
            "release_create": 0,
            "asset_upload": 0,
            "release_publish": 0,
            "install": 0,
        }

    def read_fetch_remote(self) -> str:
        return self.remote_url

    def read_push_remote(self) -> str:
        return self.remote_url

    def read_tag(self, tag: str) -> dict[str, object] | None:
        if self.reconciliation_read_error == "tag_push" and self.tag is not None:
            raise OSError("simulated remote read failure")
        return None if self.tag is None else dict(self.tag)

    def read_local_tag(self, tag: str) -> dict[str, object] | None:
        return None if self.local_tag is None else dict(self.local_tag)

    def create_annotated_tag(self, tag: str, commit: str, title: str) -> None:
        self.write_counts["tag_create"] += 1
        if self.fail_without_mutation == "tag_local_create":
            raise OSError("simulated local tag create failure")
        self.local_tag = {
            "tag": tag,
            "object_sha": "6" * 40,
            "peeled_commit": commit,
            "annotated": True,
            "message": title,
        }
        if self.fail_after_mutation == "tag_local_create":
            raise OSError("simulated local tag create response failure")

    def push_tag(self, tag: str) -> None:
        self.write_counts["tag_push"] += 1
        if self.fail_without_mutation == "tag_push":
            raise OSError("simulated tag push failure")
        assert self.local_tag is not None
        self.tag = dict(self.local_tag)
        if self.fail_after_mutation == "tag_push":
            raise OSError("simulated tag push response failure")

    def read_release(self, repository: str, tag: str) -> dict[str, object] | None:
        return None if self.release is None else json.loads(json.dumps(self.release))

    def create_draft_release(
        self,
        repository: str,
        tag: str,
        title: str,
        body: str,
    ) -> None:
        self.write_counts["release_create"] += 1
        if self.fail_without_mutation == "release_create":
            raise OSError("simulated release create failure")
        self.release = {
            "id": 249,
            "tag_name": tag,
            "name": title,
            "body": body,
            "draft": True,
            "prerelease": False,
            "html_url": "https://github.com/vibe-coding-era/goal-teams/releases/tag/v2.49",
            "assets": [],
        }
        if self.fail_after_mutation == "release_create":
            raise OSError("simulated release create response failure")

    def upload_asset(self, repository: str, tag: str, path: Path) -> None:
        assert self.release is not None
        self.write_counts["asset_upload"] += 1
        data = path.read_bytes()
        self.blobs[path.name] = data
        self.release["assets"].append(
            {
                "id": 1000 + len(self.release["assets"]),
                "name": path.name,
                "size": len(data),
                "state": "uploaded",
                "digest": f"sha256:{sha256_bytes(data)}",
            }
        )

    def publish_release(self, repository: str, tag: str) -> None:
        assert self.release is not None
        self.write_counts["release_publish"] += 1
        self.release["draft"] = False

    def download_asset(self, repository: str, tag: str, name: str, target: Path) -> None:
        target.write_bytes(self.blobs[name])

    def read_installed_state(self) -> dict[str, object] | None:
        return None if self.installed_state is None else json.loads(json.dumps(self.installed_state))

    def read_installed_version(self) -> str | None:
        if self.installed_state is None:
            return None
        value = self.installed_state.get("skill_version")
        return value if isinstance(value, str) else None

    def install(self, bundle: Path, identity_path: Path) -> None:
        self.write_counts["install"] += 1
        self.install_bundle_paths.append(str(bundle))
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        record = json.loads((bundle / "_release.json").read_text(encoding="utf-8"))
        package_files = []
        for line in (bundle / "_files.sha256").read_text(encoding="utf-8").splitlines():
            digest, mode, size, path = line.split("\t", 3)
            package_files.append(
                {
                    "path": path,
                    "sha256": digest,
                    "size": int(size),
                    "mode": 0o755 if mode == "100755" else 0o644,
                }
            )
        self.installed_state = {
            "source_kind": "github_release_asset",
            "repository": identity["repository"],
            "version": identity["version"],
            "release_tag": identity["release_tag"],
            "release_id": identity["release_id"],
            "release_state": "published",
            "source_commit": identity["source_commit"],
            "source_git_tree_id": identity["source_git_tree_id"],
            "release_assets": identity["assets"],
            "release_identity_sha256": sha256_bytes(identity_path.read_bytes()),
            "release_asset_sha256": next(
                item["sha256"]
                for item in identity["assets"]
                if item["name"] == f"goal-teams-{VERSION}.tar.gz"
            ),
            "bundle_tree_sha256": record["tree_sha256"],
            "source_tree_digest": record["tree_sha256"],
            "source_dirty": False,
            "skill_version": VERSION,
            "package_files": package_files,
            "managed_agent_files": ["goal-backend.toml"],
            "fallback_agent_files": [],
            "agent_hashes": {"goal-backend.toml": "7" * 64},
        }

    def verify_installed_payload(
        self,
        package_files: list[dict[str, object]],
        state: dict[str, object],
    ) -> dict[str, object]:
        if not self.install_payload_verified or state.get("package_files") != package_files:
            raise s4_executor.S4ExecutionError("E_V249_S4_INSTALLED_PACKAGE_DRIFT")
        return {
            "package_file_count": len(package_files),
            "package_tree_sha256": s4_executor.canonical_sha256(package_files),
            "state_package_files_sha256": s4_executor.canonical_sha256(
                state["package_files"]
            ),
            "agent_file_count": len(state["agent_hashes"]),
            "agent_set_sha256": s4_executor.canonical_sha256(state["agent_hashes"]),
            "symlink_count": 0,
        }


class TestV249S4Executor(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(
            s4_executor,
            "_default_prewrite_boundary_validator",
            side_effect=accepted_prewrite_boundary,
        )
        self.prewrite_boundary = patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def journal_entry(receipt: dict[str, object], step_id: str) -> dict[str, object]:
        entries = receipt["operation_journal"]
        assert isinstance(entries, list)
        return next(entry for entry in entries if entry["step_id"] == step_id)

    def test_first_execution_and_exact_repeat_are_both_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            control = make_control(assets)
            backend = FakeBackend()

            first = s4_executor.execute_s4(
                version=VERSION,
                commit=SOURCE,
                release_control=control,
                release_root=release_root,
                repository_root=root,
                backend=backend,
                control_validator=accepted_control,
            )
            self.assertTrue(first["passed"])
            self.assertTrue(first["action_executed"])
            self.assertEqual("executed_and_verified", first["execution_mode"])
            self.assertEqual(4, backend.write_counts["asset_upload"])
            self.assertEqual(1, backend.write_counts["install"])
            self.assertEqual(1, len(backend.install_bundle_paths))
            self.assertNotIn(str(release_root), backend.install_bundle_paths[0])
            self.assertEqual("validated", first["schema_validation"]["state"])
            self.assertTrue(all(
                entry["state"] in {"confirmed", "not_started"}
                for entry in first["operation_journal"]
            ))
            s4_executor.validate_outcome_receipt(first)

            invalid = dict(first)
            invalid["passed"] = False
            with self.assertRaises(s4_executor.S4ExecutionError):
                s4_executor.validate_outcome_receipt(invalid)

            before = dict(backend.write_counts)
            second = s4_executor.execute_s4(
                version=VERSION,
                commit=SOURCE,
                release_control=control,
                release_root=release_root,
                repository_root=root,
                backend=backend,
                control_validator=accepted_control,
            )
            self.assertTrue(second["passed"])
            self.assertFalse(second["action_executed"])
            self.assertEqual("reconciled_existing", second["execution_mode"])
            self.assertEqual(before, backend.write_counts)
            s4_executor.validate_outcome_receipt(second)

    def test_live_boundary_revalidation_runs_before_the_first_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            backend = FakeBackend()
            calls: list[dict[str, object]] = []

            def verify_before_write(**kwargs: object) -> dict[str, object]:
                self.assertEqual(
                    {key: 0 for key in backend.write_counts},
                    backend.write_counts,
                )
                calls.append(dict(kwargs))
                return accepted_prewrite_boundary(**kwargs)

            receipt = s4_executor.execute_s4(
                version=VERSION,
                commit=SOURCE,
                release_control=make_control(assets),
                release_root=release_root,
                repository_root=root,
                backend=backend,
                control_validator=accepted_control,
                prewrite_boundary_validator=verify_before_write,
            )

            self.assertTrue(receipt["passed"])
            self.assertEqual(1, len(calls))
            self.assertEqual(SOURCE, calls[0]["source_commit"])
            self.assertEqual(TREE, calls[0]["source_tree"])

    def test_live_boundary_failure_blocks_every_s4_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            backend = FakeBackend()

            def reject_dirty_source(**_: object) -> dict[str, object]:
                raise s4_executor.S4ExecutionError(
                    "E_V249_REPOSITORY_BOUNDARY_SOURCE_NOT_FROZEN"
                )

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=make_control(assets),
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                    prewrite_boundary_validator=reject_dirty_source,
                )
            self.assertEqual(
                "E_V249_REPOSITORY_BOUNDARY_SOURCE_NOT_FROZEN",
                caught.exception.code,
            )
            self.assertEqual(
                "blocked_before_write",
                caught.exception.receipt["failure_class"],
            )
            self.assertEqual(0, caught.exception.receipt["write_attempt_count"])
            self.assertEqual(
                {key: 0 for key in backend.write_counts},
                backend.write_counts,
            )

    def test_release_body_drift_is_rejected_before_release_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            backend = FakeBackend()
            backend.tag = {
                "tag": TAG,
                "object_sha": "6" * 40,
                "peeled_commit": SOURCE,
                "annotated": True,
                "message": "Goal Teams V2.49",
            }
            backend.release = {
                "id": 249,
                "tag_name": TAG,
                "name": "Goal Teams V2.49",
                "body": "wrong release notes",
                "draft": True,
                "prerelease": False,
                "html_url": (
                    "https://github.com/vibe-coding-era/goal-teams/"
                    "releases/tag/v2.49"
                ),
                "assets": [],
            }

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=make_control(assets),
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            self.assertEqual("E_V249_S4_RELEASE_DRIFT", caught.exception.code)
            self.assertEqual(
                {key: 0 for key in backend.write_counts},
                backend.write_counts,
            )

    def test_remote_asset_drift_fails_closed_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            control = make_control(assets)
            backend = FakeBackend()
            backend.tag = {
                "tag": TAG,
                "object_sha": "6" * 40,
                "peeled_commit": SOURCE,
                "annotated": True,
                "message": "Goal Teams V2.49",
            }
            backend.release = {
                "id": 249,
                "tag_name": TAG,
                "name": "Goal Teams V2.49",
                "body": RELEASE_BODY,
                "draft": True,
                "prerelease": False,
                "html_url": "https://example.invalid/release",
                "assets": [
                    {
                        "id": 1000,
                        "name": assets[0]["name"],
                        "size": assets[0]["size"],
                        "state": "uploaded",
                        "digest": "sha256:" + "0" * 64,
                    }
                ],
            }

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=control,
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            self.assertEqual("E_V249_S4_REMOTE_ASSET_DRIFT", caught.exception.code)
            self.assertEqual(0, backend.write_counts["asset_upload"])

    def test_noncanonical_github_release_url_is_a_prewrite_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            backend = FakeBackend()
            backend.tag = {
                "tag": TAG,
                "object_sha": "6" * 40,
                "peeled_commit": SOURCE,
                "annotated": True,
                "message": "Goal Teams V2.49",
            }
            backend.release = {
                "id": 249,
                "tag_name": TAG,
                "name": "Goal Teams V2.49",
                "body": RELEASE_BODY,
                "draft": False,
                "prerelease": False,
                "html_url": "https://evil.invalid/vibe-coding-era/goal-teams/v2.49",
                "assets": [],
            }

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=make_control(assets),
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            self.assertEqual("E_V249_S4_RELEASE_DRIFT", caught.exception.code)
            self.assertEqual(
                "blocked_before_write", caught.exception.receipt["failure_class"]
            )

    def test_forged_control_is_rejected_before_any_backend_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            control = make_control(assets)
            backend = FakeBackend()

            def reject(_: str, __: str, ___: dict[str, object]) -> dict[str, object]:
                return {"ok": False, "errors": ["E_V249_EXTERNAL_ANCHOR_REVALIDATION"]}

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=control,
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=reject,
                )
            self.assertEqual("E_V249_EXTERNAL_ANCHOR_REVALIDATION", caught.exception.code)
            self.assertEqual({key: 0 for key in backend.write_counts}, backend.write_counts)

    def test_https_remote_is_rejected_before_any_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            control = make_control(assets)
            backend = FakeBackend()
            backend.remote_url = "https://github.com/vibe-coding-era/goal-teams.git"

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=control,
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            self.assertEqual("E_V249_S4_GIT_TRANSPORT_NOT_SSH", caught.exception.code)
            self.assertEqual({key: 0 for key in backend.write_counts}, backend.write_counts)

    def test_existing_v249_install_drift_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            control = make_control(assets)
            backend = FakeBackend()
            s4_executor.execute_s4(
                version=VERSION,
                commit=SOURCE,
                release_control=control,
                release_root=release_root,
                repository_root=root,
                backend=backend,
                control_validator=accepted_control,
            )
            assert backend.installed_state is not None
            backend.installed_state["release_id"] = 999
            before = dict(backend.write_counts)

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=control,
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            self.assertEqual("E_V249_S4_INSTALLED_IDENTITY_DRIFT", caught.exception.code)
            self.assertEqual(before, backend.write_counts)

    def test_mutate_then_fail_is_reconciled_and_never_reported_as_prewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            control = make_control(assets)
            backend = FakeBackend()
            backend.fail_after_mutation = "tag_push"

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=control,
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            receipt = caught.exception.receipt
            self.assertEqual("partial_or_uncertain", receipt["failure_class"])
            self.assertTrue(receipt["action_executed"])
            self.assertGreaterEqual(receipt["external_side_effect_count"], 1)
            self.assertEqual(
                "confirmed", self.journal_entry(receipt, "tag_push")["state"]
            )
            self.assertTrue(receipt["reconciliation"]["performed"])
            self.assertEqual("exact", receipt["reconciliation"]["overall_state"])
            self.assertEqual(SOURCE, receipt["source_commit"])
            self.assertEqual(control["asset_set_digest"], receipt["asset_set_digest"])
            self.assertEqual("AUTH-V249-TEST", receipt["authorization_id"])
            s4_executor.validate_outcome_receipt(receipt)

            backend.fail_after_mutation = None
            before_pushes = backend.write_counts["tag_push"]
            resumed = s4_executor.execute_s4(
                version=VERSION,
                commit=SOURCE,
                release_control=control,
                release_root=release_root,
                repository_root=root,
                backend=backend,
                control_validator=accepted_control,
            )
            self.assertTrue(resumed["passed"])
            self.assertEqual(before_pushes, backend.write_counts["tag_push"])

    def test_write_attempt_with_confirmed_absence_is_failed_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            backend = FakeBackend()
            backend.tag = {
                "tag": TAG,
                "object_sha": "6" * 40,
                "peeled_commit": SOURCE,
                "annotated": True,
                "message": "Goal Teams V2.49",
            }
            backend.fail_without_mutation = "release_create"

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=make_control(assets),
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            receipt = caught.exception.receipt
            self.assertEqual("failed_after_write", receipt["failure_class"])
            self.assertFalse(receipt["action_executed"])
            self.assertEqual(
                "attempted", self.journal_entry(receipt, "release_create")["state"]
            )
            observed = {
                item["step_id"]: item["observed_state"]
                for item in receipt["reconciliation"]["entries"]
            }
            self.assertEqual("absent", observed["release_create"])
            s4_executor.validate_outcome_receipt(receipt)

    def test_prewrite_tag_conflict_is_blocked_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            backend = FakeBackend()
            backend.tag = {
                "tag": TAG,
                "object_sha": "6" * 40,
                "peeled_commit": "9" * 40,
                "annotated": True,
                "message": "Goal Teams V2.49",
            }

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=make_control(assets),
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            receipt = caught.exception.receipt
            self.assertEqual("blocked_before_write", receipt["failure_class"])
            self.assertEqual(0, receipt["write_attempt_count"])
            self.assertFalse(receipt["action_executed"])
            self.assertEqual({key: 0 for key in backend.write_counts}, backend.write_counts)
            s4_executor.validate_outcome_receipt(receipt)

    def test_unreadable_mutate_then_fail_is_partial_or_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            backend = FakeBackend()
            backend.fail_after_mutation = "tag_push"
            backend.reconciliation_read_error = "tag_push"

            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=make_control(assets),
                    release_root=release_root,
                    repository_root=root,
                    backend=backend,
                    control_validator=accepted_control,
                )
            receipt = caught.exception.receipt
            self.assertEqual("partial_or_uncertain", receipt["failure_class"])
            self.assertEqual(
                "uncertain", self.journal_entry(receipt, "tag_push")["state"]
            )
            self.assertEqual(1, receipt["uncertain_write_count"])
            self.assertNotEqual("E_V249_RELEASE_CONTROL_REQUIRED", receipt["error_code"])
            s4_executor.validate_outcome_receipt(receipt)

    def test_receipt_digest_and_success_arithmetic_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            receipt = s4_executor.execute_s4(
                version=VERSION,
                commit=SOURCE,
                release_control=make_control(assets),
                release_root=release_root,
                repository_root=root,
                backend=FakeBackend(),
                control_validator=accepted_control,
            )
            forged = json.loads(json.dumps(receipt))
            forged["receipt_sha256"] = "0" * 64
            with self.assertRaises(s4_executor.S4ExecutionError) as digest_error:
                s4_executor.validate_outcome_receipt(forged)
            self.assertEqual(
                "E_V249_S4_OUTCOME_DIGEST", digest_error.exception.code
            )

            forged = json.loads(json.dumps(receipt))
            forged["external_side_effect_count"] += 1
            forged["receipt_sha256"] = s4_executor.canonical_sha256(
                {key: value for key, value in forged.items() if key != "receipt_sha256"}
            )
            with self.assertRaises(s4_executor.S4ExecutionError) as arithmetic_error:
                s4_executor.validate_outcome_receipt(forged)
            self.assertEqual(
                "E_V249_S4_OUTCOME_INVARIANT", arithmetic_error.exception.code
            )

    def test_success_receipt_cross_identity_bindings_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            receipt = s4_executor.execute_s4(
                version=VERSION,
                commit=SOURCE,
                release_control=make_control(assets),
                release_root=release_root,
                repository_root=root,
                backend=FakeBackend(),
                control_validator=accepted_control,
            )

            for label, mutate in (
                (
                    "missing state manifest digest",
                    lambda value: value["install_readback"].pop(
                        "state_package_files_sha256"
                    ),
                ),
                (
                    "duplicate remote asset id",
                    lambda value: value["asset_readback"][1].__setitem__(
                        "asset_id", value["asset_readback"][0]["asset_id"]
                    ),
                ),
                (
                    "asset set digest mismatch",
                    lambda value: (
                        value["asset_readback"][0].__setitem__(
                            "sha256", "9" * 64
                        ),
                        value["asset_readback"][0].__setitem__(
                            "download_sha256", "9" * 64
                        ),
                    ),
                ),
                (
                    "tag source mismatch",
                    lambda value: value["tag_readback"].__setitem__(
                        "peeled_commit", "9" * 40
                    ),
                ),
                (
                    "install source mismatch",
                    lambda value: value["install_readback"].__setitem__(
                        "source_tree", "9" * 40
                    ),
                ),
                (
                    "journal scope mismatch",
                    lambda value: value["operation_journal"][0].__setitem__(
                        "scope", "external_service"
                    ),
                ),
            ):
                with self.subTest(label=label):
                    forged = json.loads(json.dumps(receipt))
                    mutate(forged)
                    forged["receipt_sha256"] = s4_executor.canonical_sha256(
                        {
                            key: value
                            for key, value in forged.items()
                            if key != "receipt_sha256"
                        }
                    )
                    with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                        s4_executor.validate_outcome_receipt(forged)
                    self.assertEqual(
                        "E_V249_S4_OUTCOME_INVARIANT", caught.exception.code
                    )

    def test_validator_oserror_still_returns_terminal_receipt(self) -> None:
        class OSErrorValidator:
            def __init__(self) -> None:
                self._identity = (
                    s4_executor.Draft202012OutcomeValidator().identity
                )

            @property
            def identity(self) -> dict[str, object]:
                return dict(self._identity)

            def validate(self, receipt: object) -> None:
                raise OSError("simulated validator loss")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release_root, assets = make_release_tree(root)
            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                s4_executor.execute_s4(
                    version=VERSION,
                    commit=SOURCE,
                    release_control=make_control(assets),
                    release_root=release_root,
                    repository_root=root,
                    backend=FakeBackend(),
                    control_validator=accepted_control,
                    outcome_validator=OSErrorValidator(),
                )
            self.assertEqual("E_V249_S4_RUNTIME_OSERROR", caught.exception.code)
            receipt = caught.exception.receipt
            self.assertIsInstance(receipt, dict)
            self.assertEqual(
                "unavailable", receipt["schema_validation"]["state"]
            )
            self.assertEqual(
                "E_V249_S4_SCHEMA_VALIDATOR_UNAVAILABLE",
                receipt["schema_validation"]["error_code"],
            )
            self.assertEqual(
                receipt["receipt_sha256"],
                s4_executor.canonical_sha256(
                    {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                ),
            )


class RecordingRunner:
    def __init__(self, results: list[s4_executor.CommandResult]) -> None:
        self.results = list(results)
        self.argv: list[list[str]] = []

    def run(
        self, argv: list[str] | tuple[str, ...], *, cwd: Path
    ) -> s4_executor.CommandResult:
        self.argv.append(list(argv))
        return self.results.pop(0)


class TestV249CommandBackend(unittest.TestCase):
    def test_tag_creation_uses_annotated_local_tag_and_ssh_origin_push(self) -> None:
        runner = RecordingRunner(
            [
                s4_executor.CommandResult(0),
                s4_executor.CommandResult(0),
            ]
        )
        backend = s4_executor.CommandBackend(Path.cwd(), runner)

        backend.create_annotated_tag(TAG, SOURCE, "Goal Teams V2.49")
        backend.push_tag(TAG)

        self.assertEqual(
            ["git", "tag", "-a", TAG, SOURCE, "-m", "Goal Teams V2.49"],
            runner.argv[0],
        )
        self.assertEqual(
            ["git", "push", "origin", "refs/tags/v2.49:refs/tags/v2.49"],
            runner.argv[1],
        )
        flattened = " ".join(item for argv in runner.argv for item in argv).lower()
        self.assertNotIn("https://", flattened)
        self.assertNotIn("token", flattened)
        self.assertNotIn("authorization", flattened)

    def test_only_an_explicit_github_404_is_treated_as_absent(self) -> None:
        not_found = s4_executor.CommandResult(
            1, 'HTTP/2.0 404 Not Found\n\n{"message":"Not Found"}\n'
        )
        backend = s4_executor.CommandBackend(Path.cwd(), RecordingRunner([not_found]))
        self.assertIsNone(backend.read_release(REPOSITORY, TAG))

        unauthorized = s4_executor.CommandResult(
            1, 'HTTP/2.0 401 Unauthorized\n\n{"message":"Bad credentials"}\n'
        )
        backend = s4_executor.CommandBackend(Path.cwd(), RecordingRunner([unauthorized]))
        with self.assertRaises(s4_executor.S4ExecutionError) as caught:
            backend.read_release(REPOSITORY, TAG)
        self.assertEqual("E_V249_S4_RELEASE_READBACK", caught.exception.code)

    def test_every_gh_command_pins_canonical_host_and_repository(self) -> None:
        response = s4_executor.CommandResult(
            0,
            'HTTP/2.0 200 OK\n\n'
            '{"id":249,"tag_name":"v2.49","name":"Goal Teams V2.49",'
            '"body":"Goal Teams V2.49. See release/current/README.md in the tagged source.",'
            '"draft":true,"prerelease":false,'
            '"html_url":"https://github.com/vibe-coding-era/goal-teams/releases/tag/v2.49",'
            '"assets":[]}\n',
        )
        runner = RecordingRunner(
            [
                response,
                s4_executor.CommandResult(0),
                s4_executor.CommandResult(0),
                s4_executor.CommandResult(0),
                s4_executor.CommandResult(0),
            ]
        )
        backend = s4_executor.CommandBackend(Path.cwd(), runner)
        with mock.patch.dict(os.environ, {"GH_HOST": "evil.invalid"}):
            self.assertIsNotNone(backend.read_release(REPOSITORY, TAG))
            backend.create_draft_release(
                REPOSITORY,
                TAG,
                "Goal Teams V2.49",
                RELEASE_BODY,
            )
            backend.upload_asset(REPOSITORY, TAG, Path("SHA256SUMS"))
            backend.publish_release(REPOSITORY, TAG)
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(s4_executor.S4ExecutionError):
                    backend.download_asset(
                        REPOSITORY, TAG, "SHA256SUMS", Path(temp) / "SHA256SUMS"
                    )

        self.assertIn("--hostname", runner.argv[0])
        self.assertEqual("github.com", runner.argv[0][runner.argv[0].index("--hostname") + 1])
        create_argv = runner.argv[1]
        self.assertEqual(
            RELEASE_BODY,
            create_argv[create_argv.index("--notes") + 1],
        )
        self.assertNotEqual(
            create_argv[create_argv.index("--title") + 1],
            create_argv[create_argv.index("--notes") + 1],
        )
        for argv in runner.argv[1:]:
            self.assertEqual("gh", argv[0])
            self.assertIn("--repo", argv)
            self.assertEqual(
                "github.com/vibe-coding-era/goal-teams",
                argv[argv.index("--repo") + 1],
            )
            self.assertNotIn("evil.invalid", " ".join(argv))

    def test_annotated_tag_readback_requires_exact_message(self) -> None:
        tag_object = (
            f"object {SOURCE}\n"
            "type commit\n"
            f"tag {TAG}\n"
            "tagger Goal Teams <noreply@example.invalid> 0 +0000\n\n"
            "Goal Teams V2.49\n"
        )
        backend = s4_executor.CommandBackend(
            Path.cwd(),
            RecordingRunner(
                [
                    s4_executor.CommandResult(0, "6" * 40 + "\n"),
                    s4_executor.CommandResult(0, "tag\n"),
                    s4_executor.CommandResult(0, tag_object),
                ]
            ),
        )
        value = backend.read_local_tag(TAG)
        self.assertEqual("Goal Teams V2.49", value["message"])

        wrong = tag_object.replace("Goal Teams V2.49\n", "wrong title\n")
        backend = s4_executor.CommandBackend(
            Path.cwd(),
            RecordingRunner(
                [
                    s4_executor.CommandResult(0, "6" * 40 + "\n"),
                    s4_executor.CommandResult(0, "tag\n"),
                    s4_executor.CommandResult(0, wrong),
                ]
            ),
        )
        with self.assertRaises(s4_executor.S4ExecutionError) as caught:
            backend.read_local_tag(TAG)
        self.assertEqual("E_V249_S4_TAG_MESSAGE_DRIFT", caught.exception.code)

    def test_formal_installer_receives_only_canonical_target_environment(self) -> None:
        runner = RecordingRunner([s4_executor.CommandResult(0)])
        backend = s4_executor.CommandBackend(Path.cwd(), runner)
        backend.install(Path("/tmp/release-bundle"), Path("/tmp/identity.json"))

        argv = runner.argv[0]
        self.assertEqual("/usr/bin/env", argv[0])
        self.assertEqual("-i", argv[1])
        self.assertIn(f"HOME={backend.code_home.parent}", argv)
        self.assertIn(f"CODEX_HOME={backend.code_home}", argv)
        flattened = " ".join(argv).lower()
        self.assertNotIn("token", flattened)
        self.assertNotIn("credential", flattened)
        self.assertNotIn("authorization", flattened)

    def test_installed_payload_matches_release_manifest_and_real_agent_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            code_home = root / ".codex"
            skill = code_home / "skills" / "goal-teams"
            agent_root = code_home / "agents"
            (skill / "subagents").mkdir(parents=True)
            agent_root.mkdir(parents=True)
            payloads = {
                "SKILL.md": b"skill\n",
                "subagents/goal-backend.toml": b"agent\n",
            }
            package_files = []
            for relative, data in sorted(payloads.items()):
                path = skill / relative
                path.write_bytes(data)
                path.chmod(0o644)
                package_files.append(
                    {
                        "path": relative,
                        "sha256": sha256_bytes(data),
                        "size": len(data),
                        "mode": 0o644,
                    }
                )
            agent = agent_root / "goal-backend.toml"
            agent.write_bytes(payloads["subagents/goal-backend.toml"])
            agent.chmod(0o644)
            agent_record = {
                "path": ".",
                "type": "file",
                "mode": 0o644,
                "sha256": sha256_bytes(agent.read_bytes()),
                "size": agent.stat().st_size,
            }
            state = {
                "package_files": package_files,
                "managed_agent_files": [agent.name],
                "fallback_agent_files": [],
                "agent_hashes": {
                    agent.name: s4_executor.canonical_sha256([agent_record])
                },
            }
            backend = s4_executor.CommandBackend(
                Path.cwd(), RecordingRunner([]), code_home=code_home
            )
            readback = backend.verify_installed_payload(package_files, state)
            self.assertEqual(2, readback["package_file_count"])
            self.assertEqual(1, readback["agent_file_count"])
            self.assertEqual(0, readback["symlink_count"])

            empty_agent_state = dict(state)
            empty_agent_state["managed_agent_files"] = []
            empty_agent_state["fallback_agent_files"] = []
            empty_agent_state["agent_hashes"] = {}
            with self.assertRaises(s4_executor.S4ExecutionError) as agent_set_error:
                backend.verify_installed_payload(
                    package_files, empty_agent_state
                )
            self.assertEqual(
                "E_V249_S4_INSTALLED_AGENT_DRIFT",
                agent_set_error.exception.code,
            )

            (skill / "SKILL.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaises(s4_executor.S4ExecutionError) as caught:
                backend.verify_installed_payload(package_files, state)
            self.assertEqual(
                "E_V249_S4_INSTALLED_PACKAGE_DRIFT", caught.exception.code
            )

    def test_installed_payload_rejects_symlink_state_manifest_and_agent_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            code_home = root / ".codex"
            skill = code_home / "skills" / "goal-teams"
            agent_root = code_home / "agents"
            skill.mkdir(parents=True)
            agent_root.mkdir(parents=True)
            expected = root / "expected"
            expected.write_text("skill\n", encoding="utf-8")
            (skill / "SKILL.md").symlink_to(expected)
            package_files = [
                {
                    "path": "SKILL.md",
                    "sha256": sha256_bytes(b"skill\n"),
                    "size": 6,
                    "mode": 0o644,
                }
            ]
            agent = agent_root / "goal-backend.toml"
            agent.write_text("agent\n", encoding="utf-8")
            state = {
                "package_files": list(package_files),
                "managed_agent_files": [agent.name],
                "fallback_agent_files": [],
                "agent_hashes": {agent.name: "0" * 64},
            }
            backend = s4_executor.CommandBackend(
                Path.cwd(), RecordingRunner([]), code_home=code_home
            )
            with self.assertRaises(s4_executor.S4ExecutionError) as symlink_error:
                backend.verify_installed_payload(package_files, state)
            self.assertEqual(
                "E_V249_S4_INSTALLED_PACKAGE_SYMLINK", symlink_error.exception.code
            )

            (skill / "SKILL.md").unlink()
            (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
            drifted_state = dict(state)
            drifted_state["package_files"] = []
            with self.assertRaises(s4_executor.S4ExecutionError) as state_error:
                backend.verify_installed_payload(package_files, drifted_state)
            self.assertEqual(
                "E_V249_S4_INSTALLED_STATE_MANIFEST_DRIFT", state_error.exception.code
            )

            with self.assertRaises(s4_executor.S4ExecutionError) as agent_error:
                backend.verify_installed_payload(package_files, state)
            self.assertEqual(
                "E_V249_S4_INSTALLED_AGENT_DRIFT", agent_error.exception.code
            )


if __name__ == "__main__":
    unittest.main()
