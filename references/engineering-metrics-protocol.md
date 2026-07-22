---
type: Engineering Metrics Protocol
title: Goal Teams V2.43 工程指标与报告协议
description: 定义十二项工程指标的计算对象、算法口径、历史聚合、Evidence 边界、Benchmark 集成和用户 OKF 报告契约。
tags: [goal-teams, engineering-metrics, benchmark, completion-report, okf]
timestamp: 2026-07-22T00:00:00+08:00
okf_version: "0.1"
project_version: V2.43
metric_schema_version: goal-teams-engineering-metrics-v2.43
source_ssot: references/engineering-metrics-manifest.json
---

# Goal Teams V2.43 工程指标与报告协议

## 定位

V2.43 使用“事件采集 → 确定性计算 → 历史聚合 → OKF 报告投影”生成工程指标。十二项指标是工程观测面，不是任务完成证据，也不替代 `SPEC -> Harness -> Evidence -> Audit`。第一版不把指标数值换算为 Benchmark 100 分评分，也不设置 Release Gate 阈值。

算法元数据、稳定 ID、显示顺序和状态规则以 `references/engineering-metrics-manifest.json` 为机器 SSOT。calculator、普通任务报告和 Benchmark 报告必须读取同一 manifest；不得各自维护一套公式。本文是面向人和 Agent 的规范投影。

## 计算对象

| 对象 | 定义 | 约束 |
| --- | --- | --- |
| `goal_run` | 一次顶层用户任务 | 不等于单个 subagent、turn 或 tool call |
| `change_unit` | SPEC 中预先声明、对用户有意义的可验收变更单元 | 不得在任务结束后拆分以美化指标 |
| `acceptance_attempt` | 独立 Validator 发起的一次正式验收 | 实现者自测不计正式验收 |
| `failure_incident` | 具有稳定 ID 和归一化 signature 的失败事件 | 时间戳、PID、临时路径等噪声不进入 signature |
| `defect` | 经独立复核并绑定具体 change/revision 的缺陷 | 未经复核的猜测不计入 |
| `context_segment` | 编排层显式装载且具有稳定 ID 的上下文片段 | 不代表模型内部 attention |

## 十二项指标

| 指标 | 本次任务算法 | 近期聚合 | 可用性与排除项 |
| --- | --- | --- | --- |
| FPAR — First-pass Acceptance Rate — 首次验收通过率 | 首次正式验收即通过的 `change_unit` 数 ÷ 本次全部可验收 `change_unit` 数 | 合并近期分子、分母 | 只认独立 Validator；实现者自测不计 |
| LCC — Loop Convergence Count — 循环收敛次数 | 首次验收后，由失败触发并完成再次提交的修复循环数；首次实现不计 | 修复循环总数 ÷ 已收敛任务数 | 未收敛显示 `未收敛（≥N 次）`，并报告 convergence coverage |
| HER — Human Escalation Rate — 人工升级率 | 执行开始后是否发生需要人工业务判断、风险接受、授权或冲突裁决的停止事件，取 `0/1` | 人工升级任务数 ÷ 可评估任务数 | 启动流程选择、预先约定检查点和普通确认不计 |
| SAR — Spec Ambiguity Rate — 规格歧义率 | 是否出现正式 `spec_ambiguity` 阻塞事件，取 `0/1` | SPEC 歧义阻塞任务数 ÷ 可评估任务数 | 不影响执行或验收的普通澄清不计 |
| CPAC — Cost per Accepted Change — 单个验收变更成本 | `(可信模型费用 + 可信计算费用) ÷ accepted change_unit 数` | 近期总成本 ÷ 近期 accepted change unit 总数 | 部分成本覆盖为 `provisional`；无可信来源为 `unavailable` |
| DER — Defect Escape Rate — 缺陷逃逸率 | 观察窗内至少出现一个生产逃逸缺陷的已部署 `change_unit` 数 ÷ 已部署 `change_unit` 数 | 合并近期分子、分母 | 未部署为 `not_applicable`；观察窗未结束为 `pending` |
| RRR — Revert / Rollback Rate — 回退/回滚率 | 观察窗内发生 revert/rollback 的已部署 `change_unit` 数 ÷ 已部署 `change_unit` 数 | 合并近期分子、分母 | 未部署为 `not_applicable`；观察窗未结束为 `pending` |
| CWR — Context Waste Rate — 上下文浪费率 | 未被后续决策、命令、变更、Evidence 或最终输出显式引用的上下文权重 ÷ 已装载上下文总权重 | 合并未使用权重和总权重 | 缺 segment provenance 为 `unavailable`；不得推断模型 attention |
| SDI — SSOT Drift Incidents — SSOT 漂移事件数 | 文档、代码、ledger、TaskList、SPEC 状态不一致的去重事件数 | 近期事件总数 ÷ 近期任务数 | 以稳定 fingerprint 去重，多个检查发现同一漂移只计一次 |
| RFR — Repeated Failure Rate — 重复失败率 | signature 在本任务或近期历史已出现的失败数 ÷ 本次失败总数 | 合并重复失败数和失败总数 | 无失败时为 `0%`；默认历史窗口为此前 20 个可比较任务 |
| ARCR — Agent Review Catch Rate — Agent 评审捕获率 | 独立 Reviewer 在验收前首次发现的缺陷数 ÷ `(Reviewer 捕获缺陷 + 同一受审 revision 后续漏检缺陷)` | 合并近期分子、分母 | 观察窗未结束可为 `pending`；无可捕获或漏检缺陷为 `not_applicable`，不是 100% |
| MRT — Mean Recovery Time — 平均恢复时间 | `failure_detected_at` 到同一事件 `work_resumed_at` 的 Agent active time 总和 ÷ 已恢复事件数 | 近期恢复 active seconds 总和 ÷ 已恢复事件数 | 等待用户、审批、凭证或外部系统的时间排除；未恢复事件作为 censored；failure telemetry 未闭合不得写成无失败 |

## 补充计算口径

### 成本与上下文

CPAC 的可信来源优先级为：Provider/平台实际账单；绑定 provider、model、区域、币种和生效时间的版本化价格快照；具有单位价格依据的宿主计算资源计量。多币种没有可信汇率快照时不得相加，缺失费用不得当作零。

CWR 优先使用 segment 级真实 token 数作为权重。宿主无法提供时可降级为 UTF-8 bytes，并记录 `weight_basis=bytes`；不同权重基准不得合并比较。“已使用”必须由 `context_segment_id` 到决策、命令、patch、Evidence、最终结论或 route gate 的显式 provenance 证明。

### 观察窗、去重与恢复时间

- DER、RRR 和 ARCR 默认生产观察窗为推广后 14 天，项目可显式覆盖。
- 迟到的生产缺陷、回滚或 Review 漏检使用 append-only correction event 修正，不覆盖原始事件。
- failure signature 至少绑定 domain、稳定 error code/check ID、failing assertion 和归一化 root cause。
- MRT 主指标采用 Agent active recovery time；wall-clock time 可保留作审计，但不得与 active time 混入同一平均值。

## 历史比较

“上一次”取当前任务之前最近一个可比较、且该指标状态为 `final` 的任务。若最近任务仍为 `pending`，向前查找最近 final 样本，并保留其 run ID 和时间。

“近期平均值”默认读取当前任务之前最近 20 个可比较任务，不包含本次任务：

- 少于 5 个样本仍可显示结果，但必须标记 `insufficient_sample` 和 `n=N`。
- 比例类指标使用 pooled numerator/denominator，禁止直接平均任务百分比。
- LCC、MRT 使用总循环数/总 active seconds 除以有效对象数；SDI 使用事件总数除以任务数。
- `pending`、`unavailable`、`not_applicable` 不得作为零加入平均值。

普通任务 cohort key：

```text
repository_or_project_id
+ work_type
+ execution_profile
+ metric_schema_version
```

Benchmark comparison key：

```text
scenario_id
+ execution_mode
+ rubric_digest
+ model_and_config_identity
+ metric_schema_version
```

Skill 版本保留为比较维度，不进入严格 equality key，因为版本变化通常是 Benchmark 自变量。

## 状态与证据

每项指标只能使用以下状态：

- `final`
- `provisional`
- `pending`
- `unavailable`
- `not_applicable`
- `insufficient_sample`

零必须有完整可计算分母和支持零值的 Evidence；“没有采集”“尚未观察”“不适用”和“样本不足”不得写成零。每项结果至少包含 `metric_id`、calculator version、status、value/unit、适用时的 numerator/denominator、coverage、observation window、weight basis 和 `evidence_refs`。

指标 `evidence_refs` 只引用本轮已有 ledger、Harness、Review、usage、deployment、failure 或 context provenance。指标摘要和报告不得作为任务完成的 Evidence，也不得把本次 Completion Audit artifact 反向用来证明自身通过。

## 存储与投影

V2.3 core ledger event type 是闭合枚举；工程指标使用独立、只追加的 telemetry sidecar，并引用 ledger/Evidence：

```text
GoalTeamsWork-<project_version>/
  versions/<artifact_version>/
    metrics/
      metric-events.jsonl
      metric-summary.json
      engineering-metrics.md
```

- `metric-events.jsonl` 保存脱敏后的原始观察和 correction event，不保存 raw prompt、secret 或未脱敏日志。
- `metric-summary.json` 是确定性 calculator 对本次、上一次和近期样本的机器投影。
- `engineering-metrics.md` 是用户查看的自包含 OKF 工程指标报告。
- Task 状态仍以 V2.3 ledger 为 SSOT；metrics sidecar 只承载工程观测事实。

## 用户 OKF 工程指标报告

默认路径：

```text
GoalTeamsWork-<project_version>/versions/<artifact_version>/metrics/engineering-metrics.md
```

报告必须是独立可解析的 OKF Concept Document。frontmatter 至少包含非空 `type`、`title`、`description`、`timestamp`、`okf_version`、产品/项目/artifact 版本、`run_id`、`metric_schema_version`、`calculator_version`、`algorithm_manifest_sha256` 和可解析的 `source_ssot`。普通任务使用 `versions/<artifact_version>/metrics/metric-summary.json`；以 scenario 目录为 OKF 根的 Benchmark 报告使用 `metrics/metric-summary.json`。`algorithm_manifest_sha256` 必须是报告实际使用的 manifest 内容 digest。

正文至少包含：

1. run identity、cohort key、calculator version、数据覆盖和观察窗。
2. 四列完整指标表；第一列严格为“缩写 — 英文全称 — 中文名称”，其余列依次为“本次任务数值”“上一次的数值”“近期平均值”。
3. 十二项指标的自包含算法与统计口径：`metric_id`、英文全称、中文名称、公式、分子、分母、排除项、本次规则、上一次选择规则、近期聚合规则、可用状态和本轮 `evidence_refs`。
4. 延迟指标的预计刷新时间、不可用原因、样本数和 coverage。
5. 算法 manifest digest、Evidence refs、correction 说明和隐私说明。

报告必须让用户在不读取实现源码或外部协议的情况下，区分零、等待观察、遥测不可用、不适用和样本不足，并理解近期值采用对应指标的 pooled aggregation。

## Completion 与用户响应

Completion 阶段先生成并校验 `engineering-metrics.md`，再给用户最终回复。指标值为 `pending`、`unavailable` 或 `not_applicable` 不阻塞业务 Done Criteria，但报告必须如实保留状态和原因。指标报告不得掩盖任何未闭合的 SPEC、Harness、Evidence 或 Audit 缺口。

最终回复不复制十二项指标表或算法正文，只提供可点击的工程指标报告链接，并明确提醒用户打开查看。报告没有真实生成时，必须说明“未生成”和原因；不得在聊天中假装已有报告，也不得给出不可定位的相对描述。

## Benchmark 集成

每个 Benchmark run record 记录同一 calculator 输出的 `engineering_metrics`：schema version、current、previous、recent、recent sample count 和 report path。`summary.json`、Benchmark Markdown report 与用户 OKF 工程指标报告必须读取同一 `metric-summary.json` 和算法 manifest，不得重复实现公式。

十二项指标在 V2.43 第一版只作为观察维度。未来若设为评分或 gate，必须另行确认基线、目标、最小样本、允许退化、观察窗和反游戏规则。

## 隐私与失败降级

- 遥测和报告沿用统一 secret redaction；不持久化 raw prompt、Authorization/Cookie、数据库 URI、云凭证或协作工具 token。
- calculator、manifest 或写入能力不可用时标记 `unavailable` 并记录原因，不估算数值。
- 生产观察窗未关闭使用 `pending`；未部署使用 `not_applicable`。
- 无权限写报告时明确报告未生成；不能用最终回复中的临时表格替代 OKF 产物。
