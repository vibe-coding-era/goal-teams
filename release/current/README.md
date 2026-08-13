# Goal Teams V2.63 Release

V2.63 is the current published product release. GitHub Release `369846737`, the annotated `v2.63` tag, the fixed four public assets, remote readback, and the formal canonical local installation have completed.

V2.63 governs discovery, immutable generation snapshots, fact-derived routes, deterministic prompt artifacts, TaskExactSet/DAG, bounded blockers/findings, Git-derived change receipts, and orthogonal completion projections while retaining the V2.5 portable execution core, v2.50 Execution assets, and V2.3 Legacy data schema.

## V2.63 changes

- Adds trusted discovery and fact-derived routing so runtime selection is bound to observed Current facts rather than an assumed path.
- Binds each frozen TaskExactSet and DAG to its budget, dependencies, validation, and exit conditions; scope changes require a plan revision.
- Adds Git-derived baseline, tracked-diff, and untracked exact-set receipts for change evidence.
- Bounds external blockers and audit findings so accepted fixes cannot silently expand scope or form an infinite loop.
- Separates engineering completion, runtime completion, and business validation as orthogonal projections.
- Removes the fixed user-visible runtime identity fingerprint; identity remains machine Evidence and is explained only when requested or required for drift diagnosis.
- Retains the V2.62 OKF Document Graph and its explicit parser, digest, resource-budget, and truncation assurance limits.

## Compatibility retained from V2.6

- Added a fail-closed compatibility chain: `Portable Core -> Host -> Provider -> Model -> optional Bridge -> Role -> Task`.
- Added explicit Codex and Claude Code host overlays, DeepSeek provider metadata, and Kimi K3 model routing.
- Added deterministic thin role projections for Codex TOML and Claude Code Markdown, including missing, drift, and managed-orphan checks.
- Kept provider and model runtime claims unverified unless a trusted runtime-binding receipt exists; structural compatibility does not imply live provider success.
- Kept Legacy out of Current routing and the default package unless an explicit trusted Replay request is supplied.

## Public assets

The fixed public set is:

- `goal-teams-V2.63.tar.gz` — 1,530,836 bytes — SHA-256 `8b66526d7761723ac82508ea27d5e6afb5989f6e9a49b8f0574ffe79a7e5d1f7`
- `SHA256SUMS` — 90 bytes — SHA-256 `6db31de5025768e7b4497a9f43dbedea5067c47689b7947550936f212dc25930`
- `_release.json` — 1,760 bytes — SHA-256 `cba5b3ac3cd579f6d49afc54a773e1e4b34e6a6a880712bcbd7b4ad60e91192e`
- `_files.sha256` — 35,570 bytes — SHA-256 `c661486db1296a761b3dd6be850f09831a2b9db97970f38cb71a0774135e1208`

No `docs/`, `develops/`, local Evidence, credentials, or optional Replay supplement is part of the default asset.

## Projection boundary

This file is the post-release `main` projection of the verified live V2.63 Release. The immutable V2.63 assets retain the candidate-time `release/current` projection captured by the single S2 build and are not rewritten after publication. The immutable V2.62 assets retain the candidate-time projection from their own release and remain untouched by this V2.63 projection.

## Completion telemetry

- Tokens consumed: Unavailable / 未获取到
- Cache hit rate: Unavailable / 未获取到

## Assurance boundary

A fresh runtime transition receipt proves only an I1 correlated local-process observation. It does not prove repository-external independence, cryptographic host attestation, or provider final-prompt assembly. Tokens consumed and cache hit rate remain unavailable unless trusted host usage Evidence exists.

Requirements: Python 3.11+ for the complete validated toolchain.
