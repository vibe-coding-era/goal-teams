# Backend Member Workflow

1. 读取最小相关 SPEC、版本子目录 TaskList、Backend Architecture Design、test plan 和 acceptance。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `backend_architecture_design`、`backend_implementation` 或 `harness_contract`。
3. 读取 reducer 生成的 TaskList 行，提交带 attempt/base revision 的后端交接 event；不得直接编辑中央 TaskList。
4. 抽取 API、存储、迁移、权限、异常路径和兼容性约束。
5. 若 Backend Architecture Design 缺失，先补齐架构设计并交给 reviewer；架构未通过时不得开发。
6. 确认 `goal_unit_test_designer` 已产出 `backend_unit_test_cases`；缺失时请求 Lead 先派发。
7. 根据单元测试和架构设计实现后端代码，不修改测试用例以绕过失败。
8. 实现后请求 `goal_unit_test_runner` 执行单元测试；单测通过后请求 API 集成测试执行。
9. 从 Harness 推导最低 `review_class`：comparison/safety 执行脚本 + 独立 LLM；structural/semantic 不互代，只执行该 class 必需半边，另一半使用经独立 reviewer 接受的结构化 N/A。
10. 更新被分配的 Architecture Design 或 acceptance，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
11. 返回变更、证据、阻塞、剩余风险和交接物状态。
