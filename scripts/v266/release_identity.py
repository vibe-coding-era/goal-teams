"""Immutable V2.66 release/runtime identity constants.

This module is data-only.  It binds the Current V2.66 runtime transition to
the exact published V2.65 predecessor without performing file, process,
network, Git, installation, or release side effects.
"""

from __future__ import annotations

from types import MappingProxyType


TARGET_PRODUCT_VERSION = "V2.66"
TARGET_RELEASE_TAG = "v2.66"
PREDECESSOR_PRODUCT_VERSION = "V2.65"
PREDECESSOR_RELEASE_TAG = "v2.65"
REPOSITORY = "vibe-coding-era/goal-teams"

HANDOFF_SCHEMA_VERSION = "goal-teams-v2.66-controller-handoff-receipt-v1"
LAUNCH_SCHEMA_VERSION = "goal-teams-v2.66-runtime-launch-receipt-v1"
CHILD_ACK_SCHEMA_VERSION = "goal-teams-v2.66-runtime-child-ack-v1"
TRANSITION_SCHEMA_VERSION = "goal-teams-v2.66-runtime-transition-receipt-v1"
PREDECESSOR_IDENTITY_SCHEMA_VERSION = (
    "goal-teams-predecessor-release-identity-v2.66"
)
HANDOFF_SIGNATURE_NAMESPACE = "goal-teams-v2.66-controller-handoff"

ACTIVE_PATH = "references/current/ACTIVE.json"
GENERATION_ROOT = "references/current/generations/V2.66"
PREDECESSOR_RELEASE_IDENTITY_PATH = (
    f"{GENERATION_ROOT}/contracts/predecessor-release-identity.json"
)
POLICY_PROFILE_PATH = "references/profiles/goal-teams-self-release-v2.66.md"
RELEASE_PROFILE_PATH = "references/release-profiles/v2.66.json"
RELEASE_ROUTE_MANIFEST_PATH = f"{GENERATION_ROOT}/contracts/release-route-manifest.json"
RELEASE_COMMAND_MANIFEST_PATH = (
    f"{GENERATION_ROOT}/contracts/release-command-manifest.json"
)
RUNTIME_TRANSITION_SCHEMA_PATH = (
    "schemas/v2.66/runtime-transition-receipt.schema.json"
)

PUBLISHED_PREDECESSOR_IDENTITY = MappingProxyType(
    {
        "tag": PREDECESSOR_RELEASE_TAG,
        "release_id": 375434758,
        "state": "published",
        "source_commit": "8512f6b9a7668daa6824b7a97494b927962b299e",
        "source_tree": "fb436dbee231ee6c066cbb00fc9048b3113134ef",
        "public_assets": (
            "goal-teams-V2.65.tar.gz",
            "SHA256SUMS",
            "_release.json",
            "_files.sha256",
        ),
    }
)


__all__ = [
    "ACTIVE_PATH",
    "CHILD_ACK_SCHEMA_VERSION",
    "GENERATION_ROOT",
    "HANDOFF_SCHEMA_VERSION",
    "HANDOFF_SIGNATURE_NAMESPACE",
    "LAUNCH_SCHEMA_VERSION",
    "POLICY_PROFILE_PATH",
    "PREDECESSOR_PRODUCT_VERSION",
    "PREDECESSOR_IDENTITY_SCHEMA_VERSION",
    "PREDECESSOR_RELEASE_IDENTITY_PATH",
    "PREDECESSOR_RELEASE_TAG",
    "PUBLISHED_PREDECESSOR_IDENTITY",
    "RELEASE_COMMAND_MANIFEST_PATH",
    "RELEASE_PROFILE_PATH",
    "RELEASE_ROUTE_MANIFEST_PATH",
    "REPOSITORY",
    "RUNTIME_TRANSITION_SCHEMA_PATH",
    "TARGET_PRODUCT_VERSION",
    "TARGET_RELEASE_TAG",
    "TRANSITION_SCHEMA_VERSION",
]
