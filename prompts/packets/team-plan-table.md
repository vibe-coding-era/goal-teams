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
| 成员：后端-WIKI 列表后端开发<br>Skill/Subagent：`goal_backend` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行，前置任务 Backend Architecture Design + TDD 单测用例<br>锁定范围：`src/api/wiki/` | 交接物：后端实现（`backend_implementation`）<br>完成标准：单测和 API 集成测试通过<br>Harness：TDD 单测 + Python/pytest API 集成测试<br>TaskList：Owner=`goal_backend`，状态=`planned` | 测试 Owner：单测执行-WIKI 列表TDD运行；API集成测试-WIKI 列表执行<br>校验者：评审-WIKI 列表代码审查<br>独立检查状态：`not_started` |
| 成员：单测设计-WIKI 列表后端TDD<br>Skill/Subagent：`goal_unit_test_designer` | 目标切片：WIKI 列表 API 单元断言<br>认领任务：GT-003-TDD<br>Workflow：串行，前置任务 Backend Architecture Design<br>锁定范围：`tests/unit/` | 交接物：后端 TDD 单元测试用例（`backend_unit_test_cases`）<br>完成标准：验收标准已转成可执行断言<br>Harness：测试收集/断言审查<br>TaskList：Owner=`goal_unit_test_designer` | 测试 Owner：单测执行-WIKI 列表TDD运行<br>校验者：评审-WIKI 列表测试审查<br>独立检查状态：`not_started` |
| 成员：API集成测试-WIKI 列表脚本生成<br>Skill/Subagent：`goal_api_integration_test_designer` | 目标切片：WIKI 列表 API 集成测试<br>认领任务：GT-003-API<br>Workflow：可并行，前置任务 Backend Architecture Design<br>锁定范围：`tests/api-integration/` | 交接物：API 集成测试脚本（`api_integration_test_script`）和测试矩阵（`api_integration_test_plan`）<br>完成标准：默认 Python + pytest，可运行命令明确<br>Harness：pytest 命令和 fixture 检查 | 测试 Owner：API集成测试-WIKI 列表执行<br>校验者：测试-WIKI 列表验收测试<br>独立检查状态：`not_started` |

风险和审批表：

| 项目 | 风险 | Owner | 是否需审批 | 停止条件 |
| --- | --- | --- | --- | --- |

SPEC 准备度：

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |

Harness 准备度：

| 任务 | Harness 类型 | 检查/命令 | 证据位置 | Owner | 状态 |
| --- | --- | --- | --- | --- | --- |

执行进度：

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |

独立校验：

| 产物 | 作者 | 校验者 | 方法 | 状态 | 证据 |
| --- | --- | --- | --- | --- | --- |

Tasklist 交接物状态：

| 任务 | 交接物 | 类型 | Owner subagent | Validator subagent | 交接状态 | 检查状态 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |

TaskList 必须先创建在版本子目录，例如 `GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md`。每个功能切片至少拆到 `prompts/packets/handoff-artifacts.md` 的 V2.0 最小颗粒度；不适用项写 `not_applicable_reason`。
