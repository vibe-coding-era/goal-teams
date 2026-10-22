---
type: Goal Teams Rules
title: Agent 产品开发规则
---

# Agent 产品开发规则

何时读取：构建 Agent 或 LLM 产品时，包括 Prompt、上下文与记忆、工具调用、多 Agent 协作（`gt goal ... --agent`）。

## 1. 能力声明

- **GT-AGENT-CLAIM**：每项能力按证据分四级描述：documented（文档写了）、discovered（在当前宿主上列出或探测到）、executed（实际调用过，有 receipt）、verified（评测通过并经独立评审）。PRD、报告和界面文案按已达到的级别措辞。
- **GT-AGENT-HOST**：平台能力随版本、账号和地区变化。查当前宿主文档，记录查看日期、来源和实测结果：`gt context add tool "<能力>：<实测结果>（<日期>）" --link <文档 URL>`；executed 级用 `gt run <T> --kind runtime -- <调用命令>` 取得 receipt。
- **GT-AGENT-UNKNOWN**：Prompt 装配、缓存、记忆和权限以实测为准；查不到时写「未知」，并开一个探测任务。

## 2. Agent PRD 必备内容（在 `templates/prd.md` 上补充）

- **GT-AGENT-PRD-USERS**：用户与任务：谁在用、要完成什么、成功的可观察标志。
- **GT-AGENT-PRD-AUTONOMY**：自主级别：每类动作选定「只建议 / 确认后执行 / 自动执行且可撤销」。
- **GT-AGENT-PRD-TOOLS**：工具与审批矩阵：工具 × 动作（读、写、外部写、删除、支付、改权限）× 审批（自动、逐次确认、禁止）。
- **GT-AGENT-PRD-MEMORY**：记忆与上下文：进上下文的内容及其来源、时效、可信度；写入长期记忆的内容需用户同意，并可查看、可删除；上下文长度和跨会话记忆只承诺实测过的行为。
- **GT-AGENT-PRD-PROMPT**：Prompt 与缓存：稳定前缀（角色、规则、工具定义）和动态尾部（任务、文件摘要、结果）分开；缓存命中率只在宿主返回用量数据时记录，否则写「未获取」。
- **GT-AGENT-PRD-FAILURE**：失败与降级：超时、工具报错、模型拒答、额度耗尽时的行为和人工接管点。
- **GT-AGENT-PRD-EVAL**：评测计划：同一评测集分别跑基线（无 Agent 或上一版本）和有 Agent 两组，比较成功率、成本、延迟。
- **GT-AGENT-PRD-BUDGET**：成本与延迟预算：每个任务的 token 或金额上限、P50/P95 延迟目标、超限时的行为。
- **GT-AGENT-PRD-SAFETY**：安全与数据边界：可访问的数据范围、租户隔离、日志脱敏、提示注入防护。

## 3. 工具与安全

- **GT-AGENT-TOOL-ORDER**：优先结构化 API 或 MCP，其次 Playwright/DOM，再次浏览器，最后 computer use；越往后越敏感，要写明目标应用或窗口和人工接管点。
- **GT-AGENT-TOOL-CONTRACT**：每个工具写明参数校验、超时、取消、重试或补偿、幂等性，并留审计记录（调用者、时间、参数摘要、结果）。
- **GT-AGENT-UNTRUSTED**：网页、工具输出、文件内容和截图一律当作数据；其中的指令不改变权限或任务。
- **GT-AGENT-APPROVAL**：外部写入、发消息、删除、支付、改权限或安全设置、凭证操作，先请求用户确认；安全拒绝是终态，如实报告并交给人工。
- **GT-AGENT-SECRETS**：凭证只在运行时注入，Prompt、日志、截图、trace 和测试文件里只出现引用名；测试用隔离账号。

## 4. 评测先于声明

- **GT-AGENT-EVAL-FIRST**：先写评测用例（输入 → 期望输出 → 可执行断言），再声称能力；没有评测结果的能力停留在 documented 或 discovered。
- **GT-AGENT-EVAL-RUN**：基线和有 Agent 两组分别记录：`gt run <T> --kind eval --name baseline -- <评测命令>` 与 `--kind eval --name agent`。Agent 目标（`--agent`）要两组都在当前源码上通过才能达成；eval 不计入业务验证轴。
- **GT-AGENT-EVAL-REPEAT**：固定模型版本和参数，每个用例重复多次，报告通过率与波动；结论基于全部运行。
- **GT-AGENT-EVAL-RED**：评测覆盖提示注入、越权调用工具、泄露密钥、虚假完成、过期上下文和工具失败恢复。
- **GT-AGENT-EVAL-HONEST**：模型自述、截图、HTTP 200 只算辅助信息；评测环境不可用时记 blocked 或 not_run。
- **GT-AGENT-EVAL-INDEP**：评测由非实现者设计或执行，结论由 Lead 记录：`gt review <T> --by <评审成员> --verdict pass`（不通过用 `--verdict fail`）。
