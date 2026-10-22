# 四组对照协议（V2.9 评测检查点）

回答一个问题：加载 Goal Teams 之后，**结果有没有更好、耗时和费用增加了多少**。四个实验组用同一批用例、同一提示词：

| 组 | 身份 | 怎么准备 |
|---|---|---|
| none | 不加载任何 Skill | `claude plugin eval` 的 W/OUT 组；另在干净的 `CLAUDE_CONFIG_DIR` 下确认没有全局 Skill 或成员文件被加载 |
| v2.68 | main `c3c0ebfd61197eb245d533ad88a1287b1ec5034b` | `git worktree add ../gt-v2.68 c3c0ebf`，按它的 README 安装到隔离的 `CLAUDE_CONFIG_DIR` / `CODEX_HOME` |
| v2.7 | `develop-v2.7` `395667364bcf28fa70c97e1264be034c87381ef0` | 同上，用 `tools/install.py --host claude --home <隔离目录>` |
| v2.9 | 本仓当前候选（记录 commit 与 tree） | `claude plugin eval plugins/goal-teams ...` 的 WITH 组 |

没有 V2.8 实现，不虚构 V2.8 组。每组的 Skill 文件、成员文件和初始工作区都隔离；同一用例的四组在同一台机器、同一天跑完。

## 固定的因素

- 模型、effort、`--judge-model`、宿主版本（`claude --version`、`codex --version`）、Python 版本，全部写进记录。
- 用例：`plugins/goal-teams/evals/` 下全部 8 例（6 例 V2.7 已有 + `direct-slugify-fix`、`tracked-two-tasks`）。
- 每例每组至少 3 次；执行顺序随机化（用例 × 组打散），不要按组批量跑。
- 评分口径：`graders/` 不改；两组都计分的项才进 Δ，`arm: with-only` 的指示项只说明 Skill 有没有按设计工作。

## 指标（每次运行都记）

| 指标 | 来源 | 说明 |
|---|---|---|
| 结果分 | 两组都计分的 grader | 每例每组的均值和分布；关键负向项（不越权、不外部写入、不假 Red）单独列，任一失败就标红，不被均值掩盖 |
| 耗时 | `aggregate-result.json` 的 duration / 轨迹首末时间戳 | 报 P50 和 P95；子代理耗时算进去 |
| 费用 | `aggregate-result.json` 的 `costUsd` | 取不到就写 unknown，不记 0 |
| gt 调用数 | 轨迹里 Bash 调用含 `gt.py` 的次数 | Lead 的调用；子代理另计 |
| 全部工具调用数 | 轨迹 | 不把成本藏进子代理 |
| 子代理数 | 轨迹里 Agent 调用 | — |
| 人工干预 | 为让它继续而额外发的消息数 | 用例要求的授权回复不算 |
| Lead 规则输入 | `gt route --mode <路径>` 的合计字节数 | v2.9：direct 8,185 B、tracked 14,222 B；其他组按各自架构统计 |

## 判读规则（回应 R09）

- 不可退化条件（权限边界、证据真实性、人工成果保护、迟到回执隔离）不参与消融，不因某次得分为零而删规则；它们由 `tests/acceptance.json` 维护。
- 只对可调流程做消融：步骤数、规则措辞、默认协作方式、成员 effort。
- 结论按分布说：direct 耗时 P50 的目标是 ≤ 1.2 × none，tracked ≤ 2 × none 且结果分不低于 none 和 v2.7；两任务流程 gt 调用 ≤ 10。样本不足、波动过大时写"待定"，不写"显著"。
- 质量、耗时、费用、人工干预分别报告，不折成一个总分。

## 记录表（CSV 列）

```text
date,case,group,commit,run,model,effort,host_version,judge_model,
score,critical_fail,duration_s,cost_usd,gt_calls,tool_calls,subagents,interventions,notes
```

每次运行一行；`aggregate-result.json`、`report.html` 和轨迹文件按 `results/<时间戳>/` 归档，不改写。

## 规模与授权

8 例 × 4 组 × 3 次 = 96 次会话（V2.9 方案估算 120 次），再加 LOOP 用例（P6b）。全部用运行者自己的额度，启动前由维护者授权（决策 D10）；本文件和测试不会触发任何运行。
