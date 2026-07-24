# E2E Test Designer Scripts

- 优先使用项目已有 E2E 命令；无约定时可建议 Playwright。
- 用例必须避免只检查整页截图；关键组件要有选择器、局部截图或几何断言。
- 可引用 `references/ui-e2e-pixel-protocol.md` 和 `references/ui-visual-contract-protocol.md`。
- 如涉及截图对比，执行证据阶段可交给 `scripts/harness/pixel-diff.py` 或项目 E2E runner 辅助校验。
- 不修改前端实现代码；缺少启动方式时记录 blocked。
- 使用 Goal Packet/Harness 指定的 V2.44 validator 检查 E2E plan/case typed fields、四段合同和 DOM/URL/可见/业务状态断言；不得用旧入口绕过新字段。
- 用安全的仓库相对路径计算测试文件 sha256，并运行框架 list/collect 命令证明真实 discovery；path、hash、test ID 一并交接。
- 不默认启用自动 retry；retry/trace/video/screenshot/cleanup 策略必须在计划中明确。
