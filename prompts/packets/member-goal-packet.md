---
type: Member Goal Packet Template
title: Member Goal Packet OKF 模板
description: 独立 subagent 成员目标包模板。
tags: [goal-teams, okf, member-goal-packet]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Member Goal Packet

本文件前半部分是可缓存的稳定字段合同；字段顺序、状态语义、Harness/Evidence 边界与输出契约先声明。每次派发的身份、目标、路径、范围和动态引用只写在文末 `Dynamic Instance Tail`，不得插入稳定合同中间。

```text
Member Goal Packet（成员目标包）:
- agent_type: goal_* 配置名或用户指定 skill
- agent_run_id: 每次派发唯一且不可用 display_name 替代
- member_id: 本项目内稳定成员 ID
- display_name: {中文角色}-{具体任务名}；若用户指定 skill，则使用 {skill 名称}-{具体任务名}
- transport_handle: 仅记录宿主返回的路由 handle；不得替代 member_id、display_name 或 agent_run_id
- role: 默认使用中文角色；若用户指定 skill，则使用 skill 名称
- skill_or_subagent:
- version:
- output_dir: GoalTeamsWork-{project_version} 或用户指定目录
- artifact_version:
- version_dir: {output_dir}/versions/{artifact_version}
- tasklist_path: {version_dir}/TaskList.md
- ledger_path: {version_dir}/ledger/events.jsonl
- okf_required: true
- workflow_mode: serial | parallel
- depends_on:
- project_route:
  - schema_version: goal-teams-project-route-v2.35
  - project_size: large | medium | small
  - work_type: feature | bugfix
  - profile / required_review_class
  - gates / specialists / reason_codes
- specialist_capability: {仅专家 packet}
  - coordination_depth: 1
  - can_spawn_subagents: false
  - can_dispatch: false
  - dispatch_owner_agent_type: goal_lead
  - handoff_mode: proposal_only
- budget_gate:
- loop_gate:
  - max_loop_rounds:
  - max_auto_continue_rounds:
  - confirmed_scope:
  - block_completion_when_evidence_missing:
  - stop_when_new_scope:
  - stop_when_safety_gate:
  - stop_when_budget_exceeded:
- conflict_policy:
- user_requested_skill:
- user_requested_subagent:
- lane_or_deliverable:
- handoff_artifacts:
  - schema_version: goal-teams-v2.3
  - task_id
  - title
  - handoff_artifact
  - artifact_type
  - source_ssot: prompts/packets/handoff-artifacts.md
  - owner_agent_type
  - owner_member_id
  - owner_run_id
  - validator_agent_type
  - validator_member_id
  - validator_run_id
  - merge_owner_run_id
  - task_state
  - check_state
  - required_for_done
  - acceptance_blocking
  - attempt_id
  - revision
  - base_revision
  - requirement_refs
  - acceptance_criteria_refs
  - artifact_refs
  - evidence_refs
  - harness_refs
- target_task_ids:
- claimed_tasks:
- goal:
- success_criteria:
- user_stories:
- functional_acceptance_criteria:
- context_refs: {只列本成员所需 path/section/digest}
- fetch_recipe: {缺上下文时由 Lead 按需提供的精确读取步骤；不得扫描整个输出目录}
- required_doc_load: {兼容的人类可读列表；机器路由以 context_refs/fetch_recipe 为准}
- allowed_scope:
- forbidden_scope:
- locked_scope:
- required_tests:
- test_case_contract_refs: {unit|tdd|integration|e2e|cli|api|fixture；V2.35 测试任务必填}
- harness_contract:
  - task_type: {review policy 的权威任务类型}
  - required_review_class: structural | comparison | safety | semantic
  - risk: {可选；只能提升最低等级}
  - checks: {完整 V2.3 Check 对象}
  - runs: {完整 V2.3 Run 对象}
  - commands
  - artifact_checks
  - e2e_checks
  - pixel_diff_checks
  - evidence_paths: {versions/{artifact_version}/evidence/evidence.jsonl 等}
  - failure_report
  - not_applicable_reason
- specialist_contract:
  - priority_level: L0 | L1 | L2
  - lifecycle_state: proposed | reviewed | applied | verified | reverted
  - proposal_ref / proposal_sha256
  - regression_evidence_ref / holdout_evidence_ref
  - specialist_dispatch_request_ref
- dual_review_contract:
  - review_class: {不得低于 harness_contract 推导结果}
  - script_review
  - llm_review
  - final_decision
- benchmark_refs:
- loop_refs:
  - loop_id
  - round
  - prior_decision
  - open_gaps
  - expected_loop_decision_update
- required_independent_validation:
  - documents
  - code
  - test cases
  - handoff artifacts
- required_docs_after_done:
- spec_updates:
  - 需求卡片
  - 用户故事
  - 功能验收标准
  - PRD
  - Requirement Specification Card
  - Page Specification Card
  - Backend Architecture Design
  - Frontend Architecture Design
  - HTML Prototype
  - TaskList
  - test plan
- v2_3_flow:
  - ledger_first: true
  - tasklist_projection_only: true
  - backend_architecture_before_backend_dev: true
  - unit_test_designer: goal_unit_test_designer
  - unit_test_runner: goal_unit_test_runner
  - api_integration_test_designer: goal_api_integration_test_designer
  - api_integration_test_runner: goal_api_integration_test_runner
  - e2e_test_designer: goal_e2e_test_designer
  - e2e_test_runner: goal_e2e_test_runner
- stop_conditions:
- output_contract:
  - Doc Capsules
  - plan
  - Harness Contract
  - revision-bound ledger events/patches
  - 变更文件
  - 运行测试
  - independent validation evidence
  - 更新文档
  - TaskList projection change requests（不得直接编辑）
  - SPEC updates
  - team-state updates
  - completion status
  - 阻塞和风险
```

稳定合同到此结束。`scripts/v23/prompt_compilers.py` 是本模板的 canonical serializer；字段顺序只从 `references/prompt-cache-manifest.json` 的 `artifact_compilers.member_goal_packet` 读取。编译必须对 marker 之前的真实 UTF-8 bytes、canonical dynamic assignment bytes 和最终 combined packet bytes 分别产出 `stable_prefix_sha256`、`dynamic_assignment_sha256`、`combined_packet_sha256`。combined digest 只写 sidecar metadata，避免自引用。旧 packet 可映射到下方动态块，但旧格式缺失的三项 digest 必须标记 `legacy/unavailable`；迁移后的新产物只能对实际新 bytes 重算 digest，不得伪造旧 digest。

<!-- goal-teams-dynamic-tail -->

## Dynamic Instance Tail

以下内容每次派发变化，必须最后追加：

```text
Member Assignment:
- agent_run_id: <unique run id>
- member_id: <stable project member id>
- display_name: <localized role-task name>
- goal: <one bounded objective>
- output_dir: <resolved output root>
- artifact_version: <version>
- target_task_ids: <ledger task ids>
- context_refs: <ordered path/section/digest refs>
- locked_scope: <exact writable or readable scope>
- forbidden_scope: <explicit exclusions>
- required_tests: <commands or contracts>
- harness_contract_ref: <bound Harness>
- validator_run_id: <independent run id>
- dynamic_assignment_sha256: <canonical dynamic block digest>
```
