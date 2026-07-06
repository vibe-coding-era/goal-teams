# Goal Teams 仓库维护指南

本仓库是 Codex Skill 包，不是业务应用。修改时优先保持规则一致、安装可用、示例可复盘。

## 维护原则

- `goal-teams.md` 记录长期用户指定要求，是规则变更的上游依据。
- `RULES.md` 承载 V2.02 Response Contract（响应规范），Goal Lead 和所有成员必须遵守。
- `VERSION` 记录当前 Skill 版本号，需要和 `SKILL.md` 正文、README、runtime 启动语保持一致；`SKILL.md` frontmatter 只保留 `name` 和 `description`。
- `SKILL.md` 是 Codex 发现和执行 skill 的主入口。
- `references/goal-teams-runtime.md` 承载详细协议、模板和 CLI 示例。
- `references/goal-teams-automation-protocol.md` 承载 V1.8 机器可读 Harness/Evidence/Pipeline 协议。
- `references/goal-teams-production-pipeline.md` 承载 V1.9 生产流、Release Gate 和 safety gate 协议。
- `references/goal-teams-scripted-tooling.md` 承载 V1.92 提示词 + 脚本混合边界、Budget Gate、Conflict Policy 和证据不足打回规则。
- `references/google-okf-bilingual-spec.md` 承载 V1.97 Google OKF 本地中英文规范、默认输出目录和 generated docs 格式规则。
- `references/ui-e2e-pixel-protocol.md` 承载 V1.92 界面 E2E、截图和像素级对比协议。
- `references/ui-visual-contract-protocol.md` 承载 UI 复刻防漏、视觉锁层、组件级视觉契约、交互状态矩阵和 Reviewer/Auditor 视觉风险门禁。
- `references/subagent-dispatch-protocol.md` 承载 V1.92 成员派发、中文展示名、transport handle 和冲突策略。
- `prompts/lead/*.md` 承载 V1.93 Goal Lead 核心、规划、派发、审计和完成提示词。
- `prompts/lead/requirement-card.md` 承载 V1.95 Plan 模式需求卡片规则。
- V1.96 起需求卡片、需求规格卡和 PRD 必须承接用户故事与功能验收标准，并让功能验收标准流向 tasklist、Harness、test plan 和 acceptance。
- V1.97 起所有生成 Markdown 文档默认采用 Google OKF；未指定生成目录时输出到 `GoalTeamsWork-<project_version>/`；输出目录必须维护 `memory.md`；页面规格卡和 HTML 原型 MOCK 必须记录组件库信息。
- V2.0 起所有 SSOT 产出物必须写入输出目录下的版本号子目录；每个项目先生成 `TaskList.md`；后端先架构设计再 TDD/实现；单元测试用例、单元测试执行、API 集成测试脚本/执行、E2E 用例/执行均由独立 subagent 负责。
- V2.02 起 `RULES.md` 定义执行期响应规范：执行优先、事实优先、未验证不宣称成功、区分观察和结论、减少无关解释。
- `prompts/members/<role>/` 承载 V1.94 各角色成员包，每个目录包含 `prompt.md`、`template.md`、`workflow.md` 和 `scripts.md`。
- `prompts/packets/*.md` 承载 V1.93 Member Goal Packet、Doc Capsule、Harness Contract 和 Teams 表格模板。
- `prompts/packets/handoff-artifacts.md` 承载交接物 SSOT、Owner subagent、独立检查者、状态字段和 tasklist 账本规则。
- `prompts/packets/requirement-card.md` 承载 V1.95 需求卡片模板。
- `prompts/packets/page-spec-card.md` 承载 PRD 后、HTML 原型前的页面规格卡模板，覆盖组件级视觉契约、交互状态矩阵、视觉锁层策略和 UI Harness 证据。
- `prompts/packets/memory.md` 承载输出目录 `memory.md` 的 OKF 时间线模板。
- `prompts/packets/html-prototype-mock.md` 承载 HTML 原型 MOCK 的 OKF 元数据和组件库记录模板。
- `prompts/members/unit-test-designer/`、`unit-test-runner/`、`api-integration-test-designer/`、`api-integration-test-runner/`、`e2e-test-designer/`、`e2e-test-runner/` 承载 V2.0 TDD/API/E2E 独立测试成员包。
- `references/dual-review-protocol.md` 承载 V1.94 LLM + 脚本双重复核协议。
- `scripts/checks/`、`scripts/harness/`、`scripts/review/`、`scripts/benchmark/`、`scripts/install/` 承载 V1.94 分目录脚本；根 `scripts/*.py` 和 `scripts/*.sh` 保留兼容入口。
- `subagents/goal-*.toml` 是实际可注册的成员 agent 配置。
- `README.md` 和 `README.en.md` 只做介绍、安装、示例和发布说明，避免承载唯一规则。

## 同步要求

更新运行规则时，通常需要同步检查：

- `goal-teams.md`
- `RULES.md`
- `VERSION`
- `SKILL.md`
- `references/goal-teams-runtime.md`
- `references/goal-teams-automation-protocol.md`
- `references/goal-teams-production-pipeline.md`
- `references/goal-teams-scripted-tooling.md`
- `references/google-okf-bilingual-spec.md`
- `references/ui-e2e-pixel-protocol.md`
- `references/ui-visual-contract-protocol.md`
- `references/subagent-dispatch-protocol.md`
- `references/dual-review-protocol.md`
- `prompts/lead/*.md`
- `prompts/members/*/{prompt.md,template.md,workflow.md,scripts.md}`
- `prompts/packets/*.md`
- `references/default-AGENTS.md`
- `scripts/*.py`
- `scripts/install-local.sh`
- `scripts/checks/*`
- `scripts/harness/*`
- `scripts/review/*`
- `scripts/benchmark/*`
- `scripts/install/*`
- `subagents/goal-*.toml`
- `README.md`
- `README.en.md`
- `examples/mini-goal-run/`
- `benchmarks/`

如果只改拼写、链接或发布说明，可以只改相关文档，但要运行校验脚本确认没有破坏安装结构。

## 校验

提交前运行：

```bash
./scripts/check.sh
```

该脚本会检查必需文件、Skill frontmatter、subagent TOML、README 发布清单、示例文档和关键规则关键词。

## 风格

- 默认中文说明；英文 README 与中文 README 保持信息等价。
- 命令、路径、配置键、API 名称保持原文。
- 不新增未验证的运行时能力描述。
- 不为小改动引入复杂生成流程；优先使用标准库脚本。
- 不擅自选择开源 License；发布前由仓库 owner 决定。
