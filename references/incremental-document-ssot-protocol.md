---
type: Incremental Document SSOT Protocol
title: Goal Teams V2.47 增量文档与稳定前缀协议
description: 规定过程文档以增量事件为事实源、稳定合同前置、动态实例尾置，并在收尾确定性投影最终文档。
tags: [goal-teams, v2.47, prompt-cache, ssot, incremental-documents]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.47 增量文档与稳定前缀协议

机器字段、P0 fixture 与确定性 reducer 以 `references/incremental-document-manifest.json`、
`schemas/v2.47/incremental-document.schema.json` 和
`scripts/checks/validate-v247-incremental-document.py` 为准。

## 目标

1. 提高相同 route、角色和合同的稳定前缀复用概率。
2. 过程阶段只追加发生变化的事实，避免反复重写整份 PRD、Plan、进度或报告。
3. 保持唯一 SSOT；最终文档是可重建投影，不是第二个可写事实源。

结构优化只能报告 `structural_delivery_state`。没有可信宿主 usage Evidence 时，不得宣称
真实 Cache 命中率已经提高。

当前交付状态为 `contract_p0_not_runtime_integrated`：本版本提供闭合 manifest、schema、
fixture reducer 与 fail-closed validator，但尚未把 document fragment reducer 接入生产
runtime。本轮项目过程文档也不是由该 reducer 生成，不能作为 runtime integration Evidence。

## 三层结构

| 层 | 内容 | 可变性 | 规则 |
| --- | --- | --- | --- |
| Stable Contract Prefix | Response Contract、invariants、schema、字段顺序、角色稳定说明 | 版本内稳定 | 放在最前；不得插入 task/run/user-specific 值 |
| Route-static References | 当前 route 所需的有序规则路径与 digest | route 内稳定 | 只由 `references/prompt-cache-manifest.json` 决定 |
| Dynamic Instance Tail | 用户请求、目标、路径、任务、状态、Evidence refs、当前增量 | 每轮变化 | 只能最后追加 |

## 增量文档事件

过程文档以 append-only `document_fragment` 记录：

```text
document_id
fragment_id
base_revision
new_revision
section_id
operation: append | replace_section | tombstone
content_ref
content_sha256
actor_run_id
created_at
```

- `append` 添加新事实。
- `replace_section` 只替换稳定 `section_id` 的当前投影；历史 fragment 保留。
- `tombstone` 只表示当前投影不再展示，不能删除历史或 Evidence。
- 同一 `document_id + new_revision` 只能有一个 fragment；CAS 冲突进入 `blocked`。

## 唯一 SSOT 与最终合并

- ledger/document fragments 是过程事实源。
- `TaskList.md`、最终 PRD、最终 test report、最终 completion report 是 reducer/compiler 投影。
- 投影文件必须声明 source fragment prefix/revision/digest。
- 收尾合并固定按 `base_revision -> new_revision -> fragment_id` 排序；相同输入必须生成
  byte-equivalent 输出。
- 最终投影生成后，任何修改仍需追加新 fragment 再重建；禁止直接编辑最终文档形成双写。

## 成员加载

成员只加载：

1. Stable Contract Prefix；
2. 当前 route 的 route-static refs；
3. 与认领 task 相关的 fragment prefix 和最新 checkpoint；
4. Dynamic Instance Tail。

禁止为了方便把整个历史 bundle、所有成员包或所有 runtime profile塞进每次请求。

## 验证

- 检查稳定前缀 bytes/digest 在仅动态输入变化时保持不变。
- 检查 dynamic fields 全部位于 tail marker 之后。
- 检查 fragment revision 连续、hash 匹配、排序确定。
- 检查最终投影可由 fragment prefix byte-equivalent 重建。
- Cache telemetry 缺失时输出 `Cache 命中率：未获取到`，不能用 digest 稳定性替代。
