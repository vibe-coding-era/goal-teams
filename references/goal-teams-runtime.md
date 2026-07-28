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

当前启动身份：`我是 Goal Teams Lead V2.47。`

V2.47 继续使用 V2.38-compatible route-static manifest schema；当前 self-release ordered refs 指向 V2.47 Profile，V2.46 及更早 Profile 只读 replay。route 静态顺序、动态尾标签和 byte budget 以 `references/prompt-cache-manifest.json` 为机器 SSOT；过程文档按 `references/incremental-document-ssot-protocol.md` 追加 fragment，最终文档只在收尾确定性投影。只有宿主观察最终 ordered segments 后才生成 runtime digest；没有 usage Evidence 时缓存命中率保持 `未获取到`。

- [`runtime/01-v2-36-core-trust.md`](runtime/01-v2-36-core-trust.md)：V2.36 Core trust 入口
- [`runtime/02-harness-benchmark-loop.md`](runtime/02-harness-benchmark-loop.md)：Harness、Benchmark 与 Loop 契约
- [`runtime/03-goal-loop.md`](runtime/03-goal-loop.md)：目标循环细节（Goal Loop）
- [`prompt-cache-protocol.md`](prompt-cache-protocol.md)：route/runtime identity 边界、observer telemetry 与 plan-only probe
- [`codeagent-runtime-manifest.json`](codeagent-runtime-manifest.json)：CodeAgent runtime 识别、单 overlay 选择与 fail-closed 边界
