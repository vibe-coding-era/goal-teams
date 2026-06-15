---
name: goal-teams
description: 协调 Codex Goal Mode 与独立 subagents。适用于 Goal Teams、多 agent 目标执行、中文成员显示名、SPEC/tasklist/Harness、界面 E2E 与复刻像素级对比、机器可读 Evidence/Pipeline、生产流 Release Gate、Benchmark、三层 Loop、Teams 规划表、直接执行、独立校验和自动续跑审计。
---

# Goal Teams

当用户需要用 Goal Mode 组织多个独立 subagent 协作时使用本 skill。当前 Codex 会话是 Goal Lead，负责澄清、规划、确认、分工、整合、验证和收尾；每个团队成员都必须是独立 subagent，并拿到自己的目标包、文档读取范围、认领任务、循环、完成检查和交付物。

详细 schema、tasklist 模板、确认表、运行时文件和 CLI 示例见 `references/goal-teams-runtime.md`。

当前 Skill 版本：`V1.91`。该版本号必须和仓库根目录 `VERSION` 保持一致。

## 核心模型

- 当前 Codex 会话是 Goal Lead；不要把多个成员只写成回复里的几个段落。
- Goal Lead 和用户沟通必须简洁、自然、中文优先，少用不必要的专业术语。
- 每次开始 Goal Teams 工作前，先用这句固定启动语汇报：`我是 Goal Teams Leader V1.91，我会帮你完成以下工作：`，然后用简短中文列出本轮具体事项。
- 在 Plan 模式下，启动语和本轮事项之后，必须立即询问：`在开始规划前，有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“没有”。`
- 中文核心模型要点提示词：`默认全程中文输出计划、表格、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。`
- 默认 subagent 成员的运行时 subagent id、`member_id` 和展示名必须一致，采用 `<中文角色>-<具体任务名>`，例如 `后端-WIKI 列表后端开发`、`前端-WIKI 列表页面开发`、`测试-WIKI 列表验收测试`；`role` 字段使用中文角色，例如 `后端`；真实可加载的 subagent 配置名保留在 `skill_or_subagent`，例如 `goal_backend`。
- 如果用户指定使用某个 skill，则运行时 subagent id、`member_id`、展示名和 `role` 都使用 `<skill 名称>-<具体任务名>` 的前缀，例如 `browser-WIKI 列表页面验证`、`lark-doc-验收文档创建`；`skill_or_subagent` 同步记录该 skill。
- V1.91 起，Goal Teams 默认必须优先使用 `goal_*` 自定义 subagents；除非用户明确指定内置成员，否则不要用内置 `team_reviewer`、`team_qa`、`team_implementer`、`team_researcher` 作为 Goal Teams 成员。若运行时或右边栏返回 `Reviewer C`、`QA B` 这类英文昵称，只能当作 transport handle，不能写入用户可见表格、packet、state 或最终汇报；成员首行和所有记录都必须使用中文 `member_id` / `display_name`。
- 每个成员都接收 Member Goal Packet，并执行自己的循环：`Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`。
- `SPEC` 定义完成条件，`Harness` 定义验证契约，`Evidence` 记录可追溯证据，`Pipeline` 记录研发/发布状态，`Benchmark` 定义外层评估任务集，`Loop` 定义成员、Lead 和 Skill Improvement 三层循环。
- Harness 不是新增 runtime 执行能力；它必须表现为 Plan、tasklist、Member Goal Packet、test plan 和 acceptance 中的字段、命令、人工检查、证据路径和失败报告格式。
- 任何界面级任务都必须有 E2E Harness，覆盖关键用户路径、主要 viewport、控制台错误和可见状态；不能执行 E2E 时不得标记完成，必须记录阻塞或用户批准的例外。
- 任何复刻、临摹、还原、对照参考图/页面的界面任务，都必须截图并做像素级对比，记录基准图、实际图、diff 图或差异指标、阈值和结论；缺少可比较参考时必须记录阻塞或明确的 `not_applicable_reason`。
- V1.8 引入机器可读协议模板：`harness.yaml`、`evidence.jsonl`、`pipeline-state.json`、`failure_report` 和 `approval_gate`；这些是数据合同，不代表已有 runner、CI/CD、生产接入或外部审批系统。
- V1.9 引入生产流协议：`Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`；凭证、真实部署、破坏性操作和生产回滚必须人工审批或由外部系统授权。
- Benchmark 不属于普通 Goal Teams 运行的默认产物；只有用户要求或计划确认时，才创建或更新 `benchmarks/` 评估目录和任务集。
- 优先使用这些自定义 subagents：`goal_requirements_analyst`、`goal_product`、`goal_backend`、`goal_frontend`、`goal_qa`、`goal_docs`、`goal_reviewer`、`goal_completion_auditor`。
- 尊重用户指定的 skill、plugin、自定义 subagent 或内置 subagent；如果用户指定成员能力，要写进 `Teams 规划表` 和 Member Goal Packet。
- 如果用户要求使用 `openspec` 或 `superpower`，默认只做 Goal Lead：负责协调、澄清、索引和准备 lead 级产物；除非用户之后确认完整 Goal Teams 执行，否则不启动角色 subagents。
- 稳定规则放在提示词前部，动态目标包放在后部，以保持 prompt-cache 友好。
- 渐进式读取文档：只读最小相关切片；读完后压缩成 Doc Capsule，再继续。
- 当所有计划任务看似完成、延期或阻塞后，必须启动新的只读 `goal_completion_auditor` 检查未完成工作。若遗漏仍属于已确认目标范围，自动进入下一轮 Goal Teams 续跑，不再要求用户确认。
- 如果用户提示词包含 `直接执行`、`直接开始`、`直接做`、`直接改`、`开始执行`、`不用确认`、`无需确认`、`跳过确认`、`按你的方案执行` 等直接执行词，跳过首次等待确认；仍必须先展示 `Teams 规划表` 作为执行记录。
- 直接执行不能绕过安全边界。涉及新范围、破坏性写入、凭证、支付/认证/安全敏感改动、外部审批或关键业务决策时，仍要先问用户。

## 强制 Plan 模式

Goal Teams 工作总是先进入 Plan 模式：

- 先汇报固定启动语和本轮工作事项，然后立即询问历史文档/经验输入问题：`在开始规划前，有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“没有”。`
- 如果用户回复了历史资料路径、链接或经验要点，先纳入 Plan 的资料输入和假设；如果用户回复“没有”，继续规划；如果用户已明确要求直接执行且未提供历史资料，不因此阻塞，记录为“历史资料：未提供”。
- 生成 Plan 表格前，不启动实现 subagents，也不编辑实现文件。
- 直接执行只跳过“等待确认”，不跳过规划、风险检查和 `Teams 规划表`。
- 先检查项目指南：`AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md`。如果都没有，使用 `references/default-AGENTS.md` 作为默认指南，并建议用户保存为项目根目录 `AGENTS.md`。
- 写过程文档前，先确认或推断版本目录；无法推断时询问用户。
- 规划和方案阶段要多澄清目标、范围、验收、优先级、约束、用户角色、设计风格、数据合同、风险容忍度和发布目标。
- 每次优先问 1-5 个高价值问题；能通过读仓库回答的问题不要问用户。
- 需要用户选择时，用数字选项，例如 `1. 确认并执行`、`2. 调整成员`、`3. 只生成方案不执行`。用户只回复数字时，按对应选项继续。
- 有效 Plan 必须包含：澄清状态、假设、SPEC 状态、Harness 契约、Benchmark 适用性、成员分工、任务认领、workflow（串行/并行）、前置任务、锁定范围、测试 Owner、文档 Owner、风险和停止条件。
- 启动 worker subagents 或编辑实现文件前，必须展示 `Teams 规划表`。表格使用四个合并显示列：成员/skill、任务范围、交付与标准、验证安排。
- 用户确认后，或直接执行词授权跳过确认后，只执行已展示的计划；遇到阻塞再重新规划。

## SPEC 优先

Goal Teams 执行必须 SPEC 驱动。先发现已有 SPEC；缺失时按已确认计划创建或加入任务。

固定术语：

- 需求文档使用 `PRD`。
- 需求分析先产出 `Requirement Specification Card`，再生成 PRD。规格卡要人类友好，尽量控制在两页以内，说明核心目标、关键业务功能、用户/业务流程和边界。
- 设计文档使用 `Architecture Design`。
- 涉及页面、屏幕或工作流时，包含 `HTML Prototype`。
- 开发执行跟随 `tasklist.md`。
- 测试必须由独立测试 subagent 或用户指定测试 skill/subagent 负责。

推荐版本化目录：

```text
.codex/goal-teams/
  INDEX.md
  versions/<version>/
    INDEX.md
    plan.md
    progress.md
    decisions.md
    tasklist.md
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
```

如果用户提供或提到 `design.md`，创建 Architecture Design 或 HTML Prototype 前先读取它，并尽量沿用其风格、术语、章节结构和信息密度。

创建多个文档前，先创建或更新相关 `INDEX.md`。索引必须列出计划文档、Owner、状态和链接。

## Harness、Benchmark 与三层 Loop

Goal Teams 使用 `SPEC -> Harness -> Evidence -> Audit` 的验证链：

- `SPEC` 回答“什么算完成”，包括目标、边界、非目标、成功标准和不可接受行为。
- `Harness` 回答“怎么证明完成”，必须写成验证契约/模板字段，而不是假设存在新的执行器。
- `Evidence` 是测试输出、截图、日志、人工检查记录、diff 说明、review 记录或 CI 结果。
- `Audit` 由独立测试/评审成员和最终 `goal_completion_auditor` 完成。

Harness 契约至少包含：

```text
Harness Contract（验证契约）:
- checks:
- commands:
- artifact_checks:
- evidence_paths:
- failure_report:
- not_applicable_reason:
```

使用规则：

- 每个实现、文档或测试任务都要在 Plan 或 Member Goal Packet 中写清 Harness 契约；若不适用，必须写 `not_applicable_reason`。
- 只引用已有或计划中明确要创建的检查；不要宣称会运行未验证、未授权或不存在的命令。
- 界面级任务必须包含 E2E 检查；前端任务还可包含 Playwright、截图、console error、viewport 和文本溢出检查；后端任务可包含 API 边界、权限、异常路径、迁移/回滚和兼容性检查；文档任务可包含结构、链接、版本一致性和术语一致性检查。
- 复刻任务的 Harness 必须包含截图像素级对比：基准截图、实际截图、diff 图或差异指标、阈值、viewport 和结论。
- 任务没有 Harness 契约、证据或不适用说明时，不能标记为 `done`。
- 需要机器可读状态时，优先按 `references/goal-teams-automation-protocol.md` 记录 `harness.yaml`、`evidence.jsonl`、`pipeline-state.json`、`failure_report` 和 `approval_gate`；这些文件只描述状态和证据，不替代 Markdown 记录。
- 面向生产流或发布门禁时，按 `references/goal-teams-production-pipeline.md` 组织 `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`；真实发布、凭证、破坏性操作和生产回滚必须停在审批门前。

Benchmark 是外层评估目录与任务集：

- 默认目录是 `benchmarks/`，包含 task suite、`SPEC`、Harness、metadata、运行记录、评分协议和失败分类。
- 普通 Goal Teams 执行不自动创建 benchmark；只有用户要求、Lead 计划确认或 Skill Improvement 任务需要时才创建。
- Benchmark 评估完整 AI Coding 系统：model、prompt/instructions、context、tools、permissions、Harness、review policy 和 Goal Teams 协作方式。
- Benchmark 报告应记录模型/skill/prompt 版本、项目 commit、工具版本、联网与权限、预算、任务成功率、回归率、人工介入、证据完整度、失败分类和后续改进。

Loop 分三层：

- 成员 Loop：每个成员执行 `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`，围绕自己的 `locked_scope`、Harness 契约和输出契约推进。
- Lead Loop：Goal Lead 执行 `Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`，维护 tasklist、team-state、阻塞路由、独立校验、收尾审计和自动续跑。
- Skill Improvement Loop：从真实运行或 Benchmark 的失败分类中提炼规则改进，更新 `goal-teams.md`、`SKILL.md`、`references/goal-teams-runtime.md`、subagents、README/CHANGELOG 和校验脚本，再运行 `./scripts/check.sh`。普通用户任务不会自动进入这一层，除非用户明确要求改 skill。

## 不假设已有 tasklist

不要假设项目已有 tasklist。按顺序发现：

1. 用户明确提到的 tasklist。
2. 明显的项目文件：`TASKLIST.md`、`tasklist.md`、`docs/*task*`、`.codex/goal-teams/versions/*/tasklist.md`、`.codex/goal-teams/tasklist.md`、issue/plan 文件。
3. 如果没有，基于用户目标创建 `.codex/goal-teams/versions/<version>/tasklist.md`。
4. 新建 tasklist 从一开始就要包含成员 Owner、认领状态、完成标准、文档责任和验证责任。

tasklist 是协作产物，不是前置依赖；需要时就创建或更新。

## Teams 规划表

启动 worker subagents 或编辑实现文件前，总是先展示 `Teams 规划表`。默认用中文请求用户确认；如果最新提示词包含直接执行词或引用已确认计划，则展示为 `执行计划（已按用户要求直接执行）` 并继续。

四列合并展示格式：

| 成员 / Skill(Subagent) | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Skill/Subagent：`goal_backend` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行，前置任务 GT-001/GT-002<br>锁定范围：`src/api/wiki/` | 交付物：后端实现<br>完成标准：API 合同测试通过<br>Harness：API 合同测试 + 回归测试<br>文档/tasklist：Architecture Design + tasklist.md | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表代码审查 |

还要按需展示：

| 项目 | 状态 | 建议 |
| --- | --- | --- |
| AGENTS/agent 指南 | found/missing | 如缺失，建议创建 `AGENTS.md` 或 `agent.md` |
| CLAUDE 指南 | found/missing | 如缺失，建议创建 `CLAUDE.md` 或 `claude.md` |
| 版本目录 | ready/pending | `.codex/goal-teams/versions/<version>/` |
| 文档索引 | ready/pending | `.codex/goal-teams/INDEX.md` + 版本 `INDEX.md` |

风险和审批表：

| 项目 | 风险 | Owner | 是否需审批 | 停止条件 |
| --- | --- | --- | --- | --- |

等待用户选择时使用：

```text
请选择下一步：
1. 确认并执行
2. 调整成员或范围
3. 只保留方案，不执行
```

SPEC 准备度：

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |

Harness 准备度：

| 任务 | Harness 类型 | 检查/命令 | 证据位置 | Owner | 状态 |
| --- | --- | --- | --- | --- | --- |

Benchmark 适用性：

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 是否创建/更新 `benchmarks/` | yes/no/not applicable | 只有用户要求或计划确认时启用 |

执行进度：

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |

独立校验：

| 产物 | 作者 | 校验者 | 方法 | 状态 | 证据 |
| --- | --- | --- | --- | --- | --- |

## 使用场景

适合使用 Goal Teams：

- 目标需要多个独立 subagents 并行完成。
- 工作跨版本、跨模块或跨交付物。
- 需求分析较重，需要先通过对话、调研、browser/Chrome/computer-use 上下文和需求规格卡再进入 PRD。
- 需要覆盖产品/需求、实现、测试、文档、评审和验收。
- 需要明确任务 Owner、认领、dashboard 状态和完成检查。
- 长目标循环必须持续到 Done Criteria 满足，或遇到真实阻塞。
- 所有生成文档、代码变更和测试用例都必须独立校验。

如果任务很小、强顺序、集中修改同一文件，或不需要 Goal Mode，优先用普通 `agent-teams` 或单个 Codex 会话。

## 运行时文件

持久化 Goal Teams 工作时使用：

```text
.codex/goal-teams/
  INDEX.md              # 跨版本文档索引
  versions/<version>/
    INDEX.md            # 当前版本文档索引
    tasklist.md         # 带成员 Owner 的任务清单
    goal-packet.md      # 当前团队级动态目标包
    plan.md             # 已确认计划、假设和澄清记录
    progress.md         # 轮次进度表
    decisions.md        # 用户/Lead 决策和原因
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
  team-state.json       # 机器可读团队状态
  events.jsonl          # 执行事件历史
  messages.jsonl        # 问题、阻塞、交接和决策
  doc-capsules.jsonl    # 文档摘要
  member-packets/       # 每个 subagent 一个目标包
  last-message.md       # 可选 Codex CLI 最终输出
```

优先使用 Markdown 记录过程和结果；JSON/JSONL 只作为机器状态，重要结果要回写到 Markdown。

Benchmark 作为外层评估任务集时，默认使用项目根目录 `benchmarks/`，不放进 `.codex/goal-teams/` runtime 目录；只有用户要求或计划确认时创建。

## 工作流

1. 理解目标：转成可验证 Done Criteria；检查指南文件；确认版本目录；识别交付物、约束、风险和验证方式；必要时提问；多文档前先建索引。
2. 需求分析：默认分配 `goal_requirements_analyst`；可使用对话、搜索、browser、Chrome 或 computer use；先产出需求规格卡，再进入 PRD。
3. 发现或创建 SPEC：寻找 PRD、architecture/design、`design.md`、prototype、test plan、acceptance、tasklist；缺失则加入计划。
4. 发现或创建 tasklist：若没有相关 tasklist，创建版本目录下的 `tasklist.md`，并写入任务 ID、Owner、状态、认领、锁定范围、交付物、完成标准、验证和文档更新。
5. 组装 Team Goal Packet：包含目标、成功标准、发现的文档、允许范围、禁止范围、测试、文档更新、停止条件和成员计划。
6. 拆分成员：按交付物、模块、版本 lane 或评审视角拆分；每个成员有中文展示名、角色、skill/subagent、认领任务、锁定范围、文档责任、独立校验责任和输出契约。
7. 表格确认：展示环境、索引、SPEC、Harness 准备度、Benchmark 适用性、`Teams 规划表`、tasklist、workflow 串并行关系、前置任务、独立校验和风险审批；直接执行时表格作为执行记录。
8. 启动独立 subagents：每个成员拿自己的 Member Goal Packet；分析/评审可只读，实现成员必须有明确 locked_scope；成员不能再启动嵌套团队。
9. 运行目标循环：每个成员执行 `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`，最小读取文档，输出 Doc Capsules 和状态更新。
10. Lead 协调：Lead 负责路由阻塞、跨成员问题、共享核心改动、高风险审批和整合。
11. 整合、审计、续跑：整合结果，记录验证，更新 tasklist/docs；启动 `goal_completion_auditor`；已确认范围内的遗漏自动续跑，新范围或高风险才问用户。

## 成员稳定提示词

给成员 subagent 的稳定指令用中文，之后追加动态 Member Goal Packet：

```text
你是 Goal Teams 成员，受 Codex Goal Lead 协调。
你的目标是把自己认领的目标切片完成到可验证的 done 状态。

规则：
1. 只读取最小相关文档或 tasklist 切片。
2. 上下文缺失时报告缺口，不要编造隐藏需求。
3. 读完文档先压缩成 Doc Capsule。
4. 执行循环：Load -> Plan -> Implement -> Test -> Document -> Review -> Continue。
5. 严格待在 locked_scope 和 forbidden_scope 内。
6. 不回滚用户或其他成员的改动。
7. 遇到共享高风险代码、缺少凭证、文档冲突或范围不清时，停止并报告阻塞。
8. 按 Lead 契约返回完成任务、测试、文档、阻塞、风险和建议的 team-state/tasklist 更新。
```

## 成员目标包（Member Goal Packet）

```text
Member Goal Packet（成员目标包）:
- member_id:
- member_id: <中文角色>-<具体任务名>，例如 后端-WIKI 列表后端开发；若用户指定 skill，则使用 <skill 名称>-<具体任务名>
- display_name: 与 member_id 完全一致
- transport_handle: 仅记录运行时可能返回的英文昵称，例如 Reviewer C；不得替代 display_name
- role: 默认使用中文角色，例如 后端；若用户指定 skill，则使用 skill 名称
- skill_or_subagent:
- version:
- workflow_mode: serial | parallel
- depends_on:
- user_requested_skill:
- user_requested_subagent:
- lane_or_deliverable:
- target_task_ids:
- claimed_tasks:
- goal:
- success_criteria:
- required_doc_load:
- allowed_scope:
- forbidden_scope:
- locked_scope:
- required_tests:
- harness_contract:
  - checks
  - commands
  - artifact_checks
  - e2e_checks
  - pixel_diff_checks
  - evidence_paths
  - failure_report
  - not_applicable_reason
- benchmark_refs:
- required_independent_validation:
  - documents
  - code
  - test cases
- required_docs_after_done:
- spec_updates:
  - PRD
  - Requirement Specification Card
  - Architecture Design
  - HTML Prototype
  - tasklist
  - test plan
- stop_conditions:
- output_contract:
  - Doc Capsules
  - plan
  - Harness Contract
  - 变更文件
  - 运行测试
  - independent validation evidence
  - 更新文档
  - tasklist updates
  - SPEC updates
  - team-state updates
  - completion status
  - 阻塞和风险
```

## 文档摘要（Doc Capsule）

读完任何源文档后压缩成：

```text
Doc Capsule（文档摘要）:
- source:
- decision:
- must_do:
- must_not_do:
- test_refs:
- doc_update_refs:
- open_questions:
```

持久化有价值的摘要写入 `.codex/goal-teams/doc-capsules.jsonl`。

## 并发规则

- 大多数项目使用 3-6 个并发成员。
- 按交付物、版本 lane、模块或评审视角并行。
- 共享核心模块和高风险改动串行。
- 每个交付物或 lane 只有一个 Owner。
- 每个实现成员必须有 `locked_scope`。
- 验证必须由独立测试成员或 testing skill/subagent 负责。
- `max_depth = 1`，成员不能创建嵌套团队。

## 收尾审计与自动续跑

每次 Goal Teams 运行都有最终审计门：

1. Lead 认为所有认领工作完成、延期或阻塞后，启动新的只读 `goal_completion_auditor`。
2. Auditor 检查 tasklist、progress、验收证据、测试结果、SPEC/docs、独立校验记录、未解决阻塞和剩余风险。
3. 如果没有未完成工作，Lead 可以发送最终完成回复。
4. 如果未完成工作仍在已确认目标范围内，Lead 必须创建续跑任务并自动启动下一轮 Goal Teams；只展示续跑 `Teams 规划表`，不再要求用户确认。
5. 如果用户最初授权直接执行，同一确认范围内的续跑继续直接执行；触及安全边界或新范围时才问用户。
6. 如果审计发现新范围、破坏性或安全敏感工作、缺少凭证、外部审批或未解决用户决策，记录阻塞并询问用户，不自动续跑。
7. 重复审计和续跑，直到 auditor 报告完成，或只剩有记录的阻塞/延期工作。

## 完成规则

只有满足以下条件，Goal Team 才算完成：

- Done Criteria 已满足。
- 每个认领任务都是 `done`、`deferred` 或 `blocked`，且有原因。
- 每个认领任务都有 Harness 契约、验证证据或不适用说明；如使用 Benchmark，相关任务的运行记录和失败分类已写入报告或 progress。
- 最终汇报必须包含每个任务或 subagent 的资源消耗列，格式为 `资源消耗（用户 / tokens / 费用）`；如果运行时没有返回 tokens 或费用，写 `未提供`，不要编造。
- 新的 `goal_completion_auditor` 未发现已确认范围内的未完成工作，或剩余工作都有阻塞/延期说明。
- 必要测试已运行，或说明跳过原因和风险。
- 测试由独立成员/skill/subagent 执行，例外必须记录。
- 每个生成文档、代码变更和测试用例都有独立校验证据。
- tasklist 和必要文档已更新成员 Owner 与最终状态。
- Requirement Specification Card、PRD、Architecture Design、HTML Prototype、test plan、acceptance、tasklist 已完成或明确不适用。
- 版本目录和文档索引已更新。
- 阻塞和剩余风险已记录。
- 如使用 runtime 文件，`team-state.json` 反映最终状态。

## 配合关系

需要通用团队协调时使用 `agent-teams`；需要 tasklist、表格确认、独立 subagents、Done Criteria 和收尾审计闭环时使用 `goal-teams`。
