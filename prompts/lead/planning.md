# Goal Teams Planning

Goal Teams 工作总是先规划，再派发或编辑实现文件。直接执行只跳过等待确认，不跳过规划、风险检查和 `Teams 规划表`。仅当用户明确同时表达“只要规划/建议”与“不落盘、不创建/修改文件、只在聊天中返回”时进入 `plan_preview`：不创建/修改文件、ledger、TaskList，不启动 subagent。仅说“先做计划”或“给方案”不是 preview；若用户要求生成计划文档、需求卡片、TaskList、ledger、SPEC、实施、派发、测试或提交，也不是 no-write preview。

规划步骤：

1. 检查项目指南：`AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md`；都没有时读取 `references/default-AGENTS.md`。
2. 将用户目标转成可验证 Done Criteria。
3. 确认或推断项目版本号；无法推断时询问。
4. 确认输出模式。只有符合上述显式 no-write 判定的聊天规划，机器值才固定为 `mode=plan_preview`、`profile=lite`、`writes_created=false`，并跳到聊天内 Plan；其他模式确认输出目录（默认 `GoalTeamsWork-<project_version>/`）和 artifact version，再创建 `versions/<artifact_version>/`。
5. 非 `plan_preview` 时读取 `prompts/packets/memory.md`，创建或更新根 `index.md`、`memory.md`，创建版本 `index.md`、append-only ledger、checkpoint 与 identity registry，并由 reducer 生成 `TaskList.md`；`tasklist.md` 仅作为 V2.2 legacy 输入；生成 Markdown 时再读 `references/google-okf-bilingual-spec.md`。
6. 非 `plan_preview` 时创建或更新 `spec/requirement-card.md`；preview 只在响应中给出同等内容，不伪称已持久化。
7. 发现已有 SPEC、TaskList、前后端架构设计、prototype、test plan、acceptance 和页面规格卡。
8. 读取 `prompts/packets/handoff-artifacts.md` 与 `prompts/packets/harness-contract.md`，按 `schemas/v2.3/goal-teams.schema.json` 装配 identity registry、Task、Check、Run、Evidence、Traceability、Review 与 Audit；schema 才是机器字段 SSOT。
9. 涉及 UI 页面、复刻、还原、截图对齐或前端交互页面时，把 `page-spec-card.md` 放在 PRD 之后、HTML Prototype 或前端实现之前；非 UI 任务记录 `not_applicable_reason`。
10. 用户要求页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面时，若缺少组件库名称、版本、URL 或 Git 仓库，先澄清；若已给出，写入 `memory.md`、页面规格卡和 HTML OKF 元数据。
11. 在 event ledger 中记录每个交接物的 append-only event / task_patch，由 reducer 生成 `TaskList.md`；成员不得直接自由编辑中央 TaskList。
12. 长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖任务必须读取 `prompts/lead/loop.md`，并在 Plan 中写入 `Loop Gate`：最大轮次、最大自动续跑轮次、成员数、时间、tokens、费用、已确认范围和停止条件。
13. Full/Regulated Profile 按 V2.0 完整颗粒度拆分；Lite/Standard 只创建风险和交付所需任务，不生成 17 个空任务。不适用项使用结构化 `not_applicable_reason`。
14. 后端任务必须安排：后端架构设计 -> `goal_unit_test_designer` 写单元测试 -> `goal_backend` 实现 -> `goal_unit_test_runner` 跑单测 -> `goal_api_integration_test_runner` 跑 API 集成测试。API 集成测试脚本可在架构设计后由 `goal_api_integration_test_designer` 并行生成，默认 Python + pytest。
15. 前端任务必须安排：前端架构设计/页面规格卡/HTML 原型 -> `goal_frontend` 开发 -> `goal_e2e_test_designer` 生成 E2E 用例 -> `goal_e2e_test_runner` 执行。
16. 生成 Plan 表格前，不启动实现 subagents，也不编辑实现文件。
17. 解析每个待加载引用的分级：核心和已触发条件引用缺失时记录缺失路径/影响并设置 `task_state=blocked`、`check_state=blocked`，停止派发；只有低风险、非 acceptance-blocking 且 Harness 未要求独立验证的工作，才可因未触发条件/可选引用记录 `degraded_mode=single_agent`。不得用此降级产生 `accepted`、`passed` 或 `achieved`。
18. 记录失败状态时只写一个 `check_state`：检查已执行但不通过或证据无效为 `failed`；因授权、能力或必需引用缺失而无法检查为 `blocked`。`failed|blocked` 只可作为自然语言替代关系，不能写入 schema。

有效 Plan 必须包含：澄清状态、假设、项目版本、输出目录、artifact version、版本子目录、memory.md 状态、TaskList 状态、需求卡片路径、用户故事、功能验收标准、SPEC 状态、页面规格卡状态、组件库状态、交接物 SSOT、Harness 契约、Benchmark 适用性、Lead LOOP 适用性、Loop Gate、成员分工、任务认领、workflow、前置任务、锁定范围、交接物 Owner、独立检查者、测试 Owner、文档 Owner、风险和停止条件。

SPEC 固定术语：

- 需求文档使用 `PRD`。
- Plan 模式先产出 `需求卡片`，再进入完整需求分析。
- 需求卡片先写 `用户故事` 和 `功能验收标准`，后续 PRD、tasklist 和 Harness 必须承接。
- 需求分析先产出 `Requirement Specification Card`，再生成 PRD。
- UI 页面、复刻、还原、截图对齐或前端交互页面在 PRD 后产出 `Page Specification Card`，路径为 `spec/page-spec-card.md`，再进入 `HTML Prototype` 或前端实现。
- 设计文档使用 `Architecture Design`。
- 后端开发前必须有 Backend Architecture Design；前端开发前必须有 Frontend Architecture Design 或 `not_applicable_reason`。
- 涉及页面、屏幕或工作流时，包含 `HTML Prototype`。
- HTML Prototype MOCK 必须按 `prompts/packets/html-prototype-mock.md` 记录 OKF 元数据和组件库信息。
- 开发执行跟随版本子目录的 `TaskList.md`；`tasklist.md` 仅可作为 legacy migration 输入。
- 测试必须由独立测试 subagent 或用户指定测试 skill/subagent 负责。

推荐版本化目录：

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
      loop-state.json
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
      harness/harness.json
      harness/traceability.json
      evidence/evidence.jsonl
      reviews/dual-review.json
      reviews/semantic-review.md
      audit/completion-audit.json
```

需要用户选择时使用数字选项：

```text
请选择下一步：
1. 确认并执行
2. 调整成员或范围
3. 只保留方案，不执行
```
