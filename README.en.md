# Goal Teams

[中文](README.md) | English

Author: 肉山@TGO Hangzhou

`goal-teams` is a Codex Skill for running Goal Mode as a coordinated team of independent subagents. It combines ideas from Claude Code Agent Teams with Codex Goal Mode, and enforces Plan Mode, Chinese-first execution, SPEC-first delivery, Markdown persistence, table-based confirmation, and independent testing.

It is designed for medium and large work: product planning, multi-module engineering, version-lane execution, frontend/backend/testing/docs collaboration, code audit, security review, architecture review, and any project where the process should be easy to review, share, and replay later.

## Core Idea

Goal Teams makes each team member an independent subagent, instead of treating roles as labels inside one long answer.

- The Goal Lead clarifies the goal, proposes the plan, confirms ownership, routes blockers, integrates outputs, and closes the work.
- Each member owns one goal slice, a locked scope, and a concrete deliverable.
- The team works from shared SPEC files, tasklists, indexes, and Markdown progress records.
- Testing must be performed by an independent QA subagent or a user-selected testing skill/subagent.
- Plans, progress, decisions, and results are persisted in Markdown so the work can be reviewed later.

## Key Capabilities

- Chinese-first execution: plans, tables, SPEC files, tasklists, progress reports, and member packets default to Chinese.
- Chinese-generated artifacts: generated docs, code comments, human-facing code strings, test names, and test case descriptions default to Chinese.
- Mandatory Plan Mode: clarify, plan, and confirm before implementation.
- More clarification during planning: ask about goals, scope, acceptance criteria, priorities, design style, data contracts, release constraints, and risk approvals when unclear.
- Environment check: check `AGENTS.md`, `agent.md`, `CLAUDE.md`, and `claude.md`; when missing, use `references/default-AGENTS.md` as default guidance and suggest saving it as project-root `AGENTS.md`.
- Versioned documents: process and result documents are stored under `.codex/goal-teams/versions/<version>/`.
- Index first: create `.codex/goal-teams/INDEX.md` and the version `INDEX.md` before creating multiple documents.
- Requirement card first: a requirements analyst uses conversation, web search, computer use, browser, or Chrome when useful, then creates a human-friendly Requirement Specification Card before PRD.
- SPEC First: create or update Requirement Specification Card, PRD, Architecture Design, HTML Prototype, Test Plan, and Acceptance before implementation.
- Markdown persistence: process and results are saved as versioned Markdown files.
- Tasklist coordination: if no tasklist exists, create `.codex/goal-teams/versions/<version>/tasklist.md`.
- Task claiming: every member has claimed tasks, locked scope, deliverables, and done criteria.
- Chinese member names: member display names use Chinese, preferably `<role>-<task>`, such as `后端-接口联调`.
- User-selected capabilities: the user can assign a member to a specific skill, plugin, custom subagent, or built-in subagent type.
- OpenSpec/Superpower compatibility: when the user specifies `openspec` or `superpower`, Goal Teams defaults to Goal Lead only and does not automatically start a full role team.
- Table-based progress feedback: progress, blockers, risks, and closeout evidence are reported in tables.
- Independent testing: implementation owners cannot be the only testers.
- Independent validation: every generated document, code change, and test case must be checked by an independent subagent or user-selected skill.
- Version-lane parallelism: work can be split by version, module, deliverable, or review lens.

## Repository Layout

After installation, the Skill layout is:

```text
goal-teams/
  SKILL.md
  agents/
    openai.yaml
  references/
    goal-teams-runtime.md
    default-AGENTS.md
  subagents/
    goal-requirements-analyst.toml
    goal-product.toml
    goal-backend.toml
    goal-frontend.toml
    goal-qa.toml
    goal-docs.toml
    goal-reviewer.toml
```

The root-level `goal-teams.md` records long-term user requirements for this Skill.

When the target project has no `AGENTS.md`, `agent.md`, `CLAUDE.md`, or `claude.md`, Goal Teams uses [default-AGENTS.md](references/default-AGENTS.md) as active default guidance and suggests copying it to the project root as `AGENTS.md`.

## Runtime Files

During project execution, Goal Teams uses or creates these files:

```text
.codex/goal-teams/
  INDEX.md              # Cross-version document index
  versions/<version>/
    INDEX.md            # Version document index, create before multiple docs
    plan.md             # Clarification questions, answers, assumptions, confirmed plan
    progress.md         # Round-by-round progress tables, blockers, next steps
    decisions.md        # Decisions, reasons, approvals
    tasklist.md         # Task ownership, state, acceptance, verification
    goal-packet.md      # Team-level goal packet
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
  team-state.json       # Machine-readable team state
  events.jsonl          # Execution event history
  messages.jsonl        # Questions, blockers, handoffs, decisions
  doc-capsules.jsonl    # Document capsules
  member-packets/       # One goal packet per subagent
```

## SPEC Convention

Goal Teams is SPEC-driven. Missing documents are created or scheduled in the tasklist before implementation.

| Layer | File | Purpose |
| --- | --- | --- |
| Index | `.codex/goal-teams/INDEX.md` + `versions/<version>/INDEX.md` | Cross-version and version document indexes |
| Requirement Specification Card | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` | Human-friendly requirements card, no more than two pages |
| PRD | `.codex/goal-teams/versions/<version>/spec/PRD.md` | Requirements document generated from the approved card |
| Architecture Design | `.codex/goal-teams/versions/<version>/spec/architecture-design.md` | Architecture, module boundaries, interfaces, data, risks |
| HTML Prototype | `.codex/goal-teams/versions/<version>/spec/HTML-prototype.html` | Screens, workflows, and interactions when UI/workflow exists |
| Test Plan | `.codex/goal-teams/versions/<version>/spec/test-plan.md` | Test scope, strategy, commands, evidence |
| Acceptance | `.codex/goal-teams/versions/<version>/spec/acceptance.md` | Final acceptance checklist, evidence, remaining risks |
| Tasklist | `.codex/goal-teams/versions/<version>/tasklist.md` | Ownership, status, dependencies, verification, docs updates |

If the project already has `design.md`, Goal Teams reads it first and mirrors its visual language, terminology, section structure, and level of detail where practical.

## Default Subagents

This repository provides seven recommended subagents:

| Subagent | Role | Typical Responsibility |
| --- | --- | --- |
| `goal_requirements_analyst` | Requirements analyst | Conversational discovery, research-assisted analysis, Requirement Specification Card, PRD handoff |
| `goal_product` | Product / PRD | Generate PRD from the approved card, acceptance criteria, prototype structure, product review |
| `goal_backend` | Backend engineer | Domain model, storage, API, CLI, MCP, migrations, integrations |
| `goal_frontend` | Frontend engineer | UI, HTML prototype, browser verification, E2E, screenshot evidence |
| `goal_qa` | QA | Independent testing, integration tests, acceptance evidence, test reports |
| `goal_docs` | Documentation | Tasklist, acceptance docs, README, reports, release notes |
| `goal_reviewer` | Reviewer | Read-only review, architecture boundaries, safety, coverage, compatibility, risks |

The user can also assign a specific member to another skill or subagent:

```text
Use $goal-teams.
Use goal_requirements_analyst for requirements analysis.
Use goal_product for PRD.
Use goal_frontend for frontend work and follow design.md.
Use goal_qa for independent testing.
Use goal_reviewer for read-only security review.
```

## Workflow

1. Understand the goal and turn it into verifiable done criteria.
2. Check the environment for `AGENTS.md`, `agent.md`, `CLAUDE.md`, or `claude.md`; suggest creating one if missing.
3. Confirm the target version and document directory.
4. Create or update the cross-version index and version index before multiple documents.
5. Ask focused clarification questions during planning.
6. Run requirements analysis and create the Requirement Specification Card.
7. Create or update SPEC docs from the approved card: PRD, Architecture Design, HTML Prototype, Test Plan, Acceptance.
8. Discover or create `.codex/goal-teams/versions/<version>/tasklist.md`.
9. Split members by version, module, deliverable, or review lens.
10. Confirm environment, indexes, SPEC readiness, member ownership, tasks, risks, and approvals in tables.
11. Use Chinese display names for members, such as `后端-接口联调` or `测试-租期规则`.
12. Assign independent validators for generated docs, code, and test cases.
13. Wait for user confirmation before implementation or worker subagents.
14. Run each member as an independent subagent.
15. Persist progress, blockers, decisions, and results in versioned Markdown.
16. Verify with independent QA, reviewer, or a user-selected validation skill/subagent.
17. Integrate outputs and close the tasklist, SPEC, progress, and acceptance docs.

## Confirmation Table Examples

### SPEC Readiness

| SPEC | Exists | Action | Owner | Output |
| --- | --- | --- | --- | --- |
| Requirement Specification Card | no | create | Requirements analyst | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` |
| PRD | no | create | Product / PRD | `.codex/goal-teams/versions/<version>/spec/PRD.md` |
| Architecture Design | no | create | Backend / Architecture | `.codex/goal-teams/versions/<version>/spec/architecture-design.md` |
| HTML Prototype | applicable | create | Frontend | `.codex/goal-teams/versions/<version>/spec/HTML-prototype.html` |
| Test Plan | no | create | QA | `.codex/goal-teams/versions/<version>/spec/test-plan.md` |
| Acceptance | no | create | Docs / QA | `.codex/goal-teams/versions/<version>/spec/acceptance.md` |

### Member Plan

| Member | Skill/Subagent | Goal Slice | Claimed Tasks | Locked Scope | Deliverable | Done Criteria | Docs/Tasklist Updates |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 需求分析-规格卡 | `goal_requirements_analyst` | Clarify requirements | GT-001 | `.codex/goal-teams/versions/<version>/spec/` | Requirement Specification Card | User confirms goals, functions, flow, boundaries | requirement-spec-card + INDEX |
| 产品-PRD | `goal_product` | Generate PRD | GT-002 | `.codex/goal-teams/versions/<version>/spec/` | PRD | Based on approved card | PRD + tasklist |
| 后端-接口联调 | `goal_backend` | Implement API contract | GT-003 | `src/api/` | API implementation | Tests pass and independent validation is recorded | Architecture Design + tasklist |
| 前端-订单页面 | `goal_frontend` | UI and workflow | GT-004 | `src/ui/` | UI/prototype | Screenshot/E2E evidence and independent validation | HTML Prototype + tasklist |
| 测试-验收证据 | `goal_qa` | Verify delivery | GT-005 | `tests/` | Test report | Evidence complete and test cases independently validated | Test Plan + Acceptance |

### Independent Validation Plan

| Artifact | Author | Validator | Method | Evidence |
| --- | --- | --- | --- | --- |
| Document | Producing member | Non-author reviewer or user-selected skill | Structure/facts/acceptance review | `progress.md` / `acceptance.md` |
| Code | Implementing member | Independent QA/reviewer or user-selected skill | Code review + command verification | `progress.md` |
| Test case | QA member | Independent reviewer or user-selected skill | Assertion and boundary review | `test-plan.md` / `progress.md` |

### Progress

| Member | Claimed Tasks | Status | Current Step | Evidence | Next |
| --- | --- | --- | --- | --- | --- |
| 后端-接口联调 | GT-003 | running | Test | `npm test -- api` | update architecture notes |

## Installation

### Install the Skill

Clone the repository into your Codex skills directory:

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

Or copy the Skill files manually:

```bash
mkdir -p ~/.codex/skills/goal-teams
cp -R ./SKILL.md ./agents ./references ~/.codex/skills/goal-teams/
```

### Install Subagents

Copy the TOML files into the Codex agents directory:

```bash
mkdir -p ~/.codex/agents
cp ./subagents/goal-*.toml ~/.codex/agents/
```

Restart Codex or refresh configuration after installation.

## Usage Examples

### Plan A Requirement

```text
Use $goal-teams.
Create a Goal Teams plan for "Car Sharing V3.0".
Use Chinese throughout.
Ask me clarification questions first.
Save process and results to the V3.0 version directory.
Create the Requirement Specification Card before PRD.
```

### Parallelize By Version

```text
Use $goal-teams.
The tasklist has V3.0, V3.1, and V3.2.
Split work by version lanes, but serialize shared core modules.
Testing must be handled by an independent QA member.
```

### Assign Specific Members

```text
Use $goal-teams.
Use goal_requirements_analyst for requirements analysis.
Use goal_product for PRD.
Use goal_frontend and follow design.md.
Use goal_qa for testing.
Use goal_reviewer in read-only mode for security review.
```

### Use OpenSpec Or Superpower

```text
Use $goal-teams.
This time use openspec.
Only act as Goal Lead: check environment, confirm version directory, create index plan, organize clarification questions and the plan.
Do not automatically start the full role team.
```

### Proposal Only

```text
Use $goal-teams.
Only create the plan tables, SPEC readiness table, member plan, and risk approval table.
Do not edit implementation files.
```

## Codex CLI Example

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

Use Chinese.
Keep Goal Lead communication concise and human-friendly.
Check AGENTS.md / agent.md / CLAUDE.md / claude.md. If none exists, use references/default-AGENTS.md as default guidance and suggest saving it as project-root AGENTS.md.
Generated docs, code comments, human-facing code strings, test names, and test case descriptions should be Chinese by default.
Use Chinese member display names in the form <role>-<task>.
Use version "$VERSION" and store generated process/result docs under .codex/goal-teams/versions/$VERSION/.
Create or update .codex/goal-teams/INDEX.md and .codex/goal-teams/versions/$VERSION/INDEX.md before creating multiple docs.
Start in Plan Mode and ask clarification questions.
Persist plans, progress, decisions, and results in versioned Markdown.
Use a requirements analyst with conversation and useful research via web search, computer use, browser, or Chrome.
First create a Requirement Specification Card of no more than two pages.
Then generate PRD from that card.
Discover or create SPEC docs: Requirement Specification Card, PRD, Architecture Design, HTML Prototype, Test Plan, Acceptance.
If no tasklist exists, create .codex/goal-teams/versions/$VERSION/tasklist.md.
Confirm members, task claims, locked scopes, testing owner, and risk approvals in tables.
Assign an independent validator or user-selected skill for every generated document, code change, and test case.
After confirmation, run each team member as an independent subagent.
Testing must be handled by independent QA or a testing skill/subagent.
PROMPT
```

Planning-only mode:

```bash
codex exec \
  -C "$PROJECT" \
  --sandbox read-only \
  --json \
  'Use $goal-teams. Use Chinese. Only act as Goal Lead: check environment, ask for version, plan indexes, create confirmation tables, and do not edit implementation files.'
```

## Agent Teams vs Goal Teams

| Dimension | Agent Teams | Goal Teams |
| --- | --- | --- |
| Purpose | General multi-agent coordination | Goal-closure execution with independent subagents |
| Planning | Optional | Mandatory Plan Mode |
| SPEC | Optional | Mandatory SPEC First |
| Requirement card | Optional | Required before PRD by default |
| Tasklist | Optional | Created when missing |
| Persistence | Case by case | Versioned Markdown-first |
| Testing | May be done by implementer | Must be independent |
| Feedback | Flexible | Progress and results in tables |
| Best for | Research, analysis, coordination | Requirement-to-delivery workflow |

## Good Fit

- Planning and delivering a product requirement from scratch.
- Requirements are unclear and should first be shaped into a concise card.
- Multi-module work involving frontend, backend, testing, docs, and review.
- Parallel version lanes such as V3.0, V3.1, V3.2.
- Work requiring PRD, architecture design, prototype, test plan, and acceptance docs.
- Work that should be shared, reviewed, or replayed later.
- Code audit, security review, and architecture review with independent perspectives.
- Combining Codex CLI, tasklists, dashboards, and local project state.

## Not A Good Fit

- Tiny single-file edits.
- Highly sequential tasks that cannot be split.
- Quick Q&A where planning, SPEC, or persistence would add unnecessary overhead.
- Very short tasks where the user does not want clarification and confirmation.

## Safety And Collaboration Rules

- Do not start implementation subagents before the plan is confirmed.
- When OpenSpec or Superpower is specified, default to Goal Lead only.
- When no AGENTS/CLAUDE guidance file exists, use `references/default-AGENTS.md` as default guidance.
- Generated content defaults to Chinese, including docs, code comments, test names, and test case descriptions.
- Member display names are Chinese, such as `后端-接口联调`.
- Create cross-version and version indexes before multiple documents.
- Store process and result documents inside the version directory.
- Complete the Requirement Specification Card before PRD unless the user explicitly skips it.
- Independently validate every generated document, code change, and test case with a separate subagent or user-selected skill.
- Do not let multiple members edit shared core modules concurrently.
- Do not skip applicability checks for Requirement Specification Card, PRD, Architecture Design, HTML Prototype, Test Plan, and Acceptance.
- Do not let the implementer be the only tester.
- Do not allow nested teams; keep `max_depth = 1`.
- Require Goal Lead and user confirmation for auth, payment, refund, migrations, destructive writes, security-sensitive integrations, or broad API changes.

## Release Contents

This repository includes:

- `SKILL.md`: main Goal Teams Skill instructions.
- `agents/openai.yaml`: Codex UI metadata.
- `references/goal-teams-runtime.md`: runtime protocol, templates, CLI examples.
- `references/default-AGENTS.md`: default Chinese AGENTS guidance used when a project has no guidance file.
- `subagents/goal-*.toml`: seven recommended member subagent configs.
- `goal-teams.md`: long-term user-specified requirements for maintaining this Skill.
- `README.md`: Chinese README.
- `README.en.md`: English README.

## License

If this repository is published as open source, add an explicit license such as MIT, Apache-2.0, or an internal sharing agreement.
