---
type: Tooling Reference
title: Goal Teams Scripted Tooling V1.94
description: 定义 Goal Teams 提示词判断与确定性脚本之间的职责和证据边界。
tags: [goal-teams, tooling, scripts, evidence]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Scripted Tooling V1.94

V1.92 采用“提示词负责判断，脚本负责确定性”的混合模型。Goal Lead 仍负责澄清、拆解、风险判断和最终整合；重复、易漏、需要精确一致的动作必须交给脚本。

V2.3 从 `harness_contract.task_type`、`required_review_class` 与风险推导最低 `review_class`：comparison/safety 采用 LLM + 脚本双重复核，structural/semantic 不互代，只执行适用复核并记录结构化 N/A。根 `scripts/*.py` 和 `scripts/*.sh` 是兼容入口；真实脚本位于 `scripts/checks/`、`scripts/harness/`、`scripts/review/`、`scripts/benchmark/` 和 `scripts/install/`。

## 分工边界

| 工作 | 默认方式 | 原因 |
| --- | --- | --- |
| 目标理解、成员拆分、风险取舍 | 提示词 | 需要上下文判断 |
| 版本号、启动语和 README 同步 | 脚本 | 必须完全一致 |
| subagent 命名和 transport handle 检查 | 脚本 | 规则固定，容易漏 |
| Harness/Evidence/Pipeline 字段校验 | 脚本 | 机器可读协议需要确定性 |
| E2E 截图与像素级对比 | 工具/脚本 | 需要真实证据和可复盘指标 |
| Benchmark 任务包检查与报告聚合 | 脚本 | 评分口径必须稳定 |
| prompt route 顺序、byte budget 与 digest | `references/prompt-cache-manifest.json` + 脚本 | 顺序和实际 bytes 必须可重算，不能由 prompt 自报 |
| provider/CLI cache usage 聚合 | runner 轮后脚本 | `observer_telemetry` 不能倒灌成当轮 Budget Gate 事实 |
| 冲突处理、预算取舍、自动续跑范围判断 | 提示词 + 表格 | 需要上下文，但必须记录字段 |

## Self-release 确定性边界

下表仅在当前 `policy_profile=goal-teams-self-release-v2.40` 时适用；V2.39/V2.38 Profile 只用于历史 replay，普通 Core V2.5 任务不创建固定第 9/11 轮、评分或归档事务。

| 工作 | 必须由脚本判定 | 不可由 prompt 代替 |
| --- | --- | --- |
| 四文件状态提交/恢复 | CAS、canonical digest、journal、temp/fsync/replace、marker-last、reconcile | 不得按 mtime/多数票猜测 current revision |
| Contract/Architecture/Environment/Implementation gate | exact hash、ledger prefix、identity independence、Evidence currency、顺序 | 不得以文本“已通过”开门 |
| 第 9 轮 reset | realpath containment、candidate manifest、authorization/hash、同文件系统 quarantine receipt | 不得删除 repo/用户数据或提供未授权 purge |
| V2.34 candidate snapshot | 临时 Git index/object tree、非空产品 delta、blob/current-byte manifest、主 index/HEAD/refs 前后指纹 | 不得以 `HEAD→HEAD`、人工文件清单或修改主 index/history 伪造候选 |
| 第 11 轮 delivery | 全部 fail-closed gates、sanitizer/manifest、归档事务、唯一 achieved 写入 | 缺口时不得进入 iteration 12 |
| 评分/分歧/瓶颈 | 四维 4×0.25 重算、五类分歧、prompt lifecycle、四级 bottleneck tuple | 不得自由输入 score、模糊猜分歧或固定瓶颈 |

Prompt/Lead 负责定义 intent、说明 judgment 和选择已授权动作；脚本负责验证状态、边界与绑定。`GTLOG` 诊断只输出确定性首个 divergence，不自动改 prompt；prompt patch 是受 locked scope/授权约束的独立任务，只有 regression + holdout 均通过才是 `verified`。

V2.40 继续由 `scripts/v23/prompt_cache.py` 的 V2.38-compatible schema 按 manifest 计算 route-static identity。`prefix_manifest_sha256` 绑定 route/顺序/动态尾标签，`route_static_digest` 绑定路径、长度与文件 bytes；完整安装由 `skill_tree_digest` 证明。只有宿主最终 ordered segments 可生成 stable/runtime digest；仓库侧必须报告 unavailable/partial，任何值都不是 provider key。V2.40 Cache Evidence 仍以 structural/host/live/request-hit 四状态轴报告；Tokens 或 Cache 命中率缺可信宿主 usage Evidence 时必须写 `未获取到` / `Unavailable`，不得估算。

## V2.35 Policy 与 Schema 边界

| 工作 | 确定性实现 | Prompt 不得代替 |
| --- | --- | --- |
| 双轴路由 | `scripts/v23/v235_policy.py` 校验完整字段、类型、优先级、稳定 reason codes | 不从自由文本猜 size/work type，不放宽 risk/UI override |
| Test-case contract | `schemas/v2.35/test-case.schema.json` + semantic validator | 不接受 prose-only、unknown comparator、exit/status-only |
| Specialist capability/lifecycle | policy 校验 role/capability/read-only/depth/transition/holdout | 不把 request 当 dispatch，不自我 verified |
| Version binding | `scripts/v23/version_binding.py` 校验 contract/review hash、版本和路径 containment | 不从 run suffix/任意 archive path 猜 release |

`scripts/checks/validate-test-case-contract.py` 是 canonical gate，`scripts/validate-test-case-contract.py` 是兼容入口；runtime `validate-test-case` 只薄委托。policy/validator 使用标准库、单 JSON、稳定排序，不扫描全树、不启动网络/浏览器/子进程。错误使用稳定 `E_V235_*` envelope。

## V1.94 脚本

| 脚本 | 用途 | 默认运行位置 |
| --- | --- | --- |
| `scripts/check.sh` -> `scripts/checks/check.sh` | 总校验入口，串联结构、版本、agent 命名、Harness、pixel diff、benchmark 包检查 | 本地 |
| `scripts/install-local.sh` -> `scripts/install/install-local.sh` | 安装/更新本地 skill 和 `goal-*.toml`，可选更新 fallback `team-*.toml` 中文昵称 | 手动运行 |
| `scripts/check-version-sync.py` -> `scripts/checks/check-version-sync.py` | 检查 `VERSION`、启动语、README、runtime、`agents/openai.yaml` 一致 | `./scripts/check.sh` |
| `scripts/check-routing-fixtures.py` -> `scripts/checks/check-routing-fixtures.py` | 运行只规划/需求卡片、纯后端 CLI、UI 复刻、长任务续跑 4 个路由 fixtures，检查触发词覆盖和条件加载不会互相污染 | `./scripts/check.sh` |
| `scripts/check-agent-names.py` -> `scripts/checks/check-agent-names.py` | 检查 subagent 中文昵称、`member_id` / `display_name` / `transport_handle` 规则 | `./scripts/check.sh` |
| `scripts/check-member-layout.py` -> `scripts/checks/check-member-layout.py` | 检查成员包目录和 `prompt/template/workflow/scripts` 文件完整性 | `./scripts/check.sh` |
| `scripts/validate-harness.py` -> `scripts/harness/validate-harness.py` | 校验 Harness contract JSON/YAML 字段；UI 要求 E2E，复刻要求 pixel diff | `./scripts/check.sh` |
| `scripts/pixel-diff.py` -> `scripts/harness/pixel-diff.py` | 对截图做像素级对比，输出 changed ratio、MAE、diff 图 | 手动或 Harness 调用 |
| `scripts/compare-artifacts.py` -> `scripts/review/compare-artifacts.py` | 对文件或目录做 hash/size/path 对比，生成脚本复核证据 | 手动或 Harness 调用 |
| `scripts/validate-dual-review.py` -> `scripts/review/validate-dual-review.py` | 校验脚本复核与 LLM 复核记录，防止单边通过 | `./scripts/check.sh` 或收尾审计 |
| `scripts/benchmark-runner.py` -> `scripts/benchmark/benchmark-runner.py` | 检查 benchmark task package 结构，必要时生成报告 | `./scripts/check.sh` |

## 双重复核边界

脚本复核负责可机械判断的事实；LLM 复核负责语义、用户目标和风险。当前 Harness 最低 review_class 的任一必需复核失败或缺失时不允许 `pass`；不适用项必须有独立接受的结构化 N/A。脚本报告把真实 `domain_execution` 与唯一可重放的 `integrity_replay` 分开记录。

## Budget Gate

长任务或生产流任务必须在 Plan 中写预算门：

```text
Budget Gate:
- max_subagents:
- max_auto_continue_rounds:
- time_budget:
- token_budget:
- cost_budget:
- stop_when_exceeded:
```

缺少实际 tokens 或费用时写 `unavailable`，不能估算成事实。预算不足时，Goal Lead 必须缩小范围、降级验证，或记录 `loop_decision=stop`、`run_outcome=partial|blocked` 与 `stop_reason=budget_exceeded`。

## Conflict Policy

并发任务必须记录冲突策略：

```text
Conflict Policy:
- shared_scope:
- write_owner:
- read_only_members:
- merge_owner:
- pause_conditions:
- replan_conditions:
```

同一 `locked_scope` 不允许多个实现成员并行写入。共享核心模块、认证、支付、迁移、安全敏感代码和大范围 API 合同默认串行。

## Evidence Insufficiency Rule

证据不足不能完成。以下情况必须被 QA、Reviewer 或 Completion Auditor 打回：

- 界面级任务没有 E2E 证据，也没有用户批准的例外。
- 复刻任务没有基准图、实际图、diff 图或差异指标。
- 实现者自测是唯一验证来源。
- Harness 只写了“人工检查通过”，没有检查项、证据路径或校验者。
- 生产流门禁缺少审批、凭证、监控或回滚证据却给出无条件 `pass`。

打回时使用 `failure_report`、单一 `check_state`（已执行失败为 `failed`，无法执行为 `blocked`）和合法的 run/loop 字段，不要把缺口改写成完成。
