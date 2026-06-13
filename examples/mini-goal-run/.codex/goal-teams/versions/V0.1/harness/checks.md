# Harness Checks

## 静态校验清单

| 检查项 | 方法 | 通过条件 | 证据 |
| --- | --- | --- | --- |
| 索引完整 | 对照总索引和版本索引 | Harness 文档被列入索引 | `../../../INDEX.md`、`../INDEX.md` |
| 计划可追溯 | 检查 Teams 规划表 | GT-006 记录 Harness Owner、锁定范围和验证安排 | `../plan.md` |
| tasklist 可追溯 | 检查 Member Ownership | GT-006、GT-007、GT-008 状态为 done | `../tasklist.md` |
| SPEC 不被 Harness 替代 | 检查 spec 目录 | PRD、设计、测试计划、验收清单仍保留 | `../spec/` |
| 证据链完整 | 检查 progress 和 acceptance | setup/run/checks/report 均被验收记录引用 | `../progress.md`、`../spec/acceptance.md` |
| automation protocol 样例 | 检查 YAML 字段 | 标记 `sample_only: true`，且声明不连接真实生产或外部服务 | `automation-protocol.sample.yaml` |
| evidence ledger 样例 | 检查 JSON 字段 | artifact、author、validator、evidence_ref 可追溯 | `evidence-ledger.sample.json` |
| pipeline gates 样例 | 检查 YAML 字段 | 范围门、SPEC 门、证据门、收尾审计门均有 owner 和 pass criteria | `pipeline-gates.sample.yaml` |
| 轻量约束 | 检查目录内容 | 只包含 Markdown、YAML、JSON 静态文件 | `README.md` |

## 手工复盘步骤

1. 从 `setup.md` 确认目标和边界。
2. 从 `run.md` 对照 `../tasklist.md` 检查任务顺序。
3. 从本文件确认每个校验项都有证据路径。
4. 从 `.sample.yaml` 和 `.sample.json` 确认没有真实生产接入字段。
5. 从 `report.md` 确认验收结论和剩余风险。

## checks 完成标准

- 每个检查项有方法、通过条件和证据。
- 检查项覆盖 setup、run、checks、report 四个阶段。
- 检查项覆盖 automation protocol、evidence ledger 和 pipeline gates 三类静态样例。
- 未要求执行外部命令。
