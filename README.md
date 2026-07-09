[English](README.en.md) | 中文

# Goal Teams

作者：肉山@TGO 杭州

当前版本：`V2.2`

`goal-teams` 是一个面向 Codex 的 Goal Mode 团队化 Skill。它把一个目标拆成 Goal Lead 统筹、多个独立 subagent 或用户指定 skill 分工执行的闭环：先澄清和规划，再按 workflow 串并行推进，最后由独立校验和收尾审计确认没有遗漏。

## 核心模型

每次启动先汇报：

```text
我是 Goal Teams Leader V2.2，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，并使用 Harness + SPEC 做为过程与结果产物的约束：
```

中文核心模型要点提示词：

```text
默认全程中文表格化输出计划、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。
```

## 规则入口

- `SKILL.md` 是触发导向入口，保留启动语、7 条不变量、规划检查、失败降级摘要和渐进式加载路由。
- `references/invariants.md` 保存永远生效的不变量、硬边界和失败降级协议。
- `references/compat.md` 集中说明 `TaskList.md`/`tasklist.md`、脚本兼容入口、成员包布局和版本说明。
- `references/rules-ui.md`、`references/rules-testing.md`、`references/rules-loop.md` 分别按 UI、测试和长任务续跑场景加载。
- `prompts/packets/handoff-artifacts.md` 是交接物 SSOT；`RULES.md` 是 Goal Lead 和成员的响应规范。

## 标准流程

1. 将用户目标转成 Done Criteria，确认项目版本、artifact version 和输出目录。
2. 创建或更新 `GoalTeamsWork-<project_version>/`、`memory.md` 和 `versions/<artifact_version>/TaskList.md`。
3. 写入 `spec/requirement-card.md`，再补齐必要 SPEC、架构、测试计划和验收文档。
4. 按任务类型加载 UI、测试或 LOOP 条件规则，生成 `Teams 规划表`。
5. 派发独立成员，所有成员按 locked scope、Harness、交接物和独立校验推进。
6. 整合证据，更新 TaskList、progress、acceptance 和必要的 `Loop Decision`。
7. 完成前启动 `goal_completion_auditor`；已确认范围内缺口按 Lead LOOP 续跑，越界问题记录阻塞。

## Teams 规划表

表格只做四列展示，但每行必须保留成员、skill/subagent、目标切片、认领任务、workflow、前置任务、锁定范围、交接物、artifact_type、Owner subagent、validator subagent、交接状态、检查状态、完成标准、Harness、文档/tasklist 更新、测试 Owner 和校验者。

| 成员 / Skill(Subagent) | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：`需求分析-WIKI 列表需求澄清`<br>Skill/Subagent：`goal_requirements_analyst` | 目标切片：梳理 WIKI 列表需求<br>认领任务：GT-001<br>Workflow：串行<br>前置任务：-<br>锁定范围：`spec/` | 交接物：需求规格卡（`requirement_spec_card`）<br>完成标准：用户确认目标、流程和边界<br>Harness：结构和边界清单审查<br>tasklist：Owner=`goal_requirements_analyst`，状态=`planned` | 测试 Owner：`评审-WIKI 列表需求校验`<br>校验者：`评审-WIKI 列表需求校验`<br>检查状态：`not_started` |
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
  RULES.md
  CHANGELOG.md
  README.md
  README.en.md
  agents/openai.yaml
  references/goal-teams-runtime.md
  references/default-AGENTS.md
  references/invariants.md
  references/compat.md
  references/rules-ui.md
  references/rules-testing.md
  references/rules-loop.md
  references/goal-teams-automation-protocol.md
  references/goal-teams-production-pipeline.md
  references/goal-teams-scripted-tooling.md
  references/google-okf-bilingual-spec.md
  references/ui-e2e-pixel-protocol.md
  references/ui-visual-contract-protocol.md
  references/subagent-dispatch-protocol.md
  references/dual-review-protocol.md
  prompts/lead/*.md
  prompts/packets/handoff-artifacts.md
  prompts/packets/page-spec-card.md
  prompts/packets/memory.md
  prompts/packets/html-prototype-mock.md
  prompts/members/shared.md
  prompts/members/<role>/prompt.md
  prompts/members/<role>/template.md
  prompts/members/<role>/workflow.md
  prompts/members/<role>/scripts.md
  prompts/packets/*.md
  scripts/check.sh
  scripts/validate.py
  scripts/install-local.sh
  scripts/check-version-sync.py
  scripts/check-routing-fixtures.py
  scripts/check-agent-names.py
  scripts/validate-harness.py
  scripts/pixel-diff.py
  scripts/compare-artifacts.py
  scripts/validate-dual-review.py
  scripts/check-member-layout.py
  scripts/benchmark-runner.py
  scripts/checks/*.py
  scripts/checks/check.sh
  scripts/harness/*.py
  scripts/review/*.py
  scripts/benchmark/*.py
  scripts/install/install-local.sh
  subagents/goal-*.toml
  examples/mini-goal-run/
  benchmarks/
```

运行目标时，项目中会优先使用或创建：

```text
GoalTeamsWork-<project_version>/
  index.md
  memory.md
  versions/
    <artifact_version>/
      index.md
      TaskList.md
      tasklist.md
      plan.md
      progress.md
      decisions.md
      goal-packet.md
      spec/
        requirement-card.md
        requirement-spec-card.md
        PRD.md
        page-spec-card.md
        frontend-architecture-design.md
        backend-architecture-design.md
        HTML-prototype.html
        test-plan.md
        acceptance.md
      tests/
        unit/
        api-integration/
        e2e/
        reports/
      artifacts/
      harness.yaml
      evidence.jsonl
      pipeline-state.json
```

## 默认成员

| Subagent ID / 角色名 | 主要职责 |
| --- | --- |
| `goal_requirements_analyst` | 澄清目标、调研辅助、需求规格卡、PRD 前置输入 |
| `goal_product` | PRD、验收标准、原型结构、产品评审 |
| `goal_backend` | 领域模型、存储、API、CLI、MCP、迁移、集成 |
| `goal_frontend` | UI、HTML 原型、浏览器验证、E2E、复刻像素级对比、截图证据 |
| `goal_unit_test_designer` | 后端 TDD 单元测试用例、断言、覆盖说明 |
| `goal_unit_test_runner` | 后端 TDD 单元测试执行、红绿证据、失败报告 |
| `goal_api_integration_test_designer` | API 集成测试脚本和测试矩阵，默认 Python + pytest |
| `goal_api_integration_test_runner` | API 集成测试执行、日志、报告和失败响应 |
| `goal_e2e_test_designer` | 前端完成后的 E2E 测试用例、viewport 和组件断言 |
| `goal_e2e_test_runner` | E2E 执行、截图、trace、console/network 证据 |
| `goal_qa` | 独立测试、集成测试、界面 E2E、像素级对比验收、测试报告 |
| `goal_docs` | tasklist、acceptance、README、报告、发布说明 |
| `goal_reviewer` | 只读评审、架构边界、安全、覆盖率、兼容性、风险 |
| `goal_completion_auditor` | 收尾审计、未完成工作检查、自动续跑建议 |

## 安装

克隆到 Codex skills 目录：

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

或直接运行本地安装脚本：

```bash
./scripts/install-local.sh --update-team-fallback
```

手动复制 subagents：

```bash
mkdir -p ~/.codex/agents
cp ~/.codex/skills/goal-teams/subagents/goal-*.toml ~/.codex/agents/
```

维护或发布前运行：

```bash
./scripts/check.sh
```

`examples/mini-goal-run` 提供最小产物树，可用于检查索引、SPEC、tasklist、Teams 规划表、独立校验和收尾审计是否齐全。`goal-teams.md` 记录长期用户指定要求，是维护时的上游依据。

`examples/mini-goal-run` 还包含 `harness/` 复盘资料，展示 `setup -> run -> checks -> report` 的最小静态链路，并提供 automation protocol、evidence ledger 和 pipeline gates 静态样本。`benchmarks/` 提供 `GT-BENCH-001`、`GT-BENCH-002`、`GT-BENCH-003` 和 `GT-BENCH-004` 模板，用于比较 baseline 与 Goal Teams 的产物质量、证据完整度、生产门禁判断、UI 证据处理、Lead LOOP 状态恢复和成本。

V1.92 新增 `references/goal-teams-scripted-tooling.md`、`references/ui-e2e-pixel-protocol.md` 和 `references/subagent-dispatch-protocol.md`，并提供 `GT-BENCH-003` 用于验证 UI E2E、复刻像素级对比和证据不足打回。

V1.93 新增 `prompts/lead/`、`prompts/members/`、`prompts/packets/`，并将真实脚本迁入 `scripts/checks/`、`scripts/harness/`、`scripts/benchmark/` 和 `scripts/install/`；`scripts/check.sh` 等旧入口保持可用。

V1.94 新增成员包子目录、`references/dual-review-protocol.md`、`prompts/packets/dual-review-record.md`、`scripts/checks/check-member-layout.py`、`scripts/review/compare-artifacts.py` 和 `scripts/review/validate-dual-review.py`。对比和校验类任务必须同时有脚本复核证据和 LLM reviewer 复核证据。

V1.95 新增 `prompts/lead/requirement-card.md` 和 `prompts/packets/requirement-card.md`，要求 Plan 模式先写入 `spec/requirement-card.md`，用简洁方案讲清核心目标、关键功能、边界、约束和风险。

V1.96 新增用户故事和功能验收标准要求：需求卡片先写“作为...我想要...以便...”格式的用户故事，并给出可验证的功能验收标准；后续 PRD、tasklist、Harness、test plan 和 acceptance 必须承接。

V1.97 新增 `references/google-okf-bilingual-spec.md`、`prompts/packets/page-spec-card.md`、`prompts/packets/memory.md`、`prompts/packets/html-prototype-mock.md`，并强化 `references/ui-visual-contract-protocol.md` 与 `references/ui-e2e-pixel-protocol.md`。所有生成 Markdown 文档默认采用 OKF；无指定目录时写入 `GoalTeamsWork-<project_version>/`；页面规格卡和 HTML 原型必须记录组件库名称、版本、来源、元素级组件库归属和必要数据模型。

V2.2 新增精简入口、条件加载 rules、路由 fixtures、文件级规则校验和 README 瘦身，用于降低前置上下文和维护风险。

V2.2 维护结构将 `SKILL.md` 收缩为触发导向入口和加载路由，新增 `references/invariants.md`、`references/compat.md`、`references/rules-ui.md`、`references/rules-testing.md` 和 `references/rules-loop.md`，用于按场景加载不变量、兼容口径、UI、测试和 LOOP 规则。

V2.1 新增 `prompts/lead/loop.md`、Lead LOOP Protocol、Loop Decision、Loop Gate、状态快照规则和 `GT-BENCH-004`，用于评估中途缺证、自动续跑、停止边界和状态恢复。

版本说明：当前版本以 `VERSION` 为准；历史 `V2.02` 与 `V2.1` 是 `V2.2` 前的补丁线，后续版本优先使用 `V2.3`、`V2.4` 这类递增格式。

V2.02 新增 `RULES.md` 响应规范，要求 Goal Lead 和所有成员执行优先、事实优先、未验证不宣称完成、减少无关解释。

V2.01 更新启动语，明确使用 Goal + Plan 模式完成规划、执行和应用交付，并要求使用 Harness + SPEC 作为过程与结果产物约束；Plan 历史资料输入支持 `没有请回复“2”`，中文输出规则强调表格化。

V2.0 新增版本子目录 SSOT、TaskList 先行、后端架构先行、独立 TDD 单测用例/执行、API 集成测试脚本/执行和前端 E2E 用例/执行规则，并新增对应 subagent 成员包和 `goal_*.toml`。

## 使用示例

规划并等待确认：

```text
Use $goal-teams。
请为“分时租赁 V3.0”做 Goal Teams 计划。
过程和结果保存到 `GoalTeamsWork-V3.0/`。
先生成带用户故事和功能验收标准的需求卡片，再生成需求规格卡和 PRD。
```

直接执行：

```text
Use $goal-teams。
请直接执行：为 WIKI 列表 V2.0 规划并实现后端 API、页面验证、独立测试和验收文档。
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

当前仓库发布内容包括 `VERSION`、`SKILL.md`、`RULES.md`、`agents/openai.yaml`、`references/goal-teams-runtime.md`、`references/default-AGENTS.md`、`references/invariants.md`、`references/compat.md`、`references/rules-ui.md`、`references/rules-testing.md`、`references/rules-loop.md`、`references/goal-teams-automation-protocol.md`、`references/goal-teams-production-pipeline.md`、`references/goal-teams-scripted-tooling.md`、`references/google-okf-bilingual-spec.md`、`references/ui-e2e-pixel-protocol.md`、`references/ui-visual-contract-protocol.md`、`references/subagent-dispatch-protocol.md`、`references/dual-review-protocol.md`、`prompts/lead/core.md`、`prompts/lead/loop.md`、`prompts/lead/requirement-card.md`、`prompts/members/shared.md`、`prompts/members/backend/prompt.md`、`prompts/members/backend/template.md`、`prompts/members/backend/workflow.md`、`prompts/members/backend/scripts.md`、`prompts/members/unit-test-designer/prompt.md`、`prompts/members/unit-test-runner/prompt.md`、`prompts/members/api-integration-test-designer/prompt.md`、`prompts/members/api-integration-test-runner/prompt.md`、`prompts/members/e2e-test-designer/prompt.md`、`prompts/members/e2e-test-runner/prompt.md`、`prompts/packets/member-goal-packet.md`、`prompts/packets/handoff-artifacts.md`、`prompts/packets/page-spec-card.md`、`prompts/packets/memory.md`、`prompts/packets/html-prototype-mock.md`、`prompts/packets/requirement-card.md`、`prompts/packets/dual-review-record.md`、`subagents/goal-*.toml`、`goal-teams.md`、`AGENTS.md`、`scripts/check.sh`、`scripts/validate.py`、`scripts/install-local.sh`、`scripts/check-version-sync.py`、`scripts/check-routing-fixtures.py`、`scripts/check-agent-names.py`、`scripts/check-member-layout.py`、`scripts/validate-harness.py`、`scripts/pixel-diff.py`、`scripts/compare-artifacts.py`、`scripts/validate-dual-review.py`、`scripts/benchmark-runner.py`、`scripts/checks/`、`scripts/checks/check-routing-fixtures.py`、`scripts/harness/`、`scripts/review/`、`scripts/benchmark/`、`scripts/install/`、`prompts/`、`examples/mini-goal-run`、`benchmarks/`、`CHANGELOG.md`、`README.md` 和 `README.en.md`。

## License

如需开源发布，建议后续补充明确的 License 文件，例如 MIT、Apache-2.0 或内部共享协议。
