---
type: Runtime Reference
title: Goal Teams Runtime
description: Goal Teams runtime 渐进式索引、启动身份与按场景加载入口。
tags: [goal-teams, runtime, progressive-loading]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Runtime

本文件是渐进式索引。先按场景选择一个分片，不要一次加载全部 runtime。

当前启动身份：`我是 Goal Teams Lead V2.44。`

V2.44 继续使用 V2.38-compatible route-static manifest schema；当前 self-release ordered refs 指向 V2.44 Profile，V2.43/V2.42/V2.41/V2.40/V2.39/V2.38 Profile 只读 replay。route 静态顺序、动态尾标签和 byte budget 以 `references/prompt-cache-manifest.json` 为机器 SSOT；计划文件 bytes 用 `route_static_digest` 标识。只有宿主观察最终 ordered segments 后才生成 runtime digest；Cache Evidence 四状态轴、usage 与 fail-closed live probe 语义见 `references/prompt-cache-protocol.md`。

- [`runtime/01-v2-36-core-trust.md`](runtime/01-v2-36-core-trust.md)：V2.36 Core trust 入口
- [`runtime/02-harness-benchmark-loop.md`](runtime/02-harness-benchmark-loop.md)：Harness、Benchmark 与 Loop 契约
- [`runtime/03-goal-loop.md`](runtime/03-goal-loop.md)：目标循环细节（Goal Loop）
- [`prompt-cache-protocol.md`](prompt-cache-protocol.md)：route/runtime identity 边界、observer telemetry 与 plan-only probe
