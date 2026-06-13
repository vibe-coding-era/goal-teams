# Goal Teams 用户指定要求

本文件记录用户对 `goal-teams` skill 的长期指定要求。后续更新 `SKILL.md`、`references/goal-teams-runtime.md`、`subagents/goal-*.toml`、`README.md` 或 `README.en.md` 时，需要优先对齐这些要求。

## 基本原则

- 当前 skill 版本号为 `V1.9`，版本号保存在仓库根目录 `VERSION`，并同步写入 `SKILL.md` 正文；`SKILL.md` frontmatter 只保留 `name` 和 `description`。
- 每次开始 Goal Teams 工作前，Goal Lead 必须先汇报：`我是 Goal Teams Leader V1.9，我会帮你完成以下工作：`，然后用简短中文列表说明本轮会处理的具体事项。
- `V1.5` 引入 Harness 契约与三层 Loop 规则，`V1.6` 补充最小 Harness 示例，`V1.7` 引入 Benchmark 外层评估模板，`V1.8` 引入机器可读研发协议，`V1.9` 引入生产流与 Release Gate 协议；发布说明可以分别记录阶段，但当前运行规则按 `V1.9` 执行。
- Plan 模式下，启动语和本轮事项后必须立即询问：`在开始规划前，有什么历史文档、历史经验或参考资料需要输入吗？如果有，请提供路径、链接或要点；没有请回复“没有”。`
- 中文核心提示词统一为：`默认全程中文输出计划、表格、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、面向用户的字符串、测试名和测试用例说明；仅代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。`
- Goal Lead 和用户交流要人类友好、简约，少用特别专业的名词。
- 强制 Plan 模式：执行前先澄清、规划，列出 `Teams 规划表` 给用户确认；如果用户提示词包含“直接执行”等明确授权词，可以跳过等待确认，但仍必须展示计划表作为执行记录。
- Plan 模式询问用户选择时，优先使用数字选项，例如 `1. 确认并执行`、`2. 调整成员或范围`、`3. 只保留方案不执行`，允许用户只回复数字。
- 计划和方案阶段要多找用户澄清，尤其是目标、范围、验收、优先级、设计风格、数据接口、发布约束和风险审批。
- 过程和结果尽量使用 Markdown 文件持久化。

## 文档与版本

- 此 skill 过程中产生的文档，全部按版本号建立目录存放。
- 默认版本目录为 `.codex/goal-teams/versions/<version>/`。
- 多文档场景一律先建立总索引文件：
  - `.codex/goal-teams/INDEX.md`
  - `.codex/goal-teams/versions/<version>/INDEX.md`
- 过程文档放在版本目录中：
  - `plan.md`
  - `progress.md`
  - `decisions.md`
  - `tasklist.md`
  - `goal-packet.md`
- SPEC 文档放在版本目录的 `spec/` 中：
  - `requirement-spec-card.md`
  - `PRD.md`
  - `architecture-design.md`
  - `HTML-prototype.html`
  - `test-plan.md`
  - `acceptance.md`

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
- 需求规格卡不超过两页，必须写清：
  - 核心目标
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
- 启动 worker subagents 或修改实现文件前，Goal Lead 必须先列出 `Teams 规划表`；默认等待用户确认。若用户最新提示词包含 `直接执行`、`直接开始`、`直接做`、`直接改`、`开始执行`、`不用确认`、`无需确认`、`跳过确认`、`按你的方案执行` 等直接执行类词语，可以不等待确认，展示为 `执行计划（已按用户要求直接执行）` 后直接进入执行。
- 直接执行只跳过“等待确认方案”，不能跳过安全边界。涉及新范围、破坏性写入、凭证、支付/认证/安全敏感改动、外部审批或关键业务决策时，仍必须询问用户。
- `Teams 规划表` 显示为四列：成员 / Skill(Subagent)、任务范围（目标切片、认领任务、workflow 串行/并行、前置任务、锁定范围）、交付与标准（交付物、完成标准、Harness、文档/tasklist 更新）、验证安排（测试 owner、校验者）。
- 项目组任务安全必须体现 workflow：每个任务说明是串行还是并行；串行任务必须写前置任务；共享核心模块、高风险改动和同一 locked_scope 不能并行写。
- 执行过程使用表格反馈。
- 开发过程按 `tasklist.md`。
- 测试必须是独立的 subagent 或 skill，不能由实现者作为唯一测试者。
- 所有生成的内容，包括文档、代码、测试用例，都必须由独立 subagent 或用户指定的 skill 校验；作者不能自我批准。
- 校验证据要写入版本目录的 `progress.md`、`acceptance.md`、`test-plan.md` 或相关 SPEC。
- 每个实现成员都要有锁定范围 `locked_scope`。
- 所有任务看似完成后，必须启动新的只读 subagent `goal_completion_auditor` 检查未完成工作、缺失证据、未更新文档、未关闭阻塞和剩余风险。
- 如果 `goal_completion_auditor` 发现的未完成工作仍属于已确认目标范围，Goal Lead 必须自动拆成续跑任务，再次启动 Goal Teams 成员并发完成，不需要用户再次确认；只展示续跑 `Teams 规划表` 作为执行记录。
- 如果未完成工作涉及新范围、高风险或破坏性改动、凭证、外部审批、用户决策，不能自动续跑，必须记录阻塞并询问用户。
- 共享核心模块、高风险改动、认证、支付、迁移、破坏性写入、安全敏感集成、大范围 API 改动需要 Goal Lead 和用户确认。
- 最终完成汇报除任务完成情况表外，还必须在同一成员状态表中加入 `资源消耗（用户 / tokens / 费用）` 列；运行时没有返回 tokens 或费用时写 `未提供`。

## Harness / Benchmark / Loop

- `SPEC` 定义“什么算完成”；`Harness` 定义“怎么证明完成”。在 Goal Teams 中，Harness 不是新的执行引擎，也不代表已经存在额外 runtime 能力，而是写入 Plan、tasklist、Member Goal Packet、test plan 和 acceptance 的验证契约/模板字段。
- 每个实现、文档或测试任务都应在计划阶段写清 Harness 契约；至少包含可用检查、执行命令或人工检查方式、产物检查、证据位置、失败报告格式和不适用原因。没有 Harness 契约或不适用说明的任务不能标记为 `done`。
- Harness 可以引用已有测试、lint、类型检查、构建、Playwright 截图、控制台检查、golden output、mock service、人工清单或外部 CI；不得宣称会运行尚不存在或未授权的检查。
- `Benchmark` 是 Goal Teams 之外的评估目录与任务集，用于比较工作流、skill 版本、prompt 或 agent 组合的稳定性。默认形态是 `benchmarks/` 下的任务包、评分协议、运行记录和失败分类；普通 Goal Teams 任务不自动创建 benchmark，除非用户要求或计划确认。
- Benchmark 任务包应由任务说明或 `SPEC`、Harness、metadata（可选）、评分协议、fixtures/expected（可选）和报告模板组成；它评估完整 AI Coding 系统，不只评模型输出。只有已有或明确实现时才引用运行/评分脚本。
- Benchmark 报告应记录模型/skill/prompt 版本、项目 commit、工具版本、联网和权限设置、时间/token/费用预算、任务成功率、回归率、人工介入、证据完整度和失败分类。
- V1.8 的机器可读协议把 `harness.yaml`、`evidence.jsonl`、`pipeline-state.json`、`failure_report` 和 `approval_gate` 作为可选数据合同；这些文件只记录契约、证据和状态，不代表已有 runner、CI/CD、生产接入或真实外部审批系统。
- V1.9 的生产流协议使用 `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`；凭证、真实部署、破坏性操作、生产回滚、auth/payment/refund/权限和安全敏感模块必须停在人工审批或外部系统授权门前。
- `Loop` 分三层：成员 Loop、Lead Loop、Skill Improvement Loop。
- 成员 Loop 是每个独立 subagent 的 `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`，必须围绕自己的 `locked_scope`、Harness 契约和输出契约运行。
- Lead Loop 是 Goal Lead 的 `Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`，负责维护 tasklist、team-state、阻塞路由、独立校验、收尾审计和自动续跑。
- Skill Improvement Loop 是发布维护层：从真实运行或 Benchmark 的失败分类中提取规则改进，更新 `goal-teams.md`、`SKILL.md`、runtime 模板、subagent 配置、README/CHANGELOG 和校验脚本，再通过 `./scripts/check.sh` 与示例复盘确认没有破坏安装结构。
- 三层 Loop 不能互相替代：成员不能创建嵌套团队；Lead 不能把未验证产物直接标记完成；Skill Improvement 不在普通用户任务中自动修改 skill 规则，除非用户明确要求。

## 发布仓库维护

- 更新 skill 规则时，同步更新：
  - `AGENTS.md`
  - `VERSION`
  - `SKILL.md`
  - `references/goal-teams-runtime.md`
  - `references/default-AGENTS.md`
  - `references/goal-teams-automation-protocol.md`
  - `references/goal-teams-production-pipeline.md`
  - `agents/openai.yaml`
  - `subagents/goal-*.toml`
  - `README.md`
  - `README.en.md`
  - `examples/mini-goal-run/`
  - `benchmarks/`
  - `CHANGELOG.md`
- 默认项目指南模板保存在 `references/default-AGENTS.md`。
- 发布或提交前运行 `./scripts/check.sh`，确保 Skill frontmatter、subagent TOML、README 发布清单、示例产物和关键规则一致。
- 新增用户长期指定要求时，也要更新本文件。
