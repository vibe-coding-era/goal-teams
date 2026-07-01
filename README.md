[English](README.en.md) | 中文

# Goal Teams

作者：肉山@TGO 杭州

当前版本：`V2.01`

`goal-teams` 是一个面向 Codex 的 Goal Mode 团队化 Skill。它把一个目标拆成 Goal Lead 统筹、多个独立 subagent 或用户指定 skill 分工执行的闭环：先澄清和规划，再按 workflow 串并行推进，最后由独立校验和收尾审计确认没有遗漏。

## 核心模型

每次启动先汇报：

```text
我是 Goal Teams Leader V2.01，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，并使用 Harness + SPEC 做为过程与结果产物的约束：
```

中文核心模型要点提示词：

```text
默认全程中文表格化输出计划、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。
```

核心规则：

- SSOT 是核心规则：交接物类型、Owner subagent、validator subagent、状态字段和 tasklist 账本格式以 `prompts/packets/handoff-artifacts.md` 为 Single Source of Truth。
- 任何角色 workflow、template、README、runtime 示例或 Member Goal Packet 提到交接物时，都必须引用或同步这份 SSOT，不得另起一套交接物口径。
- 执行过程中必须把每个交接物写入 tasklist，包含 Owner subagent、validator subagent、完成状态、独立检查状态、Harness、证据路径和阻塞/延期原因。

Goal Teams 的核心工作方式：

- Goal Lead 负责澄清目标、拆解任务、确认 workflow、分配成员、整合结果和处理阻塞。
- Plan 模式下，启动语和本轮事项之后先问：`在开始规划前，如果有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“2”。`
- Plan 模式接到需求后，先写入 `需求卡片`，用简洁方案说明核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险，再进入完整 SPEC、tasklist 和 Teams 规划表。
- 默认 subagent 成员的运行时 subagent id、`member_id` 和展示名使用 `<中文角色>-<具体任务名>`，例如 `后端-WIKI 列表后端开发`；真实可加载的 subagent 配置名保留在 `skill_or_subagent`，例如 `goal_backend`。
- 如果用户指定了 skill，运行时 subagent id、`member_id`、展示名和 `role` 使用 skill 名称作为前缀，例如 `browser-WIKI 列表页面验证`。
- V1.91 默认优先使用 `goal_*` 自定义 subagents；如果运行时或 Codex 右边栏显示 `Reviewer C`、`QA B` 这类英文昵称，只当作 transport handle，用户可见表格、packet、state 和最终汇报仍使用中文成员名。
- 每个任务都必须说明 workflow 是串行还是并行；串行任务要列出前置任务，避免共享范围被并发修改。
- `SPEC` 定义完成条件，`Harness` 定义验证契约，`Evidence` 记录可追溯证据，`Pipeline` 记录研发/发布状态，`Benchmark` 定义外层评估任务集，`Loop` 定义成员、Lead 和 Skill Improvement 三层循环。
- Harness 不是新的 runtime 执行器；它表现为 Plan、tasklist、Member Goal Packet、test plan 和 acceptance 中的检查、命令、人工清单、证据路径和失败报告格式。
- 任何界面级任务必须做 E2E 测试；复刻、临摹或还原任务必须截图做像素级对比，并记录基准图、实际图、diff 图或差异指标、阈值、viewport 和结论。
- V1.92 采用提示词 + 脚本混合模式：提示词负责目标理解、调度、冲突、预算和风险判断；脚本负责版本同步、agent 命名、Harness schema、像素 diff、benchmark 包检查和本地安装。
- V1.93 将 `SKILL.md` 收缩为核心问题和渐进式加载入口；Lead、成员角色和 packet 模板提示词分目录放入 `prompts/`，脚本按职责放入 `scripts/checks/`、`scripts/harness/`、`scripts/benchmark/` 和 `scripts/install/`，根脚本保留兼容入口。
- V1.94 将 `prompts/members/` 拆成角色成员包，每个成员目录包含 `prompt.md`、`template.md`、`workflow.md` 和 `scripts.md`；对比和校验类任务必须采用 LLM + 脚本双重复核。
- V1.95 新增 Plan 模式 `需求卡片`，默认写入 `GoalTeamsWork-<project_version>/spec/requirement-card.md`，作为后续 Requirement Specification Card、PRD、tasklist 和 Harness 的输入。
- V1.96 要求需求卡片、需求规格卡和 PRD 都承接用户故事与功能验收标准，并让功能验收标准流向 tasklist、Harness、test plan 和 acceptance。
- V1.97 要求所有生成 Markdown 文档默认采用 Google OKF；未指定生成目录时输出到 `GoalTeamsWork-<project_version>/`，并维护 `memory.md`。
- V2.0 要求所有 SSOT 产出物写入 `GoalTeamsWork-<project_version>/versions/<artifact_version>/`；每个项目先生成 `TaskList.md`；后端先架构设计再 TDD/开发；API 集成测试默认 Python + pytest；前端 E2E 用例生成和执行使用独立 subagent。
- UI 页面、复刻、还原、截图对齐或前端交互页面必须在 PRD 后生成 `page-spec-card.md`，再进入 HTML Prototype MOCK、静态页面开发或动态前端页面开发。
- 页面原型任务必须先澄清组件库名称、版本、URL 或 Git 仓库；已提供时写入 `memory.md`、页面规格卡和 HTML OKF 元数据。
- UI 视觉防漏协议要求不能只依赖整页 pixel diff；视觉锁层/overlay 必须提供 locked 和 unlocked real DOM 双证据；关键组件必须有组件级视觉契约和可执行断言。
- 长任务、自动续跑、生产流、Benchmark、浏览器 E2E 或像素对比任务必须记录 Budget Gate 和 Conflict Policy；证据不足不能完成。
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
4. 确认项目版本、artifact version 和输出目录；未指定时把输出根目录设为 `GoalTeamsWork-<project_version>/`。
5. 多文档前先创建或更新根 `index.md`、`memory.md`，再创建版本子目录 `versions/<artifact_version>/TaskList.md`。
6. 写入需求卡片：核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险。
7. 补齐 SPEC：Requirement Specification Card、PRD、Backend/Frontend Architecture Design、HTML Prototype、Test Plan、Acceptance。
8. UI 页面任务在 PRD 后补齐 Page Specification Card，再进入 HTML Prototype 或前端实现；不适用时写明原因。
9. 为每个任务写清 Harness 契约；不适用时写明原因。
10. 判断 Benchmark 是否适用；普通任务默认不创建 `benchmarks/`。
11. 发现或创建 `GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md`，并按交接物 SSOT 写入 Owner、独立检查者、状态和证据路径。
12. 后端任务安排 Backend Architecture Design -> `goal_unit_test_designer` 写单测 -> `goal_backend` 实现 -> `goal_unit_test_runner` 跑单测 -> `goal_api_integration_test_runner` 跑 API 集成测试；`goal_api_integration_test_designer` 可在架构后并行生成 Python + pytest 脚本。
13. 前端开发完成后安排 `goal_e2e_test_designer` 生成 E2E 用例，再由 `goal_e2e_test_runner` 执行。
14. 展示四列 `Teams 规划表`：成员与能力、任务范围、交付与标准、验证安排。
15. 根据确认或直接执行语义启动独立成员，按 locked scope、Harness 和 workflow 推进。
16. 将计划、进度、决策、测试证据和验收结果写入输出目录 OKF Markdown。
17. 完成后由 `goal_completion_auditor` 审计；需要续跑时只处理已确认目标范围内的剩余工作。

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
  CHANGELOG.md
  README.md
  README.en.md
  agents/openai.yaml
  references/goal-teams-runtime.md
  references/default-AGENTS.md
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

`examples/mini-goal-run` 还包含 `harness/` 复盘资料，展示 `setup -> run -> checks -> report` 的最小静态链路，并提供 automation protocol、evidence ledger 和 pipeline gates 静态样本。`benchmarks/` 提供 `GT-BENCH-001` 与 `GT-BENCH-002` 模板，用于比较 baseline 与 Goal Teams 的产物质量、证据完整度、生产门禁判断和成本。

V1.92 新增 `references/goal-teams-scripted-tooling.md`、`references/ui-e2e-pixel-protocol.md` 和 `references/subagent-dispatch-protocol.md`，并提供 `GT-BENCH-003` 用于验证 UI E2E、复刻像素级对比和证据不足打回。

V1.93 新增 `prompts/lead/`、`prompts/members/`、`prompts/packets/`，并将真实脚本迁入 `scripts/checks/`、`scripts/harness/`、`scripts/benchmark/` 和 `scripts/install/`；`scripts/check.sh` 等旧入口保持可用。

V1.94 新增成员包子目录、`references/dual-review-protocol.md`、`prompts/packets/dual-review-record.md`、`scripts/checks/check-member-layout.py`、`scripts/review/compare-artifacts.py` 和 `scripts/review/validate-dual-review.py`。对比和校验类任务必须同时有脚本复核证据和 LLM reviewer 复核证据。

V1.95 新增 `prompts/lead/requirement-card.md` 和 `prompts/packets/requirement-card.md`，要求 Plan 模式先写入 `spec/requirement-card.md`，用简洁方案讲清核心目标、关键功能、边界、约束和风险。

V1.96 新增用户故事和功能验收标准要求：需求卡片先写“作为...我想要...以便...”格式的用户故事，并给出可验证的功能验收标准；后续 PRD、tasklist、Harness、test plan 和 acceptance 必须承接。

V1.97 新增 `references/google-okf-bilingual-spec.md`、`prompts/packets/page-spec-card.md`、`prompts/packets/memory.md`、`prompts/packets/html-prototype-mock.md`，并强化 `references/ui-visual-contract-protocol.md` 与 `references/ui-e2e-pixel-protocol.md`。所有生成 Markdown 文档默认采用 OKF；无指定目录时写入 `GoalTeamsWork-<project_version>/`；页面规格卡和 HTML 原型必须记录组件库名称、版本、来源、元素级组件库归属和必要数据模型。

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

当前仓库发布内容包括 `VERSION`、`SKILL.md`、`agents/openai.yaml`、`references/goal-teams-runtime.md`、`references/default-AGENTS.md`、`references/goal-teams-automation-protocol.md`、`references/goal-teams-production-pipeline.md`、`references/goal-teams-scripted-tooling.md`、`references/google-okf-bilingual-spec.md`、`references/ui-e2e-pixel-protocol.md`、`references/ui-visual-contract-protocol.md`、`references/subagent-dispatch-protocol.md`、`references/dual-review-protocol.md`、`prompts/lead/core.md`、`prompts/lead/requirement-card.md`、`prompts/members/shared.md`、`prompts/members/backend/prompt.md`、`prompts/members/backend/template.md`、`prompts/members/backend/workflow.md`、`prompts/members/backend/scripts.md`、`prompts/members/unit-test-designer/prompt.md`、`prompts/members/unit-test-runner/prompt.md`、`prompts/members/api-integration-test-designer/prompt.md`、`prompts/members/api-integration-test-runner/prompt.md`、`prompts/members/e2e-test-designer/prompt.md`、`prompts/members/e2e-test-runner/prompt.md`、`prompts/packets/member-goal-packet.md`、`prompts/packets/handoff-artifacts.md`、`prompts/packets/page-spec-card.md`、`prompts/packets/memory.md`、`prompts/packets/html-prototype-mock.md`、`prompts/packets/requirement-card.md`、`prompts/packets/dual-review-record.md`、`subagents/goal-*.toml`、`goal-teams.md`、`AGENTS.md`、`scripts/check.sh`、`scripts/validate.py`、`scripts/install-local.sh`、`scripts/check-version-sync.py`、`scripts/check-agent-names.py`、`scripts/check-member-layout.py`、`scripts/validate-harness.py`、`scripts/pixel-diff.py`、`scripts/compare-artifacts.py`、`scripts/validate-dual-review.py`、`scripts/benchmark-runner.py`、`scripts/checks/`、`scripts/harness/`、`scripts/review/`、`scripts/benchmark/`、`scripts/install/`、`prompts/`、`examples/mini-goal-run`、`benchmarks/`、`CHANGELOG.md`、`README.md` 和 `README.en.md`。

## License

如需开源发布，建议后续补充明确的 License 文件，例如 MIT、Apache-2.0 或内部共享协议。
