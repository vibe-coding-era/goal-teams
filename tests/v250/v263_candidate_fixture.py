from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


V263_ACTIVATION_PATH = (
    "references/current/generations/V2.63/activation-manifest.json"
)
V262_ACTIVATION_PATH = (
    "references/current/generations/V2.62/activation-manifest.json"
)
ACTIVE_PATH = "references/current/ACTIVE.json"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", "develops", "docs", "__pycache__", ".DS_Store"}
    return set(names) & ignored


@dataclass(frozen=True)
class CandidateFixture:
    root: Path
    activation_path: str
    activation_sha256: str


class InactiveCandidateFixture:
    """Build a phase-independent, digest-selected V2.63 candidate repository."""

    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root.resolve()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> CandidateFixture:
        develops = self.source_root / "develops"
        develops.mkdir(exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="v263-inactive-candidate-", dir=develops
        )
        fixture_root = Path(self._temporary.name) / "repo"
        shutil.copytree(
            self.source_root,
            fixture_root,
            ignore=_copy_ignore,
            copy_function=shutil.copy2,
        )

        predecessor_path = fixture_root / V262_ACTIVATION_PATH
        predecessor_raw = predecessor_path.read_bytes()
        predecessor_sha256 = hashlib.sha256(predecessor_raw).hexdigest()
        active = {
            "schema_version": "goal-teams-active-generation-v1",
            "generation_id": "V2.62",
            "activation_manifest": V262_ACTIVATION_PATH,
            "activation_manifest_sha256": predecessor_sha256,
            "state": "active_current",
            "updated_at": "2026-08-13T00:00:00+08:00",
        }
        (fixture_root / ACTIVE_PATH).write_bytes(_json_bytes(active))

        command = [
            sys.executable,
            "scripts/v250/refresh_generation_manifests.py",
            "--write",
            "--generation-id",
            "V2.63",
            "--predecessor",
            "V2.62",
            "--base-activation-sha256",
            predecessor_sha256,
        ]
        result = subprocess.run(
            command,
            cwd=fixture_root,
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CEILING_DIRECTORIES": str(fixture_root.parent),
            },
        )
        if result.returncode != 0:
            raise AssertionError(
                "failed to build V2.63 inactive candidate fixture: "
                + hashlib.sha256(result.stderr.encode("utf-8")).hexdigest()
                + ": "
                + result.stderr.strip()
            )

        activation_path = fixture_root / V263_ACTIVATION_PATH
        activation_raw = activation_path.read_bytes()
        activation = json.loads(activation_raw.decode("utf-8"))
        prompt = json.loads(
            (
                fixture_root
                / "references/current/generations/V2.63/prompt-manifest.json"
            ).read_text(encoding="utf-8")
        )
        if (
            activation.get("generation_state") != "inactive_candidate"
            or prompt.get("manifest_state") != "inactive_candidate"
        ):
            raise AssertionError("candidate fixture phase identity differs")
        return CandidateFixture(
            root=fixture_root,
            activation_path=V263_ACTIVATION_PATH,
            activation_sha256=hashlib.sha256(activation_raw).hexdigest(),
        )

    def __exit__(self, *_exc: object) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def close(self) -> None:
        self.__exit__()

    def __del__(self) -> None:
        self.close()


def inactive_candidate_fixture(source_root: Path) -> InactiveCandidateFixture:
    return InactiveCandidateFixture(source_root)


__all__ = [
    "CandidateFixture",
    "InactiveCandidateFixture",
    "inactive_candidate_fixture",
]
