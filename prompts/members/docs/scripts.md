# Docs Member Scripts

优先脚本：

- `scripts/checks/check-version-sync.py`：版本和启动语同步。
- `scripts/checks/validate.py`：结构、关键词、README 发布清单。
- `scripts/checks/check-member-layout.py`：成员包目录完整性。
- `scripts/review/compare-artifacts.py`：文档或示例产物对比。

规则：

- 从 Harness 推导最低 review_class；comparison 使用脚本 + 独立 LLM，纯 semantic 可将脚本半边以独立接受的结构化 N/A 记录，纯 structural 反向处理，二者不可互代。
