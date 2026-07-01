# Frontend Member Workflow

1. 读取 PRD、`page-spec-card.md`、HTML Prototype、Frontend Architecture Design、design.md、test-plan、acceptance、`references/google-okf-bilingual-spec.md`、`prompts/packets/html-prototype-mock.md` 和 `references/ui-visual-contract-protocol.md`。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `frontend_architecture_design`、`html_prototype`、`frontend_implementation` 或 `evidence_record`。
3. 在 TaskList 中更新前端交接物的 Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness 和证据路径。
4. 如果缺少 UI 任务所需页面规格卡，先按 `prompts/packets/page-spec-card.md` 生成或请求 Lead 分配；非 UI 任务写 `not_applicable_reason`。
5. 页面原型任务先确认组件库名称、版本、URL 或 Git 仓库；若用户已提供，写入输出目录 `memory.md`，并同步到页面规格卡和 HTML OKF 元数据。
6. 明确 UI 流程、viewport、可见状态、组件库、组件级视觉契约、交互状态矩阵和参考图/参考页面。
7. 区分动态前端页面 Harness 与静态 HTML Prototype Harness：动态覆盖真实路由、状态变化、DOM 几何断言和交互态截图；静态覆盖结构、mock 数据、响应式截图、组件几何断言、OKF 元数据和不适用说明。
8. 先定义 E2E Harness、整页 pixel diff、局部 crop/几何断言、locked/unlocked 截图、组件库元数据检查和阈值。
9. 若 Frontend Architecture Design 缺失，先补齐或记录 `not_applicable_reason`。
10. 实现或调整 UI。
11. 前端开发完成后请求 `goal_e2e_test_designer` 生成 E2E 用例，再请求 `goal_e2e_test_runner` 执行。
12. 生成截图、控制台检查、整页和局部像素差异指标、组件断言报告、组件库元数据断言报告。
13. 请求 QA 或 reviewer 做 LLM 体验复核和 UI 视觉防漏复核。
14. 缺少参考图、运行环境、页面规格卡、组件库信息或 unlocked real DOM 证据时记录 blocked 或 `not_applicable_reason`，并写回 TaskList。
