# Unit Test Designer Result Template

成员：<中文展示名>

- 认领任务：<task_id>
- 交接物：`backend_unit_test_cases`
- 版本子目录：<GoalTeamsWork-project_version/versions/artifact_version>
- 测试文件：<paths>
- Test-case contract：<path>; `test_kind=unit|tdd`
- 四段合同：input=<refs>; processing=<target/invocation>; expected_output=<observables>; assertions=<ids/comparators>
- Validator：`scripts/checks/validate-test-case-contract.py` <passed/failed>
- TDD 绑定：test_sha256 / pre_implementation_tree / expected_initial_state=red
- 覆盖验收标准：<AC ids>
- 预期状态：red | green | blocked
- 命令：<test command>
- 证据路径：<progress/test-plan/report path>
- 需要后端实现承接：<yes/no + notes>
- 独立检查者：<validator_agent_type>; <validator_member_id>; <validator_run_id>
- 阻塞/风险：<none or details>
