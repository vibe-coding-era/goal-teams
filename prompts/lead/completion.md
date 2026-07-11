# Goal Teams Completion

只有满足以下条件，Goal Team 才算完成：

- Done Criteria 已满足。
- 每个认领任务的 `task_state` 都是 `accepted`、`deferred`、`blocked` 或 `cancelled`，且有原因；完成谓词必须重算。
- 每个认领任务都有 Harness 契约、验证证据或不适用说明。
- 每个交接物都有 ledger event，并在 reducer 生成的 TaskList 中包含具体 Owner/Validator、`task_state`、`check_state`、Harness、Evidence 或阻塞/延期原因。
- 每个交接物都有独立检查结果；Owner 不能自我批准。
- 如使用 Benchmark，相关任务的运行记录和失败分类已写入报告或 progress。
- 最终汇报包含每个任务或 subagent 的资源消耗列，格式为 `资源消耗（用户 / tokens / 费用）`；运行时没有返回 tokens 或费用时写 `未提供`。
- 新的 `goal_completion_auditor` 未发现已确认范围内的未完成工作，或剩余工作都有阻塞/延期说明。
- Lead LOOP 最终 `loop_decision` 已记录为 `continue`、`replan` 或 `stop`，并独立记录 `run_outcome` 为 `achieved`、`partial`、`blocked` 或 `aborted`；如果发生自动续跑，`progress.md` 或 `loop-state.json` 已记录轮次、open gaps、Owner、validator、证据和停止边界。
- 必要测试已运行，或说明跳过原因和风险。
- 测试由独立成员、skill 或 subagent 执行，例外必须记录。
- 每个生成文档、代码变更和测试用例都有独立校验证据。
- ledger 已记录具体 Owner/Validator 与最终状态，TaskList 已由 reducer 重建，必要文档已同步。
- Profile 要求的 Requirement Specification Card、PRD、Architecture Design、HTML Prototype、test plan、acceptance、TaskList 已完成；不适用项有结构化原因。
- 输出目录、版本子目录、`index.md` 和 `memory.md` 已更新。
- 后端任务已有 Backend Architecture Design、独立 TDD 单测用例、独立单测执行证据、API 集成测试脚本和执行证据；API 集成测试默认 Python + pytest 或有替代说明。
- 前端任务已有独立 E2E 用例生成和独立 E2E 执行证据。
- 生成 Markdown 产物符合 Google OKF，至少包含可解析 frontmatter 和非空 `type`。
- 阻塞和剩余风险已记录。
- 如使用 runtime 文件，`team-state.json` 反映最终状态。
- V2.34 实现任务已按 contract frozen/reviewed → Architecture accepted → `development_environment_check=ready` → independent tests → implementation 的顺序闭合。
- V2.34 `feature_list.json`、`progress.md`、`contract.md`、`log.md` 的 bundle revision/digest/log commit/checkpoint 一致，无未处理的 journal、混合 revision 或 stale gate。
- V2.34 第 9 轮 reset 只隔离了预授权 disposable candidate，第 11 轮是唯一 achieved/delivery 写入点；任一 gate 缺失时保持未完成且不进入 iteration 12。
- 四维评分各由四个 0.25 rubric item 和独立 Evidence 重算，GTLOG divergence/prompt regression+holdout 和 moving bottleneck 均 current；任何分数不替代测试或审计。
- 只有经审计和 sanitizer 通过的 completed/public 文档进入 `docs/archive/V2.34/<delivery_id>/`；invocation traces 不出现在公开面，完整 ledger/Evidence/review/audit/provenance 保留在非公开记录。
