# Goal Teams Runtime

This reference defines a project-agnostic Goal Teams runtime. It does not assume a business domain or an existing tasklist.

## Runtime Shape

Goal Teams = Goal Lead + independent subagent members.

```text
Goal Lead
  - communicates in Chinese by default
  - turns the user goal into Done Criteria
  - enforces Plan mode before execution
  - asks clarifying questions during planning and solution design
  - discovers or creates SPEC docs
  - discovers or creates a tasklist
  - persists process and results mainly in Markdown
  - proposes member/task ownership in tables
  - waits for confirmation when required
  - creates Member Goal Packets
  - spawns independent subagents
  - routes messages and blockers
  - integrates outputs
  - verifies completion

Subagent Member
  - receives one Member Goal Packet
  - responds in Chinese by default
  - uses the user-specified skill/subagent when assigned
  - claims specific tasks
  - loads only needed docs
  - emits Doc Capsules
  - executes its own goal loop
  - reports complete / blocked / incomplete
```

Every member is an independent subagent. Roles are responsibility boundaries; task claims and goal packets are execution granularity.

## Mandatory Plan Mode

Goal Teams always starts in Plan mode:

1. Ask clarifying questions when goals, scope, acceptance criteria, priorities, constraints, user roles, design style, data contracts, risk tolerance, or deployment targets are unclear.
2. Record questions, answers, assumptions, and decisions in Markdown, usually `.codex/goal-teams/plan.md`.
3. Discover or create SPEC and tasklist.
4. Propose member assignments, skill/subagent assignments, task claims, locked scopes, docs updates, testing owner, and done criteria.
5. Present confirmation tables.
6. Wait for user confirmation before spawning worker subagents or editing implementation files.
7. If the user explicitly says to proceed without confirmation, still show the tables as the execution plan before continuing.

Plan mode must be repeated when the user changes scope, member assignments, skill/subagent choices, locked scopes, risks, or stop conditions.

Clarification rules:

- Prefer 1-5 high-signal questions at a time.
- Group questions by topic, such as business目标, 范围边界, 验收标准, 设计风格, 数据/接口, 发布约束, 风险审批.
- If a question can be answered by reading local files, inspect first and ask only when ambiguity remains.
- If execution must continue with assumptions, record them explicitly in the plan and confirmation tables.

## Language And Persistence

Default language is Chinese for user-facing content and team artifacts:

- Plans, proposals, tables, progress updates, SPEC docs, tasklists, member packets, review reports, and final summaries should be in Chinese.
- Keep code identifiers, commands, logs, file paths, API names, dependency names, and exact source quotes in their original language when needed.
- If the user explicitly asks for another language, follow that request for the requested artifact.

Prefer Markdown as the persistent human-readable record:

```text
.codex/goal-teams/
  plan.md               # 澄清问题、用户回答、假设、确认后的计划
  progress.md           # 每轮执行进展表、阻塞、下一步
  decisions.md          # 决策、原因、审批记录
  tasklist.md           # 成员认领、任务状态、验收、验证
  goal-packet.md        # 团队级目标包
  spec/
    PRD.md
    architecture-design.md
    test-plan.md
    acceptance.md
```

Use JSON/JSONL for machine-readable runtime state only when useful; mirror important results back into Markdown.

## SPEC Contract

Goal Teams is SPEC-driven. Missing SPEC should be created or scheduled in the tasklist before implementation.

Required vocabulary:

- Requirements = `PRD`.
- Design = `Architecture Design`.
- UI/page/workflow design = `HTML Prototype`.
- Development execution = `tasklist.md`.
- Testing = independent subagent or user-specified testing skill/subagent.

Recommended files:

```text
.codex/goal-teams/spec/
  PRD.md
  architecture-design.md
  HTML-prototype.html
  test-plan.md
  acceptance.md
.codex/goal-teams/tasklist.md
```

If the user provides `design.md`, treat it as the style source for architecture/prototype work:

- Read `design.md` before creating or updating Architecture Design or HTML Prototype.
- Mirror its headings, terminology, density, and artifact style where practical.
- If it conflicts with the user goal, ask for confirmation or record a blocker.

SPEC readiness table:

| SPEC | Exists | Action | Owner | Output |
| --- | --- | --- | --- | --- |
| PRD | yes/no | create/update/skip | goal_product | `.codex/goal-teams/spec/PRD.md` |
| Architecture Design | yes/no | create/update/skip | goal_backend or goal_product | `.codex/goal-teams/spec/architecture-design.md` |
| HTML Prototype | yes/no/not applicable | create/update/skip | goal_frontend | `.codex/goal-teams/spec/HTML-prototype.html` |
| Test Plan | yes/no | create/update/skip | goal_qa | `.codex/goal-teams/spec/test-plan.md` |
| Acceptance | yes/no | create/update/skip | goal_docs | `.codex/goal-teams/spec/acceptance.md` |

## Tasklist Discovery And Creation

Discovery order:

1. User-mentioned tasklist path.
2. Project-local candidates: `TASKLIST.md`, `tasklist.md`, `TODO.md`, `docs/*task*`, `docs/*plan*`.
3. Goal Teams runtime path: `.codex/goal-teams/tasklist.md`.
4. If no relevant tasklist exists, create `.codex/goal-teams/tasklist.md`.

Generated tasklists must include ownership and confirmation-ready structure from the start:

```md
# Goal Teams Tasklist

Goal: <user goal>
Status: planning

## Member Ownership

| Task ID | Member | Skill/Subagent | Claimed By | Status | Locked Scope | Deliverable | Done Criteria | Verification | Docs/SPEC Update |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 产品/需求 | goal_product or user-selected | unclaimed | pending | docs/ | PRD | PRD approved | Review checklist | PRD + tasklist |

## Tasks

| Task ID | Title | Owner | Status | Depends On | Stop Condition |
| --- | --- | --- | --- | --- | --- |
| GT-001 | Clarify requirements and acceptance | 产品/需求 | pending | - | Missing stakeholder decision |

## Decisions And Blockers

| ID | Type | Owner | Status | Summary | Decision Needed |
| --- | --- | --- | --- | --- | --- |
```

Checkbox-only tasklists are allowed for human readability, but tables are preferred because they preserve ownership and completion status.

## Markdown Persistence Templates

Use or append to `.codex/goal-teams/plan.md`:

```md
# Goal Teams Plan

## 用户目标

<中文描述>

## 澄清问题

| 问题 | 用户回答 | 影响 | 状态 |
| --- | --- | --- | --- |

## 当前假设

| 假设 | 影响 | 验证方式 | 是否需确认 |
| --- | --- | --- | --- |

## 确认后的计划

| 阶段 | 输出 | Owner | 验收标准 | 风险 |
| --- | --- | --- | --- | --- |
```

Use or append to `.codex/goal-teams/progress.md`:

```md
# Goal Teams Progress

## <YYYY-MM-DD HH:mm> 执行轮次

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |

## 阻塞与决策

| 阻塞/决策 | 成员 | 影响 | 需要用户确认 | 建议 |
| --- | --- | --- | --- | --- |
```

Use or append to `.codex/goal-teams/decisions.md`:

```md
# Goal Teams Decisions

| 时间 | 决策 | 原因 | 决策人 | 影响范围 |
| --- | --- | --- | --- | --- |
```

## Confirmation Tables

Before spawning worker subagents or editing implementation files, present:

### SPEC Readiness

| SPEC | Exists | Action | Owner | Output |
| --- | --- | --- | --- | --- |
| PRD | no | create | 产品/需求 | `.codex/goal-teams/spec/PRD.md` |

### Member Plan

| Member | Skill/Subagent | Goal Slice | Claimed Tasks | Locked Scope | Deliverable | Done Criteria | Docs/Tasklist Updates |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 产品/需求 | goal_product or user-selected skill | Clarify scope | GT-001 | docs/ | PRD | Approved criteria | PRD + tasklist.md |

### Tasklist Execution

| Task ID | Owner | Status | Depends On | Verification | Completion Evidence |
| --- | --- | --- | --- | --- | --- |
| GT-001 | 产品/需求 | pending | - | PRD review | PRD section complete |

### Risk And Approval

| Item | Risk | Owner | Approval Needed | Stop Condition |
| --- | --- | --- | --- | --- |
| Shared module | Multiple agents may edit same files | Goal Lead | Yes | unclear locked_scope |

Ask for confirmation in plain language after the tables. If the user explicitly says to proceed without confirmation, still include the tables as the plan and continue.

Also persist the confirmation tables and any assumptions to `.codex/goal-teams/plan.md` unless the user requested a proposal only and no files should be written.

## Progress Feedback Tables

During execution, summarize each meaningful round with tables:

| Member | Claimed Tasks | Status | Current Step | Evidence | Next |
| --- | --- | --- | --- | --- | --- |
| backend-gt-002 | GT-002 | running | Test | `cargo test ...` | update docs |

For blockers:

| Blocker | Member | Task | Impact | Decision Needed | Suggested Next |
| --- | --- | --- | --- | --- | --- |

For final closeout:

| Member | Claimed Tasks | Final Status | Evidence | Remaining |
| --- | --- | --- | --- | --- |

Append progress tables, blockers, and final closeout evidence to `.codex/goal-teams/progress.md` or the relevant Markdown artifact.

## Cache-Friendly Prompt Layout

Keep this layout stable:

```text
[Stable Core Prompt]
[Document Loading Manifest]
[Goal Mode Loop]
[Dynamic Goal Packet]
```

Rules:

- Stable Core Prompt changes rarely.
- Document Loading Manifest lists paths and loading rules, not long document bodies.
- Dynamic Goal Packet goes last.
- Each subagent gets only the packet and document slices it needs.
- Read docs progressively and summarize into Doc Capsules.

## Document Loading Manifest

Use a generic manifest:

```text
Always load first:
1. User-provided goal and constraints.
2. `.codex/goal-teams/plan.md` if present.
3. Relevant tasklist if present; otherwise generated .codex/goal-teams/tasklist.md.
4. The current member's claimed task rows.
```

Load on demand:

| Need | Load |
| --- | --- |
| Product/user scope | PRD, issue, brief, or stakeholder notes if present |
| Architecture/ownership | Architecture Design, design.md, module docs, code maps, dependency files |
| UI/page/workflow design | HTML Prototype, design.md, screenshots, mockups, route maps |
| API/contract semantics | API docs, schemas, route definitions, SDK docs |
| Tests/acceptance | Test plan, existing tests, CI config, acceptance docs |
| Release/deployment | README, deployment docs, changelog, runbooks |

If a needed document does not exist, create a small scoped doc only when it is part of the confirmed plan.

## Team Goal Packet

Team-level packet:

```text
Goal Packet:
- goal:
- done_criteria:
- language: Chinese by default
- constraints:
- discovered_docs:
- markdown_persistence:
  - plan.md
  - progress.md
  - decisions.md
  - tasklist.md
- tasklist_path:
- allowed_scope:
- forbidden_scope:
- required_tests:
- required_docs_after_done:
  - Markdown progress/result updates
- required_spec:
  - PRD
  - Architecture Design
  - HTML Prototype when applicable
  - test plan
  - acceptance
- stop_conditions:
- confirmation_required:
- team_members:
  - member_id:
    role:
    skill_or_subagent:
    claimed_tasks:
    locked_scope:
    deliverable:
```

Use the team packet to create one Member Goal Packet per subagent.

## Member Goal Packet

```text
Member Goal Packet:
- member_id: backend-gt-002
- role: backend
- skill_or_subagent: goal_backend
- language: Chinese by default
- user_requested_skill:
- user_requested_subagent:
- lane_or_deliverable: API implementation
- target_task_ids:
  - GT-002
- claimed_tasks:
  - Implement the agreed API slice
- goal:
  Complete the assigned backend slice to a verifiable done state.
- success_criteria:
  - API behavior matches accepted contract.
  - Targeted tests pass.
- required_doc_load:
  - .codex/goal-teams/tasklist.md#GT-002
  - relevant API docs if present
- allowed_scope:
  - src/api
  - tests/api
- forbidden_scope:
  - shared auth/payment/core modules unless approved
- locked_scope:
  - src/api/specific-module
- required_tests:
  - targeted tests for touched module
- required_docs_after_done:
  - tasklist status
  - progress.md row
  - API notes if changed
- required_spec:
  - PRD: read or confirm not applicable
  - Architecture Design: update if API structure changes
  - HTML Prototype: not applicable unless UI changes
  - Test Plan: update if coverage changes
  - Acceptance: update if done criteria change
- stop_conditions:
  - unclear API contract
  - required credentials unavailable
- output_contract:
  - Doc Capsules
  - plan
  - files changed
  - tests run
  - docs updated
  - Markdown progress/result updates
  - tasklist updates
  - SPEC updates
  - suggested team-state updates
  - completion status
  - blockers and risks
```

## Doc Capsule JSONL

Use this durable shape:

```json
{"ts":"2026-05-26T10:00:00+08:00","member_id":"backend-gt-002","source":".codex/goal-teams/tasklist.md#GT-002","decision":"Implement only the confirmed API slice.","must_do":["match accepted contract","run targeted tests"],"must_not_do":["edit shared auth without approval"],"test_refs":["targeted module tests"],"doc_update_refs":["tasklist.md"],"open_questions":[]}
```

## Team State JSON

```json
{
  "team": {
    "mode": "goal-teams",
    "goal": "Complete the confirmed user goal",
    "status": "planning",
    "tasklist_path": ".codex/goal-teams/tasklist.md",
    "updated_at": "2026-05-26T10:00:00+08:00"
  },
  "members": [
    {
      "id": "product-gt-001",
      "role": "product",
      "skill_or_subagent": "goal_product",
      "user_requested_skill": null,
      "user_requested_subagent": null,
      "status": "pending",
      "claimed_tasks": ["GT-001"],
      "current": "Clarify requirements and acceptance",
      "locked_scope": ["docs/requirements"]
    }
  ],
  "tasks": [
    {
      "id": "GT-001",
      "title": "Clarify requirements and acceptance",
      "owner": "product-gt-001",
      "claimed_by": null,
      "status": "pending",
      "deliverable": "Requirements brief",
      "done_criteria": ["Scope confirmed", "Acceptance criteria written"],
      "locked_scope": ["docs/requirements"],
      "docs_update": [".codex/goal-teams/tasklist.md"],
      "spec_update": [".codex/goal-teams/spec/PRD.md"]
    }
  ]
}
```

## Events JSONL

```json
{"ts":"2026-05-26T10:01:00+08:00","type":"goal_team_planned","goal":"Complete the confirmed user goal"}
{"ts":"2026-05-26T10:02:00+08:00","type":"tasklist_created","path":".codex/goal-teams/tasklist.md"}
{"ts":"2026-05-26T10:03:00+08:00","type":"user_confirmed_plan","confirmation":"approved"}
{"ts":"2026-05-26T10:04:00+08:00","type":"member_spawned","member_id":"backend-gt-002","skill_or_subagent":"goal_backend"}
{"ts":"2026-05-26T10:20:00+08:00","type":"task_completed","task_id":"GT-002","member_id":"backend-gt-002"}
```

## Messages JSONL

```json
{"ts":"2026-05-26T10:12:00+08:00","from":"qa-gt-003","to":"goal-lead","task_id":"GT-003","severity":"medium","message":"Need expected behavior for empty-state validation.","decision_needed":true,"status":"open"}
```

## Goal Loop Details

### Load

1. Read user goal and constraints.
2. Read or create SPEC docs.
3. Read or create tasklist.
4. Read current member's claimed task rows.
5. Read project docs only as needed.
6. Produce Doc Capsules.

### Plan

Return up to five steps:

```text
Plan:
1. PRD task -> verify: accepted criteria
2. Architecture Design task -> verify: design review
3. HTML Prototype task -> verify: screenshot/E2E when applicable
4. Implementation tasklist task -> verify: targeted test
5. Independent QA task -> verify: command/report
6. Docs/tasklist task -> verify: status and ownership updated
```

### Implement

Use tasklist order and dependencies. For engineering-heavy work, a common order is:

1. PRD
2. Architecture Design
3. HTML Prototype if applicable
4. Tasklist implementation tasks
5. Independent QA/testing tasks
6. Docs, acceptance, and tasklist status updates

Skip layers only with an explicit reason.

### Test

Testing must be performed by an independent subagent or a user-specified testing skill/subagent. Use the smallest meaningful verification first, then broaden if shared behavior changed.

Failure report:

```text
Test failed:
- command:
- failing test:
- likely cause:
- fix plan:
- next verification:
```

### Document

Every member should report whether it updated:

- tasklist status
- owner/claimed_by fields
- docs assigned in its packet
- SPEC files assigned in its packet
- reports or acceptance notes
- remaining gaps

### Review

```text
Review Checklist:
- claimed task complete:
- done criteria:
- tests:
- docs/tasklist:
- SPEC:
- locked scope respected:
- blockers:
- remaining risks:
```

Continue the loop until complete or blocked.

## CLI Bridge

The dashboard should not execute shell commands directly. Use a local bridge if needed.

Lead execution pattern:

```bash
PROJECT="/path/to/project"

codex exec \
  -C "$PROJECT" \
  --sandbox workspace-write \
  --ask-for-approval never \
  --json \
  --output-last-message ".codex/goal-teams/last-message.md" \
  - <<'PROMPT' | tee -a ".codex/goal-teams/events.jsonl"
Use $goal-teams.

Turn the user goal into Done Criteria.
Discover an existing tasklist, or create .codex/goal-teams/tasklist.md if none exists.
Discover or create SPEC docs: PRD, Architecture Design, HTML Prototype when applicable, test plan, and acceptance.
Propose independent subagent members with claimed tasks, user-requested skill/subagent assignments, locked scopes, docs/SPEC updates, independent testing ownership, and done criteria.
Show SPEC readiness, member plan, tasklist execution, and risk tables before spawning implementation members unless already approved.
After confirmation, spawn each team member as a separate subagent.
Coordinate through team-state.json, events.jsonl, messages.jsonl, and doc-capsules.jsonl.
Run until every claimed task is done, deferred, or blocked with a documented reason.
PROMPT
```

Planning-only pattern:

```bash
codex exec \
  -C "$PROJECT" \
  --sandbox read-only \
  --json \
  'Use $goal-teams. Create a confirmation table for a goal team: members, claimed tasks, locked scopes, docs/tasklist updates, done criteria, and risks. Do not edit files.'
```

## Safety And Coordination

- Do not start implementation without locked scope.
- Do not let members modify shared core files concurrently.
- Do not skip Plan mode.
- Do not skip SPEC. Create missing PRD, Architecture Design, HTML Prototype when applicable, test plan, acceptance, and tasklist work items.
- Do not let implementation members be the only testers. Assign independent QA/testing skill/subagent.
- Honor user-specified skill/subagent assignments for members.
- Require lead approval for auth, payment, refund, migrations, destructive writes, security-sensitive integrations, or broad API changes.
- Keep `max_depth = 1`; members do not spawn nested teams.
- Keep team size around 3-6 concurrent members unless the user explicitly wants more.

## Completion Response

Use a concise final shape:

```text
完成：<一句话说明>

成员状态：
| Member | Claimed Tasks | Status | Evidence | Remaining |
| --- | --- | --- | --- | --- |

SPEC：
| SPEC | Status | Owner | Evidence |
| --- | --- | --- | --- |

验证：
- <命令>：通过
- <命令>：未运行，原因...

文档与 tasklist：
- <文件>：已更新

剩余风险：
- <如无，写“无已知阻塞。”>
```
