# Goal Teams Scripted Tooling V1.94

V1.92 采用“提示词负责判断，脚本负责确定性”的混合模型。Goal Lead 仍负责澄清、拆解、风险判断和最终整合；重复、易漏、需要精确一致的动作必须交给脚本。

V1.93 保留这套边界，并把脚本按职责分目录。V1.94 增加 review 类脚本，要求对比和校验类任务采用 LLM + 脚本双重复核。根 `scripts/*.py` 和 `scripts/*.sh` 是兼容入口；真实脚本位于 `scripts/checks/`、`scripts/harness/`、`scripts/review/`、`scripts/benchmark/` 和 `scripts/install/`。

## 分工边界

| 工作 | 默认方式 | 原因 |
| --- | --- | --- |
| 目标理解、成员拆分、风险取舍 | 提示词 | 需要上下文判断 |
| 版本号、启动语和 README 同步 | 脚本 | 必须完全一致 |
| subagent 命名和 transport handle 检查 | 脚本 | 规则固定，容易漏 |
| Harness/Evidence/Pipeline 字段校验 | 脚本 | 机器可读协议需要确定性 |
| E2E 截图与像素级对比 | 工具/脚本 | 需要真实证据和可复盘指标 |
| Benchmark 任务包检查与报告聚合 | 脚本 | 评分口径必须稳定 |
| 冲突处理、预算取舍、自动续跑范围判断 | 提示词 + 表格 | 需要上下文，但必须记录字段 |

## V1.94 脚本

| 脚本 | 用途 | 默认运行位置 |
| --- | --- | --- |
| `scripts/check.sh` -> `scripts/checks/check.sh` | 总校验入口，串联结构、版本、agent 命名、Harness、pixel diff、benchmark 包检查 | 本地 |
| `scripts/install-local.sh` -> `scripts/install/install-local.sh` | 安装/更新本地 skill 和 `goal-*.toml`，可选更新 fallback `team-*.toml` 中文昵称 | 手动运行 |
| `scripts/check-version-sync.py` -> `scripts/checks/check-version-sync.py` | 检查 `VERSION`、启动语、README、runtime、`agents/openai.yaml` 一致 | `./scripts/check.sh` |
| `scripts/check-routing-fixtures.py` -> `scripts/checks/check-routing-fixtures.py` | 运行只规划/需求卡片、纯后端 CLI、UI 复刻、长任务续跑 4 个路由 fixtures，检查触发词覆盖和条件加载不会互相污染 | `./scripts/check.sh` |
| `scripts/check-agent-names.py` -> `scripts/checks/check-agent-names.py` | 检查 subagent 中文昵称、`member_id` / `display_name` / `transport_handle` 规则 | `./scripts/check.sh` |
| `scripts/check-member-layout.py` -> `scripts/checks/check-member-layout.py` | 检查成员包目录和 `prompt/template/workflow/scripts` 文件完整性 | `./scripts/check.sh` |
| `scripts/validate-harness.py` -> `scripts/harness/validate-harness.py` | 校验 Harness contract JSON/YAML 字段；UI 要求 E2E，复刻要求 pixel diff | `./scripts/check.sh` |
| `scripts/pixel-diff.py` -> `scripts/harness/pixel-diff.py` | 对截图做像素级对比，输出 changed ratio、MAE、diff 图 | 手动或 Harness 调用 |
| `scripts/compare-artifacts.py` -> `scripts/review/compare-artifacts.py` | 对文件或目录做 hash/size/path 对比，生成脚本复核证据 | 手动或 Harness 调用 |
| `scripts/validate-dual-review.py` -> `scripts/review/validate-dual-review.py` | 校验脚本复核与 LLM 复核记录，防止单边通过 | `./scripts/check.sh` 或收尾审计 |
| `scripts/benchmark-runner.py` -> `scripts/benchmark/benchmark-runner.py` | 检查 benchmark task package 结构，必要时生成报告 | `./scripts/check.sh` |

## 双重复核边界

脚本复核负责可机械判断的事实，例如文件存在、hash、schema、字段、路径、像素指标和报告格式。LLM 复核负责语义正确性、用户目标一致性、风险取舍和规则遗漏。脚本失败、LLM 失败或任一缺失时，不允许给 `pass`。

## Budget Gate

长任务或生产流任务必须在 Plan 中写预算门：

```text
Budget Gate:
- max_subagents:
- max_auto_continue_rounds:
- time_budget:
- token_budget:
- cost_budget:
- stop_when_exceeded:
```

缺少实际 tokens 或费用时写 `未提供`，不能估算成事实。预算不足时，Goal Lead 必须缩小范围、降级验证或记录 `blocked_needs_user`。

## Conflict Policy

并发任务必须记录冲突策略：

```text
Conflict Policy:
- shared_scope:
- write_owner:
- read_only_members:
- merge_owner:
- pause_conditions:
- replan_conditions:
```

同一 `locked_scope` 不允许多个实现成员并行写入。共享核心模块、认证、支付、迁移、安全敏感代码和大范围 API 合同默认串行。

## Evidence Insufficiency Rule

证据不足不能完成。以下情况必须被 QA、Reviewer 或 Completion Auditor 打回：

- 界面级任务没有 E2E 证据，也没有用户批准的例外。
- 复刻任务没有基准图、实际图、diff 图或差异指标。
- 实现者自测是唯一验证来源。
- Harness 只写了“人工检查通过”，没有检查项、证据路径或校验者。
- 生产流门禁缺少审批、凭证、监控或回滚证据却给出无条件 `pass`。

打回时使用 `failure_report` 或 `blocked_needs_user`，不要把缺口改写成完成。
