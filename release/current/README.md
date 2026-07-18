# Goal Teams V2.40 Release

V2.40 makes the repository root, packaged current release, self-release Profile, and installed identity project the same product version while preserving the V2.39/V2.38 cache schemas, fixtures, and replay-only history.

## Release governance

- Both root READMEs contain exactly one controlled release marker that points to `v2.40` and this `release/current` note; the surrounding user-authored README body remains intact.
- `goal-teams-self-release-v2.40` is the only current repository self-release Profile. V2.39 and V2.38 Profiles are replay-only and cannot be selected for a current V2.40 release.
- The CP00–CP18 lifecycle binds every non-idempotent operation to intent, expected-before state, live readback, and marker-last recovery.
- Promotion holds an active remote main lock, advances main only through an exact compare-and-swap lease, and publishes the already verified Draft last. Tag and published Release identities are immutable.
- Draft assets are verified and rehearsed only in a temporary `CODEX_HOME`; the actual local installation consumes the published four-asset release and records its commit, tag, Release ID, asset IDs, and digests.
- CP17 freezes only the independent live release audit. The final Evidence, accepted tasks, Completion, and archived `GoalTeamsWork` are finalized in the explicit CP17-to-CP18 window; CP18 binds them to the CP17 audit SHA and revalidates the entire close boundary before and after permanent protection. Candidate-supplied positive host authority and stale marker-loss readbacks are rejected.
- Current version checks derive the product identity from `VERSION`. `development` and `candidate` are deterministic local projections; `stable` is decided only by the independent live release audit.

## Cache compatibility and claim boundary

- The V2.38-compatible prompt-cache manifest remains the route-static order and budget SSOT; V2.39/V2.38 schemas and fixtures retain their historical meaning.
- Cache Evidence keeps structural, host, live-validation, and request-hit-rate states separate. Structural governance cannot be promoted into a live provider or request-hit-rate claim.
- Goal Teams cannot force, clear, or guarantee a provider prompt cache.

## Release telemetry

- Tokens consumed / Tokens 消耗：**Unavailable / 未获取到**.
- Cache hit rate / Cache 命中率：**Unavailable / 未获取到**.

No trusted host usage artifact was available to this release note. These values are intentionally unavailable; they are not estimated, inferred, or reported as zero.

Requirements: Python 3.11+ for the complete validated toolchain. The installer fails fast when a compatible Python with `tomllib` is unavailable.
