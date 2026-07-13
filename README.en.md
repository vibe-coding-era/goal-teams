# Goal Teams

[中文](README.md) | English

Author: 肉山@TGO Hangzhou

Current version: `V2.39`

Goal Teams is a Codex Skill for coordinated agent work. It turns one goal into a verifiable plan, then lets a Goal Lead coordinate subagents or user-selected external skills across requirements, design, implementation, tests, evidence, and completion audit. A separate subagent counts as an independent acceptance identity only when its isolated context is bound to a host attestation.

The version model has three layers so that release identity, policy, and data format are not conflated:

| Layer | Current value | Purpose |
| --- | --- | --- |
| Product version | `V2.39` | Version of the Skill package, startup line, and release documentation. |
| General core policy | `V2.5` / `goal-teams-core-v2.5` | Task routing, execution class, and gates for ordinary projects. |
| Legacy data schema | `V2.3` | Compatibility for existing ledger, Evidence, Harness, and release-gate data; it is not the current product version. |

Only a current release of the Goal Teams repository itself uses `goal-teams-self-release-v2.39`. Its 52 release assertions, iterations 9/11, four-dimension scoring, prompt identity, Cache Evidence, OKF gate, and public archive do not apply as global invariants to ordinary projects; `goal-teams-self-release-v2.38` is retained only for historical replay. `profile=lite|standard|full|regulated` remains the execution class and is distinct from `policy_profile`.

Use it when:

- The task should be planned before execution.
- The task needs multiple roles or parallel work, and those roles should reason and deliver in isolated Subagent contexts.
- The task should leave SPEC, TaskList, Harness, Evidence, and acceptance records.
- The task includes backend TDD, API integration tests, frontend E2E, UI recreation, or pixel comparison.
- The task is long enough to need Lead LOOP state, auto-continuation, and clear stop boundaries.
- The task should combine external skills, existing project tools, or user-selected subagents.

Do not use it for:

- A simple one-off answer.
- A tiny single-file edit that does not need team coordination or evidence tracking.
- Real production approval, CI/CD, or background execution. Goal Teams provides coordination rules and local scripts; it does not replace external systems.

## Core Mechanisms

### Goal + Plan + Loop

Goal Teams splits complex collaboration into three layers:

- Goal defines the target and Done Criteria, so the team agrees on what completion means.
- Plan turns the target into members, Subagent contexts, scope, handoff artifacts, verification method, and stop conditions. This reduces scope drift and concurrent-edit conflicts.
- Loop records `loop_decision=continue|replan|stop` after each integration and keeps `run_outcome`, task/check state, and stop reasons orthogonal for recovery and audit.

The useful part is not simply running more agents. The useful part is that different roles work in isolated contexts while the Goal Lead keeps the target, scope, and evidence consistent. A chat request becomes an engineering process that can be traced.

### SPEC + Harness + SSOT

Goal Teams uses `SPEC -> Harness -> Evidence -> Audit` as the verification chain, with SSOT controlling handoff vocabulary:

- SPEC defines what should be completed, including requirements, boundaries, user stories, functional acceptance criteria, architecture, and test plan.
- Harness defines how completion is proven, including commands, scripts, E2E, screenshots, manual checklists, and evidence paths.
- SSOT defines the one authoritative handoff model, including artifact type, Owner, validator, status fields, and TaskList ledger format.

Together, these mechanisms make the Skill produce more than a plan. They create an evidence structure that members can execute, scripts can check, reviewers can inspect, and auditors can close. For complex application work, this is stronger than code output alone because completion must be proven.

### Benchmark

Goal Teams includes `benchmarks/` task packages for comparing workflow, prompt, or skill-version behavior. Benchmark is not a default output for ordinary tasks; it is used when the user asks for it, the plan confirms it, or a Skill Improvement task needs repeatable comparison.

The value is that benchmark results make improvement reviewable. The same task can compare baseline and Goal Teams behavior across output completeness, evidence quality, UI verification, production-gate judgment, Loop state recovery, and cost. This repository includes `GT-BENCH-001` through `GT-BENCH-004`, covering typical dimensions from basic output quality to Lead LOOP recovery.

### Prompt Cache Observability

V2.39 retains the V2.38-compatible prompt-cache schema, compilers, observer reports, fixtures, and replay behavior while switching current self-release ordered refs to the V2.39 Profile. `references/prompt-cache-manifest.json` remains the machine SSOT for route-static order and byte budgets. `route_static_digest` binds planned paths and file bytes. When the repository cannot observe the final provider request, it reports `manifest_status=unavailable` and `digest_scope=partial` instead of impersonating a `runtime_prompt_digest`; the full install remains bound by `skill_tree_digest`.

This release reports four orthogonal cache states: structural validation `passed`, host integration `unavailable`, live probe `not_authorized`, and request hit rate `unavailable`. Its claim scope is limited to `structural_governance`; without trusted host observation, user authorization, and provider request semantics, it makes no live optimization, provider-hit, or request-hit-rate claim.

For byte-compatible historical signatures and replay, the V2.35/V2.36 `rule_set` remains a policy-membership set rather than prompt order; `prompt-plan --features` compiles it into a manifest-managed ordered subset.

After each turn, the runner reports token-weighted share, uncached input, and coverage; request hit rate stays null without request events. A cache conclusion requires clean versioned telemetry, complete prompt identity, and trusted host config attestation together. This runner does not yet have that attestation, so live cache analytics remains unsupported.

The repository currently compiles only a first-seen plus five-repeat probe plan. It makes no provider calls and claims neither cold runs nor live A/B records; `live_ab_status=unavailable`. A future executor must bind model, CLI, package, configuration, scorer/Harness, and the observed prompt identity. Goal Teams cannot force, clear, or guarantee a provider prompt cache.

### Openness and External Skills

Goal Teams does not require every capability to come from a built-in subagent. During Plan, external skills, project scripts, browser tools, test tools, or user-selected subagents can be added to the `Teams 规划表` with locked scope, inputs, outputs, Harness, and validator.

This makes Goal Teams an orchestration layer. It keeps the goal, plan, handoff artifacts, and evidence consistent; concrete capabilities can come from `goal_*` subagents or external skills such as browser verification, document generation, security review, PDF/spreadsheet handling, or project-specific tools. Once an external capability joins the team, it still follows SSOT, Harness, and independent validation rules.

## Quickstart

Install into your local Codex skills directory:

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

Install or refresh from this repository:

```bash
./scripts/install-local.sh --update-team-fallback
```

Validate before maintenance or release:

```bash
./scripts/check.sh
```

A GitHub Release must be built locally as the same reproducible asset and pass source-bound validation before upload:

```bash
python3 scripts/release/build-release.py --version V2.39 --ref HEAD
python3 scripts/release/validate-release.py --version V2.39
scripts/release/publish-github-release.sh V2.39
```

Local release directories live at `release/versions/<VERSION>/`. Root `docs/` contains non-release knowledge, tests, and credentials only and is excluded by `.gitignore`. See `references/release-packaging-protocol.md` for the full contract.

The standalone deterministic routing check is `scripts/checks/check-routing-fixtures.py` (compatibility entrypoint: `scripts/check-routing-fixtures.py`).

`./scripts/check.sh` covers deterministic contract/mutation gates only; it is not real Behavior release evidence. Before RC, choose a new persistent directory outside the source repository, run the nine isolated blind scenarios, and pass their summary to the combined gate:

```bash
BLIND_OUTPUT=/absolute/path/outside/goal-teams/blind-v23-<run-id>
python3 scripts/benchmark/benchmark-runner.py --mode blind-agent --release-gate \
  --manifest tests/v23/fixtures/behavior/blind-agent-codex.json \
  --output-dir "$BLIND_OUTPUT"
python3 scripts/v23/goalteams_v23.py release-gate examples/canonical-v23 \
  --mode rc --blind-summary "$BLIND_OUTPUT/summary.json"
```

This eval invokes the Codex CLI resolved in the current environment and locks its local hash. Its trust level is `local_process_attested`, not a remote-model or code-signature attestation. Mocks/fixtures, reused directories, alternate manifests, incomplete scenarios, or a missing summary cannot satisfy RC. The combined gate rescans the fixed output/trace/evidence set and runs the full `scripts/check.sh` in the same call. A local License file is only a GA proposal until a trusted external owner attestation exists.

Copy subagents manually:

```bash
mkdir -p ~/.codex/agents
cp ~/.codex/skills/goal-teams/subagents/goal-*.toml ~/.codex/agents/
```

## Usage

The simplest direct-execution form:

```text
Use $goal-teams to complete the backend API, frontend pages, and acceptance tests for Rental V3.0.
Keep the LOOP running and finish only after an independent audit passes.
```

The Goal Lead converts the objective into Done Criteria, creates the versioned SSOT, `TaskList.md`, and Harness/Evidence, then dispatches members according to scope and risk. Users do not need to select every role manually.

Plan and wait for confirmation:

```text
Use $goal-teams to plan Rental V3.0 and save the work under `GoalTeamsWork-V3.0/`.
Create the requirement card, PRD, architecture design, and Teams plan first, then wait for my confirmation.
```

Return only an in-chat plan without files or members:

```text
Use $goal-teams in planning-only mode. Do not create or modify files and do not dispatch members.
Return the plan preview in chat.
```

Continue a long-running task automatically:

```text
Use $goal-teams to complete the full V3.0 implementation without asking about routine choices.
Keep the LOOP running: record each decision/outcome and continue fixing gaps until the independent Completion Audit passes.
```

Members and tools can be named when needed. Each member reads its own `INDEX.md` first and progressively loads only the required files:

```text
Use goal_requirements_analyst for requirements and goal_security for a read-only security audit.
Use the browser skill for page verification and independent members for E2E case design and execution.
```

Use this identity line on an explicit Goal Teams invocation or when the session first needs to establish identity; do not repeat it when full context already exists:

```text
我是 Goal Teams Lead V2.39。
```

Core language rule: user communication and governance documents default to Chinese; code, comments, test names, fixtures, and product strings follow the target repository's conventions; keep identifiers, commands, paths, API names, config keys, subagent IDs, and exact references unchanged.

## Rule Entrypoints

`SKILL.md` is the trigger-oriented entrypoint. It keeps only the startup line, invariants, planning checks, failure-degradation summary, and progressive-loading routes. Detailed rules live in references and prompts, and are loaded by task type.

| File | Purpose |
| --- | --- |
| `RULES.md` | Response contract for the Goal Lead and members: execute first, report verified facts, and avoid unverified completion claims. |
| `SKILL.md` | Skill discovery entrypoint and loading router. Its `description` keeps trigger terms such as `$goal-teams`, `Goal Mode`, `Plan Mode`, `先规划`, `只规划`, and `需求卡片`. |
| `references/invariants.md` | Always-on invariants, hard boundaries, and failure-degradation protocol. |
| `references/compat.md` | `TaskList.md`/`tasklist.md`, script compatibility wrappers, member-package layout, and version sync rules. |
| `references/rules-ui.md` | UI, Page Specification Card, HTML Prototype MOCK, E2E, and pixel-comparison rules. |
| `references/rules-testing.md` | Backend architecture-first, TDD, API integration pytest, frontend E2E, and independent testing rules. |
| `references/rules-loop.md` | Lead LOOP, Loop Decision, Loop Gate, Budget Gate, and auto-continuation boundaries. |
| `references/goal-teams-core-v2.5.md` | General policy, Lite/Standard/Full/Regulated routing, and automatic gate derivation for ordinary projects. |
| `references/profiles/goal-teams-self-release-v2.39.md` | Dedicated Profile used only for the current Goal Teams repository release. |
| `references/profiles/goal-teams-self-release-v2.38.md` | Read-only replay Profile for historical V2.38 objects. |
| `references/prompt-cache-manifest.json` | Machine SSOT for route-static order, artifact compilers, and context budgets. |
| `references/prompt-cache-protocol.md` | Route/runtime identity boundaries, observer telemetry, and plan-only probe semantics. |
| `scripts/v23/prompt_compilers.py` | Deterministic subagent-prefix and Member Goal Packet compiler/migrator. |
| `scripts/v23/prompt_cache.py` | Safely reads the ordered manifest, computes prompt identities, and aggregates provider/CLI usage events. |
| `prompts/packets/handoff-artifacts.md` | Handoff SSOT for artifact types, Owner, validator, status fields, and TaskList ledger format. |

## Workflow

1. Convert the user goal into Done Criteria.
2. Confirm project version, artifact version, and output directory.
3. If the user explicitly requests an in-chat `plan_preview` / no-write result, return the plan without creating files, a ledger, TaskList, or subagents. Other modes create or update `GoalTeamsWork-<project_version>/memory.md`, establish the versioned append-only ledger, and generate `TaskList.md` through the reducer.
4. Outside `plan_preview`, Plan Mode writes `spec/requirement-card.md` before the applicable PRD, architecture, test-plan, and acceptance artifacts.
5. Load UI, testing, or LOOP conditional rules as needed.
6. Show the four-column `Teams 规划表`, then dispatch independent members.
7. Each member works inside its locked scope and submits revision-bound events/patches, Harness, and Evidence; members do not edit the central TaskList.
8. The ledger owner merges events and renders the TaskList projection; the Goal Lead records `loop_decision` and `run_outcome` separately.
9. Before completion, launch a fresh read-only `goal_completion_auditor`. Gaps inside confirmed scope continue only in the current session when the host supports it; new scope, high-risk work, or authorization issues stop for the user.

## Output Layout

Default output directory:

```text
GoalTeamsWork-<project_version>/
  index.md
  memory.md
  versions/
    <artifact_version>/
      index.md
      TaskList.md
      ledger/events.jsonl
      ledger/checkpoint.json
      identity/registry.json
      plan.md
      progress.md
      decisions.md
      goal-packet.md
      spec/
        requirement-card.md
        requirement-spec-card.md
        PRD.md
        page-spec-card.md
        frontend-architecture-design.md
        backend-architecture-design.md
        HTML-prototype.html
        test-plan.md
        acceptance.md
      tests/
        unit/
        api-integration/
        e2e/
        reports/
      artifacts/
      harness/harness.json
      harness/traceability.json
      evidence/evidence.jsonl
      reviews/dual-review.json
      reviews/semantic-review.md
      audit/completion-audit.json
      capability/manifest.json       # when host capabilities need a record
      release/license-decision.json  # only when the repository owner authorizes GA
```

`tasklist.md` remains readable as legacy input; V2.3 writes only the reducer-generated `TaskList.md`. Machine paths are defined by `schemas/v2.3/goal-teams.schema.json`; root-level V1.8 `harness.yaml`, `evidence.jsonl`, and `pipeline-state.json` are legacy/optional protocol artifacts and do not form a V2.3 completion closure.

## Default Members

| Subagent ID | Main responsibility |
| --- | --- |
| `goal_requirements_analyst` | Clarification, research-assisted analysis, Requirement Specification Card, and PRD input. |
| `goal_product` | PRD, acceptance criteria, prototype structure, and product review. |
| `goal_backend` | Domain model, storage, API, CLI, MCP, migrations, and integrations. |
| `goal_frontend` | UI, HTML prototype, browser verification, E2E, replica pixel comparison, and screenshot evidence. |
| `goal_unit_test_designer` | Backend TDD unit-test cases, assertions, and coverage notes. |
| `goal_unit_test_runner` | Backend TDD unit-test execution, red/green evidence, and failure reports. |
| `goal_api_integration_test_designer` | API integration scripts and test matrix, defaulting to Python + pytest. |
| `goal_api_integration_test_runner` | API integration execution, logs, reports, and failure responses. |
| `goal_e2e_test_designer` | E2E cases, viewport coverage, and component assertions after frontend work. |
| `goal_e2e_test_runner` | E2E execution, screenshots, traces, and console/network evidence. |
| `goal_qa` | Independent tests, integration tests, UI E2E, pixel-comparison acceptance, and test reports. |
| `goal_docs` | Acceptance, README, reports, and release notes; TaskList changes are handed off as events/patches. |
| `goal_reviewer` | Read-only review, architecture boundaries, security, coverage, compatibility, and risk. |
| `goal_security` | Read-only security scope, dependency, port, and injection analysis/proposals; no direct scan, implementation, or dispatch. |
| `goal_performance` | Read-only SQL/page/data-path baselines and benchmark proposals; no improvement claim without current Evidence. |
| `goal_refactor` | Read-only engineering/code/document refactor, behavioral-equivalence, and rollback proposals. |
| `goal_sqa` | Read-only process, document classification, version index, and public/private archive proposals. |
| `goal_completion_auditor` | Completion audit, unfinished-work checks, and session-scoped continuation suggestions. |

## Design Sources

| Principle or technology | Why Goal Teams uses it | Source |
| --- | --- | --- |
| Codex Skill | Goal Teams is a reusable workflow, not an app. A skill can package instructions, references, and scripts so Codex can follow the same workflow repeatedly. | [OpenAI Codex Agent Skills](https://developers.openai.com/codex/skills) |
| Trigger-oriented `description` | Codex can implicitly select a skill from its `description`, so the core use case and trigger words must be concise and front-loaded. | [OpenAI Codex Agent Skills: How Codex uses skills](https://developers.openai.com/codex/skills) |
| Progressive loading | Load a small entrypoint first, then read conditional rules only when needed. This reduces context use and avoids irrelevant rule noise. | [OpenAI Codex Agent Skills](https://developers.openai.com/codex/skills), [NN/g Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/) |
| SSOT | Handoff artifacts, Owner, validator, and status fields need one authority so member packets, TaskList, and acceptance records do not diverge. | [Atlassian: Single Source of Truth](https://www.atlassian.com/work-management/knowledge-sharing/documentation/building-a-single-source-of-truth-ssot-for-your-team), `prompts/packets/handoff-artifacts.md` |
| OKF Markdown | Goal Teams artifacts must be readable by people and agents. OKF uses Markdown plus YAML frontmatter, which works well with version control, indexing, and exchange across tools. | [GoogleCloudPlatform Open Knowledge Format SPEC](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md), `references/google-okf-bilingual-spec.md` |
| Requirements-to-test traceability | Requirements, tests, evidence, and acceptance need links so the team can decide whether the work is actually complete. | [NASA Software Test Procedures](https://swehb.nasa.gov/display/SWEHBVD/5.14%2B-%2BTest%2B-%2BSoftware%2BTest%2BProcedures?desktop=true&macroName=show-if) |
| TDD | Backend work writes tests before implementation to turn requirements into executable constraints and expose drift early. | [Martin Fowler: Test-Driven Development](https://martinfowler.com/bliki/TestDrivenDevelopment.html) |
| pytest | API integration defaults to Python + pytest because pytest keeps tests readable, gives clear failure output, and scales to larger suites. | [pytest documentation](https://docs.pytest.org/en/stable/) |
| Playwright E2E | UI work needs browser-level evidence. Playwright supports browser selection, viewport coverage, traces, screenshots, and pytest integration. | [Playwright Python Pytest plugin](https://playwright.dev/python/docs/test-runners), `references/ui-e2e-pixel-protocol.md` |
| Lead LOOP | Long tasks often fail because evidence gaps, scope drift, and state loss appear mid-run. Loop Decision records what happened after each integration. | `references/rules-loop.md`, `prompts/lead/loop.md` |

## Examples and Regression Checks

`examples/mini-goal-run` provides a minimal output tree for checking index files, SPEC, TaskList, Teams planning, Harness, Evidence, independent validation, and completion audit.

`benchmarks/` provides `GT-BENCH-001`, `GT-BENCH-002`, `GT-BENCH-003`, and `GT-BENCH-004` templates for comparing baseline and Goal Teams behavior across output quality, evidence completeness, production gate judgment, UI evidence handling, Lead LOOP state recovery, and cost.

`goal-teams.md` records long-term user requirements and is the upstream source for maintaining runtime rules.

## Version Note

The product version is read from `VERSION`. `V2.39` keeps `V2.5` as the ordinary-project core and uses the dedicated `goal-teams-self-release-v2.39` Profile. Without rewriting V2.38 schemas, fixtures, or replay behavior, this release adds a trusted Cache Evidence contract and full/package Google OKF gates. Structural validation passed; host integration is unavailable, the live probe was not authorized, and request hit rate is unavailable. Therefore the release claims structural/governance completion only and does not claim provider-cache control or live optimization effectiveness. Existing machine data remains compatible with the legacy `V2.3` schema.

See [`release/current/`](release/current/README.md) for the current release note and minimal public manifest. Historical process documents, the complete local knowledge base, integration catalog, and release evidence stay in ignored `docs/` and are excluded from GitHub and the install package.

## License

This repository does not currently declare an open-source license. The owner should first choose a license or internal sharing agreement; that local decision is only a proposal, and GA authorization additionally requires a trusted external host/signature attestation. The current technical deliverable is RC at most.

## Legacy V2.3 Data Schema and Release Compatibility

The legacy V2.3 schema defines closed state enums, a single-writer ledger, Evidence/Traceability, typed migration, and release-gate data. V2.39 continues to read that data; this does not make V2.3 the product version. See `references/goal-teams-v2.3-contract.md` and run `./scripts/check.sh` before release. Technical RC and authorized GA distribution are evaluated separately; even with an owner License/internal-sharing decision, the GA gate must remain fail-closed until a trusted external host/signature attestation exists.
