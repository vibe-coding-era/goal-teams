# Product Member Template

```text
成员：<display_name>
输入：Requirement Specification Card
输出：PRD / 用户故事 / 功能验收标准 / 原型结构
验收点：
- user_stories:
- functional_acceptance_criteria:
- user_flow:
- boundaries:
- non_goals:
- success_criteria:
复核（先选 review_class）：
- review_class: structural | comparison | safety | semantic
- script_check:
- llm_review:
- not_applicable_half: <reason + reviewer_acceptance=accepted>
ledger event/patch 交接（TaskList 由 reducer 投影）：
- schema_version: goal-teams-v2.3
- task_id:
- title:
- artifact_type: prd
- owner_agent_type:
- owner_member_id:
- owner_run_id:
- validator_agent_type:
- validator_member_id:
- validator_run_id:
- merge_owner_run_id:
- task_state:
- check_state:
- required_for_done:
- acceptance_blocking:
- attempt_id:
- revision:
- base_revision:
- requirement_refs:
- acceptance_criteria_refs:
- artifact_refs:
- evidence_refs:
- harness_refs:
```
