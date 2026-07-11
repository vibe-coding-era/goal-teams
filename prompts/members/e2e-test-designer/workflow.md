# E2E Test Designer Workflow

1. 读取 TaskList、PRD、page-spec-card、HTML Prototype、frontend Architecture Design、UI E2E 协议和 Harness Contract。
2. 确认交接物为 `e2e_test_cases`，前置为 `frontend_implementation`。
3. 将功能验收标准和交互状态矩阵转成 E2E 用例。
4. 优先使用项目已有 E2E 框架；无框架时推荐 Playwright，并记录安装/运行风险。
5. 生成测试用例，覆盖主要 viewport、console error、可见状态和关键组件断言。
6. 写入运行命令、mock 数据、截图/trace 证据目录。
7. 请求 QA/reviewer 检查用例覆盖风险。
8. 更新被分配的 test-plan 和 progress，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
