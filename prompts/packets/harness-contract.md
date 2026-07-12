---
type: Harness Contract Template
title: Harness Contract OKF 模板
description: SPEC -> Harness -> Evidence -> Audit 验证链的 OKF 模板。
tags: [goal-teams, okf, harness]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Harness Contract

Goal Teams 使用 `SPEC -> Harness -> Evidence -> Audit` 的验证链。

`schemas/v2.3/goal-teams.schema.json` 是机器字段 SSOT；本 packet 只把这些字段装配成正常 Goal+Plan 路由可直接使用的 closure packet。不得用自由文本 check 或非空路径代替完整对象。

```text
Harness Contract（验证契约）:
- checks:
- commands:
- artifact_checks:
- tdd_checks:
- api_integration_checks:
- e2e_checks:
- test_case_contracts: <V2.35 unit|tdd|integration|e2e|cli|api|fixture>
- assertion_results: <observed_output + per assertion result>
- specialist_checks: <security|performance|refactor|sqa proposal/Evidence>
- evidence_paths:
- failure_report:
- not_applicable_reason:
```

可选扩展字段：

```text
- pixel_diff_checks:
- approval_gate:
- pipeline_state:
- benchmark_refs:
```

规则：

- Harness 不是新增 runtime 执行能力；它必须表现为 Plan、tasklist、Member Goal Packet、test plan 和 acceptance 中的字段、命令、人工检查、证据路径和失败报告格式。
- 每个实现、文档或测试任务都要写清 Harness 契约；若不适用，必须写 `not_applicable_reason`。
- 后端 Harness 必须能区分 TDD 单元测试用例、单元测试执行、API 集成测试脚本、API 集成测试执行；API 集成测试默认 Python + pytest，替代方案必须说明项目依据。
- 前端 Harness 必须能区分前端实现、E2E 用例生成和 E2E 执行；用例作者和执行者不能是同一唯一 subagent。
- 只引用已有或计划中明确要创建的检查；不要宣称会运行未验证、未授权或不存在的命令。
- 任务没有 Harness 契约、有效 Evidence 或不适用说明时，不能标记为 `accepted`。

## V2.35 Assertion 与 Specialist Harness

- V2.35 test-case 必须通过 `scripts/checks/validate-test-case-contract.py`，包含非空 input/processing/expected_output/assertions、真实 test refs 和至少一个非 exit/status 业务断言。
- TDD Harness 绑定 test hash、pre-implementation tree、ledger 时序、red domain log；green 由不同 runner 记录 observed output 和逐 assertion result。
- integration/API Harness 必须证明 consumed input 与业务 output/state 对应；E2E 绑定 DOM/URL/可见状态，不能只记录命令/截图存在。
- security Harness 记录 code/dependency/secret/injection/ports、授权与 safety review；无新精确授权的外部主动扫描必须 command=null、mutation=0。
- performance Harness 绑定 environment、data scale、argv/cwd、candidate digest 与 current benchmark Evidence。
- refactor Harness 绑定 equivalence、regression、holdout 与 rollback；SQA Harness 绑定 version/index/classification/version directory、sanitized public copy 与 retained private provenance。
- 专家 Harness 只允许 proposal-only；Lead 另派实现/测试。verified 需要不同 run 的 current regression + holdout。

## V2.34 Harness 扩展

实现类 Harness 还必须定义：

```text
- contract_gate:
  - contract_revision / contract_sha256 / assertion_set_sha256
  - independent_review_ref / reviewer_run_id
- architecture_gate:
  - architecture_ref / architecture_sha256 / accepted_event_ref
- environment_gate:
  - development_environment_check_ref / report_sha256
  - workspace_commit / source_manifest_digest / tool_path_version_hashes
  - conclusion: ready | needs_remediation | blocked
  - validator_run_id / evidence_refs
- state_bundle_checks:
  - feature_list.json / progress.md / contract.md / log.md
  - expected_bundle_revision / expected_bundle_digest / ledger_checkpoint
  - marker_last / journal_reconcile / crash_points
- iteration_checks:
  - iteration_9_disposable_candidate_quarantine
  - iteration_11_fail_closed_delivery
- quality_checks:
  - design / originality / craft / functionality: exactly 4 x 0.25
  - independent_reviewer / candidate_digest / evidence_refs
- diagnostic_checks:
  - GTLOG intent_judgment_divergence
  - prompt_patch_regression_and_holdout
  - moving_bottleneck_current_graph
- publication_checks:
  - public_completion_doc / sanitizer / archive_manifest / publish_guard
  - private_provenance_preserved
```

`environment_gate.conclusion` 只有 `ready` 开放实现；`needs_remediation|blocked` 必须持续为缺口。评分检查不得影响原有 test/check/review/audit 完成谓词。公开文档检查不得以删除 ledger/Evidence/review/audit/provenance 为“清洗”方式。

## V2.3 Machine Closure Packet

非 no-write `plan_preview` 的执行按以下顺序落盘：

1. `identity/registry.json`：`schema_version` 与非空 `identities[]`；每个 identity 必须含 `agent_type`、唯一 `agent_run_id`、稳定 `member_id`、`display_name`、`transport_handle`。
2. `ledger/events.jsonl` → `ledger/checkpoint.json` → reducer-generated `TaskList.md`。Task 必须含 `schema_version`、`task_id`、`title`、两类状态、两类 blocking bool、Owner/Validator member+run、`merge_owner_run_id`、requirement/AC refs、attempt/revision、artifact/evidence/harness refs；accepted 另含 `validation_check_id` / `validation_run_id`。
3. `harness/harness.json`：完整 Check 与 Run 对象，不接受 ID-only：

`harness_contract` 是 Completion review policy 的唯一权威输入，必须含：

```text
- task_type: <semantic | structural | comparison | replica | security | external-write | regulated | ...>
- required_review_class: structural | comparison | safety | semantic
- risk: <可选；只允许把最低 review class 提升>
```

外层同名字段不参与判定。`replica/ui-replica/comparison` 的最低等级为 `comparison`；`security/external-write/regulated` 或 high/critical 安全风险的最低等级为 `safety`。兼容关系不是简单数值排序：semantic 与 structural 不能彼此替代；二者可升级为 comparison/safety，comparison 只能升级为 safety，safety 不可降级。

```text
Check:
- schema_version: goal-teams-v2.3
- check_id
- check_state
- required: true | false
- acceptance_blocking: true | false
- acceptance_criteria_refs: [...]
- validator_run_id
- expected_domain_execution:             # required/acceptance-blocking passed Check 必填
  - argv: [...]                           # 与 acceptance Evidence.command.argv 精确一致
  - cwd: ...                              # 与 Evidence.command.cwd 精确一致
- evidence_refs: [...]                 # passed 时非空
- not_applicable_reason + reviewer_run_id  # not_required 时
- waiver_evidence_ref + waiver_reason + waiver_reviewer_run_id # 仅非 required/非阻断 waiver

Run:
- schema_version: goal-teams-v2.3
- run_id
- attempt_id
- check_id
- producer_run_id
- status
- started_at / ended_at
- evidence_refs: [...]                 # passed 时非空并与 Evidence 的 check/run/attempt 一致
- recovery_of_run_id                   # retry 时
```

4. `evidence/evidence.jsonl`：每行是完整、带 kind 的 Evidence；acceptance Evidence 的 `command.argv/cwd` 必须与对应 Check 的 `expected_domain_execution` 精确一致。`command_execution` / `failure_record` 同时包含两层且使用不同日志：`command` 记录真实领域执行及 exact execution record，Completion 不重跑；`integrity_replay` 是唯一可重放的 runtime-locked verifier，精确绑定领域记录、artifact、source/prefix、check/run/attempt/producer。两层必须位于 Run 时间包络内，随后才是 Evidence created 与引用 event。普通 Evidence 另绑定 ancestor commit、source manifest 与非空 ledger prefix；symbolic HEAD 只属于 canonical portable fixture。失败、人工、外部或 unverified 证据永不进入 acceptance registry。所有 artifact/log/record 先做 secret scan/redaction。
5. `harness/traceability.json`：`requirements[]`、`acceptance_criteria[]`、`tasks[]`、`checks[]`、`runs[]`、`evidence[]` 全部使用完整对象；每个 required AC 必须有 Task → passed Check → passed Run → current valid Evidence，orphan/uncovered 阻断完成。
6. `reviews/dual-review.json` 与 `reviews/semantic-review.md`：从 Harness 最低等级选择合法 `review_class`，严格字段见 `prompts/packets/dual-review-record.md`；脚本报告必须把真实 `domain_execution`、独立 `integrity_replay`、`binding_digest`、artifact、Evidence path/hash/size 和具体 reviewer run 闭合绑定。
7. `audit/completion-audit.json`：候选收尾时作为只读外部门禁生成；使用 `prompts/members/completion-auditor/template.md` 从 checkpoint、strict Evidence registry、traceability 与 review 文件重算。failed/blocked 可驱动 LOOP/停止，只有 passed/achieved 要求 required task 全 accepted；不得接受调用方自报布尔值，也不得由 required/blocking task 或本次 audit Evidence 自证。

进入 task accepted 前至少运行相应 V2.3 `validate-identity-registry`、`validate-check`、`validate-run`、带 `--ledger <ledger/events.jsonl>` 的 `validate-evidence-registry`、`validate-traceability` 和 `validate-dual-review`；候选收尾时再运行 `completion-audit` 外部门禁。完整可重放形状见 `examples/canonical-v23/`；该 example 是 fixture，不可把其 ID/hash 当作当前项目证据复制。
