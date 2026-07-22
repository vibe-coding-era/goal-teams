# Completion Auditor Template

Auditor 保持 read-only，返回一个可由 Lead 原样持久化的 JSON 对象。占位符替换后必须是合法 JSON；不得在 JSON 外夹带状态字段。

```json
{
  "schema_version": "goal-teams-v2.3",
  "audit_id": "<AUDIT-ID>",
  "auditor_run_id": "<independent auditor run>",
  "author_run_id": "<goal author/lead run>",
  "ledger_revision": 0,
  "audit_state": "failed",
  "run_outcome": "partial",
  "loop_decision": "replan",
  "stop_reason": null,
  "task_state_digest": "<64 lowercase hex>",
  "evidence_refs": ["<strict evidence id>"],
  "traceability_valid": false,
  "dual_review_valid": false,
  "required_task_ids": ["<required task id>"],
  "accepted_required_task_ids": [],
  "open_acceptance_blocking_task_ids": ["<open task id>"],
  "documented_nonblocking_tasks": [
    {
      "task_id": "<optional task id>",
      "task_state": "blocked",
      "reason": "<non-empty reason>"
    }
  ],
  "required_acceptance_criteria": ["<required AC id>"],
  "covered_acceptance_criteria": [],
  "review_ref": "versions/<artifact_version>/reviews/dual-review.json",
  "conclusion": "partial",
  "conclusion_detail": "<human-readable evidence-based explanation>",
  "open_gaps": [
    {
      "id": "<gap id>",
      "owner_run_id": "<next owner run>",
      "validator_run_id": "<independent validator run>",
      "required_evidence": "<missing evidence>"
    }
  ]
}
```

状态字段只能从 schema 枚举中选一个值；`conclusion` 必须等于 validator 重算出的 `run_outcome`，叙述放 `conclusion_detail`。`auditor_run_id` 不得等于 author、任何 Task Owner 或 Validator run。

Auditor 另可返回人类摘要，但它不替代 JSON：

```text
成员：<display_name>
审计范围：<artifact_version/ledger/TaskList/SPEC>
任务/交接物矩阵：<owner_run_id、validator_run_id、task_state、check_state、harness_refs、evidence_refs>
脚本与语义复核：<Harness task_type/required_review_class、derived minimum、domain execution、integrity replay、applicable halves、结果>
结论与续跑建议：<facts and gaps>
工程指标报告：<`metrics/engineering-metrics.md` 的 OKF valid/invalid、current run binding、manifest digest、12 metrics/algorithm completeness、status handling、report path>
用户查看提示：<最终回复仅包含可点击报告链接并提醒查看；未生成时列原因>
```

工程指标报告检查结果不新增 V2.3 Completion Audit schema 字段，避免破坏既有机器合同：报告缺失、OKF/manifest/current-run binding 无效或十二项算法不完整时，用 `open_gaps` 和 `conclusion_detail` 记录；单项数值为 `pending`、`unavailable`、`not_applicable` 或 `insufficient_sample` 本身不是 gap。Auditor 不得把工程指标报告或本次 Audit artifact 加入 `evidence_refs` 来支撑业务完成。

Lead/ledger owner 在候选收尾时持久化 JSON，并用 checkpoint、identity registry、Harness、Evidence JSONL、Traceability 和实际 Dual Review 文件运行 V2.3 `completion-audit`。failed/blocked 可驱动 LOOP/停止，只有 passed/achieved 要求 required task 全 accepted。本 Audit 是外部门禁，不能作为 required/blocking task 或 Audit Evidence 自证；命中 `E_AUDIT_SELF_REFERENCE` 或命令未通过时该记录不具有完成资格。

V2.35 字段必须由 Auditor 从 route、test-case reports、四专家 proposal/lifecycle、remote/local/post-release Evidence 与 required graph 重算；不得由作者预填 true。

V2.36 的仓库外受信宿主输出中，JSON 还必须增加：

```json
{
  "product_version": "V2.36",
  "v236_acceptance_binding": {
    "schema_version": "goal-teams-v2.36-acceptance-binding-v1",
    "product_version": "V2.36",
    "route_receipt_sha256": "<64 hex>",
    "route_digest": "<64 hex>",
    "actual_target_fingerprint": "<64 hex>",
    "actual_target_kind": "generic_project | goal_teams_repository",
    "release": false,
    "protected_snapshot_receipt_sha256": "<64 hex>",
    "snapshot_tree": "<Git tree oid>",
    "attested_identity_registry_sha256": "<64 hex>",
    "evidence_registry_sha256": "<64 hex>",
    "ledger_sha256": "<64 hex>",
    "checkpoint_sha256": "<64 hex>",
    "traceability_sha256": "<64 hex>",
    "tasklist_sha256": "<64 hex>",
    "acceptance_input_snapshot_sha256": "<64 hex>",
    "trusted_release_base": "<Git commit oid>",
    "policy_profile": "goal-teams-core-v2.5 | goal-teams-self-release-v2.36",
    "state_gate_profile": "<must equal policy_profile>",
    "execution_profile": "lite | standard | full | regulated",
    "required_review_class": "semantic | comparison | safety",
    "gates": {"<gate>": "required | conditional | not_required"},
    "gate_scopes": {"<conditional gate>": "<route-bound impact scope>"},
    "execution_contract_sha256": "<64 hex>"
  },
  "v236_gate_results": {
    "<ordinary gate>": {
      "state": "passed | not_required",
      "check_refs": ["<real passed Check>"],
      "evidence_refs": ["<current core-bound Evidence>"],
      "task_refs": ["<accepted Task>"],
      "impact_decision": "<conditional N/A only>",
      "impact_scope": "<must equal gate_scopes entry>",
      "reason": "<conditional N/A only>"
    },
    "completion_audit": {
      "state": "passed",
      "check_refs": [],
      "evidence_refs": [],
      "task_refs": [],
      "external_gate": true,
      "audit_state": "passed",
      "acceptance_binding_sha256": "<canonical binding hash>"
    }
  }
}
```

候选仓库的 Agent CLI 或 Python 调用无权自填宿主 context，也没有 V2.36 成功入口；仓库外 host adapter 未完成不可变输入快照与独立验收时，V2.36 Completion 必须返回 `E_V236_HOST_ADAPTER_REQUIRED`，不能用本模板制造 passed。
