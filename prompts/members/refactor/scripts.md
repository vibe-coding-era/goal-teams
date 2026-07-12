# Refactor Specialist Scripts

允许的确定性入口：

- `scripts/review/compare-artifacts.py`：比较 public contract/golden output。
- `scripts/review/validate-dual-review.py`：comparison review 结构。
- `scripts/checks/validate.py`：Skill/文档结构检查。

脚本不能替代语义等价性 review。不得自动改写工程、代码或文档，不得用格式化成功替代 regression/holdout，也不得执行破坏性 rollback。
