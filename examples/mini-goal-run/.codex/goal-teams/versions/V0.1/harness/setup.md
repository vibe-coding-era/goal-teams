# Harness Setup

## 目标

复盘“登录页空状态提示 V0.1”这次最小 Goal Teams 示例运行，确认它只生成文档和 HTML 原型，并能留下可检查的验收证据。

## 输入

| 输入 | 值 |
| --- | --- |
| 示例目标 | 规划登录页空状态提示 V0.1 |
| 版本目录 | `.codex/goal-teams/versions/V0.1/` |
| 团队索引 | `.codex/goal-teams/INDEX.md` |
| 版本索引 | `.codex/goal-teams/versions/V0.1/INDEX.md` |
| 执行计划 | `.codex/goal-teams/versions/V0.1/plan.md` |
| 任务清单 | `.codex/goal-teams/versions/V0.1/tasklist.md` |

## 边界

| 项目 | 规则 | 证据 |
| --- | --- | --- |
| 允许范围 | 只读示例输入，写入版本目录文档 | `plan.md#环境检查` |
| 禁止范围 | 不修改真实业务代码 | `plan.md#用户目标` |
| 依赖 | 不新增运行时依赖或脚本 | 本文件和 `decisions.md` |
| Harness 形态 | Markdown、YAML、JSON 静态复盘资料 | `README.md` |
| 生产边界 | 不连接真实生产、CI、凭证、支付或认证系统 | `automation-protocol.sample.yaml`、`pipeline-gates.sample.yaml` |

## setup 完成标准

- 能定位索引、计划、tasklist、SPEC、progress 和 acceptance。
- 能说明本示例不是业务实现。
- 能说明 Harness 只用于复盘，不是可执行测试框架。
- 能说明 automation protocol、evidence ledger 和 pipeline gates 都是静态样例。
