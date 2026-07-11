# Product Member Scripts

优先脚本：

- `scripts/harness/validate-harness.py`：文档 Harness 字段。
- `scripts/review/compare-artifacts.py`：规格卡与 PRD 结构对比。
- `scripts/review/validate-dual-review.py`：双重复核记录。

规则：

- 从 Harness 推导最低 review_class；comparison/safety 强制脚本 + LLM，semantic/structural 不互代并按 class matrix 执行，对不适用半边记录独立接受的结构化 N/A。
