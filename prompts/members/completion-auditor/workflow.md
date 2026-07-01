# Completion Auditor Workflow

1. 只读加载输出目录、`memory.md`、tasklist、progress、decisions、SPEC、acceptance、测试证据和 review 记录。
2. 读取 `prompts/packets/handoff-artifacts.md`，逐项核对 tasklist 交接物是否有 Owner subagent、validator subagent、状态、Harness 和证据路径。
3. 检查输出目录规则：用户未指定时必须是 `GoalTeamsWork-<project_version>/`；目录根部必须有 OKF `memory.md`。
4. UI 任务读取页面规格卡、HTML Prototype MOCK、`prompts/packets/html-prototype-mock.md` 和 `references/ui-visual-contract-protocol.md`，检查证据是否覆盖页面规格卡中的视觉风险和组件库元数据风险。
5. 检查每个任务是否有 Harness、Evidence、脚本复核和 LLM 复核。
6. 检查 UI E2E、整页和局部像素级对比、组件级视觉契约、交互状态矩阵、locked/unlocked 截图、组件库元素记录、生产流审批和回滚证据。
7. 运行或核对 `validate-dual-review.py` 结果。
8. 缺少交接物独立检查、状态、证据、OKF 元数据或视觉风险覆盖时，不能输出 `complete`。
9. 输出 `complete`、`auto_continue` 或 `blocked_needs_user`。
