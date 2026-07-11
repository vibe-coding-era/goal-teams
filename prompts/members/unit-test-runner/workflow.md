# Unit Test Runner Workflow

1. 读取 TaskList、后端单元测试用例、后端实现变更、test-plan 和 Harness Contract。
2. 确认交接物为 `backend_unit_test_execution`，并确认测试作者不是自己。
3. 按 TaskList 中命令运行单元测试；如 TDD 要求，分别记录实现前 red 和实现后 green。
4. 收集 stdout/stderr、退出码、失败用例、覆盖率或不可执行原因。
5. 不修改测试或生产代码；失败时写 failure_report 并把 BugFix 任务打回对应实现 Owner。
6. 更新被分配的 progress、test-plan 或 reports，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
7. 返回命令、结果、证据路径、失败归因和建议的后续任务。
