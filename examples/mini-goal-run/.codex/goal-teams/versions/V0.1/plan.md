# Goal Teams Plan

## 用户目标

为演示项目规划“登录页空状态提示 V0.1”，只生成文档和 HTML 原型，不修改业务代码。

## 环境检查

| 项目 | 结果 | 建议 |
| --- | --- | --- |
| AGENTS/agent 指南 | missing | 使用 `references/default-AGENTS.md` 作为默认指南 |
| CLAUDE 指南 | missing | 暂无需要 |
| 版本目录 | V0.1 | 写入 `.codex/goal-teams/versions/V0.1/` |
| 文档索引 | ready | 已创建总索引和版本索引 |

## 当前假设

| 假设 | 影响 | 验证方式 | 是否需确认 |
| --- | --- | --- | --- |
| 只规划不实现 | 不触碰业务代码 | tasklist 锁定范围为空实现范围 | 是 |
| 空状态用于登录页 | 决定文案和原型 | 需求规格卡 | 是 |

## Teams 规划表

| 成员 | Skill/Subagent | 目标切片 | 认领任务 | 锁定范围 | 交付物 | 完成标准 | 文档/tasklist 更新 | 测试 Owner | 校验者 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 需求分析-登录页空状态需求澄清 | `goal_requirements_analyst` | 梳理登录页空状态需求 | GT-001 | `spec/` | 需求规格卡 | 目标、流程、边界清楚 | requirement-spec-card | 评审-登录页空状态文档校验 | 评审-登录页空状态文档校验 |
| 产品-登录页空状态 PRD | `goal_product` | 生成登录页空状态 PRD | GT-002 | `spec/` | PRD | 来源于需求规格卡 | PRD | 评审-登录页空状态文档校验 | 评审-登录页空状态文档校验 |
| 前端-登录页空状态 HTML 原型 | `goal_frontend` | 登录页空状态原型 | GT-003 | `spec/HTML-prototype.html` | HTML 原型 | 能表达空状态 | HTML Prototype | 测试-登录页空状态验收测试 | 评审-登录页空状态文档校验 |
| 测试-登录页空状态验收测试 | `goal_qa` | 登录页空状态测试计划 | GT-004 | `spec/test-plan.md` | 测试计划 | 覆盖文案和流程 | test-plan | 测试-登录页空状态验收测试 | 评审-登录页空状态测试有效性 |
| 文档-登录页空状态验收文档 | `goal_docs` | 登录页空状态收口文档 | GT-005 | `spec/acceptance.md` | 验收清单 | 证据完整 | acceptance | 评审-登录页空状态文档校验 | 评审-登录页空状态文档校验 |
| 评审-登录页空状态文档校验 | `goal_reviewer` | 独立校验登录页空状态文档 | GT-006 | 只读 | 校验记录 | 非作者校验通过 | progress | 不适用 | 不适用 |

## 风险与审批

| Item | Risk | Owner | Approval Needed | Stop Condition |
| --- | --- | --- | --- | --- |
| 业务代码 | 示例误改实现文件 | Goal Lead | 是 | 出现实现文件改动 |
