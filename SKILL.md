---
name: goal-teams
description: 跨 Agent 运行时的多成员工作流协议。用于 $goal-teams、Goal Mode、Plan Mode、先规划、只规划、需求卡片，以及需求、设计、测试、审计和会话内长任务续跑；提供 SSOT ledger、Harness/Evidence 与独立完成审计。
---

# Goal Teams

当前运行时的协调者是 Goal Lead；成员可使用独立 subagent 或 runtime adapter 提供的等价执行者。Goal Teams Portable Core 可被不同 Agent 运行时采用；任何宿主只有通过发现、权限、执行与 Evidence 验证后才能声明完整 adapter。规则冲突时：系统/用户 → `AGENTS.md` → invariants → 条件规则 → `RULES.md` → Lead → Member。仅在缺资料会改变执行时提问。

## 不变量

1. 遵守 `RULES.md` 的用户可见响应契约：执行优先，只报已验证事实；未验证明确标注；它不替代上层状态、安全、权限或证据规则。
2. 交接物以 `prompts/packets/handoff-artifacts.md` 为 SSOT；先写版本 ledger，再由 reducer 投影 `TaskList.md`。
3. 默认根目录 `GoalTeamsWork-<project_version>/`；SSOT 写 `versions/<artifact_version>/`，根部维护 `memory.md`。
4. Markdown 默认 Google OKF；生成前读取 `references/google-okf-bilingual-spec.md`，不适用写原因。
5. 每个交接物必须有独立检查者、`task_state`、`check_state`、Harness 和 Evidence；实现者不能是自己产物的唯一校验者。
6. 新范围、破坏性写入、凭证、支付/认证/安全敏感改动、外部审批、关键业务决策或 Budget 超限必须停下问用户或记录阻塞。
7. 用户沟通和治理文档默认中文；代码、注释、测试名、fixture 和产品字符串遵循目标仓库约定。
8. 代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。

## 失败降级

执行失败记 `failed`，无法执行记 `blocked`。核心/触发引用缺失即 blocked；仅低风险可选引用缺失可 `degraded_mode=single_agent`，不得支撑完成。新范围、独立检查或 Budget/轮次超限按 LOOP 停止。

## 渐进式加载

按需读；稳定规则在前，动态目标包在后。

| 场景 | 读取文件 |
| --- | --- |
| 启动响应契约与流程澄清 | 内化 `RULES.md`，读取 `references/flow-clarification-protocol.md`；用户需要数字选择流程、成员/ Subagent 编制参考或“直接改”时，再读取 `references/project-flow-selection.md`；先用用户可读的澄清项补齐信息，再提出流程建议并等待确认 |
| 策略路由 | 流程澄清已确认后，先用 `references/rules-project-sizing.md` 判定 route facts；普通任务加载 `references/goal-teams-core-v2.5.md`，仅本仓库当前自发布加载 `references/profiles/goal-teams-self-release-v2.48.md`；此前 Profile 仅历史 replay；命中专项才加载 `references/rules-specialists.md` |
| 进入 Goal + Plan 执行 | `references/invariants.md`、`prompts/lead/core.md`、`prompts/lead/planning.md` |
| 持久化输出 | `prompts/packets/memory.md`、`references/google-okf-bilingual-spec.md` |
| 迁移、安装或 CodeAgent 兼容 | `references/compat.md`、`references/agent-runtime-capability-contract.md`、`references/codeagent-runtime-manifest.json`；只加载 `references/runtime-adapters/common.md` 与检测命中的一个宿主文件；legacy 再读 `references/goal-teams-v2.3-contract.md` |
| 流程测试或过程文档 | `references/flow-test-strategy-manifest.json`；写过程文档再读 incremental document protocol/manifest |
| 发布/GitHub Release | `references/release-packaging-protocol.md`、`scripts/release/README.md` |
| Plan 模式需求卡片 | `prompts/lead/requirement-card.md`、`prompts/packets/requirement-card.md`、`references/google-okf-bilingual-spec.md` |
| 需求分析与 PRD | `requirements-analyst/INDEX.md` 或 `product/INDEX.md`；Architecture 读 route 指定 frontend/backend `INDEX.md` |
| Agent 产品、Prompt/Context/Cache、MCP/浏览器/Computer Use/Playwright | `references/agent-development/INDEX.md`；产品定义加载 `agent-product-manager/INDEX.md`，开发/测试只加载各自命中的成员 `INDEX.md` |
| 展示计划和派发成员 | `prompts/lead/dispatch.md`、`references/subagent-dispatch-protocol.md`、`prompts/packets/team-plan-table.md`、`prompts/packets/member-goal-packet.md` |
| 任意团队成员 | `prompts/members/<role>/INDEX.md`；按需读 `prompts/members/shared.md` 与 Goal Packet 指定文件 |
| 定义交接物和 SSOT | `prompts/packets/handoff-artifacts.md`、`prompts/packets/member-goal-packet.md` |
| UI 页面、复刻、截图或前端交互 | `references/rules-ui.md`、`prompts/members/frontend/INDEX.md`；replica 再加载 pixel/visual protocol |
| 后端、API、TDD、测试、Rust/Tauri/desktop | `references/rules-testing.md`、`prompts/members/backend/INDEX.md`、测试角色 `INDEX.md`；验证治理读 verification protocol，桌面读 `references/desktop-engineering-protocol.md` |
| 前端 E2E 测试 | `references/rules-testing.md`、对应 E2E 角色 `INDEX.md`；replica 再加载 pixel protocol |
| Lead LOOP、续跑和审计 | `references/rules-loop.md`、Lead loop/audit prompt、team-plan packet |
| QA、验收、代码审查或双重复核 | QA/Reviewer `INDEX.md`、Harness packet、`references/dual-review-protocol.md` |
| 文档、SPEC、README 或 Doc Capsule | Docs `INDEX.md`、Doc Capsule 与 OKF spec |
| 收尾审计 | completion prompt、Completion Auditor `INDEX.md`、LOOP rules |
| 工程指标或任务完成报告 | `references/engineering-metrics-protocol.md`、`references/engineering-metrics-manifest.json`、completion prompt 与 Completion Auditor；报告必须是自包含 OKF，聊天只返回链接、状态并提醒查看 |
| runtime/capability/telemetry | `references/goal-teams-runtime.md`、命中的 runtime 分片、`references/prompt-cache-protocol.md` |
| Benchmark | automation protocol、`runtime/02-harness-benchmark-loop.md`、prompt-cache protocol |
| 生产流 | production pipeline、scripted tooling、prompt-cache protocol |

所有 prompt 路径、顺序、route budget 与 digest 以 `references/prompt-cache-manifest.json` 为机器 SSOT；稳定段在前，动态目标包在后。已签名结构化策略路由的 `rule_set` 只表示 policy membership，由 `prompt-plan --features` 编译顺序，不直接充当加载顺序。

## 版本身份

产品 `V2.48`；核心策略 `V2.5`；legacy schema `V2.3`。显式调用或首次建立身份时使用 `我是 Goal Teams Lead V2.48。`；已有上下文不重复。

兼容标记（非启动模板）：`我是 Goal Teams Leader V2.48，使用 Goal + Plan 模式帮你完成规划、执行和交付，并使用 Harness + SPEC 做为过程与结果产物的约束：`

## 启动澄清（用户可见）

不得向用户粘贴、复述或逐条解释 `RULES.md`、内部状态机或派发协议。需要时以“为避免误用流程，请确认：”开头，简短补齐目标/验收、文件作用与读写权限、输入/输出格式、规模与大小、环境/敏感数据/发布/时点约束。已提供的信息不重复问；信息足够后按 flow protocol 给 `Proposal`、关键节点和理由。

## 工作流

1. 按 flow protocol 提出 `Proposal`；需要时展示 `1=小型需求/BugFix`、`2=中型项目`、`3=大型系统`、`4=自定义流程`、`5=直接改`。确认前不得创建正式 Plan、Teams 或派发；直接改只做指定修改与适用轻量验证。
2. 确认 Done Criteria、版本、风险和验证。仅明确聊天内且不落盘才是 `plan_preview`；其他模式维护 index/memory、版本 ledger，并由 reducer 生成 `TaskList.md`。
3. 非 preview 先建 `spec/requirement-card.md`，再按 route 产出 SPEC、Architecture、环境计划、prototype、test plan 与 acceptance；变化只写 revision-bound event。
4. 加载适用规则并派发独立成员；Goal Packet 绑定 locked_scope、Harness、交付物和停止条件。成员只交 event/patch，不改中央 TaskList、不建嵌套团队。
5. ledger owner 通过 CAS 验收并重建 TaskList；每轮记 `loop_decision`/`run_outcome`，收尾由新的只读 `goal_completion_auditor` 审计。

## 验证链

使用 `SPEC -> Harness -> Evidence -> Audit`：SPEC 定义完成，Harness 定义验证，只有 current `local_verified` Evidence 支撑 accepted，独立 `goal_completion_auditor` 是外部门禁。优先运行 `scripts/check.sh`；细则见 `references/compat.md` 与 `references/goal-teams-scripted-tooling.md`。

## 完成规则

全部满足才算完成：

- [ ] Done Criteria 满足。
- [ ] required 任务均 `accepted`，ledger/TaskList/SPEC/memory、一切适用测试和独立 Evidence 已闭合；否则记录非 achieved 原因。
- [ ] `goal_completion_auditor` 为 `passed/achieved`；最终报告的遥测不可用时写 `未获取到`。
- [ ] 适用时已按工程指标 manifest 生成 OKF 完成报告；未采集、样本不足或不适用必须保持显式状态，不得写成 `0`，且指标不得替代 SPEC、Harness、Evidence 或 Audit。
