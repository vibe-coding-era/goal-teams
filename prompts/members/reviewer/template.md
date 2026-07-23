# Reviewer Member Template

```text
成员：<display_name>
评审对象：<files/artifacts>
脚本报告：
- path:
- status:
- harness_task_type / required_review_class / derived_minimum:
- domain_execution:
- integrity_replay:
- binding_digest:
LLM 发现：
- severity:
- file:
- issue:
- recommendation:
测试与版本门：
- route/specialists:
- integration_test_plan: <id/revision/hash/validator>
- denominator_recalculation: <source risks/applicable/covered/uncovered/diff>
- test_case_validator / typed fields / observed assertions:
- file_hash_discovery_checks: <path/existence/hash/discovery IDs/result>
- test_run_result: <schema/bindings/attempts/outcomes/cleanup/artifact hashes>
- flake_retry: <first attempt/all retries/classification>
- replay: <selected risk ids/exact recipe/result>
- red-implementation-green timing:
- remote/local/post-release / graph-external Audit:
tasklist 检查建议：
- artifact_type:
- validator_agent_type:
- validator_member_id:
- validator_run_id:
- check_state:
- evidence_path:
结论：approve | reject | blocked
说明：`blocked|not_run|unavailable|unknown|flaky` 不得作为 passed 或 covered。
```
