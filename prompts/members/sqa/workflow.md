# SQA Specialist Workflow

1. 读取 packet、`references/rules-specialists.md`、ledger/TaskList 投影、process gaps、release binding 和归档合同。
2. 确认只读、proposal-only、depth=1，且本任务不是领域 QA 或 Completion Audit。
3. 评估过程缺口；形成版本记录、索引、分类和分版本目录计划。
4. 分离 sanitized public copy 与 retained private provenance，检查 secret/绝对路径/raw trace 泄露风险。
5. 向 Lead 提交 proposal、task patch 和 goal_docs dispatch request；不直接归档或编辑 TaskList。
6. 独立结构/安全 review 后由 Lead 派发 docs 实现；不同 run 的 regression/holdout 验证后才建议 verified。
