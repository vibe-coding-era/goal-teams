---
type: Goal Teams Acceptance Template
title: 验收记录模板
---

何时使用：本轮收尾、执行 `gt finish` 之前；逐条核对完成标准，只写证据支持的结论。

# 验收记录：<目标名>

来源：`gt goal --show`（完成标准）、`gt check`（完成判定）、`gt status`（任务与评审）

## 1. 完成标准 → 证据 → 结论

| 完成标准 | 关联 AC | 证据（receipt id） | 评审 | 结论 |
| --- | --- | --- | --- | --- |
| <完成标准原文> | AC-001 | <来自 gt run / gt tdd 的 receipt id> | <评审人与 pass/fail> | passed / failed / blocked / not_run / stale |

- 结论只用 passed、failed、blocked、not_run、stale 五个值；没有证据就写 not_run。
- blocked 是合法结论：写清缺什么（环境、权限、外部依赖）和谁来补。
- 评审之后又改过代码或产物，结论写 stale，重新运行检查并评审。
- 手工证据（`gt run --manual`）标「手工」，写明谁、在什么环境、看到了什么。

## 2. 完成轴

| 轴 | 状态 | 依据 |
| --- | --- | --- |
| 工程：任务全部完成并通过评审 | 是 / 否 | `gt check` 的输出 |
| 运行时：在真实环境跑通 | 是 / 否 / 未验证 | <运行时检查的 receipt id> |
| 业务：业务方确认结果可用 | 是 / 否 / 未验证 | <确认人与时间> |
| 发布与安装 | 是 / 否 / 不适用 | `gt check --release` 的输出 |

各轴分开填写；工程完成不代表业务已验证。

## 3. 未通过项

| 完成标准 | 原因 | 负责人 | 下一步 |
| --- | --- | --- | --- |
| <完成标准> | <如 blocked：缺少测试环境> | <成员> | <补齐后要重跑的命令> |

## 4. 结论与决策

- 本轮结果：achieved（`gt check` 退出码 0）或 stopped（<原因>）
- 决策：`gt finish`（达成）或 `gt loop decide <continue / replan / stop> --reason "<理由>"`
- 改进建议：`gt reflect "<本轮观察>" --action "<建议动作>"`
