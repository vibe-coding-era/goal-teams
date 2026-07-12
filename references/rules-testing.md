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

## 最小颗粒度

每个功能切片必须在版本子目录 `TaskList.md` 中拆到以下颗粒度；不适用项写 `not_applicable_reason`：

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

## V2.34 架构后环境门

任一代码实现必须遵守 `Architecture Design accepted → development_environment_check ready → independent tests written → implementation`。环境检查不能和架构评审合并或由一句“环境正常”替代；实现 Owner 负责检查和安全改善，不同 `validator_run_id` 负责验证。

`development_environment_check` 至少绑定：

- accepted Architecture Design 的 exact path/hash 、contract revision/hash/assertion-set hash、workspace commit 与待改源文件 dirty-state manifest；
- 操作系统/架构、解析后的解释器和工具绝对路径、版本、可执行 hash，以及锁文件/现有依赖情况；
- 目标测试发现命令、必需 import/命令、文件系统权限、原子 replace/fsync 可行性、可用磁盘、实际工作目录与源文件安全边界；
- 所有实际执行命令的 argv/cwd/exit code/log，以及安全、仓库内、可逆的 remediation 的 before/after Evidence；
- 结论只能 `ready | needs_remediation | blocked`。`needs_remediation` 记录可逆修复和待复验项，不开放实现门；只有 current `local_verified` Evidence 且独立 validator 接受后才能 `ready`；架构、工作树、工具 path/hash 或关键依赖改变即 stale，必须重跑。

允许的环境改善仅限已授权、仓库内、可逆且不改变产品语义的动作，例如创建临时测试目录或校验本地工具。系统安装、外部下载、凭证使用、放宽权限、删除数据或跳过测试仍需新授权；不可为了让环境门通过而修改测试、合同或 Evidence。

## V2.35 测试用例断言合同

测试设计、执行、QA 和 Review 必须读取 `references/test-case-assertion-protocol.md`。V2.35 的 `unit|tdd|integration|e2e|cli|api|fixture` 用例都要有 schema-valid contract，非空 `input`、`processing`、`expected_output`、`assertions` 和真实 `test_file_refs`。

- 每条 assertion 有唯一 ID、受限 comparator、`actual_ref`，以及恰好一个 `expected_ref|expected_value`。
- 每案至少一个非 `exit_code_equals|status_code_equals` 的业务断言；prose-only、空 assertions、未知 comparator 或 exit/status-only 全部 fail closed。
- designer 在交接前运行 `scripts/checks/validate-test-case-contract.py`；runner 记录 `observed_output` 和逐 assertion result，不以退出码替代业务正确。
- integration/API 必须显式绑定 consumed input、processing 与业务 output/state；CLI 比较 stdout/file/state/hash；E2E 比较 DOM/URL/可见状态。
- TDD red Evidence 绑定测试 hash、pre-implementation tree、领域日志和 ledger 时序；implementation 后由不同 runner 产生 green。测试漂移或 implementation-before-red 关闭实现门。

## 后端与 API

- 后端、API、TDD 或完整测试编排使用 schema 机器值 `profile=full`；纯 CLI 且不含 UI 时仍为 `full`，但不得加载 UI 条件规则。
- 后端开发前必须先生成或更新 Backend Architecture Design，经独立评审 accepted 后再完成 Development Environment Check；环境未 ready 时不得写实现。
- 后端遵循 TDD：`goal_unit_test_designer` 先写单元测试用例，`goal_backend` 再实现，`goal_unit_test_runner` 独立执行并记录红/绿证据。
- V2.35 中上述 designer 同时产出 test-case contract；runner 返回 observed output 与 assertion results。API integration 不能只检查 HTTP/命令退出成功。
- 单元测试作者、后端实现者和单元测试执行者不能是同一唯一 subagent。
- 架构设计完成后，可以并行派发 `goal_api_integration_test_designer` 生成 API 集成测试脚本；默认脚本语言为 Python，默认测试框架为 `pytest`，除非项目已有更明确技术栈。
- 单元测试通过后，由 `goal_api_integration_test_runner` 执行 API 集成测试；无法执行时写阻塞、原因和风险。

## 前端与 E2E

- 前端开发前必须先生成或更新 Frontend Architecture Design，经独立评审 accepted 后再完成 Development Environment Check；不适用时写 `not_applicable_reason`。
- 前端开发完成后，由 `goal_e2e_test_designer` 生成 E2E 测试用例，再由 `goal_e2e_test_runner` 执行。
- E2E 用例作者不能作为唯一执行者。
- E2E contract 必须把输入/处理与 DOM、URL、可见交互状态或视觉 observable 对应起来；只有截图存在不等于 assertion passed。
- UI 任务的 E2E 和像素对比细节读取 `references/rules-ui.md`。

## 验证和打回

- 每个实现、文档或测试任务都必须有 Harness 契约、证据或 `not_applicable_reason`。
- 从 Harness 内层 `task_type`、`required_review_class` 与风险推导最低 `review_class`；comparison/safety 使用 LLM + 脚本双重复核，structural/semantic 不互代，只执行适用复核并记录经独立 reviewer 接受的结构化 N/A；记录到 `prompts/packets/dual-review-record.md`。
- 实现者自测不能替代独立校验。
- Evidence 不足时按原因使用 `task_state=running` 或 `blocked`，并把已执行失败/证据无效记录为 `check_state=failed`，无法执行/完成记录为 `check_state=blocked`；不得改写成 accepted/achieved。
