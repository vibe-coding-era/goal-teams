# Completion Auditor Workflow

1. 在候选收尾时只读加载输出目录、`memory.md`、ledger、TaskList、progress、decisions、SPEC、acceptance、测试 Evidence 和 review 记录；允许 required task 未 accepted 时产出 failed/blocked 并驱动 LOOP/停止，只有 passed/achieved 要求全 accepted。本次 Completion Audit 不得是被审 required/blocking task。
2. 读取 `prompts/packets/handoff-artifacts.md`，逐项核对 TaskList 交接物是否有具体 Owner/Validator member/run identity、task_state、check_state、Harness 和当前 Evidence。
3. 检查输出目录规则：用户未指定时必须是 `GoalTeamsWork-<project_version>/`；目录根部必须有 OKF `memory.md`。
4. UI 任务读取页面规格卡、HTML Prototype MOCK、`prompts/packets/html-prototype-mock.md` 和 `references/ui-visual-contract-protocol.md`，检查证据是否覆盖页面规格卡中的视觉风险和组件库元数据风险。
5. 检查每个任务的 Check `expected_domain_execution` 与 Evidence command exact 匹配、Run 包络完整；再从 Harness 内层 `task_type` / `required_review_class` 与风险重算最低 review class。核对 Evidence/Review 两层闭包；comparison/safety 继承义务并验证 trusted exact-hash tool、预批准 baseline 与 approver identity。
6. 检查 UI E2E、整页和局部像素级对比、组件级视觉契约、交互状态矩阵、locked/unlocked 截图、组件库元素记录、生产流审批和回滚证据。
7. 运行或核对 `validate-dual-review.py` 结果。
8. 缺少交接物独立检查、状态、Evidence、OKF 元数据或视觉风险覆盖时，不能输出 `audit_state=passed`。
9. 检查 required/blocking task 及 Audit Evidence 未引用本次实际 audit 文件；标准或自定义路径形成自引用时返回 `E_AUDIT_SELF_REFERENCE`。随后返回符合 template 的完整 Completion Audit JSON（不写文件），包含 audit/author/auditor identity、ledger revision、task digest、Evidence/Traceability/Review closure、状态、stop_reason 和 open gaps。
10. 要求 Lead/ledger owner 原样持久化后运行 `python3 scripts/v23/goalteams_v23.py completion-audit <audit.json> <checkpoint.json> --evidence-jsonl <evidence.jsonl> --evidence-root <output-root> --traceability <traceability.json> --review <dual-review.json> --identity-registry <identity/registry.json> --harness <harness/harness.json> --ledger <ledger/events.jsonl> --tasklist <TaskList.md>`；未看到真实 validator 结果时不得声称通过。
