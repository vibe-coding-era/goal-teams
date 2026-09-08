# V2.68 本地候选输出合同

本文件是显式候选入口的使用合同，不是 Current generation，也不表示 V2.68 已发布或安装。适用实现为 `scripts/v268/output_gateway.py`、`scripts/v268/output_dashboard.py`、`scripts/v268/specification_delivery.py`；外层复用 V2.5 序列化器，工程执行看板复用 V2.67 renderer，轻量文档交付使用 V2.68 新视图；候选呈现适配仅补齐完成态。

## 调用与保证范围

运行环境为 Python 3.11+，工作目录必须是包含上述模块的仓库根。以下命令使用 `python`；本机若默认 Python 版本较低，使用 `/opt/homebrew/bin/python3.11` 替换。`--repo-root .` 绑定当前仓库，不能把其他仓库的记录带入。

CLI 只向 stdout 输出，不隐式保存文件、不发送回复、不安装、不发布。例中的 JSON 输入由调用者用文件编辑工具保存到已授权的本地 `docs/output-example/`；stdout 中需要续用的完整 JSON 也由调用者显式保存。保留 planned 与 observed 两份记录，不覆盖最初基线。示例只说明流程，运行示例仍需相应文档写入授权。

`render` 默认输出 JSON，包含 `ok`、`mode`、`output_contract`、`artifact_delivery`、`body`、`body_sha256`、`errors` 和 `host_enforcement=unavailable`。成功退出码为 0，失败为 1；失败仍返回经外层校验的 `blocked/replan` 正文。选择 `--format markdown` 时仅输出正文。`prepare-specification`、`observe-specification` 成功输出记录 JSON，失败退出 1 并输出诊断 JSON。

发送时使用返回的 `body` 原文，保留字段顺序、轮次、终止字段和 renderer 内容。CLI 展示换行不属于 `body_sha256` 的输入。commentary 不拼入 assistant final；上层要求的 memory citation 或其他 machine trailer 按上层协议附加、校验，不由此网关伪造或验证。当前入口不能检查 Host 最终是否调用它，也不能证明正文未被发送方改写。

所有调用者事实与 reviewer 名称仍由调用者提供。摘要证明本地记录与读取字节的绑定，不能证明外部独立审核或密码学身份。`ok=true` 仅表示本地输出合同通过；它与文档完成、产品开发、Host 拦截、Release、安装分别报告。输出失败而产物能独立读回验证时，`artifact_delivery=completed` 可以保留。

## 请求形状与路由

请求精确包含 `schema_version`、`facts`、`project`、`current_round`、`estimated_total_rounds`、`loop_decision`、`task`、`members`、`result`、`banchmark`、`next_action`、`dashboard`、`specification_record`。不接受额外字段或另一个末字段。网关从 `loop_decision` 生成唯一的 `下一轮 LOOP` 或 `下一个任务`。

`schema_version=goal-teams-output-request-v2.68`；轮次为正整数且当前轮次不大于预计总轮次，布尔值不是轮次；决策为 `continue|replan|stop`。`project`、`task`、`members`、`banchmark`、`next_action` 必须是非空文本。所有 `stop` 输出必须含 `LOOP 改进建议`。

| activity | persistent_write | development_admitted | mode 与 payload |
|---|---|---|---|
| discussion / plan_preview | false | false | 同名 mode；非空 `result`，其他两个 payload 为 null |
| document | true | false | specification_delivery；`result=""`、`dashboard=null`，有效 specification_record |
| development / release | 实际 bool | true | execution；`result=""`、`specification_record=null`，有效 V2.67 dashboard |

`facts` 只能包含表中三个键。未知活动（包括 `specification_only`）和互相矛盾的事实都拒绝。持久 PRD 写入使用 document；纯阅读、评审说明使用 discussion。输出路由本身不授予产品开发或 Release 权限。

[请求 schema](../../../schemas/v2.68/output-request.schema.json) 约束键、类型与各模式的 payload 组合。schema 有意允许 `dashboard`、`specification_record` 的对象内容交给运行时验证，不能凭 schema passed 宣称读回、摘要或审核通过。JSON Schema 的整数语义也不能代替 Python 运行时对整数类型和轮次大小关系的检查。CLI 另行拒绝重复 JSON key、NaN 和超限输入。

## Discussion 可复制示例

将下列 JSON 保存为 `docs/output-example/discussion-request.json`：

```json
{
  "schema_version": "goal-teams-output-request-v2.68",
  "facts": {"activity": "discussion", "persistent_write": false, "development_admitted": false},
  "project": "goal-teams",
  "current_round": 1,
  "estimated_total_rounds": 1,
  "loop_decision": "stop",
  "task": "解释输出校验与系统机制的区别。",
  "members": "Goal Lead。",
  "result": "本地输出校验不能证明 Host 已拦截全部发送。LOOP 改进建议：分别报告本次输出校验和 Host 集成状态。",
  "banchmark": "只读说明；Host 强制发送未验证。",
  "next_action": "本次说明完成。",
  "dashboard": null,
  "specification_record": null
}
```

```bash
python -m scripts.v268.output_gateway render --request docs/output-example/discussion-request.json --repo-root . --format json
```

渲染请求自身的本地传输文件不作为所讨论业务的交付物。若当前任务同时产生对用户交付的文档，应切换 document，不得用 discussion 隐藏写入。

## 文档 prepare → observe → render 示例

### 1. 写入前锁定路径

将以下请求保存为 `docs/output-example/prepare-request.json`。`user_request` 必须摘录当前实际授权；owner 与 reviewer 必须使用本次实际分工名称，不能照抄示例冒充已派发成员。

```json
{
  "record_id": "output-example-document-r1",
  "user_request": "在授权范围内修订输出说明文档。",
  "paths": ["docs/output-example/output-note.md"],
  "owner": "document-owner",
  "reviewer": "document-reviewer"
}
```

```bash
python -m scripts.v268.output_gateway prepare-specification --request docs/output-example/prepare-request.json --repo-root .
```

将成功返回的完整 JSON 保存为 `docs/output-example/planned-record.json`。记录包含实际 canonical `repository_root`，observe 与 validate 拒绝跨仓库复用；不要手工重建或遗漏此绑定字段。目标允许尚不存在；如果存在，prepare 读取其当前摘要作为基线。随后才在授权路径 `docs/output-example/output-note.md` 写入实际文档。不要手工填充摘要或修改 planned 记录。

### 2. 读回真实产物与审核

尚未取得审核结论时，将 `[]` 保存为 `docs/output-example/reviews.json`。执行：

```bash
python -m scripts.v268.output_gateway observe-specification --record docs/output-example/planned-record.json --reviews docs/output-example/reviews.json --reflection '本轮产物已写入，尚缺审核结论；下一步按最终字节复核。' --repo-root .
```

将成功返回的完整 JSON 保存为 `docs/output-example/observed-record.json`。observe 实际读取每个授权文件，记录路径、字节数和 SHA-256，绑定 planned 摘要。无审核的产物为 `partial`；这时可以继续汇报，不能使用 `stop` 声称验收完成。

真实审核由预定 reviewer 阅读最终文件，并返回精确字段 `path`、`sha256`、`reviewer`、`verdict`、`note`。`verdict` 仅可为 `passed|failed`。`sha256` 来自 reviewer 对相同最终字节的独立读回，例如：

```bash
shasum -a 256 docs/output-example/output-note.md
```

`note` 应摘录真实 reviewer 返回的发现与结论，并写明可检索来源（例如本地审核记录路径和段落，或本次成员回复的标识）。不得从摘要自动推导“审核通过”，不得由 owner 代填审核 verdict。现有运行时只校验 reviewer 字段、非空 note 和摘要绑定，不认证 note 来源；来源真实性由调用流程负责，不能称为外部独立证明。

取得审核后，用实际结果替换 reviews 数组，再从原 planned 记录调用 observe。若文件在审核后变化，旧 review 的摘要必须失败，重新审核最终字节后再观察。所有授权产物均有匹配的 passed review 才得到 `completed`；缺审核或 failed 保持 `partial`。

### 3. 将真实 observed 记录嵌入渲染请求

以下命令只读取 observed 文件并向 stdout 打印完整请求，不写文件。把 stdout 保存为 `docs/output-example/document-request.json`。示例使用 `continue`，不会预先声称审核通过：

```bash
python - <<'PY'
import json
from pathlib import Path

record = json.loads(Path("docs/output-example/observed-record.json").read_text())
request = {
    "schema_version": "goal-teams-output-request-v2.68",
    "facts": {"activity": "document", "persistent_write": True, "development_admitted": False},
    "project": "goal-teams",
    "current_round": 1,
    "estimated_total_rounds": 2,
    "loop_decision": "continue",
    "task": "交付输出说明文档。",
    "members": f"Owner：{record['owner']}；Reviewer：{record['reviewer']}。",
    "result": "",
    "banchmark": "文档摘要由观察记录绑定，审核状态由运行时核对；产品开发未准入。",
    "next_action": "核对审核结论与最终字节，满足条件后完成文档交付。",
    "dashboard": None,
    "specification_record": record,
}
print(json.dumps(request, ensure_ascii=False, indent=2))
PY
```

```bash
python -m scripts.v268.output_gateway render --request docs/output-example/document-request.json --repo-root . --format json
```

render 再次读回产物，校验记录摘要与真实文件。轻量文档视图按看板、Context、P/D/C/A 排列，计数来自产物及已绑定的 review；不伪造工程 TaskList、memory 或 Banchmark 文件。这是 V2.68 新文档视图，不是伪造 V2.67 dashboard 的排除参数。

实际全部审核通过后，使用包含 passed reviews 的新 observed 记录构造下一次请求，将轮次设为实际值、决策设为 `stop`，并把 `next_action` 改为实际完成后的说明。文档 renderer 从真实 record 生成完成状态及 `LOOP 改进建议`。如果缺审核、摘要漂移或 record 无效，不能靠修改决策取得成功。

## 工程执行与失败处理

execution 请求使用既有 V2.67 dashboard 对象，必须具备实际 TaskList/state/Evidence/Banchmark/loop-review 与 Context 绑定。网关核对 project、轮次，再调用旧 `validate_dashboard`、`serialize_dashboard`；缺 view、绑定漂移或旧校验失败只返回 `blocked/replan`。不得创建空壳文件或手写摘要来掩盖缺失。

统一入口的完成态呈现：工程看板有已登记任务，所有任务/子任务完成、active_rows为空且无缺口/阻塞，或文档已经真实读回并通过全部绑定复核时，用“本轮全部完成；当前无进行中或剩余任务。”替代空任务表，保留原标题、真实统计、产物/完整任务链接、Context与LOOP。空行本身不是完成证据；未登记、未完成、仍有缺口/阻塞时不显示全部完成，进行中任务行不变。`0/0` 子任务不补造数量。旧直接formatter保留兼容行为；以上修正由 `scripts/v268/output_dashboard.py` 接入候选 `render` 路径，不修改Current或已安装Skill。

外层所有模式最后均经过 `validate_output` 与 `serialize_output`，保留六字段和轮次。检查 `ok` 与退出码后再发送返回正文；诊断结果也应原样使用，修复输入后重跑。若输出错误与产物验收无关，诊断正文保留独立验证为已完成的产物链接，不撤销原交付事实。异常只输出限定错误码，不把任意异常全文或文件正文放入回复。

验证本候选只能声明本地调用链有效。声明 Host 发送必经此入口，必须另有实际 Host hook、发送前阻断及最终发送读回证据；当前入口明确返回 unavailable，不以 Skill 文案或自摘要代替这些事实。
