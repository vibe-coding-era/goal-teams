# E2E Test Designer Scripts

- 优先使用项目已有 E2E 命令；无约定时可建议 Playwright。
- 用例必须避免只检查整页截图；关键组件要有选择器、局部截图或几何断言。
- 可引用 `references/ui-e2e-pixel-protocol.md` 和 `references/ui-visual-contract-protocol.md`。
- 如涉及截图对比，执行证据阶段可交给 `scripts/harness/pixel-diff.py` 或项目 E2E runner 辅助校验。
- 不修改前端实现代码；缺少启动方式时记录 blocked。
- V2.35 用 `scripts/checks/validate-test-case-contract.py` 检查 E2E 四段合同和 DOM/URL/可见状态业务断言。
