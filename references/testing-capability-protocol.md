---
type: Goal Teams Testing Capability Protocol
title: Goal Teams V2.44 API 与 E2E 测试能力协议
description: 定义测试计划、用例、执行证据、风险覆盖、问题账本和真实行为 Benchmark 的 100 分闭环。
tags: [goal-teams, v2.44, api, e2e, testing, benchmark]
timestamp: 2026-07-23T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.44 API 与 E2E 测试能力协议

## 目标与权威来源

V2.44 把“测试成员写了多少说明”改为“测试成员能否交付可执行、可重放、可审计的行为证据”。评分维度、权重、已知问题和反游戏规则以 `references/testing-capability-manifest.json` 为机器 SSOT；机器产物以 `schemas/v2.44/` 为准。

满分为 100 分，但只有各维度的 required checks 全部 `passed` 才能获得对应分值。`blocked`、`not_run`、`unavailable`、缺覆盖分母、只返回退出码、只提供 prose 或重试后隐藏首次失败均不得计分。

## 三类机器交接物

1. `integration-test-plan`：绑定需求/风险分母、环境、数据、API/E2E 范围、入口/退出条件、清理策略、独立 Owner/Validator 与预期 Evidence。
2. `test-case`：保留 V2.35 的 `input + processing + expected_output + assertions`，V2.44 API/E2E profile 进一步要求 typed protocol fields、业务 oracle、side effects/checkpoints 与可验证文件引用。
3. `test-run-result`：绑定命令、环境、数据、时间、退出状态、摘要、失败、artifact、retry/flake、cleanup 和 replay；原始失败不得被后续 retry 覆盖。

所有 source/test/artifact 引用必须至少包含规范化相对路径、SHA-256 和 discovery 状态；实际执行前必须验证文件存在、普通文件身份和 digest。

## API 风险合同

API 计划和用例必须按适用性显式处理：

- method、path、auth、headers、request、setup；
- expected status、headers、body、domain oracle 和 side effects；
- 权限边界、幂等、重试、并发、补偿、最终一致性；
- 数据隔离、清理、可重复运行和失败后的状态检查。

不适用项必须给出结构化理由，不能通过省略字段获得通过。

## E2E 风险合同

E2E 计划和用例必须按适用性显式处理：

- persona、权限、initial state、session state；
- typed actions、页面/URL/locator 与用户可见 checkpoints；
- refresh、back/forward、double click、重复提交、错误恢复；
- trace、截图、视频或 DOM/网络证据；
- 清理、隔离、重放以及浏览器不可用时的 `not_run|blocked` 事实。

非 UI 或无浏览器执行不能冒充真实 E2E 通过。

## 风险分母与问题账本

每次测试计划先列出需求、接口、用户旅程、角色权限、状态转移、失败模式和受影响数据的 coverage denominator，再把每个条目映射到用例和 Evidence。未覆盖项必须保留为 open issue 或结构化 waiver。

问题账本 append-only：已发现问题保留稳定 `issue_id`；关闭通过新增 event 记录 `resolved_by`、证据和验证 run，不得删除或改写历史问题。未来发现的新问题必须在本次评分前登记，并关联一个评分维度。

## 100 分门禁

| 维度 | 分值 | 获得满分的最低证据 |
| --- | ---: | --- |
| 角色与独立性 | 15 | 设计、实现/执行、Review 使用不同 run identity；专项 route 精确加载 |
| 机器合同与语义校验 | 20 | 三类 schema 与正负语义 fixture 全通过，引用存在且 digest 一致 |
| API 集成测试能力 | 15 | typed case 覆盖适用协议风险并由真实服务 oracle 验证 |
| E2E 测试能力 | 15 | typed journey 覆盖适用交互风险并由真实浏览器证据验证 |
| 执行与证据 | 15 | test-run-result 可重放，失败/retry/flake/cleanup 不丢失 |
| 风险、环境、数据与覆盖分母 | 10 | 分母完整、用例映射明确、未覆盖项保留 |
| 真实行为 Benchmark | 10 | seeded defects 正确检出，positive baseline 通过，重复运行一致 |

得分报告必须逐维列出 `status`、`earned`、`possible`、checks、Evidence refs 和 open issue IDs。总分只是投影；任何 required check 非 `passed` 时不得报告 `100/100 achieved`。

## Benchmark 与完成边界

真实 Benchmark 必须包含可启动系统、确定性数据、行为 oracle、seeded defect、观察输出和清理。结构校验、fixture 数量或进程退出码不等于行为结论。Benchmark 失败必须驱动 LOOP 回到合同、成员包、runner 或评分器，不得降低阈值、删除问题或改写预期。

V2.44 测试能力分数不替代项目测试、Review、Evidence 或 Completion Audit；它只证明测试成员和测试控制面具备相应能力。
