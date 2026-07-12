---
type: Team Plan Table Template
title: Teams 规划表 OKF 模板
description: Goal Teams 四列表格和确认表模板。
tags: [goal-teams, okf, team-plan]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Team Plan Tables

`Teams 规划表` 四列合并展示格式：

| 成员 / Skill(Subagent) | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Agent type：`goal_backend`<br>Member/Run：`MEMBER-BACKEND-WIKI` / `RUN-BACKEND-WIKI-001` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行，前置任务 Backend Architecture Design + TDD 单测用例<br>锁定范围：`src/api/wiki/` | 交接物：后端实现（`backend_implementation`）<br>完成标准：单测和 API 集成测试通过<br>Harness：TDD 单测 + Python/pytest API 集成测试<br>Ledger：`task_state=planned` | 测试 Owner：单测执行-WIKI 列表TDD运行；API集成测试-WIKI 列表执行<br>Validator run：`RUN-REVIEW-WIKI-CODE-001`<br>`check_state=not_started` |
| 成员：单测设计-WIKI 列表后端TDD<br>Agent type：`goal_unit_test_designer`<br>Member/Run：`MEMBER-TEST-DESIGN-WIKI` / `RUN-TEST-DESIGN-WIKI-001` | 目标切片：WIKI 列表 API 单元断言<br>认领任务：GT-003-TDD<br>Workflow：串行，前置任务 Backend Architecture Design<br>锁定范围：`tests/unit/` | 交接物：后端 TDD 单元测试用例（`backend_unit_test_cases`）<br>完成标准：验收标准已转成可执行断言<br>Harness：测试收集/断言审查<br>Ledger：`task_state=planned` | 测试 Owner：单测执行-WIKI 列表TDD运行<br>Validator run：`RUN-REVIEW-WIKI-TEST-001`<br>`check_state=not_started` |
| 成员：API集成测试-WIKI 列表脚本生成<br>Agent type：`goal_api_integration_test_designer`<br>Member/Run：`MEMBER-API-DESIGN-WIKI` / `RUN-API-DESIGN-WIKI-001` | 目标切片：WIKI 列表 API 集成测试<br>认领任务：GT-003-API<br>Workflow：可并行，前置任务 Backend Architecture Design<br>锁定范围：`tests/api-integration/` | 交接物：API 集成测试脚本（`api_integration_test_script`）和测试矩阵（`api_integration_test_plan`）<br>完成标准：默认 Python + pytest，可运行命令明确<br>Harness：pytest 命令和 fixture 检查 | 测试 Owner：API集成测试-WIKI 列表执行<br>Validator run：`RUN-QA-WIKI-001`<br>`check_state=not_started` |

风险和审批表：

| 项目 | 风险 | Owner | 是否需审批 | 停止条件 |
| --- | --- | --- | --- | --- |

V2.35 路由与专项表：

| project_size | work_type | risk/UI 覆盖 | Gate | 专项 | Lead-only 派发/Validator |
| --- | --- | --- | --- | --- | --- |
| large / medium / small | feature / bugfix | security flags、high/critical、`ui=true` | Architecture、Environment、TDD/integration/E2E/Evidence/release | security / performance / refactor / sqa：required/requested/not_required | 专家仅 proposal；Lead 另派 owner；记录独立 validator run |

V2.36 self-release 默认 Full/Regulated 并加载适用专项；普通 medium/small 按风险和技术面进入 Standard/Lite，可减少不适用的 Architecture、完整 Environment 与独立测试，但 current Evidence、目标验证和安全边界不减。Bugfix 使用影响匹配的 regression/TDD/integration；原创 UI 覆盖受影响 E2E，replica 另强制 pixel comparison。

SPEC 准备度：

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |

Harness 准备度：

| 任务 | Harness 类型 | 检查/命令 | 证据位置 | Owner | 状态 |
| --- | --- | --- | --- | --- | --- |

Lead LOOP 准备度：

| 任务 | 是否触发 Lead LOOP | Loop Gate | 当前轮次 | 停止条件 | 状态 |
| --- | --- | --- | --- | --- | --- |

续跑 Teams 规划表：

| 成员 / Skill(Subagent) | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：<display_name><br>Agent type：`<agent_type>`<br>Run：`<agent_run_id>` | Loop round：<round><br>缺口：<gap><br>来源证据：<source_evidence><br>范围状态：confirmed_scope / new_scope / safety_gate / user_decision<br>锁定范围：<locked_scope> | 预期 Evidence：<expected_evidence><br>Loop Decision：continue / replan / stop<br>Ledger：具体 Owner/Validator identity 已登记 | Validator run：<validator_run_id><br>Harness：<checks/evidence_refs><br>是否需用户确认：true / false |

执行进度：

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |

独立校验：

| 产物 | 作者 | 校验者 | 方法 | 状态 | 证据 |
| --- | --- | --- | --- | --- | --- |

TaskList 投影状态：

| 任务 | 交接物 | 类型 | Owner member/run | Validator member/run | task_state | check_state | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |

先建立 ledger，再由 reducer 在版本子目录生成 `TaskList.md`。Full/Regulated 使用完整交接物颗粒度；Lite/Standard 只生成适用任务，不适用项写结构化 `not_applicable_reason`。
