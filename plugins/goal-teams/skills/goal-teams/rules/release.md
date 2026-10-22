---
type: Goal Teams Rules
title: 发布规则
---

# 发布规则（用户项目的发版、发布与部署）

## 进入条件

- **GT-REL-ENTRY**：同时满足以下三条才进入发布：
  - 实现范围全部完成（`gt check` 通过）
  - 用户确有发布意图
  - 版本已冻结（tag 或 commit）

  PR、push 或"以后可能发布"都不触发发布流程。
- **GT-REL-AUTH**：发布涉及的外部写入在开始时一次授权；执行前 `gt auth check <动作>` 必须通过。仓库、版本或动作变化时，停下重新确认。

## 冻结版本上的一次性检查

- **GT-REL-REGRESSION**：跑一次全量回归：`gt run - --kind regression -- <命令>`。
- **GT-REL-SECURITY**：做一次安全评审。派 `goal_security`（只读）出结论，二选一记录（都绑定当前源码，人工结论不算）：
  - `gt review @goal --by goal_security --verdict pass|fail --note "..."`
  - `gt run - --kind security -- <扫描命令>`
- **GT-REL-BUILD**：只构建一次，记录产物名、大小和 SHA-256：`gt run - --kind build --artifact <产物> -- <构建命令>`（产物不存在即失败）。发布检查会核对产物仍在、内容未变；回读记录绑定这一组产物，产物变了就都要重来。产物必须是构建生成、未被 git 跟踪、不在代码或测试任务范围里的文件；声明过的产物不算源码，也不算越界改动。其他写进工作树的发布步骤会让门禁过期。除非真的做过第二次构建比对，否则不要宣称"可复现"。
- **GT-REL-FREEZE**：冻结后源码有任何变化，回归、安全和构建记录全部过期，需要重跑。`gt check --release` 会核对它们与当前源码一致；回归和构建必须是命令产生的记录，人工结论不算。

## 执行与回读

- **GT-REL-PLAN**：按 templates/release-plan.md 写发布计划，内容包括：
  - 版本与产物
  - 动作清单
  - 不可逆动作的一行预览
  - 回滚方式
  - 回读步骤
- **GT-REL-ONCE**：不可幂等的动作（tag、release、上传、部署、迁移）按"意图 → 执行一次 → 精确回读 → 对账"的顺序进行。失败后先回读现状再决定，不要盲目重试。
- **GT-REL-READBACK**：外部写入之后，回读目标系统确认结果，例如下载已发布的产物核对摘要、查询 tag 指向的 commit。用 `gt run - --kind release -- <回读命令>` 记录；只能人工确认时用 `--manual` 并附 `--evidence`。本地命令成功不等于远端成功。
- **GT-REL-INSTALL**：安装或升级之后，验证已安装的版本：`gt run - --kind install -- <验证命令>`。
- **GT-REL-HONEST**：发布报告里，构建、上传、发布、安装、回读各写各的真实状态；没做的写 not_run。

## 收尾

- 发布前：`gt check --release` 通过，才执行外部写入。
- 发布后：回读（`gt run - --kind release`）通过，才说"已发布"。发布类目标用 `gt finish` 结束时，gt 会要求回读通过。
- 同时写明仍未验证的轴，例如运行验证和业务验证。
- 发布的产物、命令和回读结果追加到 `.goal-teams/memory.md` 的"决策"一节。
