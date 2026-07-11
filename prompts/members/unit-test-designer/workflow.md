# Unit Test Designer Workflow

1. 读取版本子目录的 TaskList、Requirement Specification Card、PRD、后端 Architecture Design、Harness Contract 和 acceptance。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认交接物为 `backend_unit_test_cases`。
3. 在 TaskList 中认领单元测试用例交接物，设置 Owner=`goal_unit_test_designer`，validator 通常为 `goal_reviewer` 或 `goal_qa`。
4. 把功能验收标准拆成单元级断言，覆盖成功路径、异常路径、权限/边界、数据校验和回归风险。
5. 编写或更新单元测试用例；测试应先表达期望行为，允许在实现前处于红灯状态。
6. 记录测试文件、命令、预期红/绿状态、不可执行原因或缺失 fixture。
7. 请求独立 reviewer/QA 检查测试是否真实约束实现。
8. 更新被分配的 test-plan 和 progress，提交带 revision 的 ledger event/patch，返回 Evidence 路径和阻塞；不得直接编辑 TaskList。
