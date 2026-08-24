# Goal Teams V2.65 Release

V2.65 is the current published product release. GitHub Release `375434758`, the annotated `v2.65` tag, the fixed four public assets, exact remote readback, and the formal canonical local installation have completed.

V2.65 adds executable Graph Engineering and a proactive evolution LOOP while retaining the V2.5 portable execution core, v2.50 release controls, and V2.3 Legacy data schema.

## V2.65 changes

- Adds a typed, canonically hashed Graph contract for nodes, edges, ports, gates, authority, Host capabilities, retries and Member Packets.
- Adds a local SQLite-backed Runtime slice with durable events, checkpoints, CAS transitions, process-exit recovery, HITL resume and confirmed idempotency evidence.
- Makes fan-in, condition, retry and terminal routing fail closed instead of inferring execution from static DAG layers or filenames.
- Adds deterministic Context Bundles and append-only `loop-review.md` reflection after every LOOP and detected problem.
- Preserves explicit boundaries between local Callback/fake-adapter evidence, real Host/Provider execution, external effects and business validation.
- Keeps V2.63 as the published predecessor and excludes predecessor/Legacy test roots from the V2.65 Current execution denominator.

## Compatibility retained from V2.6

- Added a fail-closed compatibility chain: `Portable Core -> Host -> Provider -> Model -> optional Bridge -> Role -> Task`.
- Added explicit Codex and Claude Code host overlays, DeepSeek provider metadata, and Kimi K3 model routing.
- Added deterministic thin role projections for Codex TOML and Claude Code Markdown, including missing, drift, and managed-orphan checks.
- Kept provider and model runtime claims unverified unless a trusted runtime-binding receipt exists; structural compatibility does not imply live provider success.
- Kept Legacy out of Current routing and the default package unless an explicit trusted Replay request is supplied.

## Public assets

The fixed public set is:

- `goal-teams-V2.65.tar.gz` — 1,726,938 bytes — SHA-256 `bc773921cd8218fd1476666be4cd442517985cfa6d333d11230e8eb3f484e045`
- `SHA256SUMS` — 90 bytes — SHA-256 `71a2b446dc82ac24b9d900132470bd9d5d9203c585aaa3312bd1ea4d6cd56381`
- `_release.json` — 1,761 bytes — SHA-256 `aecfce9a8eedaf8bc626a0719e47af39a50f9e71ab0f60fbb795dc0bde7a2593`
- `_files.sha256` — 42,103 bytes — SHA-256 `b54d7e09d122934964b62fe9d326301a79ca91855259e341e549e40b8bb3fa78`

No `docs/`, `develops/`, local Evidence, credentials, or optional Replay supplement is part of the default asset.

## Projection boundary

This file is the post-release `main` projection of the verified live V2.65 Release. The immutable V2.65 assets retain the candidate-time `release/current` projection captured by the single S2 build and are not rewritten after publication. The immutable V2.63 assets retain the candidate-time projection from their own release and remain untouched by this V2.65 projection.

## Completion telemetry

- Tokens consumed: Unavailable / 未获取到
- Cache hit rate: Unavailable / 未获取到

## Assurance boundary

A fresh runtime transition receipt proves only an I1 correlated process observation. The installed package, local Graph Runtime tests and canonical installation do not prove repository-external independence, provider final-prompt assembly, real business execution or business acceptance. Tokens consumed and cache hit rate remain unavailable unless trusted host usage Evidence exists.

Requirements: Python 3.11+ for the complete validated toolchain.
