---
type: Goal Teams Flow Clarification Protocol
title: Goal Teams V2.43 流程澄清协议
description: 在 Plan、团队或 subagent 规划之前，让用户确认小、中或大迭代流程及节点。
tags: [goal-teams, v2.41, flow-clarification, routing]
timestamp: 2026-07-18T00:00:00+08:00
okf_version: "0.1"
---

# V2.43 流程澄清协议

启动时先依据用户目标、已提供材料和可验证工作区事实给出 `Proposal`；不得把 LLM 推断伪装成用户已经确认的规模或流程。确认前不得创建正式 Plan、Teams 表或派发 subagent。

## 用户可见格式

```markdown
LLM 的判断是：你应该使用**小型需求/BugFix**流程来完成。

判断原因：这是范围明确的单点改动；未识别到跨系统、生产发布或高风险边界。

1. 小型需求/BugFix（内部规模：small；原小迭代流程）如下：
   -> 生成 PRD 和页面原型（如有 UI）
   -> 生成测试用例及造数
   -> 生成 TDD 及代码
   -> 完成测试用例和独立复核

2. 中型项目（内部规模：medium；原中迭代流程）如下：
   -> 生成需求卡、PRD 和影响分析
   -> 生成 Architecture Design，以及开发/生产环境配置规划
   -> 生成页面原型（如有 UI）、测试用例及造数
   -> 生成 TDD、代码和 API/模块集成
   -> 完成单元、集成或 E2E 测试，并进行独立 Review

3. 大型系统（内部规模：large；原大迭代流程）如下：
   -> 流程澄清、需求卡、需求规格卡和 PRD
   -> 生成页面规格卡/原型（如有 UI）与 Architecture Design
   -> 在每份 Architecture Design 中规划开发和线上正式环境配置
   -> 独立生成测试设计、造数、TDD/测试脚本和 Harness
   -> 分工实现、执行单元/API/E2E 测试，记录 Evidence
   -> 独立 Review、LOOP 补缺、发布就绪检查和完成审计

请选择下一步：
1. 采用小型需求/BugFix 流程
2. 改用中型项目流程
3. 改用大型系统流程
4. 自定义要保留或删除的流程节点
5. 直接改：不创建正式 Plan 或 Teams，只修改指定内容并完成适用的轻量验证
```

## 流程图

```mermaid
flowchart TD
    A[用户目标] --> B[LLM 流程初判\nProposal: 小 / 中 / 大]
    B --> C{用户确认流程}
    C -->|1 小型需求/BugFix| S[需求或 BugFix -> 测试与造数 -> 实现 -> 独立复核]
    C -->|2 中型项目| M[需求与影响分析 -> 架构与双环境规划 -> 集成与测试 -> Review]
    C -->|3 大型系统| L[完整规格 -> 架构与环境 -> 独立测试与实现 -> Evidence/LOOP/审计]
    C -->|4 自定义流程| D[补齐并确认流程节点]
    C -->|5 直接改| X[最小修改\n不创建 Plan 或 Teams]
    S --> P[确认后才进入 Plan]
    M --> P
    L --> P
```

不支持 Mermaid 的宿主必须输出同构 ASCII 图，不能省略流程图。

## 选择原因

| 流程 | 适用情况 | 原因 |
| --- | --- | --- |
| 小型需求/BugFix | 单一、低风险、无跨模块/API/生产发布影响 | 以最小测试造数和独立复核约束范围；不为局部变更制造完整架构或发行仪式。通常 1–2 名项目成员、0–1 个 Subagent。 |
| 中型项目 | 多模块、API/数据边界、原创 UI、风险中等或有环境配置差异 | 增加影响分析、条件架构和双环境规划，避免配置或集成问题在编码后才暴露。通常 3–5 名项目成员、2–4 个 Subagent。 |
| 大型系统 | 多系统、发布、生产变更、安全敏感、支付/认证、复杂 UI 或高风险 | 完整的独立测试、Evidence、Review、LOOP 与审计链降低协作与上线风险。通常 6–10 名项目成员、5–8 个 Subagent。 |

数字 `1`、`2`、`3` 分别规范化为 `small`、`medium`、`large`，确认后才能生成结构化 `project_size` 并进入原有 Plan。选项 `4` 只进入 `awaiting_customization`，必须补齐节点并再次确认。选项 `5` 规范化为 `flow_selection=skipped`，只完成当前最小修改；安全、授权和上层 fail-closed 规则仍然有效。
