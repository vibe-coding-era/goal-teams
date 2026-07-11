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
| `scripts/validate-harness.py` | `scripts/harness/validate-harness.py` |
| `scripts/pixel-diff.py` | `scripts/harness/pixel-diff.py` |
| `scripts/compare-artifacts.py` | `scripts/review/compare-artifacts.py` |
| `scripts/validate-dual-review.py` | `scripts/review/validate-dual-review.py` |
| `scripts/benchmark-runner.py` | `scripts/benchmark/benchmark-runner.py` |

默认对用户展示兼容入口；在维护脚本实现时修改真实脚本。

## 版本同步

- `VERSION` 是当前版本来源。
- `SKILL.md` 正文、启动语、`README.md`、`README.en.md`、`goal-teams.md`、runtime 示例和 `agents/openai.yaml` 必须和 `VERSION` 保持一致。
- `SKILL.md` frontmatter 只保留 `name` 和 `description`，不放版本字段。
- 历史版本 `V2.02` 与 `V2.1` 是 `V2.3` 前的补丁线；后续版本优先使用 `V2.3`、`V2.4` 这类递增格式，避免继续新增 `V2.0x` 版本叙事。
- 发布或提交前运行 `./scripts/check.sh`。

## transport handle

运行时可能显示 `Reviewer C`、`QA B`、`Implementer A` 这类英文昵称；它们只作为 `transport_handle`。用户可见内容使用本地化 `display_name`；机器记录必须另外保留稳定 `member_id`、可加载 `agent_type` 和唯一 `agent_run_id`。
