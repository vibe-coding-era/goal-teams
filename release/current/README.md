# Goal Teams V2.48 Release

V2.48 adds composable Agent-product development guidance and a five-step release flow designed for a Skill bundle. It preserves the V2.3 ledger, V2.44 API/E2E contracts, V2.46 verification and desktop contracts, and V2.47 flow/document/runtime contracts.

## Agent-product development

- Adds progressive-loading references for product, prompt, context, memory/cache, tool/MCP, Browser, Computer Use, and Playwright work.
- Adds an independent Agent Product Manager member package and three composable design patterns.
- Keeps platform documentation, repository contracts, runtime adapters, and real-host verification as distinct evidence states.

## Verification governance

- Historical passed results remain valid facts under their bound code, SPEC, Harness, environment, and rule versions. Current applicability and revalidation obligations are separate state dimensions.
- Rule changes require itemized impact analysis: unaffected evidence remains current, affected evidence becomes `stale` with `retest_required`, new requirements are `not_run`, actual failures are `failed`, and only untrustworthy evidence is `invalid`.
- Test contracts bind scope, unacceptable risks, thresholds, owners, Evidence, waivers, approvals, AC, test plans, cases, and Harness.
- Grill me challenges critical requirements according to Lite/Standard/Full/Regulated routing. Adversarial tests include abuse, privilege, invalid input, concurrency, retry, recovery, and forged or stale Evidence.

## State and release governance

- Task lifecycle, check execution, run conclusion, Evidence integrity/applicability, release phase, and recovery are orthogonal.
- External effects follow persisted intent, execution, exact readback, and revision/CAS commit. Uncertain outcomes allow only reconciliation or recovery.
- `accepted`, `released`, and `closed` are derived from completion predicates, valid current Evidence, and independent audit.
- V2.48 uses `skill_simple`: source freeze, checks, deterministic packaging, isolated install rehearsal, and one human confirmation before external publication.
- The V2.46 CP00–CP18 governed engine remains available for historical replay and high-assurance compatibility; it is not the default V2.48 path.

## Rust and Tauri desktop engineering

- A consolidated, conditionally loaded desktop contract covers Rust backend architecture, typed Tauri IPC, macOS-focused frontend replication, and cross-platform client testing without expanding the main Skill entrypoint.
- Replica acceptance keeps complete source coverage, same-tuple zero-pixel difference, high fidelity, and native-semantic match as separate gates. PRD-only work creates an independently approved interactive HTML baseline before implementation.
- Desktop Evidence separates L1 Rust, L2 mock/browser, L3 instrumented real app, and L4 production package per immutable platform tuple. macOS real-app automation uses the embedded WebdriverIO Tauri service or an approved native harness; direct `tauri-driver` and browser-only runs cannot stand in for macOS client Evidence.
- Production-package checks fail closed if test plugins, debug ports, mock hooks, or broad test capabilities remain present.

## Compatibility and evidence boundary

- V2.44 schemas, fixtures, benchmark, and fixed 100-point denominator keep their original identities.
- Full regression may be required for the current candidate, but it never erases historical results.
- Structural checks, exit codes, cache telemetry, and scores do not replace behavior checks, deterministic package identity, isolated install rehearsal, or published-asset readback.

## Release telemetry

- Tokens consumed / Tokens 消耗：**Unavailable / 未获取到**.
- Cache hit rate / Cache 命中率：**Unavailable / 未获取到**.

No trusted host usage artifact was available while authoring this release note. Values are not estimated or reported as zero.

Requirements: Python 3.11+ for the complete validated toolchain. The installer fails fast when a compatible Python with `tomllib` is unavailable.
