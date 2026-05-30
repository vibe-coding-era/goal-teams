# Goal Teams Runtime

This reference defines a project-agnostic Goal Teams runtime. It does not assume a business domain or an existing tasklist.

Current Skill version: `V1.1`. Keep it aligned with the repository `VERSION` file and `SKILL.md` frontmatter.

## Runtime Shape

Goal Teams = Goal Lead + independent subagent members.

```text
Goal Lead
  - identifies itself at the start of every run as: 我是 Goal Teams Leader V1.1，我会帮你完成以下工作：
  - communicates in Chinese by default
  - communicates with the user in a friendly, concise, non-jargony style
  - ensures generated docs, code comments, test names, and test cases are Chinese by default
  - turns the user goal into Done Criteria
  - enforces Plan mode before execution
  - asks clarifying questions during planning and solution design
  - checks project guidance files such as AGENTS.md / agent.md / CLAUDE.md / claude.md
  - uses references/default-AGENTS.md when no guidance file exists
  - identifies the version directory before writing docs
  - creates document indexes before creating multiple documents
  - discovers or creates SPEC docs
  - discovers or creates a tasklist
  - persists process and results mainly in Markdown
  - assigns independent validators for every generated document, code change, and test case
  - proposes member/task ownership in tables
  - shows a Teams 规划表 and waits for user confirmation before worker execution
  - creates Member Goal Packets
  - spawns independent subagents
  - routes messages and blockers
  - integrates outputs
  - verifies completion

Subagent Member
  - receives one Member Goal Packet
  - uses a Chinese role+task display name, usually <角色>-<具体任务名>
  - responds in Chinese by default
  - uses the user-specified skill/subagent when assigned
  - claims specific tasks
  - loads only needed docs
  - emits Doc Capsules
  - executes its own goal loop
  - reports complete / blocked / incomplete
  - does not self-approve its generated artifacts
```

Every member is an independent subagent. Roles are responsibility boundaries; task claims and goal packets are execution granularity.

Exception: when the user explicitly asks to use `openspec` or `superpower`, Goal Teams should act only as the Goal Lead by default. In that mode, coordinate the process, ask clarifying questions, check environment, prepare indexes and lead-level artifacts, and avoid spawning role subagents unless the user later confirms full Goal Teams execution.

## Mandatory Plan Mode

Goal Teams always starts in Plan mode:

1. Start by saying: `我是 Goal Teams Leader V1.1，我会帮你完成以下工作：`, followed by a concise Chinese list of concrete responsibilities for this run.
2. Check environment guidance files: `AGENTS.md`, `agents.md`, `agent.md`, `CLAUDE.md`, `claude.md`.
3. If none exists, load `references/default-AGENTS.md` as active default guidance and suggest copying it to project-root `AGENTS.md` for team rules, coding style, constraints, and project context.
4. Ask for or infer the target version number. Do not write process docs until a version directory is chosen.
5. Ask clarifying questions when goals, scope, acceptance criteria, priorities, constraints, user roles, design style, data contracts, risk tolerance, or deployment targets are unclear.
6. Record questions, answers, assumptions, and decisions in Markdown, usually `.codex/goal-teams/versions/<version>/plan.md`.
7. Create or update indexes before producing multiple documents.
8. Discover or create SPEC and tasklist.
9. Propose member assignments, skill/subagent assignments, task claims, locked scopes, docs updates, testing owner, and done criteria.
10. Propose independent validators for every generated artifact: documents, code, and test cases.
11. Present a `Teams 规划表` and the related confirmation tables.
12. Wait for user confirmation before spawning worker subagents or editing implementation files.
13. If the user explicitly says to proceed without confirmation or execute an already confirmed plan, still show the `Teams 规划表` as the execution plan before continuing.

Plan mode must be repeated when the user changes scope, member assignments, skill/subagent choices, locked scopes, risks, or stop conditions.

Clarification rules:

- Prefer 1-5 high-signal questions at a time.
- Group questions by topic, such as business目标, 范围边界, 验收标准, 设计风格, 数据/接口, 发布约束, 风险审批.
- If a question can be answered by reading local files, inspect first and ask only when ambiguity remains.
- If execution must continue with assumptions, record them explicitly in the plan and confirmation tables.
- Keep Goal Lead messages brief and human. Explain why a question matters, but avoid dense process terminology.

## Language And Persistence

Default language is Chinese for user-facing content and team artifacts:

- Plans, proposals, tables, progress updates, SPEC docs, tasklists, member packets, review reports, and final summaries should be in Chinese.
- Generated documentation, code comments, human-facing code strings, test names, test descriptions, test fixtures, and test case summaries should be Chinese by default.
- Keep code identifiers, commands, logs, file paths, API names, dependency names, and exact source quotes in their original language when needed.
- If the user explicitly asks for another language, follow that request for the requested artifact.

Chinese member naming:

- Use Chinese display names for subagent members in all user-facing tables, packets, and state.
- Names must combine role + concrete task name in the pattern `<角色>-<任务名>`.
- Prefer concrete task names such as `后端-WIKI 列表后端开发`, `前端-WIKI 列表页面开发`, `测试-WIKI 列表验收测试`, `需求分析-WIKI 列表需求澄清`, `文档-WIKI 列表验收文档`, or `评审-WIKI 列表代码审查`.
- Avoid role-only or vague names such as `后端`, `测试`, or `后端-接口联调` when the actual task can be named.
- Keep the technical subagent identifier, such as `goal_backend`, only in `skill_or_subagent` or machine-readable fields.

Prefer Markdown as the persistent human-readable record:

```text
.codex/goal-teams/
  INDEX.md              # 跨版本总索引
  versions/<version>/
    INDEX.md            # 当前版本文档索引，多文档前先建
    plan.md             # 澄清问题、用户回答、假设、确认后的计划
    progress.md         # 每轮执行进展表、阻塞、下一步
    decisions.md        # 决策、原因、审批记录
    tasklist.md         # 成员认领、任务状态、验收、验证
    goal-packet.md      # 团队级目标包
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
```

Use JSON/JSONL for machine-readable runtime state only when useful; mirror important results back into Markdown.

Default guidance template:

- When no `AGENTS.md`, `agents.md`, `agent.md`, `CLAUDE.md`, or `claude.md` exists, use `references/default-AGENTS.md` as active project guidance.
- Tell the user plainly: “我没有看到项目指南文件，会先按默认 AGENTS 模板执行；也建议把它保存为项目根目录的 `AGENTS.md`。”
- If the user agrees, create project-root `AGENTS.md` from `references/default-AGENTS.md`.
- The generated `AGENTS.md` content must remain Chinese.

Version directory rules:

- All process and result documents produced by Goal Teams must be stored under a version-numbered directory, usually `.codex/goal-teams/versions/<version>/`.
- If the user gives a release name instead of a semantic version, use it as the directory name after making it filesystem-safe, such as `V3.0`, `vNext`, or `2026-Q2`.
- Keep only cross-version indexes and machine runtime files outside version directories.
- If multiple documents will be created, create or update `.codex/goal-teams/INDEX.md` and `.codex/goal-teams/versions/<version>/INDEX.md` first.

Index table template:

```md
# Goal Teams Index

| 文档 | 版本 | Owner | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `versions/V3.0/spec/requirement-spec-card.md` | V3.0 | 需求分析师 | planning | 人类友好的需求规格卡 |
```

## SPEC Contract

Goal Teams is SPEC-driven. Missing SPEC should be created or scheduled in the tasklist before implementation.

Required vocabulary:

- Human-friendly requirement summary = `Requirement Specification Card`.
- Requirements = `PRD`.
- Design = `Architecture Design`.
- UI/page/workflow design = `HTML Prototype`.
- Development execution = `tasklist.md`.
- Testing = independent subagent or user-specified testing skill/subagent.

Legacy non-versioned files may be read when found:

```text
.codex/goal-teams/spec/
  PRD.md
  architecture-design.md
  HTML-prototype.html
  test-plan.md
  acceptance.md
.codex/goal-teams/tasklist.md
```

Use the versioned layout in active projects:

```text
.codex/goal-teams/versions/<version>/spec/
  requirement-spec-card.md
  PRD.md
  architecture-design.md
  HTML-prototype.html
  test-plan.md
  acceptance.md
.codex/goal-teams/versions/<version>/tasklist.md
```

Requirement analysis flow:

1. The `goal_requirements_analyst` member talks with the user in plain Chinese and asks focused questions.
2. It may use network search, computer use, browser, or Chrome capabilities when available and useful for market, competitor, policy, workflow, or domain context.
3. It first creates `requirement-spec-card.md`, limited to roughly two pages.
4. The card must clearly cover core goal, why it matters, key business function structure, main flow, boundaries, non-goals, and open questions.
5. The PRD is generated from the approved card, not directly from scattered conversation notes.

If the user provides `design.md`, treat it as the style source for architecture/prototype work:

- Read `design.md` before creating or updating Architecture Design or HTML Prototype.
- Mirror its headings, terminology, density, and artifact style where practical.
- If it conflicts with the user goal, ask for confirmation or record a blocker.

SPEC readiness table:

| SPEC | Exists | Action | Owner | Output |
| --- | --- | --- | --- | --- |
| Requirement Specification Card | yes/no | create/update/skip | goal_requirements_analyst | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` |
| PRD | yes/no | create/update/skip | goal_product | `.codex/goal-teams/versions/<version>/spec/PRD.md` |
| Architecture Design | yes/no | create/update/skip | goal_backend or goal_product | `.codex/goal-teams/versions/<version>/spec/architecture-design.md` |
| HTML Prototype | yes/no/not applicable | create/update/skip | goal_frontend | `.codex/goal-teams/versions/<version>/spec/HTML-prototype.html` |
| Test Plan | yes/no | create/update/skip | goal_qa | `.codex/goal-teams/versions/<version>/spec/test-plan.md` |
| Acceptance | yes/no | create/update/skip | goal_docs | `.codex/goal-teams/versions/<version>/spec/acceptance.md` |

Independent validation table:

| Artifact | Author Member | Validator Member/Skill | Method | Evidence |
| --- | --- | --- | --- | --- |
| `spec/PRD.md` | 产品-WIKI 列表 PRD | 评审-WIKI 列表 PRD 校验 | checklist review | `progress.md` row |
| `src/api/order.ts` | 后端-订单接口 | 测试-接口行为 | targeted tests + code review | command output |
| `tests/order.test.ts` | 测试-订单规则 | 评审-测试有效性 | assertion review | review note |

## Tasklist Discovery And Creation

Discovery order:

1. User-mentioned tasklist path.
2. Project-local candidates: `TASKLIST.md`, `tasklist.md`, `TODO.md`, `docs/*task*`, `docs/*plan*`.
3. Goal Teams version path: `.codex/goal-teams/versions/<version>/tasklist.md`.
4. Legacy Goal Teams runtime path: `.codex/goal-teams/tasklist.md`.
5. If no relevant tasklist exists, create `.codex/goal-teams/versions/<version>/tasklist.md`.

Generated tasklists must include ownership and confirmation-ready structure from the start:

```md
# Goal Teams Tasklist

Goal: <user goal>
Status: planning

## Member Ownership

| Task ID | Member | Skill/Subagent | Claimed By | Status | Locked Scope | Deliverable | Done Criteria | Verification | Docs/SPEC Update |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 需求分析-WIKI 列表需求澄清 | goal_requirements_analyst or user-selected | unclaimed | pending | .codex/goal-teams/versions/<version>/spec/ | 需求规格卡 | 用户确认 | 评审-WIKI 列表需求校验 | 需求规格卡 + tasklist |

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

Use or append to `.codex/goal-teams/versions/<version>/plan.md`:

```md
# Goal Teams Plan

## 用户目标

<中文描述>

## 环境检查

| 项目 | 结果 | 建议 |
| --- | --- | --- |
| AGENTS/agent 指南 | found/missing | 如缺失，建议补充团队规则和项目约束 |
| CLAUDE 指南 | found/missing | 如缺失，建议补充跨工具协作约定 |
| 默认指南 | active/not needed | 缺失项目指南时使用 `references/default-AGENTS.md` |
| 版本目录 | <version> | 文档写入 `.codex/goal-teams/versions/<version>/` |

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

Use or append to `.codex/goal-teams/versions/<version>/progress.md`:

```md
# Goal Teams Progress

## <YYYY-MM-DD HH:mm> 执行轮次

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |

## 阻塞与决策

| 阻塞/决策 | 成员 | 影响 | 需要用户确认 | 建议 |
| --- | --- | --- | --- | --- |
```

Use or append to `.codex/goal-teams/versions/<version>/decisions.md`:

```md
# Goal Teams Decisions

| 时间 | 决策 | 原因 | 决策人 | 影响范围 |
| --- | --- | --- | --- | --- |
```

## Confirmation Tables

Before spawning worker subagents or editing implementation files, present a `Teams 规划表` first and ask the user to confirm it:

### Teams 规划表

The table uses merged display columns only. Keep the underlying planning logic fields intact: member, skill/subagent, goal slice, claimed tasks, locked scope, deliverable, done criteria, docs/tasklist updates, test owner, and validator.

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Skill/Subagent：`goal_backend` 或用户指定 skill | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>锁定范围：`src/api/wiki/` | 交付物：后端实现<br>完成标准：API 合同通过测试<br>文档/tasklist：Architecture Design + tasklist.md | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表代码审查 |
| 成员：前端-WIKI 列表页面开发<br>Skill/Subagent：`goal_frontend` 或用户指定 skill | 目标切片：WIKI 列表页面<br>认领任务：GT-004<br>锁定范围：`src/ui/wiki/` | 交付物：页面实现<br>完成标准：截图/E2E 通过<br>文档/tasklist：HTML Prototype + tasklist.md | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表体验审查 |

### SPEC Readiness

| SPEC | Exists | Action | Owner | Output |
| --- | --- | --- | --- | --- |
| Requirement Specification Card | no | create | 需求分析师 | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` |
| PRD | no | create | 产品/需求 | `.codex/goal-teams/versions/<version>/spec/PRD.md` |

### Environment Readiness

| Item | Status | Suggestion |
| --- | --- | --- |
| AGENTS/agent guidance | found/missing | 如果缺失，建议创建 `AGENTS.md` 或 `agent.md` |
| CLAUDE guidance | found/missing | 如果缺失，建议创建 `CLAUDE.md` 或 `claude.md` |
| Default guidance | active/not needed | 如果缺失项目指南，使用 `references/default-AGENTS.md` |
| Version directory | ready/pending | `.codex/goal-teams/versions/<version>/` |
| Document index | ready/pending | `.codex/goal-teams/INDEX.md` + `versions/<version>/INDEX.md` |

### Teams 规划表（简版）

Use this only as a compact fallback when a shorter table is needed. Prefer the full `Teams 规划表` above.

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：需求分析-WIKI 列表需求澄清<br>Skill/Subagent：`goal_requirements_analyst` 或用户指定 skill | 目标切片：梳理 WIKI 列表需求<br>认领任务：GT-001<br>锁定范围：`.codex/goal-teams/versions/<version>/spec/` | 交付物：需求规格卡<br>完成标准：用户确认核心目标/功能/流程/边界<br>文档/tasklist：requirement-spec-card.md + INDEX.md | 测试 Owner：评审-WIKI 列表需求校验<br>校验者：评审-WIKI 列表需求校验 |
| 成员：产品-WIKI 列表 PRD<br>Skill/Subagent：`goal_product` 或用户指定 skill | 目标切片：生成 WIKI 列表 PRD<br>认领任务：GT-002<br>锁定范围：`.codex/goal-teams/versions/<version>/spec/` | 交付物：PRD<br>完成标准：PRD 来源于已确认需求规格卡<br>文档/tasklist：PRD + tasklist.md | 测试 Owner：评审-WIKI 列表 PRD 校验<br>校验者：评审-WIKI 列表 PRD 校验 |

### Independent Validation Plan

| Artifact Type | Author | Validator | Validation Method | Evidence Location |
| --- | --- | --- | --- | --- |
| 文档 | 产出成员 | 非作者评审成员或用户指定 skill | 结构/事实/验收标准校验 | `progress.md` / `acceptance.md` |
| 代码 | 实现成员 | 独立测试/评审成员或用户指定 skill | 代码审查 + 命令验证 | `progress.md` |
| 测试用例 | 测试成员 | 独立评审成员或用户指定 skill | 断言有效性/边界覆盖校验 | `test-plan.md` / `progress.md` |

### Tasklist Execution

| Task ID | Owner | Status | Depends On | Verification | Completion Evidence |
| --- | --- | --- | --- | --- | --- |
| GT-001 | 需求分析师 | pending | - | 用户确认 | 需求规格卡完成 |
| GT-002 | 产品/需求 | pending | GT-001 | PRD review | PRD section complete |

### Risk And Approval

| Item | Risk | Owner | Approval Needed | Stop Condition |
| --- | --- | --- | --- | --- |
| Shared module | Multiple agents may edit same files | Goal Lead | Yes | unclear locked_scope |

Ask for confirmation in plain language after the tables. If the user explicitly says to proceed without confirmation or execute an already confirmed plan, still include the `Teams 规划表` as the plan and continue.

Also persist the confirmation tables and any assumptions to `.codex/goal-teams/versions/<version>/plan.md` unless the user requested a proposal only and no files should be written.

## Progress Feedback Tables

During execution, summarize each meaningful round with tables:

| Member | Claimed Tasks | Status | Current Step | Evidence | Next |
| --- | --- | --- | --- | --- | --- |
| 后端-WIKI 列表后端开发 | GT-003 | running | Test | `cargo test ...` | update docs |

For independent validation:

| Artifact | Author | Validator | Status | Evidence | Next |
| --- | --- | --- | --- | --- | --- |
| `spec/PRD.md` | 产品-WIKI 列表 PRD | 评审-WIKI 列表 PRD 校验 | passed | review note | update acceptance |

For blockers:

| Blocker | Member | Task | Impact | Decision Needed | Suggested Next |
| --- | --- | --- | --- | --- | --- |

For final closeout:

| Member | Claimed Tasks | Final Status | Evidence | Remaining |
| --- | --- | --- | --- | --- |

Append progress tables, blockers, and final closeout evidence to `.codex/goal-teams/versions/<version>/progress.md` or the relevant Markdown artifact.

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
2. Project guidance files when present: `AGENTS.md`, `agents.md`, `agent.md`, `CLAUDE.md`, `claude.md`.
3. `references/default-AGENTS.md` if no project guidance file exists.
4. `.codex/goal-teams/INDEX.md` and `.codex/goal-teams/versions/<version>/INDEX.md` if present.
5. `.codex/goal-teams/versions/<version>/plan.md` if present.
6. Relevant tasklist if present; otherwise generated `.codex/goal-teams/versions/<version>/tasklist.md`.
7. The current member's claimed task rows.
```

Load on demand:

| Need | Load |
| --- | --- |
| Product/user scope | Requirement Specification Card, PRD, issue, brief, or stakeholder notes if present |
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
- version:
- version_dir:
- done_criteria:
- language: Chinese by default
- constraints:
- discovered_docs:
- markdown_persistence:
  - INDEX.md
  - plan.md
  - progress.md
  - decisions.md
  - tasklist.md
- tasklist_path:
- openspec_or_superpower_lead_only: true/false
- allowed_scope:
- forbidden_scope:
- required_tests:
- required_docs_after_done:
  - Markdown progress/result updates
- required_spec:
  - Requirement Specification Card
  - PRD
  - Architecture Design
  - HTML Prototype when applicable
  - test plan
  - acceptance
- stop_conditions:
- confirmation_required:
- team_members:
  - member_id:
    display_name:
    role:
    skill_or_subagent:
    communication_style: brief, human-friendly Chinese
    claimed_tasks:
    locked_scope:
    deliverable:
    validation_owner_for:
```

Use the team packet to create one Member Goal Packet per subagent.

## Member Goal Packet

```text
Member Goal Packet:
- member_id: backend-gt-003
- display_name: 后端-WIKI 列表后端开发
- role: backend
- skill_or_subagent: goal_backend
- version: V3.0
- version_dir: .codex/goal-teams/versions/V3.0
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
  - Independent validator confirms generated code and tests.
- required_doc_load:
  - .codex/goal-teams/versions/V3.0/tasklist.md#GT-003
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
- required_independent_validation:
  - generated docs: validator must not be the author
  - generated code: independent QA/reviewer or user-specified skill
  - generated test cases: independent reviewer or user-specified skill
- required_docs_after_done:
  - tasklist status
  - versions/<version>/progress.md row
  - API notes if changed
- required_spec:
  - Requirement Specification Card: read or confirm not applicable
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
  - independent validation evidence
  - tasklist updates
  - SPEC updates
  - suggested team-state updates
  - completion status
  - blockers and risks
```

## Doc Capsule JSONL

Use this durable shape:

```json
{"ts":"2026-05-26T10:00:00+08:00","member_id":"backend-gt-003","source":".codex/goal-teams/versions/V3.0/tasklist.md#GT-003","decision":"Implement only the confirmed API slice.","must_do":["match accepted contract","run targeted tests"],"must_not_do":["edit shared auth without approval"],"test_refs":["targeted module tests"],"doc_update_refs":[".codex/goal-teams/versions/V3.0/tasklist.md"],"open_questions":[]}
```

## Team State JSON

```json
{
  "team": {
    "mode": "goal-teams",
    "goal": "Complete the confirmed user goal",
    "version": "V3.0",
    "version_dir": ".codex/goal-teams/versions/V3.0",
    "status": "planning",
    "tasklist_path": ".codex/goal-teams/versions/V3.0/tasklist.md",
    "updated_at": "2026-05-26T10:00:00+08:00"
  },
  "members": [
    {
      "id": "requirements-gt-001",
      "display_name": "需求分析-WIKI 列表需求澄清",
      "role": "requirements_analyst",
      "skill_or_subagent": "goal_requirements_analyst",
      "user_requested_skill": null,
      "user_requested_subagent": null,
      "status": "pending",
      "claimed_tasks": ["GT-001"],
      "current": "创建 WIKI 列表需求规格卡",
      "locked_scope": [".codex/goal-teams/versions/V3.0/spec"]
    }
  ],
  "tasks": [
    {
      "id": "GT-001",
      "title": "澄清需求并创建需求规格卡",
      "owner": "requirements-gt-001",
      "owner_display_name": "需求分析-WIKI 列表需求澄清",
      "claimed_by": null,
      "status": "pending",
      "deliverable": "Requirement Specification Card",
      "done_criteria": ["Core goals, functions, flows, and boundaries are clear", "User confirms the card"],
      "locked_scope": [".codex/goal-teams/versions/V3.0/spec"],
      "docs_update": [".codex/goal-teams/versions/V3.0/tasklist.md", ".codex/goal-teams/versions/V3.0/progress.md"],
      "spec_update": [".codex/goal-teams/versions/V3.0/spec/requirement-spec-card.md"],
      "validation": {
        "required": true,
        "validator": "评审-WIKI 列表需求校验",
        "evidence": []
      }
    }
  ]
}
```

## Events JSONL

```json
{"ts":"2026-05-26T10:01:00+08:00","type":"goal_team_planned","goal":"Complete the confirmed user goal"}
{"ts":"2026-05-26T10:02:00+08:00","type":"version_dir_created","path":".codex/goal-teams/versions/V3.0"}
{"ts":"2026-05-26T10:02:30+08:00","type":"index_created","path":".codex/goal-teams/versions/V3.0/INDEX.md"}
{"ts":"2026-05-26T10:03:00+08:00","type":"tasklist_created","path":".codex/goal-teams/versions/V3.0/tasklist.md"}
{"ts":"2026-05-26T10:03:00+08:00","type":"user_confirmed_plan","confirmation":"approved"}
{"ts":"2026-05-26T10:04:00+08:00","type":"member_spawned","member_id":"requirements-gt-001","skill_or_subagent":"goal_requirements_analyst"}
{"ts":"2026-05-26T10:20:00+08:00","type":"task_completed","task_id":"GT-001","member_id":"requirements-gt-001"}
```

## Messages JSONL

```json
{"ts":"2026-05-26T10:12:00+08:00","from":"qa-gt-003","to":"goal-lead","task_id":"GT-003","severity":"medium","message":"Need expected behavior for empty-state validation.","decision_needed":true,"status":"open"}
```

## Goal Loop Details

### Load

1. Read user goal and constraints.
2. Check project guidance files: `AGENTS.md`, `agents.md`, `agent.md`, `CLAUDE.md`, `claude.md`.
3. Read or create cross-version and version `INDEX.md` files.
4. Read or create versioned SPEC docs.
5. Read or create versioned tasklist.
6. Read current member's claimed task rows.
7. Read project docs only as needed.
8. Produce Doc Capsules.

### Plan

Return up to five steps:

```text
Plan:
1. 环境/版本/索引 -> verify: docs directory and INDEX ready
2. 需求规格卡 -> verify: user confirms goal/functions/flow/boundaries
3. PRD task -> verify: accepted criteria
4. Architecture Design task -> verify: design review
5. HTML Prototype task -> verify: screenshot/E2E when applicable
6. Implementation tasklist task -> verify: targeted test
7. Independent QA task -> verify: command/report
8. Docs/tasklist task -> verify: status and ownership updated
```

### Implement

Use tasklist order and dependencies. For engineering-heavy work, a common order is:

1. Environment guidance check and version directory.
2. Cross-version and version `INDEX.md`.
3. Requirement Specification Card.
4. PRD generated from the approved card.
5. Architecture Design.
6. HTML Prototype if applicable.
7. Tasklist implementation tasks.
8. Independent QA/testing tasks.
9. Docs, acceptance, and tasklist status updates.

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
- version `INDEX.md` entries when documents are added or changed
- reports or acceptance notes
- independent validation evidence for generated docs/code/tests
- remaining gaps

### Review

```text
Review Checklist:
- claimed task complete:
- done criteria:
- tests:
- generated docs/code/tests independently validated:
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
VERSION="V3.0"

codex exec \
  -C "$PROJECT" \
  --sandbox workspace-write \
  --ask-for-approval never \
  --json \
  --output-last-message ".codex/goal-teams/last-message.md" \
  - <<'PROMPT' | tee -a ".codex/goal-teams/events.jsonl"
Use $goal-teams.

Start by saying: 我是 Goal Teams Leader V1.1，我会帮你完成以下工作：
Use Chinese and keep Goal Lead messages concise and human-friendly.
Generated documentation, code comments, human-facing code strings, test names, and test cases should be Chinese by default.
Use Chinese member display names in the form <角色>-<具体任务名>, such as 后端-WIKI 列表后端开发. Show a four-column Teams 规划表 using merged display columns for member/skill, task scope, delivery/criteria, and verification, then ask the user to confirm it before spawning worker subagents or editing implementation files.
Check for AGENTS.md / agent.md / CLAUDE.md / claude.md. If none exists, use references/default-AGENTS.md as default guidance and suggest copying it to project-root AGENTS.md.
Use version "$VERSION" and store generated process/result docs under .codex/goal-teams/versions/$VERSION/.
Create or update .codex/goal-teams/INDEX.md and .codex/goal-teams/versions/$VERSION/INDEX.md before creating multiple docs.
Turn the user goal into Done Criteria.
Start with a requirements analyst. Use conversation plus web search, computer use, browser, or Chrome when available and useful to improve requirements.
First create a human-friendly Requirement Specification Card, no more than two pages, covering core goal, key business function structure, flow, and boundaries.
Generate PRD from the approved Requirement Specification Card.
Discover an existing tasklist, or create .codex/goal-teams/versions/$VERSION/tasklist.md if none exists.
Discover or create SPEC docs: Requirement Specification Card, PRD, Architecture Design, HTML Prototype when applicable, test plan, and acceptance.
Propose independent subagent members with claimed tasks, user-requested skill/subagent assignments, locked scopes, docs/SPEC updates, independent testing ownership, and done criteria.
Assign an independent validator for every generated document, code change, and test case. Use a separate subagent or the user-specified validation skill.
Show SPEC readiness, the four-column Teams 规划表, tasklist execution, independent validation plan, and risk tables before spawning implementation members unless the user explicitly skips confirmation or points to an already confirmed plan.
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
  'Use $goal-teams. 全程中文。只做 Goal Lead：检查环境，询问版本号，提出澄清问题，生成确认表格。不要编辑文件。'
```

## Safety And Coordination

- Do not start implementation without locked scope.
- Do not let members modify shared core files concurrently.
- Do not skip Plan mode.
- Do not self-approve generated artifacts.
- Do not mark generated docs, code, or test cases done without an independent subagent or user-specified skill validating them.
- Do not write multiple documents before creating the relevant `INDEX.md`.
- Do not write process/result Markdown outside the selected version directory except cross-version indexes.
- Do not skip the requirement specification card before PRD unless the user explicitly chooses OpenSpec/Superpower lead-only mode or confirms an exception.
- If the user specifies OpenSpec or Superpower, act only as Goal Lead by default and do not spawn role subagents without confirmation.
- Do not skip SPEC. Create missing Requirement Specification Card, PRD, Architecture Design, HTML Prototype when applicable, test plan, acceptance, and tasklist work items.
- Do not let implementation members be the only testers. Assign independent QA/testing skill/subagent.
- Honor user-specified skill/subagent assignments for members.
- Require lead approval for auth, payment, refund, migrations, destructive writes, security-sensitive integrations, or broad API changes.
- Keep `max_depth = 1`; members do not spawn nested teams.
- Keep team size around 3-6 concurrent members unless the user explicitly wants more.

## Completion Response

Use a concise final shape:

```text
完成：<一句话说明>

版本与文档：
| Version | Index | Main Docs |
| --- | --- | --- |

成员状态：
| Member | Claimed Tasks | Status | Evidence | Remaining |
| --- | --- | --- | --- | --- |

SPEC：
| SPEC | Status | Owner | Evidence |
| --- | --- | --- | --- |

独立校验：
| Artifact | Author | Validator | Status | Evidence |
| --- | --- | --- | --- | --- |

验证：
- <命令>：通过
- <命令>：未运行，原因...

文档与 tasklist：
- <文件>：已更新

剩余风险：
- <如无，写“无已知阻塞。”>
```
