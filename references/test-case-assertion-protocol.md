---
type: Goal Teams Test Case Assertion Protocol
title: Goal Teams V2.44 测试计划、用例与执行结果协议
description: 七类测试的风险分母、断言、文件发现、执行结果、重放和独立验证合同。
tags: [goal-teams, v2.44, testing, assertions, api, e2e, replay]
timestamp: 2026-07-23T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.44 测试计划、用例与执行结果协议

仅在测试设计、执行、QA、Review 或 Completion Audit 时加载。V2.44 新 API/E2E 执行 fail closed；V2.35 test-case 基础合同继续兼容，历史 V2.3 fixture 只在明确 legacy 条件下使用，不伪升级。

## 三段机器链

API/E2E 必须连续绑定：

1. `integration-test-plan`：记录 revision、Owner 和不同 member/run 的 QA/Reviewer identity；从 acceptance、API、persona/state、dependency/failure mode、journey 和环境建立风险分母。
2. `test-case`：把 applicable risk 映射到 typed input/processing/output、专用 scenario/action+oracle、test file hash 与 discovery ID；plan validator 必须加载 case artifact，校验 hash、case ID、API/E2E 类型和 risk refs。
3. `test-run-result`：由独立 runner 绑定当前 source/plan/case/identity，记录 attempts、observations、cleanup、artifact hashes 和 replay recipe。

Goal Packet/Harness 注入 exact paths、schema revision 和 validator argv；不得自选旧 validator或用 prose 替代机器 artifact。

计划中每个 `risk_id` 至少记录 `source_ref`、`severity`、`applicability`、`case_refs`、`coverage_state`。覆盖率分母是 applicable risks，不是已有 cases；`blocked|not_run|unavailable|unknown|flaky` 都不算 covered。只有来源证明且由独立 reviewer 接受的 true N/A 才能排除。

## V2.35 四段基础合同

`unit|tdd|integration|e2e|cli|api|fixture` 均要求 schema-valid test-case，包含 schema/case/test kind、acceptance refs、真实 `test_file_refs`，以及非空 `input|processing|expected_output|assertions`。processing 必须有可定位 target、受控 invocation 和 consumed input refs；expected output 绑定业务 observable；prose-only steps 返回 `E_V235_PROCESSING_NOT_EXECUTABLE`。

## 断言限制

只允许 `equals|not_equals|contains|member_of|less_than|less_than_or_equal|greater_than|greater_than_or_equal|json_subset|sequence_equals|sha256_equals|exit_code_equals|status_code_equals`。

- 禁止 eval、表达式、任意 Python/shell、JSONPath 执行、动态 import 和未知 comparator。
- assertion ID 在 case 内唯一；`actual_ref` 只允许 `observed_output.*|artifact.*|execution.*`。
- `expected_ref` 只允许 `expected_output.*`；每条断言恰有一个 `expected_ref|expected_value`。
- ref 禁止绝对路径、`..`、URL、命令替换和未知 observable。
- 每案至少一条非 exit/status 业务断言。

## TDD Red/Green

`test_kind=tdd` 增加 `{"tdd":{"phase":"pre_implementation","expected_initial_state":"red"}}`。Red Evidence 绑定 test hash、pre-implementation ancestor tree/非空 source manifest、领域日志、ledger prefix 与实现事件时序，由独立 designer/runner 产生。implementation-before-red、test drift、领域命令未真实失败或作者自证均关闭实现门。

Green 由不同 runner 在 implementation 后执行，绑定 current test hash、implementation digest、`observed_output` 和逐 assertion result。runner 不得改测试或产品制造 green。

## API typed contract

API case 机器声明：

- request method/path、persona/auth、headers/path/query/body；
- pre-state/fixtures、processing target 与 consumed inputs；
- expected status、response schema/business values、post-state、side effects、cleanup；
- 异步场景的观察窗、最终一致性与补偿 observable。

高风险面覆盖 authorization、idempotency、retry、concurrency、fault injection/compensation、eventual consistency，或逐项提交可审查 N/A。每个 covered risk 绑定唯一可执行 scenario 和唯一 oracle assertion；一个普通请求/断言不得冒充全部风险。status-only 不满足业务断言。

## E2E typed contract

E2E case 机器声明：

- persona、auth/session、initial URL、pre-state/seed、browser/version、viewport；
- ordered actions；每步 selector/target、输入和 checkpoint；
- final DOM、URL、visible/interaction/business state、side effects、cleanup；
- 适用的 session refresh、permission denied、validation、double-click、loading/disabled、network/service failure、retry/recovery、refresh/back/multi-tab。

session/permission/refresh/double-click/error recovery 各自绑定专用 action、checkpoint 和唯一 oracle，不得共用普通断言。截图/trace/video 不能替代 checkpoint 或业务 assertion。

## 文件、哈希与发现

每个 `test_file_ref` 是 protected tree 内相对路径并绑定 sha256；只接受可真实验证的 pytest node/glob，必须执行 collect 并证明 node 存在，其他 discovery kind 禁止。run-result 的 snapshot、attestation、plan/case、config/data、attempt/failure、cleanup/replay 等 artifact refs 都必须存在、是普通文件、无 symlink 祖先且 hash 相等。

## Test Run Result

`test-run-result` 至少绑定：

- result ID/schema、source commit/tree、plan ID/revision/hash、case IDs/hashes；
- runner member/run identity，且与 designer/implementation owner 独立；
- exact argv/cwd、runtime/dependency/config fingerprints、起止时间；
- 首次 attempt 与全部 retries、case/step outcomes、consumed inputs、observed outputs/states、逐 assertion results；validator 按 comparator 重算，拒绝自报 `passed`；
- API response/post-state/side effects 或 E2E DOM/URL/visible/business state/console/network；
- cleanup command/result、artifact 相对 paths+sha256、脱敏 replay recipe。

run validator 加载 plan/case artifacts，校验 plan ID/revision/hash、case IDs/类型/hash 和全部断言。`blocked|not_run|unavailable|unknown|flaky` 均不是 passed/covered；`fail→pass` 仍是 flaky并保留首次失败。cleanup failed 使 run failed/blocked。

## 可重放 Evidence 与独立评审

Evidence 绑定安全 seed/fixture、服务/浏览器配置引用、启动/执行/cleanup exact commands、environment fingerprints 与 artifact hashes；不得包含 secret、生产账号/数据或仅存于易变临时目录的唯一证据。

QA/Reviewer 必须：

1. 从 acceptance、API/persona/state/dependency/failure mode/journey 独立重建 denominator；
2. 运行 Harness 指定 plan/case/result validators；
3. 重算 file hash 并真实 discovery；
4. 核对 first attempt/retries/flake、cleanup 与 artifact bindings；
5. exact replay 至少一个 applicable high-risk case。

任一 required 步骤 failed/blocked，或 N/A 未独立接受，都不得批准。

## 设计、执行与门禁

| 阶段 | 必需输出 |
| --- | --- |
| 通用 Designer | schema-valid case、test refs；TDD 预期 red |
| API/E2E Designer | risk denominator、plan/case/test、file/hash/discovery binding |
| Runner | schema-valid test-run-result、observations、attempts、cleanup、replay |
| QA/Reviewer | denominator diff、independent file/discovery/replay check event |
| Completion Auditor | 只重放 current Evidence 完整性，不执行领域命令 |

V2.35 兼容入口仍可验证 legacy case；V2.44 API/E2E 使用 Harness 指定的三段 validators。验证失败时任务保持 running/failed 或 blocked，实现门关闭。

## Graph-external Completion Audit

release readiness → branch/main fast-forward push → local install → independent post-release task accepted 后，才允许图外只读 Completion Audit。Audit 不得是 required task，不得被 required artifact/evidence 引用；自引用返回 `E_AUDIT_SELF_REFERENCE`。Audit 只重放 current ledger/Harness/Evidence/Review。
