# Goal Teams V2.44 Release

V2.44 adds machine-checkable API integration and E2E test planning, case quality, execution-evidence, and capability-scoring contracts. It also upgrades the self-release engine from a V2.40-only implementation to a closed, Git-tracked release profile so the active V2.44 identity is explicit while V2.40 remains replay-only.

## Release governance

- Both root READMEs contain exactly one controlled release marker that points to `v2.44` and this `release/current` note; the surrounding user-authored README body remains intact.
- `goal-teams-self-release-v2.44` is the current repository self-release Profile. V2.40 and earlier Profiles remain historical replay material and cannot authorize external writes.
- The release-engine profile binds the version, candidate branch, tag, Release metadata, strict snapshot format, public-scan baseline, and close schema. Unknown versions and profile drift fail closed.
- The CP00–CP18 lifecycle binds every non-idempotent operation to intent, expected-before state, live readback, and marker-last recovery.
- Promotion holds an active remote main lock, advances main only through an exact compare-and-swap lease, and publishes the already verified Draft last. Tag and published Release identities are immutable.
- Draft assets are verified and rehearsed only in a temporary `CODEX_HOME`; the actual local installation consumes the published four-asset release and records its commit, tag, Release ID, asset IDs, and digests.
- Current version checks derive the product identity from `VERSION`. `development` and `candidate` are deterministic local projections; `stable` is decided only by the independent live release audit.

## Test capability and evidence boundary

- API and E2E plans must trace requirements to executable assertions, negative paths, state changes, cleanup, and reproducible Evidence.
- Test-member capability scoring distinguishes document quality, executable coverage, behavior evidence, and independent acceptance. A structural pass never becomes a behavior pass.
- Unknown, unavailable, blocked, and not-run results remain explicit and never become zero or success.

## Cache compatibility and claim boundary

- The V2.38-compatible prompt-cache manifest remains the route-static order and budget SSOT; V2.43/V2.40 and earlier schemas and fixtures retain their historical meaning.
- Cache Evidence keeps structural, host, live-validation, and request-hit-rate states separate. Structural governance cannot be promoted into a live provider or request-hit-rate claim.
- Goal Teams cannot force, clear, or guarantee a provider prompt cache.

## Release telemetry

- Tokens consumed / Tokens 消耗：**Unavailable / 未获取到**.
- Cache hit rate / Cache 命中率：**Unavailable / 未获取到**.

No trusted host usage artifact was available to this release note. These values are intentionally unavailable; they are not estimated, inferred, or reported as zero.

Requirements: Python 3.11+ for the complete validated toolchain. The installer fails fast when a compatible Python with `tomllib` is unavailable.
