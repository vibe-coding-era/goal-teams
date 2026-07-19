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
- 后端/前端只闭合 route 命中的门：Full/Regulated 使用完整 Architecture、独立 TDD/API/E2E 链；Standard/Lite 使用影响匹配的环境预检、独立复核和 targeted tests，不生成空仪式任务。
- 生成 Markdown 产物符合 Google OKF，至少包含可解析 frontmatter 和非空 `type`。
- 阻塞和剩余风险已记录。
- 如使用 runtime 文件，`team-state.json` 反映最终状态。
- V2.36 route 已记录 `policy_profile`、派生 `state_gate_profile`、task type、project_size/work_type、risk/release/UI mode；Lite/Standard 只闭合适用门，Full/Regulated 的 Architecture、Environment、独立测试、Evidence 与 Completion Audit 全部闭合。
- 原创 UI 有当前 browser/DOM/可见状态 Evidence 且不要求外部 pixel baseline；replica/reference-driven UI 有独立批准 baseline、环境指纹与像素对比。
- 仅当 `policy_profile=goal-teams-self-release-v2.41`：52 条断言 current，四文件一致，第 9 轮 reset 只隔离预授权 disposable candidate，第 11 轮才 delivery/achieved，四维评分不覆盖测试，并且 sanitizer 后副本只进入 `docs/archive/V2.41/<delivery_id>/`、私有 provenance 完整保留；`goal-teams-self-release-v2.40`、`goal-teams-self-release-v2.39` 与 `goal-teams-self-release-v2.38` 只用于历史 replay。
- V2.41 cache 任务分别记录 structural/host/live/request-hit 四状态轴、route-static identity、manifest status/scope、宿主可用时的 runtime digests、observer parser/identity/coverage 与 raw hash；Tokens/Cache 命中率缺可信 usage Evidence 时写 `未获取到` / `Unavailable`，无授权 live probe 为 `not_authorized`，cache 指标不得替代完成 Evidence。
- V2.36 代码 Evidence 已绑定自动覆盖完整 Git 变更集的 protected snapshot；独立 Agent identity 的宿主 attestation 已验证，trust key 未进入任何产物。
- V2.35 四专家均保持 read-only/proposal-only/Lead-only dispatch；适用 proposal 有独立 review，verified 有不同 run 的 current regression + holdout。
- V2.35 七类适用 test-case 均有 input/processing/expected_output/assertions、非 exit/status 业务断言、observed output 与逐 assertion result；TDD red 先于 implementation，green runner 独立。
- Self-release readiness、branch/main push、local install、post-release task 均已 accepted 后才运行图外 Completion Audit；公开 pre-audit summary 不宣称本次 Audit passed，最终 Audit 不进入 required task/package。
