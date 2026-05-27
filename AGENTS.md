# Goal Teams 仓库维护指南

本仓库是 Codex Skill 包，不是业务应用。修改时优先保持规则一致、安装可用、示例可复盘。

## 维护原则

- `goal-teams.md` 记录长期用户指定要求，是规则变更的上游依据。
- `SKILL.md` 是 Codex 发现和执行 skill 的主入口。
- `references/goal-teams-runtime.md` 承载详细协议、模板和 CLI 示例。
- `subagents/goal-*.toml` 是实际可注册的成员 agent 配置。
- `README.md` 和 `README.en.md` 只做介绍、安装、示例和发布说明，避免承载唯一规则。

## 同步要求

更新运行规则时，通常需要同步检查：

- `goal-teams.md`
- `SKILL.md`
- `references/goal-teams-runtime.md`
- `references/default-AGENTS.md`
- `subagents/goal-*.toml`
- `README.md`
- `README.en.md`
- `examples/mini-goal-run/`

如果只改拼写、链接或发布说明，可以只改相关文档，但要运行校验脚本确认没有破坏安装结构。

## 校验

提交前运行：

```bash
./scripts/check.sh
```

该脚本会检查必需文件、Skill frontmatter、subagent TOML、README 发布清单、示例文档和关键规则关键词。

## 风格

- 默认中文说明；英文 README 与中文 README 保持信息等价。
- 命令、路径、配置键、API 名称保持原文。
- 不新增未验证的运行时能力描述。
- 不为小改动引入复杂生成流程；优先使用标准库脚本。
- 不擅自选择开源 License；发布前由仓库 owner 决定。
