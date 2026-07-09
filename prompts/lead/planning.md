# Goal Teams Planning

Goal Teams 工作总是先规划，再派发或编辑实现文件。直接执行只跳过等待确认，不跳过规划、风险检查和 `Teams 规划表`。

规划步骤：

1. 检查项目指南：`AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md`；都没有时读取 `references/default-AGENTS.md`。
2. 将用户目标转成可验证 Done Criteria。
3. 确认或推断项目版本号；无法推断时询问。
4. 确认输出目录。用户未指定生成目录时，默认使用 `GoalTeamsWork-<project_version>/`；确认 artifact version，并创建 `versions/<artifact_version>/`。
5. 读取 `prompts/packets/memory.md`，创建或更新输出目录根部的 `index.md`、`memory.md`，再创建版本子目录的 `index.md` 和 `TaskList.md`（兼容 `tasklist.md`）；需要生成 Markdown 文档、SPEC 或需求卡片时再读取 `references/google-okf-bilingual-spec.md`。
6. 创建或更新 `spec/requirement-card.md`，用 OKF 简洁方案写清核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险。
7. 发现已有 SPEC、TaskList、前后端架构设计、prototype、test plan、acceptance 和页面规格卡。
8. 读取 `prompts/packets/handoff-artifacts.md`，把本轮交接物类型、Owner subagent、独立检查者和状态字段作为 SSOT。
9. 涉及 UI 页面、复刻、还原、截图对齐或前端交互页面时，把 `page-spec-card.md` 放在 PRD 之后、HTML Prototype 或前端实现之前；非 UI 任务记录 `not_applicable_reason`。
10. 用户要求页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面时，若缺少组件库名称、版本、URL 或 Git 仓库，先澄清；若已给出，写入 `memory.md`、页面规格卡和 HTML OKF 元数据。
11. 在 TaskList 中为每个交接物写入 `handoff_artifact`、`artifact_type`、`owner_subagent`、`validator_subagent`、`handoff_status`、`independent_check_status`、Harness 和证据路径。
12. 长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖任务必须读取 `prompts/lead/loop.md`，并在 Plan 中写入 `Loop Gate`：最大轮次、最大自动续跑轮次、成员数、时间、tokens、费用、已确认范围和停止条件。
13. 每个功能切片必须先拆到 V2.0 最小颗粒度：需求规格卡、PRD、页面规格卡、HTML 原型、前端开发、前后端架构设计、后端 TDD、后端开发、后端执行 TDD、API 集成测试脚本生成、API 集成测试、API 集成测试执行、生成 E2E 测试用例、执行 E2E 测试用例、BugFix、测试报告生成；不适用项写 `not_applicable_reason`。
14. 后端任务必须安排：后端架构设计 -> `goal_unit_test_designer` 写单元测试 -> `goal_backend` 实现 -> `goal_unit_test_runner` 跑单测 -> `goal_api_integration_test_runner` 跑 API 集成测试。API 集成测试脚本可在架构设计后由 `goal_api_integration_test_designer` 并行生成，默认 Python + pytest。
15. 前端任务必须安排：前端架构设计/页面规格卡/HTML 原型 -> `goal_frontend` 开发 -> `goal_e2e_test_designer` 生成 E2E 用例 -> `goal_e2e_test_runner` 执行。
16. 生成 Plan 表格前，不启动实现 subagents，也不编辑实现文件。

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
- 开发执行跟随版本子目录的 `TaskList.md`/`tasklist.md`。
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
```

需要用户选择时使用数字选项：

```text
请选择下一步：
1. 确认并执行
2. 调整成员或范围
3. 只保留方案，不执行
```
