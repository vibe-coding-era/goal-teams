"""Generation-aware control vocabulary and asset registry.

The registry is deliberately small and side-effect free.  It provides one
normalization surface for compiler/checker vocabulary and records when new
control assets first become applicable.  Unknown terms and unknown assets are
not silently accepted.
"""

from __future__ import annotations

import fnmatch
import re
from types import MappingProxyType
from typing import Final


GENERATION_RE: Final = re.compile(r"^V([0-9]+)\.([0-9]+)$")


class ControlRegistryError(RuntimeError):
    """Stable fail-closed control registry error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


_VOCABULARIES = MappingProxyType(
    {
        "phase": frozenset(
            {
                "discussion",
                "development",
                "release_readiness",
                "release",
            }
        ),
        "gate": frozenset(
            {
                "loop_bootstrap",
                "project_start_authorization",
                "environment_preflight",
                "development_environment_check",
                "tdd",
                "incremental",
                "semantic_review",
                "behavior_review",
                "completion_audit",
                "independent_review",
                "runtime_capability",
                "desktop_runtime",
                "ui_e2e",
                "pixel_comparison",
                "fresh_runtime_transition",
                "full_regression",
                "release_security_review",
                "repository_boundary_compliance",
                "s0",
                "s1",
                "s2",
                "s3",
                "s4",
            }
        ),
        "assurance": frozenset({"discussion", "lite", "standard", "full"}),
        "receipt_strength": frozenset(
            {"planned", "correlated", "observed", "provider_verified"}
        ),
        "completion_axis": frozenset(
            {
                "engineering_complete",
                "runtime_complete",
                "business_validated",
                "release_ready",
                "released",
            }
        ),
        "state_axis": frozenset(
            {"task", "check", "evidence", "audit", "run", "goal"}
        ),
    }
)

_ALIASES = MappingProxyType(
    {
        "phase": MappingProxyType({}),
        "gate": MappingProxyType(
            {
                # ``authorization`` was emitted by the first V2.63 route
                # prototype. Runtime closure uses one canonical project-start
                # authorization gate; the raw spelling remains parseable for
                # byte-compatible receipts and frozen TDD evidence.
                "authorization": "project_start_authorization",
                # V2.62 prompt manifests used this spelling while the checker
                # consumed ``full_regression``.
                "final_full_regression": "full_regression",
                "affected_scope_incremental": "incremental",
                "large_release_install": "s3",
                "publish_readback": "s4",
            }
        ),
        "assurance": MappingProxyType(
            {
                "Discussion": "discussion",
                "Lite": "lite",
                "Standard": "standard",
                "Full": "full",
            }
        ),
        "receipt_strength": MappingProxyType({}),
        "completion_axis": MappingProxyType({}),
        "state_axis": MappingProxyType({}),
    }
)


# These assets are intentionally present while ACTIVE still points at V2.62.
# They become mandatory control-closure members only for a V2.63 generation.
# Unknown new dynamic control assets retain the historical fail-closed default.
_INTRODUCED_ASSET_PATTERNS: Final = (
    ("V2.63", "scripts/v250/control_registry.py"),
    ("V2.63", "scripts/v250/discovery_policy.py"),
    ("V2.63", "scripts/v250/semantic_closure.py"),
    ("V2.63", "scripts/v250/git_change_receipt.py"),
    ("V2.63", "scripts/v250/prompt_compiler.py"),
    ("V2.63", "scripts/v250/route_derivation.py"),
    ("V2.63", "scripts/v250/runtime_session.py"),
    ("V2.63", "scripts/v250/state_reducer.py"),
    ("V2.63", "scripts/v250/task_plan_compiler.py"),
    ("V2.63", "scripts/v250/turn_receipt.py"),
    ("V2.63", "schemas/v2.50/control-registry.schema.json"),
    ("V2.63", "schemas/v2.50/active-generation.schema.json"),
    ("V2.63", "schemas/v2.50/discovery-snapshot.schema.json"),
    ("V2.63", "schemas/v2.50/prompt-manifest.schema.json"),
    ("V2.63", "schemas/v2.50/git-change-receipt.schema.json"),
    ("V2.63", "schemas/v2.50/route-prompt.schema.json"),
    ("V2.63", "schemas/v2.50/runtime-session-turn.schema.json"),
    ("V2.63", "schemas/v2.50/state-ledger.schema.json"),
    ("V2.63", "schemas/v2.50/task-plan.schema.json"),
    ("V2.63", "tests/v250/test_v263_*.py"),
    ("V2.65", "tests/v250/test_v265_*.py"),
)


def _generation_key(generation_id: str) -> tuple[int, int]:
    if not isinstance(generation_id, str):
        raise ControlRegistryError(
            "E_CONTROL_REGISTRY_GENERATION",
            "generation_id must be a version string",
        )
    matched = GENERATION_RE.fullmatch(generation_id)
    if matched is None:
        raise ControlRegistryError(
            "E_CONTROL_REGISTRY_GENERATION",
            f"invalid generation_id: {generation_id!r}",
        )
    return int(matched.group(1)), int(matched.group(2))


def resolve_control_term(vocabulary: str, value: str) -> str:
    """Resolve a canonical term or declared migration alias."""

    values = _VOCABULARIES.get(vocabulary)
    aliases = _ALIASES.get(vocabulary)
    if values is None or aliases is None or not isinstance(value, str):
        raise ControlRegistryError(
            "E_CONTROL_REGISTRY_UNKNOWN_TERM",
            f"unknown {vocabulary!r} term: {value!r}",
        )
    resolved = aliases.get(value, value)
    if resolved not in values:
        raise ControlRegistryError(
            "E_CONTROL_REGISTRY_UNKNOWN_TERM",
            f"unknown {vocabulary!r} term: {value!r}",
        )
    return resolved


def control_asset_introduced_in(relative_path: str) -> str | None:
    """Return the first generation for a registered staged control asset."""

    for generation_id, pattern in _INTRODUCED_ASSET_PATTERNS:
        if fnmatch.fnmatchcase(relative_path, pattern):
            return generation_id
    return None


def is_control_asset_applicable(relative_path: str, *, generation_id: str) -> bool:
    """Whether an asset is part of the dynamic closure for ``generation_id``.

    Unregistered assets keep the pre-V2.63 behavior and are applicable.  This
    preserves fail-closed detection for arbitrary unbound control files while
    allowing explicitly staged V2.63 assets to coexist with Current V2.62.
    """

    introduced_in = control_asset_introduced_in(relative_path)
    if introduced_in is None:
        _generation_key(generation_id)
        return True
    return _generation_key(generation_id) >= _generation_key(introduced_in)


def export_control_registry() -> dict[str, object]:
    """Return the deterministic machine projection consumed by Schema checks."""

    return {
        "schema_version": "goal-teams-control-registry-v2.65",
        "vocabularies": {
            name: sorted(values) for name, values in sorted(_VOCABULARIES.items())
        },
        "aliases": {
            name: dict(sorted(values.items()))
            for name, values in sorted(_ALIASES.items())
        },
        "assets": sorted(
            (
                {
                    "introduced_in": generation_id,
                    "path_pattern": pattern,
                }
                for generation_id, pattern in _INTRODUCED_ASSET_PATTERNS
            ),
            key=lambda item: item["path_pattern"],
        ),
    }


__all__ = [
    "ControlRegistryError",
    "control_asset_introduced_in",
    "export_control_registry",
    "is_control_asset_applicable",
    "resolve_control_term",
]
