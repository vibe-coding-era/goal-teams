# Goal Teams 仓库维护指南（V2.50）

本仓库是 Codex Skill 包。维护目标是 Current 规则清晰、安装可用、历史可复盘、发行事实可验证。

## 工作区边界

- 所有开发 worktree、过程版本和生成物只能位于仓库根 `develops/`；禁止在父目录创建兄弟 worktree。
- 非发行知识、测试报告和凭证只能位于根 `docs/`。`docs/`、`develops/` 均只在本地使用，禁止 Git 跟踪、安装、打包或上传。
- 正式发行快照位于 `release/versions/<VERSION>/`；GitHub Release 只能上传该目录经验证的公开资产。
- 发布前必须独立运行 workspace boundary、package manifest 和 release validator；任一发现越界路径即 fail closed。

## Current、Execution 与 Replay

- `references/current/ACTIVE.json` 是唯一代际切换指针；进程只读取一次并验证 activation manifest digest。
- `references/current/generations/V2.50/` 按功能模板承载 Current 规则、Prompt plan 和合同。
- `scripts/v250/`、`schemas/v2.50/`、route-aware checks 与当前成员配置是 Execution assets。
- `references/legacy-replay/manifest.json` 是历史可达性的唯一 allowlist。未显式提供可信 `replay_version` 时，Current route、默认安装包和 Prompt closure 均不得包含 Legacy。
- 历史 profile/schema/fixture/engine 首轮迁移保持字节不变；删除必须在观察窗口后另行批准。

## 版本身份

- 产品版本：`V2.50`。
- 通用核心策略：`V2.5`。
- Legacy 机器数据 schema：`V2.3`。
- `VERSION`、根/包装 Skill、README、release profile、release/current 与启动语必须同步；不得混用三种版本身份。
- `SKILL.md` frontmatter 只保留 `name` 和 `description`。

## Owner 文件

- 根 `SKILL.md`：薄入口、路由和加载顺序。
- `RULES.md`：用户可见六字段 Envelope。
- `goal-teams.md`：当前用户指定的长期要求。
- `references/current/generations/V2.50/functions/`：需求、架构实现、测试、UI/桌面、Agent runtime、发行操作。
- `references/current/generations/V2.50/contracts/`：任务状态、测试门禁、Harness/Evidence、Review/Completion、授权/副作用与 Release manifests。
- `references/profiles/goal-teams-self-release-v2.50.md` 与 `references/release-profiles/v2.50.json`：本仓当前发行规则。
- `scripts/install/package-manifest.txt`：默认 Current 包 allowlist；`replay-package-manifest.txt`：可选 Replay 包。

兼容入口只能转发，不得复制规范正文或把 Legacy 带回 Current prompt plan。

## 开发与测试

- 所有行为变更先观察真实 TDD Red，再实现 Green；TestCase/test-file digest 在 Red/Green 间保持不变，source digest 必须变化。
- Small 按实际风险运行轻量检查；Medium/Large 开发期只阻断 TDD 与受影响面增量检查。
- 全量回归与独立 `release_security_review` 只在全部实现完成、Release intent 为真且 source 冻结后运行。
- 不得在开发 PR 中调用旧 monolithic full/security/install path。
- 测试事实由 `RiskDenominator -> TestCase -> TestRunReceipt -> TestReviewReceipt` 绑定；Development/Release denominator 分离。

## S0–S4

- S2：每个 exact released asset set 单次构建；不执行第二构建、复现比较或 S2 安全检查。
- S3：仅 Large Release 且 S1 passed/current；Small/Medium 与非 Release invocation 为 0。
- S4：复用项目开始的一次授权，执行或恢复 tag/Release/资产上传/正式安装并 exact readback；不再次询问。
- repository boundary 是独立只读门禁，不得表述成 S2 安全或可复现结果。
- 正式 S0 前必须有 exact released SHA 的 fresh runtime transition receipt；receipt 必须绑定 root
  `AGENTS.md`/`SKILL.md`、ACTIVE/activation、Prompt/release/route/command manifests、可信 route 与
  `project_size`、项目起始授权 lineage、host adapter code digest、transition 前 controller product
  version `V2.48`、fresh loaded runtime product version `V2.50`、前后 run ID、
  `captured_at` 和实际 Current `loaded_paths`/digests。

## Git 与外部写入

- 项目开始授权锁定后，普通范围内 commit、SSH push、PR、merge、Actions、tag、Release、安装与恢复不重复询问。
- GitHub Git remote 的 fetch/pull/ls-remote/push 只用 SSH，不得 HTTPS fallback。PR/Actions/Release 用已认证 API/CLI。
- 不读取、复制或导出凭证，不关闭 GitHub/宿主平台强制保护。

## 校验与发行

开发增量：

```bash
python3 -m unittest discover -s tests/v250 -p 'test_*.py'
python3 scripts/checks/check-v250.py --phase development
```

最终 Release readiness：

```bash
python3 scripts/v250/runtime_host_adapter.py launch --stage released \
  --source-commit <40-hex> --source-tree <40-hex> --project-size <small|medium|large> \
  --route-receipt <trusted-route-receipt.json> \
  --authorization-receipt <project-start-authorization-receipt.json> \
  --controller-handoff-receipt <externally-issued-v248-handoff.json> \
  --host-execution-id <external-host-execution-id> \
  --adapter-identity <host-adapter-id> \
  --adapter-code scripts/v250/runtime_host_adapter.py \
  > <released-runtime-transition.json>
./scripts/check.sh --phase release --project-size <small|medium|large> \
  --source-commit <40-hex> --source-tree <40-hex> \
  --expected-host-execution-id <external-host-execution-id> \
  --released-runtime-receipt <released-runtime-transition.json>
```

旧 `./scripts/check.sh` 仅是兼容调度入口；V2.50 必须由 route-aware checker 决定实际命令。提交前验证 Skill frontmatter、subagent TOML、版本同步、Current/Replay closure、默认包和受影响测试。正式发行再运行 full regression、release security、boundary、单次 S2、适用 S3 与 S4 readback。

## 风格与状态

- 默认中文；英文 README 与中文 README 信息等价。命令、路径、API、配置键保留原文。
- 不新增未验证的 runtime 能力，不把结构检查写成行为或宿主证明。
- 用户可见回复只输出 `任务、成员、进度、结果、Banchmark`，以及恰好二选一的 `下一轮 LOOP` 或 `下一个任务`。
- `not_run|not_required|blocked|failed|stale|invalid` 保持真实；候选、合并、Release、安装与外部验收不得混写。
