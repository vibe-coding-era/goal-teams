---
type: Test Plan
title: Goal Teams V2.3 审计修复测试计划
description: 正向、负向、mutation、迁移和安装生命周期测试计划。
tags: [goal-teams, v2.3, test-plan]
timestamp: 2026-07-10T15:30:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.3 审计修复测试计划

| 测试域 | 必测内容 | Evidence |
| --- | --- | --- |
| State/Ledger | 合法/非法转换、task-local CAS、event digest、重复内容冲突、空任务、单写锁、checkpoint 与 byte-equivalent projection | unittest + JSON report |
| Evidence/Trace | 完整对象、路径、artifact/log/execution-record secret scan、hash、mtime、ancestor commit + tracked source paths/manifest digest、ledger prefix、Check expected domain command、Run 内 domain→integrity→Evidence→引用 event 时间包络、逐 AC 同路径；无关命令、普通 HEAD、untracked/dirty source、portable scope、伪 prefix/证据均失败 | mutation report |
| Review/Audit | Harness-derived review class；domain execution 与 integrity replay 分层；comparison distinct actual/baseline path+hash 及 tool argv binding；author/reviewer 隔离、同 artifact hash、完成谓词与 Audit 自引用 | canonical audit |
| Migration | scan→plan→apply→verify→rollback；dual SSOT、manual review、case、ledger/event/checkpoint/projection；backup mode 与 applied target exact tree；post-apply 漂移拒绝且无写 | temp-dir lifecycle |
| Installer | install/update/post-switch failure/rollback/uninstall；全部 package path ancestor-symlink/nonregular/mode；marker 锁定 prepare→copy TOCTOU 与 stage/live exact manifest | temp CODEX_HOME report |
| Context/UI/Security | 基础自动加载包 ≤12 KiB；路由上下文单列；空 capability fail-closed；original/replica pixel 环境与 baseline approval；HMAC 跨语法稳定；prompt injection | deterministic fixtures |
| Behavior contract | `result=failed`、负分、缺 provenance、无 scorer 或 mock-only 必须失败；只证明 runner/scorer 契约，不计发布通过 | deterministic behavior reports |
| Behavior blind eval | 4 个核心场景 + forged evidence/self-review/telemetry/no-custom-agent/prompt-injection；local-process-attested Codex CLI、installer tracked selection 的 blind-safe 投影、隐藏 typed-JSON scorer、固定 output 重评分、pre/post HEAD/index/status/filesystem digest | persistent blind-agent run directory |
| Release | RC 重算全部技术门禁；License 决策文件缺失时 GA 稳定非零并返回 blocked | release-gate JSON |

## Mutation 不空转约束

每条负向 mutation 必须执行同一临时目录中的两步断言：

1. 变异前的 pristine 副本先通过对应 validator；否则该用例失败，不允许继续把已有失败误报成 mutation 命中。
2. 只修改声明的目标字段，并断言非零退出及预期稳定错误码；仅检查“任意失败”不算覆盖。

## Live closure 时序约束

1. 先 append planned/running/review 与 artifact event，形成非空 prefix。
2. Evidence 写入该 prefix 的 revision/digest；对应 Run 完整包络真实 command、随后独立 integrity replay，再到 Evidence created 与首次引用 event。
3. 再 append check/accepted 与后续任务，旧 Evidence 仍有效；revision 0、非 prefix、错 digest 和错时序逐项 mutation。
4. Completion Audit 在候选收尾时运行；failed/blocked 可驱动 LOOP/停止，只有 passed/achieved 要求 required task 全 accepted。把实际 audit 文件（含自定义名）放入 required/blocking Task 或 Audit Evidence 必须返回 `E_AUDIT_SELF_REFERENCE`。

## Blind eval 隔离约束

- 被测 agent 的工作目录只包含 manifest 允许的 V2.3 skill/runtime 文件和当前场景输入。
- 文件集来自 installer package manifest + Git index 的 blind-safe 投影；未跟踪文件、symlink、non-regular 与 forbidden roots 不进入，persistent stage mutation 必须失败。
- `tests/`、`benchmarks/`、hidden scorer、canonical 预期答案和其他场景不得进入被测目录。
- scorer 位于隔离目录外，严格解析 JSON 类型、枚举、锁定范围和 forbidden keys；无效 JSON hard fail。
- 记录 source commit、index/status/filesystem、staged tracked projection、rubric hash、runner/provider、原始输出、重放 typed score；provider trust 明确为 `local_process_attested`，不宣称远程签名。
- 只有所有 required 场景通过，且源仓库未被修改，才可支撑 Behavior release gate。
