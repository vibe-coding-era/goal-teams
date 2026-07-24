# QA Member Template

```text
成员：<display_name>
被测对象：<artifact/task>
Harness：
- checks:
- commands:
- artifact_checks:
- evidence_paths:
- v2_35_route: <project_size/work_type/overrides/specialists>
- test_case_contracts: <validator reports>
- integration_test_plan: <plan id/revision/hash/validator report>
- denominator_recalculation: <source risks/applicable/covered/uncovered/diff from plan>
- coverage_by_risk: <risk_id/case refs/run result/outcome>
- file_hash_discovery_checks: <path/existence/expected+observed sha256/discovery ids/result>
- observed_output_and_assertion_results: <refs>
- test_run_results: <schema/source-plan-case-identity bindings/attempts/cleanup/artifact hashes>
- flake_retry: <policy/first attempt/all retries/fail-to-pass classification>
- replay: <recipe replayed/current result or blocked reason>
- specialist_checks: <security/performance/refactor/sqa evidence or N/A>
- release_audit_boundary: <remote/local/post-release accepted; Audit graph-external>
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
说明：`blocked|not_run|unavailable|unknown|flaky` 不得作为 passed 或 covered。
```
