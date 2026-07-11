# QA Member Scripts

优先脚本：

- `scripts/harness/validate-harness.py`
- `scripts/harness/pixel-diff.py`
- `scripts/review/compare-artifacts.py`
- `scripts/review/validate-dual-review.py`

规则：

- 从 Harness 推导最低 review_class；comparison/safety 先脚本后独立 LLM，semantic/structural 不互代并按 class matrix 执行。
- required half 结论冲突时使用 failed/blocked 并交给 Lead；不输出 schema 外 `conditional` 状态。
