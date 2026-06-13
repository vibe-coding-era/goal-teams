[English](README.en.md) | 中文

# Goal Teams

作者：肉山@TGO 杭州

当前版本：`V1.9`

`goal-teams` 是一个面向 Codex 的 Goal Mode 团队化 Skill。它把一个目标拆成 Goal Lead 统筹、多个独立 subagent 或用户指定 skill 分工执行的闭环：先澄清和规划，再按 workflow 串并行推进，最后由独立校验和收尾审计确认没有遗漏。

## 核心模型

每次启动先汇报：

```text
我是 Goal Teams Leader V1.9，我会帮你完成以下工作：
```

中文核心模型要点提示词：

```text
默认全程中文输出计划、表格、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。
```

Goal Teams 的核心工作方式：

- Goal Lead 负责澄清目标、拆解任务、确认 workflow、分配成员、整合结果和处理阻塞。
- Plan 模式下，启动语和本轮事项之后先问：`在开始规划前，有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“没有”。`
- 默认 subagent 成员的运行时 subagent id、`member_id` 和展示名使用 `<中文角色>-<具体任务名>`，例如 `后端-WIKI 列表后端开发`；真实可加载的 subagent 配置名保留在 `skill_or_subagent`，例如 `goal_backend`。
- 如果用户指定了 skill，运行时 subagent id、`member_id`、展示名和 `role` 使用 skill 名称作为前缀，例如 `browser-WIKI 列表页面验证`。
- 每个任务都必须说明 workflow 是串行还是并行；串行任务要列出前置任务，避免共享范围被并发修改。
- `SPEC` 定义完成条件，`Harness` 定义验证契约，`Evidence` 记录可追溯证据，`Pipeline` 记录研发/发布状态，`Benchmark` 定义外层评估任务集，`Loop` 定义成员、Lead 和 Skill Improvement 三层循环。
- Harness 不是新的 runtime 执行器；它表现为 Plan、tasklist、Member Goal Packet、test plan 和 acceptance 中的检查、命令、人工清单、证据路径和失败报告格式。
- V1.8 提供机器可读协议模板：`harness.yaml`、`evidence.jsonl`、`pipeline-state.json`、`failure_report`、`approval_gate`。
- V1.9 提供生产流协议：`Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`，并要求凭证、真实部署、破坏性操作和生产回滚停在人工或外部授权门前。
- Benchmark 默认不属于普通 Goal Teams 产物；只有用户要求、计划确认或 Skill Improvement 任务需要时，才创建或更新 `benchmarks/`。
- 默认先展示 `Teams 规划表` 等用户确认；如果用户提示词包含 `直接执行`、`不用确认`、`跳过确认` 等词，则展示执行计划后直接进入执行。
- Plan 阶段需要用户选择时使用数字选项，例如 `1. 确认并执行`、`2. 调整成员或范围`、`3. 只保留方案不执行`。
- 所有生成文档、代码变更和测试用例都需要独立校验；实现者不能成为唯一测试者。
- 看似完成后启动新的 `goal_completion_auditor` 做只读收尾审计；已确认范围内的未完成工作会自动续跑，不再要求用户再次确认。
- 最终完成汇报用表格说明每个任务或 subagent 的状态，并在同一列记录 `资源消耗（用户 / tokens / 费用）`；运行时没有返回时写 `未提供`。

## 标准流程

1. 理解目标，把用户请求转成可验证的 Done Criteria。
2. 询问历史文档、历史经验或参考资料输入，并把回答写入 Plan 假设。
3. 检查 `AGENTS.md` / `agent.md` / `CLAUDE.md` / `claude.md`；缺失时使用 `references/default-AGENTS.md` 作为默认指南。
4. 确认版本，把过程和结果写入 `.codex/goal-teams/versions/<version>/`。
5. 多文档前先创建或更新 `.codex/goal-teams/INDEX.md` 和版本 `INDEX.md`。
6. 补齐 SPEC：Requirement Specification Card、PRD、Architecture Design、HTML Prototype、Test Plan、Acceptance。
7. 为每个任务写清 Harness 契约；不适用时写明原因。
8. 判断 Benchmark 是否适用；普通任务默认不创建 `benchmarks/`。
9. 发现或创建 `.codex/goal-teams/versions/<version>/tasklist.md`。
10. 展示四列 `Teams 规划表`：成员与能力、任务范围、交付与标准、验证安排。
11. 根据确认或直接执行语义启动独立成员，按 locked scope、Harness 和 workflow 推进。
12. 将计划、进度、决策、测试证据和验收结果写入版本目录 Markdown。
13. 完成后由 `goal_completion_auditor` 审计；需要续跑时只处理已确认目标范围内的剩余工作。

## Teams 规划表

表格只做四列展示，但每行必须保留成员、skill/subagent、目标切片、认领任务、workflow、前置任务、锁定范围、交付物、完成标准、Harness、文档/tasklist 更新、测试 Owner 和校验者。

| 成员 / Skill(Subagent) | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：`需求分析-WIKI 列表需求澄清`<br>Skill/Subagent：`goal_requirements_analyst` | 目标切片：梳理 WIKI 列表需求<br>认领任务：GT-001<br>Workflow：串行<br>前置任务：-<br>锁定范围：`spec/` | 交付物：需求规格卡<br>完成标准：用户确认目标、流程和边界<br>Harness：结构和边界清单审查<br>文档/tasklist：requirement-spec-card + INDEX | 测试 Owner：`评审-WIKI 列表需求校验`<br>校验者：`评审-WIKI 列表需求校验` |
| 成员：`后端-WIKI 列表后端开发`<br>Skill/Subagent：`goal_backend` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行<br>前置任务：GT-001, GT-002<br>锁定范围：`src/api/wiki/` | 交付物：后端实现<br>完成标准：API 合同测试通过<br>Harness：API 合同测试 + 回归测试<br>文档/tasklist：Architecture Design + tasklist.md | 测试 Owner：`测试-WIKI 列表验收测试`<br>校验者：`评审-WIKI 列表代码审查` |
| 成员：`browser-WIKI 列表页面验证`<br>Skill/Subagent：`browser` skill | 目标切片：页面验证<br>认领任务：GT-004<br>Workflow：并行<br>前置任务：GT-003<br>锁定范围：`src/ui/wiki/` | 交付物：截图和控制台检查<br>完成标准：桌面/移动验证通过<br>Harness：截图 + console error + viewport 检查<br>文档/tasklist：HTML Prototype + tasklist.md | 测试 Owner：`测试-WIKI 列表验收测试`<br>校验者：`评审-WIKI 列表体验审查` |

最终完成汇报示例：

| 成员 | 认领任务 | Workflow / 前置任务 | 状态 | 证据 | 资源消耗（用户 / tokens / 费用） | 剩余 |
| --- | --- | --- | --- | --- | --- | --- |
| `后端-WIKI 列表后端开发` | GT-003 | 串行 / GT-001, GT-002 | done | `npm test -- wiki` | 用户：Rou；tokens：未提供；费用：未提供 | 无 |

## 目录结构

安装后的 Skill 包包含：

```text
goal-teams/
  VERSION
  SKILL.md
  goal-teams.md
  AGENTS.md
  CHANGELOG.md
  README.md
  README.en.md
  agents/openai.yaml
  references/goal-teams-runtime.md
  references/default-AGENTS.md
  references/goal-teams-automation-protocol.md
  references/goal-teams-production-pipeline.md
  scripts/check.sh
  scripts/validate.py
  subagents/goal-*.toml
  examples/mini-goal-run/
  benchmarks/
```

运行目标时，项目中会优先使用或创建：

```text
.codex/goal-teams/
  INDEX.md
  versions/<version>/
    INDEX.md
    plan.md
    progress.md
    decisions.md
    tasklist.md
    goal-packet.md
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
  team-state.json
  events.jsonl
  messages.jsonl
  doc-capsules.jsonl
  member-packets/
```

## 默认成员

| Subagent ID / 角色名 | 主要职责 |
| --- | --- |
| `goal_requirements_analyst` | 澄清目标、调研辅助、需求规格卡、PRD 前置输入 |
| `goal_product` | PRD、验收标准、原型结构、产品评审 |
| `goal_backend` | 领域模型、存储、API、CLI、MCP、迁移、集成 |
| `goal_frontend` | UI、HTML 原型、浏览器验证、E2E、截图证据 |
| `goal_qa` | 独立测试、集成测试、验收证据、测试报告 |
| `goal_docs` | tasklist、acceptance、README、报告、发布说明 |
| `goal_reviewer` | 只读评审、架构边界、安全、覆盖率、兼容性、风险 |
| `goal_completion_auditor` | 收尾审计、未完成工作检查、自动续跑建议 |

## 安装

克隆到 Codex skills 目录：

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

复制 subagents：

```bash
mkdir -p ~/.codex/agents
cp ~/.codex/skills/goal-teams/subagents/goal-*.toml ~/.codex/agents/
```

维护或发布前运行：

```bash
./scripts/check.sh
```

`examples/mini-goal-run` 提供最小产物树，可用于检查索引、SPEC、tasklist、Teams 规划表、独立校验和收尾审计是否齐全。`goal-teams.md` 记录长期用户指定要求，是维护时的上游依据。

`examples/mini-goal-run` 还包含 `harness/` 复盘资料，展示 `setup -> run -> checks -> report` 的最小静态链路，并提供 automation protocol、evidence ledger 和 pipeline gates 静态样本。`benchmarks/` 提供 `GT-BENCH-001` 与 `GT-BENCH-002` 模板，用于比较 baseline 与 Goal Teams 的产物质量、证据完整度、生产门禁判断和成本。

## 使用示例

规划并等待确认：

```text
Use $goal-teams。
请为“分时租赁 V3.0”做 Goal Teams 计划。
过程和结果保存到 V3.0 版本目录。
先生成需求规格卡，再生成 PRD。
```

直接执行：

```text
Use $goal-teams。
请直接执行：为 WIKI 列表 V1.9 规划并实现后端 API、页面验证、独立测试和验收文档。
仍然先展示 Teams 规划表作为执行记录，但不用等我确认。
```

指定成员能力：

```text
Use $goal-teams。
需求分析使用 goal_requirements_analyst。
页面验证使用 browser skill。
测试成员使用 goal_qa。
安全审核使用 goal_reviewer，只读模式。
```

## 发布内容

当前仓库发布内容包括 `VERSION`、`SKILL.md`、`agents/openai.yaml`、`references/goal-teams-runtime.md`、`references/default-AGENTS.md`、`references/goal-teams-automation-protocol.md`、`references/goal-teams-production-pipeline.md`、`subagents/goal-*.toml`、`goal-teams.md`、`AGENTS.md`、`scripts/check.sh`、`scripts/validate.py`、`examples/mini-goal-run`、`benchmarks/`、`CHANGELOG.md`、`README.md` 和 `README.en.md`。

## License

如需开源发布，建议后续补充明确的 License 文件，例如 MIT、Apache-2.0 或内部共享协议。
