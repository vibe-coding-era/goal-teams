---
type: Dispatch Protocol
title: Subagent Dispatch Protocol V1.94
description: 定义 Goal Lead 的成员选择、身份命名、transport handle 与降级策略。
tags: [goal-teams, subagent, dispatch, identity]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Subagent Dispatch Protocol V1.94

本协议定义 Goal Lead 如何选择成员、命名成员、处理右边栏英文 transport handle，以及如何在冲突和预算约束下派发任务。

## 派发顺序

1. 用户明确指定的 skill/plugin/subagent。
2. `goal_*` 自定义 subagents。
3. 内置 `team_*` fallback，仅在用户明确要求或 `goal_*` 不可用时使用。

默认不要把 Goal Teams 任务派给内置 `team_reviewer`、`team_qa`、`team_implementer`、`team_researcher`。只有 capability manifest 证明 fallback 能力等价且不扩大权限时才可自动降级；否则进入 blocked 或请求用户。用户可见内容仍使用本地化 `display_name`。

自定义 `goal_*` 不可用但 generic subagent 或串行执行可安全降级时，机器记录固定使用 `dispatch_mode=generic_subagent_or_serial`、`privilege_escalated=false` 并记录 degradation；不得另造近义枚举。

## 命名映射

| 字段 | 规则 |
| --- | --- |
| `agent_type` | 真实可加载配置或 skill，例如 `goal_frontend`、`browser` |
| `agent_run_id` | 每次派发唯一；重试时生成新值并引用 parent attempt |
| `member_id` | 项目内稳定成员 ID，不承担展示或宿主路由 |
| `display_name` | `<中文角色>-<具体任务名>` 或 `<skill 名称>-<具体任务名>` |
| `role` | 中文角色或用户指定 skill 名称 |
| `skill_or_subagent` | `agent_type` 的兼容别名；新机器记录优先使用 `agent_type` |
| `transport_handle` | 运行时可能返回的英文昵称，例如 `Reviewer C`，只能做路由句柄 |

任何用户可见表格、packet、TaskList、state、events、progress、acceptance 和最终总结都不得用 `transport_handle` 替代 display_name；任何独立性检查也不得使用 display_name 或 transport_handle 代替 agent_run_id。

## Member Goal Packet 首段

每个成员包开头必须包含：

```text
你是 Goal Teams 成员：<中文展示名>。
你的 member_id 是：<稳定成员 ID>；本次 agent_run_id 是：<唯一运行 ID>。
你的 display_name 是：<中文展示名>。
如果运行时或右边栏显示英文昵称，只把它当作 transport_handle。
回复首行必须写：成员：<中文展示名>
```

## 交接物派发

- 交接物类型、具体 Owner/Validator identity 和状态字段以 `prompts/packets/handoff-artifacts.md` 为 SSOT。
- Lead 派发前必须在 ledger 中创建或补齐交接物事件，并由 reducer 生成 TaskList 行。
- Lead 派发前必须先在版本子目录建立 ledger，由 reducer 生成 `TaskList.md`，并把 SSOT 产出物放到 `versions/<artifact_version>/`。
- Member Goal Packet 必须包含本成员认领的交接物，每项至少包含 `artifact_type`、具体 Owner/Validator、`task_state`、`check_state`、Harness、Evidence 和 `base_revision`。
- 成员执行过程中只提交 event/patch；只读 reviewer 或 auditor 也返回结构化 review event，由 ledger owner 合并。
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

## V2.35 四专家 Lead-only 派发

仅当结构化 route 将专项标为 required/requested 时加载 `references/rules-specialists.md` 和对应单一成员包。

| 专家 | agent_type | capability | 只读交接物 |
| --- | --- | --- | --- |
| 安全 | `goal_security` | `security_assessment`, `security_proposal` | `security_assessment`、proposal、dispatch request |
| 性能 | `goal_performance` | `performance_benchmark`, `performance_proposal` | `performance_benchmark_proposal`、dispatch request |
| 重构 | `goal_refactor` | `refactor_equivalence`, `refactor_proposal` | `refactor_equivalence_proposal`、dispatch request |
| SQA | `goal_sqa` | `sqa_process_review`, `sqa_archive_proposal` | `sqa_process_archive_proposal`、dispatch request |

四者固定 `sandbox_mode=read-only`、`coordination_depth=1`、`can_spawn_subagents=false`、`can_dispatch=false`、`dispatch_owner_agent_type=goal_lead`、`handoff_mode=proposal_only`。专家只能把 assessment/proposal/task patch/dispatch request 交给 Lead；禁止直接派发、nested team、写产品或中央 TaskList、自我 applied/verified。

Lead 收到 `specialist_dispatch_request` 后校验 proposal hash、scope containment、capability、Budget、Conflict Policy、授权与 review class，再由 ledger owner 创建 task，并派不同实现/测试/validator run。请求本身不是派发或执行 Evidence；违反时返回 `E_V235_SPECIALIST_DISPATCH_FORBIDDEN`。

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
