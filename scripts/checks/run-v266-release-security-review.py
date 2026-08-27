#!/usr/bin/env python3
"""Run the V2.66 exact released-implementation security review.

The scanning engine remains the V2.50 policy implementation, but every
generation-specific identity, contract path, runner identity, and mandatory
target is rebound before execution.  The published V2.65 helper keeps its
unchanged defaults when invoked directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GENERATION_ID = "V2.66"
CONTRACT_PATH = (
    "references/current/generations/V2.66/contracts/"
    "release-security-review-manifest.json"
)
COMMAND_CONTRACT_PATH = (
    "references/current/generations/V2.66/contracts/"
    "release-command-manifest.json"
)
RECEIPT_SCHEMA_VERSION = "goal-teams-v2.66-release-gate-receipt-v1"
RUNNER_PATH = "scripts/checks/run-v266-release-security-review.py"


def _load_base() -> ModuleType:
    path = ROOT / "scripts/checks/run-v250-release-security-review.py"
    spec = importlib.util.spec_from_file_location("_goalteams_v250_security_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("E_V266_SECURITY_REVIEW_BASE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_base()
_TARGET_REPLACEMENTS = {
    "references/current/generations/V2.65/contracts/public-asset-map.json":
        "references/current/generations/V2.66/contracts/public-asset-map.json",
    "references/current/generations/V2.65/contracts/release-command-manifest.json":
        "references/current/generations/V2.66/contracts/release-command-manifest.json",
    "references/current/generations/V2.65/contracts/release-route-manifest.json":
        "references/current/generations/V2.66/contracts/release-route-manifest.json",
    "references/current/generations/V2.65/contracts/release-security-review-manifest.json":
        CONTRACT_PATH,
    "references/current/generations/V2.65/functions/knowledge-graph.md":
        "references/current/generations/V2.66/functions/knowledge-graph.md",
    "references/current/generations/V2.65/functions/graph-engineering.md":
        "references/current/generations/V2.66/functions/graph-engineering.md",
    "references/current/generations/V2.65/contracts/loop-evolution.md":
        "references/current/generations/V2.66/contracts/loop-evolution.md",
    "schemas/v2.65/compatibility-manifest.schema.json":
        "schemas/v2.66/compatibility-manifest.schema.json",
    "schemas/v2.65/runtime-binding.schema.json":
        "schemas/v2.66/runtime-binding.schema.json",
    "schemas/v2.50/release-control.schema.json":
        "schemas/v2.66/release-control.schema.json",
    "scripts/v250/repository_boundary.py": "scripts/v266/repository_boundary.py",
    "scripts/v265/compatibility.py": "scripts/v266/compatibility.py",
    "scripts/v265/project_host_assets.py": "scripts/v266/project_host_assets.py",
    "scripts/v265/role_projections.py": "scripts/v266/role_projections.py",
}
_V266_RELEASE_TARGETS = {
    "schemas/v2.66/runtime-transition-receipt.schema.json",
    "scripts/checks/check-v266.py",
    RUNNER_PATH,
    "scripts/v266/release_identity.py",
    "scripts/v266/release_flow.py",
    "scripts/v266/repository_boundary.py",
    "scripts/v266/runtime_host_adapter.py",
    "scripts/v266/runtime_transition.py",
    "scripts/v266/s4_executor.py",
}
MANDATORY_REVIEW_TARGETS = frozenset(
    {_TARGET_REPLACEMENTS.get(path, path) for path in _BASE.MANDATORY_REVIEW_TARGETS}
    | _V266_RELEASE_TARGETS
)

# Rebind the shared engine before any delegated function is called.
_BASE.GENERATION_ID = GENERATION_ID
_BASE.CONTRACT_PATH = CONTRACT_PATH
_BASE.COMMAND_CONTRACT_PATH = COMMAND_CONTRACT_PATH
_BASE.RECEIPT_SCHEMA_VERSION = RECEIPT_SCHEMA_VERSION
_BASE.RUNNER_PATH = RUNNER_PATH
_BASE.MANDATORY_REVIEW_TARGETS = MANDATORY_REVIEW_TARGETS


def run_review(**kwargs: Any) -> dict[str, Any]:
    return _BASE.run_review(**kwargs)


def main() -> int:
    return _BASE.main()


def __getattr__(name: str) -> Any:
    return getattr(_BASE, name)


if __name__ == "__main__":
    raise SystemExit(main())
