# Goal Teams

[中文](README.md) | English

Author: 肉山@TGO Hangzhou

Current version: `V2.34`

Goal Teams is a Codex Skill for coordinated agent work. It turns one goal into a verifiable plan, then lets a Goal Lead coordinate independent subagents running in separate contexts, or user-selected external skills, across requirements, design, implementation, tests, evidence, and completion audit.

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

Plan and wait for confirmation:

```text
Use $goal-teams。
请为“分时租赁 V3.0”做 Goal Teams 计划。
过程和结果保存到 `GoalTeamsWork-V3.0/`。
先生成带用户故事和功能验收标准的需求卡片，再生成需求规格卡和 PRD。
```

Execute directly:

```text
Use $goal-teams。
请直接执行：为 WIKI 列表 V2.0 规划并实现后端 API、页面验证、独立测试和验收文档。
仍然先展示 Teams 规划表作为执行记录，但不用等我确认。
```

Assign capabilities:

```text
Use $goal-teams。
需求分析使用 goal_requirements_analyst。
页面验证使用 browser skill。
测试成员使用 goal_qa。
安全审核使用 goal_reviewer，只读模式。
```

Use this identity line on an explicit Goal Teams invocation or when the session first needs to establish identity; do not repeat it when full context already exists:

```text
我是 Goal Teams Lead V2.34。
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

The current version is read from `VERSION`. On the V2.3 machine-contract baseline, `V2.34` adds contract-first execution, Architecture and Environment Evidence gates, a recoverable `Gather → Reason → Act → Verify → Repeat` LOOP, four-file disk state, a constrained iteration-9 candidate reset, a fail-closed iteration-11 delivery gate, four-dimensional scoring, and divergence/bottleneck records. Detailed contracts are loaded from `references/` by task type. After completion, only audited public documents with invocation traces removed are archived under `docs/archive/V2.34/<delivery_id>/`; process ledgers and provenance remain in the non-public workspace.

See [Release Contents](docs/release-contents.en.md) for the visible package inventory, or [发布内容](docs/release-contents.md) for Chinese. The inventory does not replace runtime rules, `VERSION`, or installation validation.

See [Change History](docs/change-history.en.md) for the chronological version summary, or [版本变更记录](docs/change-history.md) for Chinese. `CHANGELOG.md` retains the compatibility record of individual technical changes.

## License

This repository does not currently declare an open-source license. The owner should first choose a license or internal sharing agreement; that local decision is only a proposal, and GA authorization additionally requires a trusted external host/signature attestation. The current technical deliverable is RC at most.

## V2.3 Contract and Release Boundary

V2.3 adds deterministic machine contracts for closed state enums, a single-writer ledger, strict Evidence/Traceability, capability degradation, Profile routing, typed migration, and release gates. See `references/goal-teams-v2.3-contract.md` and run `./scripts/check.sh` before release. Technical RC and authorized GA distribution are evaluated separately; even with an owner License/internal-sharing decision, the GA gate must remain fail-closed until a trusted external host/signature attestation exists.
