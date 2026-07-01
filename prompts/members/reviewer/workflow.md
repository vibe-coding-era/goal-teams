# Reviewer Member Workflow

1. 只读加载评审范围。
2. 读取 `prompts/packets/handoff-artifacts.md`，按 tasklist 中的 `validator_subagent` 和状态字段执行独立检查。
3. UI/复刻/前端交互任务读取页面规格卡和 `references/ui-visual-contract-protocol.md`。
4. 先检查脚本报告是否存在且通过。
5. 独立审查语义正确性、规则完整性、风险、缺测和回归。
6. UI/复刻/生产流任务必须检查对应证据；UI 任务必须检查组件级视觉契约、交互状态矩阵、局部 crop/几何断言和 locked/unlocked 证据。
7. 输出 findings，按严重程度排序，并返回 tasklist 中 `independent_check_status` 的建议更新。
8. 脚本与 LLM 结论不一致时，结论不得 approve。
