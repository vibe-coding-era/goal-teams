# Goal Teams 用户指定要求

本文件记录用户对 `goal-teams` skill 的长期指定要求。后续更新 `SKILL.md`、`references/goal-teams-runtime.md`、`subagents/goal-*.toml`、`README.md` 或 `README.en.md` 时，需要优先对齐这些要求。

## 基本原则

- 当前 skill 版本号为 `V1.2`，版本号保存在仓库根目录 `VERSION`，并同步写入 `SKILL.md` frontmatter。
- 每次开始 Goal Teams 工作前，Goal Lead 必须先汇报：`我是 Goal Teams Leader V1.2，我会帮你完成以下工作：`，然后用简短中文列表说明本轮会处理的具体事项。
- 默认全程中文：计划、表格、SPEC、tasklist、进度、成员包、总结都用中文；命令、路径、代码标识、API 名称保持原文。
- 生成的内容全部使用中文，包括文档、代码注释、面向用户的代码字符串、测试名称、测试说明和测试用例描述；技术标识、命令、路径、API 名称、日志原文可保持原文。
- Goal Lead 和用户交流要人类友好、简约，少用特别专业的名词。
- 强制 Plan 模式：执行前先澄清、规划，列出 `Teams 规划表` 给用户确认。
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
- 团队成员展示名称使用中文，必须采用“角色 + 具体任务名”的 `<角色>-<任务名>` 格式，例如 `后端-WIKI 列表后端开发`、`前端-WIKI 列表页面开发`、`测试-WIKI 列表验收测试`。
- 启动 worker subagents 或修改实现文件前，Goal Lead 必须先列出 `Teams 规划表` 并等待用户确认；表格显示为四列：成员 / Skill/Subagent、任务范围（目标切片、认领任务、锁定范围）、交付与标准（交付物、完成标准、文档/tasklist 更新）、验证安排（测试 owner、校验者）。
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

## 发布仓库维护

- 更新 skill 规则时，同步更新：
  - `AGENTS.md`
  - `VERSION`
  - `SKILL.md`
  - `references/goal-teams-runtime.md`
  - `references/default-AGENTS.md`
  - `agents/openai.yaml`
  - `subagents/goal-*.toml`
  - `README.md`
  - `README.en.md`
  - `examples/mini-goal-run/`
  - `CHANGELOG.md`
- 默认项目指南模板保存在 `references/default-AGENTS.md`。
- 发布或提交前运行 `./scripts/check.sh`，确保 Skill frontmatter、subagent TOML、README 发布清单、示例产物和关键规则一致。
- 新增用户长期指定要求时，也要更新本文件。
