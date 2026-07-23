# API Integration Test Designer Workflow

1. 按 Member Goal Packet 的 `context_refs` / `fetch_recipe` 读取 TaskList、SPEC/PRD、适用 Architecture、API/认证/状态合同、Harness、acceptance、`references/rules-testing.md` 和 `references/test-case-assertion-protocol.md`；缺少引用不得靠猜测补齐。
2. 确认交接物为 `api_integration_test_script`、机器可读 `integration-test-plan` 和 API `test-case`。
3. 提交 revision-bound ledger event/patch，Owner=`goal_api_integration_test_designer`，validator 通常为 `goal_qa` 或 `goal_reviewer`；不得直接编辑 TaskList。
4. 从 acceptance、API operation、persona/permission、状态机、依赖与 failure mode 建立带稳定 `risk_id` 的分母，标记 applicable/covered/uncovered；blocked/not_run/unavailable 保留为未覆盖。
5. 设计 API 矩阵：method/path、persona/auth、headers/path/query/body、pre-state、处理、status/response、post-state、side effects、数据准备与 cleanup；高风险面显式覆盖幂等、retry、并发、补偿和最终一致性或写逐项 N/A。
6. 按 `references/test-case-assertion-protocol.md` 把输入、处理、输出和业务断言写成 contract；状态码必须配合 response business value、post-state 或 side-effect observable。
7. 默认生成 Python + pytest 测试脚本；若需要 HTTP client，可优先使用项目已有依赖，新增依赖必须写明风险。
8. 验证每个 `test_file_ref` 存在且在 locked scope，记录 sha256；运行真实 discovery，绑定发现的 node/case ID，零发现或引用漂移均 failed。
9. 运行 Goal Packet/Harness 指定的 plan/case validator，记录命令、环境、mock/fixture、隔离/cleanup 和不可执行原因。
10. 请求独立 QA/reviewer 以风险分母检查覆盖、可发现性与合同语义。
11. 更新被分配的 test-plan 和 progress，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
