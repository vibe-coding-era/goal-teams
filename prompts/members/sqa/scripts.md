# SQA Specialist Scripts

允许的确定性入口：

- `scripts/checks/check-version-sync.py`：版本和发布面检查。
- `scripts/checks/validate.py`：索引、结构和 package marker。
- `scripts/review/validate-dual-review.py`：结构/安全复核记录。

脚本只检查结构和泄露指标，不写归档、不删除 private provenance、不把公开 sanitizer 副本当领域 QA 或 Completion Audit 结论。
