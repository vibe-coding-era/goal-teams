# Change History

This is the reader-facing English summary of changes by version. Its Chinese counterpart is [change-history.md](change-history.md). The repository-root [CHANGELOG.md](../CHANGELOG.md) remains the detailed technical record. `VERSION` is the authority for the current version.

## Recording boundary

- This document does not present plans, proposals, or unverified work as delivered capability.
- V2.33 splits the README's release-contents and history entrypoints into this bilingual document set. This record describes the scope, but cannot replace `VERSION` synchronization or validation gates.
- V2.34 archives completed public documents by delivery id only after independent audit and sanitization; process bundles and private provenance remain outside the public archive.
- V2.35 creates its public release summary before the graph-external Completion Audit and labels that audit as not yet run; the final audit stays only in the private process bundle.
- The local planning source `docs/后续版本规划 V3.3-3.5.md` is user-maintained and is not part of the repository or install package. AI must not edit it or commit it to GitHub without separate authorization.

## Recorded versions

| Version | Recorded change summary |
| --- | --- |
| V2.35 | Added read-only proposal roles for security, performance, refactor, and SQA without direct implementation or dispatch; a `large|medium|small` by `feature|bugfix` routing matrix with safety/UI overrides; executable test contracts covering input, processing, expected output, and assertions; and explicit hash-bound version descriptors that isolate V2.34 default behavior from V2.35 state and archives. |
| V2.34 | Added the contract-first `Gather → Reason → Act → Verify → Repeat` LOOP; crash recovery through `feature_list.json`, `progress.md`, `contract.md`, `log.md`, journal, and CAS; an Environment Evidence gate after accepted Architecture; constrained iteration-9 candidate quarantine and a fail-closed iteration-11 delivery gate; four-dimensional scoring, GTLOG divergence/prompt lifecycle, moving-bottleneck selection, and sanitized public archives. |
| V2.33 | On the V2.3 machine-contract baseline, defined precedence across system/user instructions, `AGENTS.md`, invariants, conditional rules, `RULES.md`, Lead, and Member; defined fail-closed dependency classification and limited degradation, explicit no-write `plan_preview` selection, single-value `check_state` language, and independent bilingual release/history documents. |
| V2.3 | Added closed state enums, a single-writer append-only ledger, strict Evidence/Traceability/Dual Review, Profile routing and capability degradation, typed migration, atomic installation, and deterministic release gates. Technical RC and public GA remain separate judgments. |
| V2.1 | Added Lead LOOP, Loop Decision, Loop Gate, state snapshots, and `GT-BENCH-004` to record the post-integration decision to continue or stop. |
| V2.02 | Added the `RULES.md` response contract: execute first, report facts first, and do not claim unverified completion. |
| V2.0 | Moved SSOT outputs into versioned directories, required `TaskList.md` before work, and defined independent backend-architecture, TDD, API-integration, and E2E testing responsibilities. |
| V1.97 | Added Google OKF, local bilingual guidance, the default output directory, `memory.md`, and component-library records for page specifications and HTML prototypes. |
| V1.94–V1.96 | Added role member packages, LLM-plus-script dual review, the Plan Mode requirement card, and user-story/functional-acceptance flow into Harness, testing, and acceptance. |
| V1.8–V1.93 | Progressively added machine-readable Harness/Evidence/Pipeline protocols, production release gates, scripted tooling, conflict and budget gates, progressive entrypoints, and member dispatch protocols. |
| V1.4–V1.7 | Established Plan Mode, the Teams planning table, Harness, member/Lead/Skill Improvement loops, a minimal example, and Benchmark templates. |

## Maintenance rule

For a new version, update verifiable technical records first, then keep this document and its Chinese counterpart aligned. Version changes still require synchronized checks across `VERSION`, `SKILL.md`, the READMEs, and compatibility rules. Use [CHANGELOG.md](../CHANGELOG.md) for detailed entries, compatibility detail, and historical corrections rather than inferring them from this summary.
