# Harness 复盘索引

这个目录是最小 Harness 示例，只保存静态文档，不执行命令、不引入依赖。维护者可以用它复盘一次 Goal Teams 示例运行是否能从准备输入追到最终验收。

## 复盘顺序

| 阶段 | 文档 | 作用 | 关键证据 |
| --- | --- | --- | --- |
| setup | `setup.md` | 记录目标、输入、边界和版本目录 | [`../plan.md`](../plan.md)、[`../tasklist.md`](../tasklist.md) |
| run | `run.md` | 记录成员执行顺序和产物 | [`../progress.md`](../progress.md) |
| checks | `checks.md` | 记录静态校验点和通过条件 | [`../spec/test-plan.md`](../spec/test-plan.md)、[`../spec/acceptance.md`](../spec/acceptance.md) |
| report | `report.md` | 汇总静态检查、blockers 和整体结论 | [`../progress.md#当前状态`](../progress.md#当前状态) |
| automation protocol | `automation-protocol.sample.yaml` | 展示自动化协议的静态记录字段 | [`../plan.md`](../plan.md)、[`../progress.md`](../progress.md) |
| evidence ledger | `evidence-ledger.sample.json` | 展示 artifact、author、validator、evidence_ref 及 blocked gap | [`../progress.md#当前独立校验`](../progress.md#当前独立校验) |
| pipeline gates | `pipeline-gates.sample.yaml` | 展示范围门、SPEC 门、证据门和收尾审计门 | [`../spec/acceptance.md`](../spec/acceptance.md) |

## 使用方式

1. 先读 `setup.md`，确认目标、锁定范围和不新增依赖约束。
2. 再读 `run.md`，确认每个成员的输出可以映射到 tasklist。
3. 再读 `checks.md`，确认每个校验项都有证据路径。
4. 对照三个 `.sample.*` 文件，确认自动化协议、证据账本和流水线门禁只是静态样例。
5. 最后读 `report.md`，确认验收结果、剩余风险和资源消耗记录齐备。

## 非目标

- 不模拟真实 Codex CLI 调度。
- 不新增可执行脚本。
- 不替代仓库根目录的 `./scripts/check.sh`。
- 不连接真实生产、CI、凭证、支付或认证系统。
