# E2E Test Runner Workflow

1. 读取 TaskList、E2E 用例、page-spec-card、UI E2E 协议、frontend 实现证据和 Harness Contract。
2. 确认用例作者不是自己，且前置 `e2e_test_cases` 已 ready。
3. 启动本地应用或使用授权测试 URL。
4. 执行 E2E 命令，记录浏览器、viewport、baseURL、截图、trace、console 和 network 错误。
5. 不修改用例或生产代码；失败时记录 failure_report 并创建 BugFix 任务。
6. 更新被分配的 progress、reports 和 acceptance，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
7. 返回证据路径、失败归因、风险和后续建议。
