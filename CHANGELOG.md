# Changelog

## Unreleased

- Bumped current Skill version to `V1.3` and startup identity to `我是 Goal Teams Leader V1.3，我会帮你完成以下工作：`.
- Added direct-execution trigger wording such as `直接执行`, `不用确认`, and `跳过确认`; the lead still shows the `Teams 规划表` as an execution record, then proceeds without waiting for the initial confirmation unless a safety gate applies.
- Added numbered Plan options so users can reply with simple choices like `1`, `2`, or `3`.
- Added repository-level maintenance guidance in `AGENTS.md`.
- Added `scripts/check.sh` and `scripts/validate.py` for package validation.
- Added `examples/mini-goal-run/` as a minimal Goal Teams output example.
- Documented validation and example workflows in both READMEs.
- Tightened member display names to role + concrete task names, such as `后端-WIKI 列表后端开发`.
- Required a `Teams 规划表` for user confirmation before worker execution.
- Updated the `Teams 规划表` display to four merged columns while preserving the same planning fields.
- Added `goal_completion_auditor` for post-completion unfinished-work audits and automatic continuation cycles inside the confirmed scope.
- Kept License selection pending for the repository owner.
