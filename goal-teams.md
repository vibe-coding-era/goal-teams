# Goal Teams 用户指定要求

本文件记录用户对 `goal-teams` skill 的长期指定要求。后续更新 `SKILL.md`、`references/goal-teams-runtime.md`、`subagents/goal-*.toml`、`README.md` 或 `README.en.md` 时，需要优先对齐这些要求。

## 基本原则

- 默认全程中文：计划、表格、SPEC、tasklist、进度、成员包、总结都用中文；命令、路径、代码标识、API 名称保持原文。
- Goal Lead 和用户交流要人类友好、简约，少用特别专业的名词。
- 强制 Plan 模式：执行前先澄清、规划、表格确认。
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
- 如果没有 `agent.md` 或 `claude.md` 相关文件，建议用户创建，用来记录团队规则、编码风格、项目约束和跨工具协作约定。

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
- 执行过程使用表格反馈。
- 开发过程按 `tasklist.md`。
- 测试必须是独立的 subagent 或 skill，不能由实现者作为唯一测试者。
- 每个实现成员都要有锁定范围 `locked_scope`。
- 共享核心模块、高风险改动、认证、支付、迁移、破坏性写入、安全敏感集成、大范围 API 改动需要 Goal Lead 和用户确认。

## 发布仓库维护

- 更新 skill 规则时，同步更新：
  - `SKILL.md`
  - `references/goal-teams-runtime.md`
  - `agents/openai.yaml`
  - `subagents/goal-*.toml`
  - `README.md`
  - `README.en.md`
- 新增用户长期指定要求时，也要更新本文件。
