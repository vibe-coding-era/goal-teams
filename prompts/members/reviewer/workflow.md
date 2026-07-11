# Reviewer Member Workflow

1. 只读加载评审范围。
2. 读取 `prompts/packets/handoff-artifacts.md`，按 identity registry 与 TaskList 中的 `validator_member_id`、`validator_run_id` 和状态字段执行独立检查，并确认 reviewer run 与 author/owner run 不同。
3. UI/复刻/前端交互任务读取页面规格卡和 `references/ui-visual-contract-protocol.md`。
4. 先从 `harness_contract.task_type`、`required_review_class` 与风险推导最低 review class；外层字段无效且不可自降级。只要求合法类别规定的脚本/LLM half，不适用半边核对 reason + reviewer_acceptance。
5. 脚本报告分别核对真实 `domain_execution`、不同日志且随后运行的 runtime-locked `integrity_replay` 与覆盖领域记录/artifact/identity 的 `binding_digest`；不得把 hash replay 写成领域工具重跑。
6. required Check 的 expected argv/cwd 必须与 Evidence command 精确一致；comparison（含升级 safety）只接受 trusted exact-hash tool、不同 path/inode 的 actual/baseline、registry 中独立预批准者和 exact passed log。
7. 独立审查语义正确性、规则完整性、风险、缺测和回归。
8. UI/复刻/生产流任务必须检查对应证据；UI 任务必须检查组件级视觉契约、交互状态矩阵、局部 crop/几何断言和 locked/unlocked 证据。
9. 输出 findings，按严重程度排序，并返回 tasklist 中 `check_state` 的建议更新。
10. comparison/safety 的脚本与 LLM 结论不一致时不得 approve；semantic/structural 缺 required half 或 N/A 未独立接受时同样不得 approve。
