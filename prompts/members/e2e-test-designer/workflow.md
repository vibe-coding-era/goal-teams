# E2E Test Designer Workflow

1. 按 `context_refs` / `fetch_recipe` 读取 TaskList、SPEC/PRD、page-spec-card、原型、适用 Architecture/UI 规则、会话/权限/状态合同、Harness、`references/rules-testing.md` 和 `references/test-case-assertion-protocol.md`；Rust/Tauri/desktop route 追加 desktop engineering protocol/contract；缺引用不得猜测。
2. 确认交接物为 E2E plan section、E2E `test-case` 和测试脚本，route 规定的前置 artifact/status 已满足。
3. 把 acceptance、persona/permission、关键 journey、状态/失败恢复、viewport/browser 与视觉合同转成稳定风险分母；blocked/not_run/unavailable 保留为 uncovered。
3a. 核对 verification contract 与 impact assessment，分别列出 unaffected/affected/new/undetermined；受影响项 `retest_required`，新增项 `not_run`，无依赖路径不得清零旧结果。
4. 为每案写 persona、session、initial URL、pre-state/seed、browser/viewport、ordered actions、step checkpoints、final DOM/URL/visible/business state、side effects 和 cleanup。
5. 显式设计适用的 session refresh、permission denied、validation、double-click、loading/disabled、network/service failure、retry/recovery、refresh/back/multi-tab 场景，或逐项写 N/A reason。
5a. 桌面 route 按每个 required tuple 设计真实 IPC/WebView、窗口/原生能力和 production package case，声明 L1-L4 与允许 driver；required 缺 runner 仍保留 blocked/uncovered。
6. 按 `references/test-case-assertion-protocol.md` 写 input/browser processing/expected output/assertions；截图/trace 只作辅助证据。
7. 优先使用项目已有 E2E 框架与稳定选择器；无框架时可推荐 Playwright，并记录安装/运行风险。
8. 验证每个 `test_file_ref` 存在且在 locked scope，记录 sha256；运行真实 discovery，绑定 test ID。零发现或 hash 漂移均 failed。
9. 运行 Harness 指定 plan/case validator，写入运行命令、mock/seed、隔离/cleanup、截图/trace 目录和不可执行原因。
10. 请求独立 QA/reviewer 以风险分母检查 journey、会话、恢复、可发现性和断言。
11. 更新被分配的 test-plan 和 progress，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
