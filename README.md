[English](README.en.md) | 中文

# Goal Teams

作者：肉山@TGO 杭州

当前版本：`V2.34`

Goal Teams 是一个面向 Codex 的团队协作 Skill。它会以一个 Goal Lead 的身份，把一个目标拆成可验证的计划，再协调多个独立 subagent（不同上下文执行）或用户指定的外部 skill 完成需求、设计、实现、测试、证据记录和收尾审计。过程中会应用到：
- 应用Goal + Plan + Loop 模式
- 构建和严格遵循 SPEC + Harness + SSOT 三大原则
- 不同角色使用不同的 subagent（不同上下文执行）保持上下文独立性不被污染
- 建立过程 Benchmark 基准
- 与 OpenSpec 和 Superpowers 共存；完整 adapter 进入 V2.4

适合使用它的场景：

- 任务需要先规划，再分给多个角色在独立 Subagent 上下文中隔离判断和交付。
- 任务需要留下 SPEC、TaskList、Harness、Evidence 和验收记录。
- 任务包含后端 TDD、API 集成测试、前端 E2E、UI 复刻或像素对比。
- 任务较长，需要 Lead LOOP 记录状态、续跑缺口，并在越界时停下。
- 任务需要和外部 Skill、项目已有工具或用户指定 Subagent 组合使用。

不适合使用它的场景：

- 只需要一次简单问答。
- 只改一个很小的文件，且不需要团队分工、证据链或审计。
- 需要真实生产审批、CI/CD 或后台执行器；Goal Teams 只提供协作协议和可运行脚本，不替代外部系统。

## 核心机制

### Goal + Plan + Loop

Goal Teams 把一次复杂协作拆成三个层次：

- Goal 定义目标和 Done Criteria，让团队先对“完成是什么”达成一致。
- Plan 把目标转成成员、Subagent 上下文、范围、交接物、验证方式和停止条件，降低范围漂移和并发冲突。
- Loop 在每轮整合后记录 `loop_decision=continue|replan|stop`，并把 `run_outcome`、task/check 状态与 stop_reason 分开记录，方便长任务恢复和审计。

这个模式的先进性不在于多派几个 agent，而在于让不同角色在独立上下文中工作，同时由 Goal Lead 保持目标、范围和证据的一致性。它把一次聊天式请求变成可以追踪的工程过程。

### SPEC + Harness + SSOT

Goal Teams 用 `SPEC -> Harness -> Evidence -> Audit` 做验证链，并用 SSOT 约束交接物口径：

- SPEC 说明要完成什么，包括需求、边界、用户故事、功能验收标准、架构和测试计划。
- Harness 说明如何证明完成，包括命令、脚本、E2E、截图、人工检查清单和证据路径。
- SSOT 说明交接物只有一个权威定义，包括 artifact 类型、Owner、validator、状态字段和 TaskList 账本格式。

这组机制让 Skill 的产物不只是一份计划，而是一套可以被成员执行、被脚本检查、被 reviewer 复核、被 auditor 收尾的证据结构。对复杂应用开发来说，这比单纯输出代码更稳，因为它要求“完成”必须能被证明。

### Benchmark

Goal Teams 内置 `benchmarks/` 任务包，用来比较不同工作流、prompt 或 skill 版本的表现。Benchmark 不用于普通任务的默认输出，而是在用户要求、计划确认或 Skill Improvement 场景中启用。

Benchmark 的价值是把“感觉变好了”变成可复盘的比较：同一任务可以对比 baseline 和 Goal Teams 在产物完整度、证据质量、UI 验证、生产门禁判断、Loop 状态恢复和成本上的差异。当前仓库提供 `GT-BENCH-001` 到 `GT-BENCH-004`，覆盖从基础产物质量到 Lead LOOP 恢复的几个典型维度。

### 开放性和外部 Skill

Goal Teams 不要求所有能力都来自内置 subagent。Plan 阶段可以把外部 skill、项目已有脚本、浏览器工具、测试工具或用户指定 subagent 纳入 `Teams 规划表`，并为它们定义 locked scope、输入、输出、Harness 和 validator。

这种开放性让 Goal Teams 更像一个协作编排层：它负责目标、计划、交接物和证据的一致性；具体能力可以来自 `goal_*` subagent，也可以来自外部 skill，例如 browser 验证、文档生成、安全审查、PDF/表格处理或项目自定义工具。外部能力进入团队后仍遵守 SSOT、Harness 和独立校验规则。

## 快速开始

安装到本地 Codex skills 目录：

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/.codex/skills/goal-teams
```

从本仓库安装或更新本地副本：

```bash
./scripts/install-local.sh --update-team-fallback
```

维护或发布前运行检查：

```bash
./scripts/check.sh
```

路由规则的独立确定性入口为 `scripts/checks/check-routing-fixtures.py`（兼容入口：`scripts/check-routing-fixtures.py`）。

`./scripts/check.sh` 只覆盖确定性 contract/mutation gate，不构成真实 Behavior 发布证据。发布 RC 前在源码仓库外选择一个全新、持久目录，运行 9 场景隔离盲测，再把 summary 交给组合门禁：

```bash
BLIND_OUTPUT=/absolute/path/outside/goal-teams/blind-v23-<run-id>
python3 scripts/benchmark/benchmark-runner.py --mode blind-agent --release-gate \
  --manifest tests/v23/fixtures/behavior/blind-agent-codex.json \
  --output-dir "$BLIND_OUTPUT"
python3 scripts/v23/goalteams_v23.py release-gate examples/canonical-v23 \
  --mode rc --blind-summary "$BLIND_OUTPUT/summary.json"
```

该盲测会调用当前环境解析并按 hash 锁定的 Codex CLI，信任级别为 `local_process_attested`，不等于远程模型或代码签名证明；mock/fixture、旧目录、非唯一官方 manifest、缺场景或缺 summary 均不能满足 RC。组合门禁会从固定 `output.txt`/trace/evidence 重评分，并在同一调用内执行完整 `scripts/check.sh`。GA 的本地 License 文件只算 proposal，仍需仓库外可信 owner attestation。

手动复制 subagents：

```bash
mkdir -p ~/.codex/agents
cp ~/.codex/skills/goal-teams/subagents/goal-*.toml ~/.codex/agents/
```

## 使用方式

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

显式调用 Goal Teams 或当前会话首次需要建立身份时汇报；已有完整上下文时不重复：

```text
我是 Goal Teams Lead V2.34。
```

中文核心模型要点提示词：用户沟通和治理文档默认中文；代码、注释、测试名、fixture 和产品字符串遵循目标仓库约定；代码标识、命令、路径、API 名称、配置键、subagent ID 和精确引用保留原文。

## 规则入口

`SKILL.md` 是触发导向入口。它只保留启动语、不变量、规划检查、失败降级摘要和渐进式加载路由。更细的规则放在 references 和 prompts 中，按任务类型读取。

| 文件 | 作用 |
| --- | --- |
| `RULES.md` | Goal Lead 和成员的响应规范：执行优先、事实优先、未验证不宣称完成。 |
| `SKILL.md` | Skill 发现入口和加载路由。`description` 保留 `$goal-teams`、`Goal Mode`、`Plan Mode`、`先规划`、`只规划`、`需求卡片` 等触发词。 |
| `references/invariants.md` | 永远生效的不变量、硬边界和失败降级协议。 |
| `references/compat.md` | `TaskList.md`/`tasklist.md`、脚本兼容入口、成员包布局和版本同步口径。 |
| `references/rules-ui.md` | UI、页面规格卡、HTML Prototype MOCK、E2E 和像素对比规则。 |
| `references/rules-testing.md` | 后端架构先行、TDD、API 集成 pytest、前端 E2E 和独立测试规则。 |
| `references/rules-loop.md` | Lead LOOP、Loop Decision、Loop Gate、Budget Gate 和自动续跑边界。 |
| `prompts/packets/handoff-artifacts.md` | 交接物 SSOT，定义 artifact 类型、Owner、validator、状态字段和 TaskList 账本格式。 |

## 工作流

1. 把用户目标转成 Done Criteria。
2. 确认项目版本、artifact version 和输出目录。
3. 若用户明确要求聊天内 `plan_preview` / no-write，只在响应中给出方案，不创建文件、ledger、TaskList 或 subagent；其他模式才创建或更新 `GoalTeamsWork-<project_version>/memory.md`，建立版本目录 append-only ledger，并由 reducer 生成 `TaskList.md`。
4. 非 `plan_preview` 的 Plan 模式先写 `spec/requirement-card.md`，再按适用范围补齐 PRD、架构、测试计划和验收文档。
5. 按任务类型加载 UI、测试或 LOOP 条件规则。
6. 展示四列 `Teams 规划表`，然后派发独立成员。
7. 每个成员只在自己的 locked scope 内执行，并提交带 revision 的 event/patch、Harness 和 Evidence；成员不直接编辑中央 TaskList。
8. ledger owner 合并事件并生成 TaskList 投影；Goal Lead 分别记录 `loop_decision` 与 `run_outcome`。
9. 完成前启动新的只读 `goal_completion_auditor`。仅在当前会话且宿主支持时续跑已确认范围内缺口；新范围、高风险或授权问题停下问用户。

## 输出结构

默认输出目录：

```text
GoalTeamsWork-<project_version>/
  index.md
  memory.md
  versions/
    <artifact_version>/
      index.md
      TaskList.md
      ledger/events.jsonl
      ledger/checkpoint.json
      identity/registry.json
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
      harness/harness.json
      harness/traceability.json
      evidence/evidence.jsonl
      reviews/dual-review.json
      reviews/semantic-review.md
      audit/completion-audit.json
      capability/manifest.json       # 宿主能力需要记录时
      release/license-decision.json  # 仅 repository owner 授权 GA 时
```

`tasklist.md` 仍可作为 legacy 输入读取；V2.3 新输出只写 reducer 生成的 `TaskList.md`。上述机器路径以 `schemas/v2.3/goal-teams.schema.json` 为准；V1.8 的根级 `harness.yaml`、`evidence.jsonl`、`pipeline-state.json` 仅是 legacy/可选协议，不构成 V2.3 completion closure。

## 默认成员

| Subagent ID | 主要职责 |
| --- | --- |
| `goal_requirements_analyst` | 澄清目标、调研辅助、需求规格卡、PRD 前置输入。 |
| `goal_product` | PRD、验收标准、原型结构和产品评审。 |
| `goal_backend` | 领域模型、存储、API、CLI、MCP、迁移和集成。 |
| `goal_frontend` | UI、HTML 原型、浏览器验证、E2E、复刻像素级对比和截图证据。 |
| `goal_unit_test_designer` | 后端 TDD 单元测试用例、断言和覆盖说明。 |
| `goal_unit_test_runner` | 后端 TDD 单元测试执行、红绿证据和失败报告。 |
| `goal_api_integration_test_designer` | API 集成测试脚本和测试矩阵，默认 Python + pytest。 |
| `goal_api_integration_test_runner` | API 集成测试执行、日志、报告和失败响应。 |
| `goal_e2e_test_designer` | 前端完成后的 E2E 用例、viewport 和组件断言。 |
| `goal_e2e_test_runner` | E2E 执行、截图、trace、console/network 证据。 |
| `goal_qa` | 独立测试、集成测试、UI E2E、像素级对比验收和测试报告。 |
| `goal_docs` | acceptance、README、报告和发布说明；TaskList 变化以 event/patch 交接。 |
| `goal_reviewer` | 只读评审、架构边界、安全、覆盖率、兼容性和风险。 |
| `goal_completion_auditor` | 收尾审计、未完成工作检查和会话内续跑建议。 |

## 设计依据和出处

| 原则或技术 | 为什么采用 | 出处 |
| --- | --- | --- |
| Codex Skill | Goal Teams 本质上是可复用工作流，不是业务应用。Skill 可以把 instructions、references 和 scripts 打包，让 Codex 在需要时加载。 | [OpenAI Codex Agent Skills](https://developers.openai.com/codex/skills) |
| 触发导向 `description` | Codex 会根据 skill 的 `description` 做隐式匹配，所以关键触发词必须前置且明确。 | [OpenAI Codex Agent Skills: How Codex uses skills](https://developers.openai.com/codex/skills) |
| 渐进式加载 | 先加载少量入口信息，只有任务需要时再读取细分规则，能减少上下文占用，也降低无关规则干扰。 | [OpenAI Codex Agent Skills](https://developers.openai.com/codex/skills), [NN/g Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/) |
| SSOT | 交接物、Owner、validator 和状态字段必须只有一个权威定义，避免成员包、TaskList 和验收记录各说各话。 | [Atlassian: Single Source of Truth](https://www.atlassian.com/work-management/knowledge-sharing/documentation/building-a-single-source-of-truth-ssot-for-your-team), `prompts/packets/handoff-artifacts.md` |
| OKF Markdown | Goal Teams 产物需要同时给人和 agent 读取。OKF 使用 Markdown + YAML frontmatter，适合版本控制、索引和跨工具交换。 | [GoogleCloudPlatform Open Knowledge Format SPEC](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md), `references/google-okf-bilingual-spec.md` |
| 需求到测试的可追溯性 | 需求、测试、证据和验收要能互相追踪，才能判断“是否真的完成”。 | [NASA Software Test Procedures](https://swehb.nasa.gov/display/SWEHBVD/5.14%2B-%2BTest%2B-%2BSoftware%2BTest%2BProcedures?desktop=true&macroName=show-if) |
| TDD | 后端任务先写测试再实现，可以把需求转成可执行约束，并在实现阶段及时暴露偏差。 | [Martin Fowler: Test-Driven Development](https://martinfowler.com/bliki/TestDrivenDevelopment.html) |
| pytest | API 集成测试默认用 Python + pytest，因为 pytest 语法直接、失败信息清楚，并能扩展到复杂测试。 | [pytest documentation](https://docs.pytest.org/en/stable/) |
| Playwright E2E | UI 任务需要真实浏览器证据。Playwright 支持浏览器、viewport、trace、截图和 pytest 集成。 | [Playwright Python Pytest plugin](https://playwright.dev/python/docs/test-runners), `references/ui-e2e-pixel-protocol.md` |
| Lead LOOP | 长任务常见问题不是“不会做”，而是证据缺口、范围漂移和中途状态丢失。Loop Decision 把每轮整合后的选择固定下来。 | `references/rules-loop.md`, `prompts/lead/loop.md` |

## 示例和回归

`examples/mini-goal-run` 提供一个最小输出树，用来检查 index、SPEC、TaskList、Teams 规划表、Harness、Evidence、独立校验和收尾审计是否齐全。

`benchmarks/` 提供 `GT-BENCH-001`、`GT-BENCH-002`、`GT-BENCH-003` 和 `GT-BENCH-004` 模板，用于比较 baseline 和 Goal Teams 在产物质量、证据完整度、生产门禁判断、UI 证据处理、Lead LOOP 状态恢复和成本方面的差异。

`goal-teams.md` 记录长期用户指定要求，是维护规则时的上游依据。

## 版本说明

当前版本以 `VERSION` 为准。`V2.34` 在 V2.3 机器契约基线上增加合同先行、Architecture 与 Environment Evidence 双门、`Gather → Reason → Act → Verify → Repeat` 可恢复 LOOP、四文件磁盘状态、受限第 9 轮候选集重置、第 11 轮 fail-closed 交付、四维评分与分歧/瓶颈记录。详细契约按任务类型从 `references/` 加载；完成后只将经审计且清除调用痕迹的公开文档归档到 `docs/archive/V2.34/<delivery_id>/`，过程账本与 provenance 仍保留在非公开工作区。

发布包的可见组成见[发布内容](docs/release-contents.md)；英文读者见[Release Contents](docs/release-contents.en.md)。该清单不会替代运行规则、`VERSION` 或安装校验。

按时间整理的版本改动见[版本变更记录](docs/change-history.md)；英文读者见[Change History](docs/change-history.en.md)。`CHANGELOG.md` 保留逐项技术变更的兼容记录。

## License

当前仓库还没有声明开源 License。owner 应先明确选择 License 或内部共享协议；该本地决定仅是 proposal，GA 授权还必须有仓库外可信 host/signature attestation，当前技术交付最多到 RC。

## V2.3 契约与发布边界

V2.3 增加确定性机器契约：闭合状态枚举、单写者 ledger、严格 Evidence/Traceability、能力降级、Profile 路由、typed migration 与 release gates。详见 `references/goal-teams-v2.3-contract.md`，发布前运行 `./scripts/check.sh`。技术 RC 与正式 GA 分开判断；只有 owner 的 License/内部共享决定而没有仓库外可信 host/signature attestation 时，GA 门禁仍必须 fail-closed。
