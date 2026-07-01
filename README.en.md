# Goal Teams

[中文](README.md) | English

Author: 肉山@TGO Hangzhou

Current version: `V2.01`

`goal-teams` is a Codex Skill for running Goal Mode as a coordinated team. A Goal Lead turns one goal into a plan, assigns independent subagents or user-selected skills, controls serial/parallel workflow, records the process in Markdown, and closes the work with independent validation plus a completion audit.

## Core Model

Every run starts with:

```text
我是 Goal Teams Leader V2.01，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，并使用 Harness + SPEC 做为过程与结果产物的约束：
```

中文核心模型要点提示词:

```text
默认全程中文表格化输出计划、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。
```

Core rules:

- SSOT is a core rule: handoff artifact types, Owner subagent, validator subagent, status fields, and the tasklist ledger format are defined by `prompts/packets/handoff-artifacts.md` as the Single Source of Truth.
- Any role workflow, template, README, runtime example, or Member Goal Packet that mentions handoff artifacts must reference or stay synchronized with this SSOT; do not create a separate handoff vocabulary.
- During execution, every handoff artifact must be recorded in the tasklist with Owner subagent, validator subagent, completion status, independent check status, Harness, evidence path, and blocker/defer reason.

How Goal Teams works:

- The Goal Lead clarifies the target, splits tasks, confirms workflow, assigns members, integrates results, and routes blockers.
- In Plan Mode, after the startup line and work items, ask: `在开始规划前，如果有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“2”。`
- In Plan Mode, write a `需求卡片` first: a concise plan covering core goal, key functions, user stories, functional acceptance criteria, boundaries, constraints, and risks before full SPEC, tasklist, and the Teams plan table.
- For default subagent members, the runtime subagent id, `member_id`, and display name use `<Chinese role>-<task>`, such as `后端-WIKI 列表后端开发`; the loadable subagent config name stays in `skill_or_subagent`, such as `goal_backend`.
- If the user assigns a skill, the runtime subagent id, `member_id`, display name, and `role` use the skill name prefix, such as `browser-WIKI 列表页面验证`.
- V1.91 prefers custom `goal_*` subagents by default. If the runtime or Codex right sidebar shows an English nickname such as `Reviewer C` or `QA B`, treat it only as a transport handle; user-visible tables, packets, state, and final reports still use Chinese member names.
- Every task states whether its workflow is serial or parallel; serial tasks list predecessors so shared scopes are not edited concurrently.
- `SPEC` defines completion criteria, `Harness` defines the verification contract, `Evidence` records traceable proof, `Pipeline` records R&D/release state, `Benchmark` defines the outer evaluation task set, and `Loop` defines member, Lead, and Skill Improvement cycles.
- Harness is not a new runtime executor. It appears as checks, commands, manual checklists, evidence paths, and failure-report formats in the Plan, tasklist, Member Goal Packet, test plan, and acceptance docs.
- Every UI-level task must run an E2E test. Replica/recreation tasks must take screenshots and perform pixel-level comparison, recording the baseline, actual screenshot, diff image or metric, threshold, viewport, and conclusion.
- V1.92 uses a prompt + scripted-tooling split: prompts handle goal interpretation, dispatch, conflicts, budgets, and risk judgment; scripts handle version sync, agent naming, Harness schema, pixel diff, benchmark package checks, and local installation.
- V1.93 keeps `SKILL.md` as the compact core-question and progressive-loading entrypoint. Lead, member-role, and packet prompts live under `prompts/`; scripts are grouped under `scripts/checks/`, `scripts/harness/`, `scripts/benchmark/`, and `scripts/install/`, with root compatibility wrappers preserved.
- V1.94 turns `prompts/members/` into role-specific member packages. Each member directory contains `prompt.md`, `template.md`, `workflow.md`, and `scripts.md`; comparison and validation tasks require LLM + script dual review.
- V1.95 adds the Plan Mode `需求卡片`, written by default to `GoalTeamsWork-<project_version>/spec/requirement-card.md`, as input for the Requirement Specification Card, PRD, tasklist, and Harness.
- V1.96 requires the requirement card, Requirement Specification Card, and PRD to carry user stories and functional acceptance criteria through tasklist, Harness, test plan, and acceptance.
- V1.97 makes Google OKF the default generated Markdown format. If no output directory is specified, outputs go to `GoalTeamsWork-<project_version>/` with a maintained `memory.md`.
- V2.0 requires all SSOT outputs under `GoalTeamsWork-<project_version>/versions/<artifact_version>/`, creates `TaskList.md` before work, runs backend architecture-before-TDD, defaults API integration tests to Python + pytest, and separates frontend E2E case generation from execution.
- UI pages, replicas, recreations, screenshot alignment, and frontend interaction pages must produce `page-spec-card.md` after PRD and before HTML Prototype MOCK, static page development, or dynamic frontend implementation.
- Page prototype tasks must clarify the component library name, version, URL, or Git repository first; if already provided, record it in `memory.md`, the Page Specification Card, and HTML OKF metadata.
- The UI visual leak-prevention protocol forbids relying only on full-page pixel diff; visual locks or overlays require both locked and unlocked real-DOM evidence; key components require component-level visual contracts and executable assertions.
- Long-running tasks, auto-continuation, production-flow work, Benchmark work, browser E2E, or pixel-comparison work must record Budget Gate and Conflict Policy; insufficient evidence cannot be marked complete.
- V1.8 adds machine-readable protocol templates: `harness.yaml`, `evidence.jsonl`, `pipeline-state.json`, `failure_report`, and `approval_gate`.
- V1.9 adds a production-flow protocol: `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`, with credentials, real deployment, destructive operations, and production rollback stopped behind human or external authorization gates.
- Benchmark is not a default output for ordinary Goal Teams runs. Create or update `benchmarks/` only when the user asks, the plan confirms it, or a Skill Improvement task needs it.
- By default, Goal Teams shows a `Teams 规划表` and waits for confirmation. If the prompt includes `直接执行`, `不用确认`, or `跳过确认`, it records the plan and starts execution.
- Plan choices use numbers, such as `1. 确认并执行`, `2. 调整成员或范围`, `3. 只保留方案不执行`.
- Generated documents, code changes, and test cases require independent validation; implementers cannot be the only testers.
- After apparent completion, a fresh read-only `goal_completion_auditor` checks unfinished work. Remaining work inside the confirmed scope is auto-continued without asking the user again.
- The final report includes one status table, with `资源消耗（用户 / tokens / 费用）` in one column for each task or subagent. If runtime usage is unavailable, write `未提供`.

## Standard Flow

1. Understand the goal and turn it into verifiable Done Criteria.
2. Ask for historical documents, prior experience, or reference material, then record the answer in Plan assumptions.
3. Check `AGENTS.md`, `agent.md`, `CLAUDE.md`, and `claude.md`; if none exists, use `references/default-AGENTS.md`.
4. Confirm the project version, artifact version, and output directory; when unspecified, use `GoalTeamsWork-<project_version>/` as the output root.
5. Create or update root `index.md` and `memory.md`, then create version-directory `versions/<artifact_version>/TaskList.md` before multiple documents.
6. Write the `需求卡片`: core goal, key functions, user stories, functional acceptance criteria, boundaries, constraints, and risks.
7. Prepare SPEC: Requirement Specification Card, PRD, Backend/Frontend Architecture Design, HTML Prototype, Test Plan, and Acceptance.
8. For UI page tasks, prepare the Page Specification Card after PRD and before HTML Prototype or frontend implementation; when not applicable, record the reason.
9. Write a Harness contract for each task; when not applicable, record the reason.
10. Decide whether Benchmark applies; ordinary tasks do not create `benchmarks/` by default.
11. Find or create `GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md`, then record each handoff artifact with Owner, independent validator, status, and evidence path according to the handoff SSOT.
12. For backend work, plan Backend Architecture Design -> `goal_unit_test_designer` unit tests -> `goal_backend` implementation -> `goal_unit_test_runner` unit execution -> `goal_api_integration_test_runner` API integration execution; `goal_api_integration_test_designer` may generate Python + pytest scripts after architecture design.
13. After frontend implementation, assign `goal_e2e_test_designer` to generate E2E cases and `goal_e2e_test_runner` to execute them.
14. Show the four-column `Teams 规划表`: member/capability, task scope, delivery criteria, validation plan.
15. Start independent members after confirmation or direct-execution wording; each member stays inside locked scope, Harness, and workflow constraints.
16. Persist plans, progress, decisions, test evidence, and acceptance evidence in output-directory OKF Markdown.
17. Run `goal_completion_auditor`; auto-continue only unfinished work that remains inside the confirmed scope.

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
  CHANGELOG.md
  README.md
  README.en.md
  agents/openai.yaml
  references/goal-teams-runtime.md
  references/default-AGENTS.md
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

`examples/mini-goal-run` also includes `harness/` replay material that demonstrates the minimal static `setup -> run -> checks -> report` chain, plus static automation protocol, evidence ledger, and pipeline gate samples. `benchmarks/` provides `GT-BENCH-001`, `GT-BENCH-002`, and `GT-BENCH-003` templates for comparing baseline and Goal Teams output quality, evidence completeness, production gate judgment, UI E2E/pixel evidence handling, and cost.

V1.92 adds `references/goal-teams-scripted-tooling.md`, `references/ui-e2e-pixel-protocol.md`, and `references/subagent-dispatch-protocol.md`.

V1.93 adds `prompts/lead/`, `prompts/members/`, and `prompts/packets/`, and moves real scripts into `scripts/checks/`, `scripts/harness/`, `scripts/benchmark/`, and `scripts/install/`; root entries such as `scripts/check.sh` remain compatible.

V1.94 adds member-package subdirectories, `references/dual-review-protocol.md`, `prompts/packets/dual-review-record.md`, `scripts/checks/check-member-layout.py`, `scripts/review/compare-artifacts.py`, and `scripts/review/validate-dual-review.py`. Comparison and validation tasks must include both script-review evidence and LLM-review evidence.

V1.95 adds `prompts/lead/requirement-card.md` and `prompts/packets/requirement-card.md`, requiring Plan Mode to write `spec/requirement-card.md` first with core goal, key functions, boundaries, constraints, and risks.

V1.96 adds user-story and functional-acceptance requirements: the requirement card uses “作为...我想要...以便...” stories and verifiable functional acceptance criteria; PRD, tasklist, Harness, test plan, and acceptance must carry them forward.

V1.97 adds `references/google-okf-bilingual-spec.md`, `prompts/packets/page-spec-card.md`, `prompts/packets/memory.md`, and `prompts/packets/html-prototype-mock.md`, while strengthening `references/ui-visual-contract-protocol.md` and `references/ui-e2e-pixel-protocol.md`. Generated Markdown defaults to OKF; unspecified outputs go to `GoalTeamsWork-<project_version>/`; Page Specification Cards and HTML prototypes must record component library name, version, source, per-element library ownership, and data models where applicable.

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

This repository includes `VERSION`, `SKILL.md`, `agents/openai.yaml`, `references/goal-teams-runtime.md`, `references/default-AGENTS.md`, `references/goal-teams-automation-protocol.md`, `references/goal-teams-production-pipeline.md`, `references/goal-teams-scripted-tooling.md`, `references/google-okf-bilingual-spec.md`, `references/ui-e2e-pixel-protocol.md`, `references/ui-visual-contract-protocol.md`, `references/subagent-dispatch-protocol.md`, `references/dual-review-protocol.md`, `prompts/lead/core.md`, `prompts/lead/requirement-card.md`, `prompts/members/shared.md`, `prompts/members/backend/prompt.md`, `prompts/members/backend/template.md`, `prompts/members/backend/workflow.md`, `prompts/members/backend/scripts.md`, `prompts/members/unit-test-designer/prompt.md`, `prompts/members/unit-test-runner/prompt.md`, `prompts/members/api-integration-test-designer/prompt.md`, `prompts/members/api-integration-test-runner/prompt.md`, `prompts/members/e2e-test-designer/prompt.md`, `prompts/members/e2e-test-runner/prompt.md`, `prompts/packets/member-goal-packet.md`, `prompts/packets/handoff-artifacts.md`, `prompts/packets/page-spec-card.md`, `prompts/packets/memory.md`, `prompts/packets/html-prototype-mock.md`, `prompts/packets/requirement-card.md`, `prompts/packets/dual-review-record.md`, `subagents/goal-*.toml`, `goal-teams.md`, `AGENTS.md`, `scripts/check.sh`, `scripts/validate.py`, `scripts/install-local.sh`, `scripts/check-version-sync.py`, `scripts/check-agent-names.py`, `scripts/check-member-layout.py`, `scripts/validate-harness.py`, `scripts/pixel-diff.py`, `scripts/compare-artifacts.py`, `scripts/validate-dual-review.py`, `scripts/benchmark-runner.py`, `scripts/checks/`, `scripts/harness/`, `scripts/review/`, `scripts/benchmark/`, `scripts/install/`, `prompts/`, `examples/mini-goal-run`, `benchmarks/`, `CHANGELOG.md`, `README.md`, and `README.en.md`.

## License

If this repository is published as open source, add an explicit license such as MIT, Apache-2.0, or an internal sharing agreement.
