# Harness Run

## 执行顺序

| 顺序 | 成员 | 任务 | 输出 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | 需求分析-登录页空状态需求澄清 | GT-001 | 需求规格卡 | `../spec/requirement-spec-card.md` |
| 2 | 产品-登录页空状态 PRD | GT-002 | PRD | `../spec/PRD.md` |
| 3 | 前端-登录页空状态 HTML 原型 | GT-003 | HTML 原型 | `../spec/HTML-prototype.html` |
| 4 | 测试-登录页空状态验收测试 | GT-004 | 测试计划 | `../spec/test-plan.md` |
| 5 | 文档-登录页空状态验收文档 | GT-005 | 验收清单 | `../spec/acceptance.md` |
| 6 | 文档-Harness 示例复盘 | GT-006 | Harness 复盘资料 | `README.md`、`setup.md`、`run.md`、`checks.md`、`report.md`、`automation-protocol.sample.yaml`、`evidence-ledger.sample.json`、`pipeline-gates.sample.yaml` |
| 7 | 评审-登录页空状态文档校验 | GT-007 | 独立校验记录 | `../progress.md#独立校验` |
| 8 | 收尾-登录页空状态未完成工作检查 | GT-008 | 收尾审计 | `../progress.md#收尾审计` |

## 运行记录

| 检查点 | 结果 | 说明 |
| --- | --- | --- |
| Teams 规划表先于执行产物 | passed | `../plan.md#teams-规划表` 记录成员、workflow、前置任务和验证安排 |
| tasklist 记录认领关系 | passed | `../tasklist.md#member-ownership` 覆盖 GT-001 到 GT-008 |
| progress 记录执行轮次 | passed | `../progress.md#2026-05-27-1000-执行轮次` |
| Harness 资料连接验收证据 | passed | `checks.md` 和 `report.md` 引用 acceptance/progress |
| 静态样例不触发真实自动化 | passed | `.sample.yaml` / `.sample.json` 文件均声明静态边界或 `sample_only` |

## run 完成标准

- 每个任务都有 Owner、前置任务、输出和证据。
- Harness 不要求实际调用外部服务。
- 运行记录能被维护者按表格顺序复盘。
