# Goal Teams

[中文](README.md) | English

Author: 肉山@TGO Hangzhou

Current version: `V2.2`

`goal-teams` is a Codex Skill for running Goal Mode as a coordinated team. A Goal Lead turns one goal into a plan, assigns independent subagents or user-selected skills, controls serial/parallel workflow, records the process in Markdown, and closes the work with independent validation plus a completion audit.

## Core Model

Every run starts with:

```text
我是 Goal Teams Leader V2.2，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，并使用 Harness + SPEC 做为过程与结果产物的约束：
```

中文核心模型要点提示词:

```text
默认全程中文表格化输出计划、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。
```

## Rule Entrypoints

- `SKILL.md` is the trigger-oriented entrypoint with startup text, 7 invariants, planning checks, failure-degradation summary, and progressive-loading routes.
- `references/invariants.md` stores always-on invariants, hard boundaries, and the failure-degradation protocol.
- `references/compat.md` centralizes `TaskList.md`/`tasklist.md`, script compatibility wrappers, member-package layout, and version notes.
- `references/rules-ui.md`, `references/rules-testing.md`, and `references/rules-loop.md` are loaded only for UI, testing, and long-running LOOP scenarios.
- `prompts/packets/handoff-artifacts.md` is the handoff SSOT; `RULES.md` is the response contract for the Goal Lead and all members.

## Standard Flow

1. Turn the user goal into Done Criteria, then confirm project version, artifact version, and output directory.
2. Create or update `GoalTeamsWork-<project_version>/`, `memory.md`, and `versions/<artifact_version>/TaskList.md`.
3. Write `spec/requirement-card.md`, then prepare required SPEC, architecture, test plan, and acceptance docs.
4. Load UI, testing, or LOOP conditional rules as needed, then produce the `Teams 规划表`.
5. Dispatch independent members; each works under locked scope, Harness, handoff artifacts, and independent validation.
6. Integrate evidence and update TaskList, progress, acceptance, and any required `Loop Decision`.
7. Before completion, run `goal_completion_auditor`; continue confirmed-scope gaps through Lead LOOP and block out-of-scope issues.

## Teams 规划表

The table has four display columns, but every row keeps the underlying fields: member, skill/subagent, goal slice, claimed task, workflow, predecessor, locked scope, handoff artifact, artifact_type, Owner subagent, validator subagent, handoff status, check status, done criteria, Harness, docs/tasklist update, test owner, and validator.

| 成员 / Skill(Subagent) | Scope | Delivery / Criteria | Validation |
| --- | --- | --- | --- |
| Member: `需求分析-WIKI 列表需求澄清`<br>Skill/Subagent: `goal_requirements_analyst` | Goal slice: clarify WIKI list requirements<br>Claimed task: GT-001<br>Workflow: serial<br>Predecessor: -<br>Locked scope: `spec/` | Handoff artifact: Requirement Specification Card (`requirement_spec_card`)<br>Done criteria: user confirms goals, flow, and boundaries<br>Harness: structure and boundary checklist review<br>tasklist: Owner=`goal_requirements_analyst`, status=`planned` | Test owner: `评审-WIKI 列表需求校验`<br>Validator: `评审-WIKI 列表需求校验`<br>Check status: `not_started` |
| Member: `后端-WIKI 列表后端开发`<br>Skill/Subagent: `goal_backend` | Goal slice: WIKI list API<br>Claimed task: GT-003<br>Workflow: serial<br>Predecessor: GT-001, GT-002<br>Locked scope: `src/api/wiki/` | Deliverable: backend implementation<br>Done criteria: API contract tests pass<br>Harness: API contract tests + regression tests<br>Docs/tasklist: Architecture Design + tasklist.md | Test owner: `测试-WIKI 列表验收测试`<br>Validator: `评审-WIKI 列表代码审查` |
| Member: `browser-WIKI 列表页面验证`<br>Skill/Subagent: `browser` skill | Goal slice: page verification<br>Claimed task: GT-004<br>Workflow: parallel<br>Predecessor: GT-003<br>Locked scope: `src/ui/wiki/` | Deliverable: screenshots and console checks<br>Done criteria: desktop/mobile verification passes<br>Harness: screenshots + console error + viewport checks<br>Docs/tasklist: HTML Prototype + tasklist.md | Test owner: `测试-WIKI 列表验收测试`<br>Validator: `评审-WIKI 列表体验审查` |

Final report example:

| Member | Claimed Task | Workflow / Predecessor | Status | Evidence | 资源消耗（用户 / tokens / 费用） | Remaining |
| --- | --- | --- | --- | --- | --- | --- |
| `后端-WIKI 列表后端开发` | GT-003 | serial / GT-001, GT-002 | done | `npm test -- wiki` | 用户：Rou；tokens：未提供；费用：未提供 | none |

## Layout

Installed Skill package:

```text
goal-teams/
  VERSION
  SKILL.md
  goal-teams.md
  AGENTS.md
  RULES.md
  CHANGELOG.md
  README.md
  README.en.md
  agents/openai.yaml
  references/goal-teams-runtime.md
  references/default-AGENTS.md
  references/invariants.md
  references/compat.md
  references/rules-ui.md
  references/rules-testing.md
  references/rules-loop.md
  references/goal-teams-automation-protocol.md
  references/goal-teams-production-pipeline.md
  references/goal-teams-scripted-tooling.md
  references/google-okf-bilingual-spec.md
  references/ui-e2e-pixel-protocol.md
  references/ui-visual-contract-protocol.md
  references/subagent-dispatch-protocol.md
  references/dual-review-protocol.md
  prompts/lead/*.md
  prompts/packets/handoff-artifacts.md
  prompts/packets/page-spec-card.md
  prompts/packets/memory.md
  prompts/packets/html-prototype-mock.md
  prompts/members/shared.md
  prompts/members/<role>/prompt.md
  prompts/members/<role>/template.md
  prompts/members/<role>/workflow.md
  prompts/members/<role>/scripts.md
  prompts/packets/*.md
  scripts/check.sh
  scripts/validate.py
  scripts/install-local.sh
  scripts/check-version-sync.py
  scripts/check-routing-fixtures.py
  scripts/check-agent-names.py
  scripts/validate-harness.py
  scripts/pixel-diff.py
  scripts/compare-artifacts.py
  scripts/validate-dual-review.py
  scripts/check-member-layout.py
  scripts/benchmark-runner.py
  scripts/checks/*.py
  scripts/checks/check.sh
  scripts/harness/*.py
  scripts/review/*.py
  scripts/benchmark/*.py
  scripts/install/install-local.sh
  subagents/goal-*.toml
  examples/mini-goal-run/
  benchmarks/
```

Runtime files in target projects:

```text
GoalTeamsWork-<project_version>/
  index.md
  memory.md
  versions/
    <artifact_version>/
      index.md
      TaskList.md
      tasklist.md
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
      harness.yaml
      evidence.jsonl
      pipeline-state.json
```

## Default Members

| Subagent ID / Role Name | Main Responsibility |
| --- | --- |
| `goal_requirements_analyst` | Clarification, research-assisted analysis, Requirement Specification Card, PRD handoff |
| `goal_product` | PRD, acceptance criteria, prototype structure, product review |
| `goal_backend` | Domain model, storage, API, CLI, MCP, migrations, integrations |
| `goal_frontend` | UI, HTML prototype, browser verification, E2E, replica pixel comparison, screenshot evidence |
| `goal_unit_test_designer` | Backend TDD unit-test cases, assertions, and coverage notes |
| `goal_unit_test_runner` | Backend TDD unit-test execution, red/green evidence, failure report |
| `goal_api_integration_test_designer` | API integration scripts and matrix, default Python + pytest |
| `goal_api_integration_test_runner` | API integration execution, logs, reports, and failure responses |
| `goal_e2e_test_designer` | E2E cases, viewport coverage, and component assertions after frontend work |
| `goal_e2e_test_runner` | E2E execution, screenshots, traces, console/network evidence |
| `goal_qa` | Independent tests, integration tests, UI E2E, pixel-comparison acceptance, test reports |
| `goal_docs` | tasklist, acceptance, README, reports, release notes |
| `goal_reviewer` | Read-only review, architecture boundaries, security, coverage, compatibility, risk |
| `goal_completion_auditor` | Completion audit, unfinished-work check, auto-continuation suggestions |

## Installation

Clone into the Codex skills directory:

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

Or run the local installer:

```bash
./scripts/install-local.sh --update-team-fallback
```

Manual subagent copy:

```bash
mkdir -p ~/.codex/agents
cp ~/.codex/skills/goal-teams/subagents/goal-*.toml ~/.codex/agents/
```

Validate before maintenance releases:

```bash
./scripts/check.sh
```

`examples/mini-goal-run` provides a minimal output tree for checking indexes, SPEC, tasklist, the Teams plan table, independent validation, and completion audit. `goal-teams.md` records long-term user requirements and is the upstream reference for maintaining this Skill.

`examples/mini-goal-run` also includes `harness/` replay material that demonstrates the minimal static `setup -> run -> checks -> report` chain, plus static automation protocol, evidence ledger, and pipeline gate samples. `benchmarks/` provides `GT-BENCH-001`, `GT-BENCH-002`, `GT-BENCH-003`, and `GT-BENCH-004` templates for comparing baseline and Goal Teams output quality, evidence completeness, production gate judgment, UI E2E/pixel evidence handling, Lead LOOP state recovery, and cost.

V1.92 adds `references/goal-teams-scripted-tooling.md`, `references/ui-e2e-pixel-protocol.md`, and `references/subagent-dispatch-protocol.md`.

V1.93 adds `prompts/lead/`, `prompts/members/`, and `prompts/packets/`, and moves real scripts into `scripts/checks/`, `scripts/harness/`, `scripts/benchmark/`, and `scripts/install/`; root entries such as `scripts/check.sh` remain compatible.

V1.94 adds member-package subdirectories, `references/dual-review-protocol.md`, `prompts/packets/dual-review-record.md`, `scripts/checks/check-member-layout.py`, `scripts/review/compare-artifacts.py`, and `scripts/review/validate-dual-review.py`. Comparison and validation tasks must include both script-review evidence and LLM-review evidence.

V1.95 adds `prompts/lead/requirement-card.md` and `prompts/packets/requirement-card.md`, requiring Plan Mode to write `spec/requirement-card.md` first with core goal, key functions, boundaries, constraints, and risks.

V1.96 adds user-story and functional-acceptance requirements: the requirement card uses “作为...我想要...以便...” stories and verifiable functional acceptance criteria; PRD, tasklist, Harness, test plan, and acceptance must carry them forward.

V1.97 adds `references/google-okf-bilingual-spec.md`, `prompts/packets/page-spec-card.md`, `prompts/packets/memory.md`, and `prompts/packets/html-prototype-mock.md`, while strengthening `references/ui-visual-contract-protocol.md` and `references/ui-e2e-pixel-protocol.md`. Generated Markdown defaults to OKF; unspecified outputs go to `GoalTeamsWork-<project_version>/`; Page Specification Cards and HTML prototypes must record component library name, version, source, per-element library ownership, and data models where applicable.

V2.2 adds the slim entrypoint, conditional rule files, routing fixtures, file-level rule validation, and a slimmer README to reduce upfront context and maintenance risk.

The V2.2 maintenance layout keeps `SKILL.md` as a trigger-oriented entrypoint and loading router, adding `references/invariants.md`, `references/compat.md`, `references/rules-ui.md`, `references/rules-testing.md`, and `references/rules-loop.md` for conditionally loaded invariants, compatibility, UI, testing, and LOOP rules.

V2.1 adds `prompts/lead/loop.md`, Lead LOOP Protocol, Loop Decision, Loop Gate, state snapshot rules, and `GT-BENCH-004` for evaluating mid-run evidence gaps, auto-continuation, stop boundaries, and state recovery.

Version Note: `VERSION` is the source of truth; historical `V2.02` and `V2.1` are patch lines before `V2.2`, and future releases should prefer `V2.3`, `V2.4`, and similar increasing labels.

V2.02 adds the `RULES.md` response contract, requiring the Goal Lead and all members to execute first, report facts, avoid unverified success claims, and reduce unrelated explanation.

V2.01 updates the startup identity to make Goal + Plan execution explicit for planning, execution, and application delivery, with Harness + SPEC as the process and result constraints. The Plan-mode history prompt now supports `没有请回复“2”`, and the Chinese-output rule emphasizes table-first delivery.

V2.0 adds version-subdirectory SSOT, TaskList-first execution, backend architecture-first TDD, independent unit-test authoring/execution, API integration script/execution roles, frontend E2E case/execution roles, and matching member packages plus `goal_*.toml` subagents.

## Examples

Plan and wait for confirmation:

```text
Use $goal-teams。
请为“分时租赁 V3.0”做 Goal Teams 计划。
过程和结果保存到 `GoalTeamsWork-V3.0/`。
先生成带用户故事和功能验收标准的需求卡片，再生成需求规格卡和 PRD。
```

Direct execution:

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

## Release Contents

This repository includes `VERSION`, `SKILL.md`, `RULES.md`, `agents/openai.yaml`, `references/goal-teams-runtime.md`, `references/default-AGENTS.md`, `references/invariants.md`, `references/compat.md`, `references/rules-ui.md`, `references/rules-testing.md`, `references/rules-loop.md`, `references/goal-teams-automation-protocol.md`, `references/goal-teams-production-pipeline.md`, `references/goal-teams-scripted-tooling.md`, `references/google-okf-bilingual-spec.md`, `references/ui-e2e-pixel-protocol.md`, `references/ui-visual-contract-protocol.md`, `references/subagent-dispatch-protocol.md`, `references/dual-review-protocol.md`, `prompts/lead/core.md`, `prompts/lead/loop.md`, `prompts/lead/requirement-card.md`, `prompts/members/shared.md`, `prompts/members/backend/prompt.md`, `prompts/members/backend/template.md`, `prompts/members/backend/workflow.md`, `prompts/members/backend/scripts.md`, `prompts/members/unit-test-designer/prompt.md`, `prompts/members/unit-test-runner/prompt.md`, `prompts/members/api-integration-test-designer/prompt.md`, `prompts/members/api-integration-test-runner/prompt.md`, `prompts/members/e2e-test-designer/prompt.md`, `prompts/members/e2e-test-runner/prompt.md`, `prompts/packets/member-goal-packet.md`, `prompts/packets/handoff-artifacts.md`, `prompts/packets/page-spec-card.md`, `prompts/packets/memory.md`, `prompts/packets/html-prototype-mock.md`, `prompts/packets/requirement-card.md`, `prompts/packets/dual-review-record.md`, `subagents/goal-*.toml`, `goal-teams.md`, `AGENTS.md`, `scripts/check.sh`, `scripts/validate.py`, `scripts/install-local.sh`, `scripts/check-version-sync.py`, `scripts/check-routing-fixtures.py`, `scripts/check-agent-names.py`, `scripts/check-member-layout.py`, `scripts/validate-harness.py`, `scripts/pixel-diff.py`, `scripts/compare-artifacts.py`, `scripts/validate-dual-review.py`, `scripts/benchmark-runner.py`, `scripts/checks/`, `scripts/checks/check-routing-fixtures.py`, `scripts/harness/`, `scripts/review/`, `scripts/benchmark/`, `scripts/install/`, `prompts/`, `examples/mini-goal-run`, `benchmarks/`, `CHANGELOG.md`, `README.md`, and `README.en.md`.

## License

If this repository is published as open source, add an explicit license such as MIT, Apache-2.0, or an internal sharing agreement.
