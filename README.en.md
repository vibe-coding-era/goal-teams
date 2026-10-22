English | [中文](README.md)

# Goal Teams

Author: 肉山@TGO Hangzhou

<!-- goal-teams-release:start -->
Current version: **V2.95** · [GitHub Release](https://github.com/vibe-coding-era/goal-teams/releases/tag/v2.95.0) · [Changelog](CHANGELOG.md)
<!-- goal-teams-release:end -->

Goal Teams is a team-delivery Skill for Codex and Claude Code. A Goal Lead turns your goal into verifiable tasks, then coordinates `goal_*` member subagents through requirements, implementation, testing, review and release. The `gt` command-line tool keeps the books, so every number in a report comes from a real record.

- **Process scales with the work.**
  - Questions get a direct answer.
  - Small fixes take the fast path: Red, then Green, then a summary.
  - Only medium and large goals get a ledger, tasks and members.
- **Evidence first.**
  - TDD Red and Green run the same command against the same test-file digest, and the source content must actually change between them (a commit alone does not count).
  - Every code task needs a passing test run on the final code (a manual note does not count); `gt rerun` repeats them all at the end.
  - Git collects the real changes, which are compared with the union of the tasks' locked scopes.
  - A review is bound to file digests and becomes stale when those files change.
- **Honest states.** not_run, blocked and failed are never written as passed. A goal is "achieved" only when `gt check` passes.
- **Independent validation.** The validator is never the owner. In Claude Code, read-only and runner members have no Write/Edit tools, and no member can spawn subagents.
- **One-time authorization.** External writes (push, PR, release, deploy) are confirmed once at the start. Irreversible actions get a one-line preview first.

## Quick start

### Claude Code (plugin)

```text
/plugin marketplace add vibe-coding-era/goal-teams
/plugin install goal-teams@goal-teams
```

On Claude Code 2.1.275 or later you can do this in one step: `/plugin install goal-teams --marketplace vibe-coding-era/goal-teams`.

### Codex

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/src/goal-teams   # not inside a skills folder
cd ~/src/goal-teams
python3 tools/install.py --host codex
```

The installer:
- installs the skill to `~/.agents/skills/goal-teams` (Codex's current user skills folder) and the members to `~/.codex/agents/goal_*.toml`;
- moves any older install into a backup first, including the old V2 location `~/.codex/skills/goal-teams`, so Codex never sees two copies;
- supports `--verify`, `--rollback` and `--uninstall`.

To update later, run `git pull && python3 tools/install.py --host codex` and start a new session. On Windows, use `py -3 tools\install.py --host codex`.

Claude Code users who prefer not to use the plugin can run it with `--host claude`. Use either the plugin or the installer, not both. The plugin's Stop hook needs `python3` or `python` on PATH. Upgrading from V2.x? See [MIGRATION.md](MIGRATION.md).

### Requirements

- Python 3.9+ (gt uses only the standard library).
- git is optional; without it, `gt diff` is unavailable.

## Usage

Describe your goal. The Goal Lead first decides its size:

```text
What is the difference between a Python list and a tuple?      → discussion: answer directly
slugify("Hello World") leaves a trailing dash, please fix it   → small: Red → Green → summary
Use goal teams to add coupons to the order service             → medium: goal, tasks, members, gt report each round
Plan only, no code: write a requirement card for memberships   → plan only: requirement card and plan in the reply
Release v1.2: tag, push and create a GitHub Release            → one-time authorization, then the release rules with readback
```

At the end of each medium or large round, the Lead runs `gt report` and sends you its output unchanged. The report has six fields: Task, Members, Progress, Result, Benchmark, and Next LOOP (or Next task). Result contains the task board, the Context table and the four P/D/C/A lines. Real outputs are in [examples/](examples/). Field names follow the project locale (`zh` by default, `--lang en` for English).

## How it works

| Size | When | Rules the Lead reads | State |
|---|---|---|---|
| discussion | questions, explanations, proposals | SKILL.md | none |
| small | one goal, low coupling, reversible | + core, testing (≈6K tokens in total) | none |
| medium | several files or components | + planning, members, output (≈12K tokens in total) | `.goal-teams/` |
| large | cross-module, migrations, high impact | same as medium, plus a completion audit | `.goal-teams/` |
| plan only | plan only, Plan Mode, requirement cards | + planning and the matching template | none |

Token counts are `tools/check.py` estimates (close to the estimate Claude Code shows). UI work adds `rules/ui.md`, Agent/LLM products add `rules/agent-dev.md`, and releases add `rules/release.md`.

Small work escalates to medium when any of these apply:
- more than 3 files change;
- a public API or a migration is involved;
- auth, payments or personal data are involved;
- there are external writes;
- UI visuals change;
- the user asks for a plan or a team.

### gt at a glance

```text
gt init / goal / route / doctor                            state, goal, route, environment preflight
gt auth grant / check                                      one-time authorization, pre-action check
gt task add / start / done / block / packet                tasks, blockers, packets for subagents
gt plan freeze / show                                      dependency graph, layers, critical path
gt tdd red / green                                         Red/Green evidence (Green re-runs Red's command)
gt run --kind affected|regression|e2e|security|build|...   check evidence (--artifact records build outputs)
gt rerun / retire                                          re-run tests on the final code / withdraw a mistaken failure
gt diff                                                    real changes vs locked scope
gt review                                                  review verdicts (from the task's validator)
gt loop decide · gt reflect                                round decisions · reflections
gt status / report / check                                 board, six-field report, completion check
gt config / verify                                         project conventions, ledger verification
```

Everything lives in the project's `.goal-teams/` directory:
- `ledger.jsonl`: an append-only, hash-chained ledger; `ledger.head` records the chain head so a truncated ledger is detected;
- `TaskList.md` and `benchmark.md`: generated from the ledger;
- `memory.md`: project memory;
- `loop-review.md`: reflections.

### Members

There are 20 members, each in one of three modes:

| Mode | Can | Members |
|---|---|---|
| write | edit files inside the locked scope | requirements, product, agent product, backend, frontend, test designers (unit/API/E2E), docs |
| runner | run commands and record evidence only | test runners (unit/API/E2E), QA, release engineer |
| read-only | read and return a verdict | reviewer, completion auditor, security, performance, refactor, SQA |

The full list with dispatch guidance is in [rules/members.md](plugins/goal-teams/skills/goal-teams/rules/members.md). The single source is [members/](members/); both the Codex TOML files and the Claude Code subagents are generated from it.

## Evals

[plugins/goal-teams/evals/](plugins/goal-teams/evals/) holds six `claude plugin eval` cases that compare runs with and without the skill: a discussion question, a small bugfix, a medium feature, an API defect hunt, an unauthorized release request and a plan-only request. Check the evals before keeping a rule change.

## Layout

```text
.claude-plugin/marketplace.json   Claude Code marketplace
plugins/goal-teams/               runtime package (skill, rules, templates, gt, members, hook, evals)
members/                          member single source
tools/                            generate, check, install, release, examples
tests/  examples/  extras/okf-graph/
```

## Contributing

See [AGENTS.md](AGENTS.md). Before committing, run:

```bash
python3 tools/check.py && python3 -m unittest discover -s tests -t .
```

## Design references

| Principle | Source |
|---|---|
| Skill structure, progressive loading, concision, "Solve, don't defer", eval-driven development | [Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) |
| Codex skills and trigger-oriented descriptions | [OpenAI Codex Agent Skills](https://developers.openai.com/codex/skills) |
| Claude Code plugins, subagent tool limits, hooks, plugin evals | [Plugins](https://code.claude.com/docs/en/plugins), [Subagents](https://code.claude.com/docs/en/sub-agents), [Hooks](https://code.claude.com/docs/en/hooks), [Plugin evals](https://code.claude.com/docs/en/plugin-evals) |
| TDD | [Martin Fowler: Test-Driven Development](https://martinfowler.com/bliki/TestDrivenDevelopment.html) |
| E2E and screenshot assertions | [Playwright](https://playwright.dev/docs/test-snapshots) |

## License

MIT, see [LICENSE](LICENSE).
