---
type: Architecture Design
title: Goal Teams V2.3 验证运行时架构
description: Schema、ledger、validators、canonical 和 release gate 的目标架构。
tags: [goal-teams, v2.3, architecture]
timestamp: 2026-07-10T15:30:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.3 验证运行时架构

```text
versioned schemas + concrete run identity
  → typed input validation + stable error envelope
  → append-only locked ledger + transition/CAS reducer
  → running/review ledger prefix revision + digest
  → Check expected-domain contract + Run-contained domain execution
  → runtime-locked integrity replay + strict local Evidence + secret/provenance validation
  → append check/review events + checkpoint + deterministic TaskList projection
  → full-object Traceability + conditional Dual Review
  → external, non-self-referential Completion Audit
  → technical RC gate ──→ owner License decision ──→ GA gate
```

- 所有核心枚举来自 versioned schema；`task_state`、`check_state`、`audit_state`、`run_outcome` 不混用。
- validator 默认 fail-closed，所有错误使用统一 JSON envelope；未知字段和不完整对象不通过 ID 自报降级。
- TaskList 是 ledger 投影视图；成员只提交 event/patch，ledger merge owner 通过文件锁与 CAS 单写。
- `accepted` 由 reviewer event、已通过 Check/Run、绑定完整 ancestor commit + 非空 source manifest、且每个消费 task 已在非空 ledger prefix 中 running/review 的 `local_verified` Evidence 共同支撑；合法非 source 提交和后续 append 不使旧 Evidence 失效。
- Check 明确预期领域 argv/cwd；Evidence 的 domain command 必须匹配并处于 Run 包络内。runtime-locked verifier 随后只重验当前 contained artifact、domain record 与 Evidence/Review binding，不执行领域代码，也不冒充原测试重跑。
- comparison Review 绑定 distinct actual/baseline 路径与 hash，并要求领域 tool argv 消费两者；自反比较和无关命令 fail-closed。Traceability 与 Completion Audit 重读完整对象，不接受布尔自报或 Audit 自引用。
- deterministic fixtures 证明协议，隔离 blind-agent eval 证明当前 hash 锁定 CLI 的 local-process behavior；两者证据不可互换，后者不是远程模型的密码学 attestation。
- RC 技术完成与 GA License 授权为不同门禁；仓库 owner 未给出显式决策时 GA 必须 fail-closed。
