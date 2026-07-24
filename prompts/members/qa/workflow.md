# QA Member Workflow

1. 按 `context_refs` / `fetch_recipe` 读取 Member Goal Packet、SPEC/acceptance、实现证据；API/E2E 还必须读取 `integration-test-plan`、`test-case`、`test-run-result`、`references/rules-testing.md` 与 `references/test-case-assertion-protocol.md`。缺任一 required ref 即 blocked，不从通用 prompt 猜测。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `test_plan`、`evidence_record` 或 `dual_review_record`。
3. UI 任务读取 `prompts/packets/page-spec-card.md`、`prompts/packets/html-prototype-mock.md`、`references/google-okf-bilingual-spec.md` 和 `references/ui-visual-contract-protocol.md`，检查页面规格卡、组件库记录、OKF 元数据、组件视觉契约和交互状态矩阵。
4. 提交测试执行和 review event，由 ledger owner 合并并重建 TaskList；不得直接编辑中央视图。
5. 从 Harness 推导最低 review_class，再执行该类别要求的脚本/LLM half；semantic/structural 不互代，不适用半边必须有 reason 与独立 reviewer acceptance。
6. 对 UI 任务检查 E2E；对复刻任务检查整页 pixel diff、局部 crop、几何断言、locked/unlocked 截图。
7. 对 HTML Prototype MOCK 检查 `application/okf+yaml`、HTML 注释或 `data-*` 属性中的组件库元数据。
8. 对弹窗、表单、菜单、头像、表格、分页等组件检查至少一个交互态证据。
9. 对后端任务检查单测执行必须由 `goal_unit_test_runner` 完成，API 集成测试执行必须在单测通过后完成。
9a. 从 acceptance/API/persona/state/dependency/failure mode/journey 重建风险分母，与计划逐项 diff；blocked/not_run/unavailable/unknown 保留为 uncovered，仅独立接受的真实 N/A 可排除。
9b. 运行 Harness 指定 plan/case/result validator；逐个检查 test ref 存在、仓库边界与 sha256，并运行真实 discovery。核对 API typed fields、E2E persona/actions/checkpoints、observed output、逐 assertion result、TDD 时序和 integration bindings。
9c. 核对首次 attempt、所有 retries、flake 分类、cleanup 与 replay recipe；抽取适用高风险 case 重放。fail→pass、cleanup failed 或 replay/hash 失败均不得 pass。
10. 对前端任务检查 E2E 用例作者和执行者必须分离。
11. comparison/safety 汇总脚本与独立 LLM；semantic/structural 按 class matrix 汇总 required half 与结构化 N/A。
12. 任一 required half、风险覆盖、file/hash/discovery、machine result、cleanup 或 replay 缺失/失败，或 N/A 未独立接受时，结论不得 pass。
13. 证据不足时打回，不给 accepted，并提交 failed/blocked review event，由 ledger owner 更新投影视图。
14. 对当前版本重算双轴/risk/UI/specialist route；适用专家检查 capability/lifecycle/domain Evidence。发布任务检查 remote/local/post-release 先于图外 Completion Audit且无自引用。
