# Reviewer Member Workflow

1. 按 `context_refs` / `fetch_recipe` 只读加载评审范围；API/E2E required scope 必须包含 acceptance、`integration-test-plan`、`test-case`、`test-run-result`、`references/rules-testing.md` 与 `references/test-case-assertion-protocol.md`。缺引用即 blocked，不从通用 prompt 猜测。
2. 读取 `prompts/packets/handoff-artifacts.md`，按 identity registry 与 TaskList 中的 `validator_member_id`、`validator_run_id` 和状态字段执行独立检查，并确认 reviewer run 与 author/owner run 不同。
3. UI/复刻/前端交互任务读取页面规格卡和 `references/ui-visual-contract-protocol.md`。
4. 先从 `harness_contract.task_type`、`required_review_class` 与风险推导最低 review class；外层字段无效且不可自降级。只要求合法类别规定的脚本/LLM half，不适用半边核对 reason + reviewer_acceptance。
5. 脚本报告分别核对真实 `domain_execution`、不同日志且随后运行的 runtime-locked `integrity_replay` 与覆盖领域记录/artifact/identity 的 `binding_digest`；不得把 hash replay 写成领域工具重跑。
6. required Check 的 expected argv/cwd 必须与 Evidence command 精确一致；comparison（含升级 safety）只接受 trusted exact-hash tool、不同 path/inode 的 actual/baseline、registry 中独立预批准者和 exact passed log。
7. 独立审查语义正确性、规则完整性、风险、缺测和回归。
7a. 从 acceptance/API/persona/state/dependency/failure mode/journey 独立重建风险分母，与计划逐项 diff；blocked/not_run/unavailable/unknown/flaky 保留为 uncovered，仅 independently accepted true N/A 可排除。
7b. 运行 Harness 指定 plan/case/result validators；重算每个 test ref sha256 并执行真实 discovery，检查 API/E2E typed fields、case-to-risk 与 case-to-discovery 映射。
7c. 核对 first attempt、所有 retry、flake classification、cleanup 和 artifact hashes；用 exact argv/cwd/replay recipe 重放至少一个适用高风险项。fail→pass、cleanup/replay/hash 失败均 reject。
7d. 检查业务 assertion、observed output、TDD 时序、integration bindings；再检查双轴覆盖与适用专家的 capability/domain/lifecycle Evidence。
8. UI/复刻/生产流任务必须检查对应证据；UI 任务必须检查组件级视觉契约、交互状态矩阵、局部 crop/几何断言和 locked/unlocked 证据。
9. 输出 findings，按严重程度排序，并返回 tasklist 中 `check_state` 的建议更新。
10. comparison/safety 的脚本与 LLM 结论不一致时不得 approve；semantic/structural 缺 required half、风险分母/文件/discovery/result/replay 任一门失败，或 N/A 未独立接受时同样不得 approve。
11. 当前版本发布检查 remote/local/post-release 均 accepted 后才允许图外 Completion Audit；任何 required self-reference 返回 reject / `E_AUDIT_SELF_REFERENCE`。
