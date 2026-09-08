#!/usr/bin/env python3
"""V2.68 route-aware Development and final-release checker.

The execution policy remains the shared V2.50 checker implementation.  This
entrypoint rebinds every Current-generation contract, denominator, runner, and
runtime module before delegating; the V2.67 checker keeps its original defaults.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CURRENT_RELEASE_VERSION = "V2.68"


def _load_base() -> ModuleType:
    path = ROOT / "scripts/checks/check-v250.py"
    spec = importlib.util.spec_from_file_location("_goalteams_v250_checker_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("E_V268_RELEASE_CHECKER_BASE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_base()
_BASE.CURRENT_RELEASE_VERSION = CURRENT_RELEASE_VERSION
_BASE.CONTRACT_ROOT = ROOT / "references/current/generations/V2.68/contracts"
_BASE.CONTRACT_SCHEMA_VERSIONS = {
    "release-route-manifest.json": "goal-teams-v2.68-release-route-v1",
    "release-command-manifest.json": "goal-teams-v2.68-release-command-manifest-v1",
    "release-security-review-manifest.json":
        "goal-teams-v2.68-release-security-review-v2",
    "public-asset-map.json": "goal-teams-v2.68-public-asset-map-v1",
}
_BASE.EXPECTED_PUBLIC_ASSETS = {
    "goal-teams-V2.68.tar.gz",
    "SHA256SUMS",
    "_release.json",
    "_files.sha256",
}
_BASE.CURRENT_TEST_ROOTS = ("tests/v250", "tests/v268")
_BASE.PUBLISHED_PREDECESSOR_TEST_ROOTS = ["tests/v267"]
_BASE.LEGACY_ROOTS_EXCLUDED = [
    "tests/v23",
    "tests/v249",
    "tests/v26",
    "tests/v262",
    "tests/v263",
]
_BASE.PREDECESSOR_RELEASE_IDENTITY_PATH = (
    "references/current/generations/V2.68/contracts/"
    "predecessor-release-identity.json"
)
_BASE.RELEASE_FLOW_PATH = ROOT / "scripts/v268/release_flow.py"
_BASE.RUNTIME_TRANSITION_PATH = ROOT / "scripts/v268/runtime_transition.py"
_BASE.SECURITY_REVIEW_RUNNER_PATH = (
    "scripts/checks/run-v268-release-security-review.py"
)
_BASE.SECURITY_REVIEWER_ID = (
    "goal-teams-v268-release-implementation-security-reviewer"
)
_BASE.RELEASE_GATE_RECEIPT_SCHEMA = (
    "goal-teams-v2.68-release-gate-receipt-v1"
)
_BASE.CHECK_RESULT_SCHEMA = "goal-teams-v2.68-check-result-v1"


def main() -> int:
    return _BASE.main()


def __getattr__(name: str) -> Any:
    return getattr(_BASE, name)


if __name__ == "__main__":
    raise SystemExit(main())
