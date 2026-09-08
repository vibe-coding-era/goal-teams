"""Immutable V2.68 release/runtime identity constants.

This module is data-only.  It binds the Current V2.68 runtime transition to
the exact published V2.67 predecessor without performing file, process,
network, Git, installation, or release side effects.
"""

from __future__ import annotations

from types import MappingProxyType


TARGET_PRODUCT_VERSION = "V2.68"
TARGET_RELEASE_TAG = "v2.68"
PREDECESSOR_PRODUCT_VERSION = "V2.67"
PREDECESSOR_RELEASE_TAG = "v2.67"
REPOSITORY = "vibe-coding-era/goal-teams"

HANDOFF_SCHEMA_VERSION = "goal-teams-v2.68-controller-handoff-receipt-v1"
LOCAL_PREDECESSOR_OBSERVATION_SCHEMA_VERSION = (
    "goal-teams-v2.68-local-predecessor-observation-v1"
)
LAUNCH_SCHEMA_VERSION = "goal-teams-v2.68-runtime-launch-receipt-v1"
CHILD_ACK_SCHEMA_VERSION = "goal-teams-v2.68-runtime-child-ack-v1"
TRANSITION_SCHEMA_VERSION = "goal-teams-v2.68-runtime-transition-receipt-v1"
PREDECESSOR_IDENTITY_SCHEMA_VERSION = (
    "goal-teams-predecessor-release-identity-v2.68"
)
HANDOFF_SIGNATURE_NAMESPACE = "goal-teams-v2.68-controller-handoff"

ACTIVE_PATH = "references/current/ACTIVE.json"
GENERATION_ROOT = "references/current/generations/V2.68"
PREDECESSOR_RELEASE_IDENTITY_PATH = (
    f"{GENERATION_ROOT}/contracts/predecessor-release-identity.json"
)
POLICY_PROFILE_PATH = "references/profiles/goal-teams-self-release-v2.68.md"
RELEASE_PROFILE_PATH = "references/release-profiles/v2.68.json"
RELEASE_ROUTE_MANIFEST_PATH = f"{GENERATION_ROOT}/contracts/release-route-manifest.json"
RELEASE_COMMAND_MANIFEST_PATH = (
    f"{GENERATION_ROOT}/contracts/release-command-manifest.json"
)
RUNTIME_TRANSITION_SCHEMA_PATH = (
    "schemas/v2.68/runtime-transition-receipt.schema.json"
)

PUBLISHED_PREDECESSOR_IDENTITY = MappingProxyType(
    {
        "tag": PREDECESSOR_RELEASE_TAG,
        "release_id": 379771898,
        "state": "published",
        "source_commit": "24f522a87b1aa74b6b127962ab88522ddc1f489d",
        "source_tree": "a09be8a212b583cc489125bf2ff3b4e6cbbf9b71",
        "public_assets": (
            "goal-teams-V2.67.tar.gz",
            "SHA256SUMS",
            "_release.json",
            "_files.sha256",
        ),
    }
)

# Independently read GitHub Release 379771898: public _files.sha256 raw digest
# 6e3e7d83917777ebb51fe8e6b8873111a8835057e9ef54b63f18e72734749867.
# The canonical rows are {path, sha256, size, mode}, sorted by path. This fixed
# public payload oracle is not derived from caller-supplied installation state.
PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR = MappingProxyType(
    {
        "package_file_count": 344,
        "package_files_sha256": "c7d15802c74c6d75802aed3806426610a470da31b69169ca25af6e574f941670",
        "package_manifest_sha256": "a73f9ce1b0f0177391f74dcab21735930d10a45ae4d0ff5d54ce71a1f5625a9a",
    }
)


__all__ = [
    "ACTIVE_PATH",
    "CHILD_ACK_SCHEMA_VERSION",
    "GENERATION_ROOT",
    "HANDOFF_SCHEMA_VERSION",
    "HANDOFF_SIGNATURE_NAMESPACE",
    "LAUNCH_SCHEMA_VERSION",
    "LOCAL_PREDECESSOR_OBSERVATION_SCHEMA_VERSION",
    "POLICY_PROFILE_PATH",
    "PREDECESSOR_PRODUCT_VERSION",
    "PREDECESSOR_IDENTITY_SCHEMA_VERSION",
    "PREDECESSOR_RELEASE_IDENTITY_PATH",
    "PREDECESSOR_RELEASE_TAG",
    "PUBLISHED_PREDECESSOR_IDENTITY",
    "PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR",
    "RELEASE_COMMAND_MANIFEST_PATH",
    "RELEASE_PROFILE_PATH",
    "RELEASE_ROUTE_MANIFEST_PATH",
    "REPOSITORY",
    "RUNTIME_TRANSITION_SCHEMA_PATH",
    "TARGET_PRODUCT_VERSION",
    "TARGET_RELEASE_TAG",
    "TRANSITION_SCHEMA_VERSION",
]
