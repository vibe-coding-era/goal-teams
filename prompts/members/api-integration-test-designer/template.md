# API Integration Test Designer Result Template

成员：<中文展示名>

- 认领任务：<task_id>
- 交接物：`api_integration_test_script`, `api_integration_test_plan`
- 默认栈：Python + pytest
- 实际栈：<language/framework>
- 测试文件：<paths>
- Test-case contract：<paths>; `test_kind=integration|api`
- Input/processing/output bindings：<consumed_input_refs + input_bindings>
- Assertions：<ids/comparators/business observables>
- Validator：`scripts/checks/validate-test-case-contract.py` <passed/failed>
- 覆盖端点：<method path list>
- 数据准备：<fixtures/mocks/env>
- 执行命令：<pytest command>
- 证据路径：<test-plan/progress path>
- 独立检查者：<validator_agent_type>; <validator_member_id>; <validator_run_id>
- 阻塞/风险：<none or details>
