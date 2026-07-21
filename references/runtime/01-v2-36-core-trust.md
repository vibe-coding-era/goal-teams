---
type: Goal Teams Runtime Reference Part
title: V2.36 Core trust 入口
description: Goal Teams runtime 渐进式分片。
tags: [goal-teams, runtime, progressive-loading]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# V2.36 Core trust 入口

## V2.36 Core trust 入口

- `v236-snapshot-create <repo> --baseline <commit> --receipt <private-path>`：自动发现完整 Git 变更集，以临时 index/object DB 构建 receipt；不接收路径清单，不改主 HEAD/refs/index/object store，空 delta、非祖先 baseline、symlink/submodule/unsafe path fail closed。
- `v236-snapshot-validate <repo> <receipt>`：从当前 worktree 重新隔离构树，验证完整 change manifest 与仓库保护指纹。
- `v236-validate-attested-identities <registry> --expected-issuer <issuer>`：环境变量 key 只支持兼容诊断并返回 `acceptance_eligible=false`；candidate CLI 不提供 `state/key/issuer/context` 的 acceptance 入口，跨调用 challenge 只由仓库外宿主保存和消费。
- 宿主先签发 route receipt，绑定实际 repository fingerprint/kind、trusted release base、route digest 与自动派生 profile。候选仓库的 `completion-audit` 不论来自 CLI 还是 Python 调用都没有 V2.36 acceptance 权限，必须返回 `E_V236_HOST_ADAPTER_REQUIRED`。仓库外宿主先把完整验收输入复制到不可变、宿主拥有的快照，重验 route、identity、执行门及全部引用文件，最后在同一宿主事务中消费 route + identity challenges；候选 runtime 不写 replay state。
- `scripts/v23/v236_trust.py` 中 `_host_reference_*` 仅用于验证算法和防重放测试，返回 `host_reference_only=true`、`acceptance_eligible=false`；它们不是公开宿主适配器，也不能作为 Completion 依据。公开 candidate acceptance API 永远不读取或写入调用方指定的 state，统一返回 `E_V236_HOST_ADAPTER_REQUIRED`。
- Audit、Review、Harness 使用同一完整 `goal-teams-v2.36-acceptance-binding-v1`，绑定 route/snapshot/attested registry/Evidence/ledger/checkpoint/traceability/TaskList、递归引用文件的 acceptance-input snapshot，以及重派生 execution contract；每条 current Evidence 使用 `goal-teams-v2.36-acceptance-core-binding-v1` 绑定同一 product/route/target/snapshot/attested registry/trusted base/profile/execution gates，避免自引用完成输入 hashes。所有 secret detection/redaction 统一使用 `scripts/v23/v236_security.py`；当前机器 schema 位于 `schemas/v2.36/`。legacy V2.3 `source_paths`、无 attestation identity 或无 state 诊断验证只用于兼容读取，不能支撑新的 V2.36 acceptance。

## Self-release 兼容运行扩展

本节的 V2.34 CLI/状态格式是当前 `goal-teams-self-release-v2.42` 使用的历史兼容实现，只在可信路由命中该 Profile 后加载；V2.41/V2.40/V2.39/V2.38 Profile 只用于历史 replay。普通 `goal-teams-core-v2.5` 任务不得继承四文件、固定第 9/11 轮、评分或公开归档。该控制平面不改写 V2.3 核心枚举，不代替 reducer，也不声明 daemon、后台 runner、生产审批或宿主恢复能力。

### 四文件 bundle 与 API 语义

Self-release 完整 bundle 必须在同一版本目录包含 `feature_list.json`、`progress.md`、`contract.md`、`log.md`；当前详细专项门见 `references/profiles/goal-teams-self-release-v2.42.md`。所有写 API 除 bootstrap 外必须提供 expected bundle revision 与 digest，保留未识别扩展字段，先持久化 intent/phase 再触发副作用。建议 API：

```python
load_state_bundle(root) -> StateBundle
validate_state_bundle(root, *, ledger_events=None) -> ValidationResult
commit_state_transaction(root, mutation, *, expected_bundle_revision, expected_digest, actor_run_id) -> StateBundle
reconcile_state_bundle(root, *, mode, expected_bundle_revision, expected_digest) -> StateBundle
evaluate_contract_gate(bundle, identity_registry, ledger_events, review_record) -> GateResult
evaluate_environment_gate(bundle, environment_report, evidence_registry, ledger_events) -> GateResult
evaluate_implementation_gate(bundle, task_id, ledger_events, evidence_registry) -> GateResult
create_protected_candidate_snapshot(repo_root, *, baseline_commit, receipt_path) -> SnapshotReceipt
validate_protected_candidate_snapshot(repo_root, receipt) -> ValidationResult
evaluate_delivery_gate(bundle, completion_proof, archive_descriptor, *, source_context) -> GateResult
```

合同、架构、环境或源树 digest 变更时，依赖 gate/score/Evidence 立即 stale，不得仅更新 marker 继续。恢复仅可对 journal 证明为同一 transaction 且每个 target 等于 old/new hash 的状态幂等 roll-forward；否则进入 `reconcile_required|blocked`。

### Self-release CLI 入口

V2.34 命令仍由 `python3 scripts/v23/goalteams_v23.py` 暴露，stdout 使用现有 JSON envelope，人类说明写 stderr。

| 子命令 | 语义 |
| --- | --- |
| `v234-state-init` | 新 bundle bootstrap；已有 legacy 文件只能通过 exact digest 显式 adopt，不自动覆盖 |
| `v234-state-validate` | 只读验证 marker/progress/contract/log/checkpoint 和 pending journal，返回结构化状态/错误 |
| `v234-state-transition` | 执行一个合法 phase transition；不得写 `achieved` 或 delivery 字段 |
| `v234-state-reconcile` | 仅 roll-forward 可证 pending journal 或从 receipt+ledger replay，不按 mtime/多数票 |
| `v234-contract-gate` | 验证 immutable contract、独立 review、assertion set 和 ledger preimplementation gate |
| `v234-environment-record` | 在 Architecture accepted 后登记环境报告/current Evidence，环境漂移即 stale |
| `v234-implementation-gate` | 只读校验 contract/architecture/environment/test-design 顺序，返回可绑定 receipt |
| `v234-score-record` | 一次写入四维固定 rubric 与独立 Evidence |
| `v234-log-append` / `v234-log-diagnose` | 追加 GTLOG，或返回每条因果链首个确定性 divergence |
| `v234-bottleneck-recompute` | 从 current required blocking gaps 按四级 tuple 重算 bottleneck |
| `v234-reset-plan` / `v234-reset-apply` / `v234-reset-rebind-task` | 第 9 轮预检 `.goalteams-candidates/<candidate_id>`，并隔离到 `.goalteams-quarantine/<reset_id>/<candidate_id>`；无 purge；早期 V2.34 receipt 的任务投影只能从 immutable authorization ledger event 经 CAS、identity 与 checkpoint 校验后修复 |
| `v234-closure-ledger-binding` / `v234-closure-legacy-digest` | 从普通、单链接源文件重建 state-init 所需 ledger binding 或四文件 exact legacy digest，并原子写入私有 snapshot；不执行 adopt |
| `v234-closure-reset-snapshot` | 验证 ledger 内的独立 reset authorization，持久化 authorization + no-mutation plan；不执行 quarantine |
| `v234-loop-advance` | 使用每步最新 CAS 沿正常边推进到指定 iteration/phase，并持久化逐事务 receipt；iteration 9 reset gate 与 iteration 11 delivery 边界仍由 runtime 强制执行 |
| `v234-closure-build` | 从真实 ledger/checkpoint/Evidence/review/audit、受保护 candidate snapshot（或兼容 commit delta）与公开源文件生成 archive descriptor、completion proof、source context 和 completion；全部门禁通过后才原子落私有 snapshot |
| `v234-delivery-gate` | 第 11 轮只读列出全部未闭合 gate，不写 archive/achieved |
| `v234-candidate-snapshot` | 用临时 `GIT_INDEX_FILE`、临时 object directory 和主 object alternate 重建当前 V2.34 产品 tree receipt；不改变主 index、HEAD、branch 或 refs |
| `v234-publish-guard` | staged index/非空 commit delta 拒绝过程包、调用轨迹、secret 与不可信文件；`--snapshot-receipt` 重建并校验受保护产品范围、当前 bytes 与仓库无污染指纹 |
| `v234-deliver` | 唯一 `achieved` 写入口；原子建立 `docs/archive/V2.34/<delivery_id>/` 并最后提交 marker |

所有 `v234-closure-*` 输出目录必须位于版本目录的 `.goalteams-state/` 下且在调用前不存在；工具拒绝覆盖、符号链接、多硬链接、逃逸路径与不一致 replay。`v234-closure-build` 生成的 `completion-proof.json` 必须作为普通文件被 `source-context.json` 精确引用；proof 的 required task 集必须等于 checkpoint 中全部 `required_for_done|acceptance_blocking` 任务，Audit 还必须精确绑定同一 required/evidence 集、ledger revision、task-state digest、bundle revision/digest 和 Review 文件 hash。缺任一绑定均 fail closed。

dirty worktree 的 candidate proof 默认使用 `v234-candidate-snapshot <repo> --baseline-commit <commit> --receipt <private-path>`。该命令只选择冻结的 V2.34 产品面，要求 delta 非空并至少包含 `VERSION`、V2.34 runtime/CLI 和 V2.34 测试；候选 tree/blob 写入临时 object directory，主 object database 仅作只读 alternate。receipt 记录 baseline/tree OID、完整 changed-path/blob manifest 及调用前后的 index/HEAD/branch/refs 指纹；验证时从当前 bytes 重新构树，源码漂移、receipt 篡改、主 index/refs 改变或 `HEAD → HEAD` 空差异都会失败。兼容 commit mode 仍可用，但 baseline→candidate 必须有真实非空 delta。快照是 delivery 输入，不是 acceptance，也不会写 `achieved`。

### Self-release 公开归档与私有 provenance

archive descriptor 只能引用 `publication_state=completed`、`visibility=public`、普通文件且已独立 accepted 的产物。sanitizer 必须生成副本而不原地改写源，拒绝凭证、绝对 home path、Member Goal Packet、raw log、`spawn_agent`/tool-call 轨迹、transport handle、旧启动身份模板，以及 `GoalTeamsWork-*` 内的 ledger/evidence/review/audit/harness/identity/provenance。公开 manifest 只记录产物 ID、公开相对路径、source/public hash、分类、validator、contract revision、size/media type 和时间；完整 source ref/hash、ledger prefix、sanitizer 版本与 transaction ID 保留在非公开 receipt。

`v234-deliver` 先在同父目录临时路径生成公开副本/manifest，再原子 rename 为 delivery id，fsync archive parent，最后以 `log.md → progress.md → feature_list.json` 顺序提交状态。目标已存在时只有 tree/manifest digest 完全一致可幂等重放；崩溃后没有完整 journal 的孤立公开目录不产生 `achieved`。

## 运行形态

Goal Teams = Goal Lead + 独立 subagent 成员。

```text
Goal Lead
  - 显式调用或会话首次建立身份时简短汇报：我是 Goal Teams Lead V2.42。
  - 遵守 RULES.md：执行优先，只报告已验证事实，未验证不宣称完成，不输出无关解释或建议
  - 只有缺失历史资料会改变执行时才询问；完整上下文下直接工作
  - 默认中文沟通
  - 用简洁、人类友好的方式和用户交流
  - 治理文档默认中文；代码、注释、测试和产品字符串遵循目标仓库约定
  - 把用户目标转成 Done Criteria
  - 先写需求卡片，说明核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险
  - 把 SPEC 转成可追溯 Harness 契约和证据要求
  - 每轮 Integrate 后记录 Loop Decision
  - 对长任务、自动续跑、生产流、Benchmark、E2E、像素对比或跨成员依赖任务记录 Loop Gate 和状态快照
  - 判断 Benchmark 是否适用，默认不创建外层评估目录
  - 对长任务、自动续跑、生产流、Benchmark、E2E 或像素对比任务记录 Budget Gate
  - 对并发写入记录 Conflict Policy
  - 执行前强制进入 Plan 模式
  - 规划和方案阶段主动澄清
  - 检查 AGENTS.md / agent.md / CLAUDE.md / claude.md
  - 缺少项目指南时使用 references/default-AGENTS.md
  - 写文档前确认项目版本和输出目录
  - 多文档前先创建 index.md 和 memory.md
  - 发现或创建 SPEC 文档
  - 建立版本目录 append-only ledger，并由 reducer 生成 TaskList.md 投影
  - 按功能级颗粒度拆分需求规格卡、PRD、页面规格卡、HTML 原型、前端开发、前后端架构设计、后端 TDD、后端开发、后端执行 TDD、API 集成测试脚本生成、API 集成测试、API 集成测试执行、E2E 用例生成、E2E 执行、BugFix 和测试报告
  - 用 OKF Markdown 持久化过程和结果
  - 为每个生成文档、代码变更、测试用例安排独立校验
  - 用表格提出成员和任务归属
  - 展示 Teams 规划表；默认等待用户确认，直接执行词除外
  - 使用数字选项，方便用户回复 1 / 2 / 3
  - 创建 Member Goal Packet
  - 启动独立 subagents
  - 路由消息和阻塞
  - 整合结果并验证完成状态
  - 看似完成后启动新的 goal_completion_auditor
  - 对已确认范围内的未完成工作自动续跑，不再要求用户确认

Subagent Member
  - 接收一个 Member Goal Packet
  - 遵守 RULES.md，保持简洁，报告事实，未验证时明确标注
  - 分离 agent_type、agent_run_id、member_id、display_name 和 transport_handle；独立性使用 agent_run_id
  - 优先使用 goal_* 自定义 subagents；内置 team_* 英文昵称只作为 transport handle
  - 如果右边栏显示 Reviewer C / QA B 这类英文昵称，仍以中文 member_id 和 display_name 自称
  - 默认中文回复
  - 使用用户指定的 skill/subagent；指定 skill 时展示名使用 skill 名称 + 任务名
  - 认领具体任务
  - 只加载必要文档
  - 输出 Doc Capsules
  - 执行自己的目标循环
  - 按 Harness Contract 返回证据、失败报告或不适用原因
  - 报告结构化 task_state/check_state，并提交 event/patch；不得直接编辑中央 TaskList
  - 不自我批准生成产物

Completion Auditor
  - 在所有计划任务看似完成、延期或阻塞后，以新的只读 subagent 运行
  - 检查 tasklist、progress、acceptance、测试、文档、校验证据、未解决阻塞和剩余风险
  - 输出单一 `audit_state`（`passed`、`failed` 或 `blocked`）、run_outcome、建议的 loop_decision 与 open gaps
  - 不编辑文件，不启动嵌套团队
```

每个成员都是独立 subagent。`agent_type`/`skill_or_subagent` 记录真实可加载能力，`agent_run_id` 唯一标识本次运行，`member_id` 是项目内稳定 ID，`display_name` 使用中文角色 + 任务名（例如 `后端-WIKI 列表后端开发`），`transport_handle` 只承担宿主路由。用户指定 skill 时更新 agent_type 和显示规则；不得把 skill 名、显示名或 transport handle 当成 agent_run_id。

默认成员优先使用 `goal_*` 自定义 subagents。内置 `team_*` 只有在 capability manifest 证明能力等价、权限不扩大时才可自动 fallback；否则进入 blocked 或请求用户。如果宿主显示 `Reviewer C`、`QA B`、`Implementer A` 等英文昵称，只记录为 `transport_handle`；用户可见内容使用本地化 display_name，机器记录保留 member_id 与 agent_run_id。成员回复首行使用 `成员：<中文展示名>`。

例外：如果用户明确要求 `openspec` 或 `superpower`，Goal Teams 默认只作为 Goal Lead 运行，负责协调、澄清、检查环境、准备索引和 lead 级产物；除非用户确认完整 Goal Teams 执行，否则不启动角色 subagents。

## 强制 Plan 模式

Goal Teams 总是从 Plan 模式开始。直接执行词只跳过确认等待，不跳过规划、风险检查和 `Teams 规划表`。

1. 显式调用或会话首次建立身份时使用启动语；已有完整上下文时直接执行。
2. 只有历史资料缺失会改变方案时才询问；不得为了仪式暂停已明确任务。
3. 如果用户提供历史资料路径、链接或经验要点，先纳入 Plan 的资料输入和假设；如果用户回复“无”“没有”“2”或其他自然语言表示没有历史资料，继续规划；如果用户已明确要求直接执行且未提供历史资料，不因此阻塞，记录为“历史资料：未提供”。
4. 检查项目指南：`AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md`。
5. 如果没有项目指南，加载 `references/default-AGENTS.md` 作为默认指南，并建议复制到项目根目录 `AGENTS.md`。
6. 询问或推断项目版本号；输出目录未确定前，不写过程文档。
7. 目标、范围、验收标准、优先级、约束、用户角色、设计风格、数据合同、风险容忍度或部署目标不清楚时，先澄清。
8. 用户未指定生成目录时，默认输出根目录为 `GoalTeamsWork-<project_version>/`；用户指定目录时按用户目录执行。
9. 确认 artifact version，并把 SSOT 产出物写入 `versions/<artifact_version>/`；不同版本不得混放。
10. 把问题、回答、假设和决策写入 OKF Markdown，通常是版本子目录的 `plan.md`。
11. 如触发 Lead LOOP，读取 `prompts/lead/loop.md`，并在 `plan.md` 或 `progress.md` 写入 Loop Gate、已确认范围和停止条件。
12. 创建多个文档前，先创建或更新根 `index.md`、`memory.md`，建立 ledger 并由 reducer 生成版本子目录 `TaskList.md`；legacy `tasklist.md` 只读迁移。
13. 写入包含用户故事和功能验收标准的 OKF 需求卡片，发现或创建 SPEC 与每个任务的 Harness 契约；任务变化先写 ledger，再由 reducer 更新 TaskList 投影。
14. 后端任务安排 Backend Architecture Design -> `goal_unit_test_designer` -> `goal_backend` -> `goal_unit_test_runner` -> `goal_api_integration_test_runner`；`goal_api_integration_test_designer` 可在架构后并行生成 Python + pytest 集成测试。
14. 前端任务安排 Frontend Architecture Design/Page Specification/HTML Prototype -> `goal_frontend` -> `goal_e2e_test_designer` -> `goal_e2e_test_runner`。
15. 提出成员分工、skill/subagent 分配、任务认领、locked_scope、文档更新、测试 Owner、Harness 证据和完成标准。
16. 标明每个任务的 workflow：串行或并行；串行任务必须列出前置任务，不能让有依赖的成员同时修改共享范围。
17. 为每个生成产物提出独立校验者：文档、代码和测试用例都要覆盖，并说明校验 Harness 或人工检查方式。
18. 展示 `Teams 规划表` 和相关确认表。
19. 默认等待用户确认后，才启动 worker subagents 或编辑实现文件。
20. 如果最新提示词包含 `直接执行`、`直接开始`、`直接做`、`直接改`、`开始执行`、`不用确认`、`无需确认`、`跳过确认`、`按你的方案执行` 等词，展示 Plan 表格后跳过首次等待确认。
21. 如果用户说执行已确认计划，仍要展示 `Teams 规划表` 作为执行计划记录。
22. 需要用户选择时，提供数字选项，例如 `1. 确认并执行`、`2. 调整成员或范围`、`3. 只保留方案不执行`。

范围、成员、skill/subagent、locked_scope、风险或停止条件变化时，必须重新进入 Plan 模式。

直接执行规则：

- 直接执行只跳过 Plan 表格后的确认等待。
- 仍要展示环境准备、SPEC 准备、风险、独立校验和四列 `Teams 规划表`。
- 直接执行时表格标题使用 `执行计划（已按用户要求直接执行）`。
- 不绕过安全边界。涉及新范围、破坏性写入、凭证、支付/认证/安全敏感改动、外部审批或关键业务决策时，必须先问用户。
- 用户只说“计划一下”“给我方案”“先别执行”时，不算直接执行。

澄清规则：

- 每次优先问 1-5 个高价值问题。
- 按主题分组，例如业务目标、范围边界、验收标准、设计风格、数据/接口、发布约束、风险审批。
- 能通过读本地文件回答的问题，先自己查，再决定是否提问。
- 必须带假设继续时，把假设明确写进计划和确认表。
- Goal Lead 消息要简短、自然；说明问题为什么重要，但不要堆术语。
- Plan 阶段的问题如果是选项型，优先使用数字选项。用户回复数字时，映射到对应选项；数字越界时只问一个简短追问。

## 语言与持久化

默认语言是中文：

- 核心提示词：用户沟通、计划、TaskList、SPEC、进度和治理文档默认中文；代码、注释、产品字符串、测试名和 fixture 遵循目标仓库约定。
- 计划、方案、表格、进度、SPEC、tasklist、成员包、评审报告和最终总结使用中文。
- 代码、注释、产品字符串、测试名、fixture 和测试说明遵循目标仓库的语言、i18n 与命名约定。
- 代码标识、命令、日志、路径、API 名称、依赖名和精确引用保持原文。
- 用户明确要求其他语言时，只对指定产物使用对应语言。

成员命名：

- 用户可见表格、packet 和 state 使用本地化 `display_name`；机器字段另存 `agent_type`、唯一 `agent_run_id`、稳定 `member_id` 与 `transport_handle`，不得互相复用。
- 默认 subagent 成员使用中文角色名作为前缀，例如 `后端-WIKI 列表后端开发`、`前端-WIKI 列表页面开发`、`测试-WIKI 列表验收测试`。
- `role` 字段使用中文角色，例如 `后端`、`前端`、`测试`。
- 用户指定 skill 时，`agent_type` 记录 skill，display_name 可使用 skill 名作为前缀，例如 `browser-WIKI 列表页面验证`；agent_run_id 与 member_id 仍按身份模型独立生成。
- 默认使用 `goal_*`；缺失时仅在 capability manifest 证明内置 `team_*` 能力等价、身份独立且权限不扩大后自动 fallback，否则串行降级、blocked 或询问用户；用户也可显式指定。英文昵称只进入 `transport_handle`。
- Member Goal Packet 首段必须写明中文展示名，并要求成员在回复首行声明 `成员：<中文展示名>`。
- 避免只有角色或过泛名字，例如 `后端`、`测试`、`接口联调`。
- 技术 subagent/skill 名称必须在 `agent_type`（兼容字段 `skill_or_subagent`）中保持原文。

优先使用 OKF Markdown 作为人类可读记录。用户没有指定生成目录时，默认输出根目录为 `GoalTeamsWork-<project_version>/`，SSOT 产出物写入版本子目录：

```text
GoalTeamsWork-<project_version>/
  index.md             # 当前输出目录索引，多文档前先建
  memory.md            # 用户设置、配置、组件库和上下文摘要时间线
  versions/
    <artifact_version>/
      index.md
      TaskList.md        # 成员认领、任务状态、验收、验证
      ledger/events.jsonl # append-only 事实源
      ledger/checkpoint.json
      identity/registry.json
      plan.md            # 澄清、回答、假设、确认计划
      progress.md        # 每轮进度、阻塞、下一步
      decisions.md       # 决策、原因、审批记录
      goal-packet.md     # 团队级目标包
      spec/
        requirement-card.md
        requirement-spec-card.md
        PRD.md
        page-spec-card.md
        frontend-architecture-design.md
        backend-architecture-design.md
        HTML-prototype.html
        test-plan.md
        acceptance.md
      tests/
        unit/
        api-integration/
        e2e/
        reports/
      harness/harness.json
      harness/traceability.json
      evidence/evidence.jsonl
      reviews/dual-review.json
      reviews/semantic-review.md
      audit/completion-audit.json
```

V2.3 JSON/JSONL 是机器闭包记录，重要结果同步写回 Markdown；V1.8 根级 `harness.yaml`、`evidence.jsonl`、`pipeline-state.json` 只在 legacy 协议明确适用时使用，不能替代上述路径。

## V1.92 脚本化工具链

V1.92 采用提示词 + 脚本混合模式。Goal Lead 用提示词处理目标理解、调度、冲突、预算和风险判断；脚本负责可重复、易漏、需要确定性的校验。

| 脚本 | 用途 |
| --- | --- |
| `scripts/install/install-local.sh`（兼容入口 `scripts/install-local.sh`） | 安装/更新本地 skill 与 subagents，可选更新 fallback team 昵称 |
| `scripts/checks/check-version-sync.py`（兼容入口 `scripts/check-version-sync.py`） | 检查 `VERSION`、启动语、README、runtime 和 `agents/openai.yaml` |
| `scripts/checks/check-agent-names.py`（兼容入口 `scripts/check-agent-names.py`） | 检查中文成员名、`transport_handle` 和 nickname candidates |
| `scripts/checks/check-member-layout.py`（兼容入口 `scripts/check-member-layout.py`） | 检查每个成员包包含 `prompt.md`、`template.md`、`workflow.md` 和 `scripts.md` |
| `scripts/harness/validate-harness.py`（兼容入口 `scripts/validate-harness.py`） | 校验 Harness contract；UI 必须 E2E，复刻必须 pixel diff |
| `scripts/harness/pixel-diff.py`（兼容入口 `scripts/pixel-diff.py`） | 计算截图 changed ratio、MAE 和 diff 图 |
| `scripts/review/compare-artifacts.py`（兼容入口 `scripts/compare-artifacts.py`） | 对文件或目录做 hash/size/path 对比，生成脚本复核证据 |
| `scripts/review/validate-dual-review.py`（兼容入口 `scripts/validate-dual-review.py`） | 校验脚本复核 + LLM 复核记录 |
| `scripts/benchmark/benchmark-runner.py`（兼容入口 `scripts/benchmark-runner.py`） | 检查 benchmark task package 并生成可选报告 |

这些脚本是本地确定性工具，不代表已有远端 CI/CD、生产 runner、真实审批系统或自动部署能力。

详情见 `references/goal-teams-scripted-tooling.md`、`references/ui-e2e-pixel-protocol.md`、`references/ui-visual-contract-protocol.md` 和 `references/subagent-dispatch-protocol.md`。

## V2.0 渐进式提示词目录

| 场景 | 文件 |
| --- | --- |
| Lead 核心和规划 | `RULES.md`、`references/invariants.md`、`references/compat.md`、`prompts/lead/core.md`、`prompts/lead/planning.md`、`prompts/packets/memory.md` |
| Plan 模式需求卡片 | `prompts/lead/requirement-card.md`、`prompts/packets/requirement-card.md`、`references/google-okf-bilingual-spec.md` |
| 派发和表格 | `prompts/lead/dispatch.md`、`prompts/packets/team-plan-table.md`、`prompts/packets/member-goal-packet.md` |
| 交接物 SSOT | `prompts/packets/handoff-artifacts.md`、`prompts/packets/member-goal-packet.md` |
| 页面规格卡和 UI 视觉防漏 | `references/rules-ui.md`、`prompts/packets/page-spec-card.md`、`prompts/packets/html-prototype-mock.md`、`references/ui-visual-contract-protocol.md`、`references/ui-e2e-pixel-protocol.md` |
| 成员通用规则 | `RULES.md`、`prompts/members/shared.md` |
| 需求/产品/后端/前端/QA/文档/评审/收尾 | `prompts/members/<role>/prompt.md`、按需读取同目录 `template.md`、`workflow.md`、`scripts.md` |
| Doc Capsule、SPEC 和 Harness Contract | `prompts/packets/doc-capsule.md`、`references/google-okf-bilingual-spec.md`、`prompts/packets/harness-contract.md` |
| 双重复核记录 | `prompts/packets/dual-review-record.md`、`references/dual-review-protocol.md` |

加载规则：先读 `SKILL.md`；再按任务场景读取最少数量的 `prompts/` 和 `references/` 文件。不要在普通任务中一次性加载所有角色提示词。

V2.0 成员包要求：每个成员目录必须包含 `prompt.md`、`template.md`、`workflow.md` 和 `scripts.md`。`prompt.md` 是角色稳定提示词，`template.md` 是输出模板，`workflow.md` 是成员执行流程，`scripts.md` 是该角色优先使用的确定性脚本和脚本边界。

V2.3 review 分级要求：comparison/safety 等需要机械事实与语义判断的任务必须同时产生脚本 Evidence 和独立 LLM reviewer Evidence；structural/semantic 只执行适用复核，并用经独立 reviewer 接受的结构化 N/A 说明不适用项。任一必需复核失败或缺失时不得 `pass`、`accepted` 或 `achieved`。

V1.95 需求卡片要求：Plan 模式收到需求后，Lead 先写版本子目录 `spec/requirement-card.md`，用简洁方案覆盖核心目标、关键功能、边界、约束和风险；需求卡片是后续 Requirement Specification Card、PRD、TaskList 和 Harness 的输入，不替代完整 SPEC。

V1.96 用户故事和功能验收标准要求：需求卡片、Requirement Specification Card 和 PRD 必须承接 `用户故事` 与 `功能验收标准`。用户故事使用“作为...我想要...以便...”表达角色、能力和价值；功能验收标准必须能被测试或人工检查验证，并流向 tasklist、Harness、test plan 和 acceptance。

V1.97 OKF 和输出目录要求：所有生成 Markdown 文档默认遵守 `references/google-okf-bilingual-spec.md`，至少包含 YAML frontmatter 和非空 `type`。用户没有指定生成目录时，所有输出默认进入 `GoalTeamsWork-<project_version>/`。输出目录根部必须创建或更新 `memory.md`，按时间线从老到新记录用户重要设置、配置、组件库、上下文摘要和决策，作者固定为 `GoalTeams`。

V2.3 ledger 和测试流要求：所有 SSOT 产出物必须写入 `versions/<artifact_version>/`；每个项目先建立 ledger，再由 reducer 生成 `TaskList.md`，`tasklist.md` 仅作为 V2.2 migration 输入；后端开发先生成 Backend Architecture Design，再由 `goal_unit_test_designer` 写 TDD 单测、`goal_backend` 实现、`goal_unit_test_runner` 执行单测，API 集成测试默认 Python + pytest 并由独立 subagents 生成/执行；前端开发完成后由 `goal_e2e_test_designer` 生成 E2E 用例，再由 `goal_e2e_test_runner` 执行。

V2.02 响应规范要求：`RULES.md` 定义执行期 Response Contract。Goal Lead 和所有成员必须执行优先、事实优先、未验证不宣称成功、区分观察和结论，并避免无关解释、建议、寒暄和推测。

SSOT 要求：交接物类型、具体 Owner/Validator、状态字段和 TaskList 投影格式以 `prompts/packets/handoff-artifacts.md` 为准。成员提交 event/patch；ledger owner 合并，reducer 生成 `TaskList.md`，记录 `task_state`、`check_state`、Harness、Evidence、attempt、revision 和阻塞/延期原因。

页面规格卡要求：UI 页面、复刻、还原、截图对齐或前端交互页面必须在 PRD 完成后先创建或更新 OKF `spec/page-spec-card.md`，再进入 HTML Prototype MOCK、静态页面开发或动态前端页面开发；非 UI 任务必须写 `not_applicable_reason`。页面规格卡使用 `prompts/packets/page-spec-card.md`，并承接组件库信息、视觉契约、交互状态矩阵、E2E Harness、整页和局部像素对比、Evidence 和双重复核。

HTML 原型 MOCK 要求：用户要求页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面时，若没有组件库名称、版本、URL 或 Git 仓库，必须先澄清；若提示词已有组件库信息，必须写入 `memory.md`、`spec/page-spec-card.md` 和 HTML OKF 元数据。HTML 原型必须按 `prompts/packets/html-prototype-mock.md` 使用注释、`application/okf+yaml` 或 `data-*` 属性记录组件库信息。

默认指南模板：

- 没有 `AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md` 时，使用 `references/default-AGENTS.md`。
- 对用户说明：“我没有看到项目指南文件，会先按默认 AGENTS 模板执行；也建议把它保存为项目根目录的 `AGENTS.md`。”
- 用户同意时，从 `references/default-AGENTS.md` 创建项目根目录 `AGENTS.md`。
- 生成的 `AGENTS.md` 内容保持中文。

输出目录规则：

- Goal Teams 产生的过程和结果文档都必须放进输出目录。用户未指定时，输出根目录固定为 `GoalTeamsWork-<project_version>/`。
- 所有 SSOT 产出物必须放进版本子目录 `versions/<artifact_version>/`，不同版本不得混放。
- 用户给 release 名而非语义版本时，转成文件系统安全目录名，例如 `V3.0`、`vNext`、`2026-Q2`。
- 输出目录外只保留用户明确要求的文件或必要机器状态。
- 多文档前先创建或更新根 `index.md` 和 `memory.md`，再创建版本子目录 `index.md` 与 ledger，由 reducer 生成 `TaskList.md`。

索引模板：

```md
# Goal Teams Index

| 文档 | 版本 | Owner | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `spec/requirement-card.md` | V3.0 | Goal Lead | planning | Plan 模式简洁方案 |
| `spec/requirement-spec-card.md` | V3.0 | 需求分析师 | planning | 人类友好的需求规格卡 |
```

## SPEC 契约

Goal Teams 是 SPEC 驱动。缺少 SPEC 时，应先由 ledger event 登记为任务，再由 reducer 投影到 TaskList，之后才进入实现。

固定术语：

- Plan 模式简洁方案 = `需求卡片`，路径为 `spec/requirement-card.md`。
- 人类友好的需求摘要 = `Requirement Specification Card`。
- 需求 = `PRD`。
- 页面规格 = `Page Specification Card` / `页面规格卡`，路径为 `spec/page-spec-card.md`；UI 页面任务在 PRD 后、HTML Prototype 前创建。
- 设计 = `Architecture Design`；只有 route `gates.architecture=required` 时开发前必须有对应 Backend/Frontend Architecture Design，其他等级使用影响分析或结构化不适用原因。
- UI/页面/工作流设计 = `HTML Prototype`。
- 开发执行 = ledger + reducer 生成的版本子目录 `TaskList.md`；`tasklist.md` 仅 legacy 输入。
- 测试 = Full/Regulated 使用独立 designer/runner；Lite/Standard 使用 route-required 测试并由非实现者独立复核。

仍可读取旧的非版本化文件：

```text
.codex/goal-teams/spec/
  PRD.md
  backend-architecture-design.md
  frontend-architecture-design.md
  HTML-prototype.html
  test-plan.md
  acceptance.md
.codex/goal-teams/tasklist.md
```

活跃项目使用版本化布局：

```text
GoalTeamsWork-<project_version>/
  index.md
  memory.md
  versions/<artifact_version>/
    index.md
    TaskList.md
    spec/
      requirement-card.md
      requirement-spec-card.md
      PRD.md
      page-spec-card.md
      frontend-architecture-design.md
      backend-architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
```

需求分析流程：

1. Goal Lead 先创建 `requirement-card.md`，覆盖核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险。
2. `goal_requirements_analyst` 读取需求卡片，用中文和用户交流，并提出聚焦问题。
3. 可在有用时使用网络搜索、computer use、browser 或 Chrome 获取市场、竞品、政策、流程或领域上下文。
4. 再创建 `requirement-spec-card.md`，控制在约两页内。
5. 规格卡必须覆盖核心目标、重要性、关键业务功能结构、用户故事、主流程、功能验收标准、边界、非目标和开放问题。
6. PRD 从已批准的规格卡生成，不从零散对话直接生成。

如果用户提供 `design.md`，它是架构/原型工作的风格来源：

- 创建或更新 Architecture Design / HTML Prototype 前先读 `design.md`。
- 尽量沿用其标题、术语、密度和产物风格。
- 如与用户目标冲突，先确认或记录阻塞。

SPEC 准备度表：

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |
| Ledger / TaskList | 是/否 | 每个项目先建立 ledger；TaskList 只由 reducer 生成 | ledger owner | `GoalTeamsWork-<project_version>/versions/<artifact_version>/ledger/events.jsonl` + `TaskList.md` |
| 需求卡片 | 是/否 | 创建/更新/跳过 | Goal Lead | `versions/<artifact_version>/spec/requirement-card.md` |
| Requirement Specification Card | 是/否 | 创建/更新/跳过 | goal_requirements_analyst | `versions/<artifact_version>/spec/requirement-spec-card.md` |
| PRD | 是/否 | 创建/更新/跳过 | goal_product | `versions/<artifact_version>/spec/PRD.md` |
| Page Specification Card | 是/否/不适用 | UI 页面任务创建/更新；非 UI 写原因 | goal_product 或 goal_frontend | `versions/<artifact_version>/spec/page-spec-card.md` |
| Backend Architecture Design | 是/否 | 后端开发前创建/更新 | goal_backend | `versions/<artifact_version>/spec/backend-architecture-design.md` |
| Frontend Architecture Design | 是/否/不适用 | 前端开发前创建/更新；非前端写原因 | goal_frontend | `versions/<artifact_version>/spec/frontend-architecture-design.md` |
| HTML Prototype MOCK | 是/否/不适用 | 创建/更新/跳过；必须记录 OKF 元数据和组件库信息 | goal_frontend | `versions/<artifact_version>/spec/HTML-prototype.html` |
| Test Plan | 是/否 | 创建/更新/跳过 | goal_qa | `versions/<artifact_version>/spec/test-plan.md` |
| Acceptance | 是/否 | 创建/更新/跳过 | goal_docs | `versions/<artifact_version>/spec/acceptance.md` |

独立校验表：

| 产物 | 作者成员 | 校验成员/Skill | 方法 | 证据 |
| --- | --- | --- | --- | --- |
| `spec/PRD.md` | 产品-WIKI 列表 PRD | 评审-WIKI 列表 PRD 校验 | 清单审查 | `progress.md` 行 |
| `src/api/order.ts` | 后端-订单接口 | 测试-接口行为测试 | 定向测试 + 代码审查 | 命令输出 |
| `tests/order.test.ts` | 测试-订单规则测试 | 评审-测试有效性校验 | 断言审查 | 评审记录 |
