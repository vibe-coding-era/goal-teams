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
- `tasklist.md` 是兼容旧名；读取历史输出时接受，写入新输出时优先使用 `TaskList.md`。
- SSOT 产出物统一写入输出根目录下的 `versions/<artifact_version>/`。

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
- 历史版本 `V2.02` 与 `V2.1` 是 `V2.2` 前的补丁线；后续版本优先使用 `V2.3`、`V2.4` 这类递增格式，避免继续新增 `V2.0x` 版本叙事。
- 发布或提交前运行 `./scripts/check.sh`。

## transport handle

运行时可能显示 `Reviewer C`、`QA B`、`Implementer A` 这类英文昵称；它们只作为 transport handle。用户可见表格、Member Goal Packet、TaskList、progress、acceptance 和最终汇报使用中文 `member_id` / `display_name`。
