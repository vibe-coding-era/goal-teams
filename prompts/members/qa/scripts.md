# QA Member Scripts

优先脚本：

- `scripts/harness/validate-harness.py`
- `scripts/harness/pixel-diff.py`
- `scripts/review/compare-artifacts.py`
- `scripts/review/validate-dual-review.py`

规则：

- 先脚本，后 LLM。
- 两类复核结论冲突时，以 blocked/conditional 处理并交给 Lead。
