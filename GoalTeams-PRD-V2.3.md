---
type: Product Requirements Document
title: Goal Teams V2.3 产品需求文档
description: 将 Goal Teams V2.2 审计发现转化为自洽、可执行、可验证、可迁移的 V2.3 产品需求与发布门禁。
resource: https://github.com/vibe-coding-era/goal-teams
tags: [goal-teams, prd, v2.3, orchestration, validation, evidence]
timestamp: 2026-07-10T11:33:04+08:00
okf_version: "0.1"
goal_teams_version: "V2.2"
project_version: "V2.3"
target_goal_teams_version: "V2.3"
status: Draft
owner_subagent: "/root"
validator_subagent: "/root/prd_final_review"
owner_role: Goal Lead
validator_role: Independent Completion Auditor
source_ssot: goal-teams.md
audit_baseline_version: "V2.2"
audit_baseline_commit: 79ffa09610c4d5cf3d1413e49a050da379414642
---

# Goal Teams V2.3 产品需求文档

## 1. 文档摘要

Goal Teams V2.3 的任务不是继续增加规则，而是把 V2.2 已有的治理思想转换成一套自洽、机器可检查、并发安全、能够按任务风险渐进加载的执行契约。

V2.2 已具备值得保留的核心资产：

- SPEC → Harness → Evidence → Audit 的验证链。
- Owner、独立 Validator、Reviewer 和 Completion Auditor 的职责意识。
- 后端架构先行、测试设计与执行分离、UI E2E 和像素证据。
- 安全边界、预算门、冲突策略和长任务续跑协议。
- TaskList、memory、版本化输出目录和 OKF 文档规范。

当前根本问题是：规则、示例、校验器和宿主运行能力尚未形成同一个事实系统。V2.3 必须优先解决契约冲突、状态闭包、中央账本并发、证据真实性、行为级回归和上下文成本。

## 2. 产品判断

Goal Teams 的目标定位是：

> 面向复杂、高风险、长任务的多 Agent 治理与验收编排层。

V2.3 不宣称自身是持久后台 runner、CI/CD 平台或生产审批系统。它应在宿主支持的能力范围内提供确定性协议，并在能力不足时显式降级。

## 3. 目标

| ID | 目标 | 成功定义 |
| --- | --- | --- |
| G-23-01 | 契约自洽 | Response Contract、规划、状态、完成和失败协议不存在互斥要求 |
| G-23-02 | 状态可计算 | 任意 Task、Run 和 Loop 都能得到唯一且可解释的状态 |
| G-23-03 | 并发安全 | 多成员不得直接竞争写中央 TaskList；所有更新可重放、可检测冲突 |
| G-23-04 | 证据可信 | Validator 验证事实和来源，而不是只验证非空字符串 |
| G-23-05 | 可追溯 | Requirement、AC、Task、Check、Run、Evidence 和 Audit 可机械关联 |
| G-23-06 | 渐进严格 | 小任务可使用 Lite；复杂或受监管任务可升级到 Full 或 Regulated |
| G-23-07 | 宿主适配 | 启动时识别命名、上下文、并发、模型、遥测和恢复能力 |
| G-23-08 | 发布可信 | canonical example、负向 fixtures 和真实行为测试共同决定发布结果 |
| G-23-09 | 迁移安全 | V2.2 输出可读取、可迁移，不产生两个可写 SSOT |
| G-23-10 | 文案诚实 | 对续跑、兼容、验证和运行时能力的描述不超过真实实现 |

## 4. 非目标

- 不在 V2.3 内建设独立持久化后台调度服务。
- 不把 Goal Teams 描述为生产 CI/CD、审批、支付或权限系统。
- 不在所有任务上强制 Full Profile、完整 TDD 或双重复核。
- 不在 V2.3 内实现完整 OpenSpec 或 Superpowers adapter；互操作需求进入 V2.4。
- 不替代项目自己的测试框架、代码规范、Git 策略或安全审批。
- 不擅自为仓库选择开源 License；只要求 owner 做出明确发布决定。

## 5. 目标用户与用户故事

### 5.1 用户角色

| 角色 | 核心诉求 |
| --- | --- |
| Skill Maintainer | 修改一处 schema 后能确定性生成或校验所有派生规则 |
| Goal Lead | 能根据风险和宿主能力选择正确流程并得到唯一下一步 |
| Member Agent | 只接收完成任务所需的上下文，并用结构化结果交接 |
| Reviewer / Auditor | 能独立验证 artifact、测试执行和证据来源 |
| Skill Adopter | 能安全安装、升级、迁移和卸载，不破坏已有配置 |
| Repository Owner | 能从 Release Gate 判断版本是否真实可发布 |

### 5.2 用户故事

| ID | 用户故事 | 价值 |
| --- | --- | --- |
| US-23-001 | 作为 Goal Lead，我想区分观察、假设、计划和结论，以便既能规划又不把未验证信息当作事实 | 消除响应规范冲突 |
| US-23-002 | 作为 Goal Lead，我想从正交状态机计算目标是否完成，以便避免 complete 与 blocked 同时成立 | 完成语义唯一 |
| US-23-003 | 作为 Member，我想提交带 revision 的结构化 patch，而不是直接编辑中央账本 | 避免并发覆盖 |
| US-23-004 | 作为 Auditor，我想验证证据文件、执行身份、退出码和 hash | 防止证据伪造 |
| US-23-005 | 作为需求分析者，我想从每个 AC 追踪到测试和证据 | 发现漏测和孤儿任务 |
| US-23-006 | 作为小任务用户，我想选择 Lite Profile | 降低启动和协作成本 |
| US-23-007 | 作为高风险任务用户，我想选择 Regulated Profile | 获得审批和双重复核门禁 |
| US-23-008 | 作为 Lead，我想在派发前知道宿主是否支持自定义 agent、上下文隔离和遥测 | 防止声明无法执行 |
| US-23-009 | 作为维护者，我想让 canonical example 经过真实 validator | 防止发布假绿 |
| US-23-010 | 作为安装者，我想要原子安装和可恢复备份 | 防止半安装和配置覆盖 |
| US-23-011 | 作为 UI Reviewer，我想在稳定的浏览器、字体和 DPR 条件下比较截图 | 降低像素误报 |
| US-23-012 | 作为 V2.2 用户，我想迁移旧 tasklist.md 而不产生双 SSOT | 保持历史可用 |
| US-23-013 | 作为仓库维护者，我想运行真实行为 eval，而不是只检查关键词 | 证明 Skill 的行为能力 |
| US-23-014 | 作为代码库维护者，我希望生成的代码和测试语言遵循仓库约定 | 避免中文默认侵入代码规范 |

## 6. 严重级别

| 级别 | 定义 |
| --- | --- |
| P0 | 会让协议互相不可满足、状态不唯一、证据失真或发布门禁产生错误成功 |
| P1 | 会显著降低可执行性、可恢复性、兼容性、效率或真实验证覆盖 |
| P2 | 不直接破坏正确性，但增加维护成本、采用风险、歧义或不必要仪式 |

## 7. V2.2 全量问题登记

### 7.1 P0 问题

| ID | 问题 | 当前表现 | 影响 | 对应需求 |
| --- | --- | --- | --- | --- |
| ISS-23-P0-01 | Response Contract 与规划冲突 | RULES 禁止推断和未来动作，Planning 又要求推断版本、输出计划和下一步 | Lead 无法同时遵守两套规则 | FR-CON-01、FR-CON-02 |
| ISS-23-P0-02 | 状态机不闭合 | handoff 状态缺少规范使用的状态；blocked、deferred、complete、stop_budget 混用 | 同一运行可得到多个互斥结论 | FR-STA-01 至 FR-STA-05 |
| ISS-23-P0-03 | 中央 TaskList 多写者 | 所有成员被要求更新 TaskList，同时 Conflict Policy 又要求单写者 | 丢更新、覆盖、脏账本、无法恢复 | FR-LED-01 至 FR-LED-07 |
| ISS-23-P0-04 | 总校验存在关键假绿 | check.sh 主要调用 self-test 和结构/关键词检查，未把 canonical 输出送入完整验证链 | 发布通过不等于契约真实成立 | FR-VAL-08、FR-EVL-01 |
| ISS-23-P0-05 | canonical example 违反自身契约 | 缺 OKF frontmatter、memory、Page Spec、canonical TaskList 和完整任务；Auditor 自审 | 示例会训练 Agent 产生错误输出 | FR-EXA-01 至 FR-EXA-05 |
| ISS-23-P0-06 | Evidence validator 接受伪造通过 | 不检查 evidence path、字段类型、工具执行、身份独立性和 artifact binding | 虚构证据也能被标记为 passed | FR-VAL-01 至 FR-VAL-07 |

### 7.2 P1 问题

| ID | 问题 | 当前表现 | 影响 | 对应需求 |
| --- | --- | --- | --- | --- |
| ISS-23-P1-01 | 只规划语义冲突 | 一处要求创建规划文件，另一处要求 read-only 且不编辑 | 用户授权和执行边界不清 | FR-PLN-01、FR-PLN-02 |
| ISS-23-P1-02 | 官方示例仍使用旧路径 | runtime 示例引用版本目录外 tasklist、progress 和 spec | 不同 artifact version 可能混写 | FR-PTH-01、FR-PTH-02 |
| ISS-23-P1-03 | TaskList.md 与 tasklist.md 双 SSOT | 新规范与兼容逻辑同时允许两个名字 | 大小写敏感系统发生漂移 | FR-PTH-03、FR-MIG-01 |
| ISS-23-P1-04 | 自动续跑描述超过运行时 | Skill 没有后台 runner，却容易被理解为持久自动恢复 | 用户预期错误 | FR-CAP-05、FR-DOC-04 |
| ISS-23-P1-05 | 身份字段混用 | agent type、run ID、member ID、中文名和 transport handle 被视为同一字段 | 无法唯一追踪多个实例或证明独立检查 | FR-IDN-01 至 FR-IDN-04 |
| ISS-23-P1-06 | fallback 规则冲突 | 一处禁止自动使用 team_*，另一处允许 goal_* 不可用时自动 fallback | 相同故障产生不同处置 | FR-CAP-03、FR-CAP-04 |
| ISS-23-P1-07 | 无任务复杂度 Profile | 小任务也可能承受 17 类任务、3–6 成员和完整门禁 | token、时间和协作成本过高 | FR-PRF-01 至 FR-PRF-06 |
| ISS-23-P1-08 | 渐进加载被重复规则抵消 | 基础强制规则约 36 KB，default prompt 重复 UI、TDD、Loop 等内容 | 高上下文成本和规则漂移 | FR-CTX-01 至 FR-CTX-05 |
| ISS-23-P1-09 | AC 缺少稳定追踪 ID | TaskList 和 Harness 没有 requirement、story、AC、test、evidence 引用 | 无法机械发现漏测 | FR-TRC-01 至 FR-TRC-06 |
| ISS-23-P1-10 | Dual Review 适用范围膨胀 | 从比较/校验类任务扩展为几乎所有完成任务 | 纯语义任务也可能被无意义脚本阻塞 | FR-REV-01 至 FR-REV-04 |
| ISS-23-P1-11 | 安装流程非原子 | 先 rsync、复制和修改用户配置，再执行验证 | 失败后留下半安装状态 | FR-INS-01 至 FR-INS-06 |
| ISS-23-P1-12 | Budget Gate 缺真实遥测 | 规则要求 token/cost，但宿主未必提供；又禁止估算 | Gate 不能可靠触发 | FR-CAP-06、FR-LOP-04 |
| ISS-23-P1-13 | loop-state 缺幂等信息 | 缺 commit、artifact version、revision、attempt、last event 和 updated_at | 恢复可能重复派发或覆盖新状态 | FR-LOP-01 至 FR-LOP-06 |
| ISS-23-P1-14 | 当前 Codex 命名协议不兼容 | 中文动态 subagent ID 与宿主 task_name 字符限制冲突 | 规范在当前宿主上不可实现 | FR-CAP-01、FR-IDN-01 |
| ISS-23-P1-15 | 上下文隔离未经能力协商 | 规则假定最小独立上下文，但宿主可能默认继承历史并共享文件系统 | 成本、泄漏和冲突假设失真 | FR-CAP-02、FR-CTX-04 |
| ISS-23-P1-16 | Routing fixtures 不测试路由行为 | 只检查 SKILL 表格行包含哪些字符串 | 组合条件、优先级和互斥规则未测试 | FR-EVL-02、FR-ROU-01 |
| ISS-23-P1-17 | Benchmark 不执行真实任务 | runner 只检查文件名和关键词，没有 run、score 或 evidence | 无法比较质量、成本和恢复能力 | FR-EVL-03 至 FR-EVL-07 |
| ISS-23-P1-18 | YAML 依赖未纳入契约 | validator 依赖 PyYAML，但 check.sh 不探测，官方 sample 当前环境无法验证 | canonical contract 不可移植 | FR-VAL-09、FR-INS-03 |
| ISS-23-P1-19 | UI 条件规则漂移 | 参考图要求从复刻任务扩大到所有 UI 任务 | 原创 UI 被错误阻塞 | FR-UI-01、FR-UI-02 |
| ISS-23-P1-20 | Pixel diff 过于脆弱 | 任意非零 RGB 差异计为 changed，MAE 不参与通过判定 | 字体抗锯齿、DPR 等产生误报 | FR-UI-03 至 FR-UI-07 |
| ISS-23-P1-21 | OpenSpec/Superpowers 兼容只是避让 | 当前实现仅切换 lead-only，没有 schema、状态或命令 adapter | “兼容”声明不可验证 | FR-DOC-05、FR-MIG-04；完整方案见 V2.4 |
| ISS-23-P1-22 | 规则同步依赖人工复制 | VERSION、SKILL、runtime、packets、members、README 多处重复字段和文案 | 版本及语义持续漂移 | FR-SCH-01 至 FR-SCH-05 |
| ISS-23-P1-23 | Evidence 与日志缺少统一脱敏和信任边界 | 命令输出、路径、URL、memory 和事件记录可能包含凭证或个人信息；外部 Evidence 可能无法本地验证 | 敏感信息进入仓库，或把外部引用误写成本地已验证事实 | FR-SEC-01 至 FR-SEC-05 |

### 7.3 P2 问题

| ID | 问题 | 当前表现 | 影响 | 对应需求 |
| --- | --- | --- | --- | --- |
| ISS-23-P2-01 | QA、Reviewer、Auditor 重叠 | 三者都重复检查测试、TaskList、证据和门禁 | token 与责任边界浪费 | FR-ROL-01 至 FR-ROL-04 |
| ISS-23-P2-02 | 中文默认侵入代码约定 | 代码注释、用户字符串和测试名默认中文 | 破坏英文仓库、i18n 和测试命名规范 | FR-DOC-01 |
| ISS-23-P2-03 | 固定启动语和历史追问 | 即使上下文已经明确仍要求复述版本和询问资料 | 首轮冗余且冲突执行优先 | FR-DOC-02、FR-DOC-03 |
| ISS-23-P2-04 | 缺仓库级 CI | 发布检查依赖维护者手工运行 | 回归可能进入 main | FR-REL-01 |
| ISS-23-P2-05 | License 决策缺失 | README 明示未选择 License | 外部采用和分发风险 | FR-REL-02 |
| ISS-23-P2-06 | 文案与能力边界不同步 | README 的“自动”“兼容”等词强于细则中的能力声明 | 误导用户选型 | FR-DOC-04、FR-DOC-05 |

## 8. 设计原则

1. 一份机器 schema，多份派生视图。
2. 未经验证不得宣称成功，但允许明确标记的假设和计划。
3. 中央账本单写者；成员通过事件或 patch 交接。
4. 文件存在表示 available，不表示 accepted。
5. 每个完成结论必须能追溯到执行证据。
6. Profile 按风险升级，不按仪式默认拉满。
7. 宿主能力必须探测，不得凭规则假设。
8. 兼容必须有 adapter 和 fixture；否则只称共存。
9. canonical example 是可执行测试资产，不是宣传截图。
10. 失败、部分完成和阻塞必须是合法的一等结果。

## 9. 目标架构

    User Goal / Requirement
              |
              v
    Requirement + AC Registry
              |
              v
    Typed Artifact DAG and Router
              |
              v
    Goal Lead / Ledger Owner
       |                    |
       v                    v
    Member Goal Packet   Append-only Events
       |                    |
       v                    v
    Artifact + Run Report -> Deterministic Reducer -> TaskList.md View
              |
              v
    Harness -> Evidence -> Independent Review -> Completion Audit

TaskList.md 只能由 reducer 从 ledger 确定性生成，是人类可读投影视图。ledger owner 只能验收和合并 event/patch，再调用 reducer；不得手工维护 TaskList.md 这一第二事实源。append-only events 才是可重放事实记录。

## 10. 功能需求

### 10.1 契约与优先级

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-CON-01 | Response Contract 必须允许 Observation、Assumption、Plan、Proposal、Conclusion 和 Evidence 六类明确标签 | 规划响应可以合法描述未来动作；未验证结论仍被拒绝 |
| FR-CON-02 | 禁止项改为“不得把未验证信息写成已验证事实”，而不是笼统禁止推断和计划 | RULES 与 planning 静态一致性测试通过 |
| FR-CON-03 | 定义规则优先级：系统/用户 → 项目 AGENTS → invariants → 条件规则 → Lead → Member | 冲突测试能返回唯一胜出规则和原因 |
| FR-CON-04 | 所有“完成”“通过”“验证”术语必须绑定状态定义 | 文档扫描不存在未定义完成术语 |

### 10.2 正交状态模型

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-STA-01 | task_state 仅允许 planned、running、review、accepted、blocked、deferred、cancelled | schema 拒绝其他值 |
| FR-STA-02 | run_outcome 仅允许 achieved、partial、blocked、aborted | run 关闭时必须有唯一 outcome |
| FR-STA-03 | loop_decision 仅允许 continue、replan、stop | loop 决策不再兼作任务状态 |
| FR-STA-04 | 每个任务具有 required_for_done 和 acceptance_blocking | 非阻断 deferred 不妨碍 achieved；阻断任务未 accepted 时不得 achieved |
| FR-STA-05 | 状态转换由机器规则定义，并拒绝非法回退或跳跃 | accepted 不能无审计地直接回到 running；所有转换有 event |
| FR-STA-06 | check_state 仅允许 not_required、not_started、running、passed、failed、blocked、waived | 独立检查状态不再混入 task_state；waived 必须绑定批准证据 |

建议的完成计算：

    goal_achieved =
      all(required_for_done tasks have task_state = accepted)
      and no acceptance_blocking issue remains open
      and completion audit = passed

### 10.3 单写者账本

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-LED-01 | 成员不得直接自由编辑中央 TaskList | Member prompt 和实际写入权限测试一致 |
| FR-LED-02 | 成员提交结构化 task_patch 或 append-only event | patch 包含 task_id、attempt_id、base_revision、actor、timestamp |
| FR-LED-03 | Goal Lead 或 ledger-owner 是唯一 event/patch 合并者，TaskList 只能由 reducer 生成 | 并发测试中只有一个合并者提交 ledger，手工编辑投影视图会失败 |
| FR-LED-04 | 使用 revision/CAS 检测并发冲突 | 过期 base_revision 被拒绝并返回 rebase 信息 |
| FR-LED-05 | 每个 event 具有稳定 event_id，重复 event 幂等 | 同一 event 重放两次结果不变 |
| FR-LED-06 | TaskList.md 从 ledger 状态确定性生成 | 相同 event log 生成 byte-equivalent 结果 |
| FR-LED-07 | owner 与 validator 必须引用具体 member_id 或 agent_run_id | 角色候选项和同一实例自审均被拒绝 |

### 10.4 身份模型

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-IDN-01 | 分离 agent_type、agent_run_id、member_id、display_name、transport_handle | schema 和示例不再复用同一字段 |
| FR-IDN-02 | display_name 可本地化，不承担 transport 路由 | 中文名可展示，宿主合法 handle 可派发 |
| FR-IDN-03 | reviewer independence 以具体 run/member 身份判断 | 同一实例不同显示名不能绕过独立性检查 |
| FR-IDN-04 | 每次重试生成新 attempt_id，并保留 parent_attempt_id | 审计能重建重试链 |

### 10.5 Requirement、AC 与证据追踪

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-TRC-01 | Requirement、User Story、AC、Task、Check、Test Run、Evidence 使用稳定 ID | ID 在版本目录内唯一 |
| FR-TRC-02 | Task 必须声明 requirement_refs 和 acceptance_criteria_refs | required task 缺引用时结构校验失败 |
| FR-TRC-03 | Harness check 必须声明验证哪些 AC | 无 AC 引用的强制 check 被拒绝 |
| FR-TRC-04 | Evidence 必须引用 check_id 和 run_id | 孤立 evidence 不能计入覆盖 |
| FR-TRC-05 | 提供 traceability validator | 每个 required AC 至少映射一个 check 和一份有效 evidence |
| FR-TRC-06 | 输出 orphan 和 uncovered 报告 | 发布门禁对阻断性 uncovered AC 失败 |

### 10.6 Evidence 与 Validator

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-VAL-01 | Validator 严格校验字段类型、枚举和必填关系 | string 不能冒充 list/object |
| FR-VAL-02 | evidence path 必须存在、位于允许根目录并通过 containment 检查 | 不存在路径和路径穿越均失败 |
| FR-VAL-03 | Evidence 记录 SHA-256、大小、mtime、producer 和 artifact_ref | 文件被修改后旧证据失效 |
| FR-VAL-04 | 命令证据记录 argv、cwd、started_at、ended_at、exit_code 和日志路径 | 只有 passed 字符串不能通过 |
| FR-VAL-05 | 测试结果绑定具体 attempt、commit/revision 和环境指纹 | 旧 commit 结果不能验证新 artifact |
| FR-VAL-06 | Dual Review 校验 author 与 reviewer 独立，并验证真实 tool result | 自审和虚构 tool 被拒绝 |
| FR-VAL-07 | 区分 structural_valid、executed、semantically_reviewed、accepted | 任一单层通过不得自动等同 accepted |
| FR-VAL-08 | check.sh 必须把 canonical example 送入真实 validators | 移除示例中的必填字段会导致 check.sh 非零退出 |
| FR-VAL-09 | YAML 方案必须声明并检测 PyYAML，或改用零依赖 canonical JSON | 干净环境能验证官方 sample；缺依赖时给出安装指令和非零退出 |
| FR-VAL-10 | Validator 必须提供稳定 JSON 输出和错误码 | 自动化消费者无需解析自由文本 |

### 10.7 安全、脱敏与 Evidence 信任边界

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-SEC-01 | Evidence、日志、memory、event ledger 和 failure report 写入前执行 secret redaction | token、password、authorization header、常见私钥和敏感 URL query fixture 不出现在产物 |
| FR-SEC-02 | Evidence path 使用允许根目录和最小必要披露；报告默认使用相对路径或受控摘要 | 用户主目录和无关绝对路径不被批量泄露 |
| FR-SEC-03 | 每份 Evidence 记录 trust_level：local_verified、externally_referenced、manual_observation 或 unverified | 外部 URL 和人工声明不能伪装成本地 verified |
| FR-SEC-04 | 外部 artifact、日志和网页内容按不可信数据处理，不得提升为高优先级指令 | prompt injection fixture 不能扩大权限或改变 locked scope |
| FR-SEC-05 | 脱敏必须保留可审计关联，使用稳定 digest 或占位符而非静默删除上下文 | Reviewer 能确认同一秘密被一致遮盖且不看到原值 |

### 10.8 示例契约

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-EXA-01 | canonical example 所有非保留 Markdown 均有可解析 OKF frontmatter | OKF validator 100% 通过 |
| FR-EXA-02 | 示例包含 index.md、memory.md、版本目录和 canonical TaskList.md | 目录 conformance 通过 |
| FR-EXA-03 | UI 示例包含 page-spec-card、组件库元数据、交互状态和视觉证据 | UI conformance 通过 |
| FR-EXA-04 | Owner 与 Validator 为不同具体身份 | 独立性 validator 通过 |
| FR-EXA-05 | 示例同时提供成功、阻塞、失败和恢复案例 | 状态机所有关键分支都有 fixture |

### 10.9 规划模式

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-PLN-01 | plan_preview 是聊天内、只读、不创建文件的规划 | read-only sandbox 中可完整完成 |
| FR-PLN-02 | persisted_plan 是经用户授权后写入版本目录的规划 | 未授权写入时必须阻止 |
| FR-PLN-03 | 两种模式都允许明确标记假设和待确认项 | 不因“禁止推断”而失去规划能力 |

### 10.10 Profile 与渐进严格

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-PRF-01 | 提供 Lite、Standard、Full、Regulated 四个 Profile | schema、文档和 routing fixture 均可识别 |
| FR-PRF-02 | Profile 由风险、任务规模、外部写入、安全等级和用户要求决定 | 同一输入得到确定性 Profile 或解释性建议 |
| FR-PRF-03 | Lite 不强制 17 类任务和 3–6 成员 | 小型文档/修复场景的 N/A 行显著减少 |
| FR-PRF-04 | Standard 对关键 artifact 强制独立检查 | 普通功能开发保留必要质量门 |
| FR-PRF-05 | Full 启用完整 Harness、Evidence、Loop 和 UI/测试条件规则 | 复杂任务覆盖 V2.2 核心能力 |
| FR-PRF-06 | Regulated 增加审批、双重复核、审计保留和严格失败门 | 受监管 fixture 不允许绕过 |

### 10.11 路由与上下文

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-ROU-01 | 路由实现为可测试的纯函数：task_features → profile + rule_set | fixtures 断言完整输出集合和顺序 |
| FR-ROU-02 | 多条件同时触发时按声明优先级合并，不靠表格字符串 | UI + 长任务 + 外部写入组合测试通过 |
| FR-CTX-01 | SKILL.md 只保留触发、路由和最小不变量 | 核心入口保持低上下文成本 |
| FR-CTX-02 | 详细 schema、模板和领域协议按需加载 | 非 UI 任务不加载 pixel/E2E 规则 |
| FR-CTX-03 | 默认基础包目标不超过 12 KB；超限必须有报告 | context-budget 检查纳入 CI |
| FR-CTX-04 | Member Goal Packet 只包含任务需要的 context refs 和 fetch recipe | 不默认复制完整历史 |
| FR-CTX-05 | agents/openai.yaml 不复制整套协议 | 与 SKILL.md 的重复规则由生成检查阻止 |

### 10.12 宿主能力与降级

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-CAP-01 | 启动时生成 capability manifest | 至少记录命名限制、自定义 agent、并发、上下文继承、共享文件系统和恢复能力 |
| FR-CAP-02 | 对上下文隔离和共享工作区进行显式协商 | 不再无条件宣称 isolated context |
| FR-CAP-03 | fallback 仅在能力等价且权限不扩大的情况下自动发生 | 其他情况必须请求用户或进入 blocked |
| FR-CAP-04 | 每次降级记录 degraded_capability、reason 和 impact | Completion Audit 能看到降级 |
| FR-CAP-05 | 自动续跑描述限定为会话内、宿主支持时的协议驱动续跑 | README、SKILL、runtime 用词一致 |
| FR-CAP-06 | token/cost 遥测不可用时，不得伪造；Budget Gate 退化为 round/time/member/file-size 指标 | 无遥测 fixture 得到确定性降级 |

### 10.13 Loop 与恢复

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-LOP-01 | loop-state 包含 artifact_version、workspace_commit、ledger_revision | 恢复前能判断 checkpoint 是否陈旧 |
| FR-LOP-02 | 记录 attempt_id、last_event_id、updated_at 和 active_member_runs | 重放不会重复派发已完成 attempt |
| FR-LOP-03 | 恢复先执行 reconciliation，再决定 continue/replan/stop | 文件状态与 ledger 冲突时不静默覆盖 |
| FR-LOP-04 | Budget Gate 记录可测指标及其来源 | 每个 gate 结果能区分 measured 与 unavailable |
| FR-LOP-05 | stop 只是循环决定，不自动等于 achieved | stop_budget 可得到 partial 或 blocked |
| FR-LOP-06 | checkpoint 写入必须原子化 | 中断后不会读取半个 JSON |

### 10.14 Review 分级与角色边界

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-REV-01 | 定义 structural、comparison、safety、semantic 四类 review_class | 每类有明确强制项 |
| FR-REV-02 | 只有适用类别强制 LLM + script 双重复核 | 无确定性脚本的语义任务可记录合理 N/A |
| FR-REV-03 | script 结果和 LLM 判断必须绑定同一 artifact version/hash | 不能混用旧结果 |
| FR-REV-04 | 不适用原因必须结构化并由独立 reviewer 接受 | 任意自由文本不能自动绕过 |
| FR-ROL-01 | QA 负责执行测试和记录运行证据 | 不重复做全局完成判断 |
| FR-ROL-02 | Reviewer 负责规格、代码和风险语义审查 | 不代替测试 runner |
| FR-ROL-03 | Completion Auditor 只负责闭包、状态和证据一致性 | 不重复实现领域测试 |
| FR-ROL-04 | 同一 attempt 的职责不得由同一 agent_run_id 兼任 | Regulated Profile 强制执行 |

### 10.15 UI 与像素证据

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-UI-01 | 只有 replica/reference-driven UI 强制参考图 | 原创 UI 不因缺参考图被阻塞 |
| FR-UI-02 | 页面规格卡明确 ui_mode、reference_source 和 component_library | 路由条件可机器判断 |
| FR-UI-03 | pixel diff 支持颜色容差和动态区域 mask | 字体抗锯齿小差异不再全部计为 changed |
| FR-UI-04 | 证据记录浏览器、版本、viewport、DPR、字体和操作系统 | 不同环境结果不能直接混比 |
| FR-UI-05 | 通过标准综合 changed ratio、误差指标和关键区域断言 | MAE 不再只计算不参与判定 |
| FR-UI-06 | 支持整页和组件局部证据 | 局部回归可定位 |
| FR-UI-07 | baseline 更新必须有 reviewer 和变更原因 | 禁止用更新 baseline 掩盖回归 |

### 10.16 路径与迁移

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-PTH-01 | 所有 SSOT artifact 写入 versions/artifact_version | 静态检查禁止新示例写根目录 tasklist/spec/progress |
| FR-PTH-02 | 路径从机器 schema 生成，不在 prompt 中手写多份 | 修改路径规则只需改一个源 |
| FR-PTH-03 | 新写入只允许 TaskList.md | case-sensitive fixture 不产生两个文件 |
| FR-MIG-01 | tasklist.md 仅作为旧版读取输入，迁移后写 TaskList.md | 迁移报告记录来源和 hash |
| FR-MIG-02 | V2.2 状态映射到 V2.3 正交状态并报告歧义 | 无法无损映射时进入 manual_review |
| FR-MIG-03 | 迁移工具先 dry-run，再原子写入 | 失败保留原目录 |
| FR-MIG-04 | V2.3 文案将 OpenSpec/Superpowers 从“兼容”改为“可共存”，直到 V2.4 adapter 通过 | README 与实现一致 |

### 10.17 Schema 单一来源

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-SCH-01 | 建立 versioned machine schema，定义状态、角色、artifact、证据和路径 | schema 有版本和迁移策略 |
| FR-SCH-02 | prompts、示例、validator 常量由 schema 生成或对 schema 校验 | 人工漂移测试失败 |
| FR-SCH-03 | VERSION 是发布版本唯一来源 | SKILL、README、启动语与 runtime 自动检查一致 |
| FR-SCH-04 | 未知扩展字段可保留，未知核心枚举必须拒绝 | 向前兼容与核心确定性兼得 |
| FR-SCH-05 | 所有机器输出使用统一 envelope、字段 casing、schema_version 和 error code | 消费者只实现一种解析方式 |

### 10.18 安装、发布和文档

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-INS-01 | 安装前验证源目录 | 无效源不会改动目标 |
| FR-INS-02 | 安装到 staging，验证后原子替换 | 人为制造验证失败时旧安装保持可用 |
| FR-INS-03 | 探测 Python、tomllib、PyYAML 或其他声明依赖 | 缺依赖给出可操作诊断 |
| FR-INS-04 | 修改 fallback agent 必须显式 opt-in、显示 diff 并时间戳备份 | 默认安装不改用户已有配置 |
| FR-INS-05 | 提供 uninstall 和 rollback | 能恢复上一个已验证版本 |
| FR-INS-06 | 安装报告记录来源 commit、目标路径、版本和校验结果 | 可审计 |
| FR-DOC-01 | 用户沟通默认中文；代码、测试、注释和产品字符串遵循项目约定 | 英文仓库 fixture 不被强制中文化 |
| FR-DOC-02 | 启动身份仅在显式调用或首次必要时简短展示 | 已有上下文时不重复仪式 |
| FR-DOC-03 | 只有缺少信息会改变执行时才询问历史资料 | 已提供路径时直接进入工作 |
| FR-DOC-04 | 文档区分 protocol、host capability 和 external runner | 不再暗示仓库拥有后台服务 |
| FR-DOC-05 | “兼容”必须绑定 adapter、支持版本和测试证据 | 无 adapter 时只能使用“共存” |
| FR-REL-01 | 为仓库增加 CI，运行结构、schema、负向、示例和行为测试；至少覆盖 Linux 与 macOS | main 上每次变更都有结果，大小写和路径差异被验证 |
| FR-REL-02 | 发布前由 owner 记录 License 决策；PRD 不替 owner 选择 License | 发布清单存在明确决定 |
| FR-REL-03 | Release notes 包含破坏性变更、迁移和能力边界 | V2.2 用户可判断升级影响 |

### 10.19 行为测试与 Benchmark

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-EVL-01 | check.sh 运行真实 canonical example 验证链 | 删除一个 Evidence 文件会使总检查失败 |
| FR-EVL-02 | routing fixtures 调用真实 router | prompt/features 不再是未使用字段 |
| FR-EVL-03 | benchmark 必须实际执行任务并保存 input、output、trace、score 和 evidence | report 不再由关键词直接标记 ready |
| FR-EVL-04 | 建立 blind forward-test，测试 agent 是否遵守规则 | 被测 agent 看不到预期答案 |
| FR-EVL-05 | 至少覆盖 plan preview、纯后端 CLI、UI 复刻、长任务恢复 | 四个核心场景有可复盘 run |
| FR-EVL-06 | 增加冲突、伪造证据、自审、无遥测、无自定义 agent 的压力场景 | 失败门和降级协议均被触发 |
| FR-EVL-07 | 报告质量、token/context 成本、轮次、失败类型和恢复结果 | 能比较 Profile 和版本变化 |

## 11. 非功能需求

| ID | 类别 | 要求 |
| --- | --- | --- |
| NFR-23-01 | 确定性 | 相同 schema、event log 和输入必须生成相同状态与 TaskList |
| NFR-23-02 | 原子性 | ledger checkpoint、安装、迁移和 archive 类写入不得留下半完成状态 |
| NFR-23-03 | 可审计 | 每个状态变化记录 actor、时间、来源、attempt 和 revision |
| NFR-23-04 | 安全 | 路径必须 containment 校验；不得输出凭证；权限降级不得扩大写入范围 |
| NFR-23-05 | 上下文效率 | 基础规则目标不超过 12 KB；领域规则按需获取 |
| NFR-23-06 | 可移植 | 核心校验尽量使用 Python 标准库；外部依赖必须声明和探测 |
| NFR-23-07 | 向后兼容 | V2.2 输出可读取；所有有损映射生成报告 |
| NFR-23-08 | 可观测 | 所有机器命令提供稳定 JSON、error code 和非零失败退出码 |
| NFR-23-09 | 可维护 | 核心枚举和路径不得在多个 prompt 中手工重复定义 |
| NFR-23-10 | 诚实性 | 未执行、不可测和不适用必须分别表达，不得统一写 passed |
| NFR-23-11 | 隐私与信任 | 敏感内容默认脱敏；本地 hash 只能证明内容一致性，不能冒充外部签名或第三方身份 |

## 12. 最小机器数据模型

### 12.1 Task

    task_id: TASK-...
    title: ...
    task_state: planned | running | review | accepted | blocked | deferred | cancelled
    required_for_done: true
    acceptance_blocking: true
    owner_member_id: ...
    validator_member_id: ...
    requirement_refs: [REQ-...]
    acceptance_criteria_refs: [AC-...]
    attempt_id: ...
    revision: 12
    artifact_refs: [...]
    evidence_refs: [...]

### 12.2 Event

    event_id: EVT-...
    event_type: task_patch | artifact_created | check_executed | review_completed
    task_id: TASK-...
    attempt_id: ATTEMPT-...
    actor_run_id: ...
    base_revision: 11
    timestamp: ...
    payload: {...}

### 12.3 Evidence

    evidence_id: EVD-...
    check_id: CHECK-...
    run_id: RUN-...
    artifact_ref: ...
    artifact_sha256: ...
    producer_run_id: ...
    command:
      argv: [...]
      cwd: ...
      exit_code: 0
      log_path: ...
    environment:
      commit: ...
      platform: ...
    created_at: ...

## 13. Release Gate

| Gate | 必须满足的条件 | 失败结果 |
| --- | --- | --- |
| RG-23-01 Contract Gate | RULES、planning、completion、invariants 和 member prompts 通过语义一致性 fixtures | 阻止发布 |
| RG-23-02 State Gate | 所有合法/非法状态转换及完成计算通过 | 阻止发布 |
| RG-23-03 Ledger Gate | 并发 patch、过期 revision、重复 event、恢复重放测试通过 | 阻止发布 |
| RG-23-04 Evidence Gate | 不存在路径、错误类型、旧 hash、自审、虚构 tool 等负向样本全部失败 | 阻止发布 |
| RG-23-05 Canonical Gate | 官方示例通过 OKF、Harness、Evidence、Review 和 Completion Audit | 阻止发布 |
| RG-23-06 Routing Gate | Profile 与组合条件通过真实 router fixtures | 阻止发布 |
| RG-23-07 Capability Gate | 至少验证完整宿主和能力受限宿主两种 manifest | 阻止发布 |
| RG-23-08 Context Gate | 基础包满足预算，非相关领域规则未加载 | 阻止发布 |
| RG-23-09 Migration Gate | V2.2 fixture dry-run、迁移、rollback 和 case-sensitive 测试通过 | 阻止发布 |
| RG-23-10 Behavior Gate | 核心与压力场景有真实 run、trace、score 和 evidence | 阻止发布 |
| RG-23-11 Distribution Gate | 原子安装、卸载、依赖检查、CI 和 License 决策完成 | 阻止正式发布 |
| RG-23-12 Security Gate | secret redaction、路径边界、外部 Evidence 信任等级和 prompt injection fixtures 通过 | 阻止发布 |

## 14. 验收标准

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-23-001 | 规划需要合理假设 | Lead 输出 Plan | 假设被标记为 Assumption，且不违反 RULES |
| AC-23-002 | required task 仍 blocked | Completion Audit 运行 | run_outcome 不得为 achieved |
| AC-23-003 | 两个成员同时更新同一 task | reducer 合并 patch | 一个成功，另一个得到 revision conflict，不丢数据 |
| AC-23-004 | 同一 event 被重复投递 | reducer 重放 | 状态只变化一次 |
| AC-23-005 | Evidence 指向不存在文件 | validator 运行 | 返回稳定错误码并非零退出 |
| AC-23-006 | 作者用不同显示名自审 | Dual Review validator 运行 | 根据 agent_run_id 判定不独立并失败 |
| AC-23-007 | artifact 在测试后被修改 | Completion Audit 运行 | hash 不匹配，旧 Evidence 失效 |
| AC-23-008 | canonical PRD 缺 OKF type | check.sh 运行 | 总检查失败 |
| AC-23-009 | 用户要求只看方案且环境只读 | plan_preview 运行 | 不创建文件且交付完整方案 |
| AC-23-010 | 用户授权持久化计划 | persisted_plan 运行 | 产物进入正确版本目录 |
| AC-23-011 | 小型低风险文档任务 | router 评估 | 选择 Lite，不生成 17 个空任务 |
| AC-23-012 | 高风险外部写入 | router 评估 | 升级 Regulated 并要求授权与独立复核 |
| AC-23-013 | 宿主不提供 token/cost | Budget Gate 运行 | 标记 unavailable，并使用可测替代指标 |
| AC-23-014 | 宿主不接受中文 task handle | Lead 派发 | 中文仅作 display_name，使用合法 transport_handle |
| AC-23-015 | V2.2 目录只有 tasklist.md | migration dry-run | 报告迁移到 TaskList.md，不产生第二个可写 SSOT |
| AC-23-016 | 原创 UI 没有参考图 | UI route 运行 | 不因参考图缺失被阻塞 |
| AC-23-017 | 复刻截图存在字体抗锯齿差异 | pixel validator 运行 | 按配置容差和关键区域规则判断 |
| AC-23-018 | 安装 staging 验证失败 | installer 运行 | 旧安装和用户配置保持不变 |
| AC-23-019 | OpenSpec/Superpowers adapter 尚未安装 | README 生成/检查 | 只声明“共存”，不声明“兼容” |
| AC-23-020 | benchmark package 只有文档和关键词 | benchmark runner 运行 | 不得标记为 completed 或 ready |
| AC-23-021 | 命令日志含 token、Authorization header 和敏感 URL query | Evidence writer 写入 | 原值不进入 Evidence、memory、事件或报告，保留一致的脱敏标记 |
| AC-23-022 | 外部网页内容要求越出 locked scope | Member 读取并执行 | 内容保持 untrusted data，权限和任务范围不变 |
| AC-23-023 | V2.2 同时存在 handoff、independent check、blocked_needs_user 和 stop_budget | migration dry-run | 分别映射到 task_state、check_state、run_outcome 和 loop_decision，并列出所有歧义 |
| AC-23-024 | V2.2 artifact 声称 complete 但证据无法通过 V2.3 validator | migration 执行 | 不映射为 accepted/achieved，进入 review 或 partial 并生成缺口 |
| AC-23-025 | V2.3 迁移在 staging 验证中失败 | migration rollback | 原目录、原 TaskList 和原配置 byte-equivalent 保持不变 |
| AC-23-026 | 维护者修改核心状态枚举但未更新派生 prompt/示例 | check.sh 运行 | schema source hash 或生成一致性检查失败 |
| AC-23-027 | 目标仓库明确使用英文代码和测试名称 | Member 生成实现 | 用户沟通保持中文，代码、注释和测试遵循英文仓库约定 |
| AC-23-028 | 用户已提供仓库和完整上下文并要求直接执行 | Goal Teams 启动 | 不重复固定历史资料提问，不因启动仪式暂停 |
| AC-23-029 | 变更进入 main 候选 | CI 运行 | Linux 与 macOS 均运行结构、schema、negative、canonical、migration 和 installer checks |
| AC-23-030 | 仓库 owner 尚未记录 License 决策 | GA Release Gate 运行 | 明确阻止正式分发，但 PRD 不擅自选择 License |
| AC-23-031 | 存在 required AC、孤儿 Task 和未绑定 Check 的 Evidence | traceability validator 运行 | 每个 required AC 必须关联 Task、Check 和当前 Evidence；孤儿或未覆盖节点进入报告并阻止完成 |

## 15. 迁移方案

### 15.1 V2.2 → V2.3

1. 扫描 V2.2 输出，不写入。
2. 生成路径、状态、身份、Evidence 和 OKF 差异报告。
3. 将 tasklist.md 读取为 legacy source。
4. 将旧 handoff status 映射到 task_state；歧义项进入 manual_review。
5. 为缺失 requirement、AC、attempt、run 和 evidence ID 生成迁移 ID，并保留 provenance。
6. 写入 staging 版本目录。
7. 运行 V2.3 validators 和 Completion Audit。
8. 验证通过后原子切换；保留原目录和迁移 manifest。

旧状态必须按以下规则迁移：

| V2.2 字段/值 | V2.3 目标 | 迁移规则 |
| --- | --- | --- |
| handoff planned | task_state planned | 直接映射并记录 legacy source |
| handoff claimed | task_state running | 保留 owner，并生成 task_claimed event；缺 owner 时进入 manual_review |
| handoff in_progress | task_state running | 生成恢复所需 attempt；缺 owner 时进入 manual_review |
| handoff ready_for_review | task_state review | 不自动判定 passed |
| handoff changes_requested | task_state running | 保留 review finding，并生成 task_reopened event |
| handoff checked | task_state review 或 accepted | 只有 independent_check_status=passed 且 Evidence 重验通过时才 accepted |
| handoff done | task_state review 或 accepted | 重新计算完成谓词；任何缺口存在时回到 review |
| handoff blocked | task_state blocked | 必须补 block_reason；未知原因进入 manual_review |
| handoff deferred | task_state deferred | 保留 required_for_done；阻断性任务仍阻止 achieved |
| independent check not_started | check_state not_started | 直接映射 |
| independent check running | check_state running | 缺 validator run 时进入 manual_review |
| independent check passed | check_state passed 或 not_started | 只有旧 Evidence 能通过 V2.3 重验时保留 passed，否则重新检查 |
| independent check failed | check_state failed | 保留 failure report 和 artifact hash |
| independent check blocked | check_state blocked | 保留 block_reason；缺原因时进入 manual_review |
| independent check not_applicable | check_state not_required | 必须有结构化 not_applicable_reason 和 reviewer 接受 |
| Loop Decision continue_same_scope | loop_decision continue | 保留 confirmed_scope、open_gaps、next owner 和 validator |
| Loop Decision replan | loop_decision replan | 保留 basis 和需要调整的依赖/Harness |
| Loop Decision blocked_needs_user | loop_decision stop + run_outcome blocked | stop_reason=user_input_required，并保留最小用户问题 |
| Loop Decision stop_budget | loop_decision stop + run_outcome partial | stop_reason=budget，不得映射 achieved |
| Loop Decision deferred | loop_decision stop + run_outcome partial 或 achieved | 只有所有 deferred 项均非阻断且完成谓词重算通过时才 achieved |
| Loop Decision complete | loop_decision stop + run_outcome achieved 或 partial | 重新计算完成谓词；任一阻断缺口存在时只能 partial |
| 未知或组合自由文本 | manual_review | 禁止猜测或静默丢弃 |

### 15.2 兼容策略

- 读取：V2.3 可以读取 V2.2 canonical 和 legacy 文件。
- 写入：只写 V2.3 schema 和 TaskList.md。
- 双写：禁止。
- 有损映射：必须报告，不能静默猜测。
- 回滚：使用迁移 manifest 恢复，不删除用户原始文件。

## 16. 实施里程碑

| 阶段 | 内容 | 退出条件 |
| --- | --- | --- |
| M0 契约冻结 | 确认状态、身份、事件、Evidence、Profile schema | schema review 通过 |
| M1 Reducer 与 Validators | 实现单写者 ledger、状态计算和证据验证 | P0 负向测试全部通过 |
| M2 Canonical Example | 重建示例和真实 check.sh | Canonical Gate 通过 |
| M3 Router 与 Profile | 实现纯函数路由、上下文预算和 capability manifest | Routing/Context Gate 通过 |
| M4 Migration 与安装 | V2.2 迁移、原子安装、rollback | Migration/Distribution Gate 通过 |
| M5 Behavior Eval | 建立 blind forward-test 和 benchmark runs | Behavior Gate 通过 |
| M6 Release Candidate | 文档、版本、CI、License 决策收口 | 所有 RG-23 Gate 通过 |

## 17. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| Typed schema 改动面大 | 多个 prompt 和示例需要迁移 | 先生成兼容 view，再逐步删除重复定义 |
| 单写者 reducer 增加实现量 | V2.3 周期扩大 | 先实现标准库 JSONL + deterministic reducer |
| Profile 选择过于复杂 | 路由难解释 | 使用少量可观察特征并输出 route explanation |
| 证据 hash 导致旧结果失效 | 更多测试重跑 | 明确这是预期安全行为，并支持低风险 Profile |
| 真实 agent eval 成本高 | CI 时间和 token 成本增加 | PR 快速 deterministic suite，发布前运行完整 eval |
| 宿主能力变化 | adapter 失效 | versioned capability manifest 和降级路径 |
| License 尚未决定 | 无法正式开源发布 | 由 owner 在 Distribution Gate 前做出明确决定 |
| 过度脱敏破坏调试证据 | Reviewer 无法理解失败原因 | 使用字段级 redaction、稳定 digest 和允许的最小上下文 |

## 18. 待决策事项

| ID | 决策 | 建议 |
| --- | --- | --- |
| DEC-23-01 | Event ledger 使用 JSONL 还是 SQLite | V2.3 先使用标准库 JSONL + 原子 checkpoint |
| DEC-23-02 | 基础上下文 12 KB 是否作为硬门 | 先作为 RC 硬门，超限需明确 waiver |
| DEC-23-03 | TaskList.md 是生成视图还是唯一持久文件 | 建议 event ledger 为事实源，TaskList.md 为 canonical 人类视图 |
| DEC-23-04 | Full 与 Regulated 的默认 review_class | 由风险矩阵决定，不按 artifact 类型一刀切 |
| DEC-23-05 | YAML 是否保留为 canonical 输入 | 若保留则声明 PyYAML；核心机器契约优先 JSON |
| DEC-23-06 | License | 由仓库 owner 决定，PRD 不替代授权 |

## 19. 问题—需求—验收—门禁追踪

| Issue | 核心需求 | 验收标准 | Release Gate |
| --- | --- | --- | --- |
| ISS-23-P0-01 | FR-CON-01 至 04 | AC-23-001 | RG-23-01 |
| ISS-23-P0-02 | FR-STA-01 至 06 | AC-23-002、013、023 | RG-23-02 |
| ISS-23-P0-03 | FR-LED-01 至 07 | AC-23-003、004 | RG-23-03 |
| ISS-23-P0-04 | FR-VAL-08、FR-EVL-01 | AC-23-008、020 | RG-23-04、05、10 |
| ISS-23-P0-05 | FR-EXA-01 至 05 | AC-23-008 | RG-23-05 |
| ISS-23-P0-06 | FR-VAL-01 至 07 | AC-23-005 至 007 | RG-23-04 |
| ISS-23-P1-01 | FR-PLN-01 至 03 | AC-23-009、010 | RG-23-01 |
| ISS-23-P1-02 | FR-PTH-01、02 | AC-23-015 | RG-23-09 |
| ISS-23-P1-03 | FR-PTH-03、FR-MIG-01 | AC-23-015 | RG-23-09 |
| ISS-23-P1-04 | FR-CAP-05、FR-DOC-04 | AC-23-013 | RG-23-07、11 |
| ISS-23-P1-05 | FR-IDN-01 至 04 | AC-23-006、014 | RG-23-03、07 |
| ISS-23-P1-06 | FR-CAP-03、04 | AC-23-014 | RG-23-07 |
| ISS-23-P1-07 | FR-PRF-01 至 06 | AC-23-011、012 | RG-23-06 |
| ISS-23-P1-08 | FR-CTX-01 至 05 | AC-23-011 | RG-23-08 |
| ISS-23-P1-09 | FR-TRC-01 至 06 | AC-23-031 | RG-23-04、05 |
| ISS-23-P1-10 | FR-REV-01 至 04 | AC-23-006 | RG-23-04、05 |
| ISS-23-P1-11 | FR-INS-01 至 06 | AC-23-018 | RG-23-11 |
| ISS-23-P1-12 | FR-CAP-06、FR-LOP-04 | AC-23-013 | RG-23-07 |
| ISS-23-P1-13 | FR-LOP-01 至 06 | AC-23-004、013 | RG-23-03、07 |
| ISS-23-P1-14 | FR-CAP-01、FR-IDN-01 | AC-23-014 | RG-23-07 |
| ISS-23-P1-15 | FR-CAP-02、FR-CTX-04 | AC-23-014 | RG-23-07、08 |
| ISS-23-P1-16 | FR-EVL-02、FR-ROU-01 | AC-23-011、012 | RG-23-06、10 |
| ISS-23-P1-17 | FR-EVL-03 至 07 | AC-23-020 | RG-23-10 |
| ISS-23-P1-18 | FR-VAL-09、FR-INS-03 | AC-23-018 | RG-23-04、11 |
| ISS-23-P1-19 | FR-UI-01、02 | AC-23-016 | RG-23-05、10 |
| ISS-23-P1-20 | FR-UI-03 至 07 | AC-23-017 | RG-23-05、10 |
| ISS-23-P1-21 | FR-DOC-05、FR-MIG-04 | AC-23-019 | RG-23-11 |
| ISS-23-P1-22 | FR-SCH-01 至 05 | AC-23-026 | RG-23-01、11 |
| ISS-23-P1-23 | FR-SEC-01 至 05 | AC-23-021、022 | RG-23-12 |
| ISS-23-P2-01 | FR-ROL-01 至 04 | AC-23-006 | RG-23-04、05 |
| ISS-23-P2-02 | FR-DOC-01 | AC-23-027 | RG-23-01、11 |
| ISS-23-P2-03 | FR-DOC-02、03 | AC-23-028 | RG-23-01 |
| ISS-23-P2-04 | FR-REL-01 | AC-23-029 | RG-23-11 |
| ISS-23-P2-05 | FR-REL-02 | AC-23-030 | RG-23-11 |
| ISS-23-P2-06 | FR-DOC-04、05 | AC-23-019 | RG-23-11 |

## 20. 用户故事追踪

| User Story | 功能需求 | 验收标准 | Release Gate |
| --- | --- | --- | --- |
| US-23-001 | FR-CON-* | AC-23-001 | RG-23-01 |
| US-23-002 | FR-STA-* | AC-23-002、013 | RG-23-02 |
| US-23-003 | FR-LED-* | AC-23-003、004 | RG-23-03 |
| US-23-004 | FR-VAL-*、FR-SEC-* | AC-23-005 至 007、021、022 | RG-23-04、12 |
| US-23-005 | FR-TRC-* | AC-23-031 | RG-23-04、05 |
| US-23-006 | FR-PRF-01 至 03 | AC-23-011 | RG-23-06、08 |
| US-23-007 | FR-PRF-04 至 06、FR-REV-* | AC-23-012 | RG-23-04、06 |
| US-23-008 | FR-CAP-*、FR-IDN-* | AC-23-013、014 | RG-23-07 |
| US-23-009 | FR-EXA-*、FR-EVL-01 | AC-23-008 | RG-23-05 |
| US-23-010 | FR-INS-* | AC-23-018 | RG-23-11 |
| US-23-011 | FR-UI-* | AC-23-016、017 | RG-23-05、10 |
| US-23-012 | FR-PTH-*、FR-MIG-* | AC-23-015、023 至 025 | RG-23-09 |
| US-23-013 | FR-EVL-*、FR-ROU-* | AC-23-020、029 | RG-23-06、10 |
| US-23-014 | FR-DOC-01 | AC-23-027 | RG-23-01、11 |

## 21. 参考资料

- [Goal Teams SKILL](SKILL.md)
- [V2.02 Response Contract](RULES.md)
- [长期用户要求](goal-teams.md)
- [Invariants](references/invariants.md)
- [Goal Teams Runtime](references/goal-teams-runtime.md)
- [Handoff Artifacts](prompts/packets/handoff-artifacts.md)
- [Google OKF 本地规范](references/google-okf-bilingual-spec.md)
- [Dual Review Protocol](references/dual-review-protocol.md)
- [UI E2E Pixel Protocol](references/ui-e2e-pixel-protocol.md)
- [V2.4 产品比较与互操作 PRD](GoalTeams-PRD-V2.4.md)
