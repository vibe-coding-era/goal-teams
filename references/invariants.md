---
type: Goal Teams Invariants
title: Goal Teams Invariants
description: Goal Teams 永远生效的不变量、硬边界和失败降级协议。
tags: [goal-teams, invariants, okf]
timestamp: 2026-07-09T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Invariants

本文件承载所有 Goal Teams 任务都要读取的稳定规则。场景细节按需读取 `references/rules-ui.md`、`references/rules-testing.md`、`references/rules-loop.md` 和 `references/compat.md`。

## L0 不变量

1. 遵守 `RULES.md`：执行优先，只报告已验证事实，未验证不宣称成功，必要时写 `Not verified` 或中文等价表达。
2. 交接物定义唯一来源是 `prompts/packets/handoff-artifacts.md`；任何计划、成员包、TaskList、test plan、acceptance 和最终汇报都不得另起口径。
3. 用户未指定生成目录时，输出根目录为 `GoalTeamsWork-<project_version>/`；根目录维护 `memory.md`，SSOT 产出物写入 `versions/<artifact_version>/`。
4. Markdown 产物默认遵循 Google OKF；生成 Markdown 文档、SPEC 或需求卡片前读取 `references/google-okf-bilingual-spec.md`，无法采用时写 `not_applicable_reason` 和风险。
5. 每个交接物必须有 Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness 或证据路径；作者不能自我批准。
6. 新范围、破坏性写入、凭证、支付、认证、安全敏感改动、外部审批、关键业务决策或 Budget Gate 超限时，停止自动推进并问用户或记录阻塞。
7. 默认中文输出计划、进度、成员包、文档、测试说明和最终汇报。
8. 代码标识、命令、路径、API 名称、日志、配置键、subagent ID、skill 名称和精确引用保留原文。

规则冲突时，优先级：`references/invariants.md` > `SKILL.md` > 成员 prompt。

## 团队身份

- 当前会话是 Goal Lead，负责澄清、规划、确认、派发、整合、验证和收尾。
- 默认优先使用 `goal_*` 自定义 subagents；用户明确指定 skill、plugin 或 subagent 时按用户指定执行。
- 默认 subagent 成员的运行时 subagent id、`member_id` 和 `display_name` 必须一致，采用 `<中文角色>-<具体任务名>`；真实可加载配置名写入 `skill_or_subagent`。
- 若用户指定某个 skill，`member_id`、`display_name` 和 `role` 使用 `<skill 名称>-<具体任务名>` 前缀，`skill_or_subagent` 记录该 skill。
- 若运行时或右边栏返回 `Reviewer C`、`QA B` 这类英文昵称，只能当作 `transport_handle`；用户可见表格、packet、state、events、progress、acceptance 和最终汇报必须使用中文 `member_id` / `display_name`。

## 执行边界

- 直接执行只跳过等待确认，不跳过规划、风险检查和 `Teams 规划表`。
- 启动 worker subagents 或编辑实现文件前，必须展示 `Teams 规划表`；直接执行时作为执行记录。
- 每个实现、文档或测试任务都必须有 Harness 契约、证据路径或 `not_applicable_reason`；证据不足不能完成。
- 测试和评审必须由独立成员、skill 或 subagent 执行；实现者自测不能替代独立校验。
- 对比和校验类任务必须采用 LLM + 脚本双重复核；脚本负责确定性检查，LLM reviewer 负责语义、风险和用户目标一致性。
- 所有计划任务看似完成、延期或阻塞后，必须启动新的只读 `goal_completion_auditor`；已确认范围内的遗漏按 Lead LOOP 自动续跑。

## 失败降级协议

| 情形 | 动作 | TaskList 状态 |
| --- | --- | --- |
| 证据不足 | 记录缺口，补跑或补写 Harness；不得声明完成 | `in_progress` |
| 独立检查者不可用 | 记录阻塞原因，禁止自检替代 | `blocked` |
| 需要用户决策或新范围 | 停下，写明待决问题和影响 | `blocked_needs_user` |
| 触发安全、凭证、审批或破坏性边界 | 停在授权门前，记录风险和所需授权 | `blocked_needs_user` |
| Budget/轮次超限 | 停止续跑，记录已完成范围和剩余缺口 | `blocked_needs_user`（Loop Decision: `stop_budget`） |
| 明确范围外或低优先 | 写延期原因、Owner 和触发条件 | `deferred` |

## 完成判定

完成判定必须同时满足：

- Done Criteria 已满足。
- TaskList 中每个认领任务为 `done`、`deferred` 或 `blocked`，且有原因。
- 每个交接物有独立校验证据、证据路径或阻塞/延期原因。
- 必要测试已运行，或明确写明跳过原因和风险。
- TaskList、SPEC、输出目录、版本子目录、`index.md` 和 `memory.md` 已更新或明确不适用。
- `goal_completion_auditor` 未发现已确认范围内的未完成工作；如果发现，按 `references/rules-loop.md` 续跑或阻塞。
