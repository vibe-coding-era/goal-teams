---
type: Goal Teams Progress
title: Goal Teams V2.3 修复进度
description: 记录每轮 LOOP 的完成项、缺口、证据与下一轮派发。
tags: [goal-teams, v2.3, progress, loop]
timestamp: 2026-07-10T15:30:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.3 修复进度

## Round 1

| 成员 | 任务 | 状态 | 证据 | 下一步 |
| --- | --- | --- | --- | --- |
| Goal Lead | TaskList 纠偏、版本化计划和 SPEC | running | `TaskList.md`, `plan.md` | 规则同步与整合 |
| 核心实现-V2.3契约与Reducer | TASK-23-001/002/003/006 | running | pending | 核心实现与 smoke |
| 独立测试-V2.3门禁与Canonical | TASK-23-004/005/013 | running | pending | 测试矩阵与 canonical |
| 分发实现-V2.3安装与CI | TASK-23-007/008/009/011 | running | pending | 生命周期与 CI |

### Round 1 独立复核结论

- 确定性 48-test suite、installer lifecycle、canonical 表面检查和 benchmark runner 曾返回绿色。
- 新的只读语义 Reviewer 复现 P0 假绿：canonical 未逐项验证 Check/Run；mutation temp baseline 未先证明可通过；reducer 接受自审与不存在 Evidence；Traceability 接受 ID-only 图；Evidence 未扫描日志 secrets；Behavior 未执行 blind agent；migration 未生成 ledger/checkpoint。
- 因此 Round 1 不计 accepted，结论为 `audit_state=failed`、`loop_decision=replan`、`run_outcome=partial`。

## Round 2

| 成员 | 任务 | 状态 | 失败证据 / 修复目标 | 下一步 |
| --- | --- | --- | --- | --- |
| 核心实现-V2.3契约与Reducer | TASK-23-001/002/003/006/009 | running | accepted bypass、ID-only trace、raw secret log、migration no-ledger | 强制全链验证与 valid-Evidence registry |
| 独立测试-V2.3门禁与Canonical | TASK-23-004/005/013 | running | mutation vacuous pass、虚构命令、非 blind Behavior | pristine baseline + stable error + real runner gate |
| 评审-V2.3语义与风险复核 | TASK-23-010/013 | running | P0 findings 已复现 | 完成 P0/P1/P2 独立报告并复核修复 |
| Goal Lead | TASK-23-012/014 | planned | 项目证据链尚未建立 | 修复通过后生成 ledger/Evidence/Traceability/Review/Audit |

### Round 2 中间重放（不得作为发布证据）

- Lead 在并行修复尚未合并完成时重放 `python3 -m unittest discover -s tests/v23 -p 'test_*.py' -v`：共发现 72 tests，结果为 48 failures、1 error、1 platform skip。
- 已通过域：schema 单源与大部分 reducer/CAS、严格 Evidence/Traceability/Dual Review 单元测试、migration、context/capability、pixel、安全 redaction。
- 当前集中失败：canonical 尚未迁移到新 identity/check/run/full-object chain；identity registry 有 `NameError` 且未返回 JSON envelope；Behavior fixtures freshness 失效；Completion Audit、RC/GA fixtures 与 accepted reopen 预期尚未对齐；installer nested validation 仍受总门禁失败影响。
- 该重放证明严格门禁正在拒绝旧 fixture，不能解释为回归完成；修复后必须从干净进程完整重跑。

### Round 2 分发域复核

- identity registry 异常修复且 Dual Review wrapper 更新后，聚合重跑的结构、Context/Capability、Security、CI pin、Harness、Pixel、artifact comparison、Dual Review wrapper 均通过。
- 分发域不再存在自身失败；聚合套件剩余失败均来自尚在迁移的 canonical、Completion Audit fixture、Behavior freshness 与 reopen 预期。TASK-23-007/008/009/011 仍保持 review，直到最终项目 Evidence 与独立完成审计落盘。

### Round 2 新增 P0 组合门禁缺口

- Lead 检查发现 `release-gate --mode rc` 当前只验证 canonical deterministic behavior；即使其 `release_eligible=false`，RC 仍可能在没有真实 blind-agent summary 时通过。
- TASK-23-005 的完成条件因此增加：RC 必须消费并严格验证本次持久化 blind summary（9 个 required 场景、真实 Codex provider、release eligible、隔离 staging/source digest/rubric binding）；缺失、fixture 或任一场景失败时 RC 必须 fail-closed。

### Round 2 文档—runtime 语义审计

- 独立文档 Reviewer 复现 active prompt/template 与 schema/runtime 漂移：旧根级 machine paths、Task identity 旧字段名、无效 event 示例、Dual Review/Audit 缺 provenance、plan_preview 无条件落盘、fallback 冲突及安全/trust 隐藏规则。
- Lead 已修正 README/OKF/default AGENTS 输出树、Handoff/Member/Harness/Review/Audit packet、6 条 event 示例、plan_preview no-write 分支、capability fallback、stop_reason、RC/GA 与 migration 文案；官方 event 示例逐条 `validate_event=[]`，文档 validator/context/diff 局部门禁通过。
- Evidence 进一步改为判别联合：成功执行、失败记录、人工观察、外部引用均可严格记录；仅 current `local_verified` 成功执行有 acceptance 资格。最终状态等待新增对抗测试和全量重放。

### Round 2 第二次全量重放

- V2.3 suite 已扩展到 81 tests；中间结果为 24 failures、6 skips。
- 已通过的新域包括 Evidence kind 联合、waiver 非阻断边界、plan_preview filesystem no-write、9 场景 typed hidden-scorer contract、migration unverified completion 降级、blind summary 缺失/mock fail-closed。
- 当前 failures 主要由 schema 刚新增 closure 字段但 lock 尚未最终刷新引起：`E_CHECKPOINT_SCHEMA_DRIFT` 级联到 canonical pristine、projection、completion 与 installer nested validation。该结果仍为 `replan/partial`，不得提升任务状态。

### Round 2 trusted replay 构造性复核

- schema lock 刷新后，State/Loop 定向 17 tests 已全绿；Evidence/Traceability/Governance 定向 31 tests 全绿、4 项真实 blind 依赖测试按设计跳过。
- 但独立 Reviewer 继续从最终 machine closure 反推，发现 replay 虽已拒绝 `python -c/-m` 与仓库外脚本，仍只允许固定 verifier 的 `success|recovery`，未把 verifier 实际读取对象与当前 Evidence / Dual Review 的 `artifact_ref`、哈希、check/run 语义绑定。
- 该缺口允许“验证一个无关固定 artifact、为另一个 artifact 出具通过记录”，属于新的 P0 假绿；同时复制到 installer staging 后的 pristine canonical 出现 `E_COMMAND_REPLAY_POLICY` 级联失败。已登记 GAP-23-R2-06，撤销 package freeze，进入 runtime binding + 错对象 mutation + copied-pristine 回归；修复前不得运行真实 blind 或提升 Task 状态。
- 同一轮 machine-closure 构造还复现 append-only 时序循环：当前 Evidence 的 `workspace_revision` 等于最终 ledger 文件 SHA，但正常事件流必须先生成 Evidence、再追加 check/accepted；追加后 SHA 改变会让刚生成及更早 Evidence 全部 stale。canonical 离线 builder 先写“未来 ledger”再造证据，无法证明 live workflow 可执行。
- 原 TASK-23-014 又把最终 Completion Audit 设为 required/acceptance-blocking：审计前该任务不能 accepted，审计后接受它又改变 ledger 与 task digest，导致无限重审。已登记 GAP-23-R2-07，并将 TASK-23-014 改为外部 nonrequired/nonblocking gate；runtime 必须改为可校验的 ledger prefix/stable source revision 并增加 live append mutation 回归。

### Round 2 prefix / Audit 反推复核

- ledger-prefix、runtime-locked replay 和自定义 audit path 自引用初版落地后，targeted 一度达到 61/61 green（4 项真实 blind 条件跳过），但独立文档/构造 Reviewer 继续发现三处不能忽略的边界。
- GAP-23-R2-08：文档把外部 Audit 误写成“required 全 accepted 后才运行”，与 failed/blocked Audit 驱动 LOOP 冲突；已统一为候选收尾运行，只有 passed/achieved 要求 required 全 accepted。
- GAP-23-R2-09：prefix context 只找任意相同 attempt task，跨 task 同 attempt 可借用 running 上下文；runtime/test 必须反绑所有引用 event 的 exact task。
- GAP-23-R2-10：普通 Evidence 的 symbolic `HEAD` 不能证明生成时 source snapshot；需用显式 contained source manifest digest，限制 portable fixture 例外，并覆盖 source mutation 与 Evidence-only 后续提交。
- 因此 61 项 targeted 仍只是中间证据；package freeze 再次撤销，真实 blind 继续延后。

### Round 2 第三次全量重放

- source manifest、portable scope 与 exact consumer prefix 修复后，core/canonical/governance targeted 达到 67 tests green、4 real-blind skips。
- 随后 full suite 发现 98 tests，外层结果为 2 failures、5 skips；两项外层失败均在 installer source/staging 链，不得解释为 RC 通过。
- 根因一：新 V2.3 tests/schema/runtime/canonical 尚未进入 Git index，manifest-driven installer 复制到了旧/不完整 source；Lead 已只暂存明确 V2.3 范围，个人文件保持未跟踪且不进入提交。
- 根因二：Behavior runner 在安装后的非 Git staging 中把 source/status digest 写成字面 `unavailable`，严格 validator 以 `E_BEHAVIOR_SOURCE_DRIFT` 正确拒绝。修复要求使用排除动态输出的确定性 filesystem manifest/status fallback，并覆盖 staging 内容变化负向场景；不得放宽 validator。

### Round 2 新鲜终审发现

- 新的只读终审 Reviewer 构造出 GAP-23-R2-11：内存 reducer 会把同 event id+digest 视为幂等，但 `append_event` 随后仍无条件写入同一 JSONL；一次正常网络/调用重试即可制造物理 duplicate，之后 Evidence prefix validator 正确把 ledger 判为 invalid，造成无法收尾。
- 同一 duplicate 快路径还先比较排除 `event_digest` 的 canonical digest，再处理 event validation；第二次请求携带错误 supplied `event_digest` 可能被静默当成幂等。修复必须在写入前去重、在幂等判断前验证 supplied digest，并增加真实 append/CLI 回归。
- GAP-23-R2-12：standalone migration `verify` 未提供外部 expected source hash 时，manifest 的 `source_sha256` 可被改成 null/任意而仍 verified；`source_file/legacy_hashes/plan_id/mappings` 也缺少完整交叉绑定。必须验证内部 provenance 自洽并逐字段 mutation，不能把“调用者未提供 expected”解释成“source provenance 可不验”。
- GAP-23-R2-13：blind summary validator 未从固定 `output.txt` 重跑 typed scorer；篡改实际答案并同步外层 hash、保留旧 pass score 仍可能通过。必须 strict parse persisted output、用 canonical scorer 重算并锁 exact evidence paths。
- GAP-23-R2-14：release gate 未限制 `--manifest` 的唯一 canonical path/contract hash；九个同名 trivial 场景仍可跑真实 Codex 并假装覆盖规定行为。必须锁 canonical manifest 路径与内容/有效 scorer 投影。
- GAP-23-R2-15：本地可变 identity registry 不能充当 repository owner 信任根；本地 `owner_authorized:true` 只能是 proposal，不是外部授权证明。本版无 host/signature attestation 能力时 GA 必须稳定 blocked，不能以测试 fixture 自封 owner 后宣称 authorized。
- GAP-23-R2-16：required AC 的 Task 与 passed Check/Run/Evidence 可由互不相干的对象拼接；需强制 accepted required/blocking Task 的 validation_check/run/evidence 同路径覆盖该 AC。
- GAP-23-R2-17：review 文件可自选较低 `review_class`；Completion 必须根据 Harness task type/risk 推导最低等级，防止 replica/safety 用 semantic N/A 绕过脚本复核。
- GAP-23-R2-18：RC 组合器只验证 canonical + blind，非canonical distribution/migration/security 被破坏时仍可能绿；RC 必须直接执行统一 deterministic release suite，并用内部递归护栏而非信任可伪造 summary。
- GAP-23-R2-19：Run/Evidence 分别有合法 identity 仍不足以证明归属；passed Run 必须与 Evidence producer 相同，Task validator 也必须与其 validation Check validator一致，防止把 B 的证据包装成 A 的运行。
- GAP-23-R2-20：standalone Dual Review 与 Completion 使用不同强度合同，导致官方 self-test 形状只能通过前者。两层必须共用 replay 校验，wrapper 产物必须能进入真实 Completion。
- GAP-23-R2-21：单一 `command` 字段无法同时表示真实 pytest/check.sh 执行与安全 hash replay。必须拆为不可由 validator 执行、但完整绑定的 domain command，以及唯一允许执行的 runtime-locked `integrity_replay`；缺任一层都不能成为 acceptance Evidence。
- GAP-23-R2-22：migration rollback 直接使用 manifest 的 absolute backup path/plan id，存在路径注入和任意目录移动风险；rollback 路径必须从已验证 plan + destination 确定性推导，且任何 provenance 偏差都在触碰 dst/外部目录前 fail-closed。
- GAP-23-R2-23：新 runtime 已把 `harness_contract.task_type` 与 `required_review_class` 作为 Completion 的权威 review policy 输入，并把 Evidence / Review 拆成领域执行与 runtime-locked 完整性重放；但官方 packet、runtime、PRD 与规则文档尚未同步。若不修，遵循官方模板生成的项目会稳定触发 `E_REVIEW_CLASS_POLICY` 或旧 replay 形状错误，因此实现冻结后必须做模板驱动 fixture 与文档一致性复核。
- GAP-23-R2-24：RC 的 deterministic composition 当前 source snapshot 只看 worktree bytes；`git rm --cached SKILL.md` 可保持 snapshot 不变却改变 installer 的 `git ls-files` 包成员。suite 前后必须同时绑定 trusted HEAD、index/`ls-files -s` 与 status digest，并覆盖 index-only mutation；否则不能把 RC 解释为 source-stable。
- GAP-23-R2-25：migration apply 会对可预测 staging/rollback 目录先执行无条件 `rmtree(ignore_errors=True)`；预置 sentinel 已复现被静默删除。路径碰撞或 symlink 必须在任何 mutation 前 fail-closed，只有本次事务拥有且 provenance 匹配的路径才可清理。
- GAP-23-R2-26：Evidence 的 execution record 目前只比较已知字段且未扫描整个文件；加入真实 token 形态 extra field、同步 hash/size 与 replay binding 后仍可通过。必须把 execution record 收紧为 exact-object 并做全内容 secret gate。
- GAP-23-R2-27：required Check 没有把 Harness 预期领域命令反绑到 Evidence，canonical 甚至用与声明命令无关的 `json.tool identity/registry.json` 支撑 artifact AC；comparison Review 同时允许 actual 自比 actual。必须给 Check→Evidence 建 exact command contract，并绑定不同 resolved path/inode 的 actual 与预先批准 baseline；两份内容相同时 hash 可以相同。
- GAP-23-R2-28：Run/Evidence 只绑 ID 不绑时间，canonical 的 passed Run 已结束后 domain command 才开始仍可通过。必须把 domain/integrity 执行包含在 Run 包络内，再按 Evidence created 与引用 event 递增。
- GAP-23-R2-29：blind 的“真实 provider”目前仅由 PATH 解析、`--version` 自报和本地 hash 支撑；同一 fake PATH 可同时骗过运行与验证。本版 RC 应诚实降为 `local_process_attested`，不宣称远程/密码学 attestation；更高信任必须引入仓库外 trust root。
- GAP-23-R2-30：blind 验证端的 staged tree manifest 会忽略 symlink，运行后加入外部/answer-bearing symlink 仍可能保持 digest 不变。验证端必须对任何 symlink/non-regular entry fail-closed，且不得跟随目标读取内容。
- GAP-23-R2-31：blind stage 用 allowlist rglob，installer 用 `git ls-files`，导致未跟踪 `references/skill-authoring-guide.md` 会进入盲测包却不进入提交/安装包。两者必须共用 manifest-driven index selection，并保持用户未跟踪文件不动。
- GAP-23-R2-32：blind manifest 未绑定 mode，staged package 在运行后被 chmod 仍可能保持 summary 有效。tracked projection 与实际 stage 必须绑定可移植规范 mode，并拒绝特殊位及 index/worktree mode 漂移。
- GAP-23-R2-33：replica pixel validator 与官方成功测试允许 baseline 自比 baseline；这会让 UI 复刻像素门稳定假绿。已在 replica 模式拒绝同 resolved path/inode，待独立 actual happy path与 hardlink mutation回归。
- GAP-23-R2-34：Dual Review 的 actual/baseline 只验 hash 未验 secret；不同时作为 Evidence 的 artifact 可携带 token/私钥并通过。两份被审文件都必须执行完整内容 secret gate。
- GAP-23-R2-35：migration backup tree digest 未包含权限 mode；backup chmod 后仍会恢复被篡改权限的树。迁移 manifest 与 rollback 验证必须绑定 type+mode，并覆盖 executable/special-bit mutation。
- GAP-23-R2-36：冻结版 blind runner 与 runtime 的 forbidden/excluded-untracked 集合已实证不一致；即使 paths/modes 相同，新生成 stage 也会 `E_PACKAGE_IDENTITY`。必须共享同一 selection contract，并增加 producer→validator 集成 smoke。
- GAP-23-R2-37：共享 package-selection helper 仍可经祖先目录 symlink 读取仓库外内容；临时 Git 仓库中把 tracked `prompts/` 换成外部 symlink 后 selection 仍 accepted。必须逐级 lstat/containment，并保证拒绝前不读取外部 bytes。
- GAP-23-R2-38：installer 的 prepare→source check→copy 存在 TOCTOU；临时仓库中在校验期间把 ORIGINAL 改为 MUTATED，安装仍成功但报告保留 ORIGINAL hash/clean。必须把准备期 package manifest 与 copy/stage/post-switch bytes exact 绑定。
- GAP-23-R2-39：migration apply 后新增 `post-apply-user-data.txt`，rollback 仍 rc=0/rolled_back 并静默删除新数据。apply 必须绑定 applied tree，rollback 对 current drift fail-closed 或先安全归档。

## Loop Decision

- round: 4
- loop_decision: `stop`
- run_outcome: `achieved`
- stop_reason: `achieved`
- open_gaps: `[]`
- source_commit: `7983e344a3984e98b6ce1a779e45bf7b289c747d`
- real_blind: `9/9`, `provider_trust_level=local_process_attested`
- deterministic_release_composition: `exit_code=0`, source/index/status/tree unchanged
- required_tasks: `13/13 accepted`
- independent_review_run: `RUN-R236-FRESH-REVIEW-20260711-01`
- completion_audit: `passed`, auditor `RUN-V23-COMPLETION-AUDITOR-20260711-01`
- external_boundary: GA 缺仓库外可信 owner host/signature attestation，继续 fail-closed；技术 RC 已闭合。
