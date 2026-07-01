# QA Member Workflow

1. 读取 Member Goal Packet、test plan、acceptance 和实现证据。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `test_plan`、`evidence_record` 或 `dual_review_record`。
3. UI 任务读取 `prompts/packets/page-spec-card.md`、`prompts/packets/html-prototype-mock.md`、`references/google-okf-bilingual-spec.md` 和 `references/ui-visual-contract-protocol.md`，检查页面规格卡、组件库记录、OKF 元数据、组件视觉契约和交互状态矩阵。
4. 在 TaskList 中更新测试交接物的 Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness 和证据路径。
5. 先执行可脚本化检查。
6. 对 UI 任务检查 E2E；对复刻任务检查整页 pixel diff、局部 crop、几何断言、locked/unlocked 截图。
7. 对 HTML Prototype MOCK 检查 `application/okf+yaml`、HTML 注释或 `data-*` 属性中的组件库元数据。
8. 对弹窗、表单、菜单、头像、表格、分页等组件检查至少一个交互态证据。
9. 对后端任务检查单测执行必须由 `goal_unit_test_runner` 完成，API 集成测试执行必须在单测通过后完成。
10. 对前端任务检查 E2E 用例作者和执行者必须分离。
11. 对脚本不能判断的语义、体验、边界做 LLM 复核请求。
12. 汇总脚本报告和 LLM 复核，生成结论。
13. 证据不足时打回，不给 complete，并写回 TaskList。
