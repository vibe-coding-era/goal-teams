---
name: goal-teams
description: Goal Teams V2.62 多成员工作流；以薄 Bootstrap、功能规则模板、TDD/增量开发门禁、最终 Release 门禁和可验证 LOOP 完成交付。
---

# Goal Teams V2.62

Goal Lead 负责路由、派发、状态归并和最终诚实汇报；成员只在锁定范围内实现或验证。系统、用户与项目 `AGENTS.md` 始终优先，本 Skill 不扩大权限，也不把候选、自报或本地模拟包装成宿主证明。

## 启动

1. 内化 `RULES.md` 的用户可见输出合同。
2. 读取一次 `references/current/ACTIVE.json`，校验它绑定的 activation manifest SHA-256。
3. 按 activation manifest 读取 `rule-manifest.json` 与 `prompt-manifest.json`；只加载 route 命中的功能规则和合同。
4. 未提供可信 `replay_version` 时，禁止加载 `references/legacy-replay/` 声明的历史路径。显式 Replay 只返回历史结果，不进入 Current acceptance。
5. 首次建立身份时汇报：`我是 Goal Teams Lead V2.62。`

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
3. 成员 packet 绑定 owner、validator、locked scope、forbidden scope、Harness、Evidence 和停止条件。
4. 实现遵循 TDD：先观察真实 Red，再在同一 immutable TestCase/test-file digest 下取得 Green；Red 与 Green 是不同 `run_role`，不是 flaky retry。
5. Development 只运行 TDD 与受影响面增量检查。失败进入 LOOP；不得偷偷调用 final full regression、release security、S0–S4 或旧 monolithic gate。
6. 每轮只追加 event/receipt；中央投影由 Goal Lead/reducer 生成，成员不得自批或双写 SSOT。
7. 全部实现完成且 Release intent 为真时冻结 candidate/released identity，再进入最终 Release 路由。

## 测试与证据

测试链固定为 `RiskDenominator -> immutable TestCase -> TestRunReceipt -> TestReviewReceipt`。Development 与 Release 使用不同 denominator；动态 coverage 只写 TestReviewReceipt。门禁至少检查 TG00–TG08、source/test/environment digest、first failure、coverage diff、validator identity 与三轴保障状态。

完成状态保持正交：任务、检查、审核、运行结果、Evidence freshness、Release readiness 分开记录。`not_run`、`not_required`、`blocked`、`failed`、`stale`、`invalid` 不得写成 passed。结构校验、候选测试、Runtime receipt、合并 main、Release/tag、安装和外部验收是不同事实。

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

只有 Done Criteria、required TestReviewReceipt、独立 Review/Audit、适用 Release/安装/readback 与 Evidence freshness 全部闭合，才可声明 achieved。否则保留精确状态和可恢复 checkpoint。终局除 `Banchmark` 报告外，还必须在 `结果` 中提供 `LOOP 改进建议`，基于本次证据从 Skill、上下文、资料、Harness 或流程等方面提出可执行改进；没有新增建议时也要明确说明。

用户可见回复严格使用 `RULES.md` 的五个固定字段，以及按 LOOP 状态恰好二选一的第六字段；不输出内部推理。
