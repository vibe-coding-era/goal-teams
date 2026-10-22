# 升级到 V2.95

V2.95 以提供的 V2.9 源码包为主体，只保留 V2.68 的任务图与细粒度预算约束，并修复完成判定、发行身份、安装预览和检查边界问题。源码版本不等于已经发布；远端发布与真实宿主验收需分别验证。V2.7/V2.9 的提交历史和发布状态不能由源码 ZIP 单独证明。V2.68 及更早的内容保留在 git tag 里（如 `v2.68`），需要时 `git checkout v2.68` 查看。

## 1. 重新安装

### Codex

V2.68 的 README 让你把仓库 clone 到 `~/.codex/skills/goal-teams`，V2.9 不再这样安装。V2.9 的安装器把 skill 装到 `~/.agents/skills/goal-teams`（Codex 当前读取的用户 skill 目录），成员装到 `~/.codex/agents/goal_*.toml`（设置了 `CODEX_HOME` 时为 `$CODEX_HOME/agents`），备份放在 `~/.codex/goal-teams-backups/`。用 `--skills-dir DIR` 可以改装到 `DIR/goal-teams`。

```bash
git clone https://github.com/vibe-coding-era/goal-teams.git ~/src/goal-teams   # 任意目录，但不要放在 skills 目录里
cd ~/src/goal-teams
python3 tools/install.py --host codex --dry-run   # 先看计划
python3 tools/install.py --host codex
```

Windows 上把 `python3` 换成 `py -3`，路径用 `tools\install.py`。

安装器会自动处理旧安装：

- **旧位置**：`~/.codex/skills/goal-teams` 里的内容（V2.68 的 clone 或安装包，或早期的新安装器装的版本）会整个**移入同一份备份**（`~/.codex/goal-teams-backups/<UTC 时间>-codex/`），不删除，避免 Codex 加载两份；`--rollback` 会把它放回原处。V2.68 和 clone 的备份不会被自动清理，确认不需要后自己删除；其他备份只保留最近 3 份。
- **旧成员文件**：V2.68 的 `~/.codex/agents/goal-*.toml`（连字符命名）也移入同一个备份。V2.9 成员文件是 `goal_*.toml`，`name` 与 V2.68 相同，两套同时存在会让 Codex 混淆。
- **V2.68 安装器状态**：`~/.codex/state/goal-teams/` 不会动；确认不需要后可以自己删除。
- **V2.68 的 `--update-team-fallback`**：如果用过它，它改过 `~/.codex/agents/team-{implementer,qa,researcher,reviewer}.toml` 里的 `nickname_candidates`。V2.9 不修改也不恢复这些文件，需要的话自己改回。
- **clone 还在 `~/.codex/skills/goal-teams` 里**：从那里运行安装器会被拒绝（退出码 2，不做任何改动）。先把它移走，例如 `mv ~/.codex/skills/goal-teams ~/src/goal-teams && python3 ~/src/goal-teams/tools/install.py`。

安装后检查、回退与更新：

```bash
python3 tools/install.py --verify --host codex        # 校验已安装文件
python3 tools/install.py --list-backups --host codex  # 查看备份
python3 tools/install.py --rollback --host codex      # 回到最近一份备份
git pull && python3 tools/install.py --host codex     # 以后更新
```

安装或更新后，新开一个 Codex 会话才会加载新版本。

### Claude Code

```text
/plugin marketplace add vibe-coding-era/goal-teams
/plugin install goal-teams@goal-teams
```

不用插件也可以：`python3 tools/install.py --host claude`，会把 skill 装到 `~/.claude/skills/goal-teams`，成员装到 `~/.claude/agents/`。这种方式没有 Stop 钩子。

插件和安装器二选一。两者都装时，Claude Code 会看到两份 skill 和两套成员（`goal-teams:goal_backend` 与 `goal_backend`）；改用插件时先运行 `python3 tools/install.py --uninstall --host claude`。

## 2. V2.95 保留的任务图与预算

- direct 仍无需手写计划；工具自动形成最小任务合同，有限默认预算会明确记录。tracked 使用 `gt plan apply` 编译全部 active 任务。
- 每项任务绑定当前消费者、验收、范围、禁止范围、owner/validator、依赖、退出条件和 work units / attempts / revalidations / context 预算。
- TaskExactSet 与 DAG 按 revision/digest 冻结；编辑使旧绑定失效，重计划不清空已经消耗的预算。实际执行前在账本锁内校验和计费。
- 外部 blocker 只阻断其后继；独立分支继续。审计 finding 只有复现、范围、消费者、授权和剩余预算都满足才可进入修复计划。
- context 上限约束任务包的确定性估算大小，不等于模型实际 token 账单或宿主硬隔离。
- 未结算命令会阻止完成。控制进程中断后，先确认它及后代已停止，再由操作者运行 `gt recover-run <started-seq> --reason "说明" --confirm-stopped`；中断记录保留且不退预算，须真实重跑同任务、类型、名称和命令后再验收。

`gt graph status` 查看冻结 exact-set、DAG 和账本余额；任务可以用 `--budget-json`、`--consumer`、`--requirement`、`--forbid` 配置，或在 plan 中声明：

```json
{
  "id": "T1", "title": "修复计算", "owner": "goal_backend", "validator": "goal_reviewer",
  "scope": ["src/calc.py", "tests/test_calc.py"], "accept": "边界测试通过", "exit": "TDD 和受影响验证通过",
  "requirement_refs": ["criterion:C1"], "consumer_refs": ["criterion:C1"],
  "forbidden_scope": ["credentials/**"],
  "budget": {"work_units": 12, "attempts": 4, "revalidations": 8, "context_tokens": 12000},
  "exit_condition": {"required_receipt_types": ["tdd", "affected"], "on_budget_exhaustion": "replan"}
}
```

将此任务放入 plan 的 `tasks` 数组；当前目标须存在 C1。任务预算计量边界为经 `gt` 接纳且关联任务的命令和任务包；目标完成标准检查与监督器全局预算分别处理，不能拦截操作者在外部 shell 或模型中的活动。审计准入用 `gt graph finding finding.json`，需要真实、当前源码的失败回执和范围事实；自报“已复现”不能替代证据。


## 3. 用法上的变化

### 从 V2.68

| V2.68 | V2.95 |
|---|---|
| 每条回复都调用 output gateway，手工拼 13 字段 JSON | 讨论自由回答；执行结束用 `gt report`（结果、关键证据、未完成事项）；需要六字段时 `--format six` |
| small / medium / large 按规模走不同流程 | 三条路径：discussion、direct（默认，自动最小任务合同）、tracked（计划、分工、跨轮）；质量门由风险、领域、影响、阶段决定 |
| TaskExactSet、状态机和投影的准备步骤较多 | `gt plan apply plan.json` 一次写入整份计划；`gt task add/edit` 走同一校验 |
| 已有 TestCase/Run/Review 与 digest 校验；取证和校验入口分散 | `gt tdd red` / `gt tdd green`；Red 带 `--expect` 即 red_verified，否则收尾前 `gt tdd confirm` |
| 完成验证分布在多个合同与入口 | `gt finish`：补跑过期证据、跑完成标准的 `--check`、唯一判定、记录达成 |
| 已有 GitChangeReceipt 自动采集 baseline、tracked/untracked 差异 | `gt diff`：git 自动采集，对照任务范围 |
| 每轮按 12 个维度写 `loop-review.md` | 发现问题或结束时 `gt reflect`，最多 3 条 |
| 一律 SSH remote、worktree | 沿用仓库现状；项目约定用 `gt config set` 记录 |
| `references/current/ACTIVE.json`、generation、Legacy Replay | 不再存在；历史在 git tag |
| 已有 runtime controller；实际宿主适配需单独接线 | 可选 `gt loop run --host claude|codex`：预算、截止、判停在监督器里 |

### 从 V2.7 候选（只在你试用过 `develop-v2.7` 时相关）

| V2.7 候选 | V2.95 |
|---|---|
| `--size small|medium|large` | `--mode direct|tracked` + `--risk high` / `--domain ui|agent|desktop` / `--impact` / `--release`；`--size` 仍被接受 |
| `gt plan freeze` | `gt plan apply [plan.json]`；`freeze` 仍是同义词 |
| medium 的 Red 必须写 `--expect` | 可以不写（red_observed），收尾前 `gt tdd confirm` |
| `gt task done` 缺证据就拒绝 | 只提醒；硬门禁在 `gt finish` / `gt check` |
| `gt loop decide stop --outcome achieved` | `gt finish`（旧命令仍可用，判定相同） |
| `gt report` 六字段 | 默认简洁三段；`--format six` 或 `gt config set report_format six` |
| `gt task packet --phase` | 删除；成员两步协作（实现者自己 Red/实现/Green，验证人评审） |
| `rules/core.md` 等五个规则文件 | `rules/work.md` + `rules/tracked.md` |

V2.7 候选写下的账本（`goal-teams/event@1`）V2.9 照常读取，不迁移；下一次追加时自动补上 `manifest.json`。

## 4. 项目里的旧状态

V2.95 不读取 V2.68 的 `GoalTeamsWork-*` 目录或 `docs/` 证据，可以保留作为历史，也可以归档。V2.9 的状态保存在项目根目录的 `.goal-teams/`，用 `gt init` 创建。

建议把 `.goal-teams/` 除 `evidence/` 以外的文件都提交到 git：

- `ledger.jsonl` 和 `ledger.head`（链头，要和账本一起提交，否则 `gt verify` 会报缺失）
- `TaskList.md`、`benchmark.md`、`memory.md`、`loop-review.md`
- `manifest.json`、`config.json`、`.gitignore`、`.gitattributes`（`* -text`，防止 Windows 换行转换破坏哈希链）

`journal.json` 只在一次写入进行中存在，不要提交；`evidence/` 下的日志默认被忽略（见 `.goal-teams/.gitignore`）。

## 5. 本仓库维护者

| V2.68 | V2.95 |
|---|---|
| `./scripts/check.sh --phase development` | `python3 tools/check.py && python3 tools/acceptance.py && python3 -m unittest discover -s tests -t .` |
| `scripts/v250/generate_subagents.py` | 编辑 `members/*.md` 后运行 `python3 tools/gen.py` |
| 改版本：同步 VERSION、SKILL、release profile、manifest | 只改 `VERSION`，再运行 `python3 tools/gen.py` |
| `release-gate.yml` + S4 successor | 推送 `v<VERSION>` tag 触发 `release.yml`：构建、发布、回读校验 |

详见 [AGENTS.md](AGENTS.md)。
