# Completion Auditor Scripts

优先脚本：

- `scripts/review/validate-dual-review.py`：检查双重复核记录。
- `scripts/harness/validate-harness.py`：抽查 Harness 结构。
- `scripts/benchmark/benchmark-runner.py --check-only`：Benchmark 任务包检查。
- `scripts/v23/goalteams_v23.py completion-audit <audit.json> <checkpoint.json> --evidence-jsonl <evidence.jsonl> --evidence-root <output-root> --traceability <traceability.json> --review <dual-review.json> --identity-registry <identity/registry.json> --harness <harness/harness.json> --ledger <ledger/events.jsonl> --tasklist <TaskList.md>`：候选收尾时由 Lead 持久化 Auditor 返回的外部门禁 JSON，再重放 ledger、投影和闭包；failed/blocked 可驱动 LOOP/停止，只有 passed/achieved 要求 required task 全 accepted；实际 audit 路径不得被 required/blocking task 或 Audit Evidence 引用。

审计口径：

- 适用的 review_class 缺少脚本复核或 LLM 复核时不能输出 `audit_state=passed`。
- `harness_contract.task_type` / `required_review_class` 缺失、review 自降级、domain/integrity 层缺失/互换/同日志或 binding 不一致时不能通过。
- 脚本无法覆盖语义正确性；LLM reviewer 不能替代脚本指标。
- Auditor 保持 read-only，只返回完整 JSON；不得为了运行命令自行创建审计文件。
