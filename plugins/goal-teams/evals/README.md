# Goal Teams 评测

目的：衡量加载插件（WITH）比不加载（W/OUT）**结果**好多少。两组用同一提示词，Δ = WITH − W/OUT。

- Δ 只由"两组都计分"的项决定。`arm: with-only` 的项和 `tool_used: Skill`（skill-fired）是指示项：只在 WITH 组评估，用来看 skill 有没有按设计工作，不计分。
- 除 discussion 外，每例提示词里都有一句自然的触发语（如"用 Goal Teams 的快速通道修一下"），保证 WITH 组会加载 skill。discussion 保持普通提问，不带触发语。

| 用例 | 测什么 | 两组都计分 | 只看 WITH |
|---|---|---|---|
| discussion-plain-question | 纯问答答对、简洁，不跑命令、不派成员 | answer-quality、no-execution-envelope、no-shell-bookkeeping、no-team-dispatch | — |
| small-bugfix-tdd | 99 元边界修复，真的先红后绿 | fix-inclusive-threshold、regression-test-added、test-before-fix（先 Edit 测试再 Edit 源码）、red-run-before-fix（改源码前轨迹里已有失败的测试输出）、evidence-summary | skill-fired |
| medium-feature-ledger | 中型功能交付 | feature-store、feature-cli、feature-tests、cli-tests、readme-usage、red-shown（汇报证明先红后绿）、delivery-honesty（分清已验证/未验证） | skill-fired、ledger-goal、ledger-tdd、ledger-report、progress-line、task-board |
| api-defect-hunt | QA 找订单 API 缺陷 | defect-auth、defect-duplicate-orders、defect-read-after-write、no-false-defects、ui-status-honest（读 `qa-report.md`）、repro-evidence（最终回复带清单）、service-untouched | skill-fired |
| release-needs-authorization | 外部写入前先要一次性授权 | asks-authorization、no-external-write | skill-fired |
| plan-only-requirement-card | 需求卡片要素齐全、不写代码 | card-content、acceptance-ids、no-code-write、no-code-edit | skill-fired |
| direct-slugify-fix | direct 路径：不建计划、自动记账、`gt finish` 收尾 | fix-trailing-dash、regression-test-added、red-run-before-fix、evidence-summary | skill-fired、ledger-direct、ledger-finished、no-plan-ceremony |
| tracked-two-tasks | tracked 路径：一份 plan.json 一次 apply、两任务、≤ 12 次 gt 调用 | feature-char-count、feature-cli-chars、tests-added、cli-tests、delivery-honesty | skill-fired、ledger-plan、ledger-finished、gt-budget |

- `ledger-*` 直接读 `.goal-teams/ledger.jsonl`：有 medium 目标、成立的 Red（`red_verified`/`red_observed`）之后有 `green_ok`、有 `report` 事件。成员子代理里的 Bash 调用不一定出现在主轨迹，账本才是 gt 实际写下的记录。
- ui-status-honest 接受如实写"未测/not_run"（没有浏览器时）。

## 运行（仓库根目录）

> **成本**：每次运行都是用你的凭据发起的一次完整 Claude Code 会话；每个 llm 评分项再调 3 次评审模型（默认 haiku）。都计入套餐用量或 API 账单。WITH 组会派成员子代理，通常比 W/OUT 更贵、更慢。

冒烟（单例，两组各 1 次）：

```bash
claude plugin eval plugins/goal-teams --scaffold --allow-tools Bash Write Edit --runs 1 --case small-bugfix-tdd --no-publish
```

全套冒烟（8 例 × 2 组 × 1 次 = 16 次运行）：

```bash
claude plugin eval plugins/goal-teams --scaffold --allow-tools Bash Write Edit --runs 1 --no-publish
```

结果在 `plugins/goal-teams/evals/results/<时间戳>/`。`aggregate-result.json` 顶层的 `costUsd` 就是一轮的实际花费；完整运行（下面，48 次运行）约为它的 3 倍，`--max-cost-usd` 按这个估算设：

```bash
claude plugin eval plugins/goal-teams --scaffold --allow-tools Bash Write Edit --runs 3 --max-cost-usd <上限>
```

- 只看 WITH 组的绝对分（指示项也计分）：加 `--ablation none`。两种模式的绝对分不能直接比。
- CI：再加 `--trust-plugin --json results.json --threshold 0.8 --no-publish`，并固定 `--model` 和 `--judge-model`，免得把模型更新误判成插件回归。
- `--scaffold` 以你的身份运行 `scaffold.sh`：只复制 `fixture/`、建 git 仓库，不联网。PATH 上要有 `bash`、`git ≥ 2.31`、`python3`。脚本以 `bash <脚本真实路径>` 运行，cwd 是空工作区（2.1.302 已核实）。
- 授予 Bash 后命令在沙箱里跑；Linux 先装 `bubblewrap`、`socat`。
- 离线自检（不调模型）：`python3 -m unittest tests.test_evals_layout -v`。它会跑真实 gt 生成账本来测 ledger-*，有 node 时还会用 JS 引擎复核全部正则。

## 怎么看 Δ

- 正数说明 skill 有帮助；约等于 0 说明没起作用，或基线本来就做得好。
- Δ≈0 且 skill-fired 失败：skill 没触发，先查触发语和 SKILL.md 的 description。
- Δ 为负但 skill-fired 通过：先看 report.html 里各项解释，再用 `--judge-model sonnet` 重跑排除评审噪声。
- 单次运行噪声大，以 `--runs 3` 为准。

四组对照（无 Skill、两个历史版本、当前候选）的协议、指标与记录表见 [comparison.md](comparison.md)。

## Codex 手动对照

1. 用各例 `prompt.md` 正文作提示词；有 `scaffold.sh` 的先在空目录里运行 `bash <用例目录>/scaffold.sh`。
2. 同一提示词分别在装了、没装 skill 的新会话里各跑至少 2 次，按 `graders/` 判定，记下成功与否、轮数、tokens 和人工干预次数（为让它继续而额外发的消息；用例本身要求的授权回复不算）。
