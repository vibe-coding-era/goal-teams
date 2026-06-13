# GT-BENCH-001：Benchmark 文档模板新增任务

## 任务目的

评估执行者能否在受限范围内新增可复盘 benchmark 文档，并清楚说明如何比较 Goal Teams 与 baseline 的产物质量。该任务关注文档结构、复盘性、评分可操作性和范围遵守，不考察复杂 runner 或自动化实现。

## 被测能力

- 在并发协作背景下严格遵守 locked scope。
- 将模糊目标转成可执行、可评分、可复盘的 benchmark 模板。
- 区分任务模板、执行 harness、评分标准和期望产物。
- 明确哪些同步点应交给 Lead 整合，而不是越界修改根 README、Skill 规则或校验脚本。
- 记录已运行和未运行的校验。

## 统一输入提示

将以下提示作为被测执行者的任务输入。若使用 Goal Teams 模式，Lead 应把它拆成成员目标包；若使用 baseline 模式，单个会话直接执行。

```text
你是 Goal Teams 成员，受 Codex Goal Lead 协调。

成员：文档-V1.7 Benchmark 模板
skill_or_subagent: goal_docs
目标：在 /Users/Rou/dev_projects/goal-teams 中完成 V1.7：新增 benchmark 目录与任务/评分模板，用于评估 Goal Teams 是否真的更好。

规则：
1. 默认中文输出；英文 README 同步建议可返回给 Lead。
2. 你不是独自工作，其他成员会并发改核心规则和 examples；不要回滚他人改动。
3. 锁定范围：benchmarks/。可以创建 benchmarks/README.md、benchmarks/tasks/GT-BENCH-001/ 下的 task.md、harness.md、scoring.md、expected-artifacts.md 等轻量模板。
4. 不新增复杂 runner 或未验证 CLI。只做文档模板和可复盘结构。
5. 需要 README/validate 同步时只报告建议，不要编辑根 README、SKILL.md、runtime、examples。
6. 不运行破坏性命令。

请直接编辑文件。完成后用中文返回：变更文件、benchmark 结构摘要、需要 Lead 整合的校验脚本/README 同步点、未运行/已运行的校验。
```

## 允许范围

- `benchmarks/README.md`
- `benchmarks/tasks/GT-BENCH-001/task.md`
- `benchmarks/tasks/GT-BENCH-001/harness.md`
- `benchmarks/tasks/GT-BENCH-001/scoring.md`
- `benchmarks/tasks/GT-BENCH-001/expected-artifacts.md`
- 同目录下少量补充 Markdown 文件，前提是能解释其复盘价值。

## 禁止范围

- 不修改根目录 `README.md`、`README.en.md`、`SKILL.md`、`goal-teams.md`、`references/goal-teams-runtime.md`、`examples/`、`scripts/`、`subagents/`。
- 不新增 runner、外部依赖、CI 配置或未验证 CLI 示例。
- 不回滚、清理或格式化其他成员已改动的文件。
- 不使用破坏性 Git 命令。

## Done Criteria

- `benchmarks/` 下存在清晰入口 README。
- `GT-BENCH-001` 至少包含任务说明、人工 harness、评分标准和期望产物。
- 评分标准能区分 baseline 与 Goal Teams 的实际优劣，而不是只奖励流程形式。
- 文档说明如何记录耗时、tokens、费用、运行证据和校验结果。
- 最终回复列出变更文件、结构摘要、Lead 整合建议和校验情况。

## 评测注意事项

评分者应优先检查实际 diff 是否只落在允许范围内。若执行者越界修改核心规则或 README，即使文档质量较高，也应在范围遵守项扣分。
