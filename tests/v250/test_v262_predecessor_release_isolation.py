from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.v250.test_package_isolation import (
    _embedded_installer_namespace,
    _workspace_tempdir,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "1" * 40


def _load_skill_release():
    path = ROOT / "scripts/release/skill_release.py"
    spec = importlib.util.spec_from_file_location(
        "_test_v262_predecessor_skill_release", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV262PredecessorReleaseIsolation(unittest.TestCase):
    def test_current_helper_rejects_shared_flow_predecessors_before_identity(self) -> None:
        release = _load_skill_release()
        identity = {
            "source_commit": SOURCE,
            "source_git_tree": "2" * 40,
            "tag": "v2.6",
            "tag_state": "absent",
            "tag_target_commit": None,
        }
        forged_v262_flow = SimpleNamespace(
            derive_release_plan=mock.Mock(
                return_value={"generation_id": "V2.62", "release_ready": False}
            )
        )
        for version in ("V2.50", "V2.52", "V2.6"):
            with self.subTest(version=version):
                with mock.patch.object(
                    release, "_read_identity", return_value=identity
                ) as identity_reader, mock.patch.object(
                    release,
                    "_v250_release_flow_module",
                    return_value=forged_v262_flow,
                ) as flow_loader:
                    with self.assertRaises(release.SkillReleaseError) as caught:
                        release.plan(version, SOURCE)
                self.assertEqual(
                    "E_SKILL_RELEASE_PREDECESSOR_FLOW_UNAVAILABLE",
                    caught.exception.receipt["error_code"],
                )
                identity_reader.assert_not_called()
                flow_loader.assert_not_called()

    def test_direct_flow_loader_rejects_predecessor_identity(self) -> None:
        release = _load_skill_release()
        with mock.patch.object(release, "_v250_release_flow_module") as loader:
            with self.assertRaises(release.SkillReleaseError) as caught:
                release._release_flow_module("V2.6")
        self.assertEqual(
            "E_SKILL_RELEASE_PREDECESSOR_FLOW_UNAVAILABLE",
            caught.exception.receipt["error_code"],
        )
        loader.assert_not_called()

    def test_installer_uses_v250_runtime_for_published_v26_bundle(self) -> None:
        with _workspace_tempdir("goal-teams-v26-installer-") as directory:
            work = Path(directory)
            runtime = _embedded_installer_namespace(work)
            root = work / "v26-package"
            (root / "references/current").mkdir(parents=True)
            (root / "scripts/v250").mkdir(parents=True)
            (root / "scripts/checks").mkdir(parents=True)
            (root / "references/current/ACTIVE.json").write_text(
                json.dumps({"generation_id": "V2.6"}), encoding="utf-8"
            )
            for relative in (
                "scripts/v250/generation_runtime.py",
                "scripts/v250/route_closure.py",
                "scripts/checks/check-v250.py",
            ):
                (root / relative).write_text("# fixture\n", encoding="utf-8")

            generation = {
                "generation_id": "V2.6",
                "activation_digest_verified": True,
                "activation_manifest_sha256": "a" * 64,
                "prompt_manifest_sha256": "b" * 64,
            }
            closure = {
                "loaded_paths": ["references/current/generations/V2.6/core.md"],
                "legacy_intersection": [],
            }
            runtime["load_v250_prompt_modules"] = lambda _root: (
                SimpleNamespace(load_generation=lambda _root: generation),
                SimpleNamespace(compile_route_closure=lambda *_args, **_kwargs: closure),
            )
            identity = runtime["compute_prompt_identity"](root)
            expected_runtime_digest = hashlib.sha256(
                json.dumps(
                    {
                        "generation_id": "V2.6",
                        "activation_manifest_sha256": "a" * 64,
                        "prompt_manifest_sha256": "b" * 64,
                        "route_id": "V250-ROUTE-STARTUP",
                        "loaded_paths": closure["loaded_paths"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(expected_runtime_digest, identity["runtime_prompt_digest"])

            runtime["source_info"].update(
                {
                    "prefix_manifest_sha256": identity["prefix_manifest_sha256"],
                    "route_static_digest": identity["route_static_digest"],
                    "runtime_prompt_refs": identity["ordered_refs"],
                }
            )
            observed: list[list[str]] = []

            def fake_run(argv, **_kwargs):
                observed.append([str(item) for item in argv])
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            runtime["run"] = fake_run
            runtime["validate_skill"](root, "v26_bundle")
            self.assertTrue(observed)
            self.assertTrue(observed[0][1].endswith("scripts/checks/check-v250.py"))


if __name__ == "__main__":
    unittest.main()
