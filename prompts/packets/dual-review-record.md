---
type: Dual Review Record Template
title: Dual Review Record OKF 模板
description: V2.3 review_class、脚本/LLM 复核、结构化 N/A 与 artifact binding 模板。
tags: [goal-teams, okf, dual-review]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Dual Review Record

先从 `harness_contract.task_type`、`required_review_class` 与风险推导最低等级，再选择 `structural | comparison | safety | semantic`。comparison/safety 同时要求脚本和 LLM；structural/semantic 的不适用半边必须使用经独立 reviewer 接受的结构化 N/A。review 文件不能自选更低等级，外层 task_type 不能覆盖 Harness。

```text
Dual Review Record（双重复核记录）:
- schema_version: goal-teams-v2.3
- review_class:
- author_run_id:
- reviewer_run_id:
- artifact:
  - artifact_ref:
  - artifact_sha256:
  - artifact_version:
- v236_acceptance_binding: <V2.36 时为完整 goal-teams-v2.36-acceptance-binding-v1；legacy 省略>
- script_review:
  - reviewer_run_id:
  - tool:
  - status: passed | failed | blocked | not_applicable
  - exit_code:
  - evidence_path:
  - evidence_sha256:
  - evidence_size:
  - artifact_sha256:
  - artifact_version:
  - summary:
  - reason: <仅 not_applicable>
  - reviewer_acceptance: accepted <仅 not_applicable>
- llm_review:
  - reviewer_run_id:
  - status: passed | failed | blocked | not_applicable
  - evidence_path:
  - evidence_sha256:
  - evidence_size:
  - artifact_sha256:
  - artifact_version:
  - summary:
  - reason: <仅 not_applicable>
  - reviewer_acceptance: accepted <仅 not_applicable>
- final_decision:
  - status: pass | fail | blocked
  - reason:
```

规则：

- 当前 review_class 要求的任一复核失败/缺失时，最终结论不能是 `pass`。
- N/A 缺 reason、独立接受者或 artifact binding 时不能绕过。
- author/reviewer `agent_run_id` 必须不同；Evidence path/hash/size 和 artifact version/hash 必须一致。
- V2.36 Review 必须写入完整 `v236_acceptance_binding`；它与 Harness/Audit 相同，并包含 current Evidence registry、ledger、checkpoint、traceability、TaskList、acceptance-input snapshot hashes，以及派生 execution profile/review class/gates/contract digest。每条 current Evidence 另写非循环的 `v236_acceptance_core_binding`，绑定 product/route/target/snapshot/attested registry/trusted release base/profile 与同一执行门契约。
- required `script_review.evidence_path` 指向 JSON：必须含 `schema_version`、`ok`、`error_code`、`exit_code`、`tool`、`reviewer_run_id`、artifact ref/hash/version，以及真实领域工具结果的 provenance。领域工具报告作为被审 artifact；Completion Gate 只用 runtime-locked 安全 verifier 重验 contained artifact hash 与 review binding，不执行记录提供的任意代码，也不把该 hash replay 冒充为原领域工具重跑。
- 上述脚本报告另必须含 `binding_digest`、`domain_execution` 与 `integrity_replay`。两层均记录 `argv/cwd/started_at/ended_at/exit_code/log_path/log_sha256/log_size`；领域层是真实脚本 provenance，完整性层是唯一可重放 verifier，使用不同日志且不得早于领域层结束。`binding_digest` 覆盖领域执行、artifact 与 review identity；任一层缺失、互换、同日志或被修改均失败。
- Harness 最低等级为 comparison 时（即使实际 class 升为 safety），报告固定使用 `comparison_mode=exact_hash_match`、`tool_ref=scripts/review/compare-artifacts.py`、当前 `tool_sha256` 和 `comparison_inputs`。inputs 绑定顶层 actual、独立 regular baseline、各自 hash、registry 中独立 `baseline_approver_run_id` 与不晚于领域执行的 `baseline_approved_at`；actual/baseline 路径/inode 必须不同但内容/hash应相同。domain argv 只能调用 trusted tool 并精确消费两者，log 必须是 exact passed compare report。
- required LLM Evidence 是带 OKF frontmatter 的 Markdown，正文或元数据必须绑定顶层 reviewer run、artifact hash 和 artifact version。
- 可用 `scripts/review/validate-dual-review.py` 校验 JSON 记录。
