---
type: Goal Teams Test Case Assertion Protocol
title: Goal Teams V2.35 测试用例断言协议
description: 七类测试的输入、处理、输出、断言、TDD 时序和独立执行合同。
tags: [goal-teams, v2.35, testing, assertions, tdd, integration]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.35 测试用例断言协议

本文件仅在测试设计、执行、QA、Review 或 Completion Audit 时按需加载。V2.35 新执行 fail closed；历史 V2.3 fixture 只在明确 legacy 适用条件下保留，不伪升级。

## 适用测试类型

`unit|tdd|integration|e2e|cli|api|fixture` 七类都必须有机器可读 test-case contract，并以 `test_file_refs` 绑定真实测试源。自然语言步骤、命令成功或退出码不能替代业务断言。

## 四段合同

```json
{
  "schema_version": "goal-teams-test-case-v2.35",
  "case_id": "TC-V235-001",
  "test_kind": "unit|tdd|integration|e2e|cli|api|fixture",
  "acceptance_refs": ["ASSERT-V235-001"],
  "test_file_refs": ["tests/example.py"],
  "input": {
    "fixtures": ["tests/fixture.json"],
    "values": {"case_id": "A"},
    "preconditions": ["Architecture accepted"]
  },
  "processing": {
    "kind": "call|command|http|browser|fixture_load",
    "target": "module.target",
    "invocation_ref": "processing.command.argv",
    "command": {"argv": ["python3", "test.py"], "cwd": "."},
    "consumed_input_refs": ["input.values.case_id"]
  },
  "expected_output": {
    "value": {"passed": true},
    "observable_refs": ["observed_output.result.passed"],
    "input_bindings": [
      {"input_ref": "input.values.case_id", "observable_ref": "observed_output.result.case_id"}
    ]
  },
  "assertions": [
    {
      "assertion_id": "A-TC-V235-001-01",
      "actual_ref": "observed_output.result.passed",
      "comparator": "equals",
      "expected_ref": "expected_output.value.passed"
    }
  ]
}
```

`input`、`processing`、`expected_output`、`assertions` 必须是非空结构。processing 必须有可定位 target 和受控 invocation；prose-only steps 返回 `E_V235_PROCESSING_NOT_EXECUTABLE`。

## 受限 Comparator

仅允许：

```text
equals
not_equals
contains
member_of
less_than
less_than_or_equal
greater_than
greater_than_or_equal
json_subset
sequence_equals
sha256_equals
exit_code_equals
status_code_equals
```

- 禁止 eval、模板表达式、任意 Python/shell、JSONPath 执行、动态 import 和未知 comparator。
- assertion ID 在 case 内唯一；`actual_ref` 只允许 `observed_output.*|artifact.*|execution.*`。
- `expected_ref` 只允许 `expected_output.*`；每条断言恰有一个 `expected_ref` 或 `expected_value`。
- ref 禁止绝对路径、`..`、URL、命令替换和未知 observable。
- 每个 case 至少一条非 `exit_code_equals|status_code_equals` 业务断言。

最低错误码：`E_V235_TEST_CASE_REQUIRED`、`E_V235_TEST_CASE_UNKNOWN_FIELD`、`E_V235_INPUT_EMPTY`、`E_V235_PROCESSING_NOT_EXECUTABLE`、`E_V235_EXPECTED_OUTPUT_EMPTY`、`E_V235_ASSERTIONS_EMPTY`、`E_V235_COMPARATOR_UNKNOWN`、`E_V235_ASSERTION_REF`、`E_V235_EXIT_CODE_ONLY`、`E_V235_TDD_BINDING`。

## TDD Red/Green

`test_kind=tdd` 必须增加：

```json
{"tdd": {"phase": "pre_implementation", "expected_initial_state": "red"}}
```

Red Evidence 必须绑定测试 hash、pre-implementation ancestor tree/非空 source manifest、领域命令日志、ledger prefix 与实现事件时序，并由独立 designer/runner 产生。实现事件早于 current red、测试 hash 漂移、领域命令未真实失败或作者自证都关闭 implementation gate。

Green 必须由不同的独立 runner 在 implementation 后执行，记录 current test hash、implementation digest、`observed_output` 和逐 assertion result。runner 不得改测试或产品来制造 green。

## Integration/API/CLI/E2E 比较

- integration/API：`processing.consumed_input_refs` 与 `expected_output.input_bindings` 必须证明输入被处理并映射到业务 observable；至少一条业务输出/状态变化断言。
- CLI：除退出码外比较 stdout/stderr/file/state/hash 等业务 observable。
- E2E：比较可见 DOM、URL、交互状态或视觉/几何 Evidence；`ui=true` 由独立 designer 和 runner 分离执行。
- fixture：比较加载后的值、结构或 sha256，不能只证明文件可打开。

## 设计、执行与门禁

| 阶段 | 责任 | 必需输出 |
| --- | --- | --- |
| Designer | 写测试和 contract，运行 `scripts/checks/validate-test-case-contract.py` | schema-valid case、test refs、预期 red |
| Runner | 执行领域命令，不改测试/实现 | execution record、observed_output、逐 assertion result |
| QA/Reviewer | 检查业务比较、时序、identity、hash 和 Evidence current | independent review/check event |
| Completion Auditor | 只重放 current Evidence 完整性 | 不重跑领域命令，不接受 exit-only |

CLI 兼容入口为 `scripts/validate-test-case-contract.py`；runtime 为 `scripts/v23/goalteams_v23.py validate-test-case <path>`。验证失败时测试任务保持 running/failed 或 blocked，实现门关闭。

## Graph-external Completion Audit

release readiness → branch/main fast-forward push → local install → independent post-release task accepted 后，才允许启动图外只读 Completion Audit。Audit 不得是 required task，不得被 required artifact/evidence 引用；命中自引用返回 `E_AUDIT_SELF_REFERENCE`。Audit 只重放 current ledger/Harness/Evidence/Review，不执行测试领域命令。
