---
type: Goal Teams Prompt Cache Protocol
title: Goal Teams V2.39 Prompt Cache Evidence 协议
description: 统一 route/runtime prompt 身份、host attestation、raw-first 遥测、预算和 fail-closed probe 契约。
tags: [goal-teams, v2.39, prompt-cache, telemetry, evidence, context-budget]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.39 Prompt Cache Evidence 协议

本协议只覆盖 Goal Teams 可复核的 prompt 段；不能强制、清空或保证宿主 cache，也不把本地 digest 伪装成 provider key。

## 有序 Prompt SSOT

`references/prompt-cache-manifest.json` 是 route-static 顺序、artifact compiler 与 budget 的机器 SSOT。`scripts/v23/prompt_cache.py` 负责安全读取、顺序校验和 digest；各消费者不得维护另一套顺序表。

V2.35/V2.36 的签名 `rule_set` 继续表示 policy membership，并为兼容 replay 保持原 byte shape；它不是 prompt 装载顺序。`prompt-plan --features` 在不修改 signed route 的前提下，把该集合编译成 manifest 管理的 `structured_policy` ordered subset。

- `prefix_manifest_sha256` 绑定 route ID、ordered refs 和动态尾标签，不绑定文件内容。
- `route_static_digest` 只绑定计划 route 的路径、长度、文件字节和顺序；它不是实际 provider prompt。
- 只有宿主在最终 request assembly 边界提供 ordered segments 时，才生成 `stable_prefix_digest` 与 `runtime_prompt_digest`。
- 仓库 route plan 输出 `manifest_status=unavailable`、`digest_scope=partial`、缺失 classes，runtime digests 保持 `null`。
- `skill_tree_digest` 继续证明完整安装树；它与 route/static/runtime identity 不能互相替代。
- route manifest 拒绝重复 key/路径与越界；host manifest 是闭合 schema，身份/provenance/count 必填，顺序为 platform-managed → stable → dynamic。user/tool 只能 dynamic，source ref 只用相对路径/安全 scheme；omitted 只进 manifest hash。

V2.39 的 `goal-teams-host-capability-receipt-v2.39` 先显式声明最终 request boundary、有效配置证明、usage event、cache namespace 和 request hit 语义能力。receipt 只是能力声明，不是信任证明。`goal-teams-ordered-prompt-manifest-v2` 绑定 receipt、request binding、host adapter 与 `pre_provider_send` 边界；`partial` manifest 只保留 manifest hash，`stable_prefix_digest` 与 `runtime_prompt_digest` 必须为 `null`。

Host attestation 使用发行包内 `references/prompt-cache-trust-policy.json` 的 data-only policy。`load_production_cache_policy` 只接受由 release/install 身份门签发并绑定 package tree、policy、loader 与 checker hash 的 package identity receipt；普通调用方 dict、callback、module/import path、shell command 或 executable path 一律拒绝。初始 V2.39 policy 不注册 production verifier、adapter 或 authorization issuer，因此 host/live 状态保持 unavailable。

## 遥测边界

`subject_visible_telemetry` 表示 agent 在执行当轮可见的 token/cost 信号，只能由它驱动 Budget Gate。`observer_telemetry` 表示 runner 在轮后从 provider/CLI 事件观察到的 usage，只用于事后分析，不能倒灌为当轮已知事实。

核心指标：

```text
cached_input_share = sum(cached_input_tokens) / sum(covered_input_tokens)
uncached_input_tokens = sum(covered_input_tokens) - sum(cached_input_tokens)
telemetry_coverage = telemetry_turns / completed_turns
```

`turn.completed` 是 turn 聚合。没有 request 粒度事件时，`request_hit_rate` 必须为 `null/unavailable`，禁止由 turn cache presence 或 token share 推导。

Production Evidence 只允许 `persist_usage_events → normalize_usage_events → aggregate_normalized_events` 的 receipt 链。raw receipt 绑定 output-root-relative path、原始 bytes/hash、adapter policy、capture invocation/sequence、exclusive-create 与 finalized state；normalizer 重开相对路径，拒绝 symlink/path escape 并复算 bytes/hash 后才生成逐行 source-path sidecar。普通字符串 parser 只保留为 V2.38 `diagnostic_non_evidence`，`evidence_eligible=false`，不得进入 status、recommendation 或 completion。

## Benchmark 与 A/B Probe

Benchmark record 绑定 version、CLI/model/config/package、prompt、scenario/profile 与 raw hash，并按完整 identity 分组。无可信 host config/trace attestation 或 clean/versioned telemetry 时 cache analytics 为 unsupported。

V2.38 兼容 CLI 继续只提供 probe plan compiler：每组一次 first-seen reference 和五次 repeat，比较动态尾与稳定前缀变化，不调用 provider，也不声称 cold run 或 A/B 结论。

V2.39 `scripts/v23/cache_probe.py` 编译 current/candidate 交错的 first-seen、immediate-repeat、dynamic-suffix 与 stable-prefix 计划。production executor 默认 fail closed：只有 package-bound production policy receipt 与 `verify_live_authorization` 生成的不可变 authorization verification receipt 同时成立，才可进入 adapter 选择；普通 `{authorized: true}` 或 caller adapter/callback 在任何 adapter 检查前返回 `not_authorized`。每个 usage-only raw event 必须先经过 prompt/secret/credential/绝对路径预检，再不可变落盘并 hash，之后才允许 normalize。fixture helper 永远为 `evidence_eligible=false, scope=structural_only`。

用户可见结果必须独立列出：

- `structural_delivery_state`
- `host_integration_state`
- `live_cache_validation_state`
- `request_hit_rate_support_state`

结构通过不能覆盖 host/live unavailable，也不能生成“命中率已提升”或“缓存优化有效”的声明。

## 隐私与失败语义

manifest 和报告只存路径摘要、长度、摘要、分类和 usage，不持久化原始用户 prompt、secret 或未脱敏外部内容。usage 缺失、负数、cached 大于 input、重复/冲突 terminal event 或未知事件结构时降级并记录计数。只有稳定 event ID 才可确定去重；无 ID 的相同 payload 保留为独立观察、标记 ambiguous candidate，并令 duplicate detection/结论降级，禁止静默合并。

V2.38 replay 不改写历史对象或文件。若调用方提供原始 bytes/text，sidecar 的 `source_record_sha256` 绑定原始字节；只提供 dict 时明确标记 `canonical_object`，缺失的 host receipt、runtime identity、attestation 和 request semantics 全部映射 unavailable/unsupported。
