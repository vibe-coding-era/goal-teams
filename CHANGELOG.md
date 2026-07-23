# Changelog

## Unreleased

### V2.44

- Added machine-checkable integration test plans, typed API/E2E cases, and run-result contracts with risk denominators, path/digest/discovery identity, attempts, observed assertions, cleanup, and replay.
- Upgraded API/E2E designers, runners, QA, and Reviewer to share one fail-closed testing handoff contract without treating retries, skipped execution, or prose as success.
- Added an append-only issue ledger, seven-dimension 100-point capability manifest, and a deterministic real-behavior API/E2E benchmark with seeded defects.
- Retained V2.43 engineering metrics and V2.35 test-case inputs as compatibility surfaces, and moved the V2.43 self-release Profile to replay-only routing.

### V2.43

- Added one manifest-driven calculator for 12 engineering metrics across task completion and Benchmark records: FPAR, LCC, HER, SAR, CPAC, DER, RRR, CWR, SDI, RFR, ARCR, and MRT.
- Added append-only JSONL metric events, a V2.43 summary schema, comparable-history aggregation, manifest-bytes identity, correction events, and fail-closed availability states so uncollected data is never reported as zero.
- Added self-contained Google OKF engineering-metrics reports with current, previous, and recent values plus the complete algorithms, Evidence references, coverage, observation windows, and privacy notes.
- Added Benchmark record/summary integration while keeping `quality_pass_rate` distinct from FPAR, and retained V2.42 as a replay-only self-release Profile.

### V2.40

- Added a single controlled release-identity block to both root READMEs so the public repository surface points to `v2.40` and `release/current` without replacing the user-authored body.
- Added the current `goal-teams-self-release-v2.40` Profile and moved V2.39/V2.38 Profiles to replay-only routing while preserving their cache schemas, fixtures, and historical semantics.
- Added development/candidate version projections derived from `VERSION`; stable identity remains an independent live-audit responsibility.
- Added the CP00–CP18 recoverable release lifecycle, exact operation semantics, remote promotion lock, exact main compare-and-swap before publish, immutable tag/Release gates, four-asset verification, and published-asset installation identity.
- Made release telemetry honest by reporting Tokens consumed and Cache hit rate as `未获取到` / `Unavailable` whenever trusted host usage Evidence is absent.

### V2.39

- Added a fail-closed Cache Evidence contract with trusted host capability, ordered request manifest, registered configuration attestation, raw-to-normalized receipts, and an authorization-gated live probe executor.
- Split cache reporting into four orthogonal states: structural validation `passed`, host integration `unavailable`, live probe `not_authorized`, and request hit rate `unavailable`; the release claim is limited to `structural_governance`.
- Added deterministic Google OKF A/B/C classification, safe frontmatter parsing, tracked/changed/bundle/manifest/package-tree checks, and package completeness/identity binding.
- Added the current `goal-teams-self-release-v2.39` Profile and switched current routes to it while preserving the V2.38 Profile, schemas, compilers, observer reports, fixtures, and artifacts for read-only replay.
- Kept live provider and request-hit-rate claims fail-closed because no trusted host observation or live provider probe was authorized for this release.

### V2.38

- Added `references/prompt-cache-manifest.json` as the ordered route-static and byte-budget machine SSOT, including startup headroom enforcement.
- Added order-sensitive `prefix_manifest_sha256`, byte-sensitive `route_static_digest`, host ordered-manifest digest helpers, and explicit unavailable/partial semantics when the final request is not observable.
- Added fail-closed versioned observer aggregation and identity grouping; invalid, legacy, ambiguous, or unattested config inputs cannot produce a supported cache conclusion, and request hit rate remains unavailable.
- Added a plan-only first-seen/repeat probe compiler (`live_ab_status=unavailable`); no live provider A/B records are claimed.
- Added a single-source subagent common-prefix expander/validator and canonical Member Goal Packet compiler with stable, dynamic, combined, and legacy migration digests.
- Documented the platform boundary: Goal Teams can observe reported cache usage but cannot force, clear, or guarantee a provider prompt cache.

### V2.37

- Added progressive member indexes and deterministic index/document-budget gates.
- Split the large runtime reference into routed parts and kept startup context within 12 KiB.
- Moved historical/process knowledge, the complete PRD/architecture, integration catalog, and private release evidence to local-only `docs/`.
- Reduced the install package to current runtime material while retaining legacy schemas and runtime identifiers only for compatibility.
- Added static adapter assessments for Claude Code, Trae, Qoder, WorkBuddy, QoderWork, and Cursor without claiming runtime verification.

### V2.36

- Separated the product version (`V2.36`), general core policy (`V2.5` / `goal-teams-core-v2.5`), and legacy machine-data schema (`V2.3`) so startup identity, execution policy, and persisted data are no longer conflated.
- Moved the 52 assertions, iterations 9/11, four-dimension scoring, candidate reset, and public archive into the repository-only `goal-teams-self-release-v2.36` Profile; ordinary projects no longer inherit this self-release workflow as global invariants.
- Derived gates from the bound product/core versions, task route facts, and execution class. A missing `state_gate_profile` cannot bypass gates, and a supplied value must match the derived gate.
- Restored risk- and size-based Lite/Standard execution, with explicit escalation for cross-module, high-risk, release, security, payment/authentication, and reference-driven UI work.
- Unified secret redaction across runtime and archive paths, including YAML/TOML key-value forms, database URIs, `.netrc`, Authorization/Cookie forms, cloud credentials, collaboration-tool tokens, and fail-closed non-text public copies.
- Added protected Git tree snapshots that auto-cover every tracked modification/deletion and non-ignored untracked file without a caller path list, plus host-attested Agent identity for independent validation claims.
- Added host-signed route receipts, persistent repository-external replay state, process-private trust-key FDs, and a V2.36 acceptance binding that locks Audit, Review, Harness, current Evidence, ledger, checkpoint, traceability, target fingerprint, and snapshot baseline to one completion decision.
- Added bilingual V2.36 pre-audit release summaries and synchronized package/version checks for the three-layer version model and the two policy profiles.

### V2.35

- Added four read-only, proposal-only specialist roles: `goal_security`, `goal_performance`, `goal_refactor`, and `goal_sqa`. Specialists cannot implement, dispatch, spawn nested teams, mutate central state, or self-verify; Goal Lead dispatches independent implementation and validation runs.
- Added deterministic `project_size=large|medium|small` and `work_type=feature|bugfix` routing with safety, risk, UI, and explicit-specialist overrides. Architecture, Environment, independent tests, and Evidence remain required; UI always requires E2E, and BugFix always requires TDD plus integration testing.
- Added the V2.35 test-case contract and canonical validator for non-empty `input`, `processing`, `expected_output`, and executable `assertions`; exit/status-only success cannot substitute for business-output assertions.
- Added explicit, hash-bound V2.35 version descriptors for state, recovery, closure, snapshot, and public archives while retaining byte-compatible V2.34 behavior when no descriptor is supplied. Invalid, stale, mismatched, traversal, or symlink bindings fail before mutation.
- Added strict pre-implementation and release/audit gates: delta contract review, accepted Architecture, ready Environment, independent RED tests, implementation, independent GREEN/full regression, release, remote/local Evidence, then graph-external Completion Audit.
- Added V2.35 schemas, negative fixtures, release-summary documents, package-selection denial of local roadmap/process bundles, and startup/routed-role context budgets.

### V2.34

- Added a contract-first `Gather -> Reason -> Act -> Verify -> Repeat` LOOP with durable four-file state (`feature_list.json`, `progress.md`, `contract.md`, `log.md`), revision/CAS checks, a journal, marker-last commits, reconciliation, and session-scoped crash recovery.
- Added the ordered implementation gates `contract frozen -> architecture accepted -> development environment ready -> independent tests written -> implementation`, with exact-hash Evidence and independent validation; no background daemon is implied.
- Added a constrained iteration-9 reset that can quarantine only a preauthorized disposable candidate, never repository or user data, and a fail-closed iteration-11 delivery gate with no iteration 12.
- Added four independently evidenced quality dimensions (`design`, `originality`, `craft`, `functionality`) scored by four binary 0.25 rubric items; scores supplement rather than replace tests or Evidence.
- Added canonical `GTLOG` intent/judgment frames, five divergence classes, prompt-fix lifecycle states (`proposed`, `applied`, `verified`, `reverted`) with regression plus holdout proof, and deterministic moving-bottleneck selection.
- Added audited public-document archiving under `docs/archive/V2.34/<delivery_id>/`, with invocation-trace sanitization separated from private ledger/evidence/review/audit provenance.

### V2.3

- Breaking contract: replaced legacy handoff/loop completion labels with orthogonal `task_state`, `check_state`, `run_outcome`, `loop_decision`, and `audit_state`; unknown core enums fail closed.
- Breaking persistence: append-only ledger events are the execution SSOT; members submit revision-bound events/patches and only the reducer writes `TaskList.md`. Lowercase `tasklist.md` is read-only V2.2 migration input.
- Separated `agent_type`, `agent_run_id`, `member_id`, localized `display_name`, and `transport_handle`; author/reviewer independence is bound to concrete run identity and artifact hash.
- Added versioned schema/source lock, task-local CAS, deterministic replay/projection, atomic checkpoints, strict Evidence/Traceability/Dual Review/Completion Audit, stable JSON envelopes, and negative mutation gates.
- Added Lite/Standard/Full/Regulated routing, capability manifests and non-escalating fallback, a 12 KiB base-context gate, secret redaction/trust boundaries, and environment-aware pixel validation.
- Added typed V2.2 `scan -> plan -> apply -> verify -> rollback` migration, manifest-driven atomic install/update/rollback/uninstall, dirty-source provenance, Linux/macOS CI, canonical success/blocked/failure/recovery replay, and fresh behavior scenarios.
- Capability boundary: Goal Teams remains a session-scoped orchestration protocol, not a persistent background runner, CI/CD service, or production approval system. OpenSpec and Superpowers coexist without claiming a V2.3 adapter.
- Release boundary: technical RC gates are independently testable; public GA remains fail-closed until the repository owner records a License or internal-sharing decision.

- Tightened V2.3 maintenance rules: startup text now says `规划、执行和交付`, Plan history input accepts `无` or `2`, and completion rules are a checklist.
- Added hard validation that all `SKILL.md` version strings match `VERSION`, and kept progressive-loading path existence checks in `./scripts/check.sh`.
- Moved OKF spec loading out of the all-tasks route and moved `scripts/harness/pixel-diff.py` from the UI route into `references/rules-ui.md` as an executable tool.
- Added Budget/round-limit failure degradation and explicit rule-conflict precedence.
- Restored `Plan Mode` / `先规划` / `只规划` / `需求卡片` trigger terms in `SKILL.md` description and added a routing fixture regression check.
- Bumped current Skill version to `V2.3`.
- Slimmed `SKILL.md` into a trigger-oriented entrypoint with invariants, planning checks, failure-degradation summary, and a progressive-loading router.
- Added conditional rule references: `references/invariants.md`, `references/compat.md`, `references/rules-ui.md`, `references/rules-testing.md`, and `references/rules-loop.md`.
- Extended validation to enforce compact Skill description length, progressive-loading path existence, required conditional references, and repeated-rule limits in `SKILL.md`.
- Added `scripts/check-routing-fixtures.py` for 3 route fixtures: backend CLI, UI replica, and long-running Lead LOOP.
- Added file-level rule validation so missing key rules report the exact owning file instead of only a combined-doc failure.
- Slimmed README/README.en rule sections into entrypoint indexes and centralized version narrative in `references/compat.md`.
- Bumped current Skill version to `V2.1`.
- Added `prompts/lead/loop.md` as the Lead LOOP Protocol with Loop Decision, Loop Gate, integration audit, state snapshot, auto-continuation, stop-boundary, and resume-state rules.
- Added `loop_decision_record` to the handoff artifact SSOT and propagated Lead LOOP fields into Lead planning, dispatch, audit, completion, Member Goal Packet, and Teams plan templates.
- Added `GT-BENCH-004` to benchmark Lead LOOP behavior across `baseline`, `goal-teams-v2.02`, and `goal-teams-v2.1-loop` modes.
- Bumped current Skill version to `V2.02`.
- Added `RULES.md` as the Response Contract for Goal Lead and member responses: execute first, report verified facts, avoid unverified success claims, distinguish observation from conclusion, and minimize unrelated commentary.
- Bumped current Skill version to `V2.01` and startup identity to `我是 Goal Teams Leader V2.01，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，并使用 Harness + SPEC 做为过程与结果产物的约束：`.
- Updated the Plan-mode historical-context prompt to use the `没有请回复“2”` shortcut and made the core Chinese output rule table-first.
- Bumped current Skill version to `V2.0` and startup identity to `我是 Goal Teams Leader V2.0，我会帮你完成以下工作：`.
- Required all SSOT outputs to live under output-directory version subdirectories such as `GoalTeamsWork-<project_version>/versions/<artifact_version>/`.
- Required each project to create `TaskList.md` before implementation or test execution, with feature-level rows for requirement spec, PRD, page spec, HTML prototype, frontend/backend architecture, backend TDD, backend implementation, API integration testing, E2E, BugFix, and test report.
- Added independent TDD/API/E2E subagents: `goal_unit_test_designer`, `goal_unit_test_runner`, `goal_api_integration_test_designer`, `goal_api_integration_test_runner`, `goal_e2e_test_designer`, and `goal_e2e_test_runner`.
- Required backend development to generate Backend Architecture Design before code, then follow TDD with independent unit-test authoring and execution.
- Required API integration test scripts to be generated after architecture design, defaulting to Python + pytest unless the project specifies another stack, and executed only after unit tests pass.
- Required frontend E2E tests to be generated after frontend development by a separate subagent and executed by another independent subagent.
- Bumped current Skill version to `V1.97` and startup identity to `我是 Goal Teams Leader V1.97，我会帮你完成以下工作：`.
- Added local bilingual Google OKF guidance in `references/google-okf-bilingual-spec.md` and made generated Markdown outputs default to OKF frontmatter with a required `type`.
- Changed the default output directory to `GoalTeamsWork-<project_version>/` when the user does not specify a directory.
- Added `prompts/packets/memory.md` and required output-directory `memory.md` to record important user settings, configuration, component library decisions, and context summaries from old to new with author `GoalTeams`.
- Added `prompts/packets/html-prototype-mock.md` and required HTML Prototype MOCK outputs to embed OKF metadata plus component library information.
- Extended page-spec-card, frontend, QA, reviewer, completion-auditor, runtime, README, and validation rules so page prototypes must clarify component library name/version/source or record a blocking question before generation.
- Added `prompts/packets/page-spec-card.md` for PRD-after page specification before HTML Prototype or frontend implementation.
- Added `references/ui-visual-contract-protocol.md` to prevent UI replica leaks from full-page-only pixel diff, visual overlays, missing component assertions, and missing dialog/form interaction states.
- Required frontend, QA, reviewer, and completion-auditor workflows to enforce page specs, component-level visual contracts, locked/unlocked screenshots, local crop/geometric assertions, and visual-risk coverage.
- Added `prompts/packets/handoff-artifacts.md` as the SSOT for Goal Teams handoff artifacts, Owner subagent, validator subagent, and status fields.
- Required every handoff artifact to be written into `tasklist.md` during execution with `handoff_status`, `independent_check_status`, Harness, evidence path, and blocker/defer reason.
- Updated member workflows, templates, runtime examples, README docs, subagent configs, and validation checks to enforce independent checks for every deliverable.
- Bumped current Skill version to `V1.96` and startup identity to `我是 Goal Teams Leader V1.96，我会帮你完成以下工作：`.
- Added user stories and functional acceptance criteria as required fields in requirement cards, Requirement Specification Cards, and PRD handoff.
- Required functional acceptance criteria to flow into tasklist, Harness, test plan, and acceptance evidence.
- Bumped current Skill version to `V1.95` and startup identity to `我是 Goal Teams Leader V1.95，我会帮你完成以下工作：`.
- Added Plan Mode `需求卡片` as a required pre-SPEC concise plan covering core goal, key functions, boundaries, constraints, and risks.
- Added `prompts/lead/requirement-card.md`, `prompts/packets/requirement-card.md`, and the mini-goal-run `spec/requirement-card.md` example.
- Bumped current Skill version to `V1.94` and startup identity to `我是 Goal Teams Leader V1.94，我会帮你完成以下工作：`.
- Added V1.94 member packages under `prompts/members/<role>/` with `prompt.md`, `template.md`, `workflow.md`, and `scripts.md`.
- Added LLM + script dual-review protocol plus artifact comparison and dual-review validation scripts.
- Slimmed `SKILL.md` into a compact core-question and progressive-loading entrypoint.
- Added role prompt directories under `prompts/lead/`, `prompts/members/`, and `prompts/packets/`.
- Moved real scripts into `scripts/checks/`, `scripts/harness/`, `scripts/benchmark/`, and `scripts/install/` while preserving root compatibility wrappers.
- Bumped current Skill version to `V1.92` and startup identity to `我是 Goal Teams Leader V1.92，我会帮你完成以下工作：`.
- Added V1.92 scripted tooling: local install, version sync, agent-name checks, Harness contract validation, pixel diff, and benchmark package validation.
- Added dispatch, Budget Gate, Conflict Policy, UI E2E/pixel protocol, and evidence-insufficiency rules.
- Added `GT-BENCH-003` for UI E2E, replica pixel comparison, and insufficient-evidence rejection.
- Bumped current Skill version to `V1.91` and startup identity to `我是 Goal Teams Leader V1.91，我会帮你完成以下工作：`.
- Required Goal Teams to prefer custom `goal_*` subagents and keep Chinese `member_id` / `display_name` in user-visible records even when the runtime or right sidebar returns English transport handles such as `Reviewer C`.
- Required E2E Harness evidence for every UI-level task, and screenshot-based pixel-level comparison evidence for replica/recreation UI tasks.
- Bumped current Skill version to `V1.9` and startup identity to `我是 Goal Teams Leader V1.9，我会帮你完成以下工作：`.
- Added V1.8 machine-readable automation protocol reference with `harness.yaml`, `evidence.jsonl`, `pipeline-state.json`, `failure_report`, and `approval_gate` templates.
- Added V1.9 production pipeline reference for `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`, including Release Gate and safety gate boundaries.
- Added mini-goal-run static samples for automation protocol, evidence ledger, and pipeline gates.
- Added `GT-BENCH-002` benchmark templates for production-flow gate packages, evidence completeness, auto-continuation, and safety boundaries.
- Extended `scripts/validate.py` to check V1.9, V1.8/V1.9 references, mini machine-readable samples, and `GT-BENCH-002`.
- Bumped current Skill version to `V1.7` and startup identity to `我是 Goal Teams Leader V1.7，我会帮你完成以下工作：`.
- Added V1.5 Harness and Loop rules: `SPEC` defines completion, `Harness Contract` defines verification, evidence is required before done, and Goal Teams now documents member, Lead, and Skill Improvement loops.
- Added V1.6 mini Harness replay artifacts under `examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/` with `setup -> run -> checks -> report`.
- Added V1.7 `benchmarks/` templates, including `GT-BENCH-001` task, manual harness, scoring rubric, and expected artifacts for comparing baseline vs Goal Teams.
- Extended `scripts/validate.py` to check V1.7, Harness example files, and benchmark templates.
- Bumped current Skill version to `V1.4` and startup identity to `我是 Goal Teams Leader V1.4，我会帮你完成以下工作：`.
- Added a Plan Mode startup clarification asking whether the user has historical documents, prior experience, or reference material to provide before planning.
- Added direct-execution trigger wording such as `直接执行`, `不用确认`, and `跳过确认`; the lead still shows the `Teams 规划表` as an execution record, then proceeds without waiting for the initial confirmation unless a safety gate applies.
- Added numbered Plan options so users can reply with simple choices like `1`, `2`, or `3`.
- Added repository-level maintenance guidance in `AGENTS.md`.
- Added `scripts/check.sh` and `scripts/validate.py` for package validation.
- Added `examples/mini-goal-run/` as a minimal Goal Teams output example.
- Documented validation and example workflows in both READMEs.
- Updated runtime subagent id, `member_id`, and display names to Chinese role + concrete task names, such as `后端-WIKI 列表后端开发`; when a user assigns a skill, the skill name is used, such as `browser-WIKI 列表页面验证`.
- Kept loadable technical subagent names such as `goal_backend` only in `skill_or_subagent`.
- Required task workflow safety fields in planning tables: serial/parallel workflow and predecessor tasks.
- Required final status tables to include `资源消耗（用户 / tokens / 费用）` for each task or subagent, using `未提供` when runtime usage is unavailable.
- Consolidated Chinese-output behavior into one core model prompt.
- Required a `Teams 规划表` for user confirmation before worker execution.
- Updated the `Teams 规划表` display to four merged columns while preserving the same planning fields.
- Added `goal_completion_auditor` for post-completion unfinished-work audits and automatic continuation cycles inside the confirmed scope.
- Kept License selection pending for the repository owner.
