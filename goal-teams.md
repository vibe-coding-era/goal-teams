# Goal Teams 用户指定要求（Current V2.67）

本文件记录当前代际的长期用户要求。规范语义由 `references/current/ACTIVE.json` 指向的功能 Owner 文档承载；历史版本只通过 Legacy Replay 查询，不参与 Current 优先级。

## 目标

- 随 LLM/Codex 能力提升，把 Harness 与 LOOP 收敛为薄控制层，保留必要证据、独立校验、范围和外部写入边界。
- 真实清理多历史版本对当前任务的影响：Current、Execution、Replay 分离；默认 route、安装包和 prompt 闭包不包含 Legacy。
- 规则按功能模板组织，测试用例、门禁、合同、Evidence 与 Completion 有单一 Owner，不随产品版本重复复制。
- 先简化复杂度，再逐步删除历史；迁移首轮零删除，Legacy 只保留可复盘 fixture 和显式 runner。

## README 人类维护边界

- 根 `README.md` 与 `README.en.md` 只允许人类更新；AI 不得修改其正文、发行标记或版本说明。
- 版本技术事实、候选状态与发行说明仅记录在 `CHANGELOG.md`、`release/current/` 和正式发行快照中。

## 流程

- 所有非 Discussion、非 `plan_preview` LOOP 的第一轮先建立 TaskList、分配任务并由独立成员检查环境，未闭合前不进入实现。
- Discussion：只讨论，不落工程状态。
- Small：小流程，按实际风险使用 Lite 基线，首轮做独立轻量环境 preflight，可不创建版本开发分支，只做目标相关的 TDD/受影响面检查。
- Medium：首轮由独立 `goal_release_engineer/environment_preflight` 正式检查开发环境；已有 identity 匹配且 current 的环境先复用，否则创建 `develops/v<major.minor>` worktree 与逻辑分支 `develop-v<major.minor>`，并按宿主要求添加 namespace。开发过程只确保 TDD 和增量；所有实现完成且准备 Release 时，才执行全量回归与安全审核。
- Large：环境检查与分支规则同 Medium；开发过程同样只确保 TDD 和增量；最终 Release 才执行全量回归与安全审核，并在 S1 passed/current 后执行 S3。
- 项目规模、风险、任务类型、release intent 和 workflow phase 必须分开记录，不能用单一 Full/Regulated 标签恢复所有历史门禁。
- 当前开发只接纳有明确消费者、可观察验收、锁定范围、已分配预算和固定退出条件的需求。计划冻结后形成不可变 `TaskExactSet` 与无环 DAG；新增/删除任务或改变依赖、消费者、预算必须提升 plan revision 并重算任务数、关键路径和最大并行宽度。
- 外部阻断独立建模，只传播到 DAG 后继闭包，不触发无关内部返工。审计 finding 只有在已复现、属于锁定范围、存在当前消费者且修复预算可用时才进入修复；否则保持 `observed_only|backlog_candidate|blocked`。

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

- Graph Engineering 必须区分静态 TaskExactSet/DAG、实际 scheduler/Host 执行、持久恢复、外部副作用与业务证据；只有 DAG、RDF 或 `ready_layers` 不得宣称 Runtime complete。
- 每轮 LOOP 结束后，或发现问题时，用户当前项目都要生成一次反思并 append 到 `loop-review.md`；反思覆盖 prompt、context、Skill、graph、materials、Harness、Evidence、members、tools、workflow、runtime 与 cost。
- `loop-review.md` 中的改进是项目级 candidate；自动修改全局 Skill、Prompt、权限或发行规则必须另建消费者、TaskExactSet、预算、授权和验证，不得由反思直接生效。
- Harness 只保留高信息密度断言：SPEC/route、输入身份、命令/环境、预期观察、错误码、Evidence freshness 和 Owner/Validator。
- 状态正交：task/check/audit/run/evidence/release/installation 各自记录，不以自然语言“完成”覆盖。
- 输入、代码、测试与结果必须通过 digest、receipt 和 Git baseline 绑定。tracked diff 与 untracked exact-set 由 Git 自动采集，手写变更说明不得替代或掩盖真实差异。
- 首个失败必须保留；修复、重跑和 successor receipt 追加记录，不覆盖历史。
- LOOP 每轮只输出任务、成员、进度、结果、Banchmark，以及按状态二选一的下一轮 LOOP/下一个任务；`进度` 固定反馈 `第 <当前轮> 轮/共 <总轮> 轮`。
- 全部运行结束后，除 Banchmark 报告外，`结果` 还要包含基于本次证据的 `LOOP 改进建议`，可针对 Skill、上下文、资料、Harness 或流程提出方案；确无新增项时明确写明。
- 减少展示推理过程不等于降低模型内部推理；只压缩用户可见噪声。
- 删除每轮固定输出运行身份短指纹的设计；不得增加新顶层字段或用同义字符串恢复。身份只进入机器 receipt 和诊断 Evidence。

## 用户可见执行看板

- 外层六字段 Envelope 保持不变；执行型更新的 `结果` 依次显示 `◆ Goal-Teams 任务执行看板`、`◆ Context / Knowledge / Tools` 和 `◆ LOOP：第 n 轮 / 预计 m 轮`。
- 任务表只显示进行中与剩余的业务父任务/子任务，列为 `优先级 | 任务 / 子任务 | Subagent 成员 | 进度`；完成详情通过完整 TaskList 链接查看。
- 成员后的 `（并行）` 必须来自真实 DAG/派发事实。Context 每个非空项使用真实链接，项目知识固定包含 `memory.md`，代码库只显示工程名，MCP/CLI/API 不得造占位入口。
- LOOP 使用 P/D/C/A 四行：P 为计划/下一轮目标，D 为本轮执行，C 为 Evidence/缺口/阻塞及 `Banchmark.md`，A 为决策及 `loop-review.md`。

## 可预期性原则

- 开发时间开始可预期，是因为范围和预算形成工作量上界，exact-set 与 DAG 使任务数、顺序、依赖和关键路径可计算，无消费者需求不进入本轮，外部阻断不再引发内部反复返工，修复只处理验真且在范围内的问题，每个任务都有固定验证和退出条件。
- 成果质量开始可预期，是因为输入、代码、测试和结果绑定 digest/receipt/Git baseline，真实差异由 Git 自动采集，TDD、固定回归和独立审计形成多层验证，`BLOCKED` 被允许为真实结论，并且工程完成、运行完成与业务验证严格区分。

## Runtime 与可信边界

- Candidate 可由候选外 fresh process 做 cutover/incremental transition，但不得启动正式 S0–S4。
- 合并后必须从 exact released commit/tree 再启动 fresh V2.67 runtime；只有 released transition receipt 可进入 S0。
- 本地宿主适配器最多证明 I1 correlated fresh-process observation；不得冒充独立外部验收、密码学 attestation 或 Provider prompt 签名。
- 若宿主 transition 不可用，记录 `fresh_runtime_transition_unavailable` 和可恢复 checkpoint，不回退旧 V2.48/V2.36 发行门禁，也不重复向用户授权。
