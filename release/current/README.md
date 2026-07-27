# Goal Teams V2.46 Release

V2.46 adds machine-verifiable verification governance while preserving the V2.3 ledger, V2.44 API/E2E contracts, V2.43 metrics, and V2.45 Release Engineer.

## Verification governance

- Historical passed results remain valid facts under their bound code, SPEC, Harness, environment, and rule versions. Current applicability and revalidation obligations are separate state dimensions.
- Rule changes require itemized impact analysis: unaffected evidence remains current, affected evidence becomes `stale` with `retest_required`, new requirements are `not_run`, actual failures are `failed`, and only untrustworthy evidence is `invalid`.
- Test contracts bind scope, unacceptable risks, thresholds, owners, Evidence, waivers, approvals, AC, test plans, cases, and Harness.
- Grill me challenges critical requirements according to Lite/Standard/Full/Regulated routing. Adversarial tests include abuse, privilege, invalid input, concurrency, retry, recovery, and forged or stale Evidence.

## State and release governance

- Task lifecycle, check execution, run conclusion, Evidence integrity/applicability, release phase, and recovery are orthogonal.
- External effects follow persisted intent, execution, exact readback, and revision/CAS commit. Uncertain outcomes allow only reconciliation or recovery.
- `accepted`, `released`, and `closed` are derived from completion predicates, valid current Evidence, and independent audit.
- V2.46 is the active self-release profile. V2.45 and earlier profiles are replay-only and cannot authorize new external writes.
- CP05 remains external-host-only; immutable tag/Release, four fixed assets, published-asset re-download, local installation, and independent live audit remain mandatory.

## Rust and Tauri desktop engineering

- A consolidated, conditionally loaded desktop contract covers Rust backend architecture, typed Tauri IPC, macOS-focused frontend replication, and cross-platform client testing without expanding the main Skill entrypoint.
- Replica acceptance keeps complete source coverage, same-tuple zero-pixel difference, high fidelity, and native-semantic match as separate gates. PRD-only work creates an independently approved interactive HTML baseline before implementation.
- Desktop Evidence separates L1 Rust, L2 mock/browser, L3 instrumented real app, and L4 production package per immutable platform tuple. macOS real-app automation uses the embedded WebdriverIO Tauri service or an approved native harness; direct `tauri-driver` and browser-only runs cannot stand in for macOS client Evidence.
- Production-package checks fail closed if test plugins, debug ports, mock hooks, or broad test capabilities remain present.

## Compatibility and evidence boundary

- V2.44 schemas, fixtures, benchmark, and fixed 100-point denominator keep their original identities.
- Full regression may be required for the current candidate, but it never erases historical results.
- Structural checks, exit codes, cache telemetry, and scores do not replace behavior Evidence, independent Review, trusted-host acceptance, or release readback.

## Release telemetry

- Tokens consumed / Tokens 消耗：**Unavailable / 未获取到**.
- Cache hit rate / Cache 命中率：**Unavailable / 未获取到**.

No trusted host usage artifact was available while authoring this release note. Values are not estimated or reported as zero.

Requirements: Python 3.11+ for the complete validated toolchain. The installer fails fast when a compatible Python with `tomllib` is unavailable.
