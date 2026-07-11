# Requirements Analyst Scripts

优先脚本：

- `scripts/harness/validate-harness.py`：轻量 Harness 结构。
- `scripts/review/compare-artifacts.py`：规格卡版本或模板对比。
- `scripts/review/validate-dual-review.py`：双重复核记录。

规则：

- 从 Harness 推导最低 review_class。comparison/safety 同时执行脚本和独立 LLM；semantic/structural 不互代，只要求 class matrix 的必需半边，另一半不得伪写 passed。
