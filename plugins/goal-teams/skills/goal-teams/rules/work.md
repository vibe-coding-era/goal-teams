---
type: Goal Teams Rules
title: 工作规则
---

# 工作规则（两条路径共用）

gt 校验与判定；这里补充操作要求。

## 真实与证据

- **GT-CORE-TRUTH**：区分观察、推断、计划和已验证结论。not_run、blocked、failed、stale、invalid 都不是 passed。
- **GT-CORE-EVIDENCE**：完成以 gt 回执为准。gt 只证明哪条命令在哪份代码上得到什么结果；命令是否覆盖验收标准由评审人核对。
- **GT-CORE-FIRST-FAILURE**：首个失败保留，重试只追加。命令写错的失败用 `gt retire <R> --reason` 撤销，原因进汇报。
- **GT-CORE-DIRECT**：direct 无需手写计划；第一条 `gt tdd red` / `gt run` / `gt review` 自动建立最小目标、冻结任务图和有限预算。无取证就写 evidence_mode=untracked，不说"达成"。
- **GT-CORE-FINISH**：只有 `gt finish` 通过才说"达成"：它补跑过期证据、运行完成标准的 `--check`，给出 engineering / criteria / achieved 三级结论；`gt check` 是只读版本。
- **GT-CORE-BLOCKED**：缺外部依赖、权限或环境时如实 `gt task block --external`；BLOCKED 是合法结论。

## 范围与授权

- **GT-CORE-SCOPE**：只做锁定范围内的工作，范围外的发现写进总结。新仓库、新外部系统、新动作类别或实质性范围变化先停下说明。
- **GT-CORE-AUTH**：外部写入开始时一次授权（`gt auth grant --actions ... --scope ... --repo <仓库>`），范围内不再问；执行前 `gt auth check <动作>` 核对动作、有效期、仓库，范围文字由你对照。
- **GT-CORE-IRREVERSIBLE**：merge、tag、release、deploy、delete、force-push、数据库写入前给用户一行预览（做什么、在哪里、如何回滚）。
- **GT-CORE-DATA**：DROP、TRUNCATE、无 WHERE 的 DELETE/UPDATE、不可逆迁移只做用户当场批准的那一条；先备份，优先可逆迁移。
- **GT-CORE-SECRETS**：不读取、打印或导出凭证与令牌，不写进命令、日志或产物；不绕过平台保护；沿用仓库现有 remote。

## 评审与验收

- **GT-CORE-INDEPENDENCE**：保证等级：self（`--self`）、correlated_reviewer（另一成员，名字是声明不是身份）、self_reported（转述的用户结论）。高风险、发布或 `require_independent_review` 要 correlated_reviewer 且 `--note` 写明核对了什么。
- **GT-CORE-ACCEPT**：完成标准优先给 `--check` 命令，由 `gt finish` 运行；没有命令的，用户确认后 `gt goal accept --item <C> --result pass|fail --quote "<原话>"`，汇报标明由会话写入。

## TDD 与检查

- **GT-TEST-TDD**：行为变更先 Red 后 Green。`gt tdd red <T> --test <文件> --expect "<失败特征>" -- <命令>` 必须失败（测试读取的数据文件也用 `--test` 绑定）；`gt tdd green <T>` 重跑同一命令，实现必须落在本任务范围里。
- **GT-TEST-RED-STATES**：red_verified（失败原因已核对）才是有效 TDD；red_observed 可先开发，收尾前 `gt tdd confirm <R> --expect "<失败特征>"` 读原始日志核对。命令不存在、超时或直接通过都不是 Red。
- **GT-TEST-IMMUTABLE**：Red 之后改测试文件就是新用例，重新 Red；不为变绿放宽断言。补用例写进新文件，用 affected 记录。
- **GT-TEST-ORACLE**：断言对照业务预期（输入 → 可观察结果）；只看退出码或日志字样不算通过。
- **GT-TEST-DEV**：开发期只有 TDD 和受影响面检查（`gt run <T> --kind affected -- <命令>`）两道门；每个代码任务要有在最终代码上通过的记录，文件再变就 `gt rerun`。没人读取的测试报告用 `--output` 声明或加进 .gitignore；代码或测试读取的生成文件不能声明。
- **GT-TEST-RISKS**：先列风险，每项对应用例或写明"不适用：原因"；未覆盖项保留。
- **GT-TEST-FLAKY**：失败只能由同一命令的通过关闭；同一代码上先失败后通过是不稳定通过，汇报不能只写"通过"。
