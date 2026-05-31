[English](README.en.md) | 中文

# Goal Teams

作者：肉山@TGO 杭州

当前版本：`V1.3`

`goal-teams` 是一个面向 Codex 的 Goal Mode 团队化 Skill。它把一次目标执行拆成由 Goal Lead 统一协调、多个独立 subagent 分工完成的工作流，并强制使用中文沟通、SPEC 优先、Markdown 持久化、表格确认或直接执行记录，以及独立测试。

结合了 Claude Code 的 Agent Teams 和 Codex 的 Goal Mode 能力， 并强制 Plan 模式执行。

它适合用于中大型需求、跨模块改造、多版本并发、产品/研发/测试/文档协作、代码审计、安全审核、架构评审，以及需要把过程沉淀成可复盘资料的场景。

## 核心理念

Goal Teams 的设计目标是让每个团队成员都成为一个独立 subagent：

- Goal Lead 负责澄清目标、拆解计划、确认分工、路由阻塞、整合结果。
- 每个成员只负责自己的目标切片、锁定范围和交付物。
- 所有成员都基于同一套 SPEC、tasklist 和 Markdown 过程记录协作。
- 测试必须由独立 QA subagent 或用户指定的测试 skill/subagent 执行。
- 计划、进度、决策和结果尽量写入 Markdown，便于审阅、分享和复盘。

## 关键能力

- 版本身份：当前为 `Goal Teams Leader V1.3`；每次开始工作前先汇报 `我是 Goal Teams Leader V1.3，我会帮你完成以下工作：`，再列出本轮工作。
- 全程中文：计划、表格、SPEC、tasklist、进度报告、成员包。
- 中文产物：生成的文档、代码注释、面向用户的代码字符串、测试名称和测试用例描述默认使用中文。
- 强制 Plan 模式：执行前必须先澄清、规划，列出 `Teams 规划表`；默认给用户确认，若提示词包含“直接执行/不用确认/跳过确认”等直接执行类词语，则展示计划表后直接执行。
- 数字选项：Plan 阶段需要用户选择时，使用 `1. 确认并执行`、`2. 调整成员或范围`、`3. 只保留方案不执行` 这类数字选项，用户可以只回复数字。
- 计划阶段多澄清：范围、验收、优先级、设计风格、数据接口、发布约束、风险审批不清楚时主动提问。
- 环境检查：先检查 `AGENTS.md` / `agent.md` / `CLAUDE.md` / `claude.md`，缺失时使用 `references/default-AGENTS.md` 作为默认指南，并建议用户保存为项目根目录 `AGENTS.md`。
- 版本化文档：过程和结果文档全部放入 `.codex/goal-teams/versions/<version>/`。
- 总索引先行：多文档场景先创建 `.codex/goal-teams/INDEX.md` 和版本 `INDEX.md`。
- 需求规格卡先行：需求分析师先通过交谈、网络搜索、computer use、browser/Chrome 能力完善需求，生成不超过两页的人类友好需求规格卡，再由它生成 PRD。
- SPEC First：先补齐 Requirement Specification Card、PRD、Architecture Design、HTML Prototype、Test Plan、Acceptance，再进入开发执行。
- Markdown 持久化：过程和结果优先保存为版本目录内的 `.md` 文件。
- tasklist 协作：如果没有 tasklist，自动创建 `.codex/goal-teams/versions/<version>/tasklist.md`。
- 成员认领任务：每个成员都有 claimed task、locked scope、done criteria。
- 中文成员名：成员展示名称使用角色 + 具体任务名，格式 `<角色>-<任务名>`，例如 `后端-WIKI 列表后端开发`。
- 支持用户指定成员能力：可以指定某个成员使用特定 skill、plugin、自定义 subagent 或内置 subagent 类型。
- OpenSpec/Superpower 兼容：用户指定 `openspec` 或 `superpower` 时，默认只做 Goal Lead，不自动启动完整角色团队。
- 执行过程表格反馈：每轮进度、阻塞、风险、结果都用表格输出。
- 独立测试：实现者不能成为唯一测试者，必须由独立 QA 或测试 skill/subagent 验证。
- 独立校验：所有生成的文档、代码、测试用例都必须由独立 subagent 或用户指定 skill 校验。
- 收尾审计与自动续跑：所有任务看似完成后，由新的 `goal_completion_auditor` 检查未完成工作；若剩余工作仍在已确认目标内，自动再次启动 Goal Teams 并发完成，不需要用户再次确认。
- 安全边界：直接执行和自动续跑都不能绕过新范围、破坏性写入、凭证、支付/认证/安全敏感改动、外部审批或关键业务决策。
- 适合版本并发：可以按版本、模块、交付物、审查视角拆分并发成员。

## 推荐目录结构

安装到 Codex 后，Skill 目录结构如下：

```text
goal-teams/
  VERSION
  SKILL.md
  agents/
    openai.yaml
  references/
    goal-teams-runtime.md
    default-AGENTS.md
  subagents/
    goal-requirements-analyst.toml
    goal-product.toml
    goal-backend.toml
    goal-frontend.toml
    goal-qa.toml
    goal-docs.toml
    goal-reviewer.toml
    goal-completion-auditor.toml
```

项目执行时，Goal Teams 会优先使用或创建下面的运行时文件：

```text
.codex/goal-teams/
  INDEX.md              # 跨版本总索引
  versions/<version>/
    INDEX.md            # 当前版本文档索引，多文档前先建
    plan.md             # 澄清问题、用户回答、假设、确认后的计划
    progress.md         # 每轮执行进展表、阻塞、下一步
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
  team-state.json       # 机器可读团队状态
  events.jsonl          # 执行事件历史
  messages.jsonl        # 问题、阻塞、交接、决策
  doc-capsules.jsonl    # 文档摘要
  member-packets/       # 每个 subagent 的目标包
```

## SPEC 约定

Goal Teams 强制采用 SPEC 驱动流程。缺少文档时，会先补齐或在 tasklist 中安排补齐任务。

| 层级 | 文件 | 说明 |
| --- | --- | --- |
| Index | `.codex/goal-teams/INDEX.md` + `versions/<version>/INDEX.md` | 多文档场景的总索引和版本索引 |
| Requirement Specification Card | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` | 不超过两页的人类友好需求规格卡 |
| PRD | `.codex/goal-teams/versions/<version>/spec/PRD.md` | 基于需求规格卡生成的需求文档 |
| Architecture Design | `.codex/goal-teams/versions/<version>/spec/architecture-design.md` | 架构设计、模块边界、接口、数据、风险 |
| HTML Prototype | `.codex/goal-teams/versions/<version>/spec/HTML-prototype.html` | 页面、流程、交互原型；有页面或工作流时启用 |
| Test Plan | `.codex/goal-teams/versions/<version>/spec/test-plan.md` | 测试范围、策略、命令、验收证据 |
| Acceptance | `.codex/goal-teams/versions/<version>/spec/acceptance.md` | 最终验收清单、证据、剩余风险 |
| Tasklist | `.codex/goal-teams/versions/<version>/tasklist.md` | 成员认领、状态、依赖、验证和文档更新 |

如果项目中已有 `design.md`，Goal Teams 会优先读取它，并在架构设计和 HTML 原型中继承它的风格、术语、章节结构和细节密度。

如果项目中没有 `AGENTS.md` / `agent.md` / `CLAUDE.md` / `claude.md`，Goal Teams 会使用 [default-AGENTS.md](references/default-AGENTS.md) 作为默认执行指南，并建议复制到项目根目录的 `AGENTS.md`。

## 默认团队成员

仓库提供 8 个推荐 subagent 配置：

| Subagent | 角色 | 典型职责 |
| --- | --- | --- |
| `goal_requirements_analyst` | 需求分析师 | 交谈澄清、研究辅助、需求规格卡、PRD 前置输入 |
| `goal_product` | 产品/需求 | 基于需求规格卡生成 PRD、验收标准、原型结构、产品评审 |
| `goal_backend` | 后端开发 | 领域模型、存储、API、CLI、MCP、迁移、集成 |
| `goal_frontend` | 前端开发 | UI、HTML 原型、浏览器验证、E2E、截图验收 |
| `goal_qa` | 测试 | 独立测试、集成测试、验收证据、测试报告 |
| `goal_docs` | 文档 | tasklist、验收文档、README、报告、发布说明 |
| `goal_reviewer` | 评审 | 只读评审、架构边界、安全、覆盖率、兼容性、风险 |
| `goal_completion_auditor` | 收尾审计 | 完成后检查未完成工作、缺失证据、剩余风险，并给出自动续跑任务 |

用户也可以显式指定某个成员使用其他 skill 或 subagent，例如：

```text
用 $goal-teams 规划这个需求。
产品成员使用 goal_product。
前端成员使用 browser skill 做页面验证。
测试成员必须使用独立 goal_qa。
安全审核交给 reviewer subagent。
```

## 工作流

Goal Teams 的标准流程如下：

1. 理解目标：把用户请求转换成可验证的 Done Criteria。
2. 检查环境：查看是否有 `AGENTS.md` / `agent.md` / `CLAUDE.md` / `claude.md`，没有则建议创建。
3. 确认版本：确定 `<version>`，并把过程和结果文档写入版本目录。
4. 创建索引：多文档前先创建或更新总索引和版本索引。
5. 澄清问题：在计划和方案阶段主动询问关键信息。
6. 需求分析：需求分析师通过交谈和必要研究生成需求规格卡。
7. 发现或创建 SPEC：基于需求规格卡补齐 PRD、Architecture Design、HTML Prototype、Test Plan、Acceptance。
8. 发现或创建 tasklist：没有 tasklist 时自动创建 `.codex/goal-teams/versions/<version>/tasklist.md`。
9. 拆分成员：按版本、模块、交付物、评审视角拆分。
10. 表格确认：先展示四列合并的 `Teams 规划表`，再展示环境、索引、SPEC、任务、风险、审批。
11. 中文命名：成员展示名采用 `角色-具体任务名`，例如 `后端-WIKI 列表后端开发`、`测试-WIKI 列表验收测试`。
12. 独立校验计划：为文档、代码、测试用例指定非作者校验者或用户指定 skill。
13. 用户确认或直接执行：默认确认后才开始实现或调用 worker subagents；若用户提示词已包含直接执行类词语，则展示 `执行计划（已按用户要求直接执行）` 后进入执行。
14. 独立执行：每个成员运行自己的 `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue` 循环。
15. 过程持久化：进度、阻塞、决策和结果写入版本目录 Markdown。
16. 独立测试与校验：由 QA、评审成员或用户指定 skill 验证生成内容。
17. 整合收口：Goal Lead 更新 tasklist、SPEC、progress、acceptance。
18. 收尾审计：启动新的 `goal_completion_auditor` 检查未完成工作。
19. 自动续跑：若剩余工作仍在已确认范围内，展示续跑 `Teams 规划表` 后直接并发执行，不再等待用户确认；若涉及新范围或风险决策，则记录阻塞并询问用户。

Plan 阶段等待用户选择时，推荐给出数字选项：

```text
请选择下一步：
1. 确认并执行
2. 调整成员或范围
3. 只保留方案，不执行
```

## 确认表格示例

### SPEC 准备度

| SPEC | 是否存在 | 动作 | Owner | 输出 |
| --- | --- | --- | --- | --- |
| Requirement Specification Card | 否 | 创建 | 需求分析师 | `.codex/goal-teams/versions/<version>/spec/requirement-spec-card.md` |
| PRD | 否 | 创建 | 产品/需求 | `.codex/goal-teams/versions/<version>/spec/PRD.md` |
| Architecture Design | 否 | 创建 | 后端/架构 | `.codex/goal-teams/versions/<version>/spec/architecture-design.md` |
| HTML Prototype | 适用 | 创建 | 前端 | `.codex/goal-teams/versions/<version>/spec/HTML-prototype.html` |
| Test Plan | 否 | 创建 | QA | `.codex/goal-teams/versions/<version>/spec/test-plan.md` |
| Acceptance | 否 | 创建 | 文档/QA | `.codex/goal-teams/versions/<version>/spec/acceptance.md` |

### Teams 规划表

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：需求分析-WIKI 列表需求澄清<br>Skill/Subagent：`goal_requirements_analyst` | 目标切片：梳理 WIKI 列表需求<br>认领任务：GT-001<br>锁定范围：`.codex/goal-teams/versions/<version>/spec/` | 交付物：需求规格卡<br>完成标准：用户确认目标/功能/流程/边界<br>文档/tasklist：requirement-spec-card + INDEX | 测试 Owner：评审-WIKI 列表需求校验<br>校验者：评审-WIKI 列表需求校验 |
| 成员：产品-WIKI 列表 PRD<br>Skill/Subagent：`goal_product` | 目标切片：生成 WIKI 列表 PRD<br>认领任务：GT-002<br>锁定范围：`.codex/goal-teams/versions/<version>/spec/` | 交付物：PRD<br>完成标准：来源于已确认需求规格卡<br>文档/tasklist：PRD + tasklist | 测试 Owner：评审-WIKI 列表 PRD 校验<br>校验者：评审-WIKI 列表 PRD 校验 |
| 成员：后端-WIKI 列表后端开发<br>Skill/Subagent：`goal_backend` | 目标切片：实现 WIKI 列表 API<br>认领任务：GT-003<br>锁定范围：`src/api/wiki/` | 交付物：API 实现<br>完成标准：测试通过并独立校验<br>文档/tasklist：Architecture Design + tasklist | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表代码审查 |
| 成员：前端-WIKI 列表页面开发<br>Skill/Subagent：`goal_frontend` | 目标切片：实现 WIKI 列表页面<br>认领任务：GT-004<br>锁定范围：`src/ui/wiki/` | 交付物：UI/原型<br>完成标准：截图/E2E 通过并独立校验<br>文档/tasklist：HTML Prototype + tasklist | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表体验审查 |
| 成员：测试-WIKI 列表验收测试<br>Skill/Subagent：`goal_qa` | 目标切片：验证交付<br>认领任务：GT-005<br>锁定范围：`tests/wiki/` | 交付物：测试报告<br>完成标准：证据完整，测试用例被独立校验<br>文档/tasklist：Test Plan + Acceptance | 测试 Owner：测试-WIKI 列表验收测试<br>校验者：评审-WIKI 列表测试有效性 |

### 独立校验计划

| 产物 | 作者 | 校验者 | 方法 | 证据 |
| --- | --- | --- | --- | --- |
| 文档 | 产出成员 | 非作者评审成员或用户指定 skill | 结构/事实/验收标准校验 | `progress.md` / `acceptance.md` |
| 代码 | 实现成员 | 独立测试/评审成员或用户指定 skill | 代码审查 + 命令验证 | `progress.md` |
| 测试用例 | 测试成员 | 独立评审成员或用户指定 skill | 断言有效性/边界覆盖校验 | `test-plan.md` / `progress.md` |

### 执行进度

| 成员 | 认领任务 | 状态 | 当前步骤 | 证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| 后端-WIKI 列表后端开发 | GT-003 | 进行中 | Test | `npm test -- wiki` | 更新架构说明 |

## 安装方式

### 安装 Skill

把仓库克隆到 Codex skills 目录：

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

或者如果你已经在本地有 Codex skills 目录，也可以直接复制：

```bash
mkdir -p ~/.codex/skills/goal-teams
cp -R ./SKILL.md ./agents ./references ./subagents ./goal-teams.md ~/.codex/skills/goal-teams/
```

### 安装 Subagents

把 `subagents/` 下的 TOML 文件复制到 Codex agents 目录：

```bash
mkdir -p ~/.codex/agents
cp ./subagents/goal-*.toml ~/.codex/agents/
```

安装后建议重启 Codex 或刷新配置，让 Skill 和 subagents 被重新发现。

### 校验 Skill 包

维护或发布前运行：

```bash
./scripts/check.sh
```

校验脚本会检查必需文件、Skill frontmatter、subagent TOML、README 发布清单、示例产物和关键规则关键词。

### 查看最小示例

`examples/mini-goal-run/` 提供一个最小 Goal Teams 产物树，可用来对照索引、tasklist、SPEC、HTML 原型、验收清单和独立校验记录。

## 使用示例

### 规划一个需求

```text
Use $goal-teams。
请为“分时租赁 V3.0”做 Goal Teams 计划。
先汇报：我是 Goal Teams Leader V1.3，我会帮你完成以下工作：
全程中文，先多问我澄清问题。
过程和结果保存到 V3.0 版本目录的 Markdown。
先生成需求规格卡，再生成 PRD。
```

### 按版本并发

```text
Use $goal-teams。
tasklist 里有 V3.0、V3.1、V3.2 三个版本。
请按版本拆成并发成员，但共享核心模块要串行。
测试必须由独立 QA 成员完成。
```

### 指定成员使用特定能力

```text
Use $goal-teams。
需求分析师用 goal_requirements_analyst。
产品成员用 goal_product。
前端成员用 goal_frontend，并参考 design.md。
测试成员用 goal_qa。
安全审核成员用 goal_reviewer，只读模式。
```

### 只生成方案，不执行

```text
Use $goal-teams。
只生成计划表、SPEC 准备表、成员分工表和风险审批表。
不要修改实现文件。
```

### 使用 OpenSpec 或 Superpower

```text
Use $goal-teams。
这次使用 openspec。
你只做 Goal Lead：帮我检查环境、确认版本目录、创建索引、整理澄清问题和计划，不要自动启动完整角色团队。
```

## CLI 使用示例

可以通过 Codex CLI 在项目目录中运行：

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
Use $goal-teams。

先汇报：我是 Goal Teams Leader V1.3，我会帮你完成以下工作：
全程中文。
Goal Lead 和用户交流要简洁、人类友好，少用专业术语。
先检查 AGENTS.md / agent.md / CLAUDE.md / claude.md，缺失则使用 references/default-AGENTS.md 作为默认指南，并建议保存为项目根目录 AGENTS.md。
生成的文档、代码注释、面向用户的代码字符串、测试名称和测试用例描述默认使用中文。
团队成员展示名使用“角色 + 具体任务名”，格式为 <角色>-<任务名>，例如 后端-WIKI 列表后端开发。
使用版本 "$VERSION"，过程和结果文档写入 .codex/goal-teams/versions/$VERSION/。
多文档前先创建 .codex/goal-teams/INDEX.md 和 .codex/goal-teams/versions/$VERSION/INDEX.md。
先进入 Plan 模式，主动提出澄清问题。
优先把计划、进度、决策和结果写入版本目录 Markdown。
需求分析师先通过交谈和必要的网络搜索、computer use、browser/Chrome 能力完善需求。
先生成不超过两页的需求规格卡，写清核心目标、业务重要功能结构、流程和边界。
再基于需求规格卡生成 PRD。
发现或创建 SPEC：Requirement Specification Card、PRD、Architecture Design、HTML Prototype、Test Plan、Acceptance。
如果没有 tasklist，创建 .codex/goal-teams/versions/$VERSION/tasklist.md。
先列出四列合并展示的 Teams 规划表，确认成员、任务认领、锁定范围、测试 owner、独立校验者和风险审批；如果用户提示词没有直接执行类词语，则等待用户确认。
为所有生成的文档、代码、测试用例指定独立校验者或用户指定 skill。
确认后再执行；如果用户提示词包含“直接执行/不用确认/跳过确认”，展示执行计划后直接执行。每个成员必须是独立 subagent。
测试必须由独立 QA 或测试 skill/subagent 完成。
所有任务看似完成后，启动 goal_completion_auditor 检查未完成工作；若剩余工作仍在已确认目标范围内，自动拆成续跑任务并并发执行，不再等待用户确认。
PROMPT
```

如果你想跳过首次确认，可以在提示词里加入直接执行类词语：

```text
Use $goal-teams。
请直接执行：为 WIKI 列表 V1.3 规划并实现后端 API、前端页面、独立测试和验收文档。
仍然先展示 Teams 规划表作为执行记录，但不用等我确认。
```

只做规划可以使用只读沙箱：

```bash
codex exec \
  -C "$PROJECT" \
  --sandbox read-only \
  --json \
  'Use $goal-teams。全程中文，只做 Goal Lead，检查环境，询问版本号，创建索引计划，只生成计划和确认表格，不修改实现文件。'
```

## 与普通 Agent Teams 的区别

| 维度 | Agent Teams | Goal Teams |
| --- | --- | --- |
| 目标 | 通用多 agent 协作 | 面向目标闭环的多 subagent 执行 |
| 计划 | 可选 | 强制 Plan 模式 |
| SPEC | 可选 | 强制 SPEC First |
| tasklist | 可选 | 没有就创建 |
| 持久化 | 视情况 | 按版本目录优先 Markdown 持久化 |
| 测试 | 可由实现者执行 | 必须独立测试 |
| 校验 | 可选 | 文档、代码、测试用例都要独立校验 |
| 收尾 | 可选 | 完成后由 `goal_completion_auditor` 审计，必要时自动续跑 |
| 反馈 | 可自由组织 | 表格化进度和结果 |
| 适用场景 | 协同分析、研究、开发 | 需求到交付的完整闭环 |

## 适合场景

- 产品需求从 0 到 1 规划和落地。
- 需求还不清楚，需要先通过交谈和研究生成一张清晰需求规格卡。
- 多模块开发，需要前端、后端、测试、文档并行推进。
- 多版本并行，例如 V3.0、V3.1、V3.2 分 lane 执行。
- 需要沉淀 PRD、架构设计、原型、测试计划、验收文档。
- 需要分享给团队或做复盘，要求过程有记录。
- 代码审计、安全审核、架构评审需要独立视角。
- 需要把 Codex CLI、tasklist、dashboard 或本地项目状态结合起来。

## 不适合场景

- 很小的单文件修改。
- 强顺序、强共享上下文、无法拆分的任务。
- 用户只想快速问答，不需要计划、SPEC 或持久化。
- 无法接受计划阶段澄清成本的极短任务。若只是想减少确认成本，可在提示词中写“直接执行”。

## 安全与协作规则

- 默认不在未确认计划前启动实现 subagents；如果用户明确写了“直接执行/不用确认/跳过确认”，可以在展示执行计划后直接启动。
- 使用 OpenSpec 或 Superpower 时默认只做 Goal Lead，不自动启动完整角色团队。
- 如果没有 AGENTS/CLAUDE 指南文件，使用 `references/default-AGENTS.md` 作为默认指南。
- 生成内容默认中文，包括文档、代码注释、测试名称和测试用例描述。
- 团队成员展示名使用“角色 + 具体任务名”，例如 `后端-WIKI 列表后端开发`。
- 多文档前先创建总索引和版本索引。
- 过程和结果文档必须进入版本目录。
- PRD 前先完成需求规格卡，除非用户明确要求跳过。
- 所有生成的文档、代码、测试用例都必须由独立 subagent 或用户指定 skill 校验。
- 最终完成前必须由新的 `goal_completion_auditor` 做只读收尾审计。
- 对已确认目标范围内的未完成工作自动续跑，不再等待用户确认。
- Plan 阶段给用户选择时优先使用数字选项，允许用户只回复 `1`、`2`、`3`。
- 不让多个成员同时修改共享核心模块。
- 不跳过 Requirement Specification Card、PRD、Architecture Design、HTML Prototype、Test Plan、Acceptance 的适用性判断。
- 不让实现者成为唯一测试者。
- 不允许成员创建嵌套团队，默认 `max_depth = 1`。
- 涉及新范围、认证、支付、退款、迁移、破坏性写入、安全敏感集成或大范围 API 改造时，必须由 Goal Lead 和用户确认。

## 发布状态

当前仓库包含：

- `SKILL.md`：Goal Teams Skill 主说明。
- `VERSION`：当前 Skill 版本号。
- `agents/openai.yaml`：Codex UI 元数据。
- `references/goal-teams-runtime.md`：运行时协议、模板、CLI 示例。
- `references/default-AGENTS.md`：缺失项目指南时使用的默认中文 AGENTS 模板。
- `subagents/goal-*.toml`：8 个推荐成员 subagent 配置。
- `goal-teams.md`：维护本 skill 时必须对齐的长期用户指定要求。
- `AGENTS.md`：本仓库维护指南。
- `scripts/check.sh`：一键校验入口。
- `scripts/validate.py`：Skill 包结构与规则校验脚本。
- `examples/mini-goal-run/`：最小 Goal Teams 产物示例。
- `CHANGELOG.md`：版本变更记录。
- `README.md`：中文 README。
- `README.en.md`：英文 README。

## License

如需开源发布，建议后续补充明确的 License 文件，例如 MIT、Apache-2.0 或内部共享协议。
