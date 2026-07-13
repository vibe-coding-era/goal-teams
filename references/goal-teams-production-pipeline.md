---
type: Production Pipeline Protocol
title: Goal Teams Production Pipeline V1.9
description: 定义生产流、Release Gate、观察与回退的协议模板和安全边界。
tags: [goal-teams, production, pipeline, release-gate]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Production Pipeline V1.9

> V2.3 compatibility note：本文件是 V1.9 生产流模板。V2.3 任务状态、检查状态、循环决策和 Evidence 必须通过 V2.3 schema/validator；旧状态只作为 migration 输入，不得成为第二套可写 SSOT。

本文定义 Goal Teams 面向全自动化研发生产流程的协议模板，用于把 `SPEC -> Harness -> Evidence -> Audit` 扩展为可发布、可观察、可回退的生产流。它不表示仓库已经具备真实 runner、CI/CD、生产部署、凭证接入或自动回滚能力。

## 目标

- 定义 `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback` 的 Pipeline Loop。
- 明确每个阶段的输入、动作、输出、证据和停止条件。
- 定义 Release Gate 的审批记录、风险接受和证据链。
- 写清 safety gate：凭证、真实部署、破坏性操作和生产回滚必须人工审批或由外部系统授权。
- 为 V1.8 的机器可读协议预留对齐点，但不新增未验证 runtime 能力。

## 非目标

- 不实现新的 pipeline runner。
- 不接入真实 CI/CD、生产环境、密钥系统、部署平台或回滚平台。
- 不让 Goal Teams 自动执行生产发布、数据迁移、删除、退款、权限变更或安全敏感操作。
- 不把文档门禁等同于真实生产门禁；真实门禁必须由已有外部系统或人工流程授权。

## Pipeline Loop

```text
Input/SPEC
  -> Build
  -> Verify
  -> Package
  -> Release Gate
  -> Observe
  -> Promote/Rollback
  -> Learn / Continue
```

Pipeline Loop 是协议状态流，不是执行引擎。Goal Lead 可以用它组织成员任务、证据、门禁和续跑；真正命令仍来自已存在的 Harness、测试、人工检查或外部系统。

| 阶段 | 输入 | 动作 | 输出 | 证据 | 自动续跑 |
| --- | --- | --- | --- | --- | --- |
| Build | Requirement Specification Card、PRD、Backend/Frontend Architecture Design、TaskList、Member Goal Packet | 成员按 locked_scope 完成实现、文档或模板改动；后端遵循 TDD，前端在实现后进入 E2E 用例生成/执行 | 工作区变更、构建候选说明、变更摘要 | diff、文件清单、成员输出契约、TDD/API/E2E 证据 | 仅限已确认范围内的非敏感修复 |
| Verify | Harness Contract、test-plan、现有测试/人工检查 | 运行或记录可用检查，补齐失败报告 | check_results、failure_report、验证结论 | 命令输出、人工检查清单、截图/日志路径、`progress.md` | 检查失败可续跑；缺凭证或外部授权时阻塞 |
| Package | 通过 Verify 的候选产物 | 汇总 artifact manifest、release notes draft、风险说明、回滚草案 | release_candidate、artifact_manifest、rollback_plan | 变更文件、版本/commit、证据索引 | 包内容缺失可续跑 |
| Release Gate | release_candidate、check_results、风险表、审批要求 | 人工或外部系统判断是否允许发布/推广 | gate_status、approval_record、blockers | 审批人、外部授权引用、风险接受记录 | gate_blocked 不能自动绕过 |
| Observe | 已发布/已合并/已归档候选，或文档态候选 | 收集运行信号、Benchmark 结果、用户反馈、审计结果 | observation_report、regression_flags | 监控链接、CI 结果、Benchmark 报告、审计记录 | 观察到非敏感回归可进入修复 loop |
| Promote/Rollback | Release Gate 和 Observe 结果 | 推广候选、归档版本，或触发回滚计划 | promoted、rolled_back、deferred、blocked | 发布记录、回滚审批、后续任务 | 生产回滚必须人工审批或外部授权 |

## Stage Contract

每个阶段建议记录机器可读状态，字段名可作为 V1.8 协议的扩展输入：

```yaml
pipeline_loop:
  pipeline_id: "GT-V1.9-001"
  release_candidate_id: "rc-YYYYMMDD-N"
  source_version: "V1.9"
  target_environment: "docs-only | staging | production | external"
  current_stage: "build | verify | package | release_gate | observe | promote | rollback"
  stage_status: "pending | running | passed | failed | blocked | skipped"
  evidence_paths: []
  safety_gate:
    credentials_required: false
    real_deployment: false
    destructive_operation: false
    production_rollback: false
    external_authorization_required: false
    approval_status: "not_required | pending | approved | rejected"
  release_gate:
    gate_status: "pending | approved | blocked | rejected"
    approvers: []
    external_authorization_ref: ""
    risk_acceptance: ""
    blockers: []
  observe:
    signals: []
    regression_flags: []
    follow_up_tasks: []
  promote_or_rollback:
    decision: "promote | rollback | defer | block"
    rollback_plan_ref: ""
    executed_by: "human | external_system | not_executed"
```

字段为空不代表通过。无法获得证据时必须写入 `blocked`、`skipped` 或 `not_applicable_reason`。

## Build

Build 阶段把 SPEC 和 tasklist 转成候选产物：

- Goal Lead 确认输出目录、tasklist、Owner、locked_scope 和 Harness Contract。
- 成员只在自己的 locked_scope 内修改文件，并返回变更文件、证据路径和风险。
- Build 输出可以是代码、文档、配置、示例、Benchmark 任务包或 release notes draft。
- Build 失败时记录 `build_failed`，并说明缺失输入、冲突文件或范围问题。

Build 不包含真实部署动作。涉及凭证、生产环境或破坏性命令时，必须在进入动作前停止。

## Verify

Verify 阶段证明候选产物满足 Harness Contract：

- 优先运行已有命令，例如 `./scripts/check.sh`、定向测试、lint、类型检查或文档结构检查。
- 无法运行命令时，记录人工检查清单、跳过原因、风险和下一步。
- Benchmark 可以作为 Verify 输入，但普通任务不默认创建或运行 Benchmark。
- Verify 失败时记录 `verify_failed`，并把失败命令、失败原因、修复建议和重跑要求写入 `failure_report`。

Verify 不得宣称运行了不存在、未授权或不可见的检查。

## Package

Package 阶段把通过验证的候选产物整理成可评审包：

- `artifact_manifest`：变更文件、生成文件、证据路径和版本信息。
- `release_notes_draft`：用户可读的变更摘要、风险和不兼容点。
- `rollback_plan`：如何撤销或降级的人工计划，包含前置条件和审批点。
- `known_limitations`：跳过检查、剩余风险和外部依赖。

Package 只是打包和归档协议，不代表发布已经发生。

## Release Gate

Release Gate 是发布前的决策门。它必须回答：

- 候选产物是否来自已确认范围。
- Verify 证据是否完整、可追溯。
- 风险是否被对应 Owner 接受。
- safety gate 是否触发，触发后是否已有人工审批或外部系统授权。
- Promote 或 Rollback 的执行者是谁，以及是否有明确授权。

建议记录：

```yaml
release_gate:
  gate_status: "pending | approved | blocked | rejected"
  release_candidate_id: ""
  required_checks:
    - name: ""
      status: "passed | failed | skipped | blocked"
      evidence: ""
  required_approvals:
    - scope: "credentials | deployment | destructive_operation | production_rollback | security_sensitive"
      status: "not_required | pending | approved | rejected"
      approver: ""
      external_authorization_ref: ""
  risk_acceptance:
    owner: ""
    summary: ""
    expires_at: ""
  decision_log: ""
```

`gate_status: approved` 只表示协议层允许进入下一步；真实发布仍取决于外部系统权限和人工授权。

V2.36 的 Goal Teams self-release 固定为 Full/Regulated，在进入本门前要求适用 security、performance、refactor、sqa proposal/review 与完整 Evidence gates；专家只读且不能自行派发。普通 medium/small 按 Core V2.5 路由保留 Standard/Lite，Architecture、完整 Environment 与独立测试可按影响减少，但 current Evidence、安全覆盖和适用验证不得减少。

## Safety Gate

以下情况不得由 Goal Teams 自动执行，必须人工审批或外部系统授权：

| 场景 | 风险 | 必需边界 |
| --- | --- | --- |
| 凭证、密钥、token、生产账号 | 泄露或越权 | 不读取、不打印、不生成；由用户或授权系统注入 |
| 真实部署、生产发布、开关切流 | 影响用户或业务 | 需要明确人工发布确认或外部 deployment gate |
| 破坏性操作、数据删除、不可逆迁移 | 数据丢失或服务中断 | 需要备份/演练证据、人工审批和回滚计划 |
| 生产回滚、紧急降级 | 二次故障或数据不一致 | 需要 incident/change 系统授权或人工指令 |
| auth、payment、refund、权限、安全敏感模块 | 安全和合规风险 | 需要 Lead 升级审批、独立安全/业务校验 |

触发 safety gate 时，自动续跑只能继续做文档、测试或准备性修复；不能绕过审批进入真实操作。

## Observe

Observe 阶段收集发布后或候选归档后的信号：

- 文档/skill 仓库场景：`./scripts/check.sh`、`git diff --check`、独立评审、收尾审计、Benchmark 报告、用户反馈。
- 软件项目场景：已有 CI、监控、日志、错误率、性能、SLO、工单、用户反馈。
- 若没有真实部署，只记录文档态观察结果，不伪造生产 telemetry。

观察到问题时写入 `observation_report` 和 `regression_flags`，再由 Lead 判断是否进入已确认范围内的续跑，或因新范围/高风险转为阻塞。

## Promote / Rollback

Promote 是把候选产物推广为发布、归档或推荐版本；Rollback 是按回滚计划撤销或降级。二者都必须依赖 Release Gate 和 Observe 证据。

| 决策 | 允许条件 | 禁止条件 | 输出 |
| --- | --- | --- | --- |
| promote | Release Gate approved，观察无阻断，风险已接受 | 缺少必要审批、证据不完整、触发未处理 safety gate | 发布记录、版本归档、后续观察任务 |
| rollback | 回滚计划存在，人工或外部系统授权，风险已记录 | 生产回滚未授权、回滚影响未知、缺少负责人 | 回滚记录、验证计划、事故/问题链接 |
| defer | 风险可接受但不适合当前发布窗口 | 被当作通过发布 | 延期原因、下一次 gate 条件 |
| block | 安全、凭证、破坏性或生产边界未满足 | 自动绕过 | 阻塞原因、所需审批、Owner |

Goal Teams 可以生成 rollback_plan 和检查清单；不能宣称已经执行生产回滚，除非外部授权系统或人工执行证据已提供。

## Failure Taxonomy

| 分类 | 含义 | 处理 |
| --- | --- | --- |
| `build_failed` | 候选产物未生成或范围冲突 | 成员修复或 Lead 重新规划 |
| `verify_failed` | Harness 检查失败 | 修复后重跑 Verify |
| `package_incomplete` | manifest、release notes 或 rollback_plan 缺失 | 补包后重新 gate |
| `gate_blocked` | Release Gate 缺审批或风险未接受 | 停止并请求人工/外部授权 |
| `observe_regression` | Observe 发现回归或证据异常 | 进入修复 loop 或触发回滚审批 |
| `promote_rejected` | 发布候选被拒绝 | 记录原因，返回 Build 或延期 |
| `rollback_required_manual` | 需要生产回滚但缺授权 | 停止，等待人工或外部系统 |

## 与 Goal Teams 运行时的关系

- `plan.md`：记录 Pipeline Loop 是否适用、阶段 Owner 和审批边界。
- ledger / `TaskList.md`：成员提交 event，reducer 生成版本目录 TaskList；`tasklist.md` 只作为 legacy 输入。每个任务写明 Harness、Evidence 和 safety gate。
- `progress.md`：记录阶段状态、命令结果、失败报告和人工审批证据。
- `acceptance.md`：汇总 Release Gate、Observe、Promote/Rollback 的验收结果。
- `decisions.md`：记录人工决策、风险接受和外部授权引用。

V2.35 发布闭环按顺序记录：release-readiness accepted → release branch/main fast-forward push Evidence → 本地安装 VERSION/tree/full-check Evidence → 独立 post-release task accepted → graph-external Completion Audit。公开 `docs/v2.35-release-summary*.md` 是 Audit 前候选说明，必须声明 Audit 尚未运行/待运行；最终 Audit 保留在私有过程 bundle，不进入 package。

V1.9 只定义生产流水线协议和门禁模板。若后续要接入真实 runner、CI/CD 或部署系统，需要新的版本目标、明确授权、独立安全评审和校验脚本支持。
