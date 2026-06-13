# Changelog

## Unreleased

- Bumped current Skill version to `V1.9` and startup identity to `我是 Goal Teams Leader V1.9，我会帮你完成以下工作：`.
- Added V1.8 machine-readable automation protocol reference with `harness.yaml`, `evidence.jsonl`, `pipeline-state.json`, `failure_report`, and `approval_gate` templates.
- Added V1.9 production pipeline reference for `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`, including Release Gate and safety gate boundaries.
- Added mini-goal-run static samples for automation protocol, evidence ledger, and pipeline gates.
- Added `GT-BENCH-002` benchmark templates for production-flow gate packages, evidence completeness, auto-continuation, and safety boundaries.
- Extended `scripts/validate.py` to check V1.9, V1.8/V1.9 references, mini machine-readable samples, and `GT-BENCH-002`.
- Bumped current Skill version to `V1.7` and startup identity to `我是 Goal Teams Leader V1.7，我会帮你完成以下工作：`.
- Added V1.5 Harness and Loop rules: `SPEC` defines completion, `Harness Contract` defines verification, evidence is required before done, and Goal Teams now documents member, Lead, and Skill Improvement loops.
- Added V1.6 mini Harness replay artifacts under `examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/` with `setup -> run -> checks -> report`.
- Added V1.7 `benchmarks/` templates, including `GT-BENCH-001` task, manual harness, scoring rubric, and expected artifacts for comparing baseline vs Goal Teams.
- Extended `scripts/validate.py` to check V1.7, Harness example files, and benchmark templates.
- Bumped current Skill version to `V1.4` and startup identity to `我是 Goal Teams Leader V1.4，我会帮你完成以下工作：`.
- Added a Plan Mode startup clarification asking whether the user has historical documents, prior experience, or reference material to provide before planning.
- Added direct-execution trigger wording such as `直接执行`, `不用确认`, and `跳过确认`; the lead still shows the `Teams 规划表` as an execution record, then proceeds without waiting for the initial confirmation unless a safety gate applies.
- Added numbered Plan options so users can reply with simple choices like `1`, `2`, or `3`.
- Added repository-level maintenance guidance in `AGENTS.md`.
- Added `scripts/check.sh` and `scripts/validate.py` for package validation.
- Added `examples/mini-goal-run/` as a minimal Goal Teams output example.
- Documented validation and example workflows in both READMEs.
- Updated runtime subagent id, `member_id`, and display names to Chinese role + concrete task names, such as `后端-WIKI 列表后端开发`; when a user assigns a skill, the skill name is used, such as `browser-WIKI 列表页面验证`.
- Kept loadable technical subagent names such as `goal_backend` only in `skill_or_subagent`.
- Required task workflow safety fields in planning tables: serial/parallel workflow and predecessor tasks.
- Required final status tables to include `资源消耗（用户 / tokens / 费用）` for each task or subagent, using `未提供` when runtime usage is unavailable.
- Consolidated Chinese-output behavior into one core model prompt.
- Required a `Teams 规划表` for user confirmation before worker execution.
- Updated the `Teams 规划表` display to four merged columns while preserving the same planning fields.
- Added `goal_completion_auditor` for post-completion unfinished-work audits and automatic continuation cycles inside the confirmed scope.
- Kept License selection pending for the repository owner.
