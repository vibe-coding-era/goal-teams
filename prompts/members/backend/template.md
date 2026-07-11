# Backend Member Template

```text
成员：<display_name>
范围：<locked_scope>
目标：<goal>
后端合同：<API/CLI/MCP/schema/migration>
后端架构设计：<spec/backend-architecture-design.md>
TDD 单元测试用例：<backend_unit_test_cases path/status>
TDD 单元测试执行：<backend_unit_test_execution path/status>
API 集成测试：<script/plan/execution path/status>
Harness：
- commands:
- artifact_checks:
- evidence_paths:
复核（先选 review_class）：
- review_class: structural | comparison | safety | semantic
- script_checks:
- report_path:
- reviewer:
- review_path:
- not_applicable_half: <reason + reviewer_acceptance=accepted>
ledger event/patch 交接（TaskList 由 reducer 投影）：
- schema_version: goal-teams-v2.3
- task_id:
- title:
- artifact_type: backend_architecture_design | backend_implementation
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
结论：accepted | blocked | deferred | cancelled
```
