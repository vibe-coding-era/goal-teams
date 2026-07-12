# Goal Teams Plan

## 用户目标

为“登录页空状态提示 V0.1”提供静态文档、HTML 原型和最小 Harness 结构示例，不修改业务代码。

## 启动汇报

我是 Goal Teams Lead V2.37。

- 检查示例项目执行规则和版本目录。
- 记录正交路由：`project_size=small`、`work_type=feature`、`ui=true`。
- Architecture、Environment、独立测试、Evidence 和 E2E 仍为 required；`sample_only` / `no_runner` 不豁免门禁。
- 现有静态产物可作为结构示例，但项目整体保持 blocked。

## 历史资料输入

本示例的目标、边界和参考输入已经完整；缺少额外历史资料不会改变执行，因此不再询问。

| 项目 | 记录 |
| --- | --- |
| 历史资料 | 示例未提供；不影响当前判定 |

## 门禁现状

| 门 | 状态 | 证据/缺口 |
| --- | --- | --- |
| Requirement / PRD | passed | `spec/requirement-card.md`、`spec/requirement-spec-card.md`、`spec/PRD.md` |
| Architecture acceptance | blocked | `spec/architecture-design.md` 存在，但缺独立 accepted Evidence |
| Development Environment Check | blocked | 尚无 Architecture-hash-bound `development_environment_check` 与 `ready` Evidence |
| HTML prototype | blocked | 文件存在，但不得绕过上游门禁 |
| Independent E2E | blocked | 缺四段用例 contract、browser runner、screenshot/trace/assertion Evidence |
| Completion Audit | not_started | required task 未全部 accepted；审计保持在任务图外 |

## 需求卡片

| 项目 | 记录 |
| --- | --- |
| 文档路径 | `spec/requirement-card.md` |
| 核心目标 | 展示登录页空状态的文档与 HTML 结构 |
| 关键功能 | 文案与触发场景、SPEC、原型、测试计划、验收、Harness 静态样例 |
| 用户故事 | US-001 未登录用户看到空状态；US-002 新用户看到注册或支持入口 |
| 功能验收标准 | AC-001 标题和说明；AC-002 登录主按钮；AC-003 次操作；AC-004 无真实认证调用 |
| 边界 | 不修改业务代码、不实现真实登录、不部署 |
| 约束 | 无真实 runner；不得把静态样例写成 E2E Evidence |
| 风险 | Architecture、Environment 和 E2E 未闭合，整体必须 blocked |

## Teams 规划表

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 需求分析 / `goal_requirements_analyst` | GT-001；串行；前置 -；`spec/` | 需求规格卡；当前 done | `goal_reviewer` 独立结构校验 |
| 产品 / `goal_product` | GT-002；串行；前置 GT-001；`spec/` | PRD；当前 done | `goal_reviewer` 独立溯源校验 |
| 架构 / `goal_backend` | GT-011；串行；前置 GT-002；`spec/architecture-design.md` | Architecture accepted Evidence；当前 blocked | 独立 `goal_reviewer`；作者不得自验 |
| 环境 / `goal_backend` | GT-012；串行；前置 GT-011；`spec/development-environment-check.md` | Architecture-bound `ready` Evidence；当前 blocked | 独立 `goal_qa` |
| 前端 / `goal_frontend` | GT-003；串行；前置 GT-012；`spec/HTML-prototype.html` | 现有原型不代表 gate accepted；blocked | `goal_reviewer` |
| E2E 用例 / `goal_e2e_test_designer` | GT-009；串行；前置 GT-003；`spec/e2e-test-cases.json` | 四段用例 contract；blocked | 独立 `goal_reviewer` |
| E2E 执行 / `goal_e2e_test_runner` | GT-010；串行；前置 GT-009；read-only | browser Evidence；blocked | 独立 `goal_reviewer` |
| QA / `goal_qa` | GT-004；串行；前置 GT-010；`spec/test-plan.md` | 整体测试结论；blocked | 独立 `goal_reviewer` |
| 文档 / `goal_docs` | GT-005、GT-006；串行；前置 GT-004 | acceptance + Harness；blocked | 独立 `goal_reviewer` |
| 评审 / `goal_reviewer` | GT-007；串行；前置 GT-011、GT-012、GT-003、GT-009、GT-010、GT-004、GT-005、GT-006；read-only | 完整性评审；blocked | 不适用（只读评审本身不自证完成） |

## 图外 Completion Audit

- 审计标识：`AUD-V0.1-001`。
- 历史标签 `GT-008` 已从 required/blocking 任务图移除，只作为兼容引用。
- `audit_state=not_started`；required tasks 未 accepted，不派发 `goal_completion_auditor`。

## 风险与审批

| 项目 | 风险 | Owner | 停止条件 |
| --- | --- | --- | --- |
| 业务代码 | 示例误改实现 | Goal Lead | 出现业务代码改动 |
| 完成声明 | 静态样例被误写成 accepted/achieved | `goal_reviewer` | Architecture/Environment/E2E Evidence 缺失 |
