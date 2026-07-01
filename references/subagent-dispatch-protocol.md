# Subagent Dispatch Protocol V1.94

本协议定义 Goal Lead 如何选择成员、命名成员、处理右边栏英文 transport handle，以及如何在冲突和预算约束下派发任务。

## 派发顺序

1. 用户明确指定的 skill/plugin/subagent。
2. `goal_*` 自定义 subagents。
3. 内置 `team_*` fallback，仅在用户明确要求或 `goal_*` 不可用时使用。

默认不要把 Goal Teams 任务派给内置 `team_reviewer`、`team_qa`、`team_implementer`、`team_researcher`。如果必须使用，用户可见 `member_id` 和 `display_name` 仍使用中文任务名。

## 命名映射

| 字段 | 规则 |
| --- | --- |
| `member_id` | `<中文角色>-<具体任务名>` 或 `<skill 名称>-<具体任务名>` |
| `display_name` | 与 `member_id` 完全一致 |
| `role` | 中文角色或用户指定 skill 名称 |
| `skill_or_subagent` | 真实可加载名称，例如 `goal_frontend`、`browser` |
| `transport_handle` | 运行时可能返回的英文昵称，例如 `Reviewer C`，只能做路由句柄 |

任何用户可见表格、packet、tasklist、state、events、progress、acceptance 和最终总结都不得用 `transport_handle` 替代中文展示名。

## Member Goal Packet 首段

每个成员包开头必须包含：

```text
你是 Goal Teams 成员：<中文展示名>。
你的 member_id 和 display_name 都是：<中文展示名>。
如果运行时或右边栏显示英文昵称，只把它当作 transport_handle。
回复首行必须写：成员：<中文展示名>
```

## 交接物派发

- 交接物类型、Owner subagent、validator subagent 和状态字段以 `prompts/packets/handoff-artifacts.md` 为 SSOT。
- Lead 派发前必须在 tasklist 中创建或补齐交接物行。
- V2.0 起 Lead 派发前必须先创建版本子目录 `TaskList.md`，并把 SSOT 产出物放到 `versions/<artifact_version>/`。
- Member Goal Packet 必须包含本成员认领的 `handoff_artifacts`，每项至少包含 `artifact_type`、`owner_subagent`、`validator_subagent`、`handoff_status`、`independent_check_status`、Harness 和证据路径。
- 成员执行过程中必须更新 tasklist 中自己负责的交接物状态；只读 reviewer 或 auditor 返回状态更新建议，由 Lead 或 tasklist Owner 写入。
- 每个交接物必须由独立成员、skill 或 subagent 检查；Owner 不能自我批准。

## V2.0 默认测试派发

| 场景 | 默认 subagent | 交接物 | 派发时机 |
| --- | --- | --- | --- |
| 后端架构设计 | `goal_backend` | `backend_architecture_design` | PRD 后、后端开发前 |
| 后端 TDD 单元测试用例 | `goal_unit_test_designer` | `backend_unit_test_cases` | Backend Architecture Design 后、后端实现前 |
| 后端实现 | `goal_backend` | `backend_implementation` | TDD 单元测试用例 ready 后 |
| 后端单元测试执行 | `goal_unit_test_runner` | `backend_unit_test_execution` | 后端实现后 |
| API 集成测试脚本/计划 | `goal_api_integration_test_designer` | `api_integration_test_script`, `api_integration_test_plan` | Backend Architecture Design 后可并行 |
| API 集成测试执行 | `goal_api_integration_test_runner` | `api_integration_test_execution` | 单元测试通过后 |
| 前端 E2E 用例 | `goal_e2e_test_designer` | `e2e_test_cases` | 前端开发完成后 |
| 前端 E2E 执行 | `goal_e2e_test_runner` | `e2e_test_execution` | E2E 用例 ready 后 |

单元测试作者、后端实现者和单元测试执行者不能是同一唯一 subagent。E2E 用例作者和 E2E 执行者也必须分离。API 集成测试默认 Python + pytest；项目另有规范时必须写明依据。

## 并发冲突

- 同一 `locked_scope` 只有一个写 Owner。
- 共享核心模块默认串行。
- 只读评审、QA、文档可以并行，但不能修改实现文件。
- 发现同文件并发写入时，后启动成员暂停并报告 Lead。
- Lead 指定 `merge_owner` 后才允许合并。

## 预算约束

Plan 中出现以下任一条件时必须写 Budget Gate：

- 预计超过 4 个 subagents。
- 需要自动续跑。
- 涉及生产流、Benchmark、浏览器 E2E 或像素对比。
- 用户给出时间、tokens 或费用限制。

Budget Gate 超限时，Lead 必须优先保留安全、正确性和证据完整度，缩减非必要文档或延后新范围。
