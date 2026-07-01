# Goal Teams Automation Protocol

## 定位

本文定义 V1.8 的机器可读研发协议模板，用于把 Goal Teams 的 `Harness`、`Evidence`、`Pipeline` 状态写成可解析、可审计、可交接的数据合同。

这些内容是协议和模板，不代表仓库已经存在 runner、CI/CD 接入、生产流水线、发布系统或真实外部审批系统。任何工具、命令、CI job、发布动作或生产接入，只有在目标项目中已经存在并被授权时才能引用。

## 协议产物

| 文件或对象 | 作用 | 建议位置 | 写入时机 |
| --- | --- | --- | --- |
| `index.md` | OKF 输出目录索引 | `GoalTeamsWork-<project_version>/index.md` | 多文档前创建，新增产物后更新 |
| `memory.md` | 用户重要设置、配置、组件库和上下文摘要时间线 | `GoalTeamsWork-<project_version>/memory.md` | 输出目录创建时创建，重要设置变化时追加 |
| `TaskList.md` | 版本内任务和交接物账本 | `GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md` | 每个项目先创建，派发前写入最小任务颗粒度 |
| `harness.yaml` | 单任务或单版本的验证契约 | `GoalTeamsWork-<project_version>/versions/<artifact_version>/harness.yaml` 或任务目录 | Plan 阶段创建，执行中更新 |
| `evidence.jsonl` | 追加式证据日志 | `GoalTeamsWork-<project_version>/versions/<artifact_version>/evidence.jsonl` | 每次检查、人工确认、阻塞、失败后追加 |
| `pipeline-state.json` | 当前研发流水线快照 | `GoalTeamsWork-<project_version>/versions/<artifact_version>/pipeline-state.json` | Lead 整合、门禁变化、收尾审计后更新 |
| `failure_report` | 失败记录对象 | 嵌入 `evidence.jsonl` 或 `pipeline-state.json` | 检查失败、门禁拒绝、审计阻塞时写入 |
| `approval_gate` | 人工或策略审批门对象 | 嵌入 `pipeline-state.json` | 涉及风险、外部动作、发布或安全边界时写入 |

## 通用字段规则

- `schema_version` 固定使用语义化协议名，例如 `goal-teams.automation.v1`。
- `version` 使用项目版本名，例如 `V1.8`。
- `task_id` 使用 tasklist 中的任务 ID，例如 `GT-018-001`。
- `artifact_version` 使用版本子目录名；所有 SSOT 产出物必须写入 `versions/<artifact_version>/`。
- `status` 使用小写枚举，避免自由文本。
- 时间字段使用 ISO 8601，例如 `2026-06-14T09:30:00+08:00`。
- 路径字段使用仓库相对路径，除非记录外部 URL。
- `evidence_ref` 指向 `evidence.jsonl` 的 `record_id`。
- Markdown 产物默认使用 Google OKF，至少包含 YAML frontmatter 和非空 `type`；`memory.md` 的 `author` 固定为 `GoalTeams`，时间线从老到新。
- 中文说明可以放在 `summary`、`reason`、`notes`、`human_review` 等字段中。

推荐状态枚举：

```yaml
task_status:
  - planned
  - claimed
  - running
  - blocked
  - failed
  - done
  - deferred
check_status:
  - planned
  - skipped
  - running
  - passed
  - failed
  - blocked
gate_decision:
  - pending
  - approved
  - blocked
  - rejected
  - waived
pipeline_status:
  - planning
  - ready
  - running
  - blocked
  - failed
  - passed
  - completed
```

## `harness.yaml` 示例 schema

`harness.yaml` 描述“如何证明任务完成”。它可以引用已有命令、人工检查、文档结构检查、截图、日志或外部评估结果，但不能宣称会运行尚不存在的 runner 或 CI。

```yaml
schema_version: goal-teams.automation.v1
artifact: harness.yaml
kind: HarnessContract
version: V1.8
artifact_version: V1.8
run_id: local-docs-v1-8-001
task_id: GT-018-001
owner: 文档-V1.8 机器可读研发协议
status: ready
purpose: 定义 V1.8 文档任务如何证明机器可读协议已完成
scope:
  allowed:
    - references/goal-teams-automation-protocol.md
    - GoalTeamsWork-V1.8/versions/V1.8/
  forbidden:
    - SKILL.md
    - README.md
    - README.en.md
    - references/goal-teams-runtime.md
    - scripts/validate.py
checks:
  - check_id: protocol-fields
    type: static_document
    description: 协议文档包含 harness.yaml、evidence.jsonl、pipeline-state.json、failure_report、approval_gate 示例 schema
    expected_status: passed
  - check_id: no-runner-claim
    type: wording_review
    description: 文档明确说明协议和模板不代表已有 runner、CI/CD 或生产接入
    expected_status: passed
commands:
  - command_id: repository-check
    command: ./scripts/check.sh
    required: false
    reason: 本成员不修改 validate.py；该命令用于确认当前仓库结构未被破坏
artifact_checks:
  - path: references/goal-teams-automation-protocol.md
    must_contain:
      - harness.yaml
      - evidence.jsonl
      - pipeline-state.json
      - failure_report
      - approval_gate
  - path: GoalTeamsWork-V1.8/versions/V1.8/spec/
    must_exist:
      - requirement-spec-card.md
      - PRD.md
      - backend-architecture-design.md
      - test-plan.md
      - acceptance.md
  - path: GoalTeamsWork-V1.8/versions/V1.8/TaskList.md
    must_contain:
      - backend_unit_test_cases
      - backend_unit_test_execution
      - api_integration_test_script
      - api_integration_test_execution
      - e2e_test_cases
      - e2e_test_execution
manual_checks:
  - check_id: protocol-boundary-review
    reviewer_role: 评审-V1.8 协议一致性
    checklist:
      - schema key 保持英文且可解析
      - 中文说明未承诺不存在的自动化能力
      - failure_report 和 approval_gate 可被 evidence/pipeline 引用
evidence:
  evidence_file: GoalTeamsWork-V1.8/versions/V1.8/evidence.jsonl
  required_record_types:
    - artifact_check
    - command_result
    - manual_review
failure_report:
  required: true
  schema_ref: "#failure_report"
approval_gate:
  required_when:
    - 涉及发布、生产、凭证、外部审批或破坏性动作
  schema_ref: "#approval_gate"
not_applicable_reason: null
tdd_checks:
  unit_test_cases_owner: goal_unit_test_designer
  unit_test_execution_owner: goal_unit_test_runner
api_integration_checks:
  script_owner: goal_api_integration_test_designer
  execution_owner: goal_api_integration_test_runner
  default_language: Python
  default_framework: pytest
e2e_checks:
  case_owner: goal_e2e_test_designer
  execution_owner: goal_e2e_test_runner
```

## `evidence.jsonl` 示例 schema

`evidence.jsonl` 是追加式记录，每一行都是一个独立 JSON 对象。不要把大段日志直接塞入字段；应记录摘要、状态和可追溯路径。

字段模板：

```json
{
  "schema_version": "goal-teams.automation.v1",
  "artifact": "evidence.jsonl",
  "record_id": "ev-018-001",
  "record_type": "artifact_check",
  "version": "V1.8",
  "run_id": "local-docs-v1-8-001",
  "task_id": "GT-018-001",
  "owner": "文档-V1.8 机器可读研发协议",
  "status": "passed",
  "summary": "协议文档包含五类机器可读 schema 示例",
  "command": null,
  "artifact_paths": [
    "references/goal-teams-automation-protocol.md"
  ],
  "evidence_refs": [],
  "failure_report": null,
  "created_at": "2026-06-14T09:30:00+08:00"
}
```

示例 JSONL：

```jsonl
{"schema_version":"goal-teams.automation.v1","artifact":"evidence.jsonl","record_id":"ev-018-001","record_type":"artifact_check","version":"V1.8","run_id":"local-docs-v1-8-001","task_id":"GT-018-001","owner":"文档-V1.8 机器可读研发协议","status":"passed","summary":"reference 文档包含 harness.yaml、evidence.jsonl、pipeline-state.json、failure_report、approval_gate 示例 schema","command":null,"artifact_paths":["references/goal-teams-automation-protocol.md"],"evidence_refs":[],"failure_report":null,"created_at":"2026-06-14T09:30:00+08:00"}
{"schema_version":"goal-teams.automation.v1","artifact":"evidence.jsonl","record_id":"ev-018-002","record_type":"command_result","version":"V1.8","run_id":"local-docs-v1-8-001","task_id":"GT-018-001","owner":"文档-V1.8 机器可读研发协议","status":"passed","summary":"仓库校验命令通过，且校验脚本覆盖新增 V1.8 reference 和关键 schema 字段","command":"./scripts/check.sh","artifact_paths":["scripts/check.sh","scripts/validate.py"],"evidence_refs":["ev-018-001"],"failure_report":null,"created_at":"2026-06-14T09:35:00+08:00"}
```

`record_type` 推荐枚举：

```yaml
record_type:
  - doc_capsule
  - artifact_check
  - command_result
  - manual_review
  - approval_decision
  - failure
  - completion_audit
```

## `pipeline-state.json` 示例 schema

`pipeline-state.json` 是当前状态快照，用来给 Lead、成员、QA 或审计者快速判断任务是否可继续、是否被门禁阻塞、是否有未解决失败。

```json
{
  "schema_version": "goal-teams.automation.v1",
  "artifact": "pipeline-state.json",
  "version": "V1.8",
  "run_id": "local-docs-v1-8-001",
  "status": "running",
  "generated_at": "2026-06-14T09:40:00+08:00",
  "pipeline": {
    "mode": "documentation_protocol",
    "stages": [
      {
        "stage_id": "spec",
        "name": "SPEC",
        "status": "passed",
        "owner": "文档-V1.8 机器可读研发协议",
        "evidence_refs": ["ev-018-001"]
      },
      {
        "stage_id": "validation",
        "name": "Validation",
        "status": "passed",
        "owner": "测试-V1.8 协议校验",
        "evidence_refs": ["ev-018-002"]
      }
    ]
  },
  "tasks": [
    {
      "task_id": "GT-018-001",
      "owner": "文档-V1.8 机器可读研发协议",
      "status": "done",
      "locked_scope": [
        "references/goal-teams-automation-protocol.md",
        "GoalTeamsWork-V1.8/"
      ],
      "harness_ref": "GoalTeamsWork-V1.8/spec/test-plan.md#harness-contract",
      "evidence_refs": ["ev-018-001", "ev-018-002"],
      "failure_report_ids": []
    }
  ],
  "approval_gates": [
    {
      "gate_id": "gate-018-production-claim",
      "gate_type": "production_or_ci_claim",
      "decision": "pending",
      "required_approvers": ["Goal Lead"],
      "approvers": [],
      "reason": "协议模板后续若要宣称 runner、CI/CD 或生产接入，必须先有真实实现和授权证据",
      "blocked_actions": [
        "claim_runner_exists",
        "claim_ci_cd_integrated",
        "claim_production_connected"
      ],
      "evidence_refs": [],
      "manual_only": true,
      "expires_at": null
    }
  ],
  "open_failures": [],
  "next_actions": [
    {
      "owner": "评审-V1.8 协议一致性",
      "action": "在后续真实 runner 或 CI/CD 接入前，确认本协议仍只作为数据合同使用",
      "blocked_by": null
    }
  ]
}
```

## `failure_report` 示例 schema

`failure_report` 是失败对象，可以嵌入 `evidence.jsonl` 的失败记录，也可以由 `pipeline-state.json` 汇总引用。

```json
{
  "failure_id": "fail-018-001",
  "related_task_id": "GT-018-001",
  "severity": "medium",
  "status": "open",
  "command": "./scripts/check.sh",
  "failing_check": "harness.yaml 语法或必需字段检查失败",
  "observed": "artifact_checks 缺少 evidence.jsonl 或 approval_gate 引用",
  "expected": "harness.yaml 能被解析，且必须字段覆盖 Harness、Evidence、Pipeline、failure_report 和 approval_gate",
  "likely_cause": "协议样例或成员输出未同步新增字段",
  "impacted_artifacts": [
    "scripts/validate.py",
    "references/goal-teams-automation-protocol.md"
  ],
  "next_verification": "补齐字段后重跑 ./scripts/check.sh，并解析相关 YAML/JSON/JSONL 样例",
  "owner": "测试-V1.8 协议校验",
  "evidence_refs": ["ev-018-002"],
  "created_at": "2026-06-14T09:45:00+08:00",
  "resolved_at": null
}
```

推荐枚举：

```yaml
severity:
  - low
  - medium
  - high
  - critical
failure_status:
  - open
  - triaged
  - fixed
  - accepted_risk
  - deferred
```

## `approval_gate` 示例 schema

`approval_gate` 用于显式记录人工审批或策略门禁。普通文档协议不需要外部审批；一旦涉及发布、生产、凭证、破坏性操作、外部系统或安全敏感行为，必须写入门禁对象。

```json
{
  "gate_id": "gate-018-production-claim",
  "gate_type": "production_or_ci_claim",
  "decision": "pending",
  "required_approvers": [
    "Goal Lead",
    "repository owner"
  ],
  "approvers": [],
  "reason": "V1.8 只定义协议和模板；如后续声明真实 runner、CI/CD 或生产接入，需要实现证据和授权",
  "blocked_actions": [
    "run_unapproved_ci_job",
    "publish_release",
    "access_production",
    "write_credentials",
    "claim_runner_exists"
  ],
  "evidence_refs": [],
  "manual_only": true,
  "expires_at": null,
  "notes": "未审批前只能保留为文档模板，不得升级为生产承诺"
}
```

## Done 判定规则

任务只有同时满足以下条件，才能在 `pipeline-state.json` 中标记为 `done`：

- `harness.yaml` 或等价 Harness Contract 已定义检查、证据路径、失败报告或不适用原因。
- `evidence.jsonl` 至少有一条可追溯证据记录，或明确记录跳过原因。
- 必需产物存在，且 `artifact_checks` 通过。
- 没有未解决的 `critical` / `high` `failure_report`。
- 涉及审批的 `approval_gate` 已 `approved` 或明确 `waived`，并记录原因。
- 文档没有宣称不存在的 runner、CI/CD、生产接入或外部审批能力。

## 与现有 Goal Teams 文件的关系

- Markdown 仍是面向人的主记录，JSON/YAML/JSONL 是机器状态和证据层。
- `TaskList.md`/`tasklist.md` 记录 Owner、状态、Locked Scope 和完成标准；V2.0 起必须先创建版本子目录 TaskList，并拆到需求规格卡、PRD、页面规格卡、HTML 原型、前端开发、前后端架构设计、后端 TDD、后端开发、后端执行 TDD、API 集成测试脚本生成、API 集成测试、API 集成测试执行、E2E 用例生成、E2E 执行、BugFix、测试报告生成。
- `progress.md` 记录执行摘要和关键证据。
- `spec/test-plan.md` 记录本版本如何校验协议。
- `spec/acceptance.md` 记录人工验收和剩余风险。
- 后续如要把本协议写入 `references/goal-teams-runtime.md`、`default-AGENTS.md`、`README` 或 `scripts/validate.py`，应由 Lead 在同步范围中安排，不能由本文直接暗示已经完成。
