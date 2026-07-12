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
```

Lead/ledger owner 在候选收尾时持久化 JSON，并用 checkpoint、identity registry、Harness、Evidence JSONL、Traceability 和实际 Dual Review 文件运行 V2.3 `completion-audit`。failed/blocked 可驱动 LOOP/停止，只有 passed/achieved 要求 required task 全 accepted。本 Audit 是外部门禁，不能作为 required/blocking task 或 Audit Evidence 自证；命中 `E_AUDIT_SELF_REFERENCE` 或命令未通过时该记录不具有完成资格。

V2.35 字段必须由 Auditor 从 route、test-case reports、四专家 proposal/lifecycle、remote/local/post-release Evidence 与 required graph 重算；不得由作者预填 true。
