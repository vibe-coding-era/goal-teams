# Test Plan

## 测试范围

| 范围 | 方法 | 证据 |
| --- | --- | --- |
| AC-001 空状态文案 | 静态检查 HTML 是否包含标题和说明 | `HTML-prototype.html` |
| AC-002 主操作 | 检查按钮文案为“登录” | `HTML-prototype.html` |
| AC-003 次操作 | 检查创建账号和联系支持链接 | `HTML-prototype.html` |
| AC-004 示例边界 | 检查原型不包含真实认证调用 | `HTML-prototype.html` |
| 可访问性 | 检查 `aria-labelledby` 和导航标签 | `HTML-prototype.html` |
| 界面 E2E | required；必须由独立 designer 产出四段用例契约，再由独立 runner 在真实浏览器执行 | 当前 blocked：`sample_only` / `no_runner` 不是 E2E Evidence |
| 复刻像素级对比 | 无参考图，因此不适用；真实复刻任务必须记录基准图、实际图、diff 图或差异指标 | `tasklist.md` not_applicable_reason |
| Harness 复盘链路 | 检查 setup/run/checks/report 是否能追到验收证据 | `../harness/` + `acceptance.md` |

## 不测试

- 真实登录接口。
- 会话恢复逻辑。
- 错误状态。

## 前置门禁

- Architecture 文档尚无独立 exact-hash accepted Evidence，GT-011 blocked。
- `development_environment_check` 与 Architecture-bound `ready` Evidence 缺失，GT-012 blocked。
- 因此本计划仅记录静态覆盖，不宣称整体测试 passed。

## 独立校验

测试计划由 `测试-登录页空状态验收测试` 产出，交给 `评审-登录页空状态测试有效性` 校验。当前静态断言可读，但独立 E2E 设计/执行和 current Evidence 缺失，因此整体保持 blocked。
