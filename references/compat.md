---
type: Goal Teams Compatibility
title: Goal Teams Compatibility
description: Goal Teams 旧名、兼容入口、成员包布局和版本同步口径集中声明。
tags: [goal-teams, compatibility, scripts, okf]
timestamp: 2026-07-09T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Compatibility

本文件集中记录兼容口径，避免旧名散落在 `SKILL.md` 和成员提示词中。

## 文件名兼容

- 用户可见状态账本主名为 `TaskList.md`。
- `tasklist.md` 仅是 V2.2 typed migration 输入；V2.3 新写入只允许 reducer 生成 `TaskList.md`，不得双写或把旧 `done/checked` 直接映射为 `accepted`。
- SSOT 产出物统一写入输出根目录下的 `versions/<artifact_version>/`。
- 同目录同时存在 `tasklist.md` 与 `TaskList.md` 时进入 `manual_review` 并 fail-closed；migration 必须经过 `scan -> plan -> apply -> verify`，失败或显式 rollback 后保留原数据 byte-equivalent。

## 能力与互操作边界

- fallback 只有在 capability manifest 证明能力等价且权限不扩大时才可自动执行；否则记录 degraded capability 并进入 blocked 或请求用户。
- 自动续跑仅表示当前会话和宿主能力允许时的协议驱动 continuation，不代表后台 runner 或跨会话自动恢复服务。
- V2.3 与 OpenSpec、Superpowers 共存，但不宣称存在 schema/status/command adapter；完整 adapter 属于 V2.4 范围。

## V2.33 引用加载与安全降级

`SKILL.md` 的渐进式加载表只声明入口；缺失处置必须按以下分级执行，不能以“文件过多”静默跳过。

| 分级 | 范围 | 缺失处置 |
| --- | --- | --- |
| 核心 | `references/invariants.md`、V2.3 schema、当前任务的 ledger/Harness/Evidence/独立验证契约 | 记录路径与影响，`task_state=blocked`、`check_state=blocked`；禁止降级绕过 |
| 条件 | 已由任务触发的 UI、后端、测试、LOOP、迁移、安装、运行时或安全规则 | 同核心；触发即为当前任务必需依赖 |
| 可选 | 未触发范围的说明、示例或辅助材料 | 可不加载；若低风险且非 acceptance-blocking，可记录 `degraded_mode=single_agent` 继续 |

`degraded_mode=single_agent` 是运行记录，不新增或替代 V2.3 schema 状态字段。它只能用于 Harness 明确不要求独立验证的低风险非阻断工作；不得产出 `accepted`、`passed` 或 `achieved`，也不得用于外部写入、安全、迁移、UI/E2E、后端/API、长任务或 Completion Audit。

## V2.33 plan_preview 判定

- 仅当用户明确表达“只要规划/建议”，且明确表示“不落盘”“不创建/修改文件”或“只在聊天中返回”之一时，设置 `mode=plan_preview`、`profile=lite`、`writes_created=false`。
- “先做计划”“给我方案”在没有 no-write 限制时不是 `plan_preview`；需要按普通 Plan 持久化。
- 用户要求生成计划文档、需求卡片、TaskList、ledger、SPEC，或要求实施、派发、测试、提交时，必定不是 `plan_preview`；冲突表述按更严格的写入授权和上层规则处理，仍不猜测 no-write。
- 该判定只定义模式选择，不改变 V2.3 `task_state`、`check_state`、`audit_state`、`loop_decision` 或 `run_outcome` 枚举。

## V2.33 状态表述兼容

`check_state` 继续使用 V2.3 schema 的单值枚举。本文档和提示词中的“failed 或 blocked”仅表示选择其一：检查实际运行但未通过或证据无效为 `failed`；检查无法执行/完成（如缺授权、能力或核心依赖）为 `blocked`。禁止写入 `failed|blocked` 作为机器状态。

## V2.34 扩展兼容

- `feature_list.json` / `progress.md` / `contract.md` / `log.md` 是 legacy 自发布控制平面，不取代 V2.3 ledger、TaskList reducer、Harness、Evidence 或 Completion Audit。当前只由 `goal-teams-self-release-v2.39` 加载；V2.38 Profile 只读 replay，不是通用 core 默认文件集。
- 四文件不完整、marker/digest/checkpoint 不一致或有无法证明的 pending journal 时 fail closed；旧输出不得静默补齐或猜测 revision。
- 历史 V2.34 state/profile id 只用于 byte-compatible replay，不能作为 V2.36 当前门禁选择器；新任务必须由版本与任务类型重新派生 Profile。
- 历史 `docs/archive/V2.34/<delivery_id>/` 保持只读兼容。V2.36 自发布的新公开归档使用 `docs/archive/V2.36/<delivery_id>/`；普通项目不继承该归档路径。

## V2.35 增量兼容

- `references/rules-project-sizing.md`、`references/rules-specialists.md` 和 `references/test-case-assertion-protocol.md` 都是条件引用：结构化执行路由、专项命中、测试设计/执行/评审分别触发；触发后缺失即 blocked，未触发时不得预载四专家包。
- `project_size` 与 `work_type` 是 V2.35 route 的正交新字段；旧 V2.33 `plan_preview`/route 继续使用原入口，不能由新 adapter 猜测或补齐持久化输入。
- 四个新成员包使用标准四文件布局，agent type 为 `goal_security`、`goal_performance`、`goal_refactor`、`goal_sqa`；安装时与既有 `goal-*.toml` 一并管理。
- `scripts/validate-test-case-contract.py` 是 `scripts/checks/validate-test-case-contract.py` 的兼容入口；只对明确适用 V2.35 的 test-case fail closed，历史 V2.3 fixture 不静默伪升级。
- 无 version binding 的 V2.34 state/archive bytes 与错误码保持；显式 V2.35 descriptor 必须绑定 current contract/review，`project_version=release_version=V2.35`、artifact 可为 run 版本。错误 binding 必须 blocked，不得回退到 V2.34 目录。
- V2.35 release summary 是 pre-audit 公开候选说明；最终 Completion Audit 仅保存在私有过程 bundle，Audit 后不得为改 summary 制造新 commit/push。

## V2.36 Core 与 Profile 兼容

- 通用策略固定为 `references/goal-teams-core-v2.5.md` / `policy_profile=goal-teams-core-v2.5`。V2.36 产品版本不把通用策略号伪升级为 V2.36。
- `references/profiles/goal-teams-self-release-v2.37.md` / `policy_profile=goal-teams-self-release-v2.37` 只在可信 adapter 验证目标为 Goal Teams 仓库、产品版本 `V2.37` 且任务类型 `goal_teams_self_release` 时加载。
- V2.36 structured route 使用 `goal-teams-project-route-v2.36`，新增 `product_version`、`target_kind`、`ui_mode`；旧 `goal-teams-project-route-v2.35` 保持原输出和错误码，用于历史 replay，不静默采用新 Lite/Standard 语义。
- V2.36 的 Goal Teams 仓库身份固定锚定已接受的 V2.35 commit `c91e33737cc13c68bb5cb34c572fa05e7849f1e4`，不读取候选 worktree 的可变 `VERSION`/`SKILL.md` 决定身份。后续产品版本必须显式轮换该受信基线、对应测试与发布说明，不能沿用旧锚点猜测新版本身份。
- `policy_profile` 和 `task_type` 是派生输出。`state_gate_profile` 省略时自动派生并应用；显式提供时必须与派生值完全一致，否则 fail closed。合法输出始终包含派生值，不能通过字段存在或缺失绕过门禁。
- V2.36 的 `lite|standard|full|regulated` 是执行等级，不是 policy Profile。Lite/Standard 按规模、风险、发布和技术面减少不适用门；Full/Regulated 保持 Architecture、Environment、独立测试、Harness/Evidence 与完成审计强门。
- 新 V2.36 acceptance 使用 `v236_acceptance.py`、host route receipt、protected snapshot、attested identity registry、仓库外 persistent challenge state 与 `goal-teams-v2.36-acceptance-binding-v1`。无 state 的 identity/route 验证和 V2.3 `source_paths` 仍可用于历史诊断/replay，但不能生成新的 V2.36 `accepted|achieved`；检测到 V2.36 目标或产物时省略新输入必须 fail closed。
- `ui_mode=original` 只加载 `references/rules-ui.md` 与原创 UI 的 browser/DOM/几何证据规则，不加载 pixel reference；`ui_mode=replica` 才加载 `references/ui-e2e-pixel-protocol.md` 并至少 full。

## V2.38 Prompt Cache 可观测性兼容

- `references/profiles/goal-teams-self-release-v2.39.md` / `policy_profile=goal-teams-self-release-v2.39` 只在可信 adapter 验证目标为 Goal Teams 仓库、产品版本 `V2.39` 且任务类型 `goal_teams_self_release` 时加载；V2.36/V2.37/V2.38 Profile 仅保留历史 replay，不作为当前路由。
- `references/prompt-cache-manifest.json` 是 route-static 顺序、动态尾标签、artifact compiler 与 budget 的机器 SSOT。历史 route/schema/state ID 按原字节语义读取，不因 manifest 静默改序。
- `route_static_digest` 只绑定当前 route 计划的有序路径、长度和文件 bytes；`prefix_manifest_sha256` 绑定 route/顺序/动态尾标签；`stable_prefix_digest`/`runtime_prompt_digest` 只来自宿主最终 ordered manifest；`skill_tree_digest` 绑定完整安装树，互不替代。
- V2.38 usage 汇总新增 `observer_telemetry`、token-weighted `cached_input_share`、`uncached_input_tokens` 与 `telemetry_coverage`。旧报告无 usage 时保持 unavailable，不补零、不估算；无 request 粒度事件时 `request_hit_rate=null/unavailable`。

## 成员包布局

成员包标准文件为：

```text
prompts/members/<role>/prompt.md
prompts/members/<role>/template.md
prompts/members/<role>/workflow.md
prompts/members/<role>/scripts.md
```

先读 `prompt.md`；只有生成成员包、执行该角色 workflow 或需要脚本边界时，再读取同目录其他文件。

## 脚本入口兼容

| 兼容入口 | 真实脚本 |
| --- | --- |
| `scripts/check.sh` | `scripts/checks/check.sh` |
| `scripts/install-local.sh` | `scripts/install/install-local.sh` |
| `scripts/check-version-sync.py` | `scripts/checks/check-version-sync.py` |
| `scripts/check-routing-fixtures.py` | `scripts/checks/check-routing-fixtures.py` |
| `scripts/check-agent-names.py` | `scripts/checks/check-agent-names.py` |
| `scripts/check-member-layout.py` | `scripts/checks/check-member-layout.py` |
| `scripts/validate-test-case-contract.py` | `scripts/checks/validate-test-case-contract.py` |
| `scripts/validate-harness.py` | `scripts/harness/validate-harness.py` |
| `scripts/pixel-diff.py` | `scripts/harness/pixel-diff.py` |
| `scripts/compare-artifacts.py` | `scripts/review/compare-artifacts.py` |
| `scripts/validate-dual-review.py` | `scripts/review/validate-dual-review.py` |
| `scripts/benchmark-runner.py` | `scripts/benchmark/benchmark-runner.py` |
| 无兼容入口 | `scripts/v23/prompt_cache.py` |

默认对用户展示兼容入口；在维护脚本实现时修改真实脚本。

## 版本同步

- `VERSION` 是当前版本来源。
- `SKILL.md` 正文、启动语、`README.md`、`README.en.md`、`goal-teams.md`、runtime 示例和 `agents/openai.yaml` 必须和 `VERSION` 保持一致。
- `SKILL.md` frontmatter 只保留 `name` 和 `description`，不放版本字段。
- 历史版本 `V2.02` 与 `V2.1` 是 `V2.3` 前的补丁线；后续版本优先使用 `V2.3`、`V2.4` 这类递增格式，避免继续新增 `V2.0x` 版本叙事。
- 发布或提交前运行 `./scripts/check.sh`。
- GitHub Release 之前必须按 `references/release-packaging-protocol.md` 在本地生成并校验 `release/versions/<VERSION>/`；`docs/` 只保留非发行知识与凭证，不进入安装包或 GitHub 提交。
- V2.33 及后续版本必须保留 README 与双语 release/history 的分离结构；当前版本的文档、链接和标记缺失时 fail closed。
- V2.35 还必须同步四专家、三份条件 reference、三份 schema、test-case validator、双语 pre-audit release summary 与安装面；历史 V2.34 默认合同和 completion 文档不得批量改写。
- V2.39 必须同步当前 self-release V2.39 Profile、Cache Evidence 四状态轴、OKF policy/checker、README 双语说明与 release contents；V2.38 的 `references/prompt-cache-manifest.json` schema、`scripts/v23/prompt_cache.py`、prompt compiler、observer/report schema、fixtures 与 Profile 必须保留原字节语义用于兼容 replay，不得批量改写历史 V2.38/V2.36/V2.35/V2.3 机器合同。

## transport handle

运行时可能显示 `Reviewer C`、`QA B`、`Implementer A` 这类英文昵称；它们只作为 `transport_handle`。用户可见内容使用本地化 `display_name`；机器记录必须另外保留稳定 `member_id`、可加载 `agent_type` 和唯一 `agent_run_id`。
