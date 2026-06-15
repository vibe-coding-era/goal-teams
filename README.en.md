# Goal Teams

[中文](README.md) | English

Author: 肉山@TGO Hangzhou

Current version: `V1.91`

`goal-teams` is a Codex Skill for running Goal Mode as a coordinated team. A Goal Lead turns one goal into a plan, assigns independent subagents or user-selected skills, controls serial/parallel workflow, records the process in Markdown, and closes the work with independent validation plus a completion audit.

## Core Model

Every run starts with:

```text
我是 Goal Teams Leader V1.91，我会帮你完成以下工作：
```

中文核心模型要点提示词:

```text
默认全程中文输出计划、表格、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。
```

How Goal Teams works:

- The Goal Lead clarifies the target, splits tasks, confirms workflow, assigns members, integrates results, and routes blockers.
- In Plan Mode, after the startup line and work items, ask: `在开始规划前，有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“没有”。`
- For default subagent members, the runtime subagent id, `member_id`, and display name use `<Chinese role>-<task>`, such as `后端-WIKI 列表后端开发`; the loadable subagent config name stays in `skill_or_subagent`, such as `goal_backend`.
- If the user assigns a skill, the runtime subagent id, `member_id`, display name, and `role` use the skill name prefix, such as `browser-WIKI 列表页面验证`.
- V1.91 prefers custom `goal_*` subagents by default. If the runtime or Codex right sidebar shows an English nickname such as `Reviewer C` or `QA B`, treat it only as a transport handle; user-visible tables, packets, state, and final reports still use Chinese member names.
- Every task states whether its workflow is serial or parallel; serial tasks list predecessors so shared scopes are not edited concurrently.
- `SPEC` defines completion criteria, `Harness` defines the verification contract, `Evidence` records traceable proof, `Pipeline` records R&D/release state, `Benchmark` defines the outer evaluation task set, and `Loop` defines member, Lead, and Skill Improvement cycles.
- Harness is not a new runtime executor. It appears as checks, commands, manual checklists, evidence paths, and failure-report formats in the Plan, tasklist, Member Goal Packet, test plan, and acceptance docs.
- Every UI-level task must run an E2E test. Replica/recreation tasks must take screenshots and perform pixel-level comparison, recording the baseline, actual screenshot, diff image or metric, threshold, viewport, and conclusion.
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
4. Confirm the version and write process/results under `.codex/goal-teams/versions/<version>/`.
5. Create or update `.codex/goal-teams/INDEX.md` and the version `INDEX.md` before multiple documents.
6. Prepare SPEC: Requirement Specification Card, PRD, Architecture Design, HTML Prototype, Test Plan, and Acceptance.
7. Write a Harness contract for each task; when not applicable, record the reason.
8. Decide whether Benchmark applies; ordinary tasks do not create `benchmarks/` by default.
9. Find or create `.codex/goal-teams/versions/<version>/tasklist.md`.
10. Show the four-column `Teams 规划表`: member/capability, task scope, delivery criteria, validation plan.
11. Start independent members after confirmation or direct-execution wording; each member stays inside locked scope, Harness, and workflow constraints.
12. Persist plans, progress, decisions, test evidence, and acceptance evidence in versioned Markdown.
13. Run `goal_completion_auditor`; auto-continue only unfinished work that remains inside the confirmed scope.

## Teams 规划表

The table has four display columns, but every row keeps the underlying fields: member, skill/subagent, goal slice, claimed task, workflow, predecessor, locked scope, deliverable, done criteria, Harness, docs/tasklist update, test owner, and validator.

| 成员 / Skill(Subagent) | Scope | Delivery / Criteria | Validation |
| --- | --- | --- | --- |
| Member: `需求分析-WIKI 列表需求澄清`<br>Skill/Subagent: `goal_requirements_analyst` | Goal slice: clarify WIKI list requirements<br>Claimed task: GT-001<br>Workflow: serial<br>Predecessor: -<br>Locked scope: `spec/` | Deliverable: Requirement Specification Card<br>Done criteria: user confirms goals, flow, and boundaries<br>Harness: structure and boundary checklist review<br>Docs/tasklist: requirement-spec-card + INDEX | Test owner: `评审-WIKI 列表需求校验`<br>Validator: `评审-WIKI 列表需求校验` |
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
  scripts/check.sh
  scripts/validate.py
  subagents/goal-*.toml
  examples/mini-goal-run/
  benchmarks/
```

Runtime files in target projects:

```text
.codex/goal-teams/
  INDEX.md
  versions/<version>/
    INDEX.md
    plan.md
    progress.md
    decisions.md
    tasklist.md
    goal-packet.md
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
  team-state.json
  events.jsonl
  messages.jsonl
  doc-capsules.jsonl
  member-packets/
```

## Default Members

| Subagent ID / Role Name | Main Responsibility |
| --- | --- |
| `goal_requirements_analyst` | Clarification, research-assisted analysis, Requirement Specification Card, PRD handoff |
| `goal_product` | PRD, acceptance criteria, prototype structure, product review |
| `goal_backend` | Domain model, storage, API, CLI, MCP, migrations, integrations |
| `goal_frontend` | UI, HTML prototype, browser verification, E2E, replica pixel comparison, screenshot evidence |
| `goal_qa` | Independent tests, integration tests, UI E2E, pixel-comparison acceptance, test reports |
| `goal_docs` | tasklist, acceptance, README, reports, release notes |
| `goal_reviewer` | Read-only review, architecture boundaries, security, coverage, compatibility, risk |
| `goal_completion_auditor` | Completion audit, unfinished-work check, auto-continuation suggestions |

## Installation

Clone into the Codex skills directory:

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

Copy subagents:

```bash
mkdir -p ~/.codex/agents
cp ~/.codex/skills/goal-teams/subagents/goal-*.toml ~/.codex/agents/
```

Validate before maintenance releases:

```bash
./scripts/check.sh
```

`examples/mini-goal-run` provides a minimal output tree for checking indexes, SPEC, tasklist, the Teams plan table, independent validation, and completion audit. `goal-teams.md` records long-term user requirements and is the upstream reference for maintaining this Skill.

`examples/mini-goal-run` also includes `harness/` replay material that demonstrates the minimal static `setup -> run -> checks -> report` chain, plus static automation protocol, evidence ledger, and pipeline gate samples. `benchmarks/` provides `GT-BENCH-001` and `GT-BENCH-002` templates for comparing baseline and Goal Teams output quality, evidence completeness, production gate judgment, and cost.

## Examples

Plan and wait for confirmation:

```text
Use $goal-teams。
请为“分时租赁 V3.0”做 Goal Teams 计划。
过程和结果保存到 V3.0 版本目录。
先生成需求规格卡，再生成 PRD。
```

Direct execution:

```text
Use $goal-teams。
请直接执行：为 WIKI 列表 V1.91 规划并实现后端 API、页面验证、独立测试和验收文档。
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

This repository includes `VERSION`, `SKILL.md`, `agents/openai.yaml`, `references/goal-teams-runtime.md`, `references/default-AGENTS.md`, `references/goal-teams-automation-protocol.md`, `references/goal-teams-production-pipeline.md`, `subagents/goal-*.toml`, `goal-teams.md`, `AGENTS.md`, `scripts/check.sh`, `scripts/validate.py`, `examples/mini-goal-run`, `benchmarks/`, `CHANGELOG.md`, `README.md`, and `README.en.md`.

## License

If this repository is published as open source, add an explicit license such as MIT, Apache-2.0, or an internal sharing agreement.
