---
type: Agent Runtime Capability Contract
title: Goal Teams V2.43 跨 Agent 运行时能力合同
description: 将可移植的 Goal Teams 核心与特定 Agent 平台 adapter 分离。
tags: [goal-teams, v2.41, agent-runtime, compatibility]
timestamp: 2026-07-18T00:00:00+08:00
okf_version: "0.1"
---

# 跨 Agent 运行时能力合同

Goal Teams 是可被不同 Agent 运行时采用的工作流协议；Codex 是当前完整 adapter，不是 Portable Core 的前置条件。此合同不宣称其他 Agent 已经拥有可执行 adapter。

## 分层

| 层 | 责任 |
| --- | --- |
| Portable Core | 流程澄清、Plan、SSOT、状态、Harness、Evidence、独立性和失败语义。 |
| Runtime Capability Contract | 用机器可读 manifest 声明可用能力、可信度和权限。 |
| Runtime Adapter | 把某个 Agent 平台的工具、成员 transport 和持久化映射到合同。 |
| Codex Adapter | `$goal-teams`、`SKILL.md`、`.codex`、`CODEX_HOME`、`goal-*.toml` 与 Codex transport。 |

## 最小能力

| 能力 | 作用 | 缺失处置 |
| --- | --- | --- |
| `read_workspace` | 加载规则与目标资料 | 缺失即 blocked。 |
| `write_workspace` | 持久化非 preview 产物 | 仅可执行明确的 no-write preview。 |
| `command_execution` | 测试、构建、脚本验证 | 相关检查 blocked，不能报告 passed。 |
| `vcs_snapshot` | 完整变更集与发布 Evidence | release/acceptance blocked。 |
| `subagent_dispatch` | 独立成员执行 | 仅低风险、非阻断且 Harness 不要求独立验证时可降级。 |
| `identity_attestation` | 独立性和最终验收 | 缺失时不得 accepted 或 achieved。 |
| `external_write` | 发布、部署和远程修改 | 默认 false，必须取得单独授权。 |

adapter 必须给出 `runtime_id`、版本、能力值、权限边界和可信度。自报能力、调用方 callback 或运行时名称不能替代 Evidence、受保护快照或宿主 attestation；能力不足时必须降级或 blocked，不能声称全功能兼容。

## 兼容边界

- 通用 Agent 可读取 Portable Core 并执行流程澄清、PRD 和计划。
- 只有实现了相应 adapter 且其能力获得证明时，才能运行命令、派发独立成员或产生验收 Evidence。
- Codex 专属安装与 subagent 文件保留为 Codex Adapter；其他平台不必模拟这些路径。
