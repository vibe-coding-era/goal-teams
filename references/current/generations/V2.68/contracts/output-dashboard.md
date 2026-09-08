---
type: Goal Teams Functional Contract
title: Unified Output and Dashboard Contract
description: 定义 V2.68 所有 final 的统一六字段流水线、可信工程看板、轻量文档交付和完成态显示。
tags: [goal-teams, v2.68, output, dashboard, loop]
timestamp: 2026-09-08T00:00:00+08:00
okf_version: "0.1"
---

# Unified Output and Dashboard Contract

- `contract_id`: `CONTRACT-OUTPUT-DASHBOARD-V268`
- `purpose`: 所有 final 通过同一入口验证和序列化；真实产物交付、工程执行、输出合同与 Host 能力分别报告。

## trigger_and_exclusion_facts

- 触发：Goal Lead 或成员产生用户可见 final，包括 discussion、plan_preview、specification_delivery 和 execution。
- 排除：commentary、工具结果和上层 machine trailer 按上层协议处理，不拼入本入口校验的 final 正文。入口不授予开发、发布、安装或发送权限。
- 纯阅读与方案预览不得伪造执行数据；持久交付文档不得伪装为 discussion；代码、配置、测试、发行工作不得借文档分类绕过工程准入。

## inputs

运行环境 Python 3.11+，工作目录为 Skill 包根，调用 `python -m scripts.v268.output_gateway`；`--repo-root` 绑定实际被报告的项目。安装包与项目可不同目录；文档记录绑定 canonical repository_root，不允许等字节跨项目复用。CLI 只输出 stdout，不隐式保存记录、发送回复、安装或发布。调用者使用文件编辑工具在已授权路径保存需要续用的 planned、observed、request 和验证结果。

入口请求精确包含 `schema_version`、`facts`、`project`、`current_round`、`estimated_total_rounds`、`loop_decision`、`task`、`members`、`result`、`banchmark`、`next_action`、`dashboard`、`specification_record`。Schema 为 `schemas/v2.68/output-request.schema.json`；运行时负责记录/读回/轮次交叉约束，schema passed 不等于行为通过。

| activity | persistent_write | development_admitted | mode / payload |
|---|---|---|---|
| discussion / plan_preview | false | false | 同名 mode，非空 result，另外两个 payload 为 null |
| document | true | false | specification_delivery，result 空字符串、dashboard null、有效 specification_record |
| development / release | 实际 bool | true | execution，result 空字符串、specification_record null、有效 V2.67 dashboard |

facts 只能含表中三个键；未知值、额外字段、矛盾事实和 `specification_only` 逃生字段均拒绝。facts 是调用者输入，不是可信授权 Oracle。`schema_version=goal-teams-output-request-v2.68`；轮次为正整数，bool 不作为整数，当前轮不得超过预计总轮。`loop_decision=continue|replan|stop`。

## obligations_and_outputs

- 所有 final 调用 `render`，成功返回的 `body` 原样发送。最后一层始终 `validate_output` → `serialize_output`，保持固定六字段、轮次和唯一终止字段，stop 包含 `LOOP 改进建议`。禁止只校验看板后手写外层。
- `renderer-first`：工程输入由实际 TaskList/state/Evidence/Banchmark/loop-review/Context 组成，先 `validate_dashboard`，再经 V2.68 `serialize_dashboard`，最后校验外层。工程输入保留 exact `schemas/v2.67/output-dashboard.schema.json`；V2.67 renderer 不复制或改写。
- `◆ Goal-Teams 任务执行看板` 显示已完成任务/总任务、已完成子任务/总子任务、真实 TaskList 和状态机链接；表格固定为 `优先级 | 任务 / 子任务 | Subagent 成员 | 进度`，只显示 active/remaining 项；完成明细通过完整 TaskList 查看。`（并行）` 只能由真实 DAG/派发事实证明。
- `◆ Context / Knowledge / Tools` 固定为 `核心规则 | 项目知识 | 代码库 | MCP/CLI/API`；工程 Context 非空项为真实链接，项目知识含实际 `memory.md`，代码库仅显示并链接项目名，不为显示填造占位文件。
- `◆ LOOP：第 <当前轮> 轮 / 预计 <总轮> 轮` 固定四行 `P ｜ 计划 / 下一轮目标`、`D ｜ 执行 / 本轮执行`、`C ｜ 检查 / 执行结果`、`A ｜ 改进 / 调整行动`。工程 C 链接 `Banchmark.md`，A 链接 `loop-review.md`。
- 真实全部完成时，用“本轮全部完成；当前无进行中或剩余任务。”替代空表，保留标题、统计、链接、Context 和 LOOP。工程必须有已登记任务、所有任务/子任务完成、active_rows 空且无缺口/阻塞；文档必须读回并通过所有绑定 review。空行本身不是完成证明，0/0 子任务不补造。
- 失败返回已验证的 blocked/replan 正文、限定错误码与退出码 1；不得用自由手写结果掩盖错误。若文档产物独立完成，保留 `artifact_delivery=completed` 和真实链接，不能把输出失败写成产物撤销。
- 返回值只证明本地校验/序列化；`host_enforcement=unavailable`、`frame_verification=unavailable`。Host 发送强制拦截与最终正文未被改写均需要额外真实证据，不能由 Skill 文案、自摘要、模拟发送或独立 run ID 自证。

## 文档交付调用顺序

纯文档交付无需工程 TaskList、状态机或环境 preflight，但必须在写入前保留 planned 记录，写入后实际读回并取得真实 reviewer note。存在工程开发事实时不能选择此轻量流程。

1. 用真实授权和目标构造 prepare-request：`record_id`、`user_request`、`paths`（唯一项目相对文件路径）、`owner`、`reviewer`。Owner 与 Reviewer 分开，名称必须是实际分工，不能照抄示例。调用：

   `python -m scripts.v268.output_gateway prepare-specification --request <prepare-request.json> --repo-root <project-root>`

   将返回的完整 JSON 保存为 planned-record，不手工重建摘要。尚不存在的目标可以 prepare；已有目标记录真实基线。之后才写入授权文档。

2. Reviewer 读取最终文件，以实际摘要返回精确字段 `path`、`sha256`、`reviewer`、`verdict`（passed/failed）、`note`。note 记录实际判断及可检索来源，不得由 Owner 代填通过。无 review 时保存空数组并保持 partial，不假造审核。

3. 从原 planned 调用：

   `python -m scripts.v268.output_gateway observe-specification --record <planned-record.json> --reviews <reviews.json> --reflection '<实际反思>' --repo-root <project-root>`

   保存返回的完整 observed-record；函数实际读回路径、字节数、摘要并绑定 planned。先前审核后的文件变化必须重新审核；无匹配 passed review 的产物保持 partial。记录摘要是关联证据，不能认证 reviewer 或 note 的外部真实性。

4. 构造完整 render 请求：facts 为 document/true/false，result 为空字符串，dashboard 为 null，将完整 observed-record 放入 specification_record。填写真实项目、轮次、任务、成员、Banchmark、后续动作；未完成使用 continue/replan，不用 stop 冒充验收。调用：

   `python -m scripts.v268.output_gateway render --request <request.json> --repo-root <project-root> --format json`

   render 再次读回，文档视图计数来自真实 artifacts/reviews，按看板 → Context → P/D/C/A 排列。不伪造工程 TaskList/memory/Banchmark 文件；文档交付完成不等于 Development/Release/Install 完成。

## Discussion 最小请求

将本次真实任务内容填入下列精确结构，再保存并 render；此例是说明，不是本次执行 Evidence：

```json
{
  "schema_version": "goal-teams-output-request-v2.68",
  "facts": {"activity": "discussion", "persistent_write": false, "development_admitted": false},
  "project": "goal-teams",
  "current_round": 1,
  "estimated_total_rounds": 1,
  "loop_decision": "stop",
  "task": "解释输出验证边界。",
  "members": "Goal Lead。",
  "result": "本地校验不能证明 Host 强制发送。LOOP 改进建议：分别报告这些状态。",
  "banchmark": "只读说明；没有工程验证。",
  "next_action": "本次说明结束。",
  "dashboard": null,
  "specification_record": null
}
```

`render` 默认输出 JSON，`--format markdown` 只输出正文；成功退出 0、失败退出 1。正文摘要不包含 CLI 展示额外换行。渲染传输请求文件本身不是所讨论业务的交付物；任务同时交付持久文档时仍选择 document。

## oracles_and_evidence

- 工程计数、父子行、ready_layers、LOOP、Evidence 与文件摘要 current 绑定；路径拒绝越界、缺失、目录和符号链接；正文链接来自实际读回。
- 文档 canonical repository_root、planned/observed 摘要、产物字节和实际复核来源；不把调用者自报 reviewer 升格为外部认证。
- JSON 重复键、NaN、超限、类型/跨模式/轮次/绑定漂移的真实负向测试；成功/失败都校验确定性六字段。
- 完成态、进行中态、没有已登记任务、仍有缺口/阻塞与 partial 文档分别测试；输出合同、artifact_delivery 和 Host 状态独立。

## dependencies

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`

## owned_rule_ids

- `GT266-OUTPUT-ORDER`: 结果子视图严格按 Dashboard → Context → LOOP 排序，不增加外层字段。
- `GT266-OUTPUT-TRUTH`: 工程计数、父子展示、并行、链接、Evidence、缺口、阻塞和决策绑定 current receipts；preview/example 不冒充执行。
- `GT266-OUTPUT-CONTEXT`: 工程 Context 非空项是真实链接，项目知识含 memory.md；文档视图不造工程上下文文件。
- `GT266-OUTPUT-PDCA`: LOOP 标题含当前/预计轮次，P/D/C/A 分别承载计划、执行、检查和调整。
- `GT266-OUTPUT-RENDERER-FIRST`: 工程结果只接受 current view 经 renderer，文档结果只接受真实记录经文档 renderer；失败不手写替代。
- `GT268-OUTPUT-GATEWAY`: 所有 final 的最后一层必须由统一入口调用 validate_output 与 serialize_output，原样发送 body。
- `GT268-OUTPUT-DOCUMENT`: 纯文档 delivery 在写入前 prepare、写入后真实复核和 observe，再 render；与工程准入和交付状态正交。
- `GT268-OUTPUT-COMPLETION`: 只有真实全部完成时用完成提示替代空表；保留统计和链接，不补造子任务或成功。
- `GT268-OUTPUT-HOST-BOUNDARY`: CLI 校验不证明 Host 发送拦截/最终 frame；unavailable 保持真实。
