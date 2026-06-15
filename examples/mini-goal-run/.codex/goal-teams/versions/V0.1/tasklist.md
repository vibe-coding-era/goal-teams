# Goal Teams Tasklist

Goal: 规划登录页空状态提示 V0.1
Status: done

## Member Ownership

| Task ID | Member | Skill/Subagent | Claimed By | Workflow | 前置任务 | Status | Locked Scope | Deliverable | Done Criteria | Harness Contract | Verification | Docs/SPEC Update |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 需求分析-登录页空状态需求澄清 | goal_requirements_analyst | 需求分析-登录页空状态需求澄清 | 串行 | - | done | `spec/` | 需求规格卡 | 目标/流程/边界清楚 | 结构清单、边界/非目标检查，证据：`progress.md` | 评审-登录页空状态文档校验 | requirement-spec-card |
| GT-002 | 产品-登录页空状态 PRD | goal_product | 产品-登录页空状态 PRD | 串行 | GT-001 | done | `spec/` | PRD | 基于规格卡 | PRD 溯源和验收标准清单，证据：`progress.md` | 评审-登录页空状态文档校验 | PRD |
| GT-003 | 前端-登录页空状态 HTML 原型 | goal_frontend | 前端-登录页空状态 HTML 原型 | 串行 | GT-002 | done | `spec/HTML-prototype.html` | HTML 原型 | 展示空状态 | HTML 静态结构和文案检查；E2E not_applicable_reason：sample_only 静态文档示例，无真实运行应用；复刻像素级对比 not_applicable_reason：无参考图 | 评审-登录页空状态文档校验 | HTML Prototype |
| GT-004 | 测试-登录页空状态验收测试 | goal_qa | 测试-登录页空状态验收测试 | 串行 | GT-003 | done | `spec/test-plan.md` | 测试计划 | 覆盖验收点 | 测试计划边界和断言有效性检查；真实界面任务必须补 E2E，复刻任务必须补截图像素级对比 | 评审-登录页空状态测试有效性 | test-plan |
| GT-005 | 文档-登录页空状态验收文档 | goal_docs | 文档-登录页空状态验收文档 | 串行 | GT-004 | done | `spec/acceptance.md` | 验收清单 | 证据完整 | 验收证据完整性检查，证据：`spec/acceptance.md` | 评审-登录页空状态文档校验 | acceptance |
| GT-006 | 文档-Harness 示例复盘 | goal_docs | 文档-Harness 示例复盘 | 串行 | GT-005 | done | `harness/` | Harness 复盘资料和静态样例 | setup/run/checks/report、automation protocol、evidence ledger、pipeline gates 可追溯到验收证据 | setup/run/checks/report 和静态样例追溯检查，证据：`harness/report.md` | 评审-登录页空状态文档校验 | harness + progress + acceptance |
| GT-007 | 评审-登录页空状态文档校验 | goal_reviewer | 评审-登录页空状态文档校验 | 串行 | GT-001, GT-002, GT-003, GT-004, GT-005, GT-006 | done | read-only | 校验记录 | 非作者校验完成 | 人工只读评审清单，证据：`progress.md` | 不适用 | progress |
| GT-008 | 收尾-登录页空状态未完成工作检查 | goal_completion_auditor | 收尾-登录页空状态未完成工作检查 | 串行 | GT-007 | done | read-only | 收尾审计记录 | 无未完成工作或自动续跑任务已列出 | 收尾审计清单，证据：`progress.md`；not_applicable_reason：无外部命令 | 不适用 | progress + acceptance |

## Independent Validation

| Artifact | Author | Validator | Method | Evidence |
| --- | --- | --- | --- | --- |
| `spec/requirement-spec-card.md` | 需求分析-登录页空状态需求澄清 | 评审-登录页空状态文档校验 | 结构和边界检查 | `progress.md` |
| `spec/PRD.md` | 产品-登录页空状态 PRD | 评审-登录页空状态文档校验 | PRD 来源追踪 | `progress.md` |
| `spec/HTML-prototype.html` | 前端-登录页空状态 HTML 原型 | 评审-登录页空状态文档校验 | 原型静态检查 | `progress.md` |
| `spec/test-plan.md` | 测试-登录页空状态验收测试 | 评审-登录页空状态测试有效性 | 断言和边界检查 | `progress.md` |
| `harness/` | 文档-Harness 示例复盘 | 评审-登录页空状态文档校验 | setup/run/checks/report 与静态样例追溯检查 | `progress.md` + `spec/acceptance.md` |
| 完成状态 | 收尾-登录页空状态未完成工作检查 | `goal_completion_auditor` | 未完成工作审计 | `progress.md` |
