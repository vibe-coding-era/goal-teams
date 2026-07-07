# Goal Teams 用户指定要求

本文件记录用户对 `goal-teams` skill 的长期指定要求。后续更新 `SKILL.md`、`references/goal-teams-runtime.md`、`subagents/goal-*.toml`、`README.md` 或 `README.en.md` 时，需要优先对齐这些要求。

## 基本原则

- 当前 skill 版本号为 `V2.1`，版本号保存在仓库根目录 `VERSION`，并同步写入 `SKILL.md` 正文；`SKILL.md` frontmatter 只保留 `name` 和 `description`。
- 每次开始 Goal Teams 工作前，Goal Lead 必须先汇报：`我是 Goal Teams Leader V2.1，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，并使用 Harness + SPEC 做为过程与结果产物的约束：`，然后用简短中文列表说明本轮会处理的具体事项。
- `V1.5` 引入 Harness 契约与三层 Loop 规则，`V1.6` 补充最小 Harness 示例，`V1.7` 引入 Benchmark 外层评估模板，`V1.8` 引入机器可读研发协议，`V1.9` 引入生产流与 Release Gate 协议，`V1.91` 强化中文右边栏成员显示名、界面 E2E 和复刻像素级对比，`V1.92` 引入脚本化工具链、派发协议、冲突策略、预算门和证据不足打回规则，`V1.93` 引入 `SKILL.md` 轻量入口、`prompts/` 角色提示词目录和脚本分目录，`V1.94` 引入成员包子目录和 LLM + 脚本双重复核，`V1.95` 引入 Plan 模式 `需求卡片`，`V1.96` 引入用户故事和功能验收标准，`V1.97` 引入 Google OKF、默认输出目录、memory.md、页面规格卡/HTML 原型组件库记录，`V2.0` 引入版本子目录 SSOT、TaskList 先行、后端架构先行、TDD 单测生成/执行、API 集成 pytest 和前端 E2E 生成/执行，`V2.02` 引入 `RULES.md` 响应规范，`V2.1` 引入 Lead LOOP、Loop Decision、Loop Gate、状态快照和 `GT-BENCH-004`；发布说明可以分别记录阶段，但当前运行规则按 `V2.1` 执行。
- `SKILL.md` 只保留核心问题、硬边界、工作流摘要和渐进式加载路由；详细 Lead 提示词、成员角色提示词和 packet 模板放入 `prompts/`。
- `RULES.md` 承载 Goal Lead 和所有成员的 Response Contract，要求执行优先、只报告已验证事实、未验证不宣称完成、区分观察和结论、避免无关解释和建议。
- SSOT 是核心原则：交接物类型、Owner 字段、独立检查字段和状态字段以 `prompts/packets/handoff-artifacts.md` 为 Single Source of Truth；其他 workflow、template、README 和 runtime 示例只能引用或同步它，不能另起一套口径。
- Google OKF 是生成文档的核心格式：所有 Markdown 输出默认使用 YAML frontmatter，且必须包含非空 `type`；本地双语规范为 `references/google-okf-bilingual-spec.md`。
- 用户未指定生成目录时，输出根目录默认写入 `GoalTeamsWork-<project_version>/`；该目录必须包含 OKF `memory.md`，按时间线从老到新记录重要用户设置、配置、组件库、上下文摘要和决策，作者固定为 `GoalTeams`。
- 所有 SSOT 产出物必须写入输出目录下的版本号子目录，例如 `GoalTeamsWork-<project_version>/versions/<artifact_version>/`；不同版本的 SPEC、TaskList、Harness、Evidence 和 Acceptance 不得混放。
- Plan 模式下，启动语和本轮事项后必须立即询问：`在开始规划前，如果有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“2”。`
- Plan 模式接到需求后，必须先写入 `需求卡片`，用简洁方案把核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险讲清楚，再进入完整 SPEC、tasklist 和 Teams 规划表。
- 中文核心提示词统一为：`默认全程中文表格化输出计划、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。`
- UI 页面、复刻、还原、截图对齐或前端交互页面必须在 PRD 完成后先产出 `page-spec-card.md`，再进入 HTML Prototype MOCK、静态页面开发或动态前端页面开发；非 UI 任务必须写 `not_applicable_reason`。
- 页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面任务必须先澄清组件库名称、版本、URL 或 Git 仓库；如果用户提示词里已有，必须记录到本项目输出目录的 `memory.md`、`page-spec-card.md` 和 HTML OKF 元数据。
- 页面规格卡必须在 OKF 头部记录组件库名称和版本，元素级记录每个元素的组件库名；组件有数据模型时必须记录数据模型或 mock 引用。
- 生成的 HTML 原型 MOCK 必须通过注释、`application/okf+yaml` 或 `data-*` 自定义属性记录组件库信息，并被 Harness 检查。
- 每个项目必须先生成版本子目录内的 `TaskList.md`（兼容旧名 `tasklist.md`）再派发实现或测试。
- TaskList 的最小颗粒度必须到功能级：某功能的需求规格卡、PRD、页面规格卡、HTML 原型、前端开发、前后端架构设计、后端 TDD、后端开发、后端执行 TDD、API 集成测试脚本生成、API 集成测试、API 集成测试执行、生成 E2E 测试用例、执行 E2E 测试用例、BugFix、测试报告生成。
- 后端开发必须先生成或更新后端架构设计文档，再进入单元测试和实现。
- 后端遵循 TDD：不同 subagent 先写单元测试用例，再由后端 subagent 写代码，再由新的独立 subagent 执行并跑通单元测试用例。
- 架构设计完成后，可以同步派发 API 集成测试脚本生成 subagent；默认用 Python 作为脚本语言，默认使用 `pytest` 框架；单元测试完成后再执行 API 集成测试。
- 前端开发完成后，可以单独派发 E2E 测试用例生成 subagent，并由另一个独立 subagent 执行 E2E 测试用例。
- UI 复刻防漏协议为 `references/ui-visual-contract-protocol.md`，任何整页 diff、视觉锁层、baseline overlay、组件视觉契约、弹窗/表单/菜单/头像/表格/分页验收都必须遵守该协议。
- Goal Lead 和用户交流要人类友好、简约，少用特别专业的名词。
- 强制 Plan 模式：执行前先澄清、规划，列出 `Teams 规划表` 给用户确认；如果用户提示词包含“直接执行”等明确授权词，可以跳过等待确认，但仍必须展示计划表作为执行记录。
- Plan 模式询问用户选择时，优先使用数字选项，例如 `1. 确认并执行`、`2. 调整成员或范围`、`3. 只保留方案不执行`，允许用户只回复数字。
- 计划和方案阶段要多找用户澄清，尤其是目标、范围、验收、优先级、设计风格、数据接口、发布约束和风险审批。
- 过程和结果尽量使用 Markdown 文件持久化。

## 文档与版本

- 此 skill 过程中产生的文档，全部按项目版本号建立目录存放。
- 默认输出根目录为 `GoalTeamsWork-<project_version>/`，除非用户明确指定其他生成目录。
- 多文档场景一律先建立输出目录索引和 memory：
  - `GoalTeamsWork-<project_version>/index.md`
  - `GoalTeamsWork-<project_version>/memory.md`
- SSOT 产出物放在版本子目录中：
  - `GoalTeamsWork-<project_version>/versions/<artifact_version>/index.md`
  - `GoalTeamsWork-<project_version>/versions/<artifact_version>/TaskList.md`
  - `GoalTeamsWork-<project_version>/versions/<artifact_version>/tasklist.md`（兼容旧名，可与 `TaskList.md` 同步）
- 过程文档放在版本子目录中：
  - `plan.md`
  - `progress.md`
  - `decisions.md`
  - `TaskList.md`
  - `goal-packet.md`
- `TaskList.md` 是执行状态账本，必须记录每个交接物的 `artifact_type`、Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness、证据路径和阻塞/延期原因。
- SPEC 文档放在版本子目录的 `spec/` 中：
  - `requirement-card.md`
  - `requirement-spec-card.md`
  - `PRD.md`
  - `page-spec-card.md`
  - `frontend-architecture-design.md`
  - `backend-architecture-design.md`
  - `HTML-prototype.html`
  - `test-plan.md`
  - `acceptance.md`
- 测试文档和脚本默认放在版本子目录的 `tests/` 或项目既有测试目录中，并在 TaskList 记录路径：
  - `unit/` 后端单元测试用例
  - `api-integration/` API 集成测试脚本，默认 Python + pytest
  - `e2e/` E2E 测试用例
  - `reports/` 测试报告和失败证据
- `memory.md` 必须记录：
  - 输出目录和项目版本
  - 用户重要设置/配置
  - 组件库名称、版本、来源 URL 或 Git 仓库
  - 重要上下文摘要
  - 后续用户更新设置时的 superseded 记录

## 环境检查

- 计划阶段先检查项目根目录或明显配置位置是否存在：
  - `AGENTS.md`
  - `agents.md`
  - `agent.md`
  - `CLAUDE.md`
  - `claude.md`
- 如果没有 `agent.md` 或 `claude.md` 相关文件，使用 `references/default-AGENTS.md` 作为默认执行准则，并建议用户复制到项目根目录的 `AGENTS.md`，用来记录团队规则、编码风格、项目约束和跨工具协作约定。

## 需求分析师角色

- 新增团队角色：`goal_requirements_analyst`，中文名为“需求分析师”。
- 需求分析师通过交谈帮助用户完善需求。
- 需求分析师可以在可用且合适时使用：
  - 网络搜索
  - computer use
  - browser
  - Chrome
- 需求分析师先生成一份人类友好的需求规格卡，再生成或交接 PRD。
- 需求分析师必须读取 Lead 先写入的 `需求卡片`，把其中的目标、功能、用户故事、功能验收标准、边界、约束和风险展开为 `Requirement Specification Card`。
- 需求规格卡不超过两页，必须写清：
  - 核心目标
  - 用户故事
  - 功能验收标准
  - 业务重要功能结构
  - 主要流程
  - 边界和非目标
  - 关键假设和未决问题
- PRD 必须基于已确认的需求规格卡生成，不能直接从零散对话跳到 PRD。

## OpenSpec 与 Superpower

- 如果用户在使用时指定 `openspec` 或 `superpower`，默认只做好 Goal Lead 这个角色。
- 在该模式下，Goal Lead 只负责：
  - 检查环境
  - 询问版本号
  - 创建或规划索引
  - 整理澄清问题
  - 准备 lead-level 计划和文档
- 不自动启动完整角色团队，除非用户再次明确确认。

## 团队执行规则

- 用户可以指定某个成员使用其他 skill、plugin、自定义 subagent 或内置 subagent。
- 默认 subagent 成员的运行时 subagent id、`member_id` 和展示名必须一致，采用 `<中文角色>-<任务名>`，例如 `后端-WIKI 列表后端开发`；`role` 字段使用中文角色，例如 `后端`；真实可加载的 subagent 配置名保留在 `skill_or_subagent`，例如 `goal_backend`。
- 如果用户指定使用某个 skill，则运行时 subagent id、`member_id`、展示名和 `role` 都使用 `<skill 名称>-<任务名>` 的前缀，例如 `browser-WIKI 列表页面验证`；`skill_or_subagent` 同步记录该 skill。
- 默认成员必须优先使用 `goal_*` 自定义 subagents，避免把 Goal Teams 任务派给内置 `team_reviewer`、`team_qa`、`team_implementer`、`team_researcher`。只有用户明确指定这些内置成员时才可使用。V2.0 新增 `goal_unit_test_designer`、`goal_unit_test_runner`、`goal_api_integration_test_designer`、`goal_api_integration_test_runner`、`goal_e2e_test_designer`、`goal_e2e_test_runner`。
- 如果 Codex 运行时或右边栏显示 `Reviewer C`、`QA B`、`Implementer A` 这类英文昵称，只把它作为 transport handle；`Teams 规划表`、Member Goal Packet、tasklist、team-state、events 和最终汇报仍必须使用中文 `member_id` / `display_name`。
- Member Goal Packet 的首段必须写明中文成员展示名，并要求成员回复首行使用 `成员：<中文展示名>`，防止右边栏英文临时名泄漏成用户可见身份。
- 启动 worker subagents 或修改实现文件前，Goal Lead 必须先列出 `Teams 规划表`；默认等待用户确认。若用户最新提示词包含 `直接执行`、`直接开始`、`直接做`、`直接改`、`开始执行`、`不用确认`、`无需确认`、`跳过确认`、`按你的方案执行` 等直接执行类词语，可以不等待确认，展示为 `执行计划（已按用户要求直接执行）` 后直接进入执行。
- 直接执行只跳过“等待确认方案”，不能跳过安全边界。涉及新范围、破坏性写入、凭证、支付/认证/安全敏感改动、外部审批或关键业务决策时，仍必须询问用户。
- `Teams 规划表` 显示为四列：成员 / Skill(Subagent)、任务范围（目标切片、认领任务、workflow 串行/并行、前置任务、锁定范围）、交付与标准（交付物、完成标准、Harness、文档/tasklist 更新）、验证安排（测试 owner、校验者）。
- `Teams 规划表` 和 Member Goal Packet 中的交接物必须来自 `prompts/packets/handoff-artifacts.md`；派发前必须在 tasklist 中创建或补齐交接物行。
- 项目组任务安全必须体现 workflow：每个任务说明是串行还是并行；串行任务必须写前置任务；共享核心模块、高风险改动和同一 locked_scope 不能并行写。
- 并发任务必须记录 Conflict Policy：共享范围、写 Owner、只读成员、合并 Owner、暂停条件和重新规划条件。同一 `locked_scope` 不允许多个实现成员并行写。
- 长任务、自动续跑、生产流、Benchmark、浏览器 E2E 或像素对比任务必须记录 Budget Gate：最大成员数、最大续跑轮次、时间、tokens、费用和超限停止条件。
- 执行过程使用表格反馈。
- 开发过程按版本子目录内的 `TaskList.md`/`tasklist.md`。
- 执行过程中，每个成员都要持续更新自己负责的 tasklist 交接物行；只在最终总结补写状态不合格。
- 测试必须是独立的 subagent 或 skill，不能由实现者作为唯一测试者。
- 所有生成的内容和交接物，包括文档、代码、测试用例、Harness、证据、acceptance 和 tasklist 更新，都必须由独立 subagent 或用户指定的 skill 校验；作者不能自我批准。
- 每个交接物必须标明完成情况和负责人：Owner subagent 负责产出，validator subagent 负责独立检查；缺少独立检查状态、证据路径或阻塞/延期原因时，不能标记为 `done`。
- 校验证据要写入输出目录的 `progress.md`、`acceptance.md`、`test-plan.md` 或相关 SPEC。
- 每个实现成员都要有锁定范围 `locked_scope`。
- 所有任务看似完成后，必须启动新的只读 subagent `goal_completion_auditor` 检查未完成工作、缺失证据、未更新文档、未关闭阻塞和剩余风险。
- 如果 `goal_completion_auditor` 发现的未完成工作仍属于已确认目标范围，Goal Lead 必须自动拆成续跑任务，再次启动 Goal Teams 成员并发完成，不需要用户再次确认；只展示续跑 `Teams 规划表` 作为执行记录。
- 如果未完成工作涉及新范围、高风险或破坏性改动、凭证、外部审批、用户决策，不能自动续跑，必须记录阻塞并询问用户。
- 共享核心模块、高风险改动、认证、支付、迁移、破坏性写入、安全敏感集成、大范围 API 改动需要 Goal Lead 和用户确认。
- 最终完成汇报除任务完成情况表外，还必须在同一成员状态表中加入 `资源消耗（用户 / tokens / 费用）` 列；运行时没有返回 tokens 或费用时写 `未提供`。

## Harness / Benchmark / Loop

- `SPEC` 定义“什么算完成”；`Harness` 定义“怎么证明完成”。在 Goal Teams 中，Harness 不是新的执行引擎，也不代表已经存在额外 runtime 能力，而是写入 Plan、tasklist、Member Goal Packet、test plan 和 acceptance 的验证契约/模板字段。
- 每个实现、文档或测试任务都应在计划阶段写清 Harness 契约；至少包含可用检查、执行命令或人工检查方式、产物检查、证据位置、失败报告格式和不适用原因。没有 Harness 契约或不适用说明的任务不能标记为 `done`。
- 每个交接物都应在计划阶段写入 tasklist，并在执行阶段从 `planned` / `claimed` / `in_progress` 推进到 `ready_for_review`、`checked` 或 `done`；独立检查失败时必须记录 `changes_requested`、`blocked` 或 `deferred`。
- Harness 可以引用已有测试、lint、类型检查、构建、Playwright 截图、控制台检查、golden output、mock service、人工清单或外部 CI；不得宣称会运行尚不存在或未授权的检查。
- 任何界面级任务都必须进入 E2E Harness，至少覆盖关键用户路径、主要 viewport、控制台错误和最终可见状态；不能运行 E2E 时不得标记为 `done`，必须记录阻塞、风险或用户明确批准的例外。
- 任何复刻、临摹、还原、对照参考图/参考页面的界面任务，都必须截图并做像素级对比，记录基准图、实际图、diff 图或差异指标、阈值、viewport 和结论；缺少可比较参考时必须记录阻塞或 `not_applicable_reason`。
- 任何 UI 复刻、还原、临摹、对照截图或对照页面任务，不能只依赖整页 pixel diff；关键组件必须有组件级视觉契约和可执行断言，小组件必须有局部 crop 或几何断言。
- 使用视觉锁层、baseline overlay 或截图遮挡层时，必须同时提供 locked screenshot 和 unlocked real DOM screenshot；锁层截图不能作为唯一通过证据。
- 弹窗、表单、菜单、头像、表格、分页等用户可见组件必须覆盖交互态证据；弹窗至少覆盖打开态、错误态、切换态、关闭态和移动端态。
- Reviewer 发现“锁层不证明真实 DOM”、组件断言缺失或交互态缺证据时，必须触发补偿性 Harness；Completion Auditor 必须审查证据是否覆盖风险，而不只是证据是否存在。
- V1.92 采用提示词 + 脚本混合模式：目标理解、调度、冲突和预算判断由 Goal Lead 负责；版本同步、agent 命名、Harness schema、像素 diff、benchmark 包检查和本地安装由脚本做确定性校验。
- V1.93 将角色提示词拆到 `prompts/lead/`、`prompts/members/` 和 `prompts/packets/`，执行时按 `SKILL.md` 渐进式加载路由只读取相关文件。
- V1.94 将 `prompts/members/` 进一步拆成成员包子目录；每个成员目录必须包含 `prompt.md`、`template.md`、`workflow.md` 和 `scripts.md`。
- V1.94 对对比和校验类任务要求 LLM + 脚本双重复核；脚本负责确定性检查，LLM reviewer 负责语义和风险复核，任一缺失或失败都不能给 `pass`。
- V1.95 在 Plan 模式新增 `需求卡片`：Lead 接到需求后先写输出目录的 `spec/requirement-card.md`，覆盖核心目标、关键功能、边界、约束和风险；它是简洁方案，不替代后续需求规格卡、PRD 或测试计划。
- V1.96 要求需求卡片、需求规格卡和 PRD 都承接 `用户故事` 与 `功能验收标准`；功能验收标准必须能流向 tasklist、Harness、test plan 和 acceptance。
- V1.97 要求所有生成 Markdown 文档默认采用 Google OKF；用户没有指定生成目录时，所有输出默认进入 `GoalTeamsWork-<project_version>/`；输出目录根部必须维护 `memory.md`；页面规格卡和 HTML Prototype MOCK 必须记录组件库及元素级组件库归属。
- V2.0 要求所有 SSOT 产出物按版本子目录隔离；每个项目先生成 TaskList；后端先架构设计再 TDD/开发；API 集成测试默认 Python + pytest；前端开发后由独立 subagent 生成并执行 E2E。
- V2.02 要求 Goal Lead 和所有成员遵守 `RULES.md` 响应规范：简洁、事实优先、执行优先，未验证时明确标注。
- V2.1 要求 Lead LOOP 成为执行期闭环协议：每轮 `Integrate` 后记录 `Loop Decision`，长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖任务必须记录 `Loop Gate` 和状态快照；Lead LOOP 不代表新的 runtime、后台执行器、CI/CD 或生产审批系统。
- 可用脚本包括兼容入口 `scripts/install-local.sh`、`scripts/check-version-sync.py`、`scripts/check-agent-names.py`、`scripts/check-member-layout.py`、`scripts/validate-harness.py`、`scripts/pixel-diff.py`、`scripts/compare-artifacts.py`、`scripts/validate-dual-review.py` 和 `scripts/benchmark-runner.py`；真实脚本按职责放入 `scripts/install/`、`scripts/checks/`、`scripts/harness/`、`scripts/review/` 和 `scripts/benchmark/`。
- 证据不足不能完成。缺少 E2E、缺少像素级对比、只有实现者自测、缺少独立校验或生产流缺少真实审批/回滚/监控证据时，必须打回并记录 `failure_report`、`blocked` 或 `blocked_needs_user`。
- `Benchmark` 是 Goal Teams 之外的评估目录与任务集，用于比较工作流、skill 版本、prompt 或 agent 组合的稳定性。默认形态是 `benchmarks/` 下的任务包、评分协议、运行记录和失败分类；普通 Goal Teams 任务不自动创建 benchmark，除非用户要求或计划确认。
- Benchmark 任务包应由任务说明或 `SPEC`、Harness、metadata（可选）、评分协议、fixtures/expected（可选）和报告模板组成；它评估完整 AI Coding 系统，不只评模型输出。只有已有或明确实现时才引用运行/评分脚本。
- Benchmark 报告应记录模型/skill/prompt 版本、项目 commit、工具版本、联网和权限设置、时间/token/费用预算、任务成功率、回归率、人工介入、证据完整度和失败分类。
- V1.8 的机器可读协议把 `harness.yaml`、`evidence.jsonl`、`pipeline-state.json`、`failure_report` 和 `approval_gate` 作为可选数据合同；这些文件只记录契约、证据和状态，不代表已有 runner、CI/CD、生产接入或真实外部审批系统。
- V1.9 的生产流协议使用 `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`；凭证、真实部署、破坏性操作、生产回滚、auth/payment/refund/权限和安全敏感模块必须停在人工审批或外部系统授权门前。
- `Loop` 分三层：成员 Loop、Lead LOOP、Skill Improvement Loop。
- 成员 Loop 是每个独立 subagent 的 `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`，必须围绕自己的 `locked_scope`、Harness 契约和输出契约运行。
- Lead LOOP 是 Goal Lead 的 `Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`，负责维护 tasklist、team-state、阻塞路由、独立校验、收尾审计、Loop Decision 和自动续跑边界。
- Skill Improvement Loop 是发布维护层：从真实运行或 Benchmark 的失败分类中提取规则改进，更新 `goal-teams.md`、`SKILL.md`、runtime 模板、subagent 配置、README/CHANGELOG 和校验脚本，再通过 `./scripts/check.sh` 与示例复盘确认没有破坏安装结构。
- 三层 Loop 不能互相替代：成员不能创建嵌套团队；Lead 不能把未验证产物直接标记完成；Skill Improvement 不在普通用户任务中自动修改 skill 规则，除非用户明确要求。

## 发布仓库维护

- 更新 skill 规则时，同步更新：
  - `AGENTS.md`
  - `RULES.md`
  - `VERSION`
  - `SKILL.md`
  - `references/goal-teams-runtime.md`
  - `references/default-AGENTS.md`
  - `references/google-okf-bilingual-spec.md`
  - `references/goal-teams-automation-protocol.md`
  - `references/goal-teams-production-pipeline.md`
  - `references/goal-teams-scripted-tooling.md`
  - `references/ui-e2e-pixel-protocol.md`
  - `references/subagent-dispatch-protocol.md`
  - `references/dual-review-protocol.md`
  - `prompts/lead/*.md`
  - `prompts/members/*.md`
  - `prompts/members/*/{prompt.md,template.md,workflow.md,scripts.md}`
  - `prompts/packets/*.md`
  - `prompts/packets/memory.md`
  - `prompts/packets/html-prototype-mock.md`
  - `agents/openai.yaml`
  - `scripts/*.py`
  - `scripts/checks/*`
  - `scripts/harness/*`
  - `scripts/review/*`
  - `scripts/benchmark/*`
  - `scripts/install/*`
  - `scripts/install-local.sh`
  - `subagents/goal-*.toml`
  - `README.md`
  - `README.en.md`
  - `examples/mini-goal-run/`
  - `benchmarks/`
  - `CHANGELOG.md`
- 默认项目指南模板保存在 `references/default-AGENTS.md`。
- 发布或提交前运行 `./scripts/check.sh`，确保 Skill frontmatter、subagent TOML、README 发布清单、示例产物和关键规则一致。
- 新增用户长期指定要求时，也要更新本文件。
