# Goal Teams 运行协议

本文件定义通用 Goal Teams runtime。它不假设业务领域，也不假设项目已经存在 tasklist。

当前 Skill 版本：`V1.9`。版本号必须和仓库根目录 `VERSION`、`SKILL.md` 正文、README 和启动语保持一致。

## 运行形态

Goal Teams = Goal Lead + 独立 subagent 成员。

```text
Goal Lead
  - 每次开始先汇报：我是 Goal Teams Leader V1.9，我会帮你完成以下工作：
  - Plan 模式启动语后立即询问历史文档、历史经验或参考资料输入
  - 默认中文沟通
  - 用简洁、人类友好的方式和用户交流
  - 生成文档、代码注释、测试名称、测试用例说明默认中文
  - 把用户目标转成 Done Criteria
  - 把 SPEC 转成可追溯 Harness 契约和证据要求
  - 判断 Benchmark 是否适用，默认不创建外层评估目录
  - 执行前强制进入 Plan 模式
  - 规划和方案阶段主动澄清
  - 检查 AGENTS.md / agent.md / CLAUDE.md / claude.md
  - 缺少项目指南时使用 references/default-AGENTS.md
  - 写文档前确认版本目录
  - 多文档前先创建 INDEX.md
  - 发现或创建 SPEC 文档
  - 发现或创建 tasklist.md
  - 用 Markdown 持久化过程和结果
  - 为每个生成文档、代码变更、测试用例安排独立校验
  - 用表格提出成员和任务归属
  - 展示 Teams 规划表；默认等待用户确认，直接执行词除外
  - 使用数字选项，方便用户回复 1 / 2 / 3
  - 创建 Member Goal Packet
  - 启动独立 subagents
  - 路由消息和阻塞
  - 整合结果并验证完成状态
  - 看似完成后启动新的 goal_completion_auditor
  - 对已确认范围内的未完成工作自动续跑，不再要求用户确认

Subagent Member
  - 接收一个 Member Goal Packet
  - 使用 <中文角色>-<任务名> 作为运行时 subagent id、member_id 和展示名
  - 默认中文回复
  - 使用用户指定的 skill/subagent；指定 skill 时展示名使用 skill 名称 + 任务名
  - 认领具体任务
  - 只加载必要文档
  - 输出 Doc Capsules
  - 执行自己的目标循环
  - 按 Harness Contract 返回证据、失败报告或不适用原因
  - 报告 complete / blocked / incomplete
  - 不自我批准生成产物

Completion Auditor
  - 在所有计划任务看似完成、延期或阻塞后，以新的只读 subagent 运行
  - 检查 tasklist、progress、acceptance、测试、文档、校验证据、未解决阻塞和剩余风险
  - 输出 complete、auto_continue 或 blocked_needs_user
  - 不编辑文件，不启动嵌套团队
```

每个成员都是独立 subagent。默认情况下，运行时 subagent id、`member_id` 和展示名使用中文角色 + 任务名，例如 `后端-WIKI 列表后端开发`；`role` 字段使用中文角色，例如 `后端`；真实可加载的 subagent 配置名保留在 `skill_or_subagent`，例如 `goal_backend`。如果用户指定某个 skill，则运行时 subagent id、`member_id`、展示名和 `role` 使用 skill 名称 + 任务名，例如 `browser-WIKI 列表页面验证`。

例外：如果用户明确要求 `openspec` 或 `superpower`，Goal Teams 默认只作为 Goal Lead 运行，负责协调、澄清、检查环境、准备索引和 lead 级产物；除非用户确认完整 Goal Teams 执行，否则不启动角色 subagents。

## 强制 Plan 模式

Goal Teams 总是从 Plan 模式开始。直接执行词只跳过确认等待，不跳过规划、风险检查和 `Teams 规划表`。

1. 先说：`我是 Goal Teams Leader V1.9，我会帮你完成以下工作：`，然后用中文简短列出本轮职责。
2. 立即询问历史资料输入：`在开始规划前，有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“没有”。`
3. 如果用户提供历史资料路径、链接或经验要点，先纳入 Plan 的资料输入和假设；如果用户回复“没有”，继续规划；如果用户已明确要求直接执行且未提供历史资料，不因此阻塞，记录为“历史资料：未提供”。
4. 检查项目指南：`AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md`。
5. 如果没有项目指南，加载 `references/default-AGENTS.md` 作为默认指南，并建议复制到项目根目录 `AGENTS.md`。
6. 询问或推断目标版本号；版本目录未确定前，不写过程文档。
7. 目标、范围、验收标准、优先级、约束、用户角色、设计风格、数据合同、风险容忍度或部署目标不清楚时，先澄清。
8. 把问题、回答、假设和决策写入 Markdown，通常是 `.codex/goal-teams/versions/<version>/plan.md`。
9. 创建多个文档前，先创建或更新索引。
10. 发现或创建 SPEC、tasklist 和每个任务的 Harness 契约。
11. 提出成员分工、skill/subagent 分配、任务认领、locked_scope、文档更新、测试 Owner、Harness 证据和完成标准。
12. 标明每个任务的 workflow：串行或并行；串行任务必须列出前置任务，不能让有依赖的成员同时修改共享范围。
13. 为每个生成产物提出独立校验者：文档、代码和测试用例都要覆盖，并说明校验 Harness 或人工检查方式。
14. 展示 `Teams 规划表` 和相关确认表。
15. 默认等待用户确认后，才启动 worker subagents 或编辑实现文件。
16. 如果最新提示词包含 `直接执行`、`直接开始`、`直接做`、`直接改`、`开始执行`、`不用确认`、`无需确认`、`跳过确认`、`按你的方案执行` 等词，展示 Plan 表格后跳过首次等待确认。
17. 如果用户说执行已确认计划，仍要展示 `Teams 规划表` 作为执行计划记录。
18. 需要用户选择时，提供数字选项，例如 `1. 确认并执行`、`2. 调整成员或范围`、`3. 只保留方案不执行`。

范围、成员、skill/subagent、locked_scope、风险或停止条件变化时，必须重新进入 Plan 模式。

直接执行规则：

- 直接执行只跳过 Plan 表格后的确认等待。
- 仍要展示环境准备、SPEC 准备、风险、独立校验和四列 `Teams 规划表`。
- 直接执行时表格标题使用 `执行计划（已按用户要求直接执行）`。
- 不绕过安全边界。涉及新范围、破坏性写入、凭证、支付/认证/安全敏感改动、外部审批或关键业务决策时，必须先问用户。
- 用户只说“计划一下”“给我方案”“先别执行”时，不算直接执行。

澄清规则：

- 每次优先问 1-5 个高价值问题。
- 按主题分组，例如业务目标、范围边界、验收标准、设计风格、数据/接口、发布约束、风险审批。
- 能通过读本地文件回答的问题，先自己查，再决定是否提问。
- 必须带假设继续时，把假设明确写进计划和确认表。
- Goal Lead 消息要简短、自然；说明问题为什么重要，但不要堆术语。
- Plan 阶段的问题如果是选项型，优先使用数字选项。用户回复数字时，映射到对应选项；数字越界时只问一个简短追问。

## 语言与持久化

默认语言是中文：

- 核心提示词：`默认全程中文输出计划、表格、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。`
- 计划、方案、表格、进度、SPEC、tasklist、成员包、评审报告和最终总结使用中文。
- 生成文档、代码注释、面向用户的代码字符串、测试名、测试说明、测试 fixture 和测试用例摘要默认中文。
- 代码标识、命令、日志、路径、API 名称、依赖名和精确引用保持原文。
- 用户明确要求其他语言时，只对指定产物使用对应语言。

成员命名：

- 所有用户可见表格、packet 和 state 中，运行时 subagent id、`member_id` 和展示名必须一致，使用 `<中文角色>-<任务名>`。
- 默认 subagent 成员使用中文角色名作为前缀，例如 `后端-WIKI 列表后端开发`、`前端-WIKI 列表页面开发`、`测试-WIKI 列表验收测试`。
- `role` 字段使用中文角色，例如 `后端`、`前端`、`测试`。
- 用户指定 skill 时，运行时 subagent id、`member_id`、展示名和 `role` 都使用 skill 名称作为前缀，例如 `browser-WIKI 列表页面验证`、`lark-doc-验收文档创建`。
- 避免只有角色或过泛名字，例如 `后端`、`测试`、`接口联调`。
- 技术 subagent ID 和 skill 名称必须在 `skill_or_subagent` 或机器字段中保持原文。

优先使用 Markdown 作为人类可读记录：

```text
.codex/goal-teams/
  INDEX.md              # 跨版本总索引
  versions/<version>/
    INDEX.md            # 当前版本文档索引，多文档前先建
    plan.md             # 澄清、回答、假设、确认计划
    progress.md         # 每轮进度、阻塞、下一步
    decisions.md        # 决策、原因、审批记录
    tasklist.md         # 成员认领、任务状态、验收、验证
    goal-packet.md      # 团队级目标包
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
    harness.yaml          # 可选机器可读 Harness 契约
    evidence.jsonl        # 可选追加式证据日志
    pipeline-state.json   # 可选流水线状态快照
```

JSON/JSONL 只作为机器可读状态；重要结果要同步写回 Markdown。

默认指南模板：

- 没有 `AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md` 时，使用 `references/default-AGENTS.md`。
- 对用户说明：“我没有看到项目指南文件，会先按默认 AGENTS 模板执行；也建议把它保存为项目根目录的 `AGENTS.md`。”
- 用户同意时，从 `references/default-AGENTS.md` 创建项目根目录 `AGENTS.md`。
- 生成的 `AGENTS.md` 内容保持中文。

版本目录规则：

- Goal Teams 产生的过程和结果文档都必须放进版本目录，通常是 `.codex/goal-teams/versions/<version>/`。
- 用户给 release 名而非语义版本时，转成文件系统安全目录名，例如 `V3.0`、`vNext`、`2026-Q2`。
- 版本目录外只保留跨版本索引和必要机器状态。
- 多文档前先创建或更新 `.codex/goal-teams/INDEX.md` 和 `.codex/goal-teams/versions/<version>/INDEX.md`。

索引模板：

```md
# Goal Teams Index

| 文档 | 版本 | Owner | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `versions/V3.0/spec/requirement-spec-card.md` | V3.0 | 需求分析师 | planning | 人类友好的需求规格卡 |
```

## SPEC 契约

Goal Teams 是 SPEC 驱动。缺少 SPEC 时，应先创建或放入 tasklist，再进入实现。

固定术语：

- 人类友好的需求摘要 = `Requirement Specification Card`。
- 需求 = `PRD`。
- 设计 = `Architecture Design`。
- UI/页面/工作流设计 = `HTML Prototype`。
- 开发执行 = `tasklist.md`。
- 测试 = 独立 subagent 或用户指定 testing skill/subagent。

仍可读取旧的非版本化文件：

```text
.codex/goal-teams/spec/
  PRD.md
  architecture-design.md
  HTML-prototype.html
  test-plan.md
  acceptance.md
.codex/goal-teams/tasklist.md
```

活跃项目使用版本化布局：

```text
.codex/goal-teams/versions/<version>/spec/
  requirement-spec-card.md
  PRD.md
  architecture-design.md
  HTML-prototype.html
  test-plan.md
  acceptance.md
.codex/goal-teams/versions/<version>/tasklist.md
```

需求分析流程：

1. `goal_requirements_analyst` 用中文和用户交流，并提出聚焦问题。
2. 可在有用时使用网络搜索、computer use、browser 或 Chrome 获取市场、竞品、政策、流程或领域上下文。
3. 先创建 `requirement-spec-card.md`，控制在约两页内。
4. 规格卡必须覆盖核心目标、重要性、关键业务功能结构、主流程、边界、非目标和开放问题。
5. PRD 从已批准的规格卡生成，不从零散对话直接生成。

如果用户提供 `design.md`，它是架构/原型工作的风格来源：

- 创建或更新 Architecture Design / HTML Prototype 前先读 `design.md`。
- 尽量沿用其标题、术语、密度和产物风格。
- 如与用户目标冲突，先确认或记录阻塞。

SPEC 准备度表：

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |
| Requirement Specification Card | 是/否 | 创建/更新/跳过 | goal_requirements_analyst | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` |
| PRD | 是/否 | 创建/更新/跳过 | goal_product | `.codex/goal-teams/versions/<version>/spec/PRD.md` |
| Architecture Design | 是/否 | 创建/更新/跳过 | goal_backend 或 goal_product | `.codex/goal-teams/versions/<version>/spec/architecture-design.md` |
| HTML Prototype | 是/否/不适用 | 创建/更新/跳过 | goal_frontend | `.codex/goal-teams/versions/<version>/spec/HTML-prototype.html` |
| Test Plan | 是/否 | 创建/更新/跳过 | goal_qa | `.codex/goal-teams/versions/<version>/spec/test-plan.md` |
| Acceptance | 是/否 | 创建/更新/跳过 | goal_docs | `.codex/goal-teams/versions/<version>/spec/acceptance.md` |

独立校验表：

| 产物 | 作者成员 | 校验成员/Skill | 方法 | 证据 |
| --- | --- | --- | --- | --- |
| `spec/PRD.md` | 产品-WIKI 列表 PRD | 评审-WIKI 列表 PRD 校验 | 清单审查 | `progress.md` 行 |
| `src/api/order.ts` | 后端-订单接口 | 测试-接口行为测试 | 定向测试 + 代码审查 | 命令输出 |
| `tests/order.test.ts` | 测试-订单规则测试 | 评审-测试有效性校验 | 断言审查 | 评审记录 |

## Harness、Benchmark 与 Loop 契约

Goal Teams 使用 `SPEC -> Harness -> Evidence -> Audit` 作为验证链。这里的 `Harness` 是验证契约和模板字段，不是新的 runtime 执行器；它可以指向已有命令、计划中要创建的测试、人工检查清单、截图、日志、CI 结果或外部评估脚本，但不能宣称会运行未验证、未授权或不存在的能力。

定义：

| 概念 | 含义 | Goal Teams 产物 |
| --- | --- | --- |
| `SPEC` | 定义什么算完成 | Requirement Specification Card、PRD、Architecture Design、test plan、acceptance、tasklist |
| `Harness` | 定义怎么证明完成 | Plan、tasklist、Member Goal Packet、test plan、acceptance 中的验证契约 |
| `Evidence` | 记录可追溯证据 | `progress.md`、`acceptance.md`、`evidence.jsonl`、命令输出、截图、人工检查 |
| `Pipeline` | 记录研发/发布状态 | `pipeline-state.json`、Release Gate、Observe、Promote/Rollback 记录 |
| `Benchmark` | 在多任务上评估工作流是否稳定 | `benchmarks/` 任务集、run matrix、scorecard、failure taxonomy |
| `Loop` | 持续推进和改进机制 | 成员 Loop、Lead Loop、Skill Improvement Loop |

Harness Contract 模板：

```text
Harness Contract（验证契约）:
- purpose:
- checks:
- commands:
- artifact_checks:
- evidence_paths:
- failure_report:
  - command:
  - failing_check:
  - likely_cause:
  - next_verification:
- not_applicable_reason:
```

Harness 准备度表：

| 任务 | Harness 类型 | 检查/命令 | 证据位置 | Owner | 状态 |
| --- | --- | --- | --- | --- | --- |
| GT-003 | automated + manual | `npm test -- wiki` + API 合同检查 | `progress.md` / CI 输出 | 测试-WIKI 列表验收测试 | planned |

按任务类型选择 Harness：

| 任务类型 | 常见 Harness |
| --- | --- |
| 前端 | Playwright、截图、console error、桌面/移动 viewport、文本溢出或遮挡检查 |
| 后端 | API 边界、权限、异常路径、数据兼容性、迁移/回滚检查 |
| 文档 | 结构完整性、链接、术语、版本一致性、README/CHANGELOG 同步检查 |
| 测试用例 | 断言有效性、失败模式覆盖、fixture 可复现、不会只验证 happy path |
| 评审/审计 | diff 审查、tasklist 状态、acceptance 证据、阻塞/风险清单 |

规则：

- 启动实现成员前，Plan 或 tasklist 必须给每个认领任务写出 Harness Contract；不适用时写 `not_applicable_reason`。
- 成员完成时必须返回 Harness 证据或跳过原因；只有 Lead 和独立校验者都能追溯证据时，任务才可标记为 `done`。
- 失败时按 Harness Contract 的 `failure_report` 格式报告，不用笼统写“测试失败”。
- Harness 可以成为 Benchmark 的一部分，但普通 Goal Teams 任务不自动创建 benchmark。

机器可读协议是 V1.8 的可选数据合同，详见 `references/goal-teams-automation-protocol.md`。它不代表已有 runner、CI/CD、生产接入或真实外部审批系统。

| Artifact | 作用 | 建议位置 |
| --- | --- | --- |
| `harness.yaml` | 单任务或单版本的验证契约 | `.codex/goal-teams/versions/<version>/harness.yaml` |
| `evidence.jsonl` | 追加式证据日志 | `.codex/goal-teams/versions/<version>/evidence.jsonl` |
| `pipeline-state.json` | 研发/门禁状态快照 | `.codex/goal-teams/versions/<version>/pipeline-state.json` |
| `failure_report` | 失败对象 | 嵌入 evidence 或 pipeline 状态 |
| `approval_gate` | 人工或策略审批门对象 | 嵌入 pipeline 状态 |

生产流协议是 V1.9 的发布门禁模板，详见 `references/goal-teams-production-pipeline.md`。它使用 `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback` 组织候选产物、证据和审批。凭证、真实部署、破坏性操作、生产回滚、auth/payment/refund/权限和安全敏感模块必须人工审批或由外部系统授权；Goal Teams 不能自动绕过这些 safety gate。

Benchmark 是外层评估目录与任务集，用于比较 Goal Teams、single agent、不同 skill 版本或 prompt 的稳定性。默认目录建议：

```text
benchmarks/
  README.md
  tasks/
    GT-BENCH-001/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
    GT-BENCH-002/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
  runs/
    <date>-<task>-<mode>/
      report.md
      artifacts/
```

Benchmark 任务包最少包含：

- `task.md` 或 `SPEC.md`：目标、成功标准、非目标、禁止行为、可见/隐藏验收。
- Harness：环境准备、可见测试、评分/检查、日志和证据收集。
- `scoring.md`：分值、严重度、失败分类、人工介入记录和成本指标。
- metadata（可选）：任务类型、难度、允许工具、时间/token/费用预算、基线信息。
- 运行记录：模型/skill/prompt 版本、项目 commit、工具版本、联网/权限、运行日期、结果。
- 失败分类：需求误解、上下文没读全、定位失败、工具失败、环境失败、实现错误、测试不足、过度修改、引入回归、证据缺失、权限/安全违规、长任务漂移、多 agent 协调失败。

普通 Goal Teams 运行只在以下情况创建或更新 `benchmarks/`：

- 用户明确要求构建 benchmark、运行 benchmark 或比较 workflow。
- Lead 已在 `Teams 规划表` 中确认 Benchmark 任务和 Owner。
- Skill Improvement 任务明确以 Benchmark 失败分类为输入。

Loop 分三层：

| Loop | 责任 | 状态流 | 产物 |
| --- | --- | --- | --- |
| 成员 Loop | 单个 subagent 完成认领切片 | `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue` | Doc Capsules、Harness 证据、tasklist 更新 |
| Lead Loop | 团队协调和完成闭环 | `Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue` | `plan.md`、`progress.md`、team-state、续跑计划 |
| Skill Improvement Loop | 维护 skill 规则和发布质量 | `Run/Eval -> Classify -> Update Rules/Templates -> Validate -> Release Notes` | `goal-teams.md`、`SKILL.md`、runtime、subagents、README/CHANGELOG、校验结果 |

三层 Loop 的边界：

- 成员不能启动嵌套团队，不能越过自己的 `locked_scope`。
- Lead 负责把成员结果整合到 tasklist、acceptance、progress 和最终审计；不能用自己的感觉替代独立校验证据。
- Skill Improvement 不在普通用户任务中自动发生；只有用户明确要求改 skill 或 benchmark/复盘任务进入该层。

## 任务清单发现与创建（Tasklist）

发现顺序：

1. 用户提到的 tasklist 路径。
2. 项目本地候选：`TASKLIST.md`、`tasklist.md`、`TODO.md`、`docs/*task*`、`docs/*plan*`。
3. Goal Teams 版本路径：`.codex/goal-teams/versions/<version>/tasklist.md`。
4. 旧 runtime 路径：`.codex/goal-teams/tasklist.md`。
5. 如果没有相关 tasklist，创建 `.codex/goal-teams/versions/<version>/tasklist.md`。

生成 tasklist 时，必须从一开始包含 Owner 和可确认结构：

```md
# Goal Teams Tasklist

Goal: <用户目标>
Status: planning

## 成员归属

| Task ID | 成员 | Skill/Subagent | Workflow | 前置任务 | 认领者 | 状态 | Locked Scope | 交付物 | 完成标准 | Harness | 验证 | Docs/SPEC 更新 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 需求分析-WIKI 列表需求澄清 | goal_requirements_analyst | 串行 | - | unclaimed | pending | .codex/goal-teams/versions/<version>/spec/ | 需求规格卡 | 用户确认 | 文档结构/边界清单 | 评审-WIKI 列表需求校验 | 需求规格卡 + tasklist |

## 任务

| Task ID | 标题 | Owner | Workflow | 前置任务 | 状态 | Harness | 停止条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 澄清需求和验收标准 | goal_requirements_analyst | 串行 | - | pending | 文档清单审查 | 缺少业务决策 |

## 决策与阻塞

| ID | 类型 | Owner | 状态 | 摘要 | 需要决策 |
| --- | --- | --- | --- | --- | --- |
```

纯 checkbox tasklist 可以用于人类可读性，但表格更能保留 Owner 和完成状态。

## Markdown 持久化模板

追加到 `.codex/goal-teams/versions/<version>/plan.md`：

```md
# Goal Teams Plan

## 用户目标

<中文描述>

## 环境检查

| 项目 | 结果 | 建议 |
| --- | --- | --- |
| AGENTS/agent 指南 | found/missing | 如缺失，建议补充团队规则和项目约束 |
| CLAUDE 指南 | found/missing | 如缺失，建议补充跨工具协作约定 |
| 默认指南 | active/not needed | 缺失项目指南时使用 `references/default-AGENTS.md` |
| 版本目录 | <version> | 文档写入 `.codex/goal-teams/versions/<version>/` |

## 澄清问题

| 问题 | 用户回答 | 影响 | 状态 |
| --- | --- | --- | --- |

## 当前假设

| 假设 | 影响 | 验证方式 | 是否需确认 |
| --- | --- | --- | --- |

## 确认后的计划

| 阶段 | 输出 | Owner | 验收标准 | 风险 |
| --- | --- | --- | --- | --- |

## Harness / Benchmark

| 任务 | Harness 契约 | 证据位置 | Benchmark 是否适用 | 状态 |
| --- | --- | --- | --- | --- |
```

追加到 `.codex/goal-teams/versions/<version>/progress.md`：

```md
# Goal Teams Progress

## <YYYY-MM-DD HH:mm> 执行轮次

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |

## 阻塞与决策

| 阻塞/决策 | 成员 | 影响 | 需要用户确认 | 建议 |
| --- | --- | --- | --- | --- |
```

追加到 `.codex/goal-teams/versions/<version>/decisions.md`：

```md
# Goal Teams Decisions

| 时间 | 决策 | 原因 | 决策人 | 影响范围 |
| --- | --- | --- | --- | --- |
```

## 确认表

启动 worker subagents 或编辑实现文件前，先展示 `Teams 规划表`。除非有直接执行词或已确认计划，否则请求用户确认。

### Teams 规划表

表格只用四个合并显示列，但底层逻辑字段必须保留：成员、skill/subagent、目标切片、认领任务、workflow、前置任务、locked_scope、交付物、完成标准、Harness、docs/tasklist 更新、测试 Owner、校验者。

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Skill/Subagent：`goal_backend` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行<br>前置任务：GT-001, GT-002<br>锁定范围：`src/api/wiki/` | 交付物：后端实现<br>完成标准：API 合同测试通过<br>Harness：API 合同测试 + 回归测试<br>文档/tasklist：Architecture Design + tasklist.md | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表代码审查 |
| 成员：browser-WIKI 列表页面验证<br>Skill/Subagent：`browser` skill | 目标切片：页面验证<br>认领任务：GT-004<br>Workflow：并行<br>前置任务：GT-003<br>锁定范围：`src/ui/wiki/` | 交付物：页面截图和控制台检查<br>完成标准：桌面/移动截图通过<br>Harness：截图 + console error + viewport 检查<br>文档/tasklist：HTML Prototype + tasklist.md | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表体验审查 |

### SPEC 准备度

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |
| Requirement Specification Card | no | create | 需求分析师 | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` |
| PRD | no | create | 产品/需求 | `.codex/goal-teams/versions/<version>/spec/PRD.md` |

### Harness 准备度

| 任务 | Harness 类型 | 检查/命令 | 证据位置 | Owner | 状态 |
| --- | --- | --- | --- | --- | --- |
| GT-003 | automated | API 合同测试 + 定向回归 | `progress.md` | 测试-WIKI 列表验收测试 | planned |

### Benchmark 适用性

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 是否创建/更新 `benchmarks/` | yes/no/not applicable | 只有用户要求或计划确认时启用 |
| Benchmark 任务来源 | tasklist/SPEC/历史 issue/not applicable | 不适用时写明原因 |
| 失败分类记录 | planned/not applicable | 使用 Benchmark 时必须记录 |

### 环境准备度

| 项目 | 状态 | 建议 |
| --- | --- | --- |
| AGENTS/agent 指南 | found/missing | 如缺失，建议创建 `AGENTS.md` 或 `agent.md` |
| CLAUDE 指南 | found/missing | 如缺失，建议创建 `CLAUDE.md` 或 `claude.md` |
| 默认指南 | active/not needed | 如缺失项目指南，使用 `references/default-AGENTS.md` |
| 版本目录 | ready/pending | `.codex/goal-teams/versions/<version>/` |
| 文档索引 | ready/pending | `.codex/goal-teams/INDEX.md` + `versions/<version>/INDEX.md` |

### Teams 规划表（简版）

仅在需要短表时使用；优先使用完整 `Teams 规划表`。

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：需求分析-WIKI 列表需求澄清<br>Skill/Subagent：`goal_requirements_analyst` | 目标切片：梳理 WIKI 列表需求<br>认领任务：GT-001<br>Workflow：串行<br>前置任务：-<br>锁定范围：`.codex/goal-teams/versions/<version>/spec/` | 交付物：需求规格卡<br>完成标准：用户确认核心目标/功能/流程/边界<br>Harness：文档结构与边界清单审查<br>文档/tasklist：requirement-spec-card.md + INDEX.md | 测试 Owner：评审-WIKI 列表需求校验<br>校验者：评审-WIKI 列表需求校验 |
| 成员：产品-WIKI 列表 PRD<br>Skill/Subagent：`goal_product` | 目标切片：生成 WIKI 列表 PRD<br>认领任务：GT-002<br>Workflow：串行<br>前置任务：GT-001<br>锁定范围：`.codex/goal-teams/versions/<version>/spec/` | 交付物：PRD<br>完成标准：PRD 来源于已确认需求规格卡<br>Harness：PRD 溯源和验收标准清单<br>文档/tasklist：PRD + tasklist.md | 测试 Owner：评审-WIKI 列表 PRD 校验<br>校验者：评审-WIKI 列表 PRD 校验 |

### 独立校验计划

| 产物类型 | 作者 | 校验者 | 校验方法 | 证据位置 |
| --- | --- | --- | --- | --- |
| 文档 | 产出成员 | 非作者评审成员或用户指定 skill | 结构/事实/验收标准校验 | `progress.md` / `acceptance.md` |
| 代码 | 实现成员 | 独立测试/评审成员或用户指定 skill | 代码审查 + 命令验证 | `progress.md` |
| 测试用例 | 测试成员 | 独立评审成员或用户指定 skill | 断言有效性/边界覆盖校验 | `test-plan.md` / `progress.md` |

### Tasklist 执行

| Task ID | Owner | 状态 | 依赖 | Harness | 验证 | 完成证据 |
| --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 需求分析师 | pending | - | 文档清单审查 | 用户确认 | 需求规格卡完成 |
| GT-002 | 产品/需求 | pending | GT-001 | PRD 溯源检查 | PRD review | PRD 章节完成 |

### 风险与审批

| 项目 | 风险 | Owner | 是否需审批 | 停止条件 |
| --- | --- | --- | --- | --- |
| Shared module | 多成员可能编辑同一文件 | Goal Lead | 是 | locked_scope 不清楚 |

表格后用中文询问，并默认给数字选项：

```text
请选择下一步：
1. 确认并执行
2. 调整成员或范围
3. 只保留方案，不执行
```

如果用户明确要求继续、包含直接执行词或执行已确认计划，仍展示 `Teams 规划表`，然后直接继续。

除非用户只要方案且不希望写文件，否则把确认表和假设持久化到 `.codex/goal-teams/versions/<version>/plan.md`。

## 进度反馈表

每个有意义轮次都用表格总结：

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| 后端-WIKI 列表后端开发 | GT-003 | running | Test | `cargo test ...` | 更新文档 |

独立校验：

| 产物 | 作者 | 校验者 | 状态 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `spec/PRD.md` | 产品-WIKI 列表 PRD | 评审-WIKI 列表 PRD 校验 | passed | review note | 更新 acceptance |

阻塞：

| 阻塞 | 成员 | 任务 | 影响 | 需要决策 | 建议下一步 |
| --- | --- | --- | --- | --- | --- |

最终收尾：

| 成员 | 认领任务 | Workflow / 前置任务 | 最终状态 | 证据 | 资源消耗（用户 / tokens / 费用） | 剩余 |
| --- | --- | --- | --- | --- | --- | --- |

把进度、阻塞和收尾证据追加到 `.codex/goal-teams/versions/<version>/progress.md` 或相关 Markdown 产物。

## 提示词缓存友好布局（Prompt）

保持布局稳定：

```text
[稳定核心提示词]
[文档加载清单]
[Goal Mode 循环]
[动态目标包]
```

规则：

- 稳定核心提示词很少变化。
- 文档加载清单只列路径和读取规则，不塞长文档正文。
- 动态目标包放最后。
- 每个 subagent 只拿自己的 packet 和必要文档切片。
- 渐进读取文档，并总结成 Doc Capsules。

## 文档加载清单

通用清单：

```text
总是先加载：
1. 用户目标和约束。
2. 项目指南文件：AGENTS.md、agents.md、agent.md、CLAUDE.md、claude.md。
3. 没有项目指南时加载 references/default-AGENTS.md。
4. 如存在，加载 .codex/goal-teams/INDEX.md 和 .codex/goal-teams/versions/<version>/INDEX.md。
5. 如存在，加载 .codex/goal-teams/versions/<version>/plan.md。
6. 如存在，加载相关 tasklist；否则创建 .codex/goal-teams/versions/<version>/tasklist.md。
7. 当前成员认领任务行。
8. 当前任务的 Harness Contract；如使用 Benchmark，加载对应 `benchmarks/` 任务包索引和报告。
```

按需加载：

| 需求 | 加载 |
| --- | --- |
| 产品/用户范围 | Requirement Specification Card、PRD、issue、brief 或干系人备注 |
| 架构/归属 | Architecture Design、design.md、模块文档、代码地图、依赖文件 |
| UI/页面/工作流 | HTML Prototype、design.md、截图、mockup、route map |
| API/合同语义 | API 文档、schema、route 定义、SDK 文档 |
| 测试/验收 | Test Plan、现有测试、CI 配置、acceptance 文档 |
| Harness | tasklist 中的 Harness Contract、测试命令、人工检查清单、证据路径 |
| Benchmark | `benchmarks/README.md`、任务 `task.md` 或 `SPEC.md`、metadata（如有）、Harness、scoring、reports |
| 发布/部署 | README、部署文档、changelog、runbook |

所需文档不存在时，只有它属于已确认计划，才创建小范围文档。

## 团队目标包（Team Goal Packet）

```text
Goal Packet（团队目标包）:
- goal:
- version:
- version_dir:
- done_criteria:
- language: 默认中文
- constraints:
- discovered_docs:
- markdown_persistence:
  - INDEX.md
  - plan.md
  - progress.md
  - decisions.md
  - tasklist.md
- tasklist_path:
- openspec_or_superpower_lead_only: true/false
- allowed_scope:
- forbidden_scope:
- required_tests:
- harness_policy:
  - 每个任务必须有 Harness Contract、证据路径或 not_applicable_reason
  - 不宣称未验证或未授权的运行能力
- benchmark_policy:
  - enabled: true/false
  - benchmark_dir: benchmarks/（仅在用户要求或计划确认时）
  - failure_taxonomy_required: true/false
- loop_policy:
  - member_loop: Load -> Plan -> Implement -> Test -> Document -> Review -> Continue
  - lead_loop: Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue
  - skill_improvement_loop: 仅在用户明确要求改 skill 或 benchmark/复盘任务时启用
- required_docs_after_done:
  - Markdown 进度/结果更新
- required_spec:
  - Requirement Specification Card
  - PRD
  - Architecture Design
  - HTML Prototype（适用时）
  - test plan
  - acceptance
- stop_conditions:
- confirmation_required:
- team_members:
  - member_id:
    subagent_id:
    display_name:
    role:
    skill_or_subagent:
    workflow_mode: serial | parallel
    depends_on:
    communication_style: 简洁、人类友好的中文
    claimed_tasks:
    locked_scope:
    deliverable:
    harness_owner_for:
    validation_owner_for:
```

用 Team Goal Packet 为每个 subagent 创建 Member Goal Packet。

## 成员目标包（Member Goal Packet）

```text
Member Goal Packet（成员目标包）:
- member_id: 后端-WIKI 列表后端开发
- subagent_id: 后端-WIKI 列表后端开发
- display_name: 后端-WIKI 列表后端开发
- role: 后端
- skill_or_subagent: goal_backend
- workflow_mode: serial
- depends_on:
  - GT-001
  - GT-002
- version: V3.0
- version_dir: .codex/goal-teams/versions/V3.0
- language: 默认中文
- user_requested_skill:
- user_requested_subagent:
- lane_or_deliverable: API 实现
- target_task_ids:
  - GT-002
- claimed_tasks:
  - 实现已确认的 API 切片
- goal:
  完成被分配的后端切片，并达到可验证 done 状态。
- success_criteria:
  - API 行为符合已接受合同。
  - 定向测试通过。
  - 独立校验者确认生成代码和测试。
- required_doc_load:
  - .codex/goal-teams/versions/V3.0/tasklist.md#GT-003
  - 相关 API 文档，如存在
- allowed_scope:
  - src/api
  - tests/api
- forbidden_scope:
  - 未审批不得修改 shared auth/payment/core modules
- locked_scope:
  - src/api/specific-module
- required_tests:
  - 被修改模块的定向测试
- harness_contract:
  purpose: 证明 API 切片符合已接受合同且不引入回归。
  checks:
    - API 合同测试
    - 定向回归测试
  commands:
    - <按项目实际命令填写，未知时写需 Lead 确认>
  artifact_checks:
    - tasklist 状态更新
    - progress 证据行
  evidence_paths:
    - .codex/goal-teams/versions/V3.0/progress.md
  failure_report:
    - command
    - failing_check
    - likely_cause
    - next_verification
  not_applicable_reason:
- benchmark_refs:
  - enabled: false
  - task_id:
  - report_path:
- required_independent_validation:
  - 生成文档：校验者不能是作者
  - 生成代码：独立 QA/reviewer 或用户指定 skill
  - 生成测试用例：独立 reviewer 或用户指定 skill
- required_docs_after_done:
  - tasklist 状态
  - versions/<version>/progress.md 行
  - API 说明（如有变化）
- required_spec:
  - Requirement Specification Card：读取或确认不适用
  - PRD：读取或确认不适用
  - Architecture Design：API 结构变化时更新
  - HTML Prototype：无 UI 变化时不适用
  - Test Plan：覆盖范围变化时更新
  - Acceptance：Done Criteria 变化时更新
- stop_conditions:
  - API 合同不清楚
  - 必要凭证不可用
- output_contract:
  - Doc Capsules
  - plan
  - Harness Contract
  - 变更文件
  - 运行测试
  - 更新文档
  - Markdown 进度/结果更新
  - 独立校验证据
  - tasklist 更新
  - SPEC 更新
  - 建议的 team-state 更新
  - 完成状态
  - 阻塞和风险
```

## 文档摘要 JSONL（Doc Capsule）

```json
{"ts":"2026-05-26T10:00:00+08:00","member_id":"后端-WIKI 列表后端开发","subagent_id":"后端-WIKI 列表后端开发","source":".codex/goal-teams/versions/V3.0/tasklist.md#GT-003","decision":"只实现已确认 API 切片。","must_do":["符合已接受合同","运行定向测试"],"must_not_do":["未审批不得编辑 shared auth"],"test_refs":["定向模块测试"],"doc_update_refs":[".codex/goal-teams/versions/V3.0/tasklist.md"],"open_questions":[]}
```

## 团队状态 JSON（Team State）

```json
{
  "team": {
    "mode": "goal-teams",
    "goal": "完成已确认用户目标",
    "version": "V3.0",
    "version_dir": ".codex/goal-teams/versions/V3.0",
    "status": "planning",
    "tasklist_path": ".codex/goal-teams/versions/V3.0/tasklist.md",
    "updated_at": "2026-05-26T10:00:00+08:00"
  },
  "members": [
    {
      "id": "需求分析-WIKI 列表需求澄清",
      "subagent_id": "需求分析-WIKI 列表需求澄清",
      "display_name": "需求分析-WIKI 列表需求澄清",
      "role": "需求分析",
      "skill_or_subagent": "goal_requirements_analyst",
      "workflow_mode": "serial",
      "depends_on": [],
      "status": "pending",
      "claimed_tasks": ["GT-001"],
      "current": "创建 WIKI 列表需求规格卡",
      "locked_scope": [".codex/goal-teams/versions/V3.0/spec"]
    }
  ]
}
```

## 事件 JSONL（Events）

```json
{"ts":"2026-05-26T10:01:00+08:00","type":"goal_team_planned","goal":"完成已确认用户目标"}
{"ts":"2026-05-26T10:02:00+08:00","type":"version_dir_created","path":".codex/goal-teams/versions/V3.0"}
{"ts":"2026-05-26T10:02:30+08:00","type":"index_created","path":".codex/goal-teams/versions/V3.0/INDEX.md"}
{"ts":"2026-05-26T10:03:00+08:00","type":"tasklist_created","path":".codex/goal-teams/versions/V3.0/tasklist.md"}
{"ts":"2026-05-26T10:03:00+08:00","type":"user_confirmed_plan","confirmation":"approved"}
{"ts":"2026-05-26T10:04:00+08:00","type":"member_spawned","member_id":"需求分析-WIKI 列表需求澄清","subagent_id":"需求分析-WIKI 列表需求澄清","skill_or_subagent":"goal_requirements_analyst"}
{"ts":"2026-05-26T10:20:00+08:00","type":"task_completed","task_id":"GT-001","member_id":"需求分析-WIKI 列表需求澄清","subagent_id":"需求分析-WIKI 列表需求澄清"}
```

## 消息 JSONL（Messages）

```json
{"ts":"2026-05-26T10:12:00+08:00","from":"qa-gt-003","to":"goal-lead","task_id":"GT-003","severity":"medium","message":"需要确认空状态验收的预期行为。","decision_needed":true,"status":"open"}
```

## 目标循环细节（Goal Loop）

Goal Loop 分三层：成员 Loop、Lead Loop、Skill Improvement Loop。普通执行默认只跑成员 Loop 和 Lead Loop；只有用户明确要求改进 skill、构建 benchmark 或进行复盘时，才进入 Skill Improvement Loop。

### 成员 Loop

### Load（加载）

1. 读取用户目标和约束。
2. 检查项目指南：`AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md`。
3. 读取或创建跨版本和版本 `INDEX.md`。
4. 读取或创建版本化 SPEC。
5. 读取或创建版本化 tasklist。
6. 读取当前成员认领任务行。
7. 只按需读取项目文档。
8. 读取当前任务的 Harness Contract；如果缺失，报告缺口，不编造验证方式。
9. 如任务属于 Benchmark，读取对应 task package 的 `task.md` 或 `SPEC.md`、metadata（如有）和 Harness 说明。
10. 产出 Doc Capsules。

### Plan（计划）

优先返回精简执行步骤；复杂目标可展开，但每步都要带验证方式：

```text
Plan（计划）:
1. 环境/版本/索引 -> 验证：文档目录和 INDEX 已准备
2. 需求规格卡 -> 验证：用户确认目标/功能/流程/边界
3. PRD 任务 -> 验证：验收标准已确认
4. Architecture Design 任务 -> 验证：设计评审通过
5. HTML Prototype 任务 -> 验证：适用时有截图/E2E
6. Harness 契约 -> 验证：检查、命令、证据路径或不适用原因已写明
7. 实现 tasklist 任务 -> 验证：定向测试通过
8. 独立 QA 任务 -> 验证：命令/报告可追溯
9. 文档/tasklist 任务 -> 验证：状态和 Owner 已更新
```

### Implement（实现）

按 tasklist 顺序和依赖执行。工程任务常见顺序：

1. 环境指南检查和版本目录。
2. 跨版本和版本 `INDEX.md`。
3. Requirement Specification Card。
4. 基于已确认规格卡生成 PRD。
5. Architecture Design。
6. 适用时生成 HTML Prototype。
7. tasklist 实现任务。
8. 独立 QA/testing 任务。
9. Harness 证据、失败报告或不适用原因。
10. 文档、acceptance 和 tasklist 状态更新。

跳过层级时必须说明原因。

### Test（测试）

测试必须由独立 subagent 或用户指定 testing skill/subagent 执行。先做最小有效验证；共享行为变化时再扩大范围。

测试阶段优先执行 Member Goal Packet 中的 Harness Contract。命令未知或不可运行时，成员必须记录原因、风险和下一步验证建议，不能把缺失 Harness 当成通过。

失败报告：

```text
测试失败：
- command:
- failing test:
- likely cause:
- fix plan:
- next verification:
```

### Document（记录）

每个成员都要说明是否更新：

- tasklist 状态
- owner/claimed_by 字段
- packet 中分配的 docs
- packet 中分配的 SPEC
- Harness 证据、失败报告或不适用原因
- Benchmark 运行记录或失败分类（如适用）
- 新增或变更文档的版本 `INDEX.md`
- 报告或 acceptance 备注
- 生成 docs/code/tests 的独立校验证据
- 剩余缺口

### Review（评审）

```text
Review Checklist（评审清单）:
- 认领任务完成:
- 完成标准:
- Harness 契约:
- Harness 证据:
- Benchmark 记录（如适用）:
- 测试:
- 生成 docs/code/tests 是否独立校验:
- docs/tasklist:
- SPEC:
- locked_scope 是否遵守:
- 阻塞:
- 剩余风险:
```

持续循环，直到完成或阻塞。

### Lead Loop

Goal Lead 的循环是 `Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`：

1. `Plan`：把用户目标转为 Done Criteria、SPEC、tasklist、Harness 契约、Benchmark 适用性和风险表。
2. `Dispatch`：按 `Teams 规划表` 分发 Member Goal Packet，保证每个实现成员有 `locked_scope` 和 Harness Contract。
3. `Route`：处理成员阻塞、跨成员依赖、共享范围冲突、高风险审批和用户决策。
4. `Integrate`：汇总成员输出，更新 Markdown、team-state、events、messages、doc-capsules 和 tasklist。
5. `Audit`：启动只读 `goal_completion_auditor`，检查完成标准、Harness 证据、独立校验和剩余风险。
6. `Continue`：已确认范围内遗漏自动续跑；新范围、高风险、凭证、外部审批或未解决决策才问用户。

Lead Loop 不替代成员 Loop：Lead 负责协调和证据闭环，不直接把未验证产物标记为完成。

### Skill Improvement Loop

Skill Improvement Loop 是发布维护层，状态流是 `Run/Eval -> Classify -> Update Rules/Templates -> Validate -> Release Notes`：

1. `Run/Eval`：收集真实 Goal Teams 运行、Benchmark 报告、收尾审计和用户反馈。
2. `Classify`：按失败分类归因，例如需求误解、上下文没读全、定位失败、工具失败、环境失败、实现错误、测试不足、过度修改、引入回归、证据缺失、权限/安全违规、长任务漂移、多 agent 协调失败。
3. `Update Rules/Templates`：按用户授权更新 `goal-teams.md`、`SKILL.md`、`references/goal-teams-runtime.md`、subagents、默认 AGENTS、README/CHANGELOG、examples 或校验脚本。
4. `Validate`：运行 `./scripts/check.sh`，必要时补充示例复盘或 benchmark smoke run。
5. `Release Notes`：记录版本阶段，例如 `V1.5` Harness 与三层 Loop 规则、`V1.6` 最小 Harness 示例、`V1.7` Benchmark 模板、`V1.8` 机器可读协议、`V1.9` 生产流门禁。

普通用户任务不会自动进入 Skill Improvement Loop；只有用户明确要求改 skill、发布版本、构建 benchmark 或进行复盘时才进入。

## 收尾审计与自动续跑

每次看似完成后，Goal Lead 必须先做最终审计，再发送最终回复。

使用新的只读 `goal_completion_auditor`，packet 如下：

```text
Completion Audit Packet（收尾审计包）:
- display_name: 收尾-WIKI 列表未完成工作检查
- skill_or_subagent: goal_completion_auditor
- version:
- confirmed_goal:
- confirmed_scope:
- tasklist_path:
- progress_path:
- acceptance_path:
- spec_paths:
- test_evidence:
- validation_evidence:
- audit_scope:
  - 任务状态
  - 完成标准
  - docs/SPEC 更新
  - Harness 契约和证据
  - Benchmark 运行记录和失败分类（如适用）
  - 独立校验证据
  - 测试和验收证据
  - 未解决阻塞
  - 剩余风险
- output_contract:
  - 审计结论：complete | auto_continue | blocked_needs_user
  - 未完成项
  - 证据
  - 缺失 Harness 或 Benchmark 记录
  - 建议续跑任务
  - 建议成员/subagents
  - locked_scope
  - 停止条件
```

审计结论处理：

| 结论 | Lead 动作 |
| --- | --- |
| `complete` | 发送最终完成回复。 |
| `auto_continue` | 把未完成项转成 tasklist 条目，展示续跑 `Teams 规划表`，不再要求用户确认，直接启动需要的成员。 |
| `blocked_needs_user` | 在 `decisions.md` 或 `progress.md` 记录阻塞/决策，说明为何不能安全自动续跑，并询问用户缺失决策或审批。 |

自动续跑只允许处理已确认目标范围内的未完成工作。不要自动进入新范围、破坏性写入、安全敏感工作、缺少凭证、外部审批或未解决用户决策。

每次自动续跑：

1. 追加 `completion_audit_started`、`completion_audit_finished`、`auto_continuation_started` 等事件。
2. 用续跑任务 ID 和 Owner 更新 tasklist/progress。
3. 展示四列续跑 `Teams 规划表`。
4. 在范围不冲突时并发启动所需成员。
5. 照常执行独立测试和独立校验。
6. 续跑完成后再次执行收尾审计。

## 命令行桥接（CLI Bridge）

dashboard 不直接执行 shell 命令；需要时用本地 bridge。

Lead 执行模式：

```bash
PROJECT="/path/to/project"
VERSION="V3.0"

codex exec \
  -C "$PROJECT" \
  --sandbox workspace-write \
  --ask-for-approval never \
  --json \
  --output-last-message ".codex/goal-teams/last-message.md" \
  - <<'PROMPT' | tee -a ".codex/goal-teams/events.jsonl"
Use $goal-teams.

先汇报：我是 Goal Teams Leader V1.9，我会帮你完成以下工作：
全程中文，Goal Lead 消息要简洁、人类友好。
生成文档、代码注释、面向用户的代码字符串、测试名称和测试用例默认中文。
运行时 subagent id、member_id 和成员展示名使用 <中文角色>-<具体任务名>，例如 后端-WIKI 列表后端开发；如果用户指定 skill，则使用 skill 名称，例如 browser-WIKI 列表页面验证。真实 subagent 配置名只写入 skill_or_subagent。
启动 worker subagents 或编辑实现文件前，展示四列 Teams 规划表；除非有直接执行词，否则等待确认。
检查 AGENTS.md / agent.md / CLAUDE.md / claude.md。缺失时使用 references/default-AGENTS.md，并建议复制为项目根目录 AGENTS.md。
使用版本 "$VERSION"，过程和结果文档写入 .codex/goal-teams/versions/$VERSION/。
多文档前先创建或更新 .codex/goal-teams/INDEX.md 和 .codex/goal-teams/versions/$VERSION/INDEX.md。
把用户目标转成 Done Criteria。
把 SPEC 定义为“什么算完成”，把 Harness 定义为验证契约/模板字段，不宣称新增 runtime 执行能力。
每个任务在 Plan、tasklist 或 Member Goal Packet 中写清 Harness Contract：checks、commands、artifact_checks、evidence_paths、failure_report 或 not_applicable_reason。
需要机器可读状态时，按 references/goal-teams-automation-protocol.md 记录 harness.yaml、evidence.jsonl、pipeline-state.json、failure_report 和 approval_gate；它们是协议模板，不代表已有 runner、CI/CD 或生产接入。
面向生产流或发布门禁时，按 references/goal-teams-production-pipeline.md 组织 Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback；凭证、真实部署、破坏性操作和生产回滚必须人工审批或外部授权。
Benchmark 是外层评估目录与任务集，默认不创建；只有用户要求或计划确认时才创建/更新 benchmarks/，并记录任务集、运行记录、评分协议和失败分类。
三层 Loop：成员 Loop 是 Load -> Plan -> Implement -> Test -> Document -> Review -> Continue；Lead Loop 是 Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue；Skill Improvement Loop 只在用户要求改 skill、benchmark 或复盘时启用。
先安排需求分析成员；可在有用时使用 web search、computer use、browser 或 Chrome 改善需求质量。
先创建人类友好的 Requirement Specification Card，控制在两页以内，覆盖核心目标、关键业务功能结构、流程和边界。
从已确认的 Requirement Specification Card 生成 PRD。
发现已有 tasklist；没有则创建 .codex/goal-teams/versions/$VERSION/tasklist.md。
发现或创建 SPEC：Requirement Specification Card、PRD、Architecture Design、适用时的 HTML Prototype、test plan、acceptance。
提出独立 subagent 成员，包含认领任务、用户指定 skill/subagent、locked_scope、Harness Contract、docs/SPEC 更新、独立测试 Owner 和完成标准。
每个生成文档、代码变更和测试用例都要安排独立校验者，可用单独 subagent 或用户指定校验 skill。
启动实现成员前展示 SPEC 准备度、Harness 准备度、Benchmark 适用性、四列 Teams 规划表、tasklist 执行、独立校验计划和风险表。若提示词含直接执行词，展示为执行记录后直接继续。
确认后，每个成员作为独立 subagent 运行。
通过 team-state.json、events.jsonl、messages.jsonl、doc-capsules.jsonl 协调。
持续运行，直到每个认领任务完成、延期或阻塞且原因明确。
看似完成后，启动 goal_completion_auditor 检查未完成工作。若发现已确认范围内仍有未完成工作，创建续跑任务并并发重启 Goal Teams 成员，不再要求用户确认。只有新范围、高风险/破坏性工作、凭证、外部审批或未解决决策才问用户。
PROMPT
```

只规划模式：

```bash
codex exec \
  -C "$PROJECT" \
  --sandbox read-only \
  --json \
  'Use $goal-teams. 全程中文。只做 Goal Lead：检查环境，询问版本号，提出澄清问题，生成确认表格。不要编辑文件。'
```

## 安全与协作

- 没有 locked_scope 不启动实现。
- 不让多个成员同时编辑共享核心文件。
- 不跳过 Plan 模式。直接执行词只跳过确认等待，不跳过 Plan 表格。
- Plan 模式尽量用数字选项。
- 不自我批准生成产物。
- 生成 docs、code 或 test cases 没有独立校验，不标记 done。
- 多文档前先创建相关 `INDEX.md`。
- 除跨版本索引外，过程/结果 Markdown 不写到版本目录之外。
- PRD 前不跳过需求规格卡，除非用户明确选择 OpenSpec/Superpower lead-only 模式或确认例外。
- 用户指定 OpenSpec 或 Superpower 时，默认只做 Goal Lead，不经确认不启动角色 subagents。
- 不跳过 SPEC；缺少 Requirement Specification Card、PRD、Architecture Design、适用时的 HTML Prototype、test plan、acceptance、tasklist 时，创建或加入任务。
- 不跳过 Harness；每个任务必须有验证契约、证据路径或不适用说明。
- 不默认创建 Benchmark；只有用户要求或计划确认时，才创建或更新 `benchmarks/`。
- 实现成员不能是唯一测试者；必须安排独立 QA/testing skill/subagent。
- 尊重用户指定的成员 skill/subagent。
- auth、payment、refund、migrations、破坏性写入、安全敏感集成或广泛 API 变化需要 Lead 审批。
- `max_depth = 1`；成员不创建嵌套团队。
- 并发成员通常控制在 3-6 个，除非用户明确要求更多。
- 新的 `goal_completion_auditor` 审计前，不发送最终完成回复。
- 已确认范围内的未完成工作自动续跑，不再要求用户确认；但要展示续跑计划。
- 审计暴露新范围、破坏性或安全敏感工作、缺少凭证、外部审批或未解决决策时，必须问用户。

## 完成回复

最终回复保持简洁：

```text
完成：<一句话说明>

版本与文档：
| 版本 | 索引 | 主要文档 |
| --- | --- | --- |

成员状态：
| 成员 | 认领任务 | Workflow / 前置任务 | 状态 | 证据 | 资源消耗（用户 / tokens / 费用） | 剩余 |
| --- | --- | --- | --- | --- | --- | --- |

SPEC：
| SPEC | 状态 | Owner | 证据 |
| --- | --- | --- | --- |

Harness / Benchmark：
| 项目 | 状态 | 证据 | 剩余 |
| --- | --- | --- | --- |

独立校验：
| 产物 | 作者 | 校验者 | 状态 | 证据 |
| --- | --- | --- | --- | --- |

验证：
- <命令>：通过
- <命令>：未运行，原因...

文档与 tasklist：
- <文件>：已更新

剩余风险：
- <如无，写“无已知阻塞。”>
```
