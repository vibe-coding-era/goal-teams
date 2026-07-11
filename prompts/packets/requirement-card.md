---
type: Requirement Card Template
title: 需求卡片 OKF 模板
description: Plan 模式最小需求卡片模板，后续流向 Requirement Specification Card、PRD、页面规格卡、tasklist 和 Harness。
tags: [goal-teams, okf, requirement-card]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
source_ssot: references/google-okf-bilingual-spec.md
---

# 需求卡片 OKF 模板

```markdown
---
type: Requirement Card
title: 需求卡片：<版本或目标名>
description: <一句话说明本轮真正要完成什么>
tags: [goal-teams, requirement, <project_version>]
timestamp: <ISO 8601 datetime>
okf_version: "0.1"
goal_teams_version: <Vx.x>
project_version: <项目版本号>
output_dir: <GoalTeamsWork-project_version 或用户指定目录>
owner_agent_type: Goal Lead
owner_member_id: <稳定成员 ID>
owner_agent_run_id: <本次运行 ID>
validator_agent_type: goal_reviewer 或 user
validator_member_id: <独立检查成员 ID 或 user>
validator_agent_run_id: <独立检查运行 ID 或 user-approval-ID>
source_ssot: prompts/packets/handoff-artifacts.md
---

# 需求卡片：<版本或目标名>

## 核心目标

- <一句话说明本轮真正要完成什么>

## 关键功能

- <必须覆盖的功能或交付 1>
- <必须覆盖的功能或交付 2>

## 用户故事

| ID | 用户故事 | 价值 |
| --- | --- | --- |
| US-001 | 作为 <用户角色>，我想要 <能力/动作>，以便 <业务价值> | <价值说明> |

## 功能验收标准

| ID | 对应功能/故事 | 验收标准 |
| --- | --- | --- |
| AC-001 | <功能或 US-001> | Given <前置条件>，When <用户行为或系统事件>，Then <可观察结果> |

## 边界

- 范围内：<本轮明确处理的范围>
- 范围外：<本轮不处理的内容>
- 禁止/只读：<不能修改或只能读取的范围>

## 约束

| 约束 | 影响 | 处理方式 |
| --- | --- | --- |
| <时间/版本/技术栈/权限/安全/成本/兼容性/上下文约束> | <影响> | <处理方式> |

## 风险

| 风险 | 影响 | 缓解方式 | 是否需确认 |
| --- | --- | --- | --- |
| <需求不清/依赖缺失/验证困难/并发冲突/生产风险> | <影响> | <缓解方式> | 是/否 |

## 待确认问题

1. <需要用户、业务方或外部系统确认的问题>

## 后续流向

- Requirement Specification Card：<创建/更新/不适用，原因>
- PRD：<如何承接用户故事和功能验收标准>
- Page Specification Card：<UI 页面、复刻、还原、截图对齐或前端交互页面必须创建/更新 page-spec-card.md；非 UI 写 not_applicable_reason>
- HTML Prototype MOCK：<页面原型任务必须先确认组件库；组件库已提供时写入 memory.md、page-spec-card.md 和 HTML OKF 元数据>
- tasklist：<如何按故事/验收标准拆成任务>
- Harness：<如何验证功能验收标准>
- Visual Contract / Evidence：<页面规格卡如何承接组件级视觉契约、交互状态矩阵、E2E Harness、整页和局部像素对比、证据目录>
```
