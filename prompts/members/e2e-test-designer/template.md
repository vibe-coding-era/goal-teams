# E2E Test Designer Result Template

成员：<中文展示名>

- 认领任务：<task_id>
- 交接物：E2E plan section + E2E `test-case` + `e2e_test_cases`
- Plan ID / revision / schema：<plan_id>; <revision>; <schema_version>
- 风险分母：<total/applicable/covered/uncovered>; <risk_id/source/severity/applicability/coverage/case_refs>
- 覆盖率：<covered applicable risks / applicable risks>; blocked/not_run/unavailable 不计 covered
- 前置前端实现：<artifact/status>
- E2E 框架：<Playwright or project framework>
- 用例文件：<paths>
- 测试文件绑定：<path/sha256/discovery command/discovered test ids>
- Test-case contract：<path>; <persona/session/initial URL/pre-state/actions/checkpoints/expected state/cleanup>
- Validator：<Goal Packet/Harness 指定命令>; <passed/failed>
- 覆盖用户路径：<list>
- 覆盖 viewport：<list>
- 会话/权限/恢复场景：<session refresh/denied/double click/network error/recovery + case refs or N/A>
- 组件/交互态断言：<step checkpoints + final DOM/URL/visible/business state>
- 选择器策略：<role/label/test-id; brittle selectors + risks>
- 隔离与数据生命周期：<seed/isolation/cleanup/repeatability>
- 执行命令：<commands>
- 证据目录：<screenshots/traces path>
- 独立检查者：<validator_agent_type>; <validator_member_id>; <validator_run_id>
- 未覆盖/阻塞风险：<risk ids + reason + owner>; none 仅在 denominator 全覆盖时允许
