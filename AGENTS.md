# Goal Teams 仓库维护指南

本仓库是 Codex Skill 包，不是业务应用。修改时优先保持规则一致、安装可用、示例可复盘。

## 工作区边界

- Goal Teams 的开发、临时 worktree、版本过程目录和生成文件不得创建在仓库根目录之外；禁止在父目录建立 `goal-teams-*` 兄弟目录。
- 所有开发过程版本和 Git worktree 统一放入根目录 `develops/<version-or-branch>/`；`develops/` 只在本地使用，禁止 Git 跟踪、安装、打包或上传 GitHub。
- 非发行知识、测试报告、历史过程与凭证统一放入根目录 `docs/`；`docs/` 只在本地使用，禁止 Git 跟踪、安装、打包或上传 GitHub。
- 正式发行快照统一放入 `release/versions/<VERSION>/`。GitHub Release 只能上传该目录经校验的资产；GitHub 分支可保留仓库治理与 CI 文件，但必须由 source-tree forbidden gate 排除所有非发行数据。
- 新建或移动 worktree 必须以 `develops/` 为目标；发布前必须运行 workspace boundary、package manifest 和 release validator，任一出现 `docs/`、`develops/` 或父目录版本副本即 fail closed。

## 维护原则

- `goal-teams.md` 记录长期用户指定要求，是规则变更的上游依据。
- `RULES.md` 承载 V2.02 Response Contract（响应规范），Goal Lead 和所有成员必须遵守。
- `VERSION` 只记录当前产品版本 `V2.41`，需要和 `SKILL.md` 正文、README 的 append-only V2.41 改动列表、runtime 启动语保持一致；公开 README 的 V2.40 发布投影由 development version checker 单独校验；通用核心策略版本为 `V2.5`，legacy 机器数据 schema 版本为 `V2.3`，三者不得混用；`SKILL.md` frontmatter 只保留 `name` 和 `description`。
- `SKILL.md` 是 Codex 发现和执行 skill 的主入口。
- `references/invariants.md` 承载所有任务永远生效的不变量、硬边界和失败降级协议。
- `references/compat.md` 集中声明 `TaskList.md`/`tasklist.md`、脚本兼容入口、成员包布局和版本同步口径。
- `references/rules-ui.md` 承载 UI、页面规格卡、HTML Prototype MOCK、E2E 和像素对比的条件规则。
- `references/rules-testing.md` 承载后端架构先行、TDD、API 集成 pytest、前端 E2E 和独立测试派发条件规则。
- `references/rules-loop.md` 承载 Lead LOOP、Loop Decision、Loop Gate、Budget Gate、Conflict Policy 和自动续跑边界。
- `references/goal-teams-core-v2.5.md` 承载普通项目通用核心策略、`goal-teams-core-v2.5` policy profile 和自动 gate 派生契约。
- `references/profiles/goal-teams-self-release-v2.41.md` 仅承载 Goal Teams 仓库当前自发布的 52 条断言、第 9/11 轮、四维评分、prompt identity、Cache Evidence、OKF、V2.41 发行状态机和公开归档规则；`goal-teams-self-release-v2.40.md`、`goal-teams-self-release-v2.39.md` 与 `goal-teams-self-release-v2.38.md` 只保留历史 replay，不得把任一 self-release 专项规则放回全局不变量。
- `references/rules-project-sizing.md` 承载项目规模、工作类型与安全/UI 覆盖的条件路由规则；V2.36 起 Lite/Standard 必须按实际风险和工作量保留轻量路径。
- `references/rules-specialists.md` 承载 V2.35 安全、性能、重构和 SQA 四个只读提案专家及 Lead-only dispatch 边界。
- `references/test-case-assertion-protocol.md` 承载 V2.35 测试输入、处理、期望输出与可执行断言契约。
- `references/goal-teams-runtime.md` 承载详细协议、模板和 CLI 示例。
- `references/goal-teams-automation-protocol.md` 承载 V1.8 机器可读 Harness/Evidence/Pipeline 协议。
- `references/goal-teams-production-pipeline.md` 承载 V1.9 生产流、Release Gate 和 safety gate 协议。
- `references/goal-teams-scripted-tooling.md` 承载 V1.92 提示词 + 脚本混合边界、Budget Gate、Conflict Policy 和证据不足打回规则。
- `references/prompt-cache-protocol.md` 承载 V2.38 兼容 route/runtime identity、observer telemetry，以及 V2.39/V2.40 fail-closed Cache Evidence 与 live probe 边界；`references/prompt-cache-manifest.json` 是 route-static 顺序、artifact compiler 与 budget 的机器 SSOT。
- `scripts/v23/v236_security.py` 承载 V2.36 统一 secret redaction/detection；`scripts/v23/v236_trust.py` 承载宿主 attestation、route receipt、持久 challenge state 与受保护 Git tree snapshot；`scripts/v23/v236_acceptance.py` 承载 Audit/Review/Harness/Evidence 完成绑定。runtime 与归档路径不得各自维护更窄的 secret pattern。
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
- V2.36 起 `policy_profile`、产品版本、任务类型和 route facts 自动派生 `gate_profile`；调用方不得通过提交或省略 `state_gate_profile` 自选门禁。
- V2.36 的 Lite/Standard 按风险、规模和任务类型生成必要任务与证据；只有高风险、跨模块、发布、安全、支付/认证、UI 复刻等覆盖事实才能升级到 Full/Regulated，不得因“存在代码/UI/测试”一律升级。
- V2.36 的 Evidence 必须以受保护 Git tree snapshot 自动覆盖完整 Git 变更集；Agent 独立性必须绑定宿主 attestation，并通过仓库外持久 challenge state 拒绝跨调用重放。最终 acceptance 还必须验证 host-signed route receipt、snapshot baseline/target、Audit/Review/Harness 完整 binding 与 Evidence core binding。候选仓库 runtime 永远没有宿主验收权限，只能返回 `E_V236_HOST_ADAPTER_REQUIRED`；仓库外宿主必须冻结完整验收输入树并在自己的受信进程中验证、消费 challenge。不同 `agent_run_id`、调用方自选 key/state、无 state 诊断验证、自报身份或手填文件清单不能支撑独立验收。
- V2.36 所有持久化、公开归档和运行时输出共用 secret redaction，并用 Authorization/Cookie、YAML/TOML、数据库 URI、`.netrc`、云凭证、协作工具 token 与非文本副本负向测试防回归。
- V2.35 四专家只能输出 assessment/proposal/task patch/dispatch request，不得直接实现、测试、派发、写中央状态或自证 verified；由 Goal Lead 派发独立实现和验证。
- `prompts/members/<role>/` 承载 V1.94 各角色成员包，每个目录包含 `prompt.md`、`template.md`、`workflow.md` 和 `scripts.md`。
- `prompts/packets/*.md` 承载 V1.93 Member Goal Packet、Doc Capsule、Harness Contract 和 Teams 表格模板。
- `prompts/packets/handoff-artifacts.md` 承载交接物 SSOT、Owner subagent、独立检查者、状态字段和 tasklist 账本规则。
- `prompts/packets/requirement-card.md` 承载 V1.95 需求卡片模板。
- `prompts/packets/page-spec-card.md` 承载 PRD 后、HTML 原型前的页面规格卡模板，覆盖组件级视觉契约、交互状态矩阵、视觉锁层策略和 UI Harness 证据。
- `prompts/packets/memory.md` 承载输出目录 `memory.md` 的 OKF 时间线模板。
- `prompts/packets/html-prototype-mock.md` 承载 HTML 原型 MOCK 的 OKF 元数据和组件库记录模板。
- `prompts/members/unit-test-designer/`、`unit-test-runner/`、`api-integration-test-designer/`、`api-integration-test-runner/`、`e2e-test-designer/`、`e2e-test-runner/` 承载 V2.0 TDD/API/E2E 独立测试成员包。
- `prompts/members/security/`、`performance/`、`refactor/`、`sqa/` 承载 V2.35 四专家标准四文件成员包。
- `references/dual-review-protocol.md` 承载 V1.94 LLM + 脚本双重复核协议。
- `scripts/checks/`、`scripts/harness/`、`scripts/review/`、`scripts/benchmark/`、`scripts/install/` 承载 V1.94 分目录脚本；根 `scripts/*.py` 和 `scripts/*.sh` 保留兼容入口。
- `scripts/checks/check-routing-fixtures.py` 承载只规划/需求卡片、纯后端 CLI、UI 复刻和长任务续跑的渐进式加载路由 fixtures。
- `subagents/goal-*.toml` 是实际可注册的成员 agent 配置。
- `README.md` 和 `README.en.md` 只做介绍、安装、示例和发布说明，避免承载唯一规则。
- `references/release-packaging-protocol.md` 是统一发行规范；所有版本必须先生成并校验 `release/versions/<VERSION>/`，再上传 GitHub Release。
- `scripts/release/` 承载发行构建、验证与 GitHub 发布后复核脚本；不得绕过本地 release 门禁直接上传。
- `scripts/checks/check-workspace-boundaries.py` 检查 worktree 不越出仓库、`docs/`/`develops/` 不被跟踪或安装、GitHub Release 资产只来自 `release/versions/`。

## 同步要求

更新运行规则时，通常需要同步检查：

- `goal-teams.md`
- `RULES.md`
- `VERSION`
- `SKILL.md`
- `references/invariants.md`
- `references/compat.md`
- `references/rules-ui.md`
- `references/rules-testing.md`
- `references/rules-loop.md`
- `references/goal-teams-core-v2.5.md`
- `references/profiles/goal-teams-self-release-v2.41.md`
- `references/profiles/goal-teams-self-release-v2.40.md`（历史 replay）
- `references/profiles/goal-teams-self-release-v2.39.md`（历史 replay-only）
- `references/profiles/goal-teams-self-release-v2.38.md`（历史 replay）
- `references/rules-project-sizing.md`
- `references/rules-specialists.md`
- `references/test-case-assertion-protocol.md`
- `references/goal-teams-runtime.md`
- `references/goal-teams-automation-protocol.md`
- `references/goal-teams-production-pipeline.md`
- `references/goal-teams-scripted-tooling.md`
- `references/prompt-cache-protocol.md`
- `references/prompt-cache-manifest.json`
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
