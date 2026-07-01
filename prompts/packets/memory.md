---
type: Memory Ledger Template
title: Goal Teams memory.md 模板
description: 输出目录内 memory.md 的 OKF 模板，用于按时间线记录用户重要设置、配置和上下文摘要。
tags: [goal-teams, okf, memory, output-directory]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# memory.md 模板

`memory.md` 必须创建在本轮输出目录根部。没有用户指定生成目录时，输出目录为 `GoalTeamsWork-<project_version>/`；用户指定目录时，写入该目录。

```markdown
---
type: Memory Ledger
title: Goal Teams Memory - <project_version>
description: 记录本项目 Goal Teams 运行中的用户重要设置、配置和上下文摘要。
tags: [goal-teams, memory, <project_version>]
timestamp: <ISO 8601 datetime>
okf_version: "0.1"
goal_teams_version: <Vx.x>
project_version: <项目版本号>
author: GoalTeams
timeline_order: old_to_new
output_dir: <GoalTeamsWork-project_version 或用户指定目录>
---

# Memory Timeline

## <ISO 8601 datetime>

- author: GoalTeams
- type: user_setting | project_config | context_summary | component_library | output_directory | decision
- summary: <一句话摘要>
- details:
  - <重要设置、配置或上下文>
- source: <用户消息 / 文件路径 / URL / Git 仓库 / 推断来源>
- applies_to:
  - <相关产物或任务>
- status: active | superseded | blocked | confirmed
```

规则：

- 时间线从老到新追加，不倒序。
- `author` 固定为 `GoalTeams`。
- 记录用户重要设置、组件库名称和版本、输出目录、项目版本、上下文摘要、关键约束和已确认偏好。
- 如果后续用户更新设置，不覆盖旧条目；追加新条目，并把旧条目标记或说明为 `superseded`。
- 不记录密钥、令牌、个人敏感信息或无法安全持久化的凭证内容。
- 页面原型任务若已给出组件库、URL 或 Git 仓库，必须把该信息写入 `memory.md` 的 `component_library` 条目。
