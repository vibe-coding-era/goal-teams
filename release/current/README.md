# Goal Teams V2.6 Release

V2.6 is the current published product release. Its annotated tag, fixed four public assets, remote readback, and formal canonical local installation have completed.

V2.6 is a compatibility-policy release under the OSI-approved MIT License. It keeps the V2.5 portable execution core and V2.3 Legacy data schema while adding typed compatibility routing without creating a V2.53 product identity.

## V2.6 changes

- Added a fail-closed compatibility chain: `Portable Core -> Host -> Provider -> Model -> optional Bridge -> Role -> Task`.
- Added explicit Codex and Claude Code host overlays, DeepSeek provider metadata, and Kimi K3 model routing.
- Added deterministic thin role projections for Codex TOML and Claude Code Markdown, including missing, drift, and managed-orphan checks.
- Kept provider and model runtime claims unverified unless a trusted runtime-binding receipt exists; structural compatibility does not imply live provider success.
- Kept Legacy out of Current routing and the default package unless an explicit trusted Replay request is supplied.

## Public assets

The fixed public set is:

- `goal-teams-V2.6.tar.gz`
- `SHA256SUMS`
- `_release.json`
- `_files.sha256`

No `docs/`, `develops/`, local Evidence, credentials, or optional Replay supplement is part of the default asset.

## Completion telemetry

- Tokens consumed: Unavailable / 未获取到
- Cache hit rate: Unavailable / 未获取到

## Assurance boundary

A fresh runtime transition receipt proves only an I1 correlated local-process observation. It does not prove repository-external independence, cryptographic host attestation, or provider final-prompt assembly. Tokens consumed and cache hit rate remain unavailable unless trusted host usage Evidence exists.

Requirements: Python 3.11+ for the complete validated toolchain.
