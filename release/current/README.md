# Goal Teams V2.45 Release

V2.45 adds a standalone, progressively loaded Release Engineer member for governed environment preparation, packaging, application/container/WeChat Mini Program/GitHub Skill delivery, rollback, benchmark baselines, and post-release readback. The member ships in the package but is not connected to the main Skill route or normal member dispatch.

## Release governance

- `goal-teams-self-release-v2.45` is the active repository self-release Profile. V2.44 retains predecessor and external-host verification semantics for replay, but cannot authorize new external writes.
- The release-engine profile binds V2.45, `codex/v2.45-release-engineer`, `v2.45`, Release metadata, strict snapshot format, public-scan baseline, and close schema.
- CP05 is external-host-only for every profile that freezes `host_acceptance`; caller JSON, files, paths, argv, environment tokens, and self-reported reviewer identity cannot advance it.
- The CP00–CP18 lifecycle, exact-SHA CI, remote lock, immutable tag/Release, four fixed assets, published-asset re-download, temporary installation audit, actual local installation, and independent live audit remain mandatory.

## Standalone Release Engineer

- Normal invocation performs only final release Evidence checks and never runs the full test suite.
- Java, Rust, Go, Python, Node.js, five environments, and four release surfaces are selected from an approved versioned kit catalog.
- Script generation requires a trusted-host-signed human plan approval; live execution requires a second trusted-host-signed human approval with one-time challenge, least-privilege, and database-safety attestations.
- The fixed Evidence denominator includes unit, API, E2E, Review, Completion Audit, artifact, package, SBOM, provenance, and signature evidence. Callers may add kinds but cannot remove them.
- Database destructive operations and unclosed indirect helper/database scripts fail closed. Production requires backup, restore proof, rollback, benchmark baseline, and post-release verification.
- Receipts reuse the repository-wide V2.36 secret redaction boundary for credentials, Cookie, database URIs, `.netrc`, cloud secrets, and collaboration tokens.

## Compatibility and evidence boundary

- V2.44 API/E2E schemas, fixtures, benchmark, and the fixed 100-point capability denominator remain historical machine contracts and are not renamed.
- The V2.43 engineering-metrics sidecar remains compatible; unavailable or insufficient observations are never reported as zero.
- Structural validation, test exit codes, cache telemetry, and benchmark scores do not replace real Evidence, independent Review, trusted-host acceptance, or release readback.

## Release telemetry

- Tokens consumed / Tokens 消耗：**Unavailable / 未获取到**.
- Cache hit rate / Cache 命中率：**Unavailable / 未获取到**.

No trusted host usage artifact was available while authoring this release note. Values are not estimated or reported as zero.

Requirements: Python 3.11+ for the complete validated toolchain. The installer fails fast when a compatible Python with `tomllib` is unavailable.
