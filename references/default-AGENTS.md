# 默认 AGENTS.md 模板

当项目根目录或明显配置位置没有 `AGENTS.md`、`agents.md`、`agent.md`、`CLAUDE.md`、`claude.md` 时，Goal Teams 默认采用本模板作为团队执行准则，并建议用户把它复制到项目根目录的 `AGENTS.md` 中。

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.
<!-- 中文注释：这是一份用于减少 LLM 编码常见错误的行为准则。可根据具体项目补充项目级规则。 -->

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.
<!-- 中文注释：这些规则更偏向谨慎而不是速度。遇到非常简单、低风险的任务时，应结合上下文判断，不要机械执行。 -->

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**
<!-- 中文注释：不要默默假设，不要掩盖不确定性，要主动说明权衡。 -->

Before implementing:
<!-- 中文注释：在开始实现之前，先完成以下检查。 -->

- State your assumptions explicitly. If uncertain, ask.
  <!-- 中文注释：明确说出自己的假设。如果关键前提不确定，应先询问。 -->
- If multiple interpretations exist, present them; do not pick silently.
  <!-- 中文注释：如果需求存在多种理解，应列出这些理解，不要静默选择其中一种。 -->
- If a simpler approach exists, say so. Push back when warranted.
  <!-- 中文注释：如果存在更简单的实现方式，应说明；当需求会导致明显复杂化或风险时，应提出异议。 -->
- If something important is unclear, stop. Name what is confusing. Ask.
  <!-- 中文注释：如果重要信息不清楚，应暂停实现，明确指出不清楚的点并询问。低风险细节可以说明假设后继续。 -->

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**
<!-- 中文注释：只写解决当前问题所需的最少代码，不写猜测性的功能。 -->

- No features beyond what was asked.
  <!-- 中文注释：不要添加用户没有要求的功能。 -->
- No abstractions for single-use code.
  <!-- 中文注释：不要为了只使用一次的代码创建抽象。 -->
- No "flexibility" or "configurability" that was not requested.
  <!-- 中文注释：不要添加未被要求的灵活性或可配置性。 -->
- No complex error handling for purely theoretical scenarios.
  <!-- 中文注释：不要为纯理论上的异常场景编写复杂错误处理；必要的真实边界条件仍应处理。 -->
- If you write 200 lines and it could be 50, rewrite it.
  <!-- 中文注释：如果 50 行能清楚解决的问题写成了 200 行，应简化重写。 -->

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.
<!-- 中文注释：自检问题：资深工程师会不会认为这过度复杂？如果会，就应简化。 -->

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**
<!-- 中文注释：只修改必须修改的内容，只清理自己改动造成的问题。 -->

When editing existing code:
<!-- 中文注释：编辑已有代码时，遵守以下规则。 -->

- Do not "improve" adjacent code, comments, or formatting.
  <!-- 中文注释：不要顺手“优化”相邻代码、注释或格式。 -->
- Do not refactor things that are not broken.
  <!-- 中文注释：不要重构与当前任务无关、且没有出问题的代码。 -->
- Match existing style, even if you would do it differently.
  <!-- 中文注释：遵循现有代码风格，即使你个人会用另一种写法。 -->
- If you notice unrelated dead code, mention it; do not delete it.
  <!-- 中文注释：如果发现无关的死代码，可以说明，但不要擅自删除。 -->

When your changes create orphans:
<!-- 中文注释：当你的改动产生未使用代码时，按以下规则处理。 -->

- Remove imports, variables, or functions that your changes made unused.
  <!-- 中文注释：删除由你的改动造成的未使用 import、变量或函数。 -->
- Do not remove pre-existing dead code unless asked.
  <!-- 中文注释：不要删除改动前就已经存在的死代码，除非用户明确要求。 -->

The test: Every changed line should trace directly to the user's request.
<!-- 中文注释：检验标准：每一处改动都应能直接对应到用户的需求。 -->

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**
<!-- 中文注释：先定义成功标准，再反复执行和验证，直到满足标准。 -->

Transform tasks into verifiable goals:
<!-- 中文注释：把任务转化为可验证的目标。 -->

- "Add validation" -> "Write tests for invalid inputs, then make them pass"
  <!-- 中文注释：“添加校验”应转化为“为非法输入编写测试，然后让测试通过”。 -->
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
  <!-- 中文注释：“修复 bug”应转化为“编写能复现 bug 的测试，然后让测试通过”。 -->
- "Refactor X" -> "Ensure tests pass before and after"
  <!-- 中文注释：“重构 X”应转化为“确保重构前后测试都通过”。 -->

For multi-step tasks, state a brief plan:
<!-- 中文注释：对于多步骤任务，应先给出简短计划。 -->

1. [Step] -> verify: [check]
   <!-- 中文注释：第 1 步：说明操作，并说明如何验证。 -->
2. [Step] -> verify: [check]
   <!-- 中文注释：第 2 步：说明操作，并说明如何验证。 -->
3. [Step] -> verify: [check]
   <!-- 中文注释：第 3 步：说明操作，并说明如何验证。 -->

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
<!-- 中文注释：明确的成功标准能让执行过程自主推进；含糊标准，例如“让它能用”，通常需要反复澄清。 -->

### Harness Contract

For non-trivial tasks, define a lightweight Harness Contract before claiming done:
<!-- 中文注释：对于非平凡任务，在声称完成前先定义轻量 Harness 契约。 -->

- `checks`: what must be checked.
  <!-- 中文注释：需要检查什么。 -->
- `commands`: exact commands when they exist.
  <!-- 中文注释：如果有命令，写出精确命令。 -->
- `artifact_checks`: files, screenshots, logs, reports, or docs that prove the result.
  <!-- 中文注释：用来证明结果的文件、截图、日志、报告或文档。 -->
- `evidence_paths`: where evidence will be recorded.
  <!-- 中文注释：证据记录在哪里。 -->
- `failure_report`: how failures should be reported.
  <!-- 中文注释：失败时按什么格式报告。 -->
- `not_applicable_reason`: why a harness is not useful for this task.
  <!-- 中文注释：如果不适用，说明原因。 -->
- `harness_contract.task_type` and `required_review_class`: authoritative review policy inputs; outer fields cannot lower the class.
  <!-- 中文注释：Harness 内层任务类型和最低复核等级是权威输入；外层字段不能降级。 -->

Do not invent commands, CI jobs, or tools that do not exist. Use manual checks when that is the honest harness.
<!-- 中文注释：不要编造不存在的命令、CI 或工具。人工检查也是有效的 Harness，只要可复盘。 -->

For any UI-level task, include E2E testing in the Harness and record evidence. For replica/recreation tasks, take screenshots and perform pixel-level comparison against the reference; record the baseline, actual screenshot, diff image or metric, threshold, viewport, and conclusion.
<!-- 中文注释：任何界面级任务都要做 E2E 测试并记录证据；复刻/还原任务必须截图并与参考做像素级对比，记录基准图、实际图、diff 图或指标、阈值、viewport 和结论。 -->

For long-running, multi-agent, UI E2E, pixel comparison, benchmark, or production-flow work, record a Budget Gate and Conflict Policy before claiming completion.
<!-- 中文注释：长任务、多 agent、界面 E2E、像素对比、benchmark 或生产流任务，在完成前必须记录预算门和冲突策略。 -->

For Goal Teams projects, establish `ledger/events.jsonl` first and let the V2.3 reducer generate `TaskList.md`; members never edit that projection directly. SSOT outputs belong under `GoalTeamsWork-<project_version>/versions/<artifact_version>/` unless the user specifies another output directory. A chat-only `plan_preview` is the no-write exception and must not create either file.
<!-- 中文注释：Goal Teams 项目先建立 ledger，再由 reducer 生成 TaskList；成员不得直接编辑投影。聊天内 plan_preview 是不写文件的例外。 -->

For V2.36 execution, derive the policy and gate profile from product version, trusted target, task type, project size, work type, and risk. Lite and Standard omit inapplicable Architecture/full Environment/full-test tasks; Full and Regulated retain the complete gate chain. Omitting `state_gate_profile` never skips a gate, and an explicit value must match the derived result.
<!-- 中文注释：V2.36 从版本、可信目标、任务类型、规模与风险派生 Profile/gates；Lite/Standard 删除不适用的重门，Full/Regulated 保留完整门链，省略或伪造 state gate 都不能降级。 -->

The V2.35 `goal_security`, `goal_performance`, `goal_refactor`, and `goal_sqa` roles are read-only proposal specialists. They may return assessment, proposal, task patch, and dispatch request artifacts to Goal Lead, but cannot implement, dispatch, spawn nested teams, mutate central state, or self-verify. Goal Lead assigns independent implementation and validation runs.
<!-- 中文注释：V2.35 四专家只读且只提案，不得实现、派发、创建嵌套团队、写中央状态或自证；独立实现和验证由 Goal Lead 派发。 -->

Applicable V2.35 test cases must provide non-empty structured `input`, `processing`, `expected_output`, and executable `assertions`. Exit code or HTTP status alone does not prove business correctness; TDD and integration cases must bind inputs through processing to asserted business outputs.
<!-- 中文注释：V2.35 适用测试用例必须有非空输入、处理、期望输出和可执行断言；退出码或 HTTP status 不能单独证明业务正确。 -->

Backend work follows the derived gates: Full/Regulated uses Architecture-first independent TDD and API integration; Standard triggers those gates for contract/API/data/behavior impact; Lite uses targeted regression. API integration defaults to Python + pytest when required.
<!-- 中文注释：后端按派生门工作；Full/Regulated 使用架构先行与独立 TDD/API 链，Standard 按影响触发，Lite 使用 targeted regression。 -->

For implementation work, freeze a testable contract first. After Architecture Design is independently accepted, inspect the actual development environment, apply only authorized reversible in-repository remediation, and obtain independent current Evidence with conclusion `ready` before writing implementation code. `needs_remediation` or `blocked` does not open the implementation gate.
<!-- 中文注释：实现类工作先冻结可测试合同；架构设计独立 accepted 后，检查实际开发环境，只做已授权、仓库内、可逆改善，并在写实现代码前取得独立且 current 的 `ready` Evidence；`needs_remediation` 或 `blocked` 不开放实现门。 -->

Frontend work uses browser/E2E coverage proportional to the derived tier. Full/Regulated separates E2E designer and runner; Lite/Standard covers affected paths with independent review. Only replica/reference-driven UI requires a pixel baseline.
<!-- 中文注释：前端 browser/E2E 按等级覆盖；Full/Regulated 分离 designer/runner，Lite/Standard 覆盖受影响路径并独立复核，只有 replica 强制像素基线。 -->

V2.36 source Evidence uses a protected Git snapshot that auto-covers the complete change set, and independent Agent identity requires host attestation; caller-selected file lists or self-reported run IDs are insufficient.
<!-- 中文注释：V2.36 源码证据使用自动覆盖完整变更集的受保护 Git snapshot，独立 Agent 身份需要宿主 attestation；人工文件清单或自报 run ID 不足。 -->

Insufficient evidence cannot be marked complete. Missing E2E evidence, missing pixel diff evidence, self-validation-only work, missing independent review, or missing production approval/rollback/monitoring evidence must remain blocked or failed until resolved.
<!-- 中文注释：证据不足不能标记完成。缺少 E2E、缺少像素对比、只有自测、缺少独立评审、缺少生产审批/回滚/监控证据时，必须保持阻塞或失败状态，直到补齐。 -->

Derive reviews from the Harness first. Comparison/safety reviews require deterministic script evidence plus an independent LLM reviewer; structural/semantic are not interchangeable and may mark only the non-applicable half with an independently accepted structured reason. Command evidence records the real domain execution separately from the runtime-locked integrity replay; Completion executes only the latter.
<!-- 中文注释：先从 Harness 推导 review_class；semantic/structural 不互代。命令证据分开真实领域执行与完整性重放，Completion 只执行后者。 -->

Required checks bind exact expected domain argv/cwd and keep domain plus integrity execution inside the Run. Generic comparison uses the trusted exact-hash tool with a distinct, independently pre-approved baseline; a stricter review class inherits that obligation.
<!-- 中文注释：required Check 精确绑定领域命令；generic comparison 使用可信 exact-hash 工具和独立预批准 baseline，升级 review class 不移除该义务。 -->

V2.3 machine closure uses `ledger/checkpoint.json`, `identity/registry.json`, `harness/harness.json`, `harness/traceability.json`, `evidence/evidence.jsonl`, `reviews/dual-review.json`, and `audit/completion-audit.json`. Older root-level `harness.yaml`, `evidence.jsonl`, and `pipeline-state.json` are legacy/optional protocol data and cannot prove V2.3 completion. None of these artifacts implies a real runner, CI/CD system, production connection, or external approval system.
<!-- 中文注释：V2.3 使用版本目录内的 checkpoint、identity、Harness、Traceability、Evidence、Review 和 Audit 严格路径；旧根级文件不能证明 V2.3 完成。 -->

## 5. Code Quality Principles

**Use engineering principles as guardrails, not as excuses for abstraction.**
<!-- 中文注释：工程原则是约束和检查工具，不是制造抽象、扩大范围或过度设计的理由。 -->

### KISS: Keep It Simple

- Prefer the simplest implementation that satisfies the request.
  <!-- 中文注释：优先选择能满足需求的最简单实现。 -->
- Keep functions short and readable. If a function grows past 20-40 lines, check whether it has multiple responsibilities before splitting it.
  <!-- 中文注释：函数应保持短小且可读。若函数超过 20 到 40 行，应先检查是否职责过多，再决定是否拆分；不要为了行数限制机械拆分。 -->
- Avoid overengineering and premature optimization.
  <!-- 中文注释：避免过度设计和过早优化。只有在已有明确性能问题、扩展需求或维护成本时，才引入相应设计。 -->
- Prefer the standard library and existing project utilities before adding new third-party dependencies.
  <!-- 中文注释：优先使用标准库和项目内已有工具；只有在收益明确且成本可接受时，才新增第三方依赖。 -->
- Code should make its intent obvious without requiring cleverness.
  <!-- 中文注释：代码意图应一眼可见，不应依赖晦涩技巧才能理解。 -->

### SOLID: Apply When It Fits

Use SOLID as a design check for object-oriented or long-lived modules.
<!-- 中文注释：SOLID 适合用于面向对象代码或长期维护模块的设计检查，不应强行套用于一次性脚本或小范围修改。 -->

- Single Responsibility: each class or function should have one clear reason to change.
  <!-- 中文注释：单一职责：每个类或函数应只有一个清晰的变化原因。 -->
- Open/Closed: make extension easy only when extension is actually expected.
  <!-- 中文注释：开闭原则：只有在确实预期会扩展时，才为扩展性做设计；不要为了假想扩展增加复杂度。 -->
- Liskov Substitution: subclasses should preserve the behavior expected from their parent type.
  <!-- 中文注释：里氏替换：子类应保持父类型承诺的行为，不能破坏调用方对父类型的合理预期。 -->
- Interface Segregation: avoid forcing callers to depend on methods they do not use.
  <!-- 中文注释：接口隔离：不要让调用方依赖它不需要的方法。 -->
- Dependency Inversion: depend on abstractions when it reduces coupling; do not introduce abstractions by default.
  <!-- 中文注释：依赖倒置：只有当抽象能实际降低耦合时才依赖抽象，不要默认创建接口、工厂或依赖注入结构。 -->

Do not introduce interfaces, factories, inheritance, or dependency injection just to satisfy SOLID in a small or one-off change.
<!-- 中文注释：不要为了在小型或一次性改动中满足 SOLID，而引入接口、工厂、继承或依赖注入。 -->

### DRY: Remove Real Duplication

- Extract repeated logic when it appears multiple times and the shared behavior is stable.
  <!-- 中文注释：只有当重复逻辑已经多次出现，且共享行为相对稳定时，才抽取公共逻辑。 -->
- Prefer existing constants and configuration patterns in the project.
  <!-- 中文注释：优先沿用项目中已有的常量和配置管理方式。 -->
- Use reusable helpers or components only when they reduce real duplication and improve clarity.
  <!-- 中文注释：只有在能减少真实重复并提升清晰度时，才创建可复用 helper 或组件。 -->
- Avoid premature utility classes or generic templates.
  <!-- 中文注释：避免过早创建工具类或通用模板。 -->
- Small, intentional duplication is better than a confusing abstraction.
  <!-- 中文注释：少量有意保留的重复，优于难以理解的抽象。 -->

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
<!-- 中文注释：如果这些准则有效，应表现为：diff 中不必要的改动减少，因过度复杂导致的重写减少，并且澄清问题发生在实现前，而不是出错后。 -->

## 6. Independent Validation

**Generated artifacts need an independent check before they count as done.**
<!-- 中文注释：所有生成产物在计为完成前，都需要独立校验。 -->

- Documents should be validated by a non-author subagent or a user-selected skill.
  <!-- 中文注释：文档应由非作者 subagent 或用户指定 skill 校验。 -->
- Code should be checked by an independent QA, reviewer, or user-selected skill.
  <!-- 中文注释：代码应由独立 QA、评审成员或用户指定 skill 校验。 -->
- Test cases also need validation for target, assertions, and edge coverage.
  <!-- 中文注释：测试用例也要校验测试目标、断言和边界覆盖是否合理。 -->
- Record validation evidence in the version subdirectory, usually `progress.md`, `acceptance.md`, `test-plan.md`, `reports/`, or the relevant SPEC.
  <!-- 中文注释：校验证据应写入 `progress.md`、`acceptance.md`、`test-plan.md` 或相关 SPEC。 -->

Benchmark tasks are outside ordinary delivery work unless explicitly requested. When used, they should compare the same input under the same constraints and record output quality, failures, time, tokens, and cost.
<!-- 中文注释：Benchmark 任务不属于普通交付，除非用户明确要求。使用时应在同一输入和约束下比较，并记录产物质量、失败、耗时、tokens 和费用。 -->

Production-flow work should follow `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback` as a protocol only. Credentials, real deployments, destructive operations, production rollback, auth/payment/refund/permission changes, and security-sensitive modules require human approval or external system authorization before action.
<!-- 中文注释：生产流工作只把 `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback` 作为协议。凭证、真实部署、破坏性操作、生产回滚、认证/支付/退款/权限变更和安全敏感模块必须先获得人工审批或外部系统授权。 -->

## 7. Output Language

**Default generated content to Chinese unless the project already has another convention.**
<!-- 中文注释：除非项目已有其他语言规范，生成内容默认使用中文。 -->

- Requirements, PRD, architecture design, prototypes, test plans, and acceptance docs use Chinese.
  <!-- 中文注释：需求、PRD、架构设计、原型、测试计划和验收文档使用中文。 -->
- Code comments, test names, docstrings, and human-facing strings prefer Chinese when project style allows.
  <!-- 中文注释：在项目风格允许时，代码注释、测试名称、文档字符串和面向用户的字符串优先使用中文。 -->
- Keep commands, paths, identifiers, API names, dependency names, and raw logs unchanged.
  <!-- 中文注释：命令、路径、代码标识、API 名称、依赖名称和日志原文保持不变。 -->
