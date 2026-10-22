[English](README.en.md) | 中文

# Goal Teams

作者：肉山@TGO 杭州

<!-- goal-teams-release:start -->
当前版本：**V2.95** · [GitHub 发行页](https://github.com/vibe-coding-era/goal-teams/releases/tag/v2.95.0) · [更新记录](CHANGELOG.md)
<!-- goal-teams-release:end -->

Goal Teams 是面向 Codex 和 Claude Code 的团队协作交付 Skill。由一个 Goal Lead 把目标拆成可验证的任务，协调 `goal_*` 成员子代理完成需求、实现、测试、评审和发布。整个过程用 `gt` 命令行工具记账，汇报里的每个数字都来自真实记录。

- **按规模走流程**：
  - 问答直接回答。
  - 小改动走快速通道：先 Red，再 Green，最后给摘要。
  - 中大型任务才建账本、拆任务、派成员。
- **证据优先**：
  - TDD 的 Red 和 Green 用同一条命令、绑定同一组测试文件，并且源码内容确实发生了变化（只提交不算）。
  - 每个代码任务都要有在最终代码上通过的测试记录（人工结论不算），收尾时用 `gt rerun` 一次重跑。
  - 真实改动由 git 采集，再与全部任务的锁定范围对比。
  - 评审结论绑定文件摘要，文件改动后评审自动过期。
- **诚实状态**：not_run、blocked、failed 不会写成 passed；只有 `gt check` 通过，才算"达成"。
- **独立验证**：验证人不能是负责人。在 Claude Code 中，只读和执行类成员没有 Write/Edit，所有成员都不能再派子代理。
- **一次授权**：push、PR、发布、部署等外部写入在开始时一次确认；不可逆动作执行前先给预览。

## 快速开始

### Claude Code（插件）

```text
/plugin marketplace add vibe-coding-era/goal-teams
/plugin install goal-teams@goal-teams
```

Claude Code 2.1.275 及以上可以一步完成：`/plugin install goal-teams --marketplace vibe-coding-era/goal-teams`。

### Codex

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/src/goal-teams   # 不要 clone 到 skills 目录里
cd ~/src/goal-teams
python3 tools/install.py --host codex
```

安装器的行为：

- 把 skill 装到 `~/.agents/skills/goal-teams`（Codex 当前的用户 skill 目录），成员装到 `~/.codex/agents/goal_*.toml`。
- 旧位置 `~/.codex/skills/goal-teams`（V2 的安装位置）会被移入备份，避免 Codex 读到两份。
- 旧版本会先移入备份，支持 `--verify`、`--rollback` 和 `--uninstall`。
- 以后更新：`git pull && python3 tools/install.py --host codex`，然后新开会话。
- Windows 用 `py -3 tools\install.py --host codex`。
- 不用插件的 Claude Code 用户可以改用 `--host claude`；插件和安装器二选一，不要同时装。
- Claude Code 插件的 Stop 钩子需要 PATH 上有 `python3` 或 `python`。

从 V2.x 升级请看 [MIGRATION.md](MIGRATION.md)。

### 环境要求

- Python 3.9+（gt 只用标准库）。
- git：可选，没有时 `gt diff` 不可用。

## 怎么用

直接描述你的目标，Goal Lead 会先判定规模：

```text
Python 的 list 和 tuple 有什么区别？                       → discussion：直接回答
slugify("Hello World") 多了个末尾横杠，修一下               → small：Red → Green → 摘要
用 goal teams 给订单服务加优惠券功能（API + 校验 + 文档）    → medium：建目标、拆任务、派成员、每轮 gt report
只规划，不写代码：给会员系统出需求卡片                       → 只规划：在回复里给出需求卡片与计划
帮我把 v1.2 发布出去：打 tag、推送、建 GitHub Release        → 先一次性授权，再按发布规则执行并回读
```

medium/large 每一轮结束时，Goal Lead 运行 `gt report`，把输出原样发给你。输出包含六个字段：任务、成员、进度、结果、Benchmark、下一轮 LOOP（或下一个任务）。其中"结果"里有任务看板、Context 表和 P/D/C/A 四行。真实输出见 [examples/](examples/)。

## 工作方式

| 规模 | 判定 | Lead 读取的规则 | 状态 |
|---|---|---|---|
| discussion | 只问答、解释、给方案 | SKILL.md | 无 |
| small | 单一目标、低耦合、可逆 | + core、testing（共约 6K tokens） | 无 |
| medium | 跨数个文件或组件 | + planning、members、output（共约 12K tokens） | `.goal-teams/` |
| large | 跨模块、迁移、高影响 | 同 medium，另需完成审计 | `.goal-teams/` |
| 只规划 | 只规划、Plan Mode、需求卡片 | + planning 和对应模板 | 无 |

token 数按 `tools/check.py` 估算（与 Claude Code 显示的估算接近）。UI 任务加读 `rules/ui.md`，Agent 产品加读 `rules/agent-dev.md`，发布加读 `rules/release.md`。

以下情况会把 small 自动升级为 medium：
- 改动超过 3 个文件；
- 涉及公共 API 或迁移；
- 涉及认证、支付或个人数据；
- 有外部写入；
- 涉及 UI 视觉；
- 用户要求计划或团队协作。

### gt 命令一览

```text
gt init / goal / route / doctor                            建状态、目标、路由、环境预检
gt auth grant / check                                      一次性授权与执行前检查
gt task add / start / done / block / packet                任务、阻塞、给子代理的任务包
gt plan freeze / show                                      依赖图冻结、分层、关键路径
gt tdd red / green                                         Red/Green 证据（Green 重跑 Red 的命令）
gt run --kind affected|regression|e2e|security|build|...   检查证据（--artifact 记录产物）
gt rerun / retire                                          收尾重跑测试 / 撤销错误的检查失败
gt diff                                                    真实改动对照锁定范围
gt review                                                  评审结论（由验证人给出）
gt loop decide · gt reflect                                轮次决策 · 反思
gt status / report / check                                 看板、六字段汇报、完成检查
gt config / verify                                         项目约定、账本校验
```

所有状态保存在项目的 `.goal-teams/` 中：

- `ledger.jsonl`：只追加、带哈希链的账本；`ledger.head` 记录链头，账本被截断时能发现；
- `TaskList.md`、`benchmark.md`：由账本生成；
- `memory.md`：项目记忆；
- `loop-review.md`：反思记录。

### 成员

成员共 20 个，按职责分为三种模式：

| 模式 | 能做什么 | 成员 |
|---|---|---|
| write | 改锁定范围内的文件 | 需求、产品、Agent 产品、前后端、测试设计（单测/API/E2E）、文档 |
| runner | 只运行命令、记录证据 | 测试执行（单测/API/E2E）、QA、发布工程 |
| read-only | 只读，给出结论 | 评审、完成审计、安全、性能、重构、质量体系 |

完整清单和派发时机见 [rules/members.md](plugins/goal-teams/skills/goal-teams/rules/members.md)。成员的单一来源是 [members/](members/)：Codex 的 TOML 和 Claude Code 的子代理都由它生成。

## 评测

[plugins/goal-teams/evals/](plugins/goal-teams/evals/) 收录了 6 个用例，用 `claude plugin eval` 对比有无 Skill 时的结果：

- 讨论题
- small bugfix
- medium 功能
- API 缺陷狩猎
- 未授权发布
- 只规划

改动规则后，先用评测确认确实有收益。

## 目录

```text
.claude-plugin/marketplace.json   Claude Code marketplace
plugins/goal-teams/               运行时包（skill、规则、模板、gt、成员、钩子、评测）
members/                          成员单一来源
tools/                            生成、检查、安装、发布、示例
tests/  examples/  extras/okf-graph/
```

## 参与开发

见 [AGENTS.md](AGENTS.md)。提交前运行：

```bash
python3 tools/check.py && python3 -m unittest discover -s tests -t .
```

## 设计依据

| 原则 | 出处 |
|---|---|
| Skill 结构、渐进加载、简洁、"Solve, don't defer"、评测驱动 | [Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) |
| Codex Skill 与触发式 description | [OpenAI Codex Agent Skills](https://developers.openai.com/codex/skills) |
| Claude Code 插件、子代理工具限制、钩子、插件评测 | [Plugins](https://code.claude.com/docs/en/plugins)、[Subagents](https://code.claude.com/docs/en/sub-agents)、[Hooks](https://code.claude.com/docs/en/hooks)、[Plugin evals](https://code.claude.com/docs/en/plugin-evals) |
| TDD | [Martin Fowler: Test-Driven Development](https://martinfowler.com/bliki/TestDrivenDevelopment.html) |
| E2E 与截图断言 | [Playwright](https://playwright.dev/docs/test-snapshots) |

## License

MIT，见 [LICENSE](LICENSE)。
