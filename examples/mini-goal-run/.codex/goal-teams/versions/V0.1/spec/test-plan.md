# Test Plan

## 测试范围

| 范围 | 方法 | 证据 |
| --- | --- | --- |
| 空状态文案 | 静态检查 HTML | `HTML-prototype.html` |
| 主操作 | 检查按钮文案为“登录” | `HTML-prototype.html` |
| 次操作 | 检查创建账号和联系支持链接 | `HTML-prototype.html` |
| 可访问性 | 检查 `aria-labelledby` 和导航标签 | `HTML-prototype.html` |
| Harness 复盘链路 | 检查 setup/run/checks/report 是否能追到验收证据 | `../harness/` + `acceptance.md` |

## 不测试

- 真实登录接口。
- 会话恢复逻辑。
- 错误状态。

## 独立校验

测试计划由 `测试-登录页空状态验收测试` 产出，交给 `评审-登录页空状态测试有效性` 校验断言是否覆盖 PRD 验收标准；Harness 复盘链路由 `评审-登录页空状态文档校验` 复核证据引用。
