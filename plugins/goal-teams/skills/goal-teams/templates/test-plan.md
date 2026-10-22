---
type: Goal Teams Test Plan Template
title: 测试计划模板
---

何时使用：实现开始前（Medium/Large 必写）。先列风险，再写用例，用例确认后再写实现。

# 测试计划：<功能名>

来源：<需求卡片、PRD、页面规格卡路径>

## 1. 风险清单

| RISK | 来源 | 严重度 | 用例 | 覆盖状态 |
| --- | --- | --- | --- | --- |
| RISK-001 | <AC、接口、状态或失败模式> | 高 / 中 / 低 | TC-001 | 已覆盖 / 未覆盖 / 不适用：<理由> |

每条适用风险至少一个用例。blocked、not_run、flaky 都记为未覆盖。

## 2. 用例

### TC-001 <名称>（覆盖 RISK-001、AC-001；层级 unit / api / e2e）

- 输入：<数据、前置状态、角色>
- 步骤：<调用的函数、接口或页面操作，按顺序>
- 预期输出：<返回值、状态变化、DOM 或 URL、副作用>
- 断言：`<assert order.status == "paid">`、`<expect(page.getByTestId('empty')).toBeVisible()>`
- 测试文件：`<tests/test_order.py::test_pay>`

每个用例至少一条业务断言；只看退出码或 HTTP 状态码不算。

## 3. TDD Red / Green

| 任务 | 测试文件 | Red 预期失败原因 | 测试命令 |
| --- | --- | --- | --- |
| T1 | `<tests/test_order.py>` | <功能未实现导致断言失败> | `<pytest tests/test_order.py>` |

1. Red：`gt tdd red T1 --test <测试文件> --expect "<失败信息>" -- <测试命令>`，必须失败。
2. 只改实现，不改测试。
3. Green：`gt tdd green T1 -- <测试命令>`，必须通过。测试文件改过就重新跑 Red。

## 4. 开发期检查（每个任务）

| 检查 | 命令 | 记录方式 |
| --- | --- | --- |
| 受影响测试 | <命令> | `gt run <T> --kind affected -- <命令>` |
| Lint | <命令> | `gt run <T> --kind lint -- <命令>` |
| 构建 | <命令> | `gt run <T> --kind build -- <命令>` |
| E2E（有 UI） | <命令> | `gt run <T> --kind e2e -- <命令>`，由 e2e runner 执行 |

## 5. 发布期检查（冻结版本后各跑一次）

| 检查 | 命令 | 记录方式 |
| --- | --- | --- |
| 全量回归 | <命令> | `gt run - --kind regression -- <命令>` |
| 安全检查 | <命令> | `gt run - --kind security -- <命令>` |

## 6. 环境与数据

- <测试库、种子数据、mock 服务、清理方式>
- 使用测试账号和虚构数据，不连生产库。
