# Backend Member Workflow

1. 读取最小相关 SPEC、版本子目录 TaskList、Backend Architecture Design、test plan 和 acceptance。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `backend_architecture_design`、`backend_implementation` 或 `harness_contract`。
3. 在 TaskList 中更新后端交接物的 Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness 和证据路径。
4. 抽取 API、存储、迁移、权限、异常路径和兼容性约束。
5. 若 Backend Architecture Design 缺失，先补齐架构设计并交给 reviewer；架构未通过时不得开发。
6. 确认 `goal_unit_test_designer` 已产出 `backend_unit_test_cases`；缺失时请求 Lead 先派发。
7. 根据单元测试和架构设计实现后端代码，不修改测试用例以绕过失败。
8. 实现后请求 `goal_unit_test_runner` 执行单元测试；单测通过后请求 API 集成测试执行。
9. 用脚本生成结构化检查结果；再请求独立 LLM reviewer 复核。
10. 更新 TaskList、Architecture Design 或 acceptance。
11. 返回变更、证据、阻塞、剩余风险和交接物状态。
