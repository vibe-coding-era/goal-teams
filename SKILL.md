---
name: goal-teams
description: Coordinate Codex Goal Mode with independent subagents. Use for Goal Teams, multi-agent goal execution, Chinese-first SPEC/tasklist work, Teams planning tables, direct-execution plan records, numbered Plan choices, independent validation, and completion audits with auto-continuation.
---

# Goal Teams

Use this skill when a user wants Goal Mode execution with Agent Teams. The current Codex session is the Goal Lead, and every team member is an independent subagent with its own goal packet, document-loading slice, task claim, loop, completion check, and deliverable.

For detailed schemas, generic tasklist templates, confirmation tables, and CLI bridge examples, read `references/goal-teams-runtime.md`.

Current Skill version: `V1.3`. Keep this value aligned with the repository `VERSION` file.

## Core Model

- The current Codex session is the Goal Lead. It plans, proposes, confirms, assigns, coordinates, integrates, verifies, and summarizes.
- The Goal Lead communicates with the user in a human-friendly, concise style. Prefer plain words, short explanations, and clear options. Avoid unnecessary specialist vocabulary unless the user asks for detail.
- At the start of every Goal Teams run, before asking clarification questions, writing process docs, spawning subagents, or editing files, report identity and scope with this exact opening line: `我是 Goal Teams Leader V1.3，我会帮你完成以下工作：`. Then list the concrete work items you will handle in concise Chinese.
- Use Chinese throughout by default, including plans, tables, tasklists, SPEC docs, progress reports, subagent packets, final summaries, generated documentation, code comments, test names, test cases, and human-facing code strings. Keep code identifiers, commands, file paths, API names, logs, and quoted source text in their original language when needed.
- Every team member must be a separate subagent. Do not simulate team members only as sections inside the lead response when the user asks for Goal Teams.
- Use Chinese human-readable team member names in plans, packets, progress tables, and dashboard state. Names must combine role + concrete task name in the pattern `<角色>-<任务名>`, such as `后端-WIKI 列表后端开发`, `前端-WIKI 列表页面开发`, `测试-WIKI 列表验收测试`, or `需求分析-WIKI 列表需求澄清`. Avoid role-only or generic names such as `后端` or `后端-接口联调` when a concrete task is known. Keep technical subagent config IDs stable when needed.
- Each member receives a Member Goal Packet and runs its own loop: `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`.
- Prefer custom subagents `goal_requirements_analyst`, `goal_product`, `goal_backend`, `goal_frontend`, `goal_qa`, `goal_docs`, `goal_reviewer`, and `goal_completion_auditor` when those roles match the member packet.
- Honor user member overrides. If the user specifies that a member should use a particular skill, plugin, custom subagent, or built-in subagent type, include that assignment in the confirmation table and Member Goal Packet.
- If the user asks to use `openspec` or `superpower`, act only as the Goal Lead unless the user later confirms a full Goal Teams execution. In that mode, coordinate, clarify, index docs, and prepare lead-level artifacts, but do not spawn role subagents by default.
- Keep stable instructions unchanged across runs. Put dynamic details at the end of prompts to preserve prompt-cache friendliness.
- Use progressive document loading. Read only the smallest relevant existing document slices. If no tasklist exists, create one from the user goal before assigning work.
- Compress read documents into Doc Capsules before continuing.
- After all planned tasks appear complete, deferred, or blocked, spawn a fresh `goal_completion_auditor` subagent to inspect unfinished work before final response. If the auditor finds unfinished work inside the already confirmed goal scope, start a new Goal Teams continuation cycle automatically and do not ask the user for confirmation again.
- If the user prompt includes clear direct-execution wording such as `直接执行`, `直接开始`, `直接做`, `直接改`, `开始执行`, `不用确认`, `无需确认`, `跳过确认`, or `按你的方案执行`, treat it as permission to skip waiting for the initial Plan confirmation. Still produce the `Teams 规划表` as the execution record, then proceed directly.
- Direct execution never bypasses safety gates. If the plan requires new scope, destructive writes, credential access, payment/auth/security-sensitive changes, external approval, or a material business decision, ask the user before that risky step.

## Mandatory Plan Mode

Always begin in Plan mode for Goal Teams work:

- First report: `我是 Goal Teams Leader V1.3，我会帮你完成以下工作：`, followed by a short list of planned responsibilities for this run.
- Do not spawn implementation subagents or edit implementation files before producing the Plan tables.
- Do not skip Plan mode unless the user explicitly says to execute an already confirmed plan. When direct-execution wording is present, still run Plan mode, but do not wait for confirmation after showing the Plan tables unless a safety gate applies.
- Check the project environment before planning: look for `AGENTS.md`, `agents.md`, `agent.md`, `CLAUDE.md`, or `claude.md` at the project root or obvious config locations. If none exists, use `references/default-AGENTS.md` as the default active guidance and suggest that the user copy it to project-root `AGENTS.md` to capture team rules, coding style, and project constraints.
- Ask for or infer a version number before writing process docs. If no version is provided and it cannot be inferred, ask the user for the version directory name.
- Ask clarifying questions generously during planning and solution-design stages when goals, scope, acceptance criteria, priorities, constraints, user roles, design style, data contracts, risk tolerance, or deployment targets are unclear.
- Prefer 1-5 high-signal questions at a time, grouped by topic. Do not ask implementation trivia that can be discovered locally.
- When asking the user to choose among Plan options, present concise numbered choices, for example `1. 确认并执行`, `2. 调整成员`, `3. 只生成方案不执行`. Tell the user they can reply with a number. Treat a numeric reply as selecting the matching option.
- A valid Plan includes clarification status, assumptions, SPEC status, member assignments, task claims, locked scopes, test ownership, docs ownership, risks, and stop conditions.
- Before starting worker subagents or implementation edits, present a `Teams 规划表` for user confirmation or as a direct-execution record. The table must use four merged display columns: member/skill, task scope, delivery/criteria, and verification. Keep each member's role+task display name, skill/subagent, task slice, claimed tasks, locked scope, deliverable, done criteria, docs/tasklist updates, testing owner, and independent validator visible within those columns.
- After the user confirms, or after direct-execution wording authorizes skipping confirmation, execute exactly the shown plan unless a blocker requires re-planning.
- If the user changes the team, scope, skill, or subagent assignment, update the tables before continuing.

## SPEC First

Goal Teams execution is SPEC-driven. Discover existing SPEC docs first; create missing ones when needed and when appropriate for the confirmed plan.

Use these names:

- Requirements are `PRD`.
- Requirement analysis first creates a human-friendly `Requirement Specification Card` before the PRD. Keep it short enough to fit within two pages and make core goals, key business functions, user/business flows, and boundaries clear.
- Design is `Architecture Design`.
- If pages, screens, or workflows are involved, include an `HTML Prototype`.
- Development execution follows `tasklist.md`.
- Testing must be assigned to an independent test subagent or a user-specified testing skill/subagent.

Recommended project-local SPEC files are stored by version:

```text
.codex/goal-teams/
  INDEX.md
  versions/<version>/
    INDEX.md
    plan.md
    progress.md
    decisions.md
    tasklist.md
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
```

If the user provides or references `design.md`, read it before creating architecture/prototype docs and mirror its style, terminology, section structure, and level of detail where practical.

When creating more than one document, create or update the relevant `INDEX.md` first. The index must list planned documents, owners, status, and links.

## No Tasklist Assumption

Do not assume a project already has a tasklist. Discover first:

1. Look for user-mentioned tasklists.
2. Look for obvious project tasklists such as `TASKLIST.md`, `tasklist.md`, `docs/*task*`, `.codex/goal-teams/versions/*/tasklist.md`, `.codex/goal-teams/tasklist.md`, or issue/plan files.
3. If none exists, create `.codex/goal-teams/versions/<version>/tasklist.md` from the user goal.
4. In the generated tasklist, include member ownership, claim status, done criteria, docs responsibility, and verification responsibility from the beginning.

The tasklist is not a dependency; it is a coordination artifact. Create or update it as needed.

## Teams Planning Confirmation

Before spawning worker subagents or editing implementation files, always present a `Teams 规划表` to the user. Ask for confirmation in plain language unless the latest user prompt contains direct-execution wording or references an already confirmed plan. In direct-execution mode, label the table as `执行计划（已按用户要求直接执行）` and continue after showing it.

At minimum, show the logical planning fields in these four display columns:

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Skill/Subagent：`goal_backend` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>锁定范围：`src/api/wiki/` | 交付物：后端实现<br>完成标准：API 合同通过测试<br>文档/tasklist：Architecture Design + tasklist.md | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表代码审查 |

Member names in this table must use role + concrete task name, for example `后端-WIKI 列表后端开发`.

Also show environment and document-index readiness:

| Item | Status | Suggestion |
| --- | --- | --- |
| AGENTS/agent guidance | found/missing | If missing, suggest creating `AGENTS.md` or `agent.md` |
| CLAUDE guidance | found/missing | If missing, suggest creating `CLAUDE.md` or `claude.md` |
| Version directory | ready/pending | `.codex/goal-teams/versions/<version>/` |
| Document index | ready/pending | `.codex/goal-teams/INDEX.md` and version `INDEX.md` |

Also show a second table for risks and approvals when relevant:

| Item | Risk | Owner | Approval Needed | Stop Condition |
| --- | --- | --- | --- | --- |

After the user confirms the `Teams 规划表`, or after direct-execution wording authorizes execution, spawn each member as an independent subagent. If the user requests only a proposal, stop after the tables.

When waiting for a Plan decision, use numbered options by default:

```text
请选择下一步：
1. 确认并执行
2. 调整成员或范围
3. 只保留方案，不执行
```

The user may answer with just `1`, `2`, or `3`. If they answer with free text, map it to the closest option when unambiguous; otherwise ask one short follow-up.

Also show SPEC readiness:

| SPEC | Exists | Action | Owner | Output |
| --- | --- | --- | --- | --- |

During execution, report progress with tables:

| Member | Claimed Tasks | Status | Current Step | Evidence | Next |
| --- | --- | --- | --- | --- | --- |

Also report independent validation:

| Artifact | Author | Validator | Method | Status | Evidence |
| --- | --- | --- | --- | --- | --- |

## When To Use

Use Goal Teams for:

- Goals that benefit from multiple independent subagents.
- Multi-version, multi-module, or multi-deliverable work.
- Requirement-analysis-heavy work where conversation, research, browser/Chrome/computer-use context, and a short requirement specification card should precede the PRD.
- Work that must cover product/requirements, implementation, tests, docs, review, and acceptance.
- Projects where task ownership, task claiming, dashboard state, or completion checks should be explicit.
- Long goal loops that must continue until Done Criteria are satisfied or a real blocker is reached.
- Work where every generated document, code change, and test case must be checked by an independent subagent or a user-specified skill.

Prefer normal `agent-teams` or a single Codex session when the task is small, same-file heavy, highly sequential, or does not need Goal Mode.

## Runtime Files

For persistent Goal Teams work, use:

```text
.codex/goal-teams/
  INDEX.md              # Cross-version document index
  versions/<version>/
    INDEX.md            # Version document index, create before multiple docs
    tasklist.md         # Human-readable tasklist with member ownership
    goal-packet.md      # Current team-level dynamic goal packet
    plan.md             # Confirmed plan, assumptions, and clarification log
    progress.md         # Human-readable round-by-round progress tables
    decisions.md        # User decisions, lead decisions, and rationale
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
  team-state.json       # Canonical dashboard/team state
  events.jsonl          # Execution event history
  messages.jsonl        # Questions, blockers, handoffs, decisions
  doc-capsules.jsonl    # Progressive document summaries
  member-packets/       # One goal packet per subagent
  last-message.md       # Optional Codex CLI final output
```

Prefer Markdown files for persistent process and result records. Use structured JSON/JSONL as machine state only when needed; keep the durable human-facing source of truth in Markdown.

All process and result Markdown documents produced by this skill must live inside a version-numbered directory. Use `.codex/goal-teams/versions/<version>/` unless the project already has a stronger versioned docs convention. Keep only cross-version indexes or machine runtime files outside version directories.

Persist, when appropriate:

- Plans, assumptions, clarification questions, and user answers in `.codex/goal-teams/versions/<version>/plan.md`.
- Team/member progress tables in `.codex/goal-teams/versions/<version>/progress.md`.
- Product, design, prototype, test, acceptance, and task ownership in Markdown SPEC/tasklist files.
- Final results, verification evidence, and remaining risks in Markdown closeout notes or the relevant SPEC/tasklist sections.

When the project already uses another coordination directory, either reuse it or mirror critical fields.

## Goal Team Workflow

1. Understand the goal.
   - Turn the user request into verifiable Done Criteria.
   - Check for `AGENTS.md`/`agent.md` and `CLAUDE.md`/`claude.md`; if none exists, load `references/default-AGENTS.md` as default guidance and suggest creating `AGENTS.md`.
   - Identify or ask for the target version number and version docs directory.
   - Identify likely deliverables, constraints, risks, and verification.
   - In planning and solution-design stages, ask clarifying questions before locking scope whenever material information is missing.
   - Persist questions, answers, assumptions, and decisions in Markdown.
   - If multiple docs will be generated, create/update `.codex/goal-teams/INDEX.md` and `.codex/goal-teams/versions/<version>/INDEX.md` before creating the docs.

2. Run requirement analysis.
   - Assign `goal_requirements_analyst` unless the user chooses `openspec` or `superpower` lead-only mode.
   - Use conversation plus allowed web search, computer use, browser, or Chrome capabilities when relevant and available.
   - Produce `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` before PRD.
   - Keep the requirement specification card human-friendly and no more than two pages.

3. Discover or create SPEC.
   - Look for PRD, architecture/design docs, design.md, prototypes, test plans, acceptance docs, and tasklists.
   - If missing, add SPEC creation/update tasks to the Plan.
   - Generate PRD from the requirement specification card, not directly from raw conversation.
   - Use `PRD` for requirements and `Architecture Design` for design.
   - If UI/pages/workflows exist, include an `HTML Prototype` task.

4. Discover or create the tasklist.
   - Read an existing tasklist only if it exists and is relevant.
   - If none exists, create `.codex/goal-teams/versions/<version>/tasklist.md`.
   - Include task ID, owner/member, status, claimed_by, locked_scope, deliverable, done criteria, verification, and docs updates.
   - Development work must follow tasklist order and dependencies.

5. Build the Team Goal Packet.
   - Include goal, success criteria, discovered docs, allowed scope, forbidden scope, tests, docs-after-done, stop conditions, and member plan.
   - Include user-specified skills/subagents for members.
   - Keep this packet compact and append it after the stable core instructions.

6. Split into members.
   - Split by deliverable, module, version lane, or review lens.
   - Assign each member a Chinese display name formed from role + concrete task name, role, skill/subagent type, claimed tasks, locked scope, docs responsibility, independent validation responsibility, and output contract.
   - Typical members: requirements analyst, product/PRD, backend, frontend, QA, docs, reviewer/security.
   - Assign testing to an independent `goal_qa`, testing skill, reviewer, or user-specified test subagent. Do not let the implementation owner be the only tester.
   - Assign every generated artifact to a validator that is not the author, unless the user explicitly specifies a validation skill.

7. Confirm with tables.
   - Present environment readiness, index readiness, SPEC readiness, `Teams 规划表`, tasklist, independent validation plan, and risk/approval tables.
   - Wait for user confirmation before spawning worker subagents or editing implementation files unless the latest user prompt contains direct-execution wording or references an already confirmed plan. If confirmation is skipped, still show the `Teams 规划表` as the execution record before continuing.
   - When waiting for the user's Plan decision, offer numbered choices so the user can reply with a simple number.

8. Spawn independent subagents.
   - Each member runs as a subagent with its own Member Goal Packet.
   - Use read-only/explorer agents for analysis, requirements, architecture mapping, review, or test planning.
   - Use worker agents for implementation with explicit locked scope.
   - Do not let subagents spawn their own teams.

9. Run goal loops.
   - Every member performs `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`.
   - Each member reads only the minimum document slices needed for its packet.
   - Each member emits Doc Capsules and state updates.
   - Each member must report whether its claimed task is complete, blocked, or incomplete.
   - The lead summarizes progress with a table after each meaningful round.

10. Coordinate through the lead.
   - The lead routes blockers and cross-member questions through `messages.jsonl` or direct follow-up.
   - Shared core changes, migrations, auth, payment, destructive writes, and broad API changes require lead approval.

11. Integrate, audit, and continue if needed.
   - The lead integrates outputs, resolves conflicts, runs verification, updates `team-state.json`, and updates tasklist/docs.
   - Do not mark a goal done until every claimed task is done, explicitly deferred, or blocked with a documented reason.
   - Do not mark a generated document, code change, or test case done until independent validation evidence is recorded.
   - Spawn a new `goal_completion_auditor` subagent to audit tasklist, progress, acceptance, tests, docs, and remaining risks.
   - If the auditor finds unfinished work within the confirmed goal scope, convert those gaps into continuation tasks, show the continuation Teams plan as an execution record, and spawn the needed Goal Teams members without waiting for user confirmation.
   - Ask the user only when the auditor finds new scope, risky/destructive work, missing external information, or a decision outside the already confirmed plan.

## Stable Core Prompt

Use this stable instruction block for member subagents, then append the Member Goal Packet:

```text
You are a Goal Teams member running under a Codex Goal Lead.
Your objective is to complete your claimed goal slice to a verifiable done state.

Rules:
1. Read only the smallest relevant documents or tasklist sections.
2. If required context is missing, report the gap instead of inventing hidden requirements.
3. Convert documents into Doc Capsules before continuing.
4. Follow the loop: Load -> Plan -> Implement -> Test -> Document -> Review -> Continue.
5. Stay inside locked_scope and forbidden_scope.
6. Do not revert user or other-agent changes.
7. Stop and report a blocker if shared risky code, missing credentials, conflicting docs, or unclear scope blocks safe progress.
8. Update state through the lead contract: completed tasks, tests, docs, blockers, risks, and suggested team-state/tasklist changes.
```

## Member Goal Packet

Give each subagent a compact packet:

```text
Member Goal Packet:
- member_id:
- display_name: <角色>-<具体任务名>, for example 后端-WIKI 列表后端开发
- role:
- skill_or_subagent:
- version:
- user_requested_skill:
- user_requested_subagent:
- lane_or_deliverable:
- target_task_ids:
- claimed_tasks:
- goal:
- success_criteria:
- required_doc_load:
- allowed_scope:
- forbidden_scope:
- locked_scope:
- required_tests:
- required_independent_validation:
  - documents
  - code
  - test cases
- required_docs_after_done:
- spec_updates:
  - PRD
  - Requirement Specification Card
  - Architecture Design
  - HTML Prototype
  - tasklist
  - test plan
- stop_conditions:
- output_contract:
  - Doc Capsules
  - plan
  - files changed
  - tests run
  - independent validation evidence
  - docs updated
  - tasklist updates
  - SPEC updates
  - team-state updates
  - completion status
  - blockers and risks
```

## Doc Capsule

After reading any source document, compress it into:

```text
Doc Capsule:
- source:
- decision:
- must_do:
- must_not_do:
- test_refs:
- doc_update_refs:
- open_questions:
```

Append durable capsules to `.codex/goal-teams/doc-capsules.jsonl` when persistent state matters.

## Parallelism Rules

- Use 3-6 concurrent members for most projects.
- Parallelize by deliverable, version lane, module, or review lens.
- Serialize shared core modules and high-risk changes.
- Assign one owner per deliverable or lane.
- Give every implementation member a `locked_scope`.
- Require an independent test member or testing skill/subagent for verification.
- Keep `max_depth = 1`; members should not create nested teams.

## Completion Audit And Auto-Continuation

Every Goal Teams run has a final audit gate:

1. When the lead believes all claimed work is complete, deferred, or blocked, spawn a fresh `goal_completion_auditor` subagent in read-only mode.
2. The auditor checks tasklist status, progress logs, acceptance evidence, test results, SPEC/docs, independent validation records, unresolved blockers, and remaining risks.
3. If the auditor reports no unfinished work, the lead may send the final completion response.
4. If the auditor finds unfinished work inside the already confirmed goal scope, the lead must create continuation tasks and start another Goal Teams cycle automatically. Do not ask the user for confirmation; show the continuation `Teams 规划表` as the execution record and spawn the needed members.
5. If the user originally authorized direct execution, keep using direct execution for continuation tasks inside the same confirmed scope. Ask only when the continuation touches a safety gate or new scope.
6. If the auditor finds new scope, destructive or security-sensitive work, missing credentials, external approvals, or unresolved user decisions, record the blocker and ask the user instead of auto-continuing.
7. Repeat audit and continuation until the auditor reports complete, or only blocked/deferred work remains with documented reasons.

## Completion Rules

A Goal Team is not done until the lead can report:

- Done Criteria satisfied.
- Each claimed task is `done`, `deferred`, or `blocked` with a reason.
- A fresh `goal_completion_auditor` subagent found no unfinished work inside the confirmed scope, or any remaining work is blocked/deferred with documented reasons.
- Required tests run, or skipped with reason and risk.
- Testing was performed by an independent member/skill/subagent, or the exception is explicitly documented.
- Every generated document, code change, and test case was validated by an independent subagent or a user-specified skill, with evidence recorded.
- Tasklist and required docs updated with member ownership and final status.
- Requirement Specification Card, PRD, Architecture Design, HTML Prototype when relevant, test plan, acceptance, and tasklist are complete or explicitly marked not applicable.
- Version directory and document indexes are updated.
- Blockers and remaining risks captured.
- `team-state.json` reflects final state when runtime files are used.

## Useful Pairing

Use `agent-teams` when you need general team coordination. Use `goal-teams` when the team must create/maintain a tasklist, confirm member ownership in tables, spawn independent subagents, and close a goal loop with done criteria.
