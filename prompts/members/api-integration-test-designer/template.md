# API Integration Test Designer Result Template

成员：<中文展示名>

- 认领任务：<task_id>
- 交接物：`api_integration_test_script`, `integration-test-plan`, API `test-case`
- 计划 ID / revision / schema：<plan_id>; <revision>; <schema_version>
- 风险分母：<total/applicable/covered/uncovered>; <risk_id/source/severity/applicability/coverage/case_refs>
- 覆盖率：<covered applicable risks / applicable risks>; blocked/not_run/unavailable 不计 covered
- 默认栈：Python + pytest
- 实际栈：<language/framework>
- 测试文件：<paths>
- 测试文件绑定：<path/sha256/discovery command/discovered node ids>
- Test-case contract：<paths>; `test_kind=integration|api`; <method/path/persona/auth/request/pre-state>
- Input/processing/output bindings：<consumed_input_refs + input_bindings>
- Assertions：<ids/comparators/response business observables/post-state/side effects>
- 高风险场景：<authorization/idempotency/retry/concurrency/compensation/eventual consistency + case refs or N/A reasons>
- 隔离与数据生命周期：<seed/isolation/cleanup/repeatability>
- Validator：<Goal Packet/Harness 指定命令>; <passed/failed>
- 覆盖端点：<method path list>
- 数据准备：<fixtures/mocks/env>
- 执行命令：<pytest command>
- 证据路径：<test-plan/progress path>
- 独立检查者：<validator_agent_type>; <validator_member_id>; <validator_run_id>
- 未覆盖/阻塞风险：<risk ids + reason + owner>; none 仅在 denominator 全覆盖时允许
