---
type: Goal Teams Function Rules
title: Graph Engineering Function
description: 定义 V2.67 可执行 Graph 的编译、调度、权限、恢复与证据边界。
tags: [goal-teams, v2.67, graph-engineering, runtime]
timestamp: 2026-08-22T00:00:00+08:00
okf_version: "0.1"
---

# Graph Engineering Function

- `function_id`: `FUNCTION-GRAPH-ENGINEERING-V266`
- `purpose`: 把 Requirement/TaskExactSet 编译为有类型端口、条件、权限、重试、恢复和完成语义的可执行 Graph；区分静态 DAG、宿主执行与真实业务证明。
- `execution_asset_generation`: `V2.65`；V2.67 只改变 Product/Policy 输出控制，不复制或冒充新的 Graph Runtime。

## trigger_and_exclusion_facts

- 触发：任务需要多节点依赖、并行/汇聚、条件路由、重试、HITL、持久恢复、外部副作用或多轮主动进化。
- 排除：只有文件索引、RDF 文档关系、Task 列表或 `ready_layers` 不构成可执行 Runtime；结构 Green 不证明 Host/Provider 或业务行为。

## inputs

- current Requirement/AC、plan revision、TaskExactSet digest、Owner/Validator、资源与权限、Host capability、预算、恢复与退出合同。

## obligations_and_outputs

- Graph contract 必须规范化并哈希 node/edge/port/gate/action/resource identity；必需 Input Port 必须由 typed Data Edge 完整绑定。
- Runtime 只执行全部 predecessor、Gate、authority、scope 和 Host capability 已满足的节点；fan-in、condition、retry 与 terminal transition fail closed。
- 外部 effect 使用 durable idempotency reservation/confirmation/readback；prepared 不能冒充 running，confirmed key 不得重复执行。
- checkpoint、RunHead、Event 和 mutation receipt 必须原子持久化并支持进程退出后的 reopen/recover；CAS 冲突不可静默覆盖。
- HITL interrupt/resume 保留全局运行身份、批准证据、attempt 与后继关系；恢复必须重新验证 authority 和 Host capability。
- Callback 仅为 `fixture_only`；local fake external adapter 必须声明 `real_external_effects=false`。真实 Host/Provider 与业务完成保持独立 Evidence。

## oracles_and_evidence

- immutable Red/Green TestCase digest、compiled Graph digest、Runtime event chain、Host lifecycle receipt、Store readback、process-exit recovery和独立 completion review。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`

## dependencies

- `FUNCTION-ARCHITECTURE-IMPLEMENTATION-V250`
- `FUNCTION-AGENT-RUNTIME-V250`
- `FUNCTION-TESTING-V250`

## owned_rule_ids

- `GT265-GRAPH-TYPED-CLOSURE`: 每个 required Input Port 必须由类型兼容且来源明确的 Data Edge 完整绑定；Gate、Human、Control 和 Data Edge 不得互相冒充。
- `GT265-GRAPH-AUTHORITY`: Owner、Validator、Host adapter、workspace、permission、tool、network 和 external-effect authority 必须在执行前闭合并进入 receipt lineage。
- `GT265-GRAPH-DURABILITY`: Event、checkpoint、RunHead、idempotency 与 mutation receipt 使用原子事务、CAS 和精确 readback；恢复不得重复 confirmed side effect。
- `GT265-GRAPH-SCHEDULER`: 并行、fan-in、condition、retry、HITL 与 terminal transition 由 Runtime 语义驱动，不由文件名、节点枚举或静态层级推断。
- `GT265-GRAPH-EVIDENCE-BOUNDARY`: 本地 fake/Callback、结构验证、installed manifest 和真实 Host/Provider/业务证据分别投影，任何较弱层级不得提升为较强完成声明。
