# QA Member Template

```text
成员：<display_name>
被测对象：<artifact/task>
Harness：
- checks:
- commands:
- artifact_checks:
- evidence_paths:
复核（先选 review_class）：
- review_class: structural | comparison | safety | semantic
- script:
- report:
- reviewer:
- findings:
- not_applicable_half: <reason + reviewer_acceptance=accepted>
ledger event/patch 交接（TaskList 由 reducer 投影）：
- schema_version: goal-teams-v2.3
- task_id:
- title:
- artifact_type: test_plan | evidence_record | dual_review_record
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
结论：passed | failed | blocked
```
