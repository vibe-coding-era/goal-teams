"""Phase-independent V2.63 activation lifecycle test fixture.

The source repository may already point at V2.63.  Lifecycle tests must still
exercise the V2.62 -> prepared V2.63 -> active V2.63 transition, so every test
copy reconstructs that predecessor identity explicitly instead of inheriting
the source repository's mutable ACTIVE pointer.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys


ACTIVE = pathlib.Path("references/current/ACTIVE.json")
V262_ACTIVATION = pathlib.Path(
    "references/current/generations/V2.62/activation-manifest.json"
)
V263_ACTIVATION = pathlib.Path(
    "references/current/generations/V2.63/activation-manifest.json"
)
REFRESH = pathlib.Path("scripts/v250/refresh_generation_manifests.py")
V262_ACTIVATED_AT = "2026-08-07T18:00:00+08:00"


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class V263ActivationFixture:
    """Own one isolated repository with an explicit V2.62 base identity."""

    def __init__(
        self,
        source_root: pathlib.Path,
        root: pathlib.Path,
        *,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.source_root = source_root.resolve(strict=True)
        self.root = root.resolve(strict=True)
        self.environment = dict(os.environ if environment is None else environment)
        self.base_active_raw = b""
        self.base_active_sha256 = ""
        self.base_activation_sha256 = ""
        self.prepared_activation_sha256: str | None = None

    @classmethod
    def copy_from(
        cls,
        source_root: pathlib.Path,
        root: pathlib.Path,
        *,
        environment: dict[str, str] | None = None,
    ) -> "V263ActivationFixture":
        shutil.copytree(
            source_root,
            root,
            ignore=shutil.ignore_patterns(
                ".git", "docs", "develops", "__pycache__", "*.pyc"
            ),
        )
        fixture = cls(source_root, root, environment=environment)
        fixture.restore_v262_base()
        return fixture

    def restore_v262_base(self) -> bytes:
        """Restore exact predecessor assets and synthesize its ACTIVE pointer."""

        activation_raw = (self.source_root / V262_ACTIVATION).read_bytes()
        try:
            activation = json.loads(activation_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssertionError("V2.62 fixture activation is invalid JSON") from exc
        if (
            not isinstance(activation, dict)
            or activation.get("schema_version")
            != "goal-teams-activation-manifest-v2.50"
            or activation.get("generation_id") != "V2.62"
            or activation.get("generation_state") != "active"
        ):
            raise AssertionError("V2.62 fixture activation identity is invalid")

        activation_target = self.root / V262_ACTIVATION
        activation_target.parent.mkdir(parents=True, exist_ok=True)
        activation_target.write_bytes(activation_raw)
        activation_sha256 = sha256(activation_raw)
        active_raw = json_bytes(
            {
                "schema_version": "goal-teams-active-generation-v1",
                "generation_id": "V2.62",
                "activation_manifest": V262_ACTIVATION.as_posix(),
                "activation_manifest_sha256": activation_sha256,
                "state": "active_current",
                "updated_at": V262_ACTIVATED_AT,
            }
        )
        active_target = self.root / ACTIVE
        active_target.parent.mkdir(parents=True, exist_ok=True)
        active_target.write_bytes(active_raw)
        if (
            activation_target.read_bytes() != activation_raw
            or active_target.read_bytes() != active_raw
        ):
            raise AssertionError("V2.62 fixture exact readback failed")

        self.base_active_raw = active_raw
        self.base_active_sha256 = sha256(active_raw)
        self.base_activation_sha256 = activation_sha256
        self.prepared_activation_sha256 = None
        return active_raw

    def run_refresh(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / REFRESH), *arguments],
            cwd=self.root,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def prepare_v263(self) -> subprocess.CompletedProcess[str]:
        """Rebuild prepared V2.63 assets from the explicit V2.62 base."""

        self.restore_v262_base()
        result = self.run_refresh(
            "--prepare-active",
            "--generation-id",
            "V2.63",
            "--predecessor",
            "V2.62",
            "--base-active-sha256",
            self.base_active_sha256,
            "--base-activation-sha256",
            self.base_activation_sha256,
        )
        if result.returncode == 0:
            prepared_raw = (self.root / V263_ACTIVATION).read_bytes()
            prepared = json.loads(prepared_raw.decode("utf-8"))
            if (
                prepared.get("generation_id") != "V2.63"
                or prepared.get("generation_state") != "active"
                or (self.root / ACTIVE).read_bytes() != self.base_active_raw
            ):
                raise AssertionError("V2.63 prepared fixture identity is invalid")
            self.prepared_activation_sha256 = sha256(prepared_raw)
        return result
