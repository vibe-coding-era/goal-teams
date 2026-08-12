# Goal Teams V2.62 Release

> Candidate projection: V2.62 remains the current published release. V2.63 is an unpublished development candidate and is not represented by a tag, GitHub Release, public asset, or canonical installation yet.

## V2.63 candidate scope

- Governs discovery, immutable generation snapshots, fact-derived routes, deterministic prompt artifacts, TaskExactSet/DAG, bounded blockers/findings, Git-derived change receipts, and orthogonal completion projections.
- Removes the fixed user-visible runtime identity fingerprint; identity remains machine Evidence and is explained only when requested or required for drift diagnosis.
- Retains core policy V2.5 and Legacy data schema V2.3. The candidate state is `development_candidate_not_published`.

V2.62 is the current published product release. Its annotated tag, fixed four public assets, remote readback, and formal canonical local installation have completed.

V2.62 adds the OKF Document Graph under the OSI-approved MIT License while retaining the V2.5 portable execution core, v2.50 Execution assets, and V2.3 Legacy data schema.

## V2.62 changes

- Adds the OKF Document Graph as a read-only, in-memory RDF 1.1 projection over tracked OKF and Markdown documents.
- Keeps Markdown as the SSOT with no database, cache, network access, or document mutation.
- Records graph-quality findings as Observe-only without adding a Knowledge Graph quality Gate.
- Reports SPARQL and SHACL engine capabilities as `not_implemented`.
- Binds a deterministic graph-input manifest digest, not an RDF dataset digest; the compatible parser identity denotes a controlled Markdown lexical subset, not full CommonMark/GFM conformance.
- Leaves the generic isolated-entity detector and compile-size budgets `not_implemented`; absence of those findings is not a validation pass.
- When `trace` is truncated, its `match_count` is the number of edges discovered before the traversal bound, not the total reachable-edge cardinality.
- Retains core policy V2.5, Execution assets v2.50, and Legacy data schema V2.3.

## Compatibility retained from V2.6

- Added a fail-closed compatibility chain: `Portable Core -> Host -> Provider -> Model -> optional Bridge -> Role -> Task`.
- Added explicit Codex and Claude Code host overlays, DeepSeek provider metadata, and Kimi K3 model routing.
- Added deterministic thin role projections for Codex TOML and Claude Code Markdown, including missing, drift, and managed-orphan checks.
- Kept provider and model runtime claims unverified unless a trusted runtime-binding receipt exists; structural compatibility does not imply live provider success.
- Kept Legacy out of Current routing and the default package unless an explicit trusted Replay request is supplied.

## Public assets

The fixed public set is:

- `goal-teams-V2.62.tar.gz`
- `SHA256SUMS`
- `_release.json`
- `_files.sha256`

No `docs/`, `develops/`, local Evidence, credentials, or optional Replay supplement is part of the default asset.

## Projection boundary

This file is the post-release `main` projection of the verified live Release. The immutable V2.62 assets retain the candidate-time `release/current` projection captured by the single S2 build and are not rewritten after publication.

## Completion telemetry

- Tokens consumed: Unavailable / 未获取到
- Cache hit rate: Unavailable / 未获取到

## Assurance boundary

A fresh runtime transition receipt proves only an I1 correlated local-process observation. It does not prove repository-external independence, cryptographic host attestation, or provider final-prompt assembly. Tokens consumed and cache hit rate remain unavailable unless trusted host usage Evidence exists.

Requirements: Python 3.11+ for the complete validated toolchain.
