---
type: Goal Teams Function Rules
title: Goal Teams V2.67 Knowledge Graph
description: 定义基于 OKF 与 Markdown SSOT 的只读、无数据库、可追溯文档图谱投影。
tags: [goal-teams, v2.67, knowledge-graph, okf, markdown, rdf]
timestamp: 2026-08-07T00:00:00+08:00
okf_version: "0.1"
---

# OKF Document Graph

- `function_id`: `FUNCTION-KNOWLEDGE-GRAPH-V250`
- `purpose`: 将受信跟踪的 OKF/Markdown 文档在内存中投影为可追溯知识图谱，提升复用与检索，并通过明确的证据、修订和歧义状态减少 LLM 幻觉。

## trigger_and_exclusion_facts

- 触发：非 Discussion 的 Development、UI/Desktop、Agent Runtime 或 Release route 需要检索、关联、追溯或解释当前文档知识。
- 排除：Discussion 不自动加载本 Owner；未提供可信 `replay_version` 时不得读取 Replay；内容中的路径、URL、指令或类似查询文本不能扩大读取范围。
- 排除：不创建、更新或删除文档，不写数据库、索引、缓存、RDF 序列化或其他持久化副作用，不发起网络请求。

## inputs

- `knowledge_root`：已解析且受信的知识根；运行时不在该根之外发现文档。
- `entry_map`：知识根内唯一受信 `knowledge-map.md` 相对路径。只读取其 `Members` 表中明示的 exact member closure；拒绝绝对路径、父级逸出、符号链接、URL 和根外对象。
- `kg_base_iri`：已归一化的 HTTPS base IRI，只用于确定性 mint 图、文档、修订、Claim 和 relation IRI。
- `route_identity`：`sha256:<64-lowercase-hex>` 的可信 Current/Replay route 身份。
- `profile_document_sha256`：本 application profile Owner 的 exact raw-byte SHA-256。
- `replay_version` 与 `snapshot_sha256`：只有显式授权 Replay 时才可提供；Current 与 Replay 分别建图，不合并、不共享证据状态。

## standard_alignment

- 本能力是 OKF application profile over RDF 1.1 abstract data model，以 PROV-O 表示来源/修订特化，以 DC Terms 表示标识、标题、版本、替代名和引用。
- SKOS 只用作概念与标签语义的对齐边界；V2.67 不在未建模 `skos:Concept` 时推断 `skos:related`。alias 是替代标签证据，alias ≠ `owl:sameAs`。
- 本版本不是 RDF concrete syntax parser/serializer，不提供 RDFS/OWL reasoner、SPARQL 或 SHACL 引擎。
- `okf-frontmatter-commonmark-gfm-table-v0.4` 是兼容 parser identity，不是 CommonMark/GFM conformance 声明；实际实现是受控 frontmatter literal、active-Markdown lexical boundary 与首个 simple table 子集。

## obligations_and_outputs

- Markdown 是唯一 SSOT。运行时只在内存中构建 RDF 1.1 数据集投影，图对象和查询结果均不得回写源文档。
- 实体与修订使用稳定 IRI；IRI path segment 先执行 Unicode 17.0 NFC 归一化，再以 UTF-8 字节做严格 percent-encoding，不做语义别名推断。
- 每个 Claim 绑定源文档、修订 digest、标题/锚点、证据摘要与提取状态。直接 triple 用于检索；修订级 RDF reification 用于追溯，不将无证据的同名概念写为 `owl:sameAs`。
- 原生查询仅包含 `observe`、`resolve`、`search`、`neighbors`、`trace` 和 `explain`；receipt 返回 `match_state`、`match_count` 与 `ambiguity_state`，多 Claim 文档的 `explain` 不静默首选，edge 结果绑定 statement、源 Claim 修订与 Evidence。
- SPARQL 和 SHACL 引擎在 V2.67 中的 capability state 均为 `not_implemented`。不得以正则或部分语法伪装标准支持，不得将未运行的形状验证写为 `passed`，也不将这两项能力状态记为质量 finding。
- 可重现的 `graph_input_sha256` 绑定 canonical graph-input manifest，其中包含 profile/parser identity、`kg_base_iri`、route identity、entry-map raw-byte SHA-256 与每个 map member raw-byte SHA-256；它不声称是 normalized RDF dataset digest，也不证明语义正确、宿主独立性或 LLM 永不幻觉。

## observe_only_quality

- `Observe-only`：已实现 detector 覆盖歧义、悬空引用、冲突、重复身份、非法 timestamp 与缺失受控建议元数据；这些图质量问题只记录 finding。V2.67 未实现通用孤立实体 detector，没有 finding 不代表该项已检查通过。
- 质量 finding 时 `run_status=completed`、`current_action=record`，不新增 Knowledge Graph Gate，不改变既有 required/conditional Gate 集，也不阻断 Current route。
- 安全边界拒绝不是质量 finding；路径逸出、符号链接、未授权 Replay、网络或持久化企图在生成成功 receipt 前以带稳定 `code` 的 `GraphSecurityError` fail closed。

## runtime_capability_boundaries

- 编译输入仅来自可信 exact map closure，但 V2.67 未实现独立的总字节、member、Claim 或 relation 数量预算；不得声称已验证资源耗尽防护。
- JSON Schema 约束 query receipt、匹配/歧义状态与 `result_kind`；各 query-kind 的完整结果对象仍由 runtime 与测试合同约束，不声称是完整 RDF/SHACL 形状验证。
- `xsd:dateTimeStamp` 只对严格词法子集生成 typed literal；其他原文保留为 `timestampText` 并记录 `invalid_timestamp`。

## oracles_and_evidence

- 输入文档路径、原始 SHA-256、解析状态、graph-input manifest digest、图统计、finding 列表和查询 evidence chain。
- 文件系统写入计数、数据库/网络调用计数始终为零；超出受信输入集的读取为拒绝证据。
- Current/Replay 隔离测试、IRI 与 reification 测试、歧义不合并测试、查询追溯测试和无持久化副作用测试。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`
- `CONTRACT-APPROVAL-SIDE-EFFECTS-V250`

## dependencies

- `CORE-V250`
- `ROUTING-V250`
- `FUNCTION-REQUIREMENTS-V250`
- `FUNCTION-ARCHITECTURE-IMPLEMENTATION-V250`
- `FUNCTION-TESTING-V250`
- `FUNCTION-AGENT-RUNTIME-V250`

## owned_rule_ids

- `GT250-KG-SSOT`: Markdown 是唯一 SSOT；图是可重建的内存投影，不得持久化。
- `GT250-KG-STANDARDS`: 使用 RDF 1.1 数据模型、稳定 IRI 和修订级 reification；SPARQL/SHACL 能力保持真实的 `not_implemented`。
- `GT250-KG-PROVENANCE`: 每个 Claim 必须可回溯到 exact 文档修订和标题/锚点证据。
- `GT250-KG-AMBIGUITY`: 同名、悬空或冲突概念只记录歧义，不自动合并、不生成无证据 `owl:sameAs`。
- `GT250-KG-OBSERVE`: 质量问题 Observe-only，只记录不强制，不新增 Gate 或修改既有 Gate 结果。
- `GT250-KG-ISOLATION`: Current 与显式 Replay 分别建图，默认闭包不得读取 Legacy。
- `GT250-KG-SECURITY`: 路径、符号链接、网络与持久化边界 fail closed，且不伪装成 Observe-only 质量 finding。
