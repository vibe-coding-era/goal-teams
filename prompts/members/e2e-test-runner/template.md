# E2E Test Runner Result Template

成员：<中文展示名>

- 认领任务：<task_id>
- 交接物：E2E `test-run-result`
- Result ID / schema：<run_result_id>; <schema_version>
- Plan/case binding：<plan_id/revision/hash>; <case ids/hashes>
- Source / identity：<commit/tree>; <runner member_id/run_id>; designer/implementation owner 均不同
- 用例作者：<goal_e2e_test_designer member_id>
- 文件与发现绑定：<path/expected sha256/observed sha256/discovery command/discovered IDs>
- 执行命令：<commands>
- 浏览器/viewport：<name/version/viewport list>
- baseURL：<url>
- 测试环境/时间：<runtime/config fingerprints>; <started_at/finished_at/duration>
- 退出码：<code>
- Actions/checkpoints：<case_id/step/observed DOM-URL-visible-business state/result>
- Assertion results：<case_id/assertion_id/comparator/actual/expected/passed list>
- 首次执行与 retry：<attempts/reasons/results>; fail→pass 必须 `flaky`
- Run outcome：<passed/failed/blocked/flaky/not_run>; 只有无失败、无 flaky、cleanup passed 才可 passed
- 截图/trace/video：<relative paths + sha256>
- console/network 错误：<none or details>
- Cleanup：<command/UI+business reset result/log hash>
- 可重放证据：<argv/cwd/config refs/seed/service+browser versions/artifact hashes/replay recipe>
- BugFix 任务：<created/not_applicable>
- 证据路径：<report/progress path>
- 独立检查者：<validator_agent_type>; <validator_member_id>; <validator_run_id>
