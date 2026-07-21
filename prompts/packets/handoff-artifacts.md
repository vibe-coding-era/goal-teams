---
type: Handoff Artifacts SSOT
title: Handoff Artifacts SSOT
description: Goal Teams 交接物类型、Owner、独立检查者、状态字段和 tasklist 账本的 Single Source of Truth。
tags: [goal-teams, okf, ssot, handoff-artifacts]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Handoff Artifacts SSOT

本文件是 Goal Teams 交接物的 Single Source of Truth。任何角色 workflow、Member Goal Packet、tasklist、Teams 规划表、test plan、acceptance 或最终汇报提到交接物时，都必须使用这里定义的名称、负责人字段、独立检查字段和状态字段；不要在角色文件里另起一套交接物口径。

## SSOT 规则

- `prompts/packets/handoff-artifacts.md` 定义交接物类型和状态字段。
- append-only event ledger 是执行事实源；`TaskList.md` 是 reducer 生成的人类投影视图，记录交接物、具体 Owner/Validator、状态和 Evidence。
- `tasklist.md` 只作为 V2.2 legacy migration 输入；V2.3 禁止双写。所有 SSOT 产出物写入 `versions/<artifact_version>/`。
- `Member Goal Packet` 是成员执行契约，必须只认领 tasklist 中已有或计划创建的交接物。
- 交接物没有独立检查者、有效 `check_state` 或 Evidence 时，不能标记为 `accepted`。
- 交接物字段变化时，先更新本文件，再同步 workflow、template、README 和 runtime 示例。

## V2.3 正交状态字段

```text
task_state:
- planned
- running
- review
- accepted
- blocked
- deferred
- cancelled

check_state:
- not_required
- not_started
- running
- passed
- failed
- blocked
- waived

run_outcome: achieved | partial | blocked | aborted
loop_decision: continue | replan | stop
```

## V2.3 Task 机器必填字段

```text
Task Handoff Record（ledger checkpoint 与 TaskList 投影的同一任务）:
- schema_version: goal-teams-v2.3
- task_id:
- title:
- handoff_artifact:
- artifact_type:
- source_ssot: prompts/packets/handoff-artifacts.md
- owner_agent_type:
- owner_member_id:
- owner_run_id:
- validator_agent_type:
- validator_member_id:
- validator_run_id:
- merge_owner_run_id:
- task_state:
- check_state:
- required_for_done: true | false
- acceptance_blocking: true | false
- attempt_id:
- revision:
- requirement_refs:
- acceptance_criteria_refs:
- artifact_refs:
- evidence_refs:
- harness_refs:
- validation_check_id: <accepted 时与 valid Evidence 绑定>
- validation_run_id: <accepted 时与 valid Evidence 绑定>
- last_event_id:
- last_actor_run_id:
- blocked_reason | deferred_reason: <对应状态时>
```

`owner_agent_type` / `validator_agent_type` 是人类可读扩展；机器验证和独立性使用 identity registry 中的 `owner_run_id` / `validator_run_id`。旧名 `owner_agent_run_id`、`validator_agent_run_id`、`ledger_merge_owner_run_id` 不得写入 V2.3 canonical Task。

## 交接物类型

| artifact_type | 交接物 | 默认 Owner agent_type | 默认独立检查者 agent_type | 必须登记到 ledger | 典型证据 |
| --- | --- | --- | --- | --- | --- |
| `tasklist_projection` | reducer 生成的 TaskList 人类视图 | ledger owner / reducer | `goal_completion_auditor` | 每个项目先建立 ledger 后生成 | `ledger/events.jsonl`、checkpoint、`TaskList.md` byte-equivalent replay |
| `requirement_card` | 需求卡片 | Goal Lead | `goal_reviewer` 或用户确认 | 是 | `spec/requirement-card.md`、确认记录 |
| `requirement_spec_card` | Requirement Specification Card | `goal_requirements_analyst` | `goal_product` 或 `goal_reviewer` | Standard/Full/Regulated 或 route 要求时；Lite 可并入 requirement card | `spec/requirement-spec-card.md`、结构检查、LLM 复核 |
| `prd` | PRD、用户故事、功能验收标准 | `goal_product` | `goal_reviewer` | 新产品/功能、Full/Regulated 或 route 要求时；局部 Lite 修复可结构化 N/A | `spec/PRD.md`、溯源检查、评审记录 |
| `page_spec_card` | Page Specification Card、页面规格卡、组件级视觉契约、交互状态矩阵 | `goal_product` 或 `goal_frontend` | `goal_reviewer` 或 `goal_qa` | 新页面/replica/跨页面状态或 route 要求时写入 | `spec/page-spec-card.md`、视觉契约检查、Harness 证据 |
| `backend_architecture_design` | Backend Architecture Design、后端架构设计 | `goal_backend` | `goal_reviewer` | `gates.architecture=required` 的后端任务写入 | `spec/backend-architecture-design.md`、架构评审、API/数据/权限边界 |
| `frontend_architecture_design` | Frontend Architecture Design、前端架构设计 | `goal_frontend` | `goal_reviewer` 或 `goal_qa` | `gates.architecture=required` 的前端任务写入 | `spec/frontend-architecture-design.md`、组件库/状态/路由/数据边界 |
| `architecture_design` | Architecture Design、跨端架构设计 | `goal_backend`、`goal_frontend` 或 `goal_product` | `goal_reviewer` | 涉及架构决策时写入 | `spec/architecture-design.md`、架构评审 |
| `environment_configuration_plan` | Architecture Design 内的 Development Configuration Plan 与 Production Configuration Plan | 对应 Architecture Design Owner | `goal_reviewer` 或 `goal_qa` | 每份适用 Architecture Design 必须写入；Lite 未创建 Architecture 时记录不适用原因 | 配置来源/引用、依赖、网络/数据、可观测性、验证、差异；不记录 secret 值，生产环境规划不代表部署授权 |
| `development_environment_check` | Architecture accepted 后的开发环境检查与安全 remediation | 当前 `goal_backend` / `goal_frontend` 实现 Owner | `goal_qa` 或 `goal_reviewer`（必须是不同 run） | Full/Regulated 或 route 要求时写入；Lite 用 preflight | `spec/development-environment-check.md`、Architecture/workspace/tool exact hash、argv/cwd/log、remediation before/after、current `local_verified` Evidence；只有 `ready` 开实现门 |
| `security_assessment` | 代码、依赖、secret、注入、端口暴露只读安全评估 | `goal_security` | `goal_reviewer`（不同 run，最低 safety） | 路由命中 security 时 | coverage、授权记录、findings、脚本 + 独立语义安全复核 |
| `performance_benchmark_proposal` | SQL、页面、数据路径 baseline 与优化 proposal | `goal_performance` | `goal_qa` 或 `goal_reviewer` | 路由命中 performance 时 | environment/data scale/argv/cwd/candidate digest/current benchmark Evidence |
| `prompt_cache_observation` | V2.40 Cache Evidence 四状态轴、V2.38-compatible route-static/宿主 runtime identity 与轮后 usage | benchmark runner / telemetry owner | `goal_qa` 或 `goal_reviewer`（不同 run） | telemetry/cache route 命中时 | structural/host/live/request-hit 状态、route-static digest、manifest status/scope、可用时的 runtime digests、CLI/model/config/package/parser/scenario、raw hash、invalid/unsupported/duplicate counts、covered/cached/uncached、coverage、Tokens/Cache hit-rate unavailable reason |
| `refactor_equivalence_proposal` | 工程、代码、文档结构的行为等价重构 proposal | `goal_refactor` | `goal_qa` 或 `goal_reviewer` | 路由命中 refactor 时 | equivalence contract、regression、holdout、rollback boundary |
| `sqa_process_archive_proposal` | 过程改进与版本化文档归档 proposal | `goal_sqa` | `goal_reviewer` | 路由命中 sqa 时 | version record、index、classification、version directory、sanitized public/private provenance |
| `specialist_improvement_proposal` | 四专家共同的分级改进 proposal | 对应 `goal_security|goal_performance|goal_refactor|goal_sqa` | `goal_reviewer` | 专家建议进入 reviewed 前 | L0/L1/L2、scope、AC、proposal hash、lifecycle、Evidence request |
| `specialist_dispatch_request` | 专家向 Lead 提交的派发请求，不是已派发事实 | 对应只读专家 | Lead 校验 + 独立 `goal_reviewer` | proposal 需实现/测试时 | proposal hash、requested owner/validators、locked/forbidden scope、risk/review class/approval gate |
| `iteration_state_bundle` | Self-release 四文件 LOOP 状态与 transaction/reconcile receipt | Goal Lead / 唯一 state writer | `goal_qa` 或 `goal_completion_auditor`（不同 run） | 仅当前 `goal-teams-self-release-v2.42` 每个 committed revision 登记；V2.41/V2.40/V2.39/V2.38 只读 replay | `feature_list.json`、`progress.md`、`contract.md`、`log.md`、journal/receipt hash、marker-last/CAS/reconcile Evidence |
| `public_completion_doc` | Self-release 审计完成且清除调用痕迹的公开交付文档 | `goal_docs` 或 Goal Lead | `goal_reviewer` 与最终 `goal_completion_auditor` | 仅 self-release 进入 `docs/archive/V2.42/<delivery_id>/` 前写入 | accepted source hash、sanitizer report、public manifest/tree digest、private provenance receipt；不包含 invocation/tool-call/transport/raw log |
| `protected_git_tree_snapshot` | 自动完整 Git 变更集 receipt | runtime / ledger owner | `goal_reviewer` 或 `goal_completion_auditor` | V2.36 代码 Evidence 必需 | baseline ancestor、tracked 修改/删除、non-ignored untracked、isolated tree、HEAD/refs/index/object-store 前后指纹 |
| `host_attested_identity_registry` | 宿主签发的 Agent identity registry | host adapter | `goal_reviewer` 或 `goal_completion_auditor` | V2.36 独立验证必需 | issuer/run/transport/nonce/time/core hash/signature；trust key 不进入产物 |
| `v236_execution_contract` | V2.36 自动派生执行门契约 | route runtime | host adapter + `goal_reviewer` | 每个 V2.36 route 必需 | execution profile、required review class、完整 gates、conditional scopes、specialists/rules/reasons 与 canonical digest |
| `host_route_receipt` | 宿主签名的 V2.36 route/target receipt | host adapter | `goal_reviewer` 或 `goal_completion_auditor` | V2.36 acceptance 必需 | actual repository fingerprint/kind、trusted release base、route digest、派生 task/profile、execution contract、nonce/time/signature |
| `host_challenge_state` | 跨调用 nonce 消费账本 | host adapter | 受保护 completion validator | V2.36 acceptance 必需；不得进入项目仓库 | absolute host-private path、0600、MAC、lock、challenge hash；不保存 raw nonce 或 trust key |
| `v236_acceptance_input_snapshot` | 完整验收输入快照 manifest | host adapter | `goal_completion_auditor` | V2.36 acceptance 必需 | 自动覆盖 Evidence/Review/Harness/Audit/ledger/checkpoint/traceability/TaskList 与递归引用的 ignored logs/reports/artifacts；mode/size/hash/hash_mode；不接受手填删减 manifest |
| `v236_acceptance_binding` | route/snapshot/identity 与完成输入的完整绑定 | Goal Lead / ledger owner | host adapter + `goal_completion_auditor` | V2.36 Audit、Review、Harness 必需 | `goal-teams-v2.36-acceptance-binding-v1`、route/snapshot/registry/Evidence/ledger/checkpoint/traceability/TaskList/input-snapshot hashes、policy 与 execution contract |
| `v236_acceptance_core_binding` | current Evidence 的非循环完成绑定 | Evidence producer | host adapter + `goal_reviewer` | 每条 V2.36 acceptance Evidence 必需 | product/route/target/release/snapshot/attested registry/trusted base/profile/execution contract；不自引用 Evidence registry 或完成输入 hashes |
| `html_prototype` | HTML Prototype | `goal_frontend` | `goal_qa` 或 `goal_reviewer` | 新页面/replica/route 要求时；既有页面 Lite 局部改动可结构化 N/A | `spec/HTML-prototype.html`、截图、控制台检查 |
| `frontend_implementation` | 前端开发、页面实现、交互实现 | `goal_frontend` | `goal_qa` 或 `goal_reviewer` | 前端任务必须写入 | diff 摘要、截图、控制台、组件断言 |
| `backend_unit_test_cases` | 后端 TDD 单元测试用例 | `goal_unit_test_designer` | `goal_reviewer` 或 `goal_qa` | `gates.tdd=required` 时写入；Lite 可用 inline targeted assertion | 测试文件、预期失败/覆盖说明、断言审查 |
| `backend_implementation` | 后端开发、API/领域/存储实现 | `goal_backend` | `goal_reviewer` | 后端任务必须写入 | diff 摘要、单测和集成测试引用 |
| `backend_unit_test_execution` | 后端执行 TDD、单元测试运行证据 | `goal_unit_test_runner` | `goal_qa` 或 `goal_reviewer` | `gates.tdd=required` 时写入 | 测试命令、红/绿记录、失败日志、覆盖结果 |
| `api_integration_test_script` | API 集成测试脚本生成 | `goal_api_integration_test_designer` | `goal_reviewer` 或 `goal_qa` | `gates.integration=required` 时写入 | Python/pytest 测试文件、fixture、环境说明 |
| `api_integration_test_plan` | API 集成测试、场景和数据准备 | `goal_api_integration_test_designer` | `goal_qa` | `gates.integration=required` 时写入 | 测试矩阵、端点/认证/mock/数据准备 |
| `api_integration_test_execution` | API 集成测试执行 | `goal_api_integration_test_runner` | `goal_qa` 或 `goal_reviewer` | `gates.integration=required` 时写入 | pytest 命令、日志、报告、失败截图/响应 |
| `e2e_test_cases` | 生成 E2E 测试用例 | `goal_e2e_test_designer` | `goal_reviewer` 或 `goal_qa` | `gates.e2e=required` 时写入 | Playwright/浏览器脚本、路径覆盖、viewport |
| `e2e_test_execution` | 执行 E2E 测试用例 | `goal_e2e_test_runner` | `goal_qa` 或 `goal_reviewer` | `gates.e2e=required` 时写入 | 命令、截图、trace、console/network 记录 |
| `bugfix` | BugFix、缺陷修复 | 对应实现 Owner agent_type | 发现问题的测试/评审 agent_type；必须派发具体 run | 有失败证据时必须写入 | failure_report、修复 diff、回归证据 |
| `test_report` | 测试报告生成 | `goal_qa` 或 `goal_docs` | `goal_completion_auditor` | Full/Regulated 或 route 要求时；Lite/Standard 可并入 acceptance | `reports/test-report.md`、覆盖/失败/风险汇总 |
| `harness_contract` | Harness Contract | 认领任务 Owner | `goal_qa` 或 `goal_reviewer` | 是 | Harness 字段、命令、人工检查、失败报告格式 |
| `implementation_change` | 代码或配置变更 | 实现 Owner agent_type；ledger 记录具体 member/run | `goal_qa` 和/或 `goal_reviewer` 的具体 run | 是 | diff 摘要、测试输出、review 记录 |
| `test_plan` | Test Plan、测试用例、测试说明 | `goal_qa` | `goal_reviewer` | Standard/Full/Regulated 或 route 要求时；Lite 可使用 inline Harness | `spec/test-plan.md`、测试命令、断言审查 |
| `evidence_record` | Evidence、脚本报告、截图、日志 | 测试 Owner 或认领任务 Owner | `goal_reviewer` 或 `goal_completion_auditor` | 是 | `progress.md`、报告路径、截图路径、JSONL |
| `loop_decision_record` | Lead LOOP Decision、Loop Gate、状态快照、续跑决策 | Goal Lead | `goal_completion_auditor` | 长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖任务必须写入 | `progress.md`、`loop-state.json`、续跑 Teams 规划表 |
| `acceptance_record` | Acceptance、验收记录 | `goal_docs` 或 Goal Lead | `goal_reviewer` 或 `goal_completion_auditor` | 是 | `spec/acceptance.md`、验收清单、最终结论 |
| `doc_capsule` | Doc Capsule | 读取文档的成员 | Goal Lead 或下游接收者 | 需要长期复用时写入 | `.codex/goal-teams/doc-capsules.jsonl` |
| `dual_review_record` | Dual Review Record | 执行校验的 QA/reviewer | `goal_completion_auditor` | 对比和校验类任务必须写入 | 脚本复核、LLM 复核、最终决策 |
| `ledger_event` | Task 状态或交接物变化事件 | 当前任务 Owner；合并者只能是 ledger owner | `goal_completion_auditor` | 是 | `ledger/events.jsonl` event、revision/CAS 结果、reducer 生成的 `TaskList.md` |

## 交接顺序

1. Goal Lead 在 Plan 阶段先注册 identity，再写入初始 `task_patch` event，由 reducer 生成 `planned` TaskList 行。
2. 成员认领后提交带 `attempt_id` 和 `base_revision` 的 event，将任务迁移到 `running`。
3. Owner 用 `artifact_created` 只登记非空 `artifact_refs`；状态变化另用 `task_patch`，让被验任务先进入 `running|review`。此时记录非空 ledger prefix 的 `ledger_revision` 与 digest。
4. Runner 在该 prefix 后按 Check 的 `expected_domain_execution.argv/cwd` 执行真实领域命令，固化 domain log 与 exact execution record；再用不同日志运行 runtime-locked `integrity_replay`，最后生成 Evidence。Run 必须完整包络两层执行，随后才是 Evidence created 与引用 event；Completion 只重放完整性层。然后独立 validator 才追加 `check_executed`，绑定 `check_state`、`validation_check_id`、`validation_run_id` 和 `evidence_refs`。
   `artifact_sha256` 与 current artifact 不一致时，标准机器错误码是 `E_HASH_MISMATCH`；不得改写为自然语言别名，也不得用于 acceptance。
5. 独立检查者按 Harness 内层 `task_type` / `required_review_class` 约束 Review；需要脚本时报告必须含 `domain_execution`、独立 `integrity_replay` 与 `binding_digest`。comparison（含升级 safety）另绑定 trusted exact-hash tool、不同 path/inode 的 actual/baseline 与 registry 中独立预批准者。随后提交 `review_completed` event；它必须由 `validator_run_id` 对应 run 发出，且 `task_state=accepted` 与 valid Evidence registry 的 Check/Run 一致。
6. V2.36 候选 runtime 只生成待宿主验收的 bundle 并返回 `E_V236_HOST_ADAPTER_REQUIRED`，不得写 replay state。仓库外宿主先冻结覆盖 TaskList、Evidence/Review/Harness/Audit、ledger/checkpoint/traceability 及其引用日志/报告/artifact 的完整输入树，再验证 route receipt、protected snapshot、所有 host attestation、完整/core binding 与派生执行门；只有全部通过时，才一次性把 route + identity challenges 写入宿主私有 state。任何失败或缺输入都不得部分消费或回退 legacy identity/source_paths。
7. ledger owner 只负责持锁/CAS 合并；不代替 reviewer。TaskList、checkpoint 和 traceability 的 Task 对象由 reducer 重建并 byte-equivalent 校验。Completion Audit 在候选收尾时作为外部门禁运行：failed/blocked 驱动 LOOP/停止，只有 passed/achieved 要求 required task 全 accepted；Audit 不得成为 required/blocking 自证任务。

V2.35 专家只能提交 assessment/proposal、revision-bound `specialist_task_patch` 和 `specialist_dispatch_request`；task patch 是 ledger event/patch，不是第七种 artifact type。固定能力为 `coordination_depth=1`、`can_spawn_subagents=false`、`can_dispatch=false`、`dispatch_owner_agent_type=goal_lead`、`handoff_mode=proposal_only`。Lead 接受后另建实现、测试和验证任务；专家不得直接写产品/中央 TaskList 或把自己的 proposal 标成 applied/verified。

## V2.0 TaskList 最小颗粒度

Full/Regulated Profile 的每个功能切片在版本子目录 `TaskList.md` 中按以下颗粒度拆分；Lite/Standard 只创建适用任务，不适用项使用结构化 `not_applicable_reason`，不得生成空仪式任务：

| 顺序 | 功能级任务 | artifact_type | 默认 Owner agent_type（派发时必须具体到 member/run） | 默认前置 |
| --- | --- | --- | --- | --- |
| 1 | 某功能的需求规格卡 | `requirement_spec_card` | `goal_requirements_analyst` | `tasklist_projection`（其事实源为 ledger） |
| 2 | 某功能的 PRD | `prd` | `goal_product` | `requirement_spec_card` |
| 3 | 某功能的页面规格卡 | `page_spec_card` | `goal_product` 或 `goal_frontend` | `prd` |
| 4 | 某功能的 HTML 原型 | `html_prototype` | `goal_frontend` | `page_spec_card` |
| 5 | 某功能的前端架构设计 | `frontend_architecture_design` | `goal_frontend` | `prd` |
| 6 | 某功能的后端架构设计 | `backend_architecture_design` | `goal_backend` | `prd` |
| 7 | 某功能的 Architecture 双环境配置规划 | `environment_configuration_plan` | 对应 Architecture Owner | applicable Architecture Design |
| 8 | 某功能的开发环境检查 | `development_environment_check` | 当前实现 Owner | applicable Architecture Design accepted + `environment_configuration_plan` |
| 9 | 某功能的前端开发 | `frontend_implementation` | `goal_frontend` | `frontend_architecture_design`、`development_environment_check=ready`、`html_prototype` |
| 9 | 某功能的后端 TDD | `backend_unit_test_cases` | `goal_unit_test_designer` | `backend_architecture_design`、`development_environment_check=ready` |
| 10 | 某功能的后端开发 | `backend_implementation` | `goal_backend` | `backend_unit_test_cases`、`development_environment_check=ready` |
| 11 | 某功能的后端执行 TDD | `backend_unit_test_execution` | `goal_unit_test_runner` | `backend_implementation` |
| 12 | 某功能的 API 集成测试脚本生成 | `api_integration_test_script` | `goal_api_integration_test_designer` | `backend_architecture_design`、`development_environment_check=ready` |
| 13 | 某功能的 API 集成测试 | `api_integration_test_plan` | `goal_api_integration_test_designer` | `api_integration_test_script` |
| 14 | 某功能的 API 集成测试执行 | `api_integration_test_execution` | `goal_api_integration_test_runner` | `backend_unit_test_execution`、`api_integration_test_plan` |
| 15 | 某功能的生成 E2E 测试用例 | `e2e_test_cases` | `goal_e2e_test_designer` | `frontend_implementation` |
| 16 | 某功能的执行 E2E 测试用例 | `e2e_test_execution` | `goal_e2e_test_runner` | `e2e_test_cases` |
| 17 | 某功能的 BugFix | `bugfix` | 对应实现 Owner | 任一失败测试或评审 |
| 18 | 某功能的测试报告生成 | `test_report` | `goal_qa` 或 `goal_docs` | 全部验证项 |
