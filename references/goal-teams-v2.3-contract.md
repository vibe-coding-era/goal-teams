---
type: Goal Teams V2.3 Contract
title: Goal Teams V2.3 Contract
description: V2.3 机器可检查契约、Release Gate 与迁移边界摘要。
tags: [goal-teams, v2.3, contract]
timestamp: 2026-07-10T00:00:00Z
okf_version: "0.1"
---

# Goal Teams V2.3 Contract

## V2.34 Self-release Extensions (V2.3 Schema Compatible)

以下历史扩展在当前 V2.43 只由 `goal-teams-self-release-v2.43` Profile 加载；V2.42/V2.41/V2.40/V2.39/V2.38 Profile 只用于历史 replay。它们保持 V2.3 schema compatibility，不是 `goal-teams-core-v2.5` 的通用完成条件。

- V2.34 增加四文件可恢复控制平面与扩展 gate，不改变 V2.3 `task_state` / `check_state` / `run_outcome` / `loop_decision` / `audit_state` 枚举，也不让 `feature_list.json` 成为 acceptance SSOT。
- 实现顺序为 immutable contract 及独立 review、Architecture accepted、`development_environment_check=ready` 及 current independent Evidence、独立测试用例、implementation；任一 exact-hash/identity/ledger prefix 漂移即重验。
- iteration 9 只允许将预授权 `.goalteams-candidates/<candidate_id>` 原子隔离到 `.goalteams-quarantine/<reset_id>/<candidate_id>`，不删除仓库/用户数据且不提供 purge；iteration 11 是唯一 delivery/achieved 写入门，缺证时不得 iteration 12。
- 公开归档只包含 sanitizer 后的 completed/public 副本；完整 source hash、ledger/Evidence/review/audit 和 sanitizer receipt 保留在非公开 provenance，不得为清除调用痕迹而删除审计链。

## V2.33 Clarifications (V2.3 Schema Compatible)

### Rule precedence and response scope

- 规则优先级为：系统/用户 → 项目 `AGENTS.md` → `references/invariants.md` → 已触发的条件规则 → `RULES.md`（仅用户可见响应）→ Lead prompt → Member prompt。
- `RULES.md` 约束事实标签、汇报内容和措辞，不得覆盖状态机、权限、locked scope、Harness、Evidence、独立性、安全门或完成谓词。

### Explicit preview and missing-reference handling

- `mode=plan_preview` 仅在用户明确同时要求“只要规划/建议”与“不落盘、不创建/修改文件、只在聊天中返回”时可用。要求生成计划文档、需求卡片、TaskList、ledger、SPEC、实施、派发、测试或提交时不得使用；单独的“先做计划”不构成 no-write 授权。
- 核心引用（invariants、schema、当前范围的 ledger/Harness/Evidence/独立验证契约）或已触发条件引用缺失时，必须记录缺失路径和影响，并使用 `task_state=blocked`、`check_state=blocked`。不得以单 agent、缓存或作者自检绕过独立验证。
- 只有低风险、非 acceptance-blocking，且 Harness 明确不要求独立验证的工作，可在未触发条件/可选引用缺失时记录 `degraded_mode=single_agent`。该记录不是 V2.3 schema 字段，不能支持 `accepted`、`passed` 或 `achieved`，并且不适用于外部写入、安全、迁移、UI/E2E、后端/API、长任务和 Completion Audit。

### Single-valued check state

- V2.3 schema 不变：`check_state` 必须是单个枚举值。已运行但检查未通过或 Evidence 无效使用 `failed`；因授权、能力、核心依赖或已触发条件引用缺失而无法运行/完成使用 `blocked`。文档里的“failed 或 blocked”不是允许写入的组合态。

## Capability Snapshot

- 启动时记录宿主是否支持 `custom_goal_subagents`、上下文隔离、并发、遥测和恢复。
- 未暴露 `goal_*` 时，只有 capability manifest 证明通用 subagent 能力等价、身份独立且权限不扩大才可自动 fallback；否则串行降级、blocked 或请求用户，并记录原因。
- `display_name` 可中文本地化；`transport_handle` 只承担宿主路由，不作为独立性证据。
- V2.36 新独立身份还须通过宿主 attestation 验证 run/transport/nonce/time；V2.3 registry 的自报字段仅保留兼容读取能力。

## 状态闭包

- `task_state`: `planned | running | review | accepted | blocked | deferred | cancelled`。
- `run_outcome`: `achieved | partial | blocked | aborted`。
- `loop_decision`: `continue | replan | stop`。
- `check_state`: `not_required | not_started | running | passed | failed | blocked | waived`。
- `required_for_done` 与 `acceptance_blocking` 共同决定完成谓词；阻断任务未 `accepted` 时不得输出 `achieved`。

## 单写者账本

- 成员提交 append-only event；每条含 `schema_version`、`event_id`、`event_type`、`task_id`、`attempt_id`、`base_revision`、`actor_run_id`、`ledger_owner_run_id`、`timestamp` 和 `payload`。
- Reducer 使用 revision/CAS 合并；重复 `event_id` 幂等，过期 `base_revision` 返回冲突。
- `TaskList.md` 是 reducer 生成的人类视图，不是多成员自由编辑的 SSOT。

## Evidence Gate

- Evidence 以 `evidence_kind=command_execution|failure_record|manual_observation|external_reference` 判别，并绑定 check/run/attempt/producer、artifact snapshot/hash、trust level、完整 ancestor commit、非空 `source_paths` 的 path/size/hash manifest digest 与 `ledger_revision>0`/`ledger_prefix_sha256`。普通 Evidence 的 source path 必须在绑定 commit 中且当前 bytes 相同；symbolic `HEAD` 仅允许 `validate-canonical` 内部 portable fixture，通用 validator 报 `E_PORTABLE_FIXTURE_SCOPE`。prefix 是前 N 条 event 去 `event_digest` 后的有序 canonical digest，允许后续合法 append，但拒绝空/未来/伪 prefix、跨 task 借用 attempt 与错误时间顺序。
- required/acceptance Check 必须声明 `expected_domain_execution.argv/cwd`；acceptance Evidence 精确匹配，且 Run 包络 command→integrity replay，随后才是 Evidence created 与引用 event。无关成功命令不能覆盖 AC。
- Validator 必须做路径 containment、文件存在、hash、字段类型、reviewer 独立性及 prefix→领域执行→integrity replay→Evidence→引用 event 顺序检查。`command` 记录真实领域执行和 execution record，Completion 绝不重跑；只有独立日志的 `integrity_replay` runtime-locked verifier 可执行，其 argv 精确绑定领域 provenance、artifact ref/hash 与 Evidence/Review binding。
- Evidence 的 `artifact_sha256` 与 current artifact 不一致时，标准机器错误码固定为 `E_HASH_MISMATCH`；不得输出 `E_ARTIFACT_HASH_MISMATCH` 等近义码。
- 只有 current `local_verified` 的成功 `command_execution` 可进入 acceptance registry；failure/manual/external/unverified 只记录事实。
- token、Authorization header、secret、敏感 URL query 必须脱敏后进入 Evidence、memory 或报告。
- V2.36 新源码 Evidence 使用 `schemas/v2.36/protected-git-tree-snapshot.schema.json` 的自动完整变更集 receipt；本节 `source_paths` 继续用于 legacy 数据重放，不能替代当前 snapshot。
- Completion Audit 是任务图之外的只读外部门禁，在候选收尾时运行；failed/blocked 可驱动 LOOP 或结构化停止，只有 passed/achieved 要求 required task 全 accepted。required/blocking Task 或 Audit Evidence 指向本次实际 audit 文件时必须以 `E_AUDIT_SELF_REFERENCE` 失败。
- Review 最低等级来自 `harness_contract.task_type`、`required_review_class` 与风险；outer 字段不能覆盖，semantic/structural 不可互代，replica 至少 comparison，security/external-write/regulated 至少 safety。
- comparison 义务在升级 safety 后仍保留；generic comparison 只接受当前 hash 锁定的 trusted `compare-artifacts` exact-hash 模式、不同 path/inode 的 actual/baseline、registry-bound 预批准者和 exact passed log。pixel 阈值走专用 validator。

## Profile 与 Router

机器字段只使用 schema 小写枚举 `lite|standard|full|regulated`；V2.3 只保留枚举兼容，当前派生语义以 `references/rules-project-sizing.md` 为准。

- Lite：small/low-risk 的局部文档、配置、CLI 或原创 UI 小改；使用 targeted validation，不生成空仪式任务。
- Standard：medium，或 small 但涉及 backend/API、medium risk、跨文件行为；保留环境预检、适用独立测试/Review，Architecture 按边界变化触发。
- Full：large、release、replica/reference-driven UI 或多系统任务；使用完整 Architecture/Environment/独立测试/Harness/Evidence 门。
- Regulated：高风险、外部写入、安全/审批/凭证/破坏性任务；必须升级授权和独立复核。

## Migration

- V2.2 `tasklist.md` 可读；V2.3 只写 `TaskList.md`。
- 同时存在 `tasklist.md` 与 `TaskList.md` 时进入 `manual_review`，禁止双写。
- 旧 `done` / `checked` 不直接映射为 `accepted`，必须经 V2.3 Evidence 重验。
- rollback 必须保持原目录、原 TaskList 和原配置 byte-equivalent。
- apply 后的 target tree 由 manifest exact 绑定；rollback 前若 current path/type/mode/content 漂移，必须 `E_MIGRATION_ROLLBACK_DRIFT` 且不得覆盖 post-apply 数据。

## Distribution

- Installer 与 blind runner 共用 manifest-driven Git-index selection；blind 只取声明的安全投影。
- manifest、全部 installer files 及每个祖先组件逐级拒绝 symlink/nonregular/越界与 mode drift。
- 准备期 package manifest 必须在 copy 后、staging validation 后和 post-switch 后按 path/mode/size/hash exact 重验；并发 source mutation只能 fail/rollback或保持原 snapshot。

## Release Gate

V2.3 发布候选必须通过 Contract、State、Ledger、Evidence、Canonical、Routing、Capability、Context、Migration、Behavior、Distribution 与 Security Gate。先用唯一官方 manifest 运行隔离 blind-agent eval；它锁定当前环境解析的 CLI path/hash，`provider_trust_level=local_process_attested`，不证明远程模型或签名身份。RC 会从固定 output/trace/evidence 重评分，并在同一调用内直接执行 `scripts/checks/check.sh`。GA 的本地 License 文件只算 proposal；缺仓库外可信 host/signature attestation 时必须 `E_LICENSE_ATTESTATION_UNVERIFIED`。
