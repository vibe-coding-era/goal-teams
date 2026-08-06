# Release Engineer Workflow

## Mode A: environment_preflight

1. 核对第一轮 TaskList 与任务分配存在，冻结 repo/version/source/project_size/user_requested_check。
2. 只读列出现有 worktree、branch、runtime、工具链、依赖和 workspace boundary。
3. 按 exact version、source compatibility、toolchain/dependency digest 与 Evidence freshness 评估复用；不得仅凭目录名复用。
4. 兼容且 current 时返回 `decision=reuse`；否则返回 `decision=create|blocked` 与拒绝复用理由。Medium/Large 创建使用 `develops/v<major.minor>` 与逻辑分支 `develop-v<major.minor>`；宿主要求 namespace 时添加前缀，本仓为 `codex/develop-v<major.minor>`。Small 可写 `version_branch=not_required`。
5. 提交 `environment_preflight_receipt`；环境 ready 前实现任务保持 pending。Architecture/依赖漂移后旧 receipt stale，必须 targeted revalidation。
6. `environment_preflight 完成后立即停止`；不得进入 Mode B。

## Mode B: release

1. 冻结 locked scope、候选 identity、项目根、release root 和外部写边界；不得复用 `environment_preflight` 作为 Release Evidence。
2. 只读运行 `check-evidence`；不得调用项目全量测试命令。
3. Evidence 缺失、过期、未由 trusted host 签名或 issuer run 不独立时，输出精确缺口和原 Owner；不制造替代 Evidence。
4. 无显式发布意图时，报告后等待用户确认；有明确提示时直接进入 `plan`。
5. 运行 `discover-scripts`；发现本地 bundle 时，先报告准确版本、digest、环境和 lifecycle，并等待用户确认执行同一已批准 run、派生新版本或忽略。
6. 从 `kits/catalog.json` 精确匹配语言、构建工具、环境和发布面；只接受 approved kit。
7. 生成 draft plan；任何脚本生成前必须验证 plan approval。
8. `compose` 只写入解析后的项目本地 release root；复制模板并生成新 manifest，绝不修改内置 kit。
9. 运行静态危险操作、路径 containment、digest、兼容性和权限检查。
10. 验证绑定 `execution_id/mode/operation`、隔离 runner、凭据清洗与最小权限 attestation 的 execution approval 后才允许 `execute`；执行前持久化 intent，使用无宿主凭据的闭集环境，每步写 receipt。
11. 只对标记 idempotent、无外部写且在批准范围内的失败步骤自动 LOOP。
12. 生产前验证备份 restore proof 与 Release Benchmark 基线；不满足即停止。
13. 发布后做平台 readback、线上 identity、最小 smoke、业务不变量和观察窗；receipt 必须为本次 execution 产生、typed、当前且 assertions 全通过。
14. 指标不可判定时暂停；数据/schema 风险转人工恢复；安全无状态失败才可执行预批准回滚，回滚后必须复核计划中冻结的 previous-good identity，不能继续要求候选 identity。
15. 由不同 member/run 进行独立完成审计。

LOOP 使用 `Gather → Reason → Act → Verify → Repeat`，状态写入本地 release run 的 `loop/`。最大尝试由计划给出，默认 3；禁止无限后台运行。
