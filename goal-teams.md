# Goal Teams 用户指定要求（Current V2.51）

本文件记录当前代际的长期用户要求。规范语义由 `references/current/ACTIVE.json` 指向的功能 Owner 文档承载；历史版本只通过 Legacy Replay 查询，不参与 Current 优先级。

## 目标

- 随 LLM/Codex 能力提升，把 Harness 与 LOOP 收敛为薄控制层，保留必要证据、独立校验、范围和外部写入边界。
- 真实清理多历史版本对当前任务的影响：Current、Execution、Replay 分离；默认 route、安装包和 prompt 闭包不包含 Legacy。
- 规则按功能模板组织，测试用例、门禁、合同、Evidence 与 Completion 有单一 Owner，不随产品版本重复复制。
- 先简化复杂度，再逐步删除历史；迁移首轮零删除，Legacy 只保留可复盘 fixture 和显式 runner。

## 流程

- Discussion：只讨论，不落工程状态。
- Small：小流程，按实际风险使用 Lite 基线，只做目标相关的 TDD/受影响面检查。
- Medium：开发过程只确保 TDD 和增量；所有实现完成且准备 Release 时，才执行全量回归与安全审核。
- Large：开发过程同样只确保 TDD 和增量；最终 Release 才执行全量回归与安全审核，并在 S1 passed/current 后执行 S3。
- 项目规模、风险、任务类型、release intent 和 workflow phase 必须分开记录，不能用单一 Full/Regulated 标签恢复所有历史门禁。

## 测试合同

- 固定链：`RiskDenominator -> TestCase -> TestRunReceipt -> TestReviewReceipt`。
- TestCase 一经执行即不可变；修改输入、步骤、断言或期望输出必须产生新 ID/digest。
- TDD Red 与 Green 是两个有序 receipt：case/test digest 相同、source digest 不同。只有同一 run_role 内 fail→pass 重试才可标记 flaky。
- Development 与 Release 使用不同 denominator。开发 denominator 中 full/security/S0–S4 明确为 `not_required/not_run`；Release intent 只表示未来计划，不阻塞 development_complete。
- Release denominator 只在实现完成、候选冻结后激活；动态 coverage 只写 ReviewReceipt，不污染 denominator digest。

## 发行简化

1. 完全取消 S2 第二次确定性构建、逐字节复现比较及 S2 安全检查。
2. S2 对每个 exact released asset set 只构建一次并记录 name/size/SHA-256/source identity；不得宣称可复现或 S2 安全通过。
3. 只有 `project_size=large + release_intent=true + S1 passed/current` 执行 S3。Small/Medium 与 Large 非 Release 的 S3 invocation 必须为 0。
4. S4 只保留开始授权校验、远端状态判定、执行/恢复和 exact readback；不再建立二次授权、advance grant 或平行授权账本。
5. Medium/Large 的全量回归和 `release_security_review` 只在最终 Release readiness 执行一次；它们不属于 S2，也不能产生 `s2_security_checks=passed`。
6. workspace/package/release boundary 是 S0–S4 之外的独立门禁，只读运行一次，不得恢复旧 S2 state machine。

## 授权与 GitHub

- 预计存在 commit、SSH push、PR、merge、Actions、tag、Release、安装、更新、回滚、删除或其他外部写入时，在项目最开始一次列出并确认。
- 已确认的仓库、版本、范围、动作类别、身份和停止条件不变时，过程不再询问；发生实质漂移才停止。
- GitHub remote 的 fetch、pull、ls-remote、branch push、tag push 全部使用 SSH，禁止 HTTPS fallback。
- PR、Actions、ruleset、Release 使用已认证 GitHub API/CLI。不得读取、复制、导出凭证或绕过平台保护。

## Harness、Evidence 与 LOOP

- Harness 只保留高信息密度断言：SPEC/route、输入身份、命令/环境、预期观察、错误码、Evidence freshness 和 Owner/Validator。
- 状态正交：task/check/audit/run/evidence/release/installation 各自记录，不以自然语言“完成”覆盖。
- 首个失败必须保留；修复、重跑和 successor receipt 追加记录，不覆盖历史。
- LOOP 每轮只输出任务、成员、进度、结果、Banchmark，以及按状态二选一的下一轮 LOOP/下一个任务；`进度` 固定反馈 `第 <当前轮> 轮/共 <总轮> 轮`。
- 全部运行结束后，除 Banchmark 报告外，`结果` 还要包含基于本次证据的 `LOOP 改进建议`，可针对 Skill、上下文、资料、Harness 或流程提出方案；确无新增项时明确写明。
- 减少展示推理过程不等于降低模型内部推理；只压缩用户可见噪声。

## Runtime 与可信边界

- Candidate 可由候选外 fresh process 做 cutover/incremental transition，但不得启动正式 S0–S4。
- 合并后必须从 exact released commit/tree 再启动 fresh V2.51 runtime；只有 released transition receipt 可进入 S0。
- 本地宿主适配器最多证明 I1 correlated fresh-process observation；不得冒充独立外部验收、密码学 attestation 或 Provider prompt 签名。
- 若宿主 transition 不可用，记录 `fresh_runtime_transition_unavailable` 和可恢复 checkpoint，不回退旧 V2.48/V2.36 发行门禁，也不重复向用户授权。
