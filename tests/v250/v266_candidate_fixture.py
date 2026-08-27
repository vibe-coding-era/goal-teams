"""Shared immutable identities and modules for V2.66 Current release tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from scripts.v266 import release_flow, runtime_transition, s4_executor
from scripts.v266.repository_boundary import build_boundary_receipt
from scripts.v250.route_closure import compile_derived_route_closure
from scripts.v250.route_derivation import derive_route


ROOT = Path(__file__).resolve().parents[2]
TARGET_VERSION = "V2.66"
TARGET_TAG = "v2.66"
TARGET_BRANCH = "codex/develop-v2.66"
PREDECESSOR_VERSION = "V2.65"
PREDECESSOR_TAG = "v2.65"
GENERATION_ROOT = ROOT / "references/current/generations/V2.66"
RELEASE_SCHEMA_ROOT = ROOT / "schemas/v2.66"
RELEASE_PROFILE_PATH = ROOT / "references/release-profiles/v2.66.json"
SOURCE = "1" * 40
TREE = "2" * 40
CAPTURED_AT = "2026-08-26T08:05:00+00:00"
VALIDATION_TIME = dt.datetime(2026, 8, 26, 8, 5, tzinfo=dt.timezone.utc)
ROUTE_ID = "V250-ROUTE-LARGE-RELEASE"
HANDOFF_NONCE = "nonce-v266-controller-handoff-000001"
PUBLISHED_V265_IDENTITY = {
    "tag": "v2.65",
    "release_id": 375434758,
    "state": "published",
    "source_commit": "8512f6b9a7668daa6824b7a97494b927962b299e",
    "source_tree": "fb436dbee231ee6c066cbb00fc9048b3113134ef",
    "public_assets": [
        "goal-teams-V2.65.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    ],
}
V266_ACTIVATION_PATH = (
    "references/current/generations/V2.66/activation-manifest.json"
)
V265_ACTIVATION_PATH = (
    "references/current/generations/V2.65/activation-manifest.json"
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
    """Build a phase-independent V2.66 candidate over active V2.65."""

    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root.resolve()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> CandidateFixture:
        develops = self.source_root / "develops"
        develops.mkdir(exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="v266-inactive-candidate-", dir=develops
        )
        fixture_root = Path(self._temporary.name) / "repo"
        shutil.copytree(
            self.source_root,
            fixture_root,
            ignore=_copy_ignore,
            copy_function=shutil.copy2,
        )

        predecessor_path = fixture_root / V265_ACTIVATION_PATH
        predecessor_raw = predecessor_path.read_bytes()
        predecessor_sha256 = hashlib.sha256(predecessor_raw).hexdigest()
        active = {
            "schema_version": "goal-teams-active-generation-v1",
            "generation_id": PREDECESSOR_VERSION,
            "activation_manifest": V265_ACTIVATION_PATH,
            "activation_manifest_sha256": predecessor_sha256,
            "state": "active_current",
            "updated_at": "2026-08-26T00:00:00+08:00",
        }
        (fixture_root / ACTIVE_PATH).write_bytes(_json_bytes(active))

        command = [
            sys.executable,
            "scripts/v250/refresh_generation_manifests.py",
            "--write",
            "--generation-id",
            TARGET_VERSION,
            "--predecessor",
            PREDECESSOR_VERSION,
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
                "failed to build V2.66 inactive candidate fixture: "
                + hashlib.sha256(result.stderr.encode("utf-8")).hexdigest()
                + ": "
                + result.stderr.strip()
            )

        activation_path = fixture_root / V266_ACTIVATION_PATH
        activation_raw = activation_path.read_bytes()
        activation = json.loads(activation_raw.decode("utf-8"))
        prompt = json.loads(
            (
                fixture_root
                / "references/current/generations/V2.66/prompt-manifest.json"
            ).read_text(encoding="utf-8")
        )
        if (
            activation.get("generation_state") != "inactive_candidate"
            or prompt.get("manifest_state") != "inactive_candidate"
        ):
            raise AssertionError("candidate fixture phase identity differs")
        return CandidateFixture(
            root=fixture_root,
            activation_path=V266_ACTIVATION_PATH,
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


def _runtime_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def _runtime_write(root: Path, relative: str, raw: bytes) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _runtime_activation_payload_sha256(value: dict) -> str:
    payload = dict(value)
    payload.pop("manifest_payload_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _prepare_v266_observer_inputs(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    bootstrap_paths = {
        ".agents/skills/goal-teams/SKILL.md": b"wrapper\n",
        "AGENTS.md": b"agents\n",
        "RULES.md": b"rules\n",
        "SKILL.md": b"skill\n",
    }
    core_path = "references/current/generations/V2.66/core.md"
    core_raw = b"core\n"
    facts_source = {
        "schema_version": "goal-teams-project-route-facts-source-v2.66",
        "repository": "vibe-coding-era/goal-teams",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "workflow_run_id": "10001",
        "workflow_run_attempt": "1",
        "project_start_authorization_receipt_sha256": "3" * 64,
    }
    project_route_facts = {
        "project_size": "large",
        "workflow_phase": "release",
        "stage": "released",
        "release_intent": True,
        "implementation_scope_complete": True,
        "risk": "high",
        "failure_consequence": "high",
        "reversibility": "partially_reversible",
        "compliance": "none",
        "external_write": True,
        "security_sensitive": True,
        "ui_or_desktop": False,
        "agent_runtime": True,
        "environment_check_required": True,
        "authorization_state": "granted",
        "facts_source_sha256": runtime_transition._canonical_sha256(facts_source),
    }
    derived_route = derive_route(project_route_facts, generation_id="V2.66")
    owner = {
        "owner_id": "core",
        "path": core_path,
        "source_sha256": hashlib.sha256(core_raw).hexdigest(),
        "owned_rule_ids": ["GT263-RUNTIME-TEST"],
        "route_membership": [ROUTE_ID],
        "dependencies": [],
    }
    rule_manifest = {"owners": [owner]}
    rule_manifest_path = (
        "references/current/generations/V2.66/rule-manifest.json"
    )
    current_paths = {
        core_path: core_raw,
        rule_manifest_path: _runtime_json_bytes(rule_manifest),
        "references/current/generations/V2.66/prompt-manifest.json": b"",
        "references/profiles/goal-teams-self-release-v2.66.md": b"profile\n",
        "references/release-profiles/v2.66.json": b"{}\n",
        "references/current/generations/V2.66/contracts/release-route-manifest.json": b"{}\n",
        "references/current/generations/V2.66/contracts/release-command-manifest.json": b"{}\n",
        "references/current/generations/V2.66/contracts/predecessor-release-identity.json": _runtime_json_bytes(
            {
                "schema_version": "goal-teams-predecessor-release-identity-v2.66",
                "generation_id": "V2.66",
                "predecessor_product_version": "V2.65",
                "release_identity": PUBLISHED_V265_IDENTITY,
                "release_identity_sha256": hashlib.sha256(
                    json.dumps(
                        PUBLISHED_V265_IDENTITY,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
        ),
    }
    execution_paths = {
        "scripts/checks/check-v266.py": b"checker\n",
        "scripts/v266/release_identity.py": b"release-identity\n",
        "scripts/v266/runtime_host_adapter.py": b"host-adapter\n",
        "scripts/v266/runtime_transition.py": b"observer\n",
    }
    schema_paths = {
        "schemas/v2.66/runtime-transition-receipt.schema.json": (
            runtime_transition.ROOT
            / "schemas/v2.66/runtime-transition-receipt.schema.json"
        ).read_bytes(),
    }
    prompt = {
        "schema_version": "goal-teams-prompt-manifest-v2.50",
        "generation_id": "V2.66",
        "manifest_state": "active_current",
        "routes": {
            ROUTE_ID: {
                "workflow_phase": "release",
                "ordered_refs": [core_path],
                "required_gates": derived_route["required_gates"],
                "conditional_gates": derived_route["conditional_gates"],
                "expected_loaded_rule_bytes": len(core_raw),
                "max_loaded_rule_bytes": len(core_raw),
            }
        },
    }
    current_paths[
        "references/current/generations/V2.66/prompt-manifest.json"
    ] = _runtime_json_bytes(prompt)

    entries: dict[str, list[dict[str, object]]] = {
        "bootstrap": [],
        "current": [],
        "execution": [],
        "schemas_and_validators": [],
    }
    for root_set, paths in (
        ("bootstrap", bootstrap_paths),
        ("current", current_paths),
        ("execution", execution_paths),
        ("schemas_and_validators", schema_paths),
    ):
        for relative, raw in paths.items():
            digest = _runtime_write(root, relative, raw)
            entries[root_set].append(
                {"path": relative, "sha256": digest, "bytes": len(raw)}
            )

    # Mutable published projection remains available to prove it is not part
    # of the V2.66 runtime or predecessor-controller identity closure.
    _runtime_write(
        root,
        "release/current/manifest.json",
        _runtime_json_bytes(
            {
                "schema_version": "goal-teams-release-manifest-v2.65",
                "product_version": "V2.65",
                "release_identity": PUBLISHED_V265_IDENTITY,
                "status": "release",
            }
        ),
    )

    activation = {
        "schema_version": "goal-teams-activation-manifest-v2.50",
        "generation_id": "V2.66",
        "generation_state": "active",
        "identity": {
            "loaded_runtime_product_version": "V2.66",
            "route_contract_schema_version": "goal-teams-project-route-v2.50",
            "target_policy_generation": "V2.66",
        },
        "root_sets": entries,
        "rule_manifest_path": rule_manifest_path,
        "prompt_manifest_path": "references/current/generations/V2.66/prompt-manifest.json",
        "current_default_allowlist": [core_path],
        "legacy_classification": {"exact_paths": [], "path_prefixes": []},
        "budgets": {"max_route_rule_bytes": len(core_raw)},
    }
    activation["manifest_payload_sha256"] = _runtime_activation_payload_sha256(activation)
    activation_path = "references/current/generations/V2.66/activation-manifest.json"
    activation_raw = _runtime_json_bytes(activation)
    activation_digest = _runtime_write(root, activation_path, activation_raw)
    active = {
        "schema_version": "goal-teams-active-generation-v1",
        "generation_id": "V2.66",
        "activation_manifest": activation_path,
        "activation_manifest_sha256": activation_digest,
        "state": "active_current",
    }
    _runtime_write(root, "references/current/ACTIVE.json", _runtime_json_bytes(active))

    generation = {
        "generation_id": "V2.66",
        "activation_digest_verified": True,
        "member_digests_verified": True,
        "activation_manifest": activation,
        "prompt_manifest": prompt,
        "rule_manifest": rule_manifest,
        "current_default_allowlist": [core_path],
        "legacy_exact_paths": [],
        "legacy_path_prefixes": [],
    }
    route = compile_derived_route_closure(root, generation, derived_route)
    route_facts_path = root / "docs/release-route-facts.json"
    derived_route_path = root / "docs/release-route-derived.json"
    route_path = root / "docs/release-route-receipt.json"
    route_path.parent.mkdir(parents=True)
    route_facts_path.write_bytes(
        json.dumps(
            {
                "facts_source": facts_source,
                "project_route_facts": project_route_facts,
                "project_route_facts_sha256": runtime_transition._canonical_sha256(
                    project_route_facts
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    derived_route_path.write_bytes(
        json.dumps(
            derived_route,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    route_path.write_bytes(
        json.dumps(
            route,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    intent = {
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.66",
        "action_allowlist": ["fresh_runtime_transition"],
    }
    authorization = {
        "schema_version": "goal-teams-project-start-authorization-v2.50",
        "receipt_id": "AUTH-V250-TEST",
        "authorization_id": "AUTH-V250-TEST",
        "authorization_state": "granted_once_at_project_start",
        "authorization_lineage_preserved": True,
        "repository": {"name_with_owner": "vibe-coding-era/goal-teams"},
        "version": "V2.66",
        "action_allowlist": ["fresh_runtime_transition"],
        "intent": intent,
        "intent_sha256": runtime_transition._canonical_sha256(intent),
    }
    authorization_path = root / "docs/authorization-receipt.json"
    authorization_path.write_bytes(_runtime_json_bytes(authorization))

    adapter_path = root / "docs/trusted-runtime-adapter.py"
    adapter_path.write_bytes(b"# trusted host adapter\n")
    return (
        route_facts_path,
        derived_route_path,
        route_path,
        authorization_path,
        adapter_path,
    )


def _v266_handoff(authorization_path: Path) -> dict:
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    signed_payload = {
        "repository": "vibe-coding-era/goal-teams",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "authorization_id": authorization["authorization_id"],
        "authorization_receipt_sha256": hashlib.sha256(
            authorization_path.read_bytes()
        ).hexdigest(),
        "authorization_intent_sha256": authorization["intent_sha256"],
        "previous_controller_product_version": "V2.65",
        "previous_run_id": "V265-HOST-RUN-0001",
        "nonce": HANDOFF_NONCE,
        "issued_at": "2026-08-26T08:00:00+00:00",
        "expires_at": "2026-08-26T08:10:00+00:00",
        "installed_v265_current_state": {
            "source_commit": PUBLISHED_V265_IDENTITY["source_commit"],
            "source_tree": PUBLISHED_V265_IDENTITY["source_tree"],
            "tag": PUBLISHED_V265_IDENTITY["tag"],
            "release_id": PUBLISHED_V265_IDENTITY["release_id"],
        },
        "github_signing_identity": {
            "account": "vibe-coding-era",
            "key_id": 152596014,
            "public_key": (
                "ssh-ed25519 "
                "AAAAC3NzaC1lZDI1NTE5AAAAIJ7qqfn52U2nhALTYS8ofXEwJwIq6GispivX9W/NG2Ot"
            ),
            "public_key_fingerprint": (
                "SHA256:fEM2bYLJFOSvNA78soiWLvrSUaWxANVr1HIVl6AAirE"
            ),
            "ssh_signature_namespace": "goal-teams-v2.66-controller-handoff",
        },
    }
    installed = signed_payload["installed_v265_current_state"]
    installed["state_sha256"] = runtime_transition._canonical_sha256(
        installed, digest_field="state_sha256"
    )
    return {
        "schema_version": "goal-teams-v2.66-controller-handoff-receipt-v1",
        "signed_payload": signed_payload,
        "payload_sha256": runtime_transition._canonical_sha256(signed_payload),
        "ssh_signature": (
            "-----BEGIN SSH SIGNATURE-----\n"
            "Zm9yZ2VkLXRlc3Qtc2lnbmF0dXJl\n"
            "-----END SSH SIGNATURE-----\n"
        ),
    }


def _v266_launch(handoff: dict, adapter_path: Path) -> dict:
    value = {
        "schema_version": "goal-teams-v2.66-runtime-launch-receipt-v1",
        "controller_handoff_receipt_sha256": runtime_transition.object_sha256(handoff),
        "controller_handoff_payload_sha256": handoff["payload_sha256"],
        "nonce": HANDOFF_NONCE,
        "parent_pid": os.getppid(),
        "expected_child_pid": os.getpid(),
        "host_execution_id": "GITHUB-RUN-10001",
        "new_run_id": "V266-RUNTIME-RUN-0001",
        "launched_at": CAPTURED_AT,
        "adapter_identity": "codex-host-runtime-adapter",
        "adapter_code_sha256": hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
    }
    value["receipt_sha256"] = runtime_transition._canonical_sha256(value)
    return value


def observe_runtime_transition(root: Path) -> dict:
    (
        route_facts_path,
        derived_route_path,
        route_path,
        authorization_path,
        adapter_path,
    ) = _prepare_v266_observer_inputs(root)
    handoff = _v266_handoff(authorization_path)
    launch = _v266_launch(handoff, adapter_path)
    with mock.patch.object(
        runtime_transition, "_verify_handoff_signature", return_value=True
    ):
        return runtime_transition.observe_transition(
            stage="released",
            source_commit=SOURCE,
            source_tree=TREE,
            project_size="large",
            route_facts_receipt_path=route_facts_path,
            derived_route_receipt_path=derived_route_path,
            route_receipt_path=route_path,
            authorization_receipt_path=authorization_path,
            adapter_identity="codex-host-runtime-adapter",
            adapter_code_path=adapter_path,
            controller_handoff_receipt=handoff,
            runtime_launch_receipt=launch,
            captured_at=CAPTURED_AT,
            transition_id="TRANSITION-1",
            validation_time=VALIDATION_TIME,
            root=root,
        )


__all__ = [
    "GENERATION_ROOT",
    "CandidateFixture",
    "InactiveCandidateFixture",
    "PREDECESSOR_TAG",
    "PREDECESSOR_VERSION",
    "RELEASE_PROFILE_PATH",
    "RELEASE_SCHEMA_ROOT",
    "ROOT",
    "TARGET_BRANCH",
    "TARGET_TAG",
    "TARGET_VERSION",
    "build_boundary_receipt",
    "inactive_candidate_fixture",
    "observe_runtime_transition",
    "release_flow",
    "runtime_transition",
    "s4_executor",
]
