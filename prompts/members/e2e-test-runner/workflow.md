# E2E Test Runner Workflow

1. 按 `context_refs` / `fetch_recipe` 读取 TaskList、E2E plan/case、page-spec-card、适用 UI 规则、实现证据、Harness、`references/rules-testing.md` 和 `references/test-case-assertion-protocol.md`。
2. 确认 route 前置门 ready，runner 与用例作者/implementation owner identity 独立。
3. 运行 Harness 指定 validator；重算测试文件 sha256 并执行真实 discovery。合同无效、hash 漂移、零发现或发现集不匹配即 failed。
4. 记录 source commit/tree、browser/runtime/依赖/config 指纹和 seed；启动本地应用或使用授权测试 URL。
5. 先执行 cleanup preflight，再以 exact argv/cwd 运行；逐 action 收集 checkpoint，记录 DOM/URL/visible/business state、assertions、console/network、截图/trace/video。
6. 只有计划预授权且为诊断需要时 retry；保留首次失败和所有 attempts。任何 `fail→pass` 输出 `flaky`。
7. 无论通过、失败或中断都执行 cleanup，验证测试数据、session 与 UI/business state 复位；cleanup failed 关闭通过门。
8. 生成 schema-valid `test-run-result` 和 replay recipe，绑定所有 artifact 相对 path/hash；运行 Harness 指定结果 validator。
9. 不修改用例或生产代码；failed/flaky 时记录 failure_report 并创建 BugFix，无法执行为 blocked，不能把 unavailable 写成 pass。
10. 更新被分配的 progress、reports 和 acceptance，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
11. 返回证据路径、失败归因、风险和后续建议。
