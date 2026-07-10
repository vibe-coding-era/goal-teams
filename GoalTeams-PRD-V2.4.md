---
type: Product Requirements Document
title: Goal Teams V2.4 产品比较与互操作需求文档
description: 对比 Goal Teams、OpenSpec 与 Superpowers 的定位、能力和边界，并定义 V2.4 可验证的组合架构与互操作需求。
resource: https://github.com/vibe-coding-era/goal-teams
tags: [goal-teams, prd, v2.4, openspec, superpowers, interoperability]
timestamp: 2026-07-10T11:33:04+08:00
okf_version: "0.1"
goal_teams_version: "V2.2"
project_version: "V2.4"
target_goal_teams_version: "V2.4"
status: Draft
owner_subagent: "/root"
validator_subagent: "/root/prd_final_review"
owner_role: Goal Lead
validator_role: Independent Completion Auditor
source_ssot: GoalTeams-PRD-V2.3.md
comparison_date: 2026-07-10
openspec_baseline: "Fission-AI/OpenSpec v1.5.0"
superpowers_baseline: "obra/superpowers v6.1.1"
---

# Goal Teams V2.4 产品比较与互操作需求文档

## 1. 文档摘要

本文将 Goal Teams V2.2/V2.3 与官方 Fission-AI/OpenSpec、obra/superpowers 进行公平比较，并把比较结论转化为 V2.4 的产品战略和互操作需求。

三者不是同一类产品：

- OpenSpec 是规格变更生命周期、artifact graph 和 CLI/schema 层。
- Superpowers 是可组合的软件工程执行纪律和技能包。
- Goal Teams 是多 Agent 调度、交接、证据与完成审计的治理层。

V2.4 的目标不是复制或取代另外两个项目，而是建立清晰的组合边界：

> OpenSpec 管需求和规格变更；Superpowers 管 worker 执行纪律；Goal Teams 管跨成员编排、证据、风险和验收。

## 2. 比较范围与基线

### 2.1 产品身份

本文中的 OpenSpec 指：

- [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec)
- 固定比较基线：[v1.5.0](https://github.com/Fission-AI/OpenSpec/releases/tag/v1.5.0)。这是正式 release tag，但其中 Stores 仍被上游明确标注为 very early beta，相关能力不得作为稳定互操作承诺
- 预发布观察版本：[v1.6.0-beta.1](https://github.com/Fission-AI/OpenSpec/releases/tag/v1.6.0-beta.1)

不指同名的 openspec.tech 数据格式项目。

本文中的 Superpowers 指：

- [obra/superpowers](https://github.com/obra/superpowers)
- 稳定基线：[v6.1.1](https://github.com/obra/superpowers/releases/tag/v6.1.1)

Goal Teams 基线：

- 当前实现：V2.2
- 修复前置：[Goal Teams V2.3 PRD](GoalTeams-PRD-V2.3.md)
- 本文目标版本：V2.4

### 2.2 比较原则

1. 固定公开 release tag 作为可复盘比较快照；对 tag 内仍被上游标为 beta/experimental 的子能力单独降级，不把 main、预发布版或实验能力当作稳定承诺。
2. 区分产品定位，不做无意义总排名。
3. 区分提示词承诺、机器实现和可复现实证。
4. 不以 GitHub stars、社区热度或营销文案替代质量证据。
5. 同时记录优势、局限和适用边界。
6. 所有“兼容”声明必须有版本、adapter、fixture 和证据。

## 3. 一句话定位

| 产品 | 一句话定位 | 最适合的问题 |
| --- | --- | --- |
| Goal Teams | 多 Agent 工程治理与验收编排层 | 复杂、高风险、长任务、跨角色交接和证据闭环 |
| OpenSpec | 轻量规格变更账本、artifact DAG 与跨工具 CLI | Brownfield 需求演进、change proposal、living spec 和归档 |
| Superpowers | 可组合的软件工程执行纪律技能包 | brainstorming、计划、TDD、调试、review 和分支收口 |

## 4. 核心能力比较

| 维度 | Goal Teams V2.2/V2.3 方向 | OpenSpec 1.5 | Superpowers 6.1.1 |
| --- | --- | --- | --- |
| 核心定位 | 多 Agent 治理、调度、交接、验收 | Spec/change lifecycle、CLI、schema | 工程过程技能和 worker 纪律 |
| 主要事实源 | TaskList、artifact ledger、Harness、Evidence、memory | openspec/specs 当前行为 + openspec/changes 增量 | Git、计划、任务上下文、progress |
| Brownfield 规格演进 | 当前较弱 | 最强；requirement delta 是一等对象 | 非核心能力 |
| Artifact 模型 | 类型丰富但分散在 Markdown 规则 | 声明式 artifact dependency graph | 以技能和计划步骤组织 |
| 机器可执行程度 | 当前偏低，目标经 V2.3 提升 | 较高；CLI、status、instructions、validate、archive | 中等；主要依赖宿主执行 skills |
| 完成定义 | 目标是 Evidence + independent audit | artifact 文件存在、task checkbox；质量需另行验证 | 新鲜验证证据和 review，但无全局 ledger |
| 多 Agent 编排 | 三者中最完整，但 V2.2 有中央账本并发缺陷 | 没有一等团队调度 | 通用 subagent-driven development |
| 角色与独立检查 | Owner、Validator、Reviewer、Auditor | 默认无独立角色模型 | implementer + spec reviewer + quality reviewer |
| TDD | 独立测试设计/执行角色，流程覆盖广 | 默认不强制 | 最强；RED-GREEN-REFACTOR 是核心纪律 |
| 系统化调试 | 有失败降级，但根因方法不够突出 | 非核心能力 | 强；明确禁止未定位根因就修改 |
| Evidence | 设计丰富，V2.2 validator 可信度不足 | 无统一 evidence ledger | 强调新鲜命令证据，但不做跨任务持久账本 |
| 上下文策略 | 当前基础规则较重，目标按需路由 | 动态 instructions、dependency paths、context budget | task brief、implementer report、diff review package |
| 长任务恢复 | memory、TaskList、Loop State；V2.2 幂等字段不足 | change 目录和 task checkbox 易恢复 | progress 文件和 Git history |
| Git/worktree 生命周期 | 规则较弱 | Git-native change diff，但不主导 worktree | 强；worktree、分支和 finishing workflow |
| UI、E2E、Pixel | 三者中最完整 | 无领域内建 | 无专门 UI 视觉协议 |
| 安全与授权 | 三者中最系统 | 主要依赖宿主和用户 | 主要依赖宿主和项目流程 |
| Budget Gate | 有协议，V2.2 遥测不足 | 无通用预算治理 | 无通用预算治理 |
| 跨工具适配 | 偏 Codex，当前“兼容”只是共存 | 强，支持大量 AI coding 工具 | 多工具技能安装，Codex 可原生发现 |
| 行为评测 | 当前主要为静态 fixtures | CLI 单测强，语义质量闭环有限 | 有真实 skill-pressure/eval 实践 |
| 使用成本 | 高，适合复杂任务；V2.3 将引入 Profile | 低，Markdown/YAML + Node CLI | 中，按技能组合 |

## 5. Goal Teams 深度评估

### 5.1 独特优势

1. 将 SPEC、Harness、Evidence 和 Audit 明确分层。
2. 把 Owner 与独立 Validator 作为一等治理概念。
3. 对单测设计/执行、API 集成、E2E 和 Completion Audit 做角色分离。
4. 提供 UI 页面规格、组件视觉契约、截图和像素比较协议。
5. 对凭证、外部写入、支付、认证、破坏性操作和预算设置边界。
6. 适合跨文档、代码、测试、视觉和审计的复合目标。

### 5.2 当前局限

1. 规则主要由提示词声明，机器执行内核较薄。
2. 状态、路径、身份和完成语义在多个文件中重复。
3. 中央 TaskList 多写者与单写者冲突策略不一致。
4. Evidence validator 目前可接受虚构证据。
5. canonical example 与自身规范不一致。
6. 渐进加载被较大的基础包和重复 default prompt 抵消。
7. 缺少真实行为 benchmark 和跨宿主 adapter。
8. “自动续跑”和“兼容”文案强于实际能力。

### 5.3 不应放弃的产品边界

- Goal Teams 不应退化成单纯 spec 文档工具。
- 不应取消独立测试与完成审计。
- 不应为了轻量化删除安全门和 Evidence 模型。
- 应通过 Profile 降低默认成本，而不是删除高风险能力。

## 6. OpenSpec 深度评估

### 6.1 架构与工作流

OpenSpec 的核心事实模型是：

    openspec/
      specs/                  当前系统行为
      changes/
        change-name/
          proposal.md
          design.md
          tasks.md
          specs/...           本次 delta
        archive/...

官方概念文档将 specs 定义为 current truth，将 changes 定义为拟议变更：

- [OpenSpec Concepts](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/docs/concepts.md#L28-L50)

默认 artifact graph 大致为：

    proposal
      |---- specs
      |---- design
              |
             tasks
              |
             apply

默认 schema：

- [spec-driven schema](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/schemas/spec-driven/schema.yaml#L1-L153)

### 6.2 值得 Goal Teams 借鉴

1. Current Truth + Change Delta 双层 SSOT。
2. Requirement 级 ADDED、MODIFIED、REMOVED、RENAMED。
3. 声明式 artifact dependency graph。
4. CLI 动态返回 context、rules、template 和 dependency paths。
5. 统一 status、instructions、validate 和 archive 的机器接口方向。
6. Change folder 自包含，易于 Git diff、review 和归档。
7. 跨 AI coding 工具 adapter。
8. Context 和 reference index 的字节预算与按需 fetch。

动态 instruction 的官方实现：

- [instruction loader](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/src/core/artifact-graph/instruction-loader.ts#L273-L341)

### 6.3 不应照搬

1. Artifact 文件存在即 done。

   OpenSpec 的状态实现主要以输出文件是否存在判断 artifact 是否完成：

   - [artifact state](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/src/core/artifact-graph/state.ts#L6-L36)

   Goal Teams 必须把这种状态映射为 artifact_available，而不是 accepted。

2. Task checkbox 不能替代 Owner、Validator、Evidence 和稳定 Task ID。

3. Verify 不应成为唯一质量门。

   OpenSpec 的 verify 是提示词驱动的搜索、推断与审查，并非可复现 Harness；默认 core profile 也不强制 verify。

4. Archive 不应允许绕过测试、审批和 Evidence。

5. 不应保留两套 merge 语义。

   OpenSpec 1.5 schema 要求 MODIFIED 携带完整 requirement：

   - [MODIFIED requirement rules](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/schemas/spec-driven/schema.yaml#L41-L61)

   程序化 archive 使用整块替换：

   - [programmatic replacement](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/src/core/specs-apply.ts#L284-L307)

   但 sync skill 鼓励保留未提及内容并智能部分合并：

   - [sync partial merge guidance](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/src/core/templates/workflows/sync-specs.ts#L51-L82)

   因此 V2.4 必须只有一个确定性 merge engine。v1.6.0-beta.1 已声明修复 archive scenario drift，但 beta 不作为稳定互操作基线。

6. 不应在 Release Gate 前把计划中的行为静默写入 current truth。

7. 不应让新 capability 的 Purpose 以 TBD 长期进入 SSOT。

### 6.4 适用边界

OpenSpec 最适合作为 Goal Teams 上游规格层，而不是替代：

- 多 Agent owner/validator 调度；
- 测试设计与执行分离；
- Evidence ledger；
- Budget、Safety 和 Completion Audit；
- UI 视觉验证。

## 7. Superpowers 深度评估

### 7.1 核心技能链

Superpowers 把软件开发拆成可组合技能，包括：

- using-superpowers；
- brainstorming；
- writing-plans；
- using-git-worktrees；
- subagent-driven-development；
- test-driven-development；
- systematic-debugging；
- verification-before-completion；
- requesting/receiving-code-review；
- finishing-a-development-branch。

官方工作流：

- [Superpowers README](https://github.com/obra/superpowers/blob/v6.1.1/README.md#L188-L230)

Subagent-driven development：

- [Subagent workflow](https://github.com/obra/superpowers/blob/v6.1.1/skills/subagent-driven-development/SKILL.md#L8-L82)

TDD：

- [Test-driven development](https://github.com/obra/superpowers/blob/v6.1.1/skills/test-driven-development/SKILL.md#L16-L45)

Systematic debugging：

- [Systematic debugging](https://github.com/obra/superpowers/blob/v6.1.1/skills/systematic-debugging/SKILL.md#L46-L213)

### 7.2 值得 Goal Teams 借鉴

1. 小而可组合的技能，而不是一个默认全量规则包。
2. Task brief 只携带当前任务需要的信息。
3. Implementer report 明确改动、测试、风险和待审查内容。
4. Reviewer 接收 spec、diff 和报告，不读取无关历史。
5. TDD 必须看到真实 RED，再实现 GREEN。
6. 完成声明前运行新鲜验证命令。
7. 调试先定位根因，不进行试探式补丁堆叠。
8. Worktree 隔离和分支收口。
9. 真实场景 eval，而不是只检查文档关键词。

### 7.3 不应照搬

1. 不对所有创意或非代码任务强制完整 brainstorming 仪式。
2. 不对所有风险级别强制同等 TDD 成本。
3. 不要求计划包含大量可直接复制的实现代码。
4. 不把 reviewer 读取报告等同于 reviewer 已重新验证。
5. 不只依赖 ignored progress 文件作为持久事实源。
6. 不让单一 reviewer 同时承担规格、代码、测试和全局完成判断。
7. 不用软件工程专用流程替代 Goal Teams 的文档、UI、安全和预算治理。

### 7.4 适用边界

Superpowers 最适合作为 Goal Teams worker execution policy：

- 编码前澄清和计划；
- worktree/branch 隔离；
- TDD；
- 系统化调试；
- 完成前验证；
- task-level review；
- branch finishing。

它不应成为 Goal Teams 的唯一持久 SSOT 或全局 Completion Auditor。

## 8. 战略结论

### 8.1 最合理的组合

    OpenSpec
    Current Truth + Change Delta
              |
              v
    Goal Teams
    Typed Artifact DAG + Ledger + Routing
              |
              v
    Superpowers
    Worker Planning + TDD + Debugging + Review
              |
              v
    Goal Teams
    Harness + Evidence + Independent Audit

### 8.2 SSOT 所有权

| 事实类型 | 默认 Owner | 说明 |
| --- | --- | --- |
| 已验收产品行为规格 | OpenSpec specs，若项目启用 OpenSpec | Goal Teams 引用，不创建第二份可写副本 |
| 活跃需求变更 | OpenSpec changes，若启用 | Proposal、design、delta 和 tasks 保留 provenance |
| Goal 运行状态与成员调度 | Goal Teams ledger | OpenSpec task checkbox 不能替代 |
| 代码和分支状态 | Git | Worktree 和 commit 是代码事实源 |
| Worker 执行纪律 | Superpowers skills | 不作为独立持久 SSOT |
| Harness、Run、Evidence、Audit | Goal Teams | 与 commit、OpenSpec change 和 task ID 关联 |
| 用户授权与安全决策 | Goal Teams decision ledger / 宿主 | 不可由外部 adapter 推断 |

### 8.3 权威冲突规则

1. OpenSpec file exists 不得覆盖 Goal Teams accepted 状态。
2. Superpowers implementer report 不得覆盖测试 run 事实。
3. Git commit 不等于 requirement 已验收。
4. Goal Teams 不得在未授权时写回 OpenSpec current truth。
5. 三方状态冲突时进入 reconciliation，不静默选取“更新的文件”。

## 9. V2.4 产品目标

| ID | 目标 | 成功定义 |
| --- | --- | --- |
| G-24-01 | 真正互操作 | “兼容”有 versioned adapter、mapping、fixture 和 evidence |
| G-24-02 | 保持单一事实源 | 同一事实只有一个可写 Owner |
| G-24-03 | 可组合执行 | Goal Teams 能选择性调用 Superpowers worker discipline |
| G-24-04 | 规格演进 | 可读取和关联 OpenSpec current spec 与 active change |
| G-24-05 | 不丢失语义 | 导入、导出和 round-trip 保留已支持字段及 provenance |
| G-24-06 | 安全写回 | 外部写入默认 dry-run，需要明确授权和 Release Gate |
| G-24-07 | 可验证比较 | 互操作结论来自真实 scenario，而不是产品名称检测 |

## 10. 非目标

- 不 fork OpenSpec 或 Superpowers。
- 不复制其全部 prompt、命令或内部实现。
- 不把 OpenSpec beta 作为默认生产依赖。
- 不承诺支持所有历史版本。
- 不让 adapter 自动修改用户规格、分支或配置。
- 不用 OpenSpec status 替代 Goal Teams Completion Audit。
- 不用 Superpowers 的流程覆盖非软件工程领域。
- 不实现两套规格 merge engine。

## 11. 用户故事

| ID | 用户故事 | 价值 |
| --- | --- | --- |
| US-24-001 | 作为 Goal Lead，我想导入 OpenSpec active change，以便复用 proposal、design、delta 和 tasks | 避免重复规格 |
| US-24-002 | 作为 Spec Owner，我想看到 OpenSpec requirement 到 Goal Teams AC、Task 和 Evidence 的映射 | 保持追踪 |
| US-24-003 | 作为 Worker，我想按任务选择 Superpowers 的 TDD 或 debugging discipline | 提高执行质量 |
| US-24-004 | 作为 Reviewer，我想收到 spec、diff、test run 和 evidence package | 降低无关上下文 |
| US-24-005 | 作为 OpenSpec 用户，我想默认 read-only 集成，只有明确授权才写回 | 保护 current truth |
| US-24-006 | 作为 Auditor，我想知道每个外部 artifact 的来源版本和 hash | 可复盘 |
| US-24-007 | 作为维护者，我想对支持版本运行真实互操作 fixtures | 防止名义兼容 |
| US-24-008 | 作为不安装外部产品的用户，我想继续使用 Goal Teams | 避免强依赖 |
| US-24-009 | 作为升级用户，我想在 adapter 版本不匹配时得到明确降级 | 防止静默破坏 |
| US-24-010 | 作为仓库 owner，我想比较组合流程的质量和成本 | 判断是否值得启用 |

## 12. Adapter 总体契约

### 12.1 Adapter Manifest

每个 adapter 必须暴露：

    adapter_id: ...
    adapter_schema_version: ...
    product: openspec | superpowers
    supported_product_versions: [...]
    detected_product_version: ...
    capabilities:
      read: [...]
      write: [...]
      commands: [...]
    default_mode: read_only
    provenance: ...
    limitations: [...]

### 12.2 兼容状态模型

V2.4 禁止使用没有能力维度的“兼容”结论。兼容报告由四个正交部分组成，不把 import、export、sync 和 execution 压成一个互斥等级。

#### Detection State

| 状态 | 含义 |
| --- | --- |
| not_detected | 未检测到产品 |
| detected | 检测到产品并获得可解析的版本信息 |

#### Version Support State

| 状态 | 含义 |
| --- | --- |
| not_evaluated | 尚未把检测版本与 adapter 支持范围比较 |
| supported | 版本位于 adapter 声明并测试的支持范围 |
| unsupported | 版本不在支持范围，或无法安全解析 |

#### Operational State

| 状态 | 含义 |
| --- | --- |
| ready | 所请求能力已验证且当前可执行 |
| degraded | 部分能力缺失，但存在确定性降级 |
| blocked | 安全、版本、授权或权威冲突阻止运行 |

#### Per-capability Conformance

每项 capability：coexistence、import、export、sync、execution，独立记录以下一个状态：

| 状态 | 允许的对外表述 |
| --- | --- |
| not_tested | 未验证，不得宣称支持 |
| verified | 支持该产品版本下的指定能力，并引用 conformance report |
| failed | 测试失败，不得使用该能力 |
| not_applicable | 不适用，并记录原因 |

例如，一个 adapter 可以同时是 detection=detected、version_support=supported、operational=ready、import=verified、export=not_tested、sync=not_tested、execution=not_applicable。只有 detection=detected 且 version_support=supported 后，capability 才可能标记 verified；任何 not_tested 都不得在 README、启动语或报告中简化为“兼容”。

### 12.3 通用需求

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-24-ADP-01 | Adapter 必须版本化并声明支持范围 | 未支持版本进入 unsupported 或 degraded |
| FR-24-ADP-02 | 默认只读探测和导入 | 未经授权不得修改外部文件 |
| FR-24-ADP-03 | 所有导入 artifact 记录 path、product version、hash 和 imported_at | Audit 可定位来源 |
| FR-24-ADP-04 | 未支持字段以 extensions 保留，不得静默丢弃 | round-trip fixture 保留未知字段 |
| FR-24-ADP-05 | 写回前提供 dry-run diff 和冲突报告 | 用户可审查将发生的变更 |
| FR-24-ADP-06 | 写回必须显式授权并经过适用 Release Gate | read-only 默认不能被 prompt 绕过 |
| FR-24-ADP-07 | Adapter 错误使用统一 machine envelope 和 error code | Goal Lead 可确定性降级 |
| FR-24-ADP-08 | Adapter 可独立安装、禁用和卸载 | 不影响 Goal Teams 核心流程 |
| FR-24-ADP-09 | 每个 Task 同一 attempt 只能有一个 orchestration_owner | Goal Teams 与 Superpowers 不能同时派发同一 locked scope |
| FR-24-ADP-10 | 未安装外部产品时保持零强制开销 | 不加载 adapter 细则、不生成 adapter artifact、不新增阻塞任务 |

## 13. OpenSpec Adapter 需求

### 13.1 Artifact 映射

| OpenSpec | Goal Teams | 映射规则 |
| --- | --- | --- |
| openspec/specs/capability/spec.md | current_truth_spec | 只读导入时保持 OpenSpec 为权威 |
| changes/change/proposal.md | change_proposal | 保留 change ID 和来源 hash |
| changes/change/design.md | architecture_or_design_artifact | 不自动视为已审查 |
| changes/change/specs/... | requirement_delta | 保留 ADDED/MODIFIED/REMOVED/RENAMED |
| changes/change/tasks.md | imported_task_hint | checkbox 不是 Goal Teams accepted |
| archived change | archived_change_ref | 保留日期、路径和 provenance |
| validate result | structural_validation_evidence | 不自动满足实现或测试验收 |
| verify result | semantic_review_evidence | 记录 heuristic 性质和 reviewer |

### 13.2 状态映射

| OpenSpec 状态 | Goal Teams 状态 | 禁止映射 |
| --- | --- | --- |
| artifact 文件存在 | artifact_available | 不得直接映射 accepted |
| artifact ready | dependency_ready | 不得映射 task running |
| task checkbox checked | reported_complete | 不得映射 accepted |
| validate passed | structurally_valid | 不得映射 implementation_verified |
| verify 无 critical | semantically_reviewed | 不得单独映射 completion passed |
| archive 完成 | external_archived | 不得证明代码或 Evidence 已验收 |

### 13.3 功能需求

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-24-OSP-01 | 探测 OpenSpec root、版本、profile 和 active changes | 多 root 时不静默选错 |
| FR-24-OSP-02 | 读取 current specs 和 active change artifact graph | import report 列出缺失和 blocked artifact |
| FR-24-OSP-03 | 将 requirement/scenario 分配稳定 external_ref | Goal Teams AC 可引用 |
| FR-24-OSP-04 | 保留 delta operation 和 requirement 完整文本 | MODIFIED 不因导入丢 scenario |
| FR-24-OSP-05 | OpenSpec tasks 只作为 task hint，经 Goal Lead 正规化后进入 ledger | checkbox 不能绕过 Owner/Validator |
| FR-24-OSP-06 | 支持 validate 结果导入，但标记为 structural evidence | Completion Audit 不误用 |
| FR-24-OSP-07 | 写回使用唯一确定性 merge engine | sync 和 archive 不产生不同结果 |
| FR-24-OSP-08 | merge 先 plan、dry-run、全量验证、staging、原子替换 | 中途失败保留旧 specs |
| FR-24-OSP-09 | Release Gate 前不得自动污染 current truth | active change 与 current specs 权威清晰 |
| FR-24-OSP-10 | 检测 partial MODIFIED、并行 change 和 archive 冲突 | 冲突进入 manual reconciliation |
| FR-24-OSP-11 | 不默认依赖 beta 特性 | beta 需显式 opt-in 和独立 fixture |
| FR-24-OSP-12 | 支持 read-only coexistence，即使写回能力不可用 | 用户仍能引用 OpenSpec artifact |

### 13.4 社区 Bridge 边界

OpenSpec 官方社区目录列出了 superpowers-bridge，可作为研究对象和兼容 fixture：

- [OpenSpec community schemas](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/docs/customization.md#L340-L350)

Goal Teams 不把社区 bridge 当作核心依赖，不假设其版本与 OpenSpec、Superpowers 同步，也不因检测到它就宣称三方兼容。Goal Teams 的 authority、Evidence、Safety 和 Completion Audit 仍然生效。

## 14. Superpowers Adapter 需求

### 14.1 Skill 映射

| Superpowers Skill | Goal Teams 阶段 | 使用边界 |
| --- | --- | --- |
| brainstorming | requirement discovery | Lite 和明确需求可跳过 |
| writing-plans | implementation planning | 计划不能替代 TaskList ledger |
| using-git-worktrees | workspace isolation | 需项目允许创建 worktree |
| subagent-driven-development | member dispatch policy | Goal Teams 仍拥有 member identity 和 ledger |
| test-driven-development | implementation check policy | 根据 Profile 和任务类型启用 |
| systematic-debugging | failure diagnosis | 出现测试/运行异常时优先 |
| verification-before-completion | member completion evidence | 仍需 Goal Teams independent validation |
| requesting-code-review | task review | 绑定 spec、diff 和 run evidence |
| receiving-code-review | feedback resolution | 反馈状态写回 Goal Teams ledger |
| finishing-a-development-branch | branch close/release | 不替代外部审批和 Release Gate |

### 14.2 运行模式与唯一编排所有者

Superpowers Adapter 支持两种模式：

| 模式 | orchestration_owner | 行为 |
| --- | --- | --- |
| skill_mode | goal_teams | Goal Teams 保持任务派发权，只调用 TDD、debugging、verification、review 等原子技能；Superpowers 不再启动整套子任务编排 |
| delegate_mode | superpowers | Goal Teams 将一个边界明确的完整执行切片委托给 Superpowers；委托期间不得为相同 locked scope 创建第二个 writer |

每个 Execution Packet 至少包含：

    task_id: TASK-...
    attempt_id: ATTEMPT-...
    orchestration_owner: goal_teams | superpowers
    execution_mode: skill_mode | delegate_mode
    requirement_refs: [...]
    acceptance_criteria_refs: [...]
    allowed_paths: [...]
    locked_scope: [...]
    forbidden_paths: [...]
    repository_rules: [...]
    required_checks: [...]
    required_evidence: [...]
    branch_policy: existing | worktree | new_branch

Provider 切换必须先关闭当前 attempt 或显式创建 successor attempt。自然语言“已委托”不能改变 ledger ownership。

### 14.3 功能需求

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-24-SPW-01 | 探测已安装 Superpowers 版本和可用 skills | 缺失 skill 有明确 degraded capability |
| FR-24-SPW-02 | Goal Lead 根据 Profile、task type 和风险选择技能组合 | 不默认对所有任务运行完整链 |
| FR-24-SPW-03 | Member Goal Packet 可生成 Superpowers 风格 task brief | 只包含当前任务、constraints、consumes、produces 和 checks |
| FR-24-SPW-04 | Implementer report 必须包含 diff/ref、测试命令、结果、风险和未完成项 | 自由文本“done”不被接受 |
| FR-24-SPW-05 | TDD 任务保存 RED 和 GREEN 两阶段 evidence | 没有真实失败测试不得声明完成 TDD |
| FR-24-SPW-06 | Debugging 任务保存 hypothesis、observation、root cause 和 verification | 连续随机补丁被流程阻止 |
| FR-24-SPW-07 | Review package 包含 requirement/AC、diff、run evidence 和 known risks | Reviewer 不依赖完整聊天历史 |
| FR-24-SPW-08 | Reviewer 必须独立运行或验证关键 checks | 不只相信 implementer report |
| FR-24-SPW-09 | Worktree/branch 操作遵守用户授权和仓库策略 | 不擅自创建、合并或删除分支 |
| FR-24-SPW-10 | progress 信息写入 Goal Teams ledger 或引用，不形成第二个权威状态源 | 恢复时不发生状态分叉 |
| FR-24-SPW-11 | 非代码、低风险和探索任务可跳过不适用技能 | 记录 selection reason |
| FR-24-SPW-12 | Superpowers 不可用时 Goal Teams 核心仍可工作 | fallback 不扩大权限 |
| FR-24-SPW-13 | skill_mode 禁止外部 provider 再启动任务级 orchestrator | 同一 task 只有 Goal Teams 派发 |
| FR-24-SPW-14 | delegate_mode 禁止 Goal Teams 并行派发相同 locked scope | 双 writer fixture 被拒绝并记录冲突 |
| FR-24-SPW-15 | 外部 execution report 必须转换为 Goal Teams EvidenceRecord | 自然语言 done 不更新 task_state |

## 15. 组合编排流程

### 15.1 标准流程

1. Capability Probe：探测 Goal Teams、OpenSpec、Superpowers 和宿主能力。
2. Authority Selection：声明规格、运行状态、代码和 Evidence 的事实源。
3. Read-only Import：读取 OpenSpec current spec 和 active change。
4. Normalize：生成 Goal Teams requirement/AC refs 和 artifact graph。
5. Route：根据 Profile 为 worker 选择 Superpowers skills。
6. Execute：成员在授权 workspace 中实现，并产生真实 run evidence。
7. Review：进行 task-level spec/quality review。
8. Audit：Goal Teams 验证 traceability、Evidence 和完成状态。
9. Optional Export：用户授权后 dry-run 写回 OpenSpec change/current truth。
10. Reconcile and Close：解决冲突、归档并更新 ledger。

### 15.2 降级流程

| 条件 | 行为 |
| --- | --- |
| OpenSpec 未安装 | Goal Teams 使用自己的 Requirement/SPEC artifact，不声明 OpenSpec 兼容 |
| OpenSpec 版本不支持 | 只读 raw reference 或进入 blocked，不执行写回 |
| Superpowers 未安装 | 使用 Goal Teams 标准 Member Packet 和项目既有工作流 |
| 某 Superpowers skill 缺失 | 跳过并记录 degraded capability，不伪造成功 |
| 宿主不支持 subagent/worktree | 降级单 Agent 或请求用户，不扩大文件权限 |
| 外部状态冲突 | 停止写回，生成 reconciliation report |

## 16. Context 与 Handoff

### 16.1 上下文与交接

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-24-CTX-01 | OpenSpec context 使用 index + summary + fetch recipe，不默认内联所有 specs | 大型规格库不淹没 member context |
| FR-24-CTX-02 | 每个 adapter 设置 byte/token budget | 超限产生 truncation diagnostic |
| FR-24-CTX-03 | Member 只收到任务依赖的 requirements、design refs 和 file scope | 无关 change 不进入 packet |
| FR-24-CTX-04 | Handoff 使用 task brief、implementer report、review package 三种稳定 schema | 上下文可跨会话恢复 |
| FR-24-CTX-05 | 所有外部引用记录版本、路径和 hash | 文件变化可检测 |

### 16.2 Cross-provider Traceability

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-24-TRC-01 | 为导入的 requirement 和 scenario 分配稳定 external_ref，并绑定 Goal Teams REQ/AC | 同一 source revision 重复导入不产生新 ID |
| FR-24-TRC-02 | 每个 acceptance-blocking AC 必须关联 Task、Check、Run 和 Evidence | 任何断链阻止 accepted |
| FR-24-TRC-03 | Traceability validator 输出 uncovered、orphan 和 stale 引用 | 报告能区分缺失映射、孤儿节点和 hash drift |
| FR-24-TRC-04 | 外部 source hash 改变后，旧 Task/Evidence 映射进入 stale | Completion Audit 不使用过期映射 |
| FR-24-TRC-05 | Trace report 同时记录 OpenSpec change、Git revision、Superpowers provider run 和 Goal Teams attempt | 能从 requirement 追溯到最终 Evidence |

## 17. 安全与写入控制

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-24-SAF-01 | Adapter 默认 read_only | 安装后不会自动写 OpenSpec 或 Git |
| FR-24-SAF-02 | 外部写入需要明确 user authorization | prompt 内部规则不能替代用户授权 |
| FR-24-SAF-03 | 写入前进行 path containment 和 symlink 检查 | 不允许越出授权 root |
| FR-24-SAF-04 | 所有 write plan 提供 diff、目标、rollback 和风险 | 用户能理解影响 |
| FR-24-SAF-05 | Archive、merge、branch finish 分别建 gate | 一个授权不自动扩展到其他动作 |
| FR-24-SAF-06 | Community schema/skill 记录来源和信任状态 | 未审查来源不能获得额外权限 |
| FR-24-SAF-07 | 外部 spec、skill、日志和 artifact 按不可信数据处理 | 其中的 prompt injection 不能改变规则优先级、权限或 locked scope |
| FR-24-SAF-08 | Adapter 不自动安装外部产品、修改 session hook 或执行来源不明脚本 | capability probe 保持只读 |

## 18. 互操作验收标准

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-24-001 | OpenSpec 1.5 active change 完整 | adapter 导入 | proposal、design、delta、tasks 和 provenance 均可查询 |
| AC-24-002 | OpenSpec artifact 文件存在 | 状态映射 | 只得到 artifact_available，不得到 accepted |
| AC-24-003 | tasks.md checkbox 已选中但无 Evidence | Completion Audit | 任务不得 accepted |
| AC-24-004 | MODIFIED delta 只含部分 scenario | dry-run merge | 检测歧义并阻止自动写回 |
| AC-24-005 | 两个 active changes 修改同一 requirement | reconcile | 输出 requirement-level conflict report |
| AC-24-006 | OpenSpec validate passed | 导入结果 | 记录 structural evidence，不自动证明实现 |
| AC-24-007 | 用户未授权写 OpenSpec | adapter export | 返回 authorization_required 且文件不变 |
| AC-24-008 | staging merge 中途失败 | export | current specs byte-equivalent 保持不变 |
| AC-24-009 | 编码任务启用 TDD skill | worker 执行 | 保存 RED 和 GREEN 两份不同 run evidence |
| AC-24-010 | 测试持续失败 | worker 调试 | 先生成 root-cause record，再修改实现 |
| AC-24-011 | implementer 声称 tests passed 但无 run evidence | reviewer 审查 | 拒绝完成声明 |
| AC-24-012 | worktree 操作未获授权 | Superpowers adapter 路由 | 不创建 worktree，选择允许的 fallback |
| AC-24-013 | Superpowers 不可用 | Goal Teams 运行 | 核心流程继续，记录 degraded capability |
| AC-24-014 | adapter 遇到未知外部字段 | import/export round-trip | 字段保留在 extensions |
| AC-24-015 | 外部 artifact 在导入后改变 | Completion Audit | hash drift 被发现，旧映射失效 |
| AC-24-016 | Goal Teams、OpenSpec 和 Git 状态冲突 | resume | 进入 reconciliation，不静默选择任一方 |
| AC-24-017 | 只安装 Goal Teams | capability probe | 不显示虚假 OpenSpec/Superpowers compatibility |
| AC-24-018 | 支持版本的混合场景完成 | benchmark | 保存输入、trace、成本、Evidence 和 score |
| AC-24-019 | 检测到未经 conformance 测试的产品版本 | compatibility report | detection=detected；version_support 按版本范围确定；未测试 capability=not_tested，不显示 compatible |
| AC-24-020 | 同一 Task 同时请求 Goal Teams 派发和 Superpowers delegate | orchestration guard 运行 | 只允许一个 owner，第二个请求被拒绝并记录 |
| AC-24-021 | 项目未安装 OpenSpec 或 Superpowers | Lite/Standard 任务运行 | 不加载 adapter 细则、不创建 adapter state、不新增阻塞任务 |
| AC-24-022 | 外部 proposal 含要求读取凭证或越出 scope 的指令 | adapter 导入并派发 | 内容仅作为数据保存，权限和 locked scope 不变 |
| AC-24-023 | 已有 V2.3 项目没有外部 provider | V2.4 migration dry-run | Goal Teams core ledger、TaskList 和 artifact 产生零语义 diff |
| AC-24-024 | V2.3 仅记录 OpenSpec/Superpowers coexistence-only | V2.4 migration | 生成 adapter binding；detection/version_support 分别记录，所有无报告 capability=not_tested |
| AC-24-025 | Adapter migration 在 staging 验证中失败 | rollback 运行 | V2.3 项目和外部产品文件 byte-equivalent 保持不变 |
| AC-24-026 | V2.3 任一 RG-23-01 至 RG-23-12 未通过 | V2.4 Release Gate 运行 | Foundation Gate 失败，V2.4 不得发布 |
| AC-24-027 | 迁移只需要建立 read-only binding | migration 执行 | 不运行外部写命令，不修改 OpenSpec、Git、hooks 或 Superpowers 安装 |
| AC-24-028 | OpenSpec requirement 已导入，且存在孤儿 Task、未绑定 Check 和旧 source hash Evidence | traceability validator 运行 | 输出 requirement→AC→Task→Check→Run→Evidence 断链和 stale 报告，并阻止 accepted |

## 19. V2.3 → V2.4 迁移与回滚

V2.4 建立在 V2.3 typed state、single-writer ledger、Evidence validator 和 Release Gate 上，不允许绕过 V2.3 基础合同直接安装 adapter。

### 19.1 迁移需求

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-24-MIG-01 | 迁移前验证 V2.3 schema version、ledger revision 和 RG-23-01 至 RG-23-12 报告 | 缺失或失败时只输出诊断，不写入 |
| FR-24-MIG-02 | 无外部 provider 的 V2.3 项目保持零语义变更 | V2.3 core artifact 和 ledger hash 不变 |
| FR-24-MIG-03 | legacy lead-only/coexistence 记录迁移为 versioned AdapterBinding | 初始 capability 只能是 not_tested，除非已有可验证 conformance report |
| FR-24-MIG-04 | Adapter state、mapping 和 provenance 在 staging 中生成并验证后原子启用 | 失败不留下半绑定 |
| FR-24-MIG-05 | 提供 disable、uninstall 和 rollback manifest | 可返回纯 V2.3 core 模式且不删除外部产品数据 |
| FR-24-MIG-06 | 迁移默认只读，不运行 OpenSpec write/archive、Git mutation、hook 或外部安装 | 任何写入必须进入独立授权流程 |

### 19.2 迁移步骤

1. 读取 V2.3 release manifest、schema、ledger revision 和 Gate 报告。
2. 探测外部产品与版本，但不执行修改命令。
3. 生成 compatibility report，所有未验证 capability 初始为 not_tested。
4. 把旧 coexistence/lead-only 记录投影为 AdapterBinding，并保留 provenance。
5. 在 staging 生成 adapter state、mapping index 和 rollback manifest。
6. 运行 schema、authority、no-provider、read-only 和 prompt-injection checks。
7. 验证通过后原子启用；否则删除 staging 并保持 V2.3 状态不变。
8. 后续 export、sync、delegate 或 hook 能力分别走独立授权和 Release Gate。

### 19.3 回滚不变量

- 回滚不得删除或改写 OpenSpec、Superpowers、Git 或 V2.3 ledger。
- 回滚只移除 V2.4 adapter binding、cache 和 capability projection。
- 所有外部 provenance 保留在 rollback report 中。
- 已经显式授权并完成的外部写入不能伪装成“自动回滚”；必须使用对应产品的独立逆向计划。

## 20. Benchmark 设计

### 19.1 必测场景

| ID | 场景 | 主要风险 |
| --- | --- | --- |
| BENCH-24-01 | 导入现有 OpenSpec change 并生成 Goal Teams traceability | 字段丢失和重复规格 |
| BENCH-24-02 | OpenSpec partial MODIFIED 冲突 | 双 merge 语义 |
| BENCH-24-03 | Goal Teams + Superpowers TDD 实现 | 报告代替真实 RED/GREEN |
| BENCH-24-04 | 系统化调试失败案例 | 随机补丁和假根因 |
| BENCH-24-05 | 中断后跨会话恢复 | 三方状态分叉 |
| BENCH-24-06 | OpenSpec + Superpowers + Goal Teams 完整组合 | 权威冲突和上下文成本 |
| BENCH-24-07 | 外部产品缺失或版本不支持 | 降级可靠性 |
| BENCH-24-08 | 未授权写回和路径穿越 | 安全边界 |

### 19.2 评测指标

| 指标 | 定义 |
| --- | --- |
| Traceability Coverage | required AC 中有 Task、Check、Run、Evidence 的比例 |
| False Completion Rate | 无有效 Evidence 却被 accepted 的比例，目标为 0 |
| Mapping Fidelity | 支持字段 round-trip 不丢失的比例 |
| Conflict Detection | 预置冲突被识别的比例 |
| Context Cost | 基础与每任务实际加载字节/token |
| Execution Cost | 轮次、成员数、运行时间和 token/cost（可测时） |
| Recovery Accuracy | 中断恢复后无重复任务、无状态回退的比例 |
| Unauthorized Mutation | 未授权外部写入次数，目标为 0 |
| Review Freshness | 绑定当前 commit/hash 的关键检查比例 |

## 21. Release Gate

| Gate | 条件 | 失败结果 |
| --- | --- | --- |
| RG-24-00 Foundation Gate | 同一 baseline commit 的 V2.3 RG-23-01 至 RG-23-12 全部通过 | 阻止任何 V2.4 稳定发布 |
| RG-24-01 Baseline Gate | 支持版本、官方来源和能力表固定 | 阻止发布 |
| RG-24-02 Adapter Contract Gate | manifest、错误码、provenance、read-only 默认通过 | 阻止发布 |
| RG-24-03 OpenSpec Mapping Gate | artifact、delta、status 和 conflict fixtures 通过 | 阻止 OpenSpec compatibility 声明 |
| RG-24-04 Superpowers Mapping Gate | skill selection、TDD、debug、review 和 fallback fixtures 通过 | 阻止 Superpowers compatibility 声明 |
| RG-24-05 Authority Gate | SSOT owner 和三方冲突测试通过 | 阻止发布 |
| RG-24-06 Safety Gate | 未授权写入、路径 containment、dry-run、rollback 通过 | 阻止发布 |
| RG-24-07 Round-trip Gate | 支持字段和 extensions 不丢失 | 阻止写回能力 |
| RG-24-08 Behavior Gate | 八个真实 benchmark 有 trace、Evidence 和 score | 阻止正式兼容声明 |
| RG-24-09 Cost Gate | 组合流程相较单独 Goal Teams 的成本和收益有实测报告 | 允许发布但不得宣传未证实收益 |
| RG-24-10 Documentation Gate | README 明确支持矩阵、限制和降级 | 阻止发布 |
| RG-24-11 Orchestration Gate | skill_mode、delegate_mode、provider 切换和双 writer fixtures 通过 | 阻止 execution capability 标记为 verified |
| RG-24-12 Trust Gate | 外部 prompt injection、来源、hook 和未知脚本 fixtures 通过 | 阻止发布 |
| RG-24-13 Migration Gate | no-provider、coexistence-only、staging failure、rollback 和 read-only migration fixtures 通过 | 阻止发布 |

## 22. 分阶段实施

| 阶段 | 内容 | 退出条件 |
| --- | --- | --- |
| M24-0 V2.3 前置 | 状态、ledger、Evidence、Profile、行为测试与发布工程稳定 | V2.3 RG-23-01 至 RG-23-12 全部通过 |
| M24-1 Adapter SDK | manifest、provenance、错误码、read-only 和 capability probe | 通用 adapter tests 通过 |
| M24-2 OpenSpec Read Adapter | root/version 探测、artifact graph、delta 和状态映射 | Read-only fixtures 通过 |
| M24-3 Superpowers Worker Adapter | skill selection、task brief、TDD/debug/review evidence | Worker fixtures 通过 |
| M24-4 Reconciliation | SSOT owner、hash drift、冲突报告和恢复 | 混合状态 tests 通过 |
| M24-5 OpenSpec Write Adapter | dry-run、唯一 merge engine、staging、rollback | Safety/Round-trip Gate 通过 |
| M24-6 Behavior Eval | 八个 benchmark 和成本比较 | Behavior/Cost Gate 通过 |
| M24-7 Release Candidate | 支持矩阵、安装、文档和降级收口 | 全部 Release Gate 通过 |

## 23. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 外部产品快速变化 | Adapter 频繁失效 | 固定版本范围、contract tests、显式 unsupported |
| 三方都有状态文件 | 产生多个事实源 | 预先声明 authority table，冲突进入 reconciliation |
| OpenSpec merge 语义变化 | current truth 损坏 | 唯一 merge engine、dry-run、staging、原子替换 |
| Superpowers 流程过度使用 | 小任务成本上升 | Profile 和 skill selection reason |
| Community skills/schema 供应链风险 | 非预期指令或路径访问 | 来源、hash、信任状态和权限隔离 |
| 组合 eval 成本高 | CI 变慢 | PR 运行 deterministic contract tests，发布前运行完整 behavior suite |
| 兼容文案过度承诺 | 用户预期错误 | 支持矩阵绑定版本、能力和 Evidence |
| V2.3 基础未稳定 | Adapter 建在不闭合状态上 | V2.4 Foundation Gate 明确依赖 V2.3 RG-23-01 至 RG-23-12 |
| Adapter 迁移污染既有项目 | V2.3 或外部产品状态被意外改写 | 默认只读、staging、hash 比对、Migration Gate 和 rollback manifest |

## 24. 产品决策

| ID | 决策 | 结论 |
| --- | --- | --- |
| DEC-24-01 | 是否用 OpenSpec 取代 Goal Teams SPEC | 否；可作为上游权威规格源 |
| DEC-24-02 | 是否用 Superpowers 取代成员包 | 否；作为可选 worker execution policy |
| DEC-24-03 | OpenSpec file done 是否等于 Goal Teams accepted | 否 |
| DEC-24-04 | 是否默认写回 OpenSpec | 否；默认只读 |
| DEC-24-05 | 是否支持双 merge engine | 否；只能有一个确定性实现 |
| DEC-24-06 | 是否默认依赖 beta | 否 |
| DEC-24-07 | 外部产品缺失时是否阻塞 Goal Teams | 否；除非用户明确要求该能力 |
| DEC-24-08 | 何时可以使用“兼容” | 对应版本的 Adapter、fixtures 和 Behavior Gate 全部通过后 |

## 25. 最终建议

### 从 OpenSpec 借鉴

- Current Truth + Change Delta。
- Requirement 级 delta。
- Typed artifact graph。
- Dynamic instruction JSON。
- Context index、fetch recipe 和 byte budget。
- 跨工具 adapter registry。

### 从 Superpowers 借鉴

- 小而可组合的技能。
- Task brief、implementer report、review package。
- 真实 RED/GREEN Evidence。
- 系统化根因调试。
- Worktree/branch 生命周期。
- 完成前新鲜验证。
- 真实 skill-pressure/eval。

### Goal Teams 必须坚持

- 多成员 Owner、Validator 和 Conflict Policy。
- Requirement → AC → Task → Check → Run → Evidence → Audit。
- 安全、预算、权限和外部审批边界。
- UI 页面规格、E2E 和视觉证据。
- Completion Audit 作为最终闭包，而不是文件存在或成员自报完成。

## 26. 用户故事—需求—验收—门禁追踪

| User Story | 功能需求 | 验收标准 | Release Gate |
| --- | --- | --- | --- |
| US-24-001 | FR-24-OSP-01 至 06、12 | AC-24-001 至 003、006 | RG-24-03 |
| US-24-002 | FR-24-OSP-03、FR-24-CTX-05、FR-24-TRC-01 至 05 | AC-24-015、028 | RG-24-03、05、08 |
| US-24-003 | FR-24-ADP-09、FR-24-SPW-01 至 15 | AC-24-009 至 013、020 | RG-24-04、11 |
| US-24-004 | FR-24-SPW-04、07、08、15 | AC-24-010、011 | RG-24-04、08 |
| US-24-005 | FR-24-ADP-02、05、06、FR-24-OSP-07 至 10、FR-24-SAF-01 至 08 | AC-24-004、005、007、008、022 | RG-24-05、06、07、12 |
| US-24-006 | FR-24-ADP-03、04、FR-24-CTX-05 | AC-24-014、015 | RG-24-02、07 |
| US-24-007 | FR-24-ADP-01、07、FR-24-OSP-10、11、FR-24-MIG-* | AC-24-018、019、023 至 027 | RG-24-00、01、02、13 |
| US-24-008 | FR-24-ADP-08、10、FR-24-SPW-12 | AC-24-013、017、021 | RG-24-02、08 |
| US-24-009 | FR-24-ADP-01、07、FR-24-OSP-11 | AC-24-019 | RG-24-01、10 |
| US-24-010 | FR-24-CTX-01 至 05、FR-24-TRC-03 至 05、Benchmark 指标 | AC-24-018、028 | RG-24-08、09 |

## 27. 参考资料

### Goal Teams

- [Goal Teams V2.3 PRD](GoalTeams-PRD-V2.3.md)
- [Goal Teams SKILL](SKILL.md)
- [Goal Teams Runtime](references/goal-teams-runtime.md)
- [Automation Protocol](references/goal-teams-automation-protocol.md)
- [Production Pipeline](references/goal-teams-production-pipeline.md)

### OpenSpec

- [OpenSpec repository](https://github.com/Fission-AI/OpenSpec)
- [OpenSpec v1.5.0](https://github.com/Fission-AI/OpenSpec/releases/tag/v1.5.0)
- [OpenSpec v1.6.0-beta.1](https://github.com/Fission-AI/OpenSpec/releases/tag/v1.6.0-beta.1)
- [Concepts](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/docs/concepts.md)
- [Default schema](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/schemas/spec-driven/schema.yaml)
- [CLI documentation](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/docs/cli.md)
- [Customization and community schemas](https://github.com/Fission-AI/OpenSpec/blob/v1.5.0/docs/customization.md)

### Superpowers

- [Superpowers repository](https://github.com/obra/superpowers)
- [Superpowers v6.1.1](https://github.com/obra/superpowers/releases/tag/v6.1.1)
- [Superpowers workflow](https://github.com/obra/superpowers/blob/v6.1.1/README.md)
- [Subagent-driven development](https://github.com/obra/superpowers/blob/v6.1.1/skills/subagent-driven-development/SKILL.md)
- [Test-driven development](https://github.com/obra/superpowers/blob/v6.1.1/skills/test-driven-development/SKILL.md)
- [Systematic debugging](https://github.com/obra/superpowers/blob/v6.1.1/skills/systematic-debugging/SKILL.md)
- [Verification before completion](https://github.com/obra/superpowers/blob/v6.1.1/skills/verification-before-completion/SKILL.md)
