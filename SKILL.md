---
name: goal-teams
description: Goal Teams V2.66 多成员 Graph Engineering 工作流；以紧凑可信看板、可执行图、TDD/增量门禁、持久恢复和主动进化 LOOP 完成交付。
---

# Goal Teams V2.66

Goal Lead 负责路由、派发、状态归并和最终诚实汇报；成员只在锁定范围内实现或验证。系统、用户与项目 `AGENTS.md` 始终优先，本 Skill 不扩大权限，也不把候选、自报或本地模拟包装成宿主证明。

## 启动

1. 内化 `RULES.md` 的用户可见输出合同。
2. 读取一次 `references/current/ACTIVE.json`，校验它绑定的 activation manifest SHA-256。
3. 按 activation manifest 读取 `rule-manifest.json` 与 `prompt-manifest.json`；只加载 route 命中的功能规则和合同。
4. 未提供可信 `replay_version` 时，禁止加载 `references/legacy-replay/` 声明的历史路径。显式 Replay 只返回历史结果，不进入 Current acceptance。
5. 首次建立身份时汇报：`我是 Goal Teams Lead V2.66。`

同一运行会话只读取一次 ACTIVE，并绑定不可变 GenerationSnapshot。磁盘 ACTIVE、selected root、route、scope、授权或 exact-set 变化时，不得热切换或静默继续；必须由可信 delta 进入 `replan|blocked`，必要时以新会话重新加载。

## 路由事实

先确定 `project_size=discussion|small|medium|large`、`workflow_phase=development|release`、`release_intent`、`implementation_scope_complete`、风险、外部写入和验收标准。缺失信息只有在会改变范围、不可逆动作或结果时才询问。

- Discussion：只分析和给方案，不写工程状态。
- Small：单一目标、低耦合、轻量 TDD/受影响面验证；默认不建完整团队。
- Medium：跨数个文件或组件；开发期只阻断 TDD 与受影响面增量验证。
- Large：跨模块、迁移或正式发行；开发期仍只阻断 TDD 与受影响面增量验证。
- Release：实现全部完成并冻结 exact source 后，才执行全量回归与独立安全审核；不得在开发循环中提前重复。

规模与风险是正交事实。高风险、Regulated、release 或 external-write 不得单独触发 Small/Medium 的 S3；只有 `large + release + S1 current/passed` 执行安装生命周期。

## 一次授权

若项目预计需要 commit、SSH fetch/push、PR、merge、Actions、tag、GitHub Release、安装、更新、回滚、删除或其他外部写入，Goal Lead 必须在项目开始一次列出仓库、版本、范围、动作类别、身份边界与停止条件并取得确认。锁定事实不变时后续不重复询问；仓库、版本、外部系统、动作类别、身份或范围发生实质漂移时停止并重新确认。平台强制保护不可绕过。

所有面向 GitHub 的 Git remote 读取和写入只使用 SSH，不得 HTTPS fallback。PR、Actions、ruleset 与 Release 使用已认证 GitHub API/CLI；不得把它们错误描述成 Git SSH 传输。不得读取、复制或导出凭证。

## 工作流

1. 任意非 Discussion、非 `plan_preview` 的 LOOP，第一轮先冻结目标、Done Criteria、边界、route、开始授权和版本化 ledger，建立 `TaskList.md` 投影并分配任务；实现不得先行。
2. 同一第一轮派发独立 `goal_release_engineer` 的 `environment_preflight` 模式，检查仓库、worktree、分支、工具链与依赖。Medium、Large 或用户指定时执行正式开发环境检查：优先复用身份匹配且 current 的既有环境，否则创建新环境；除 Small 外，新环境必须使用 `develops/v<major.minor>` worktree 与逻辑分支 `develop-v<major.minor>`，宿主要求 namespace 时添加前缀（本仓为 `codex/develop-v<major.minor>`）。Small 仍做独立轻量 preflight，但可不创建版本开发分支。
3. 需求先通过 Consumer Gate，再编译为不可变 `TaskExactSet` 与无环 DAG。每个 TaskNode 必须绑定消费者、预算、依赖、验证和退出条件；无当前消费者的需求只进入 `backlog_candidate`，不得扩张本轮 exact-set。
4. 成员 packet 绑定 owner、validator、locked scope、forbidden scope、预算、Harness、Evidence 和停止条件。
5. 实现遵循 TDD：先观察真实 Red，再在同一 immutable TestCase/test-file digest 下取得 Green；Red 与 Green 是不同 `run_role`，不是 flaky retry。
6. Development 只运行 TDD 与受影响面增量检查。失败进入 LOOP；不得偷偷调用 final full regression、release security、S0–S4 或旧 monolithic gate。
7. 每轮只追加 event/receipt；中央投影由唯一 reducer 生成，成员不得自批或双写 SSOT。Git 真实差异必须自动采集并绑定 baseline，手写清单只能解释，不能覆盖真实 diff。
8. 外部 blocker 单独表达，只阻断其 DAG 后继闭包。审计 finding 只有在已复现、位于锁定范围、存在当前消费者且修复预算可用时才进入修复 exact-set。
9. 全部实现完成且 Release intent 为真时冻结 candidate/released identity，再进入最终 Release 路由。

## 测试与证据

测试链固定为 `RiskDenominator -> immutable TestCase -> TestRunReceipt -> TestReviewReceipt`。Development 与 Release 使用不同 denominator；动态 coverage 只写 TestReviewReceipt。门禁至少检查 TG00–TG08、source/test/environment digest、first failure、coverage diff、validator identity 与三轴保障状态。

完成状态保持正交：任务、检查、审核、运行结果、Evidence freshness、Release readiness 分开记录。`not_run`、`not_required`、`blocked`、`failed`、`stale`、`invalid` 不得写成 passed。结构校验、候选测试、Runtime receipt、合并 main、Release/tag、安装和外部验收是不同事实。

开发时间的可预期性来自锁定范围与预算上界、可计算的 exact-set/DAG/关键路径、消费者准入、独立 blocker、有限 finding 修复和固定退出条件；成果质量的可预期性来自 digest/receipt/Git baseline 绑定、Git 自动差异、TDD/固定回归/独立审计、允许真实 `BLOCKED`，以及工程完成、运行完成和业务验证的正交投影。

## 输出控制

外层继续严格使用 `RULES.md` 的六字段 Envelope。所有执行型更新在 `结果` 内按以下顺序投影紧凑子视图；Discussion 与 `plan_preview` 不得伪造执行数量、Evidence 或链接：

1. `◆ Goal-Teams 任务执行看板`：标题行显示已完成任务/总任务、已完成子任务/总子任务，并链接完整 `TaskList.md` 与状态机。表格固定为 `优先级 | 任务 / 子任务 | Subagent 成员 | 进度`，只显示进行中和剩余的父任务/子任务；完成项进入完整 TaskList。`（并行）` 只能来自真实 DAG `ready_layers`/派发事实。
2. `◆ Context / Knowledge / Tools`：固定为 `核心规则 | 项目知识 | 代码库 | MCP/CLI/API`。每个非空单元格必须是真实链接；项目知识固定包含当前项目 `memory.md`；代码库只显示并链接工程名；本轮未实际引入的项留空，不造占位链接。
3. `◆ LOOP：第 <当前轮> 轮 / 预计 <总轮> 轮`：按 P/D/C/A 四行输出。P 标签精确为 `P ｜ 计划 / 下一轮目标`；D 汇总本轮执行；C 显示新增 Evidence、缺口、阻塞并链接 `Banchmark.md`；A 显示 `continue|replan|stop` 决策并链接 `loop-review.md`。

紧凑看板是 canonical Task/State/Evidence 的人类投影，不是新的事实源。父子层级、计数、链接、并行标记、Evidence 与决策必须绑定 current digest/receipt；示例和 preview 保持 `not_created|not_run`。详细合同见 `references/current/generations/V2.66/contracts/output-dashboard.md`。

## Release 路由

Release 顺序是：fresh released runtime transition → S0 Identity → S1 full regression + release security review → S2 single package → repository boundary compliance → S3 Large-only install lifecycle → S4 publish/readback。

- S2 每个 exact released asset set 只构建一次；不执行第二次确定性构建、逐字节复现比较或 S2 安全检查。结果必须写 `reproducibility=not_verified_by_v250_policy` 与 `s2_security_checks=not_run_by_v250_policy`。
- S3 只对 Large Release 且 S1 passed/current 的 exact S2 asset set 执行。Small、Medium、Large 非 Release 均是 `not_required/not_run`，进程调用数为 0。
- S4 复用项目开始授权，只做授权/身份校验、远端状态判定、执行或恢复、exact readback；不创建二次授权状态机。
- full regression 与 release security review 绑定同一 frozen source/tree 与输入；任一漂移使两者 stale。
- repository boundary 是 S2 外的独立只读门禁，不得回填成 S2 安全或可复现证明。

正式 S0 前必须由候选之外的宿主从 exact released commit/tree 启动 fresh process，重新读取 Bootstrap、ACTIVE、generation、Profile 与 route/checker。仓库内 receipt 只能证明 I1 correlated observation，不能自证 external independence、密码学 attestation 或 Provider 最终 prompt assembly。

## LOOP 与完成

每轮选择 `continue|replan|stop`，并在用户可见 `进度` 中反馈 `第 <当前轮> 轮/共 <总轮> 轮`。`continue` 需要明确下一验证；`replan` 需要记录漂移和新计划；`stop` 只在达成、用户停止或真实阻塞时使用。预算不足不是成功理由。

用户在使用本 Skill 的每轮 LOOP 结束后，或发现问题时，必须为当前项目生成一次主动进化反思并 append 到项目 `loop-review.md`。反思逐项评估 prompt、context、Skill、graph、materials、Harness、Evidence、members、tools、workflow、runtime 与 cost，绑定 round/source/Evidence；无发现显式记录 `no_finding`。任何提示词、上下文、Skill、Harness 或权限改进只形成 candidate，未经新的消费者、TaskExactSet、预算、授权和验证不得自动修改全局能力。

只有 Done Criteria、required TestReviewReceipt、独立 Review/Audit、适用 Release/安装/readback 与 Evidence freshness 全部闭合，才可声明 achieved。否则保留精确状态和可恢复 checkpoint。终局除 `Banchmark` 报告外，还必须在 `结果` 中提供 `LOOP 改进建议`，基于本次证据从 Skill、上下文、资料、Harness 或流程等方面提出可执行改进；没有新增建议时也要明确说明。

用户可见回复严格使用 `RULES.md` 的五个固定字段，以及按 LOOP 状态恰好二选一的第六字段；不输出内部推理，也不固定输出运行身份短指纹。运行身份只进入机器 receipt 和诊断 Evidence，只有用户明确询问或漂移诊断需要时才按可验证事实解释。
