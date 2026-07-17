from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "b" * 40
WORKFLOW_BLOB = "c" * 40
JOBS = ("check-ubuntu", "check-macos", "release-asset-gate")


def _load_auditor():
    path = ROOT / "scripts" / "release" / "audit-release.py"
    spec = importlib.util.spec_from_file_location("goal_teams_v240_audit_provenance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = _load_auditor()


def _stage(*, post: bool) -> dict[str, object]:
    run_id = 24017 if post else 24013
    return {
        "head_sha": COMMIT,
        "workflow_path": ".github/workflows/release-gate.yml",
        "workflow_blob_sha": WORKFLOW_BLOB,
        "workflow_id": 240,
        "run_id": run_id,
        "run_attempt": 1,
        "event": "workflow_dispatch" if post else "push",
        "actor_id": 253628811,
        "triggering_actor_id": 253628811,
        "created_at": "2026-07-14T08:02:00Z" if post else "2026-07-14T07:00:00Z",
        "jobs": [
            {"name": name, "head_sha": COMMIT, "conclusion": "success"}
            for name in JOBS
        ],
    }


def _observation() -> dict[str, object]:
    surfaces = ("main", "tag", "release", "asset", "installed")
    readme_zh = hashlib.sha256(b"README.md V2.40\n").hexdigest()
    readme_en = hashlib.sha256(b"README.en.md V2.40\n").hexdigest()
    return {
        "version": "V2.40",
        "tag": "v2.40",
        "latest_release_tag": "v2.40",
        "release_published_at": "2026-07-14T08:00:00Z",
        "release_actor_id": 253628811,
        "commits": {surface: COMMIT for surface in surfaces},
        "readme_sha256": {
            "README.md": {surface: readme_zh for surface in surfaces},
            "README.en.md": {surface: readme_en for surface in surfaces},
        },
        "ci": {"candidate": _stage(post=False), "post_release": _stage(post=True)},
    }


class V240AuditProvenanceTests(unittest.TestCase):
    def test_accepts_two_exact_distinct_live_ci_runs(self) -> None:
        receipt = audit.audit_release_identity(_observation())
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["ci"]["candidate"]["event"], "push")
        self.assertEqual(
            receipt["ci"]["post_release"]["event"], "workflow_dispatch"
        )

    def test_rejects_wrong_post_event(self) -> None:
        observation = _observation()
        observation["ci"]["post_release"]["event"] = "push"
        with self.assertRaisesRegex(Exception, "E_V240_POST_RELEASE_CI"):
            audit.audit_release_identity(observation)

    def test_rejects_nonpositive_actor_and_job_head_drift(self) -> None:
        for mutate in ("actor", "triggering_actor", "job_head"):
            observation = _observation()
            if mutate == "actor":
                observation["ci"]["candidate"]["actor_id"] = 0
            elif mutate == "triggering_actor":
                observation["ci"]["candidate"]["run_attempt"] = 2
                observation["ci"]["candidate"]["triggering_actor_id"] = 241
            else:
                observation["ci"]["candidate"]["jobs"][0]["head_sha"] = "a" * 40
            with self.subTest(mutate=mutate), self.assertRaisesRegex(
                Exception, "E_V240_CANDIDATE_CI"
            ):
                audit.audit_release_identity(observation)

    def test_rejects_reused_or_prepublication_post_run(self) -> None:
        reused = _observation()
        reused["ci"]["post_release"]["run_id"] = reused["ci"]["candidate"][
            "run_id"
        ]
        before = _observation()
        before["ci"]["post_release"]["created_at"] = "2026-07-14T07:59:59Z"
        for name, observation in (("reused", reused), ("before", before)):
            with self.subTest(name=name), self.assertRaisesRegex(
                Exception, "E_V240_POST_RELEASE_CI"
            ):
                audit.audit_release_identity(observation)


if __name__ == "__main__":
    unittest.main()
