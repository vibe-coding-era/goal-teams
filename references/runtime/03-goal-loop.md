---
type: Goal Teams Runtime Reference Part
title: 目标循环细节（Goal Loop）
description: Goal Teams runtime 渐进式分片。
tags: [goal-teams, runtime, progressive-loading]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# 目标循环细节（Goal Loop）

## 目标循环细节（Goal Loop）

Goal Loop 分三层：成员 Loop、Lead Loop、Skill Improvement Loop。普通执行默认只跑成员 Loop 和 Lead Loop；只有用户明确要求改进 skill、构建 benchmark 或进行复盘时，才进入 Skill Improvement Loop。

### 成员 Loop

### Load（加载）

1. 读取用户目标和约束。
2. 检查项目指南：`AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md`。
3. 读取或创建输出目录 `index.md` 和 `memory.md`。
4. 读取或创建输出目录 SPEC。
5. 读取版本目录 ledger 与 reducer 生成的 TaskList；成员缺少任务行时报告 Lead，不自行创建或编辑投影。
6. 读取当前成员认领任务行。
7. 只按需读取项目文档。
8. 读取当前任务的 Harness Contract；如果缺失，报告缺口，不编造验证方式。
9. 如任务属于 Benchmark，读取对应 task package 的 `task.md` 或 `SPEC.md`、metadata（如有）和 Harness 说明。
10. 产出 Doc Capsules。

### Plan（计划）

优先返回精简执行步骤；复杂目标可展开，但每步都要带验证方式：

```text
Plan（计划）:
1. 环境/版本/索引 -> 验证：输出目录、index.md 和 memory.md 已准备
2. 需求规格卡 -> 验证：用户确认目标/功能/流程/边界
3. PRD 任务 -> 验证：验收标准已确认
4. Architecture Design 任务 -> 验证：设计评审通过
5. HTML Prototype 或界面级任务 -> 验证：必须有 E2E；复刻任务必须有截图像素级对比
6. Harness 契约 -> 验证：检查、命令、证据路径或不适用原因已写明
7. 实现 tasklist 任务 -> 验证：定向测试通过
8. 独立 QA 任务 -> 验证：命令/报告可追溯
9. 文档/ledger event 任务 -> 验证：具体 identity、revision、状态和 Evidence 已登记，TaskList 已由 reducer 重建
```

### Implement（实现）

按 tasklist 顺序和依赖执行。工程任务常见顺序：

1. 环境指南检查和输出目录。
2. 输出目录 `index.md` 和 `memory.md`。
3. Requirement Specification Card。
4. 基于已确认规格卡生成 PRD。
5. Architecture Design。
6. 适用时生成 HTML Prototype。
7. tasklist 实现任务。
8. 独立 QA/testing 任务。
9. Harness 证据、失败报告或不适用原因。
10. 文档、acceptance 和 tasklist 状态更新。

跳过层级时必须说明原因。

### Test（测试）

测试必须由独立 subagent 或用户指定 testing skill/subagent 执行。先做最小有效验证；共享行为变化时再扩大范围。

测试阶段优先执行 Member Goal Packet 中的 Harness Contract。命令未知或不可运行时，成员必须记录原因、风险和下一步验证建议，不能把缺失 Harness 当成通过。

失败报告：

```text
测试失败：
- command:
- failing test:
- likely cause:
- fix plan:
- next verification:
```

### Document（记录）

每个成员都要说明是否更新：

- tasklist 状态
- owner/claimed_by 字段
- packet 中分配的 docs
- packet 中分配的 SPEC
- Harness 证据、失败报告或不适用原因
- Benchmark 运行记录或失败分类（如适用）
- 新增或变更文档的输出目录 `index.md`
- 用户重要设置、组件库或上下文变化已写入 `memory.md`
- 报告或 acceptance 备注
- 生成 docs/code/tests 的独立校验证据
- 剩余缺口

### Review（评审）

```text
Review Checklist（评审清单）:
- 认领任务完成:
- 完成标准:
- Harness 契约:
- Harness 证据:
- Benchmark 记录（如适用）:
- 测试:
- 生成 docs/code/tests 是否独立校验:
- docs/tasklist:
- SPEC:
- locked_scope 是否遵守:
- 阻塞:
- 剩余风险:
```

持续循环，直到完成或阻塞。

### Lead LOOP

Goal Lead 的循环是 `Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`。V2.3 起 `loop_decision` 与 `run_outcome` 正交，详细协议以 `prompts/lead/loop.md` 为准：

1. `Plan`：把用户目标转为 Done Criteria、SPEC、tasklist、Harness 契约、Benchmark 适用性和风险表。
2. `Dispatch`：按 `Teams 规划表` 分发 Member Goal Packet，保证每个实现成员有 `locked_scope` 和 Harness Contract。
3. `Route`：处理成员阻塞、跨成员依赖、共享范围冲突、高风险审批和用户决策。
4. `Integrate`：汇总成员输出，验证并合并 events，更新 Markdown、team-state、messages、doc-capsules、Evidence index，再由 reducer 重建 TaskList 投影。
5. `Audit`：每轮做轻量 integration audit；最终完成前启动只读 `goal_completion_auditor`，检查完成标准、Harness 证据、独立校验和剩余风险。
6. `Continue`：输出 `Loop Decision`；已确认范围内遗漏自动续跑；新范围、高风险、凭证、外部审批、预算超限或未解决决策才问用户。

Lead Loop 不替代成员 Loop：Lead 负责协调和证据闭环，不直接把未验证产物标记为完成。

Loop Decision 模板：

```text
Loop Decision:
- loop_id:
- round:
- loop_decision: continue | replan | stop
- run_outcome: achieved | partial | blocked | aborted
- basis:
- confirmed_scope:
- open_gaps:
- evidence_refs:
- next_owner:
- next_validator:
- user_confirmation_required: true | false
- stop_reason:
```

Loop Decision 处理：

| decision | Lead 动作 |
| --- | --- |
| `continue` | 展示续跑 Teams 规划表并继续，不再次要求确认。 |
| `replan` | 写入修订事件，更新依赖、Owner、Harness、Budget Gate 和 Conflict Policy，再由 reducer 重建 TaskList。 |
| `stop` | 另写 `run_outcome` 与 `stop_reason`；只有完成谓词和审计通过才可 `achieved`。 |

长任务或自动续跑必须记录 Loop Gate：

```yaml
loop_gate:
  max_loop_rounds:
  max_auto_continue_rounds:
  max_subagents:
  time_budget:
  token_budget:
  cost_budget:
  confirmed_scope:
  block_completion_when_evidence_missing: true
  stop_when_new_scope: true
  stop_when_safety_gate: true
  stop_when_user_decision_required: true
  stop_when_budget_exceeded: true
```

`block_completion_when_evidence_missing` 表示缺证时不能输出 `audit_state=passed` 或 `run_outcome=achieved`；若缺口仍在已确认范围内，且未触发预算、安全、审批或用户决策边界，Lead 使用 `loop_decision=continue|replan` 补证。状态快照可写入 `progress.md`；需要机器可读恢复时可额外写 `loop-state.json`。该文件只保存状态，不代表实际执行引擎。

### Skill Improvement Loop

Skill Improvement Loop 是发布维护层，状态流是 `Run/Eval -> Classify -> Update Rules/Templates -> Validate -> Release Notes`：

1. `Run/Eval`：收集真实 Goal Teams 运行、Benchmark 报告、收尾审计和用户反馈。
2. `Classify`：按失败分类归因，例如需求误解、上下文没读全、定位失败、工具失败、环境失败、实现错误、测试不足、过度修改、引入回归、证据缺失、权限/安全违规、长任务漂移、多 agent 协调失败。
3. `Update Rules/Templates`：按用户授权更新 `goal-teams.md`、`SKILL.md`、`references/goal-teams-runtime.md`、subagents、默认 AGENTS、README/CHANGELOG、examples 或校验脚本。
4. `Validate`：运行 `./scripts/check.sh`，必要时补充示例复盘或 benchmark smoke run。
5. `Release Notes`：记录版本阶段，例如 `V1.5` Harness 与三层 Loop 规则、`V1.6` 最小 Harness 示例、`V1.7` Benchmark 模板、`V1.8` 机器可读协议、`V1.9` 生产流门禁、`V1.91` 中文成员显示名和界面验证强化、`V1.92` 脚本化工具链和证据不足打回、`V1.93` 渐进式提示词目录和脚本分目录、`V1.94` 成员包和 LLM + 脚本双重复核、`V1.95` Plan 模式需求卡片、`V1.96` 用户故事和功能验收标准、`V1.97` Google OKF、默认输出目录、memory.md、页面规格卡/HTML 原型组件库记录、`V2.0` 版本子目录 SSOT、TaskList 先行、后端架构先行、TDD/API/E2E 独立测试 subagents、`V2.02` 响应规范 `RULES.md`、`V2.1` Lead LOOP、Loop Decision、Loop Gate、状态快照和 `GT-BENCH-004`。

普通用户任务不会自动进入 Skill Improvement Loop；只有用户明确要求改 skill、发布版本、构建 benchmark 或进行复盘时才进入。

## 收尾审计与自动续跑

每次看似完成后，Goal Lead 必须先做最终审计，再发送最终回复。

审计从 `harness_contract.task_type`、`required_review_class` 与风险重算最低 review class；外层同名字段或 review 自报不能降级。Evidence/脚本 Review 均须区分真实领域执行与唯一可重放的 `integrity_replay`，并核对两层独立日志、时间及 binding。

使用新的只读 `goal_completion_auditor`，packet 如下：

```text
Completion Audit Packet（收尾审计包）:
- agent_type: goal_completion_auditor
- agent_run_id: <唯一审计运行 ID>
- member_id: <稳定审计成员 ID>
- display_name: 收尾-WIKI 列表未完成工作检查
- transport_handle: <宿主返回值或 null>
- version:
- confirmed_goal:
- confirmed_scope:
- ledger_path:
- tasklist_path:
- progress_path:
- acceptance_path:
- spec_paths:
- test_evidence:
- validation_evidence:
- audit_scope:
  - 任务状态
  - 完成标准
  - docs/SPEC 更新
  - Harness 契约和证据
  - Benchmark 运行记录和失败分类（如适用）
  - 独立校验证据
  - 测试和验收证据
  - 未解决阻塞
  - 剩余风险
- output_contract:
  - audit_state: passed | failed | blocked
  - run_outcome: achieved | partial | blocked | aborted
  - recommended_loop_decision: continue | replan | stop
  - stop_reason
  - 未完成项
  - 证据
  - 缺失 Harness 或 Benchmark 记录
  - 建议续跑任务
  - 建议成员/subagents
  - locked_scope
  - 停止条件
```

审计结论处理：

| 审计输出 | Lead 动作 |
| --- | --- |
| `audit_state=passed` | 校验完成谓词后记录 `loop_decision=stop`、`run_outcome=achieved`。 |
| `audit_state=failed` | 将 open gaps 写为 ledger events，记录 `loop_decision=continue|replan`、`run_outcome=partial`，展示续跑 Teams 规划表并继续。 |
| `audit_state=blocked` | 记录 `loop_decision=stop`、`run_outcome=blocked` 与 stop_reason；需要用户/授权时提出最小问题。 |

自动续跑只允许处理已确认目标范围内的未完成工作。不要自动进入新范围、破坏性写入、安全敏感工作、缺少凭证、外部审批或未解决用户决策。

每次自动续跑：

1. 追加 `completion_audit_started`、`completion_audit_finished`、`auto_continuation_started` 等事件。
2. 用续跑任务 ID 和具体 Owner identity 写入 ledger event，重建 TaskList，并更新 progress。
3. 写入 `Loop Decision`，只能是 `continue`、`replan` 或 `stop`，并另写合法 `run_outcome`。
4. 更新 `progress.md`；需要机器可读恢复时同步 `loop-state.json`。
5. 展示四列续跑 `Teams 规划表`。
6. 在范围不冲突时并发启动所需成员。
7. 照常执行独立测试和独立校验。
8. 续跑完成后再次执行 integration audit；看似完成时再次执行收尾审计。

## V2.35 结构化路由、测试合同与版本绑定

V2.35 持久化执行先建立 `goal-teams-project-route-v2.35` JSON；`project_size` 与 `work_type` 正交，字段完整性、类型、risk/security/UI precedence 由 runtime fail closed。示例：

```bash
python3 scripts/v23/goalteams_v23.py route route.json
```

只有 route 命中专项时才读取 `references/rules-specialists.md` 和对应单一成员包；四专家只提交 proposal/dispatch request，Lead 是唯一派发者。测试设计、执行和评审读取 `references/test-case-assertion-protocol.md`：

```bash
python3 scripts/checks/validate-test-case-contract.py test-case.json
python3 scripts/v23/goalteams_v23.py validate-test-case test-case.json
```

七类用例都必须比较 input、processing、expected_output 与 assertions；命令退出码不能替代业务断言。TDD red 绑定实现前 tree/test hash/ledger prefix，implementation 后由不同 runner 产出 green 与逐 assertion results。

无 version binding 时，V2.34 state/archive 默认语义保持。显式 V2.35 descriptor 必须绑定 current delta contract 和独立 review：

```json
{
  "schema_version": "goal-teams-version-binding-v1",
  "project_version": "V2.35",
  "release_version": "V2.35",
  "artifact_version": "V2.35-run2",
  "contract_ref": "GoalTeamsWork-V2.35/versions/V2.35-run2/spec/v2.35-contract.md",
  "contract_sha256": "<sha256>",
  "contract_revision": 2,
  "review_ref": "<independent review>",
  "review_sha256": "<sha256>",
  "review_state": "passed"
}
```

runtime 不接受 caller 提供的 `archive_path`，只从已校验 `release_version` 推导 `docs/archive/V2.35/<delivery_id>/`。binding/hash/path 错误必须 0 mutation，不得静默回退 V2.34。

V2.35 发布顺序是 release readiness → branch/main fast-forward push → local install → independent post-release task accepted → graph-external Completion Audit；Audit 不进入 required task 或 public package。

## 命令行桥接（CLI Bridge）

dashboard 不直接执行 shell 命令；需要时用本地 bridge。

Lead 执行模式：

```bash
PROJECT="/path/to/project"
VERSION="V3.0"

codex exec \
  -C "$PROJECT" \
  --sandbox workspace-write \
  --ask-for-approval never \
  --json \
  --output-last-message ".codex/goal-teams/last-message.md" \
  - <<'PROMPT' | tee -a ".codex/goal-teams/events.jsonl"
Use $goal-teams.

先汇报：我是 Goal Teams Lead V2.40。
用户沟通与治理记录全程中文，Goal Lead 消息要简洁、人类友好；代码、注释、产品字符串、测试名和 fixture 遵循目标仓库约定。
分离 agent_type、agent_run_id、member_id、display_name 和 transport_handle；display_name 使用 <中文角色>-<具体任务名>。V2.36 新验收身份必须绑定宿主 attestation，不能只凭不同 agent_run_id 自报独立。真实 subagent/skill 配置名写入 agent_type（兼容字段 skill_or_subagent）；宿主英文昵称只记录为 transport_handle。
启动 worker subagents 或编辑实现文件前，展示四列 Teams 规划表；除非有直接执行词，否则等待确认。
检查 AGENTS.md / agent.md / CLAUDE.md / claude.md。缺失时使用 references/default-AGENTS.md，并建议复制为项目根目录 AGENTS.md。
使用版本 "$VERSION"，输出根目录写入 GoalTeamsWork-$VERSION/，SSOT 产出物写入 GoalTeamsWork-$VERSION/versions/$VERSION/。
所有生成 Markdown 文档默认采用 Google OKF，至少包含 YAML frontmatter 和非空 type。
多文档前先创建或更新 GoalTeamsWork-$VERSION/index.md 和 GoalTeamsWork-$VERSION/memory.md；再建立 GoalTeamsWork-$VERSION/versions/$VERSION/ledger/events.jsonl，由 reducer 生成 TaskList.md。memory.md 按时间线从老到新记录用户重要设置、配置、组件库和上下文摘要，作者为 GoalTeams。
把用户目标转成 Done Criteria。
先写 GoalTeamsWork-$VERSION/versions/$VERSION/spec/requirement-card.md，用需求卡片覆盖核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险。
把 SPEC 定义为“什么算完成”，把 Harness 定义为验证契约/模板字段，不宣称新增 runtime 执行能力。
每个任务在 Plan、tasklist 或 Member Goal Packet 中写清 Harness Contract：内层必填 `task_type`、`required_review_class`，以及 checks、commands、artifact_checks、e2e_checks、pixel_diff_checks、evidence_paths、failure_report 或 not_applicable_reason；review 不能用外层字段降级。
任何界面级任务都必须做 E2E 测试；复刻任务必须截图做像素级对比，记录基准图、实际图、diff 图或差异指标、阈值、viewport 和结论。
长任务、会话内续跑、生产流、Benchmark、浏览器 E2E 或像素对比任务必须记录 Budget Gate 和 Conflict Policy；证据不足不能完成，必须进入 failure_report、单一 `check_state`（已执行失败为 `failed`，无法执行为 `blocked`）和合法的 run/loop 状态。
脚本化校验优先使用 scripts/check.sh、scripts/harness/validate-harness.py、scripts/harness/pixel-diff.py、scripts/review/compare-artifacts.py、scripts/review/validate-dual-review.py 和 scripts/benchmark/benchmark-runner.py；兼容入口 scripts/validate-harness.py、scripts/pixel-diff.py、scripts/compare-artifacts.py、scripts/validate-dual-review.py 和 scripts/benchmark-runner.py 仍可用。这些脚本不代表已有真实 CI/CD 或生产 runner。
V2.3 completion 使用版本目录内的 ledger/checkpoint、identity/registry.json、harness/harness.json、harness/traceability.json、evidence/evidence.jsonl、reviews/dual-review.json 和 audit/completion-audit.json；V1.8 根级 harness.yaml/evidence.jsonl/pipeline-state.json 仅是 legacy/可选协议，不代表 completion 或真实 runner。
面向生产流或发布门禁时，按 references/goal-teams-production-pipeline.md 组织 Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback；凭证、真实部署、破坏性操作和生产回滚必须人工审批或外部授权。
Benchmark 是外层评估目录与任务集，默认不创建；只有用户要求或计划确认时才创建/更新 benchmarks/，并记录任务集、运行记录、评分协议和失败分类。
V2.40 继续按 V2.38-compatible prompt-cache manifest 编译 route-static order，但当前 self-release refs 指向 V2.40 Profile，V2.39/V2.38 只读 replay；再追加动态目标包。`route_static_digest` 不冒充最终 prompt 或 provider key。只有宿主最终 ordered manifest 才生成 runtime digest。observer telemetry 只在轮后分析，不得倒灌为当轮 Budget Gate 事实；无授权 live probe 必须保持 `not_authorized`。
三层 Loop：成员 Loop 是 Load -> Plan -> Implement -> Test -> Document -> Review -> Continue；Lead LOOP 是 Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue；Skill Improvement Loop 只在用户要求改 skill、benchmark 或复盘时启用。
V2.3 Lead LOOP 必须读取 prompts/lead/loop.md：每轮 Integrate 后记录 `loop_decision=continue|replan|stop`，并独立记录 `run_outcome=achieved|partial|blocked|aborted` 与 stop_reason。长任务记录 Loop Gate、round、open gaps、Owner、Validator、Evidence 和停止边界。Lead LOOP 不是后台执行器、CI/CD 或生产审批系统。
先安排需求分析成员；可在有用时使用 web search、computer use、browser 或 Chrome 改善需求质量。
先创建需求卡片，作为 Requirement Specification Card、PRD、ledger/TaskList 和 Harness 的输入。
需求卡片必须包含用户故事和功能验收标准，功能验收标准必须能被后续测试或人工检查验证。
先创建人类友好的 Requirement Specification Card，控制在两页以内，覆盖核心目标、关键业务功能结构、用户故事、流程、功能验收标准和边界。
从已确认的 Requirement Specification Card 生成 PRD。
UI 页面、复刻、还原、截图对齐或前端交互页面必须在 PRD 后创建 spec/page-spec-card.md，再进入 HTML Prototype MOCK、静态页面开发或动态前端页面开发；非 UI 任务记录 not_applicable_reason。
页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面任务必须先确认组件库名称、版本、URL 或 Git 仓库；若提示词已提供组件库信息，写入 memory.md、page-spec-card.md 和 HTML OKF 元数据。
页面规格卡头部必须记录组件库名称和版本；每个元素都记录组件库名；有数据模型的组件记录数据模型或 mock 引用。HTML 原型用注释、application/okf+yaml 或 data-* 属性记录组件库信息。
UI 视觉防漏必须读取 references/ui-visual-contract-protocol.md：不能只依赖整页 pixel diff；使用 baseline overlay、视觉锁层或截图遮挡层时必须提供 locked screenshot 和 unlocked real DOM screenshot；关键组件必须有组件级视觉契约和可执行断言；小组件必须有局部 crop 或几何断言；弹窗必须覆盖打开态、错误态、切换态、关闭态和移动端态；Reviewer 和 Completion Auditor 必须检查证据是否覆盖视觉风险。
发现已有 ledger/TaskList；没有则建立版本 ledger 并由 reducer 生成 TaskList。
Full/Regulated 的每个适用功能切片按最小颗粒度写入 ledger events：需求规格卡、PRD、页面规格卡、HTML 原型、前端开发、前后端架构设计、后端 TDD、后端开发、后端执行 TDD、API 集成测试脚本生成/执行、E2E 用例生成/执行、BugFix、测试报告；Lite/Standard 只登记适用任务。
后端开发必须先生成 Backend Architecture Design；随后由 goal_unit_test_designer 写单元测试、goal_backend 写实现、goal_unit_test_runner 执行单测。API 集成测试脚本由 goal_api_integration_test_designer 生成，默认 Python + pytest；单测通过后由 goal_api_integration_test_runner 执行。
前端开发完成后由 goal_e2e_test_designer 生成 E2E 用例，再由 goal_e2e_test_runner 独立执行。
交接物类型、具体 Owner/Validator identity、状态字段和 ledger 事件以 prompts/packets/handoff-artifacts.md 为 SSOT；成员提交带 revision 的 event/patch，reducer 生成 TaskList，记录 task_state、check_state、Harness、Evidence 和阻塞/延期原因。
发现或创建 SPEC：Requirement Specification Card、PRD、Backend Architecture Design、Frontend Architecture Design、适用时的 HTML Prototype、test plan、acceptance。
提出独立 subagent 成员，包含认领任务、用户指定 skill/subagent、locked_scope、Harness Contract、docs/SPEC 更新、独立测试 Owner 和完成标准。
每个生成文档、代码变更和测试用例都要安排独立校验者，可用单独 subagent 或用户指定校验 skill。
每个交接物都要安排具体独立 Validator；缺少 `check_state=passed`、当前 Evidence 或阻塞/延期原因时，不得标记 accepted。
启动实现成员前展示 SPEC 准备度、Harness 准备度、Benchmark 适用性、四列 Teams 规划表、tasklist 执行、独立校验计划和风险表。若提示词含直接执行词，展示为执行记录后直接继续。
确认后，每个成员作为独立 subagent 运行。
通过 team-state.json、events.jsonl、messages.jsonl、doc-capsules.jsonl 协调。
持续运行，直到每个认领任务完成、延期或阻塞且原因明确。
看似完成后，启动 goal_completion_auditor 检查未完成工作。若发现已确认范围内仍有未完成工作，创建续跑任务并并发重启 Goal Teams 成员，不再要求用户确认。只有新范围、高风险/破坏性工作、凭证、外部审批、预算超限或未解决决策才问用户。每次续跑前后更新 progress.md 或 loop-state.json。
PROMPT
```

只规划模式：

```bash
codex exec \
  -C "$PROJECT" \
  --sandbox read-only \
  --json \
  'Use $goal-teams. 全程中文。只做 Goal Lead：检查环境，询问版本号，提出澄清问题，生成确认表格。不要编辑文件。'
```

## 安全与协作

- 没有 locked_scope 不启动实现。
- 不让多个成员同时编辑共享核心文件。
- 不跳过 Plan 模式。直接执行词只跳过确认等待，不跳过 Plan 表格。
- Plan 模式尽量用数字选项。
- 不自我批准生成产物。
- 生成 docs、code 或 test cases 没有独立校验，不标记 accepted。
- 多文档前先创建相关 `index.md` 和 `memory.md`。
- 过程/结果 Markdown 不写到输出目录之外，除非用户明确指定其他目录。
- PRD 前不跳过需求规格卡，除非用户明确选择 OpenSpec/Superpower lead-only 模式或确认例外。
- 用户指定 OpenSpec 或 Superpower 时，默认只做 Goal Lead，不经确认不启动角色 subagents。
- 不跳过 SPEC；缺少 Requirement Specification Card、PRD、Architecture Design、适用时的 HTML Prototype、test plan、acceptance、tasklist 时，创建或加入任务。
- 不跳过 Harness；每个任务必须有验证契约、证据路径或不适用说明。
- 不跳过交接物 SSOT；每个交接物必须在 ledger/TaskList 中有具体 Owner/Validator member/run identity、task_state、check_state、Harness 和当前 Evidence。
- 不默认创建 Benchmark；只有用户要求或计划确认时，才创建或更新 `benchmarks/`。
- 实现成员不能是唯一测试者；必须安排独立 QA/testing skill/subagent。
- 尊重用户指定的成员 skill/subagent。
- auth、payment、refund、migrations、破坏性写入、安全敏感集成或广泛 API 变化需要 Lead 审批。
- `max_depth = 1`；成员不创建嵌套团队。
- 并发成员通常控制在 3-6 个，除非用户明确要求更多。
- 新的 `goal_completion_auditor` 审计前，不发送最终完成回复。
- 已确认范围内的未完成工作自动续跑，不再要求用户确认；但要展示续跑计划。
- 审计暴露新范围、破坏性或安全敏感工作、缺少凭证、外部审批或未解决决策时，必须问用户。

## 完成回复

最终回复保持简洁：

```text
完成：<一句话说明>

版本与文档：
| 版本 | 索引 | 主要文档 |
| --- | --- | --- |

成员状态：
| 成员 | 认领任务 | Workflow / 前置任务 | 状态 | 证据 | 资源消耗（用户 / tokens / 费用） | 剩余 |
| --- | --- | --- | --- | --- | --- | --- |

SPEC：
| SPEC | 状态 | Owner | 证据 |
| --- | --- | --- | --- |

Harness / Benchmark：
| 项目 | 状态 | 证据 | 剩余 |
| --- | --- | --- | --- |

独立校验：
| 产物 | 作者 | 校验者 | 状态 | 证据 |
| --- | --- | --- | --- | --- |

验证：
- <命令>：通过
- <命令>：未运行，原因...

文档与 tasklist：
- <文件>：已更新

剩余风险：
- <如无，写“无已知阻塞。”>
```
