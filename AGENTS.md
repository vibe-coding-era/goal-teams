# Goal Teams 仓库维护指南（V2.95）

本仓库发布 Goal Teams：一个 Codex Skill，同时也是 Claude Code 插件。维护目标有四条：
- 规则少而准；
- 确定性的记账交给工具；
- 生成物与来源保持一致；
- 发布结果可以回读确认。

产品层面的长期要求见 [goal-teams.md](goal-teams.md)。

## 本次版本边界

V2.95 采用 V2.9 的单一运行时、direct/tracked、CLI、安装和发行结构；仅任务图与细粒度预算保留前代约束，接入同一个 ledger。不能重新引入旧 Generation/Host 全栈。计划准入、冻结 exact-set、DAG、范围与 forbidden scope、预算和退出条件均须有实际执行消费者与负向测试。

本仓开发 worktree 和临时生成物只放仓库根 `develops/`；过程文档、测试日志与凭证只放根 `docs/`，两者不跟踪、不安装、不打包。历史保留在 Git，不删除已有本地记录。

## 目录与来源

| 路径 | 内容 | 维护方式 |
|---|---|---|
| `plugins/goal-teams/` | **唯一的运行时包**，只有它会被安装或发布 | — |
| `…/skills/goal-teams/SKILL.md`、`rules/`、`templates/` | Lead 的操作手册、规则、文档模板 | 手写 |
| `…/skills/goal-teams/scripts/gt.py` + `goalteams/` | gt CLI（Python 3.9+，只用标准库） | 手写 |
| `…/agents/`、`…/codex/agents/`、`rules/tracked.md` 中的成员表 | 各宿主的成员文件 | `tools/gen.py` 生成 |
| `…/hooks/hooks.json`、`…/.claude-plugin/plugin.json`、`…/evals/` | Claude Code 钩子、插件清单、评测套件 | 手写；版本号由生成器写入 |
| `members/` | 成员的单一来源：`_protocol.md`、`_readonly.md`、`goal_*.md` | 手写 |
| `tools/` | `gen.py`、`check.py`、`acceptance.py`、`install.py`、`release.py`、`make_examples.py` | 手写 |
| `tests/`、`extras/okf-graph/` | 测试；`tests/acceptance.json` 是 AC01–AC36 固定验收矩阵；可选的 OKF 文档图（不随包发布） | 手写 |
| `examples/` | 真实的 gt 输出 | `tools/make_examples.py` 生成（README 除外） |
| `.claude-plugin/marketplace.json` | Claude Code marketplace | 手写 |

## 修改规则

- **不要复制目录来做版本。** 历史在 git tag 里（`v2.68` 及更早）。不要新增 `vX.Y` 形式的目录或文件，`tools/check.py` 会拒绝。
- **改成员**：编辑 `members/*.md`（frontmatter 可选 `effort: low|medium|high`、`model`），然后运行 `python3 tools/gen.py`。不要手改生成的 agents。
- **改版本**：只改 `VERSION`（如 `2.8.0`），然后运行 `python3 tools/gen.py`。生成器会同步以下位置：
  - `plugin.json`
  - gt 版本号
  - 身份语
  - README 版本区块
- **改路由**：门禁策略在 `goalteams/policy.py`（风险、领域、影响、阶段决定门禁；mode 只决定协作方式），规则文件映射在 `goalteams/routes.py`；SKILL.md 中的路径表必须与它一致，check 会比对。
- **改验收矩阵**：`tests/acceptance.json` 的 36 项只增不删（退役项改为 not_required 并写理由）；每项声明的 passed/partial 必须指向真实测试，`python3 tools/acceptance.py --run` 用实测结算。
- **规则 ID**：格式为 `GT-<领域>-<名称>`，全局唯一，不含版本号。新增规则时，先说明它解决了什么真实失败，最好有评测用例。
- **预算是硬限制**：
  - 文件字节数和每条路径的字节数见 `tools/check.py` 的 `FILE_BUDGETS` 和 `ROUTE_BYTE_BUDGETS`（direct ≤ 8 KB、tracked ≤ 14 KB）。
  - 超出预算时，先删旧内容再加新内容。
- **运行时代码**：Python 3.9+，只用标准库，兼容 Linux/macOS/Windows；不用 `shell=True`，不读取凭证。
- **README**：正文由维护者维护；版本区块由 `gen.py` 生成。AI 修改 README 正文，需要维护者在当次任务中明确要求。

## gt 账本格式（供维护者参考）

`.goal-teams/ledger.jsonl` 每行是一条 JSON 事件，字段如下：

- `schema`：`goal-teams/event@2`（V2.7 候选写的 `event@1` 仍能读，不迁移）；
- `seq`：递增序号；
- `ts`：UTC 时间；
- `type`：事件类型；
- `actor`：执行者；
- `data`：事件内容；
- `prev`：上一行原文的 SHA-256，构成哈希链。

`manifest.json` 记录事件格式、最低读取版本（`min_reader`）、所需能力和项目身份；版本不够或能力缺失时 gt 不判定也不追加。`ledger.head` 记录最后一条事件的 seq 和 SHA-256，用来发现被截断或改写的末尾；末尾与它不一致时 gt 拒绝追加。每次追加先写 `journal.json`（旧链头、目标 seq、事件摘要），再写事件并 fsync，再原子替换链头，最后删除 journal；崩溃后只按 journal 补齐或忘记那一次写入，账本在 gt 之外多出的事件会被拒绝。`.gitattributes`（`* -text`）防止换行转换破坏哈希链。

`type` 有这些取值：

- `init`、`goal`、`goal.update`、`goal.accept`（逐项验收，assurance=self_reported）、`goal.finished`（`gt finish` 记录的达成）、`auth.grant`
- `task.add`、`task.edit`、`task.state`、`plan.applied`（`gt plan apply`；旧的 `plan.freeze` 仍能读）
- `run.started`（命令执行前写入，绑定目标、计划版本与任务规格摘要）、`tdd.red`（outcome red_verified / red_observed / red_invalid …）、`tdd.green`、`tdd.confirm`、`run`、`diff`、`scope.allow`、`review`（带 assurance）；回执带 `started` 指回开始事件，落账时目标已结束或任务规格已变的回执带 `late`，只保留不计入验收
- `loop.decide`、`reflect`、`context.add`、`preflight`、`report`、`memory`、`config`
- `operation.prepared` / `operation.dispatched` / `operation.result` / `operation.confirmed` / `operation.reconciled`：外部操作先登记意图再执行，回读确认（`gt operation`）
- `control.set` / `control.proposal` / `control.decision`：控制面（预算、允许工具）只由操作者设置；子会话只能提案
- `loop.lease` / `loop.lease.end` / `loop.reserve` / `loop.round` / `loop.next`：监督器租约（epoch 防重入）、预算预留与结算、每轮记录与确定性判定
- `retire`（撤销一次错误的检查失败）、`head.reset`（确认原因后重置链头）

 reducer 不认识的事件类型会被记录并阻断完成判定，不再静默忽略。

哈希链和链头能发现意外损坏和粗糙的改写，但挡不住有意同时改写账本和链头的人；需要更强的保证时，把 `.goal-teams/` 提交到 git，并在受保护的分支上合并。

状态由 `goalteams/state.py` 中的 reducer 从事件重建。`TaskList.md`、`benchmark.md` 是投影，只由 gt 写入。修改事件结构时，旧事件必须仍能被 reducer 读出；用 `schema` 字段区分版本。

## 行为变更与测试

先保存真实 Red，再实现 Green；测试文件摘要保持不变，源码摘要必须变化。开发阶段运行受影响检查；实现完成并冻结候选后运行全量测试和独立审核。测试、模型评测、宿主加载、安装与远端发布分别报告，未运行不得写 passed。

## 提交前

```bash
python3 tools/gen.py --check
python3 tools/check.py
python3 tools/acceptance.py            # 验收矩阵引用有效；--run 用实测结算
python3 -m unittest discover -s tests -t .
python3 -m unittest discover -s extras/okf-graph/tests -t extras/okf-graph
python3 tools/make_examples.py --check      # gt 输出改了就重新生成 examples
claude plugin validate --strict plugins/goal-teams   # 有 Claude Code CLI 时运行
```

CI（`.github/workflows/ci.yml`）在 Linux/macOS/Windows 上跑这些检查，不需要任何密钥。例外：examples 只在 Linux 上比对；`extras/okf-graph` 不支持 Windows，在 Windows 上跳过；插件校验单独在 Linux 上跑。

## 评测

`plugins/goal-teams/evals/` 中的用例比较"有 Skill"和"无 Skill"两种情况下的结果，详见该目录的 README。改动 SKILL.md、规则或成员后，至少跑一次冒烟评测：

```bash
claude plugin eval plugins/goal-teams --scaffold --allow-tools Bash Write Edit --ablation none --runs 1
```

评测会使用运行者自己的模型额度。

## 发布

1. 更新 `VERSION` 和 `CHANGELOG.md`（标题包含版本号，如 `## V2.7.0 — <日期>`），运行 `python3 tools/gen.py`。
2. 合并到 main，打 tag 并推送：`git tag -a v2.7.0 -m "Goal Teams V2.7"`，再 `git push origin v2.7.0`。也可以在 Actions 里手动运行 release，输入已有的 tag。
3. `release.yml` 会依次完成：
   1. 校验 tag 与 VERSION 一致，且 tag 指向 main 上的提交；
   2. 跑全部检查和测试；
   3. 运行 `tools/release.py build`，只构建一次，生成确定性的 tarball、`release.json` 和 `SHA256SUMS`；
   4. 可选：用仓库密钥 `GOAL_TEAMS_RELEASE_SIGNING_KEY` 做 ed25519 签名；
   5. 发布前先 verify；如果 Release 已存在（上次回读失败后重跑），比对远端资产：完全一致就跳过创建、只做回读，不一致或不完整就停止，不覆盖；
   6. 下载已发布的产物，用 `tools/release.py verify` 回读校验，并与构建产物逐字节比对。
4. 本地自检（工作区必须与 HEAD 一致，否则 build 会拒绝；试构建加 `--allow-dirty`，此时 commit/tree 记为 null）：

   ```bash
   python3 tools/release.py build --out dist
   python3 tools/release.py verify dist
   ```

签名是可选的，但两项要么都配、要么都不配：
- 私钥：`openssl genpkey -algorithm ed25519 -out key.pem`，存为仓库密钥 `GOAL_TEAMS_RELEASE_SIGNING_KEY`，不进仓库；
- 公钥：`openssl pkey -in key.pem -pubout -out keys/release-ed25519.pub`，提交到仓库。

只配一项时，发布前的 verify 会失败，不会发布。verify 只证明资产彼此一致；没有签名时不证明来源。构建只做一次，不宣称可复现；发布说明会如实写明本次是否签名。

## 本仓库自己的 Git 约定

以下约定只适用于本仓库，不是 Goal Teams 对用户项目的要求：

- 开发分支命名为 `develop-v<major.minor>`；宿主要求命名空间时加前缀，例如 `codex/develop-v<major.minor>`。
- 推送到 GitHub 时，本仓库维护者使用 SSH remote。
