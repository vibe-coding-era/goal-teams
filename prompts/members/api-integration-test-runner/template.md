# API Integration Test Runner Result Template

成员：<中文展示名>

- 认领任务：<task_id>
- 交接物：API `test-run-result`
- Result ID / schema：<run_result_id>; <schema_version>
- Plan/case binding：<plan_id/revision/hash>; <case ids/hashes>
- Source / identity：<commit/tree>; <runner member_id/run_id>; designer/implementation owner 均不同
- 前置单元测试状态：<passed/blocked/failed>
- 文件与发现绑定：<path/expected sha256/observed sha256/discovery command/discovered IDs>
- 执行命令：<commands>
- 测试环境：<local/test/staging/mock + runtime/dependency/config fingerprints>
- 时间：<started_at/finished_at/duration>
- 退出码：<code>
- Consumed input / observed output：<refs/values>
- Assertion results：<case_id/assertion_id/comparator/actual/expected/passed list>
- Post-state / side effects：<structured refs/values>
- 首次执行与 retry：<attempts/reasons/results>; fail→pass 必须 `flaky`
- Run outcome：<passed/failed/blocked/flaky/not_run>; 只有无失败、无 flaky、cleanup passed 才可 passed
- 失败响应：<path or none>
- Cleanup：<command/result/log hash>
- 可重放证据：<argv/cwd/env refs/seed/service config/artifact relative paths+sha256/replay recipe>
- BugFix 任务：<created/not_applicable>
- 证据路径：<report/progress path>
- 独立检查者：<validator_agent_type>; <validator_member_id>; <validator_run_id>
