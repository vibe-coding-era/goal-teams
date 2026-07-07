---
type: Handoff Artifacts SSOT
title: Handoff Artifacts SSOT
description: Goal Teams 交接物类型、Owner、独立检查者、状态字段和 tasklist 账本的 Single Source of Truth。
tags: [goal-teams, okf, ssot, handoff-artifacts]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Handoff Artifacts SSOT

本文件是 Goal Teams 交接物的 Single Source of Truth。任何角色 workflow、Member Goal Packet、tasklist、Teams 规划表、test plan、acceptance 或最终汇报提到交接物时，都必须使用这里定义的名称、负责人字段、独立检查字段和状态字段；不要在角色文件里另起一套交接物口径。

## SSOT 规则

- `prompts/packets/handoff-artifacts.md` 定义交接物类型和状态字段。
- `tasklist.md` 是执行中的状态账本，必须逐项记录交接物、Owner subagent、独立检查者、状态和证据路径。
- V2.0 起用户可见状态账本名称为 `TaskList.md`，保留 `tasklist.md` 作为兼容旧名；所有 SSOT 产出物必须写入输出根目录下的版本子目录 `versions/<artifact_version>/`。
- `Member Goal Packet` 是成员执行契约，必须只认领 tasklist 中已有或计划创建的交接物。
- 交接物没有独立检查者、检查状态或证据路径时，不能标记为 `done`。
- 交接物字段变化时，先更新本文件，再同步 workflow、template、README 和 runtime 示例。

## 状态字段

```text
handoff_status:
- planned
- claimed
- in_progress
- ready_for_review
- changes_requested
- checked
- done
- blocked
- deferred

independent_check_status:
- not_started
- running
- passed
- failed
- blocked
- not_applicable
```

## Tasklist 必填字段

```text
Tasklist Handoff Row（tasklist 交接物行）:
- task_id:
- handoff_artifact:
- artifact_type:
- source_ssot: prompts/packets/handoff-artifacts.md
- owner_subagent:
- validator_subagent:
- handoff_status:
- independent_check_status:
- harness_contract:
- evidence_path:
- tasklist_update_owner:
- last_updated:
- blocked_or_deferred_reason:
```

## 交接物类型

| artifact_type | 交接物 | 默认 Owner subagent | 默认独立检查者 | 必须写入 tasklist | 典型证据 |
| --- | --- | --- | --- | --- | --- |
| `tasklist` | TaskList、任务状态账本、交接物账本 | Goal Lead 或 `goal_docs` | `goal_completion_auditor` | 每个项目必须先写入 | `versions/<artifact_version>/TaskList.md`、交接物行完整性检查 |
| `requirement_card` | 需求卡片 | Goal Lead | `goal_reviewer` 或用户确认 | 是 | `spec/requirement-card.md`、确认记录 |
| `requirement_spec_card` | Requirement Specification Card | `goal_requirements_analyst` | `goal_product` 或 `goal_reviewer` | 是 | `spec/requirement-spec-card.md`、结构检查、LLM 复核 |
| `prd` | PRD、用户故事、功能验收标准 | `goal_product` | `goal_reviewer` | 是 | `spec/PRD.md`、溯源检查、评审记录 |
| `page_spec_card` | Page Specification Card、页面规格卡、组件级视觉契约、交互状态矩阵 | `goal_product` 或 `goal_frontend` | `goal_reviewer` 或 `goal_qa` | UI 页面任务必须写入，非 UI 写原因 | `spec/page-spec-card.md`、视觉契约检查、Harness 证据 |
| `backend_architecture_design` | Backend Architecture Design、后端架构设计 | `goal_backend` | `goal_reviewer` | 后端开发前必须写入 | `spec/backend-architecture-design.md`、架构评审、API/数据/权限边界 |
| `frontend_architecture_design` | Frontend Architecture Design、前端架构设计 | `goal_frontend` | `goal_reviewer` 或 `goal_qa` | 前端开发前必须写入或写原因 | `spec/frontend-architecture-design.md`、组件库/状态/路由/数据边界 |
| `architecture_design` | Architecture Design、跨端架构设计 | `goal_backend`、`goal_frontend` 或 `goal_product` | `goal_reviewer` | 涉及架构决策时写入 | `spec/architecture-design.md`、架构评审 |
| `html_prototype` | HTML Prototype | `goal_frontend` | `goal_qa` 或 `goal_reviewer` | 是，界面不适用时写原因 | `spec/HTML-prototype.html`、截图、控制台检查 |
| `frontend_implementation` | 前端开发、页面实现、交互实现 | `goal_frontend` | `goal_qa` 或 `goal_reviewer` | 前端任务必须写入 | diff 摘要、截图、控制台、组件断言 |
| `backend_unit_test_cases` | 后端 TDD 单元测试用例 | `goal_unit_test_designer` | `goal_reviewer` 或 `goal_qa` | 后端开发前必须写入 | 测试文件、预期失败/覆盖说明、断言审查 |
| `backend_implementation` | 后端开发、API/领域/存储实现 | `goal_backend` | `goal_reviewer` | 后端任务必须写入 | diff 摘要、单测和集成测试引用 |
| `backend_unit_test_execution` | 后端执行 TDD、单元测试运行证据 | `goal_unit_test_runner` | `goal_qa` 或 `goal_reviewer` | 后端开发后必须写入 | 测试命令、红/绿记录、失败日志、覆盖结果 |
| `api_integration_test_script` | API 集成测试脚本生成 | `goal_api_integration_test_designer` | `goal_reviewer` 或 `goal_qa` | API 任务必须写入或写原因 | Python/pytest 测试文件、fixture、环境说明 |
| `api_integration_test_plan` | API 集成测试、场景和数据准备 | `goal_api_integration_test_designer` | `goal_qa` | API 任务必须写入或写原因 | 测试矩阵、端点/认证/mock/数据准备 |
| `api_integration_test_execution` | API 集成测试执行 | `goal_api_integration_test_runner` | `goal_qa` 或 `goal_reviewer` | 单元测试通过后必须写入或写阻塞 | pytest 命令、日志、报告、失败截图/响应 |
| `e2e_test_cases` | 生成 E2E 测试用例 | `goal_e2e_test_designer` | `goal_reviewer` 或 `goal_qa` | 前端开发完成后必须写入或写原因 | Playwright/浏览器脚本、路径覆盖、viewport |
| `e2e_test_execution` | 执行 E2E 测试用例 | `goal_e2e_test_runner` | `goal_qa` 或 `goal_reviewer` | E2E 用例生成后必须写入或写阻塞 | 命令、截图、trace、console/network 记录 |
| `bugfix` | BugFix、缺陷修复 | 对应实现 Owner subagent | 发现问题的测试/评审 subagent | 有失败证据时必须写入 | failure_report、修复 diff、回归证据 |
| `test_report` | 测试报告生成 | `goal_qa` 或 `goal_docs` | `goal_completion_auditor` | 收尾前必须写入 | `reports/test-report.md`、覆盖/失败/风险汇总 |
| `harness_contract` | Harness Contract | 认领任务 Owner | `goal_qa` 或 `goal_reviewer` | 是 | Harness 字段、命令、人工检查、失败报告格式 |
| `implementation_change` | 代码或配置变更 | 实现 Owner subagent | `goal_qa` 和/或 `goal_reviewer` | 是 | diff 摘要、测试输出、review 记录 |
| `test_plan` | Test Plan、测试用例、测试说明 | `goal_qa` | `goal_reviewer` | 是 | `spec/test-plan.md`、测试命令、断言审查 |
| `evidence_record` | Evidence、脚本报告、截图、日志 | 测试 Owner 或认领任务 Owner | `goal_reviewer` 或 `goal_completion_auditor` | 是 | `progress.md`、报告路径、截图路径、JSONL |
| `loop_decision_record` | Lead LOOP Decision、Loop Gate、状态快照、续跑决策 | Goal Lead | `goal_completion_auditor` | 长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖任务必须写入 | `progress.md`、`loop-state.json`、续跑 Teams 规划表 |
| `acceptance_record` | Acceptance、验收记录 | `goal_docs` 或 Goal Lead | `goal_reviewer` 或 `goal_completion_auditor` | 是 | `spec/acceptance.md`、验收清单、最终结论 |
| `doc_capsule` | Doc Capsule | 读取文档的成员 | Goal Lead 或下游接收者 | 需要长期复用时写入 | `.codex/goal-teams/doc-capsules.jsonl` |
| `dual_review_record` | Dual Review Record | 执行校验的 QA/reviewer | `goal_completion_auditor` | 对比和校验类任务必须写入 | 脚本复核、LLM 复核、最终决策 |
| `tasklist_update` | tasklist 状态更新 | 当前任务 Owner 或 Goal Lead | `goal_completion_auditor` | 是 | `tasklist.md` 行变更、progress 记录 |

## 交接顺序

1. Goal Lead 在 Plan 阶段把每个交接物写入 `tasklist.md`，至少达到 `planned`。
2. 成员认领任务后，把自己的交接物更新为 `claimed` 或 `in_progress`。
3. 交接物完成初稿或变更后，Owner 更新为 `ready_for_review` 并填入证据路径。
4. 独立检查者完成检查后，更新 `independent_check_status`，并把结论写入证据路径。
5. 只有 `handoff_status` 和 `independent_check_status` 都支持完成结论时，Goal Lead 才能把任务标记为 `done`。

## V2.0 TaskList 最小颗粒度

每个功能切片都必须在版本子目录的 `TaskList.md`/`tasklist.md` 中先拆到以下颗粒度；不适用项必须写 `not_applicable_reason`：

| 顺序 | 功能级任务 | artifact_type | 默认 Owner subagent | 默认前置 |
| --- | --- | --- | --- | --- |
| 1 | 某功能的需求规格卡 | `requirement_spec_card` | `goal_requirements_analyst` | `tasklist` |
| 2 | 某功能的 PRD | `prd` | `goal_product` | `requirement_spec_card` |
| 3 | 某功能的页面规格卡 | `page_spec_card` | `goal_product` 或 `goal_frontend` | `prd` |
| 4 | 某功能的 HTML 原型 | `html_prototype` | `goal_frontend` | `page_spec_card` |
| 5 | 某功能的前端架构设计 | `frontend_architecture_design` | `goal_frontend` | `prd` |
| 6 | 某功能的后端架构设计 | `backend_architecture_design` | `goal_backend` | `prd` |
| 7 | 某功能的前端开发 | `frontend_implementation` | `goal_frontend` | `frontend_architecture_design`、`html_prototype` |
| 8 | 某功能的后端 TDD | `backend_unit_test_cases` | `goal_unit_test_designer` | `backend_architecture_design` |
| 9 | 某功能的后端开发 | `backend_implementation` | `goal_backend` | `backend_unit_test_cases` |
| 10 | 某功能的后端执行 TDD | `backend_unit_test_execution` | `goal_unit_test_runner` | `backend_implementation` |
| 11 | 某功能的 API 集成测试脚本生成 | `api_integration_test_script` | `goal_api_integration_test_designer` | `backend_architecture_design` |
| 12 | 某功能的 API 集成测试 | `api_integration_test_plan` | `goal_api_integration_test_designer` | `api_integration_test_script` |
| 13 | 某功能的 API 集成测试执行 | `api_integration_test_execution` | `goal_api_integration_test_runner` | `backend_unit_test_execution`、`api_integration_test_plan` |
| 14 | 某功能的生成 E2E 测试用例 | `e2e_test_cases` | `goal_e2e_test_designer` | `frontend_implementation` |
| 15 | 某功能的执行 E2E 测试用例 | `e2e_test_execution` | `goal_e2e_test_runner` | `e2e_test_cases` |
| 16 | 某功能的 BugFix | `bugfix` | 对应实现 Owner | 任一失败测试或评审 |
| 17 | 某功能的测试报告生成 | `test_report` | `goal_qa` 或 `goal_docs` | 全部验证项 |
