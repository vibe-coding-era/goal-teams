---
type: Goal Teams Testing Rules
title: Goal Teams Testing Rules
description: 后端架构先行、TDD、API 集成测试、前端 E2E 和独立测试派发规则。
tags: [goal-teams, testing, tdd, e2e, okf]
timestamp: 2026-07-09T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Testing Rules

只在任务涉及实现、测试、API、CLI、MCP、前端交互、E2E、QA、验收或测试报告时读取本文件。

## 必读文件

- `prompts/packets/handoff-artifacts.md`
- `references/subagent-dispatch-protocol.md`
- `prompts/packets/harness-contract.md`
- 对应成员包：`prompts/members/<role>/prompt.md`，必要时读取同目录 `template.md`、`workflow.md`、`scripts.md`

API/E2E 路由还必须把本文件、`references/test-case-assertion-protocol.md`、适用 `integration-test-plan`、`test-case`、`test-run-result` 的 exact `context_refs` 和 validator argv 写入 Member Goal Packet/Harness。成员不得仅加载通用 prompt、沿用历史 validator 或自行猜测 artifact 路径；required ref 缺失即 blocked。

## 适用颗粒度

每个功能切片只创建当前 `profile` 与技术面实际触发的任务；不得为 Lite/Standard 预建 18 个空任务。Full/Regulated 使用下表的完整适用链，其他等级只保留 required/conditional 命中的行；不适用项可在计划层集中写 `not_applicable_reason`，无需逐项制造任务。

| 顺序 | 任务 | 默认 Owner |
| --- | --- | --- |
| 1 | 需求规格卡 | `goal_requirements_analyst` |
| 2 | PRD | `goal_product` |
| 3 | 页面规格卡 | `goal_product` 或 `goal_frontend` |
| 4 | HTML 原型 | `goal_frontend` |
| 5 | 前端架构设计 | `goal_frontend` |
| 6 | 后端架构设计 | `goal_backend` |
| 7 | Development Environment Check | 当前实现 Owner |
| 8 | 前端开发 | `goal_frontend` |
| 9 | 后端 TDD 单元测试用例 | `goal_unit_test_designer` |
| 10 | 后端开发 | `goal_backend` |
| 11 | 后端单元测试执行 | `goal_unit_test_runner` |
| 12 | API 集成测试脚本生成 | `goal_api_integration_test_designer` |
| 13 | API 集成测试计划 | `goal_api_integration_test_designer` |
| 14 | API 集成测试执行 | `goal_api_integration_test_runner` |
| 15 | E2E 测试用例 | `goal_e2e_test_designer` |
| 16 | E2E 测试执行 | `goal_e2e_test_runner` |
| 17 | BugFix | 对应实现 Owner |
| 18 | 测试报告 | `goal_qa` 或 `goal_docs` |

## 分级实现门

- `lite`：scoped contract 与 targeted validation 必需；Architecture 默认 `not_required`，环境使用可复现的轻量 preflight。变更行为必须有当前检查证据，但不强制完整环境报告或三方 TDD 角色链。
- `standard`：当前环境检查、适用独立测试与独立 Review 必需；只有合同/API/数据/持久化/跨模块边界改变时 Architecture 为 required，否则可记录结构化 `not_applicable_reason`。
- `full|regulated`：严格遵守 `Architecture Design accepted → development_environment_check ready → independent tests/current TDD red → implementation`。环境检查不能和架构评审合并或由一句“环境正常”替代；实现 Owner 负责检查和安全改善，不同 `validator_run_id` 负责验证。
- 路由结果是门禁 SSOT；不得因 payload 省略 `state_gate_profile` 跳过，也不得自行把 full 门降为 standard/lite。

Full/Regulated 的 `development_environment_check` 至少绑定：

- accepted Architecture Design 的 exact path/hash 、contract revision/hash/assertion-set hash、workspace commit 与待改源文件 dirty-state manifest；
- 操作系统/架构、解析后的解释器和工具绝对路径、版本、可执行 hash，以及锁文件/现有依赖情况；
- 目标测试发现命令、必需 import/命令、文件系统权限、原子 replace/fsync 可行性、可用磁盘、实际工作目录与源文件安全边界；
- 所有实际执行命令的 argv/cwd/exit code/log，以及安全、仓库内、可逆的 remediation 的 before/after Evidence；
- 结论只能 `ready | needs_remediation | blocked`。`needs_remediation` 记录可逆修复和待复验项，不开放实现门；只有 current `local_verified` Evidence 且独立 validator 接受后才能 `ready`；架构、工作树、工具 path/hash 或关键依赖改变即 stale，必须重跑。

允许的环境改善仅限已授权、仓库内、可逆且不改变产品语义的动作，例如创建临时测试目录或校验本地工具。系统安装、外部下载、凭证使用、放宽权限、删除数据或跳过测试仍需新授权；不可为了让环境门通过而修改测试、合同或 Evidence。

## 测试用例断言合同

测试设计、执行、QA 和 Review 必须读取 `references/test-case-assertion-protocol.md`。任何被路由为 required 的 `unit|tdd|integration|e2e|cli|api|fixture` 用例都要有 schema-valid contract，非空 `input`、`processing`、`expected_output`、`assertions` 和真实 `test_file_refs`。Lite 的一次性 targeted check 可使用 Harness 内联断言，不必伪装成完整 test-case 文档。

- 每条 assertion 有唯一 ID、受限 comparator、`actual_ref`，以及恰好一个 `expected_ref|expected_value`。
- 每案至少一个非 `exit_code_equals|status_code_equals` 的业务断言；prose-only、空 assertions、未知 comparator 或 exit/status-only 全部 fail closed。
- designer 在交接前运行 Goal Packet/Harness 指定的当前 schema validator；runner 记录 `observed_output` 和逐 assertion result，不以退出码替代业务正确。V2.35 legacy case 才使用兼容入口。
- integration/API 必须显式绑定 consumed input、processing 与业务 output/state；CLI 比较 stdout/file/state/hash；E2E 比较 DOM/URL/可见状态。
- TDD red Evidence 绑定测试 hash、pre-implementation tree、领域日志和 ledger 时序；implementation 后由不同 runner 产生 green。测试漂移或 implementation-before-red 关闭实现门。

V2.44 的 API/E2E required 测试除 case contract 外，还必须形成完整机器链：

```text
acceptance / API / persona / state / failure mode
  → integration-test-plan risk denominator
  → typed test-case
  → real file existence + sha256 + discovery
  → independent test-run-result
  → replayable Evidence
  → independent QA / Review
```

- `integration-test-plan` 必须以稳定 `risk_id` 建立分母，记录来源、严重度、适用性、case refs 与 covered/uncovered。已有 case 数不是分母；`blocked|not_run|unavailable|unknown|flaky` 都保留为 uncovered。
- 只有来源证明风险确实不适用且有独立 reviewer acceptance 的 `not_applicable_reason`，才可从 applicable denominator 排除；不得删除失败项、降低分母或用 unavailable 伪造 100%。
- API case 显式声明 method/path、persona/auth、headers/path/query/body、pre-state、processing、expected status/response、post-state、side effects、cleanup；高风险面覆盖 authorization、idempotency、retry、concurrency、compensation、eventual consistency 或逐项 accepted N/A。
- E2E case 显式声明 persona/session、initial URL/pre-state、browser/viewport、ordered actions、step checkpoints、final DOM/URL/visible/business state、side effects、cleanup；适用时覆盖 session refresh、permission denied、double-click、loading/disabled、network failure/recovery、refresh/back/multi-tab。
- 每个 test ref 必须是受保护树内的相对路径，绑定当前 sha256 和真实 framework discovery ID；字符串路径、文件存在但零发现、hash 漂移或 case/discovery 映射不完整均 failed。
- runner 必须产出 schema-valid `test-run-result`，绑定 source/plan/case/identity、exact argv/cwd、environment、attempts、observed outputs/states、assertion results、artifacts、cleanup 与 replay recipe。designer、implementation owner、runner、reviewer 按 gate 要求保持独立 identity。
- retry 只用于计划预授权的诊断；首次失败必须保留，`fail→pass` 是 `flaky` 而不是 clean passed。cleanup failed、Evidence 不可重放或 artifact hash 不匹配关闭通过门。

## 后端与 API

- 后端/API 不再仅因技术面自动 `full`：small/medium、low/medium risk、非 release 可为 standard；large/release 或高风险覆盖仍为 full/regulated。纯 CLI 的 small low-risk 局部改动可为 lite。
- Standard 的 API feature/bugfix 仍必须执行 integration gate；API surface 本身就是集成边界，不能仅因项目规模较小标记为 `not_required`。Standard backend-only feature 可将 TDD 作为影响范围门，backend-only bugfix 的 integration 仅在 API/data/cross-component boundary 改变时适用。
- Backend Architecture Design 只在路由 `gates.architecture=required` 时必须生成或更新；standard 的内部局部实现可由影响分析证明不改变合同/API/数据边界。
- `full|regulated` 后端遵循完整 TDD：`goal_unit_test_designer` 先写单元测试用例，`goal_backend` 再实现，`goal_unit_test_runner` 独立执行并记录红/绿证据。Standard bugfix 在可测试行为上要求 red/green，但允许按影响合并最小测试设计交接；Lite 使用针对性 regression。
- V2.35 中上述 designer 同时产出 test-case contract；runner 返回 observed output 与 assertion results。API integration 不能只检查 HTTP/命令退出成功。
- V2.44 的 API designer 还必须产出风险分母驱动的 `integration-test-plan`；runner 必须产出可重放 `test-run-result`。QA/Reviewer 独立复算 denominator，并验证 test file existence/hash/discovery，不接受设计者自报覆盖率。
- Full/Regulated 的单元测试作者、后端实现者和单元测试执行者不能是同一唯一 subagent；Standard 至少由非实现者独立复核/执行 required checks。
- 架构设计完成后，可以并行派发 `goal_api_integration_test_designer` 生成 API 集成测试脚本；默认脚本语言为 Python，默认测试框架为 `pytest`，除非项目已有更明确技术栈。
- 单元测试通过后，由 `goal_api_integration_test_runner` 执行 API 集成测试；无法执行时写阻塞、原因和风险。

## 前端与 E2E

- 前端 Architecture/Environment 按路由 gate 执行：原创 UI 的 small/low-risk 局部改动可不生成 Architecture；Full/Regulated 和跨页面状态/数据/组件边界变化仍必须先设计、评审和环境验证。
- 前端开发完成后，由 `goal_e2e_test_designer` 生成 E2E 测试用例，再由 `goal_e2e_test_runner` 执行。
- Full/Regulated 的 E2E 用例作者不能作为唯一执行者；Lite/Standard 至少由独立 reviewer 检查关键路径结果与 Evidence。
- E2E contract 必须把输入/处理与 DOM、URL、可见交互状态或视觉 observable 对应起来；只有截图存在不等于 assertion passed。
- E2E plan/case 必须把 persona、session/permission、initial state、ordered actions 与 step checkpoints 写成机器字段；runner 保留首次 attempt、console/network、DOM/URL/visible/business state 和 cleanup。框架自动 retry 不得隐藏 flake。
- UI 任务先读取 `references/rules-ui.md`；只有 `ui_mode=replica` 才加载像素 baseline 协议，原创 UI 不因缺参考图 blocked。

## 验证和打回

- 每个实现、文档或测试任务都必须有 Harness 契约、证据或 `not_applicable_reason`。
- 从 Harness 内层 `task_type`、`required_review_class` 与风险推导最低 `review_class`；comparison/safety 使用 LLM + 脚本双重复核，structural/semantic 不互代，只执行适用复核并记录经独立 reviewer 接受的结构化 N/A；记录到 `prompts/packets/dual-review-record.md`。
- 实现者自测不能替代独立校验。
- Evidence 不足时按原因使用 `task_state=running` 或 `blocked`，并把已执行失败/证据无效记录为 `check_state=failed`，无法执行/完成记录为 `check_state=blocked`；不得改写成 accepted/achieved。
- QA/Reviewer 必须从上游 acceptance/API/persona/state/failure mode 重建风险分母，对照 plan diff，并至少重放一个适用高风险 case；plan/case/result validator、file/hash/discovery、cleanup/replay 任一 required 门失败即不得 pass。
