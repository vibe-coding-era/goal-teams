---
type: Goal Teams Runtime Reference Part
title: Harness、Benchmark 与 Loop 契约
description: Goal Teams runtime 渐进式分片。
tags: [goal-teams, runtime, progressive-loading]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# Harness、Benchmark 与 Loop 契约

## Harness、Benchmark 与 Loop 契约

Goal Teams 使用 `SPEC -> Harness -> Evidence -> Audit` 作为验证链。这里的 `Harness` 是验证契约和模板字段，不是新的 runtime 执行器；它可以指向已有命令、计划中要创建的测试、人工检查清单、截图、日志、CI 结果或外部评估脚本，但不能宣称会运行未验证、未授权或不存在的能力。

定义：

| 概念 | 含义 | Goal Teams 产物 |
| --- | --- | --- |
| `SPEC` | 定义什么算完成 | Requirement Specification Card、PRD、Architecture Design、test plan、acceptance、tasklist |
| `Harness` | 定义怎么证明完成 | Plan、tasklist、Member Goal Packet、test plan、acceptance 中的验证契约 |
| `Evidence` | 记录可追溯事实；仅 current local_verified 成功执行有 acceptance 资格 | `evidence/evidence.jsonl`、`progress.md`、`acceptance.md`、命令/截图/人工/外部来源记录 |
| `Pipeline` | 记录研发/发布状态；不替代 V2.3 completion | V1.8 `pipeline-state.json`、Release Gate、Observe、Promote/Rollback 记录 |
| `Benchmark` | 在多任务上评估工作流是否稳定 | `benchmarks/` 任务集、run matrix、scorecard、failure taxonomy |
| `Loop` | 持续推进和改进机制 | 成员 Loop、Lead Loop、Skill Improvement Loop |

Harness Contract 模板：

```text
Harness Contract（验证契约）:
- purpose:
- checks:
- commands:
- artifact_checks:
- e2e_checks:
- pixel_diff_checks:
- evidence_paths:
- failure_report:
  - command:
  - failing_check:
  - likely_cause:
  - next_verification:
- not_applicable_reason:
```

Harness 准备度表：

| 任务 | Harness 类型 | 检查/命令 | 证据位置 | Owner | 状态 |
| --- | --- | --- | --- | --- | --- |
| GT-003 | automated + manual | `npm test -- wiki` + API 合同检查 | `progress.md` / CI 输出 | 测试-WIKI 列表验收测试 | planned |

按任务类型选择 Harness：

| 任务类型 | 常见 Harness |
| --- | --- |
| 前端 / 界面级任务 | 必须包含 E2E；通常使用 Playwright、截图、console error、桌面/移动 viewport、文本溢出或遮挡检查 |
| 复刻 / 还原界面 | 必须截图做像素级对比；记录基准图、实际图、diff 图或差异指标、阈值、viewport 和结论 |
| UI 视觉防漏 | 必须包含页面规格卡、组件级视觉契约、交互状态矩阵、locked/unlocked 截图、局部 crop 或几何断言 |
| 后端 | API 边界、权限、异常路径、数据兼容性、迁移/回滚检查 |
| 文档 | 结构完整性、链接、术语、版本一致性、README/CHANGELOG 同步检查 |
| 测试用例 | 断言有效性、失败模式覆盖、fixture 可复现、不会只验证 happy path |
| 评审/审计 | diff 审查、tasklist 状态、acceptance 证据、阻塞/风险清单 |

规则：

- 启动实现成员前，Plan 或 tasklist 必须给每个认领任务写出 Harness Contract；不适用时写 `not_applicable_reason`。
- 任何界面级任务都必须做 E2E；不能运行时保持 blocked，不得用 waiver 获得 accepted。
- 复刻、临摹、还原、对照参考图/参考页面的任务必须截图做像素级对比；缺参考/截图/diff 能力时保持 blocked。只有用户明确把范围改为非 UI/`sample_only`，才可建立 `required=false`、`acceptance_blocking=false` 的 `not_required` Check。
- UI E2E 和像素级对比细则见 `references/ui-e2e-pixel-protocol.md`；UI 复刻防漏、视觉锁层、组件级视觉契约和交互状态矩阵见 `references/ui-visual-contract-protocol.md`。使用 `scripts/harness/pixel-diff.py --ui-mode original|replica`；replica 自动强制 baseline/actual environment 与独立 baseline approval，缺失时 fail-closed。
- 整页 diff 不能覆盖小组件缺陷时，必须增加局部 crop 或几何断言；pixel threshold 不能在失败后为了通过而放宽。
- 默认主截图若来自 overlay、视觉锁层或截图遮挡层，必须额外采集 unlocked real DOM screenshot。
- 弹窗和表单类组件必须有打开态和错误态截图；弹窗还应覆盖切换态、关闭态和移动端态。
- Harness contract 可用 `scripts/harness/validate-harness.py` 或兼容入口 `scripts/validate-harness.py` 检查结构；检查通过只代表字段完整，不代表真实测试已经运行。
- 成员完成时必须返回 Harness Evidence 或结构化跳过原因；只有 ledger owner 和独立 Validator 都能追溯当前证据时，任务才可标记为 `accepted`。
- 证据不足不能完成。缺少 E2E、缺少像素 diff、只有实现者自测、缺少独立校验或生产流缺少审批/回滚/监控 Evidence 时，必须打回并记录 `failure_report` 与单一 `check_state`：已运行失败为 `failed`，无法执行为 `blocked`；不得输出 `run_outcome=achieved`。
- 失败时按 Harness Contract 的 `failure_report` 格式报告，不用笼统写“测试失败”。
- Harness 可以成为 Benchmark 的一部分，但普通 Goal Teams 任务不自动创建 benchmark。

机器可读协议是 V1.8 的可选数据合同，详见 `references/goal-teams-automation-protocol.md`。它不代表已有 runner、CI/CD、生产接入或真实外部审批系统。

| Artifact | 作用 | 建议位置 |
| --- | --- | --- |
| `harness.yaml` | 单任务或单版本的验证契约 | `GoalTeamsWork-<project_version>/versions/<artifact_version>/harness.yaml` |
| `evidence.jsonl` | 追加式证据日志 | `GoalTeamsWork-<project_version>/versions/<artifact_version>/evidence.jsonl` |
| `pipeline-state.json` | 研发/门禁状态快照 | `GoalTeamsWork-<project_version>/versions/<artifact_version>/pipeline-state.json` |
| `failure_report` | 失败对象 | 嵌入 evidence 或 pipeline 状态 |
| `approval_gate` | 人工或策略审批门对象 | 嵌入 pipeline 状态 |

生产流协议是 V1.9 的发布门禁模板，详见 `references/goal-teams-production-pipeline.md`。它使用 `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback` 组织候选产物、证据和审批。凭证、真实部署、破坏性操作、生产回滚、auth/payment/refund/权限和安全敏感模块必须人工审批或由外部系统授权；Goal Teams 不能自动绕过这些 safety gate。

Benchmark 是外层评估目录与任务集，用于比较 Goal Teams、single agent、不同 skill 版本或 prompt 的稳定性。默认目录建议：

```text
benchmarks/
  README.md
  tasks/
    GT-BENCH-001/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
    GT-BENCH-002/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
  runs/
    <date>-<task>-<mode>/
      report.md
      artifacts/
```

Benchmark 任务包最少包含：

- `task.md` 或 `SPEC.md`：目标、成功标准、非目标、禁止行为、可见/隐藏验收。
- Harness：环境准备、可见测试、评分/检查、日志和证据收集。
- `scoring.md`：分值、严重度、失败分类、人工介入记录和成本指标。
- metadata（可选）：任务类型、难度、允许工具、时间/token/费用预算、基线信息。
- 运行记录：模型/skill/prompt 版本、项目 commit、工具版本、联网/权限、运行日期、结果。
- 失败分类：需求误解、上下文没读全、定位失败、工具失败、环境失败、实现错误、测试不足、过度修改、引入回归、证据缺失、权限/安全违规、长任务漂移、多 agent 协调失败。

普通 Goal Teams 运行只在以下情况创建或更新 `benchmarks/`：

- 用户明确要求构建 benchmark、运行 benchmark 或比较 workflow。
- Lead 已在 `Teams 规划表` 中确认 Benchmark 任务和 Owner。
- Skill Improvement 任务明确以 Benchmark 失败分类为输入。

Benchmark 任务包可用 `scripts/benchmark/benchmark-runner.py --check-only` 或兼容入口 `scripts/benchmark-runner.py --check-only` 检查结构。当前任务集包括 `GT-BENCH-001`、`GT-BENCH-002`、`GT-BENCH-003` 和 `GT-BENCH-004`。

## Budget Gate 与 Conflict Policy

以下任务必须写 Budget Gate：预计超过 4 个 subagents、需要自动续跑、生产流、Benchmark、浏览器 E2E、像素对比、或用户给出时间/tokens/费用约束。

```text
Budget Gate:
- max_subagents:
- max_auto_continue_rounds:
- time_budget:
- token_budget:
- cost_budget:
- stop_when_exceeded:
```

并发任务必须写 Conflict Policy：

```text
Conflict Policy:
- shared_scope:
- write_owner:
- read_only_members:
- merge_owner:
- pause_conditions:
- replan_conditions:
```

同一 `locked_scope` 只有一个写 Owner。共享核心模块、认证、支付、迁移、安全敏感代码和大范围 API 合同默认串行。冲突策略详见 `references/subagent-dispatch-protocol.md`。

Loop 分三层：

| Loop | 责任 | 状态流 | 产物 |
| --- | --- | --- | --- |
| 成员 Loop | 单个 subagent 完成认领切片 | `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue` | Doc Capsules、Harness Evidence、revision-bound event/patch |
| Lead LOOP | 团队协调和完成闭环 | `Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`；每轮输出 `Loop Decision` | `plan.md`、`progress.md`、`loop-state.json`、team-state、续跑计划 |
| Skill Improvement Loop | 维护 skill 规则和发布质量 | `Run/Eval -> Classify -> Update Rules/Templates -> Validate -> Release Notes` | `goal-teams.md`、`SKILL.md`、runtime、subagents、README/CHANGELOG、校验结果 |

三层 Loop 的边界：

- 成员不能启动嵌套团队，不能越过自己的 `locked_scope`。
- Lead 负责把成员结果整合到 tasklist、acceptance、progress 和最终审计；不能用自己的感觉替代独立校验证据。
- Skill Improvement 不在普通用户任务中自动发生；只有用户明确要求改 skill 或 benchmark/复盘任务进入该层。

## 任务清单发现与创建（Tasklist）

发现顺序：

1. 用户提到的 tasklist 路径。
2. 项目本地候选：`TaskList.md`、`TASKLIST.md`、`tasklist.md`、`TODO.md`、`docs/*task*`、`docs/*plan*`。
3. Goal Teams 版本路径：`GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md`。
4. 旧 runtime 路径：`.codex/goal-teams/tasklist.md`。
5. 如果没有活跃 TaskList，建立 ledger 并生成 `GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md`；发现 legacy `tasklist.md` 时先迁移，禁止双写。

ledger owner 建立任务事件后，reducer 生成的 TaskList 必须从一开始包含具体身份、正交状态、revision 和可验证结构：

```md
# Goal Teams TaskList

Goal: <用户目标>
Run outcome: partial
Ledger revision: 1

## 成员归属

| Task ID | display_name | agent_type | member_id / agent_run_id | Workflow | 前置任务 | task_state | Locked Scope | 交付物 | 完成标准 | Harness | Validator run / check_state | Docs/SPEC event |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 需求分析-WIKI 列表需求澄清 | goal_requirements_analyst | MEMBER-REQ-WIKI / RUN-REQ-WIKI-001 | 串行 | - | planned | GoalTeamsWork-<project_version>/versions/<artifact_version>/spec/ | 需求规格卡 | AC 覆盖 | 文档结构/边界清单 | RUN-REVIEW-REQ-001 / not_started | requirement artifact event |

## 任务

| Task ID | 标题 | Owner member/run | Workflow | 前置任务 | task_state | Harness | 停止条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 澄清需求和验收标准 | MEMBER-REQ-WIKI / RUN-REQ-WIKI-001 | 串行 | - | planned | 文档清单审查 | 缺少业务决策 |

## 交接物投影

| Task ID | 交接物 | 类型 | Source SSOT | Owner member/run | Validator member/run | task_state | check_state | revision / attempt | Harness | Evidence | 阻塞/延期原因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | Requirement Specification Card | requirement_spec_card | prompts/packets/handoff-artifacts.md | MEMBER-REQ-WIKI / RUN-REQ-WIKI-001 | MEMBER-REVIEW-REQ / RUN-REVIEW-REQ-001 | planned | not_started | 1 / ATT-GT-001-001 | 结构/边界清单 | pending | - |

## 决策与阻塞

| ID | 类型 | Owner | 状态 | 摘要 | 需要决策 |
| --- | --- | --- | --- | --- | --- |
```

TaskList 是 reducer 投影，不能用手工 checkbox 文件替代 ledger 或丢失具体 identity/revision。

## Markdown 持久化模板

追加到 `GoalTeamsWork-<project_version>/versions/<artifact_version>/plan.md`：

```md
# Goal Teams Plan

## 用户目标

<中文描述>

## 环境检查

| 项目 | 结果 | 建议 |
| --- | --- | --- |
| AGENTS/agent 指南 | found/missing | 如缺失，建议补充团队规则和项目约束 |
| CLAUDE 指南 | found/missing | 如缺失，建议补充跨工具协作约定 |
| 默认指南 | active/not needed | 缺失项目指南时使用 `references/default-AGENTS.md` |
| 输出目录 | <project_version> | 根目录 `GoalTeamsWork-<project_version>/`，SSOT 写入 `versions/<artifact_version>/` |

## 澄清问题

| 问题 | 用户回答 | 影响 | 状态 |
| --- | --- | --- | --- |

## 当前假设

| 假设 | 影响 | 验证方式 | 是否需确认 |
| --- | --- | --- | --- |

## 确认后的计划

| 阶段 | 输出 | Owner | 验收标准 | 风险 |
| --- | --- | --- | --- | --- |

## Harness / Benchmark

| 任务 | Harness 契约 | 证据位置 | Benchmark 是否适用 | 状态 |
| --- | --- | --- | --- | --- |
```

追加到 `GoalTeamsWork-<project_version>/versions/<artifact_version>/progress.md`：

```md
# Goal Teams Progress

## <YYYY-MM-DD HH:mm> 执行轮次

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |

## 阻塞与决策

| 阻塞/决策 | 成员 | 影响 | 需要用户确认 | 建议 |
| --- | --- | --- | --- | --- |
```

追加到 `GoalTeamsWork-<project_version>/versions/<artifact_version>/decisions.md`：

```md
# Goal Teams Decisions

| 时间 | 决策 | 原因 | 决策人 | 影响范围 |
| --- | --- | --- | --- | --- |
```

## 确认表

启动 worker subagents 或编辑实现文件前，先展示 `Teams 规划表`。除非有直接执行词或已确认计划，否则请求用户确认。

### Teams 规划表

表格只用四个合并显示列，但底层逻辑字段必须保留：agent_type、agent_run_id、member_id、display_name、transport_handle、目标切片、认领任务、workflow、前置任务、locked_scope、交接物、artifact_type、具体 Owner/Validator identity、task_state、check_state、完成标准、Harness、Evidence、文档与 ledger event、测试 Owner。

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Agent type：`goal_backend`<br>Member/Run：`MEMBER-BACKEND-WIKI` / `RUN-BACKEND-WIKI-001` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行<br>前置任务：GT-ARCH, GT-TDD-CASES<br>锁定范围：`src/api/wiki/` | 交接物：后端实现（`backend_implementation`）<br>完成标准：TDD 单测和 API 集成测试通过<br>Harness：单测 + API 集成 pytest<br>Ledger event：Architecture Design + implementation refs<br>`task_state=planned` | 测试 Owner：单测执行-WIKI 列表TDD运行；API集成测试-WIKI 列表执行<br>Validator run：`RUN-REVIEW-WIKI-CODE-001`<br>`check_state=not_started` |
| 成员：browser-WIKI 列表页面验证<br>Agent type：`browser`<br>Member/Run：`MEMBER-BROWSER-WIKI` / `RUN-BROWSER-WIKI-001` | 目标切片：页面验证<br>认领任务：GT-004<br>Workflow：并行<br>前置任务：GT-003<br>锁定范围：`src/ui/wiki/` | 交付物：页面截图和控制台检查<br>完成标准：桌面/移动截图通过<br>Harness：截图 + console error + viewport 检查<br>Ledger event：HTML Prototype + Evidence refs | 测试 Owner：测试-WIKI 列表验收测试<br>Validator run：`RUN-REVIEW-WIKI-UI-001` |

### SPEC 准备度

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |
| Requirement Specification Card | no | create | 需求分析师 | `versions/<artifact_version>/spec/requirement-spec-card.md` |
| PRD | no | create | 产品/需求 | `versions/<artifact_version>/spec/PRD.md` |

### Harness 准备度

| 任务 | Harness 类型 | 检查/命令 | 证据位置 | Owner | 状态 |
| --- | --- | --- | --- | --- | --- |
| GT-003 | automated | API 合同测试 + 定向回归 | `progress.md` | 测试-WIKI 列表验收测试 | planned |

### Benchmark 适用性

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 是否创建/更新 `benchmarks/` | yes/no/not applicable | 只有用户要求或计划确认时启用 |
| Benchmark 任务来源 | tasklist/SPEC/历史 issue/not applicable | 不适用时写明原因 |
| 失败分类记录 | planned/not applicable | 使用 Benchmark 时必须记录 |

### 环境准备度

| 项目 | 状态 | 建议 |
| --- | --- | --- |
| AGENTS/agent 指南 | found/missing | 如缺失，建议创建 `AGENTS.md` 或 `agent.md` |
| CLAUDE 指南 | found/missing | 如缺失，建议创建 `CLAUDE.md` 或 `claude.md` |
| 默认指南 | active/not needed | 如缺失项目指南，使用 `references/default-AGENTS.md` |
| 输出目录 | ready/pending | `GoalTeamsWork-<project_version>/` |
| 文档索引 | ready/pending | `GoalTeamsWork-<project_version>/index.md` |
| memory | ready/pending | `GoalTeamsWork-<project_version>/memory.md` |
| 版本子目录 | ready/pending | `GoalTeamsWork-<project_version>/versions/<artifact_version>/` |
| TaskList | ready/pending | `GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md` |

### Teams 规划表（简版）

仅在需要短表时使用；优先使用完整 `Teams 规划表`。

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：需求分析-WIKI 列表需求澄清<br>Agent type：`goal_requirements_analyst`<br>Member/Run：`MEMBER-REQ-WIKI` / `RUN-REQ-WIKI-001` | 目标切片：梳理 WIKI 列表需求<br>认领任务：GT-001<br>Workflow：串行<br>前置任务：-<br>锁定范围：`GoalTeamsWork-<project_version>/versions/<artifact_version>/spec/` | 交付物：需求规格卡<br>完成标准：用户确认核心目标/功能/流程/边界<br>Harness：文档结构与边界清单审查<br>Ledger event：requirement-spec-card ref | 测试 Owner：评审-WIKI 列表需求校验<br>Validator run：`RUN-REVIEW-REQ-001` |
| 成员：产品-WIKI 列表 PRD<br>Agent type：`goal_product`<br>Member/Run：`MEMBER-PRODUCT-WIKI` / `RUN-PRODUCT-WIKI-001` | 目标切片：生成 WIKI 列表 PRD<br>认领任务：GT-002<br>Workflow：串行<br>前置任务：GT-001<br>锁定范围：`GoalTeamsWork-<project_version>/versions/<artifact_version>/spec/` | 交付物：PRD<br>完成标准：PRD 来源于已确认需求规格卡<br>Harness：PRD 溯源和验收标准清单<br>Ledger event：PRD ref | 测试 Owner：评审-WIKI 列表 PRD 校验<br>Validator run：`RUN-REVIEW-PRD-001` |

### TaskList 投影视图

| 任务 | 交接物 | 类型 | Owner member/run | Validator member/run | task_state | check_state | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |

### 独立校验计划

| 产物类型 | 作者 | 校验者 | 校验方法 | 证据位置 |
| --- | --- | --- | --- | --- |
| 文档 | 产出成员 | 非作者评审成员或用户指定 skill | 结构/事实/验收标准校验 | `progress.md` / `acceptance.md` |
| 代码 | 实现成员 | 独立测试/评审成员或用户指定 skill | 代码审查 + 命令验证 | `progress.md` |
| 测试用例 | 测试成员 | 独立评审成员或用户指定 skill | 断言有效性/边界覆盖校验 | `test-plan.md` / `progress.md` |

### Ledger / TaskList 执行

| Task ID | Owner member/run | task_state | 依赖 | Harness | Validator run / check_state | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| GT-001 | MEMBER-REQ-WIKI / RUN-REQ-WIKI-001 | planned | - | 文档清单审查 | RUN-REVIEW-REQ-001 / not_started | pending |
| GT-002 | MEMBER-PRODUCT-WIKI / RUN-PRODUCT-WIKI-001 | planned | GT-001 | PRD 溯源检查 | RUN-REVIEW-PRD-001 / not_started | pending |

### 风险与审批

| 项目 | 风险 | Owner | 是否需审批 | 停止条件 |
| --- | --- | --- | --- | --- |
| Shared module | 多成员可能编辑同一文件 | Goal Lead | 是 | locked_scope 不清楚 |

表格后用中文询问，并默认给数字选项：

```text
请选择下一步：
1. 确认并执行
2. 调整成员或范围
3. 只保留方案，不执行
```

如果用户明确要求继续、包含直接执行词或执行已确认计划，仍展示 `Teams 规划表`，然后直接继续。

除非用户只要方案且不希望写文件，否则把确认表和假设持久化到 `GoalTeamsWork-<project_version>/plan.md`。

## 进度反馈表

每个有意义轮次都用表格总结：

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| 后端-WIKI 列表后端开发 | GT-003 | running | Test | `cargo test ...` | 更新文档 |

独立校验：

| 产物 | 作者 | 校验者 | 状态 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `spec/PRD.md` | 产品-WIKI 列表 PRD | 评审-WIKI 列表 PRD 校验 | passed | review note | 更新 acceptance |

阻塞：

| 阻塞 | 成员 | 任务 | 影响 | 需要决策 | 建议下一步 |
| --- | --- | --- | --- | --- | --- |

最终收尾：

| 成员 | 认领任务 | Workflow / 前置任务 | 最终状态 | 证据 | 资源消耗（用户 / tokens / 费用） | 剩余 |
| --- | --- | --- | --- | --- | --- | --- |

把进度、阻塞和收尾证据追加到 `GoalTeamsWork-<project_version>/versions/<artifact_version>/progress.md` 或该版本目录内的相关 Markdown 产物。

## 提示词缓存友好布局（Prompt）

保持布局稳定：

```text
[稳定核心提示词]
[文档加载清单]
[Goal Mode 循环]
[动态目标包]
```

规则：

- 稳定核心提示词很少变化。
- 文档加载清单只列路径和读取规则，不塞长文档正文。
- 动态目标包放最后。
- 每个 subagent 只拿自己的 packet 和必要文档切片。
- 渐进读取文档，并总结成 Doc Capsules。

## 文档加载清单

通用清单：

```text
总是先加载：
1. 用户目标和约束。
2. 项目指南文件：AGENTS.md、agents.md、agent.md、CLAUDE.md、claude.md。
3. 没有项目指南时加载 references/default-AGENTS.md。
4. 如存在，加载 `GoalTeamsWork-<project_version>/index.md` 和 `memory.md`。
5. 加载目标 artifact version 的 `versions/<artifact_version>/index.md` 和 `plan.md`。
6. 加载该版本的 ledger 与 reducer 生成的 `TaskList.md`；不存在时由 ledger owner 建立 ledger，成员不得自行创建或编辑 TaskList。
7. 当前成员认领任务行。
8. 当前任务的 Harness Contract；如使用 Benchmark，加载对应 `benchmarks/` 任务包索引和报告。
```

按需加载：

| 需求 | 加载 |
| --- | --- |
| 产品/用户范围 | Requirement Specification Card、PRD、issue、brief 或干系人备注 |
| 架构/归属 | Architecture Design、design.md、模块文档、代码地图、依赖文件 |
| UI/页面/工作流 | HTML Prototype、design.md、截图、mockup、route map |
| API/合同语义 | API 文档、schema、route 定义、SDK 文档 |
| 测试/验收 | Test Plan、现有测试、CI 配置、acceptance 文档 |
| Harness | TaskList 投影引用的 Harness Contract、测试命令、人工检查清单、Evidence 路径 |
| Benchmark | `benchmarks/README.md`、任务 `task.md` 或 `SPEC.md`、metadata（如有）、Harness、scoring、reports |
| 发布/部署 | README、部署文档、changelog、runbook |

所需文档不存在时，只有它属于已确认计划，才创建小范围文档。

## 团队目标包（Team Goal Packet）

```text
Goal Packet（团队目标包）:
- goal:
- version:
- output_dir:
- done_criteria:
- language: 用户沟通与治理文档默认中文；代码和测试遵循目标仓库约定
- constraints:
- discovered_docs:
- markdown_persistence:
  - index.md
  - memory.md
  - plan.md
  - progress.md
  - decisions.md
  - versions/<artifact_version>/TaskList.md（reducer projection）
  - versions/<artifact_version>/ledger/events.jsonl
- tasklist_path: <version_dir>/TaskList.md
- ledger_path: <version_dir>/ledger/events.jsonl
- openspec_or_superpower_lead_only: true/false
- allowed_scope:
- forbidden_scope:
- required_tests:
- harness_policy:
  - 每个任务必须有 Harness Contract、证据路径或 not_applicable_reason
  - 不宣称未验证或未授权的运行能力
- benchmark_policy:
  - enabled: true/false
  - benchmark_dir: benchmarks/（仅在用户要求或计划确认时）
  - failure_taxonomy_required: true/false
- loop_policy:
  - member_loop: Load -> Plan -> Implement -> Test -> Document -> Review -> Continue
  - lead_loop: Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue
  - skill_improvement_loop: 仅在用户明确要求改 skill 或 benchmark/复盘任务时启用
- required_docs_after_done:
  - Markdown 进度/结果更新
- required_spec:
  - Requirement Specification Card
  - PRD
  - Architecture Design
  - HTML Prototype（适用时）
  - test plan
  - acceptance
- stop_conditions:
- confirmation_required:
- team_members:
  - member_id:
    subagent_id:
    display_name:
    role:
    skill_or_subagent:
    workflow_mode: serial | parallel
    depends_on:
    budget_gate:
    conflict_policy:
    communication_style: 用户沟通使用简洁、人类友好的中文；实现内容遵循目标仓库约定
    claimed_tasks:
    locked_scope:
    deliverable:
    harness_owner_for:
    validation_owner_for:
```

用 Team Goal Packet 为每个 subagent 创建 Member Goal Packet。

## 成员目标包（Member Goal Packet）

```text
Member Goal Packet（成员目标包）:
- agent_type: goal_backend
- agent_run_id: RUN-BACKEND-WIKI-001
- member_id: MEMBER-BACKEND-WIKI
- display_name: 后端-WIKI 列表后端开发
- transport_handle: <宿主返回值或 null>
- role: 后端
- skill_or_subagent: goal_backend
- workflow_mode: serial
- depends_on:
  - GT-001
  - GT-002
- budget_gate:
  - max_subagents:
  - max_auto_continue_rounds:
  - time_budget:
  - token_budget:
  - cost_budget:
  - stop_when_exceeded:
- conflict_policy:
  - shared_scope:
  - write_owner:
  - read_only_members:
  - merge_owner:
  - pause_conditions:
  - replan_conditions:
- version: V3.0
- output_dir: GoalTeamsWork-V3.0
- artifact_version: V3.0
- version_dir: GoalTeamsWork-V3.0/versions/V3.0
- language: 用户沟通和治理文档默认中文；实现内容遵循仓库约定
- user_requested_skill:
- user_requested_subagent:
- lane_or_deliverable: API 实现
  - handoff_artifacts:
  - schema_version: goal-teams-v2.3
    task_id: GT-003
    title: WIKI 列表 API 实现
    handoff_artifact: 后端实现
    artifact_type: implementation_change
    source_ssot: prompts/packets/handoff-artifacts.md
    owner_agent_type: goal_backend
    owner_member_id: MEMBER-BACKEND-WIKI
    owner_run_id: RUN-BACKEND-WIKI-001
    validator_agent_type: goal_reviewer
    validator_member_id: MEMBER-REVIEWER-WIKI
    validator_run_id: RUN-REVIEWER-WIKI-001
    merge_owner_run_id: RUN-LEDGER-OWNER-WIKI-001
    task_state: planned
    check_state: not_started
    required_for_done: true
    acceptance_blocking: true
    attempt_id: ATT-GT-003-001
    base_revision: 0
    requirement_refs: [REQ-WIKI-003]
    acceptance_criteria_refs: [AC-WIKI-003]
    artifact_refs: []
    evidence_refs: []
    harness_refs: [versions/V3.0/harness/harness.json]
- target_task_ids:
  - GT-002
- claimed_tasks:
  - 实现已确认的 API 切片
- goal:
  完成被分配的后端切片，并达到可验证 accepted 状态。
- success_criteria:
  - API 行为符合已接受合同。
  - 定向测试通过。
  - 独立校验者确认生成代码和测试。
- required_doc_load:
  - GoalTeamsWork-V3.0/versions/V3.0/TaskList.md#GT-003
  - 相关 API 文档，如存在
- allowed_scope:
  - src/api
  - tests/api
- forbidden_scope:
  - 未审批不得修改 shared auth/payment/core modules
- locked_scope:
  - src/api/specific-module
- required_tests:
  - 被修改模块的定向测试
- harness_contract:
  purpose: 证明 API 切片符合已接受合同且不引入回归。
  checks:
    - API 合同测试
    - 定向回归测试
  commands:
    - <按项目实际命令填写，未知时写需 Lead 确认>
  artifact_checks:
    - revision-bound ledger event accepted by ledger owner
    - progress 证据行
  evidence_paths:
    - GoalTeamsWork-V3.0/versions/V3.0/evidence/EVD-GT-003.json
  failure_report:
    - command
    - failing_check
    - likely_cause
    - next_verification
  not_applicable_reason:
- benchmark_refs:
  - enabled: false
  - task_id:
  - report_path:
- required_independent_validation:
  - 生成文档：校验者不能是作者
  - 生成代码：独立 QA/reviewer 或用户指定 skill
  - 生成测试用例：独立 reviewer 或用户指定 skill
  - 交接物：validator_run_id 必须独立于 owner_run_id，并在 identity/registry.json 中有具体身份
- required_docs_after_done:
  - TaskList 所需的结构化 event/patch（不直接编辑投影）
  - GoalTeamsWork-<project_version>/versions/<artifact_version>/progress.md 行
  - API 说明（如有变化）
- required_spec:
  - Requirement Specification Card：读取或确认不适用
  - PRD：读取或确认不适用
  - Architecture Design：API 结构变化时更新
  - HTML Prototype：无 UI 变化时不适用
  - Test Plan：覆盖范围变化时更新
  - Acceptance：Done Criteria 变化时更新
- stop_conditions:
  - API 合同不清楚
  - 必要凭证不可用
- output_contract:
  - Doc Capsules
  - plan
  - Harness Contract
  - revision-bound ledger events/patches
  - 变更文件
  - 运行测试
  - 更新文档
  - Markdown 进度/结果更新
  - 独立校验证据
  - TaskList 投影变更请求（不得直接编辑）
  - SPEC 更新
  - 建议的 team-state 更新
  - 完成状态
  - 阻塞和风险
```

## 文档摘要 JSONL（Doc Capsule）

```json
{"ts":"2026-05-26T10:00:00+08:00","agent_type":"goal_backend","agent_run_id":"RUN-BACKEND-WIKI-001","member_id":"MEMBER-BACKEND-WIKI","display_name":"后端-WIKI 列表后端开发","source":"GoalTeamsWork-V3.0/versions/V3.0/TaskList.md#GT-003","decision":"只实现已确认 API 切片。","must_do":["符合已接受合同","运行定向测试"],"must_not_do":["未审批不得编辑 shared auth"],"test_refs":["定向模块测试"],"doc_update_refs":["GoalTeamsWork-V3.0/versions/V3.0/ledger/events.jsonl"],"open_questions":[]}
```

## 团队状态 JSON（Team State）

```json
{
  "team": {
    "mode": "goal-teams",
    "goal": "完成已确认用户目标",
    "version": "V3.0",
    "version_dir": "GoalTeamsWork-V3.0/versions/V3.0",
    "ledger_path": "GoalTeamsWork-V3.0/versions/V3.0/ledger/events.jsonl",
    "tasklist_path": "GoalTeamsWork-V3.0/versions/V3.0/TaskList.md",
    "ledger_revision": 0,
    "loop_decision": "continue",
    "run_outcome": null,
    "updated_at": "2026-05-26T10:00:00+08:00"
  },
  "members": [
    {
      "agent_type": "goal_requirements_analyst",
      "agent_run_id": "RUN-REQ-WIKI-001",
      "member_id": "MEMBER-REQ-WIKI",
      "display_name": "需求分析-WIKI 列表需求澄清",
      "role": "需求分析",
      "skill_or_subagent": "goal_requirements_analyst",
      "workflow_mode": "serial",
      "depends_on": [],
      "task_state": "planned",
      "claimed_tasks": ["GT-001"],
      "current": "创建 WIKI 列表需求规格卡",
      "locked_scope": ["GoalTeamsWork-V3.0/versions/V3.0/spec"]
    }
  ]
}
```

## 事件 JSONL（Events）

```json
{"schema_version":"goal-teams-v2.3","event_id":"EVT-GT-001-PLANNED","event_type":"task_patch","task_id":"GT-001","attempt_id":"ATT-GT-001-001","actor_run_id":"RUN-REQ-WIKI-001","ledger_owner_run_id":"RUN-LEDGER-OWNER-WIKI-001","base_revision":0,"timestamp":"2026-05-26T10:01:00+08:00","payload":{"title":"WIKI 列表需求规格卡","task_state":"planned","check_state":"not_started","required_for_done":true,"acceptance_blocking":true,"owner_member_id":"MEMBER-REQ-WIKI","owner_run_id":"RUN-REQ-WIKI-001","validator_member_id":"MEMBER-REVIEWER-WIKI","validator_run_id":"RUN-REVIEWER-WIKI-001","merge_owner_run_id":"RUN-LEDGER-OWNER-WIKI-001","requirement_refs":["REQ-WIKI-001"],"acceptance_criteria_refs":["AC-WIKI-001"],"artifact_refs":[],"evidence_refs":[],"harness_refs":["versions/V3.0/harness/harness.json"]}}
{"schema_version":"goal-teams-v2.3","event_id":"EVT-GT-001-RUNNING","event_type":"task_patch","task_id":"GT-001","attempt_id":"ATT-GT-001-001","actor_run_id":"RUN-REQ-WIKI-001","ledger_owner_run_id":"RUN-LEDGER-OWNER-WIKI-001","base_revision":1,"timestamp":"2026-05-26T10:04:00+08:00","payload":{"task_state":"running"}}
{"schema_version":"goal-teams-v2.3","event_id":"EVT-GT-001-ARTIFACT","event_type":"artifact_created","task_id":"GT-001","attempt_id":"ATT-GT-001-001","actor_run_id":"RUN-REQ-WIKI-001","ledger_owner_run_id":"RUN-LEDGER-OWNER-WIKI-001","base_revision":2,"timestamp":"2026-05-26T10:18:00+08:00","payload":{"artifact_refs":["versions/V3.0/spec/requirement-spec-card.md"]}}
{"schema_version":"goal-teams-v2.3","event_id":"EVT-GT-001-CHECK","event_type":"check_executed","task_id":"GT-001","attempt_id":"ATT-GT-001-001","actor_run_id":"RUN-REVIEWER-WIKI-001","ledger_owner_run_id":"RUN-LEDGER-OWNER-WIKI-001","base_revision":3,"timestamp":"2026-05-26T10:19:00+08:00","payload":{"check_state":"passed","validation_check_id":"CHECK-GT-001","validation_run_id":"RUN-CHECK-GT-001","evidence_refs":["EVD-GT-001-001"]}}
{"schema_version":"goal-teams-v2.3","event_id":"EVT-GT-001-REVIEW-READY","event_type":"task_patch","task_id":"GT-001","attempt_id":"ATT-GT-001-001","actor_run_id":"RUN-REQ-WIKI-001","ledger_owner_run_id":"RUN-LEDGER-OWNER-WIKI-001","base_revision":4,"timestamp":"2026-05-26T10:19:30+08:00","payload":{"task_state":"review"}}
{"schema_version":"goal-teams-v2.3","event_id":"EVT-GT-001-ACCEPTED","event_type":"review_completed","task_id":"GT-001","attempt_id":"ATT-GT-001-001","actor_run_id":"RUN-REVIEWER-WIKI-001","ledger_owner_run_id":"RUN-LEDGER-OWNER-WIKI-001","base_revision":5,"timestamp":"2026-05-26T10:20:00+08:00","payload":{"task_state":"accepted","review_ref":"REV-GT-001-001"}}
```

上述事件逐条通过 `validate-event`。其中 `EVD-GT-001-001` 必须在前三条事件已经持久化后、`CHECK` 事件追加前生成：普通 Evidence 绑定完整 ancestor SHA、非空 tracked `source_paths` manifest 与 ledger prefix。对应 Check 先声明 exact `expected_domain_execution`，Run 包络匹配的真实 `command`、独立日志/record、随后 runtime-locked `integrity_replay`，再结束并生成 Evidence；Completion 只重放后者。symbolic HEAD 仅供 `validate-canonical` 内部 portable fixture；完整 replay 必须用 `--ledger`，不能用无关命令、未来 ledger、复制 fixture或只补 ID 宣称 accepted。

## 消息 JSONL（Messages）

```json
{"ts":"2026-05-26T10:12:00+08:00","from":"qa-gt-003","to":"goal-lead","task_id":"GT-003","severity":"medium","message":"需要确认空状态验收的预期行为。","decision_needed":true,"status":"open"}
```
