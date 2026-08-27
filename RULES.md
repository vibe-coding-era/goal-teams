# Response Contract V2.66

本契约只约束 Goal Lead 与成员的用户可见输出，不改变上层权限、范围、安全、Harness、Evidence 或完成条件。

## 事实规则

1. 先执行安全且已授权的范围内动作，再汇报已验证结果。
2. 候选、测试、合并、Release、安装和外部验收分开陈述；未运行或不可用必须显式写明。
3. `passed`、`accepted`、`release_ready`、`achieved` 必须绑定 current Evidence；`failed|blocked|not_run|not_required|stale|invalid` 不得包装成成功。
4. 不输出内部推理、隐藏思维链、冗长命令流水或与目标无关的解释；输出可检查的任务、状态、结果、证据摘要和下一动作。
5. `Banchmark` 拼写是固定兼容字段，不得改为其他名称。
6. 每次执行更新的 `进度` 必须包含 `第 <当前轮> 轮/共 <总轮> 轮`，且当前轮不得大于总轮。
7. 终局 `loop_decision=stop` 时，`结果` 除完成事实外必须包含 `LOOP 改进建议`；建议可覆盖 Skill、上下文、资料、Harness 或流程，也可基于证据明确写“暂无新增建议”。
8. 不固定输出运行身份短指纹，也不得以同义额外字段恢复该设计。运行身份只进入机器 receipt 和诊断 Evidence；仅在用户明确询问或漂移诊断必要时，才在既有字段内解释可验证事实。
9. 执行型更新的 `结果` 使用 V2.66 紧凑子视图：`◆ Goal-Teams 任务执行看板` → `◆ Context / Knowledge / Tools` → `◆ LOOP：第 n 轮 / 预计 m 轮`。它们不得提升为外层顶级字段。
10. 看板只显示 active/remaining 父任务与子任务；完成项只通过真实 TaskList 链接查看。`Subagent 成员` 的 `（并行）` 标识必须来自 DAG/派发事实。
11. Context 每个非空项都必须是真实链接；项目知识必须包含当前项目 `memory.md`；代码库只显示工程名；不存在或未读取的 MCP/CLI/API 不得生成占位链接。
12. LOOP 固定四行：`P ｜ 计划 / 下一轮目标`、`D ｜ 执行 / 本轮执行`、`C ｜ 检查 / 执行结果`、`A ｜ 改进 / 调整行动`。C 链接 `Banchmark.md`，A 链接 `loop-review.md`；标题必须包含当前轮次与预计总轮次。
13. 所有任务/子任务计数、并行性、Evidence、缺口、阻塞和决策均来自 current 绑定；preview/example 不得以非零成功数据冒充执行事实。

## 唯一输出 Envelope

所有执行更新与最终答复恰好包含以下五个顶层字段，顺序固定：

1. `任务`
2. `成员`
3. `进度`
4. `结果`
5. `Banchmark`

末尾再恰好二选一：

- `loop_decision=continue|replan`：输出 `下一轮 LOOP`。
- `loop_decision=stop`：输出 `下一个任务`。

禁止同时输出两个末字段，禁止增加“推理过程”等顶层字段。Markdown 可用于字段内容，但不得改变顶层字段数量与名称。

## `结果` 内固定子视图

机器可验证的结构由 `schemas/v2.66/output-dashboard.schema.json` 定义，并由 `scripts/v266/output_dashboard.py` 进行确定性验证和渲染。外层 `任务、成员、进度、结果、Banchmark` 与终止字段合同仍由通用核心负责。
