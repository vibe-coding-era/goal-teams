# Goal Teams Plan

## 用户目标

为演示项目规划“登录页空状态提示 V0.1”，只生成文档、HTML 原型和最小 Harness 复盘资料，不修改业务代码。

## 启动汇报

我是 Goal Teams Lead V2.33。

- 检查示例项目执行规则和版本目录。
- 创建索引、tasklist、SPEC、原型、测试计划和验收清单。
- 补充最小 Harness 资料，记录 setup、run、checks、report 与验收证据。
- 列出 Teams 规划表并记录独立校验安排。

## 历史资料输入

本示例的目标、边界和参考输入已经完整；缺少额外历史资料不会改变执行，因此不再询问。

| 项目 | 记录 |
| --- | --- |
| 历史资料 | 示例未提供；不影响当前执行 |

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

## 需求卡片

| 项目 | 记录 |
| --- | --- |
| 文档路径 | `spec/requirement-card.md` |
| 核心目标 | 只生成登录页空状态提示的文档、HTML 原型和最小 Harness 复盘资料 |
| 关键功能 | 文案与触发场景、SPEC、原型、测试计划、验收、Harness 静态样例 |
| 用户故事 | US-001 未登录用户看到空状态提示；US-002 新用户看到创建账号或联系支持入口 |
| 功能验收标准 | AC-001 空状态标题和说明；AC-002 登录主按钮；AC-003 次操作入口；AC-004 不含真实认证调用 |
| 边界 | 不修改业务代码，不实现真实登录接口，不做生产部署 |
| 约束 | 示例项目无真实运行环境，Harness 仅为 `sample_only` |
| 风险 | 空状态业务语境不足，真实项目仍需 E2E 和截图证据 |

## Teams 规划表

| 成员 / Skill/Subagent | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：需求分析-登录页空状态需求澄清<br>Skill/Subagent：`goal_requirements_analyst` | 目标切片：梳理登录页空状态需求<br>认领任务：GT-001<br>Workflow：串行<br>前置任务：-<br>锁定范围：`spec/` | 交付物：需求规格卡<br>完成标准：目标、流程、边界清楚<br>文档/tasklist：requirement-spec-card | 测试 Owner：评审-登录页空状态文档校验<br>校验者：评审-登录页空状态文档校验 |
| 成员：产品-登录页空状态 PRD<br>Skill/Subagent：`goal_product` | 目标切片：生成登录页空状态 PRD<br>认领任务：GT-002<br>Workflow：串行<br>前置任务：GT-001<br>锁定范围：`spec/` | 交付物：PRD<br>完成标准：来源于需求规格卡<br>文档/tasklist：PRD | 测试 Owner：评审-登录页空状态文档校验<br>校验者：评审-登录页空状态文档校验 |
| 成员：前端-登录页空状态 HTML 原型<br>Skill/Subagent：`goal_frontend` | 目标切片：登录页空状态原型<br>认领任务：GT-003<br>Workflow：串行<br>前置任务：GT-002<br>锁定范围：`spec/HTML-prototype.html` | 交付物：HTML 原型<br>完成标准：能表达空状态<br>文档/tasklist：HTML Prototype | 测试 Owner：测试-登录页空状态验收测试<br>校验者：评审-登录页空状态文档校验 |
| 成员：测试-登录页空状态验收测试<br>Skill/Subagent：`goal_qa` | 目标切片：登录页空状态测试计划<br>认领任务：GT-004<br>Workflow：串行<br>前置任务：GT-003<br>锁定范围：`spec/test-plan.md` | 交付物：测试计划<br>完成标准：覆盖文案和流程<br>文档/tasklist：test-plan | 测试 Owner：测试-登录页空状态验收测试<br>校验者：评审-登录页空状态测试有效性 |
| 成员：文档-登录页空状态验收文档<br>Skill/Subagent：`goal_docs` | 目标切片：登录页空状态收口文档<br>认领任务：GT-005<br>Workflow：串行<br>前置任务：GT-004<br>锁定范围：`spec/acceptance.md` | 交付物：验收清单<br>完成标准：证据完整<br>文档/tasklist：acceptance | 测试 Owner：评审-登录页空状态文档校验<br>校验者：评审-登录页空状态文档校验 |
| 成员：文档-Harness 示例复盘<br>Skill/Subagent：`goal_docs` | 目标切片：最小 Harness 复盘资料<br>认领任务：GT-006<br>Workflow：串行<br>前置任务：GT-005<br>锁定范围：`harness/` | 交付物：setup/run/checks/report 文档<br>完成标准：可从 Harness 文档追到验收证据<br>文档/tasklist：harness + progress + acceptance | 测试 Owner：测试-登录页空状态验收测试<br>校验者：评审-登录页空状态文档校验 |
| 成员：评审-登录页空状态文档校验<br>Skill/Subagent：`goal_reviewer` | 目标切片：独立校验登录页空状态文档和 Harness 证据<br>认领任务：GT-007<br>Workflow：串行<br>前置任务：GT-001, GT-002, GT-003, GT-004, GT-005, GT-006<br>锁定范围：只读 | 交付物：校验记录<br>完成标准：非作者校验通过<br>文档/tasklist：progress | 测试 Owner：不适用<br>校验者：不适用 |
| 成员：收尾-登录页空状态未完成工作检查<br>Skill/Subagent：`goal_completion_auditor` | 目标切片：检查未完成工作和缺失证据<br>认领任务：GT-008<br>Workflow：串行<br>前置任务：GT-007<br>锁定范围：只读 | 交付物：收尾审计记录<br>完成标准：确认无未完成工作，或输出自动续跑任务<br>文档/tasklist：progress + acceptance | 测试 Owner：不适用<br>校验者：不适用 |

## 风险与审批

| 项目 | 风险 | Owner | 是否需审批 | 停止条件 |
| --- | --- | --- | --- | --- |
| 业务代码 | 示例误改实现文件 | Goal Lead | 是 | 出现实现文件改动 |
