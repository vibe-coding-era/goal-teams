#!/usr/bin/env python3
"""Independent, observation-only Goal Teams V2.40 release auditor.

The auditor deliberately ignores promotion-state success booleans.  Its verdict
is reconstructed from five commit identities, README byte digests, Latest
Release identity, and exact post-release CI observations supplied by the caller.
The public release entry supplies those observations only from its independent
live collector; promotion-state pass/fail fields are never accepted here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_POINTS = ["main", "tag", "release", "asset", "installed"]
README_FILES = ["README.en.md", "README.md"]
RELEASE_GATE_JOBS = {"check-ubuntu", "check-macos", "release-asset-gate"}
RELEASE_GATE_WORKFLOW = ".github/workflows/release-gate.yml"


class AuditError(RuntimeError):
    """Independent audit failure with a zero-effect machine receipt."""

    def __init__(self, error_code: str, message: str) -> None:
        self.receipt = {
            "passed": False,
            "error_code": error_code,
            "mutation_count": 0,
            "external_side_effect_count": 0,
        }
        super().__init__(f"{error_code}: {message}")


def _fail(error_code: str, message: str) -> None:
    raise AuditError(error_code, message)


def _jobs_succeeded(
    jobs: Any,
    required_names: set[str] | None = None,
    *,
    head_sha: str | None = None,
) -> bool:
    if not isinstance(jobs, Sequence) or isinstance(jobs, (str, bytes)):
        return False
    records = [
        job
        for job in jobs
        if isinstance(job, Mapping) and isinstance(job.get("name"), str)
    ]
    if len(records) != len(jobs):
        return False
    names = {str(job["name"]) for job in records}
    if required_names is not None and names != required_names:
        return False
    return all(
        job.get("conclusion") == "success"
        and (head_sha is None or job.get("head_sha") == head_sha)
        for job in records
    )


def _parse_utc(value: Any, error_code: str = "E_V240_POST_RELEASE_CI") -> datetime:
    if not isinstance(value, str) or not value:
        _fail(error_code, "CI timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(error_code, "CI timestamp is invalid")
    if parsed.tzinfo is None:
        _fail(error_code, "CI timestamp lacks a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_ci_stage(
    stage: str,
    value: Any,
    *,
    source_commit: str,
    release_actor_id: int,
) -> dict[str, Any]:
    error_code = (
        "E_V240_CANDIDATE_CI" if stage == "candidate" else "E_V240_POST_RELEASE_CI"
    )
    expected_event = "push" if stage == "candidate" else "workflow_dispatch"
    if not isinstance(value, Mapping):
        _fail(error_code, f"{stage} CI live receipt is missing")
    if (
        value.get("head_sha") != source_commit
        or value.get("workflow_path") != RELEASE_GATE_WORKFLOW
        or SHA40_RE.fullmatch(str(value.get("workflow_blob_sha", ""))) is None
        or not isinstance(value.get("workflow_id"), int)
        or isinstance(value.get("workflow_id"), bool)
        or value.get("workflow_id", 0) < 1
        or not isinstance(value.get("run_id"), int)
        or isinstance(value.get("run_id"), bool)
        or value.get("run_id", 0) < 1
        or not isinstance(value.get("run_attempt"), int)
        or isinstance(value.get("run_attempt"), bool)
        or value.get("run_attempt", 0) < 1
        or value.get("event") != expected_event
        or not isinstance(value.get("actor_id"), int)
        or isinstance(value.get("actor_id"), bool)
        or value.get("actor_id") != release_actor_id
        or not isinstance(value.get("triggering_actor_id"), int)
        or isinstance(value.get("triggering_actor_id"), bool)
        or value.get("triggering_actor_id") != release_actor_id
    ):
        _fail(error_code, f"{stage} CI provenance is not exact")
    created_at = _parse_utc(value.get("created_at"), error_code)
    if not _jobs_succeeded(
        value.get("jobs"), RELEASE_GATE_JOBS, head_sha=source_commit
    ):
        _fail(error_code, f"{stage} exact-SHA CI jobs are not successful")
    return {
        "head_sha": source_commit,
        "workflow_path": RELEASE_GATE_WORKFLOW,
        "workflow_blob_sha": value["workflow_blob_sha"],
        "workflow_id": value["workflow_id"],
        "run_id": value["run_id"],
        "run_attempt": value["run_attempt"],
        "event": expected_event,
        "actor_id": value["actor_id"],
        "triggering_actor_id": value["triggering_actor_id"],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "jobs": [
            {
                "name": job["name"],
                "head_sha": job["head_sha"],
                "conclusion": job["conclusion"],
            }
            for job in value["jobs"]
        ],
    }


def audit_release_identity(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild stable-release truth from raw observations only."""

    if not isinstance(observation, Mapping):
        _fail("E_V240_FIVE_POINT_IDENTITY", "observation must be an object")
    version = observation.get("version")
    tag = observation.get("tag")
    expected_tag = str(version).lower() if isinstance(version, str) else None
    commits = observation.get("commits")
    if not isinstance(commits, Mapping):
        _fail("E_V240_FIVE_POINT_IDENTITY", "five commit observations are missing")
    values = [commits.get(point) for point in IDENTITY_POINTS]
    if (
        any(not isinstance(value, str) or SHA40_RE.fullmatch(value) is None for value in values)
        or len(set(values)) != 1
    ):
        _fail(
            "E_V240_FIVE_POINT_IDENTITY",
            "main/tag/release/asset/installed commits differ",
        )
    source_commit = values[0]

    readmes = observation.get("readme_sha256")
    if not isinstance(readmes, Mapping) or set(readmes) != set(README_FILES):
        _fail("E_V240_README_BYTE_IDENTITY", "README observations are incomplete")
    readme_receipts: dict[str, str] = {}
    for name in README_FILES:
        surfaces = readmes.get(name)
        if not isinstance(surfaces, Mapping) or set(surfaces) != set(IDENTITY_POINTS):
            _fail(
                "E_V240_README_BYTE_IDENTITY",
                f"{name} does not cover all five surfaces",
            )
        digests = [surfaces.get(point) for point in IDENTITY_POINTS]
        if (
            any(
                not isinstance(digest, str)
                or SHA256_RE.fullmatch(digest) is None
                for digest in digests
            )
            or len(set(digests)) != 1
        ):
            _fail(
                "E_V240_README_BYTE_IDENTITY",
                f"{name} bytes differ across release surfaces",
            )
        readme_receipts[name] = digests[0]

    latest = observation.get("latest_release_tag")
    if (
        not isinstance(tag, str)
        or tag != expected_tag
        or latest != tag
    ):
        _fail("E_V240_LATEST_RELEASE", "Latest Release does not equal target tag")

    ci = observation.get("ci")
    if not isinstance(ci, Mapping):
        _fail("E_V240_POST_RELEASE_CI", "CI observations are missing")
    release_actor_id = observation.get("release_actor_id")
    if (
        not isinstance(release_actor_id, int)
        or isinstance(release_actor_id, bool)
        or release_actor_id < 1
    ):
        _fail("E_V240_POST_RELEASE_CI", "release actor authority is missing")
    candidate_ci = _validate_ci_stage(
        "candidate",
        ci.get("candidate"),
        source_commit=source_commit,
        release_actor_id=release_actor_id,
    )
    post_ci = _validate_ci_stage(
        "post_release",
        ci.get("post_release"),
        source_commit=source_commit,
        release_actor_id=release_actor_id,
    )
    if candidate_ci["workflow_blob_sha"] != post_ci["workflow_blob_sha"]:
        _fail("E_V240_POST_RELEASE_CI", "candidate/post workflow blob differs")
    if candidate_ci["run_id"] == post_ci["run_id"]:
        _fail("E_V240_POST_RELEASE_CI", "candidate/post CI reused one run")
    release_published_at = _parse_utc(observation.get("release_published_at"))
    if _parse_utc(candidate_ci["created_at"], "E_V240_CANDIDATE_CI") >= release_published_at:
        _fail("E_V240_CANDIDATE_CI", "candidate CI did not precede publication")
    if _parse_utc(post_ci["created_at"]) <= release_published_at:
        _fail("E_V240_POST_RELEASE_CI", "post-release CI predates publication")

    return {
        "passed": True,
        "mutation_count": 0,
        "external_side_effect_count": 0,
        "version": version,
        "tag": tag,
        "latest_release_tag": latest,
        "source_commit": source_commit,
        "identity_points": list(IDENTITY_POINTS),
        "readme_files": list(README_FILES),
        "readme_sha256": readme_receipts,
        "release_published_at": release_published_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "release_actor_id": release_actor_id,
        "ci": {"candidate": candidate_ci, "post_release": post_ci},
        "decision_source": "independent_raw_observations",
    }


def main() -> int:
    # No live CLI adapter is bundled here.  A caller should import the pure
    # function after independently collecting observations.
    receipt = {
        "passed": False,
        "error_code": "E_V240_AUDIT_OBSERVATIONS_REQUIRED",
        "mutation_count": 0,
        "external_side_effect_count": 0,
    }
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
