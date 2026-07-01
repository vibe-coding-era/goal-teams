# Docs Member Scripts

优先脚本：

- `scripts/checks/check-version-sync.py`：版本和启动语同步。
- `scripts/checks/validate.py`：结构、关键词、README 发布清单。
- `scripts/checks/check-member-layout.py`：成员包目录完整性。
- `scripts/review/compare-artifacts.py`：文档或示例产物对比。

规则：

- 文档一致性先脚本检查，再 LLM 复核语义是否丢规则。
