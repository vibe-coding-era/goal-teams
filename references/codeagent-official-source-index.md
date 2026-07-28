---
type: Official Source Index
title: Goal Teams V2.47 CodeAgent 官方规则来源
description: Codex、Claude Code、Cursor、Kimi Code、GLM、Qwen Code、Qoder 与 TRAE 的官方 Skill/Rules 资料索引和适配边界。
tags: [goal-teams, v2.47, codeagent, official-sources]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# CodeAgent 官方规则来源

检索日期：`2026-07-28`。这里只登记厂商官方文档、官方仓库、官方 changelog
和标明官方身份的官方社区 FAQ。官方产品能力只能证明宿主合同，不等于 Goal Teams
adapter 已通过运行时验证。

| ID | Runtime | 官方来源 | 合同用途 |
| --- | --- | --- | --- |
| OAI-01 | Codex | [Codex manual](https://developers.openai.com/codex/codex-manual.md) | 当前行为总览 |
| OAI-02 | Codex | [Build skills](https://learn.chatgpt.com/docs/build-skills) | `SKILL.md`、发现、渐进加载与调用 |
| OAI-03 | Codex | [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | 指令层级、作用域与覆盖 |
| OAI-04 | Codex | [Rules](https://learn.chatgpt.com/docs/agent-configuration/rules) | 命令策略与 sandbox 边界 |
| ANT-01 | Claude Code | [Extend Claude Code](https://code.claude.com/docs/en/features-overview) | Rules、Skills、MCP、subagent、hook |
| ANT-02 | Claude Code | [Memory](https://code.claude.com/docs/en/memory) | `CLAUDE.md`、Rules、`AGENTS.md` shim |
| ANT-03 | Claude Code | [Skills](https://code.claude.com/docs/en/skills) | Skill 路径、字段、加载与权限 |
| ANT-04 | Claude Code | [SDK Skills](https://code.claude.com/docs/en/agent-sdk/skills) | CLI/SDK 权限差异 |
| CUR-01 | Cursor | [Agent Skills](https://cursor.com/docs/skills) | Skill roots、frontmatter、调用 |
| CUR-02 | Cursor | [Rules](https://cursor.com/docs/rules) | Project/Team/User Rules 与 `AGENTS.md` |
| CUR-03 | Cursor | [CLI Agent](https://cursor.com/docs/cli/using) | CLI 规则发现与审批 |
| CUR-04 | Cursor | [CLI permissions](https://cursor.com/docs/cli/reference/permissions) | shell、文件、网络、MCP 权限 |
| KIMI-01 | Kimi Code | [Agent Skills](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/skills.html) | Skill schema、路径、优先级与调用 |
| KIMI-02 | Kimi Code | [Customization](https://www.kimi.com/help/kimi-code/cli-customization) | `AGENTS.md` 与相关目录加载 |
| KIMI-03 | Kimi Code | [Agents](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html) | 工具限制与 subagent |
| KIMI-04 | Kimi Code | [kimi command](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command.html) | `--skills-dir`、plan、yolo、ACP |
| KIMI-05 | Kimi Code | [Data locations](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/data-locations.html) | `$KIMI_CODE_HOME` |
| GLM-01 | GLM | [Coding Agent 工作原理](https://docs.bigmodel.cn/cn/coding-plan/learning-resources/how-coding-agent-works) | 模型、宿主、工具边界 |
| GLM-02 | GLM | [Agentic 扩展组件](https://docs.bigmodel.cn/cn/coding-plan/learning-resources/agentic-extension) | 宿主生态能力 |
| GLM-03 | GLM | [Claude Code 接入](https://docs.bigmodel.cn/cn/guide/develop/claude) | GLM 作为模型服务接入宿主 |
| GLM-04 | CodeGeeX | [CodeGeeX repository](https://github.com/zai-org/CodeGeeX) | 官方产品能力；无原生 Skill 合同 |
| QWEN-01 | Qwen Code | [Agent Skills](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/) | Skill schema、paths、发现 |
| QWEN-02 | Qwen Code | [Memory](https://qwenlm.github.io/qwen-code-docs/en/users/features/memory/) | `QWEN.md` 与 `AGENTS.md` |
| QWEN-03 | Qwen Code | [Headless mode](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/) | system prompt、safe mode、approval |
| QWEN-04 | Qwen Code | [Extensions](https://qwenlm.github.io/qwen-code-docs/en/users/extension/introduction/) | extension Skills 与上下文 |
| QODER-01 | Qoder | [Skills](https://docs.qoder.com/en/cli/Skills) | Skill schema、渐进加载、优先级 |
| QODER-02 | Qoder | [Rules](https://docs.qoder.com/user-guide/rules) | `.qoder/rules` 与冲突优先级 |
| QODER-03 | Qoder | [记忆](https://docs.qoder.cn/cli/memory) | CN 路径、子目录触发、`paths` |
| QODER-04 | Qoder | [使用 CLI](https://docs.qoder.com/zh/cli/using-cli) | 权限、`AGENTS.md`、subagent |
| TRAE-01 | TRAE | [Changelog](https://www.trae.ai/changelog) | Skills、`.agents/skills`、嵌套 Rules |
| TRAE-02 | TRAE | [官方 FAQ：Rules](https://forum.trae.cn/t/topic/52) | Rules 优先级与 `.trae/rules` |
| TRAE-03 | TRAE | [官方 FAQ：SOLO](https://forum.trae.cn/t/topic/53) | Agent 与执行面边界 |

## 适配判定

- `codex`、`claude-code`、`cursor`、`kimi-code`、`qwen-code`、`qoder`：
  官方合同已映射，但 Goal Teams 完整 adapter 仍需对应 surface 的 P0 runtime smoke。
- `glm`：`model_provider`，必须另有实际 `host_runtime_id`；不得当作独立 Skill runtime。
- `trae`：已确认 Skill/Rules 能力，但公开 schema 不完整；保持
  `capability_probe_required`。
- 任何 URL、版本或官方合同漂移时，先更新本索引和
  `references/codeagent-runtime-manifest.json`，再更新单个 overlay；公共规则不得复制供应商方言。
