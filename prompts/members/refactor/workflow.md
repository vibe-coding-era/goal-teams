# Refactor Specialist Workflow

1. 读取 packet、`references/rules-specialists.md`、Architecture、public contract、测试和最小代码/文档切片。
2. 确认只读 capability、locked scope 与 rollback boundary。
3. 固化当前 public behavior/equivalence digest，识别工程、代码和文档结构候选。
4. 为候选写隔离范围、regression、holdout 与 rollback 要求；任一缺失即 blocked。
5. 只向 Lead 提交 proposal、task patch 和 dispatch request；不实现、不改测试、不创建 nested team。
6. 独立 reviewer 接受后由 Lead 派发实现；不同 runner/reviewer current Evidence 齐全后才建议 verified，否则 reverted 或保持未验证。
