# Completion Auditor Scripts

优先脚本：

- `scripts/review/validate-dual-review.py`：检查双重复核记录。
- `scripts/harness/validate-harness.py`：抽查 Harness 结构。
- `scripts/benchmark/benchmark-runner.py --check-only`：Benchmark 任务包检查。

审计口径：

- 缺少脚本复核或 LLM 复核时不能 complete。
- 脚本无法覆盖语义正确性；LLM reviewer 不能替代脚本指标。
