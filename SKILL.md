---
name: goal-teams
description: Run Codex Goal Mode as a coordinated team of independent subagents for any project. Use when the user asks for Goal Teams, goal-mode teams, multi-agent goal execution, version/module goals, versioned document directories, document indexes, requirement analysis, requirement specification cards, goal packets, Chinese-first team execution, Markdown persistence for process/results, planning-stage clarification questions, SPEC-driven execution, PRD, architecture design, HTML prototypes, tasklist creation, member task claiming, confirmation tables, progress tables, progressive document loading, Doc Capsules, or when combining Codex Goal Mode with Agent Teams so every team member runs as its own subagent.
---

# Goal Teams

Use this skill when a user wants Goal Mode execution with Agent Teams. The current Codex session is the Goal Lead, and every team member is an independent subagent with its own goal packet, document-loading slice, task claim, loop, completion check, and deliverable.

For detailed schemas, generic tasklist templates, confirmation tables, and CLI bridge examples, read `references/goal-teams-runtime.md`.

## Core Model

- The current Codex session is the Goal Lead. It plans, proposes, confirms, assigns, coordinates, integrates, verifies, and summarizes.
- The Goal Lead communicates with the user in a human-friendly, concise style. Prefer plain words, short explanations, and clear options. Avoid unnecessary specialist vocabulary unless the user asks for detail.
- Use Chinese throughout by default, including plans, tables, tasklists, SPEC docs, progress reports, subagent packets, and final summaries. Keep code identifiers, commands, file paths, API names, and quoted source text in their original language when needed.
- Every team member must be a separate subagent. Do not simulate team members only as sections inside the lead response when the user asks for Goal Teams.
- Each member receives a Member Goal Packet and runs its own loop: `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`.
- Prefer custom subagents `goal_requirements_analyst`, `goal_product`, `goal_backend`, `goal_frontend`, `goal_qa`, `goal_docs`, and `goal_reviewer` when those roles match the member packet.
- Honor user member overrides. If the user specifies that a member should use a particular skill, plugin, custom subagent, or built-in subagent type, include that assignment in the confirmation table and Member Goal Packet.
- If the user asks to use `openspec` or `superpower`, act only as the Goal Lead unless the user later confirms a full Goal Teams execution. In that mode, coordinate, clarify, index docs, and prepare lead-level artifacts, but do not spawn role subagents by default.
- Keep stable instructions unchanged across runs. Put dynamic details at the end of prompts to preserve prompt-cache friendliness.
- Use progressive document loading. Read only the smallest relevant existing document slices. If no tasklist exists, create one from the user goal before assigning work.
- Compress read documents into Doc Capsules before continuing.

## Mandatory Plan Mode

Always begin in Plan mode for Goal Teams work:

- Do not spawn implementation subagents or edit implementation files before producing the Plan tables.
- Do not skip Plan mode unless the user explicitly says to execute an already confirmed plan.
- Check the project environment before planning: look for `AGENTS.md`, `agents.md`, `agent.md`, `CLAUDE.md`, or `claude.md` at the project root or obvious config locations. If none exists, suggest that the user create one to capture team rules, coding style, and project constraints.
- Ask for or infer a version number before writing process docs. If no version is provided and it cannot be inferred, ask the user for the version directory name.
- Ask clarifying questions generously during planning and solution-design stages when goals, scope, acceptance criteria, priorities, constraints, user roles, design style, data contracts, risk tolerance, or deployment targets are unclear.
- Prefer 1-5 high-signal questions at a time, grouped by topic. Do not ask implementation trivia that can be discovered locally.
- A valid Plan includes clarification status, assumptions, SPEC status, member assignments, task claims, locked scopes, test ownership, docs ownership, risks, and stop conditions.
- After the user confirms, execute exactly the confirmed plan unless a blocker requires re-planning.
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

## Confirmation First

Before spawning worker subagents or editing implementation files, present a confirmation table to the user unless they explicitly told you to proceed without confirmation.

At minimum, show:

| Member | Skill/Subagent | Goal Slice | Claimed Tasks | Locked Scope | Deliverable | Done Criteria | Docs/Tasklist Updates |
| --- | --- | --- | --- | --- | --- | --- | --- |

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

After the user confirms, spawn each member as an independent subagent. If the user requests only a proposal, stop after the tables.

Also show SPEC readiness:

| SPEC | Exists | Action | Owner | Output |
| --- | --- | --- | --- | --- |

During execution, report progress with tables:

| Member | Claimed Tasks | Status | Current Step | Evidence | Next |
| --- | --- | --- | --- | --- | --- |

## When To Use

Use Goal Teams for:

- Goals that benefit from multiple independent subagents.
- Multi-version, multi-module, or multi-deliverable work.
- Requirement-analysis-heavy work where conversation, research, browser/Chrome/computer-use context, and a short requirement specification card should precede the PRD.
- Work that must cover product/requirements, implementation, tests, docs, review, and acceptance.
- Projects where task ownership, task claiming, dashboard state, or completion checks should be explicit.
- Long goal loops that must continue until Done Criteria are satisfied or a real blocker is reached.

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
   - Check for `AGENTS.md`/`agent.md` and `CLAUDE.md`/`claude.md`; if none exists, suggest creating one.
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
   - Assign each member a role, skill/subagent type, claimed tasks, locked scope, docs responsibility, verification responsibility, and output contract.
   - Typical members: requirements analyst, product/PRD, backend, frontend, QA, docs, reviewer/security.
   - Assign testing to an independent `goal_qa`, testing skill, reviewer, or user-specified test subagent. Do not let the implementation owner be the only tester.

7. Confirm with tables.
   - Present environment readiness, index readiness, SPEC readiness, member assignment, tasklist, and risk/approval tables.
   - Wait for user confirmation before spawning worker subagents or editing implementation files, unless the user explicitly asked you to proceed.

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

11. Integrate and close.
   - The lead integrates outputs, resolves conflicts, runs verification, updates `team-state.json`, and updates tasklist/docs.
   - Do not mark a goal done until every claimed task is done, explicitly deferred, or blocked with a documented reason.

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

## Completion Rules

A Goal Team is not done until the lead can report:

- Done Criteria satisfied.
- Each claimed task is `done`, `deferred`, or `blocked` with a reason.
- Required tests run, or skipped with reason and risk.
- Testing was performed by an independent member/skill/subagent, or the exception is explicitly documented.
- Tasklist and required docs updated with member ownership and final status.
- Requirement Specification Card, PRD, Architecture Design, HTML Prototype when relevant, test plan, acceptance, and tasklist are complete or explicitly marked not applicable.
- Version directory and document indexes are updated.
- Blockers and remaining risks captured.
- `team-state.json` reflects final state when runtime files are used.

## Useful Pairing

Use `agent-teams` when you need general team coordination. Use `goal-teams` when the team must create/maintain a tasklist, confirm member ownership in tables, spawn independent subagents, and close a goal loop with done criteria.
