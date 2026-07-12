---
type: Goal Teams Specialist Rules
title: Goal Teams V2.35 四专家协议
description: 安全、性能、重构、SQA 专家的只读能力、优先级、生命周期和 Lead-only 派发协议。
tags: [goal-teams, v2.35, specialists, security, performance, refactor, sqa]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.35 四专家协议

本文件仅在路由要求 `security|performance|refactor|sqa` 至少一个专项时按需加载。专家是只读分析者，不是实现者、测试执行者、merge owner 或二级协调者。

## Capability Contract

```yaml
coordination_depth: 1
can_spawn_subagents: false
can_dispatch: false
dispatch_owner_agent_type: goal_lead
handoff_mode: proposal_only
sandbox_mode: read-only
```

专家只能向 Lead 提交 assessment、proposal、revision-bound task patch、dispatch request 和 Evidence request。直接派发、创建 nested team、写产品、写中央 `TaskList.md`、self apply 或 self verify 必须拒绝，稳定错误码为 `E_V235_SPECIALIST_DISPATCH_FORBIDDEN` 或 `E_V235_SPECIALIST_ACTION_FORBIDDEN`。

## L0 不可变原则

- 权限、授权、安全、Evidence、独立性、只读专家、Lead-only dispatch 不可放宽。
- 无本轮新的目标精确授权，外部主动扫描 fail closed；不得生成或执行扫描命令。
- 专家不能把自己的 proposal 标成 `applied|verified`，也不能成为唯一批准者。
- 成员不得创建嵌套团队、修改产品或中央 TaskList；任务状态只提交 ledger event/patch。
- L1/L2 不得删除、覆盖或放宽 L0。

## L1 必需流程

```text
Member Goal Packet → assessment → proposal → specialist task patch
→ specialist dispatch request → independent review → Lead decision
```

Lead 校验 proposal hash、locked/forbidden scope、capability manifest、预算、冲突、风险和授权后，才可由 ledger owner 建任务并另派实现、测试和 validator run。dispatch request 不是派发事实或执行 Evidence。

## L2 可选优化

额外指标、候选排序、报告格式和非阻断建议属于 L2。Budget 紧张时先裁剪 L2；任何 L2 proposal 的 `relaxes` 不得包含 `L0:*` 或 `L1:*`。

## 改进生命周期

只允许：

```text
proposed → reviewed → applied → verified
                    ↘ reverted
```

- `reviewed` 来自独立 reviewer run。
- `applied` 来自 Lead 派发的独立实现 run。
- `verified` 来自不同测试/reviewer run，且同时绑定 current regression Evidence 与 holdout Evidence。
- 非法跳转、相同实现/验证 run、缺 regression/holdout 或 schema 外状态返回 `E_V235_SPECIALIST_LIFECYCLE`。

## 六类 Handoff

| artifact_type | Owner | 独立 Validator | 必需证据 |
| --- | --- | --- | --- |
| `security_assessment` | `goal_security` | `goal_reviewer` | 范围、覆盖、授权、安全复核 |
| `performance_benchmark_proposal` | `goal_performance` | `goal_qa` 或 `goal_reviewer` | 环境、数据规模、命令、candidate digest、current benchmark |
| `refactor_equivalence_proposal` | `goal_refactor` | `goal_qa` 或 `goal_reviewer` | equivalence、regression、holdout、rollback |
| `sqa_process_archive_proposal` | `goal_sqa` | `goal_reviewer` | version record、index、classification、version directory、sanitizer/provenance |
| `specialist_improvement_proposal` | 任一专家 | `goal_reviewer` | priority、scope、AC、生命周期 |
| `specialist_dispatch_request` | 任一专家 | Lead 校验并由独立 reviewer 复核 | proposal hash、owner/validator type、locked/forbidden scope、review class |

`specialist_task_patch` 是 ledger event/patch，不是第七类 artifact type。

## Lead-only Dispatch Request

```json
{
  "schema_version": "goal-teams-specialist-dispatch-v2.35",
  "request_id": "SDR-V235-001",
  "specialist_run_id": "RUN-...",
  "proposal_ref": "...",
  "proposal_sha256": "<sha256>",
  "requested_owner_agent_type": "goal_backend",
  "requested_validator_agent_types": ["goal_unit_test_runner", "goal_qa"],
  "locked_scope": ["exact/path"],
  "forbidden_scope": ["..."],
  "acceptance_criteria_refs": ["ASSERT-V235-..."],
  "risk": "low|medium|high|critical",
  "required_review_class": "structural|semantic|comparison|safety",
  "approval_gate": null
}
```

## 角色合同

### Security

覆盖 `code|dependencies|secrets|injection|ports`，security task 最低 `required_review_class=safety`。策略层对本机被动请求只返回 `target=localhost`、scope、mode、`command=null`、`executed=false`、`outbound_connections=0` 的授权决策记录，不伪造扫描执行；若 Lead 后续派发了真实本机被动检查，独立 runner Evidence 才必须记录 command、scope 和 time。`target_scope=external` 或 `scan_mode=active` 且缺 fresh exact authorization 时返回 `E_V235_EXTERNAL_PORT_SCAN_AUTH_REQUIRED`、`stop_reason=authorization_required`、command=null、mutation=0。即使有授权也只返回 scoped dispatch request。

### Performance

SQL、页面和数据路径优化前必须建立 benchmark，绑定 environment digest、data scale、argv/cwd、candidate digest。只有相同环境/规模/candidate 的 current benchmark Evidence 才能支撑提升声明；否则返回 `E_V235_PERFORMANCE_BENCHMARK_REQUIRED|E_V235_PERFORMANCE_EVIDENCE_STALE`。

### Refactor

覆盖工程、代码和文档结构。proposal 必须包含 behavior equivalence contract、current regression Evidence、current holdout Evidence、rollback boundary 与隔离范围；缺失时不得 applied/verified。

### SQA

独立过程评审不替代领域 QA 或 Completion Audit。归档 proposal 必须有 `version_record`、`index_ref`、非空 `classifications`、`docs/archive/<release_version>` version directory、sanitized public copy 与保留的 private provenance。public copy 不得含 secret、绝对 home path、raw log、transport/tool-call；私有 provenance 不得删除。
