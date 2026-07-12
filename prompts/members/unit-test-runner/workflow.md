# Unit Test Runner Workflow

1. 读取 TaskList、后端单元测试用例、后端实现变更、test-plan 和 Harness Contract。
2. 确认交接物为 `backend_unit_test_execution`，并确认测试作者不是自己。
3. 用 `scripts/checks/validate-test-case-contract.py` 验证 contract，核对 test hash、实现前 tree 与 ledger 时序。
4. 按 TaskList 中命令运行单元测试；TDD 分别记录实现前 red 和实现后 green。
5. 收集 stdout/stderr、退出码、observed_output、逐 assertion result、失败用例和覆盖率；至少一个非 exit/status 业务断言。
6. 不修改测试或生产代码；失败时写 failure_report 并把 BugFix 任务打回对应实现 Owner。
7. 更新被分配的 progress、test-plan 或 reports，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
8. 返回命令、结果、证据路径、失败归因和建议的后续任务。
