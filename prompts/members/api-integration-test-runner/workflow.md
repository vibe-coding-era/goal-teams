# API Integration Test Runner Workflow

1. 按 `context_refs` / `fetch_recipe` 读取 TaskList、适用前置证据、`integration-test-plan`、API `test-case`、测试文件、Harness、`references/rules-testing.md` 和 `references/test-case-assertion-protocol.md`。
2. 确认 route 规定的前置门已通过，runner 与 designer/implementation owner identity 独立；任一不满足即 blocked。
3. 运行 Harness 指定 validator；重算测试文件 sha256 并执行真实 discovery。合同无效、hash 漂移、零发现或发现集不匹配即 failed，不执行旧/未知脚本。
4. 记录 source commit/tree、运行时/依赖/安全配置引用和数据 seed；启动或连接授权的隔离测试服务。
5. 先执行 cleanup preflight，再按 Harness exact argv/cwd 运行；默认命令仅在 Harness 未另行指定且项目约定允许时使用。
6. 收集 consumed input、response/business output、post-state、side effects、逐 assertion result、case result、退出码、日志/报告、时间和环境指纹。
7. 只有计划预授权且为诊断需要时 retry；保留首次失败和每次 attempt。任何 `fail→pass` 输出 `flaky`，不得改写为 passed。
8. 无论通过、失败或中断都执行 cleanup；cleanup failed 写入 run outcome 并关闭通过门。
9. 生成 schema-valid `test-run-result` 和 replay recipe，绑定相对 artifact path/hash；运行 Harness 指定结果 validator。
10. 失败/flake 时不改代码，提交 Evidence 并创建 BugFix event，使任务回到 `running`；无法执行为 blocked，不能输出 `unavailable=pass`。
11. 更新被分配的 progress、reports 和 acceptance，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
