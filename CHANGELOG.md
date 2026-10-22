# Changelog

## V2.95.0 — 2026-10-22

本地整合候选：采用 V2.9 的单一运行时和产品流程，仅任务图与细粒度预算保留 V2.68 的约束语义。此条记录源码变化，不声明已发布、已安装或真实模型验收。

- 保留 direct/tracked、自动取证、统一完成入口、成员生成、双宿主安装器及精简发行流程。
- 任务图与预算接入同一账本：消费者准入、冻结 TaskExactSet、revision/digest、DAG、范围/禁止范围、有限预算、blocker 闭包与有界 finding 准入。
- 修复检查仍在运行时提前完成、逐任务 TDD 漏检、unknown 操作的 supervisor 判停顺序。
- 增加中断命令显式结算和同命令重验；旧 achieved 入口在锁内重验快照。依赖准入验证前驱当前范围与未闭合失败，独立范围的改动不误阻断。
- 修复 Git 提交身份与打包字节不一致、回滚 dry-run 写入、嵌套 Git 源码检查空跑、宿主能力报告误标成功。
- 更正迁移文档对旧版 TDD/Git 自动采集能力的描述；保留真实模型、宿主和远端发布验证的证据边界。

## V2.9.0 — 2026-10-22

以下为导入源码的版本说明，发布状态未由源码包证明：包含未单独发布的 V2.7 候选（下方 V2.7.0 一节）的全部内容，再加以下改动。V2.8 只有方案，没有代码。升级见 [MIGRATION.md](MIGRATION.md)。

### 用起来更快
- **三条路径**：discussion（直接回答）、direct（默认：任何实现任务，不论文件数，不建计划、不派成员；第一条 `gt tdd red` / `gt run` 自动建立最小状态）、tracked（用户要计划、分工、并行、跨轮或发布时）。删除按文件数、模块数升级的规则。
- **质量门与路径无关**：`policy.required_gates(风险, 领域, 影响, 阶段)`。同样的风险和改动，direct 与 tracked 要求相同；纯文档不要求 TDD，纯样式不强制全站 E2E；认证、支付、个人数据、迁移用 `--risk high`。
- **规则减半**：SKILL.md 4,090 B（原 8,018）；`rules/work.md` + `rules/tracked.md` 取代五个规则文件；Lead 读取量 direct 8,185 B、tracked 14,256 B（V2.7：small 16.9 KB、medium 30.8 KB）。规则 ID 125 → 98。
- **一次写入的计划**：`gt plan apply plan.json` 在内存校验整份计划后一条事件提交，无效就什么都不写；`plan freeze` 并入。
- **收尾一步**：`gt finish` 补跑过期证据和完成标准的 `--check`，用唯一判定给出结论并记录达成；可重复运行，不评审、不构建、不外部写入。
- **简洁汇报**：`gt report` 默认"结果、关键证据、未完成事项"；六字段改为 `--format six`。`gt review --file` 批量评审。`gt resume` 生成六节续接包。
- **成员两步协作**：实现者自己写测试、Red、实现、Green，验证人评审；成员可设 `effort`、`model`。
- `gt task done` 缺证据只提醒；Red 的 `--expect` 可后补（`gt tdd confirm`）。

### 结论更可靠
- **唯一完成判定** `completion.evaluate()`：纯函数；`gt check`、`gt finish`、`gt report`、`gt loop decide`、`gt goal accept`、监督器都读它。三级结论 engineering_passed / criteria_accepted / goal_achieved；状态 achieved、review_required、acceptance_required、blocked、unverified；每个门禁 passed / failed / not_run / stale / not_required。
- **完成标准**：`--done` 编号 C1…，可配 `--check` 命令；没有命令的由 `gt goal accept --item --quote` 记录，固定 assurance=self_reported；标准改了验收自动过期。
- **保证等级**：评审记录 self / correlated_reviewer / self_reported；高风险、发布、`require_independent_review` 要求 correlated_reviewer。
- **Red 三态**：red_verified 才是有效 TDD；`gt tdd confirm` 读原始日志（sha256 绑定），日志被改过即拒绝。
- **账本**：`goal-teams/event@2` + `manifest.json`（版本或能力不够就拒绝判定与追加）；journal 提交协议，崩溃后补齐或忘记那一次写入，gt 之外追加的事件被拒绝；未知事件类型阻断完成判定。
- **迟到回执**：命令执行前写 `run.started`；回执落账时任务规格已变或目标已结束，记 `late` 只保留不计入验收；中断的命令在看板和检查里可见。
- **外部操作**：`gt operation prepare/dispatch/confirm/reconcile`：先登记意图再执行；结果不明不重放，`once` 不重试；`--required` 的操作回读确认前不能达成；`gt resume --readback` 对账。
- **安装事务**：每次切换写 journal，断电后下一次安装或 `--rollback` 先撤销记录的移动；`--dry-run` 不创建任何东西。
- **发行资产**：`release.json` 带 `asset_set_id` 与构建环境，verify 重新计算。

### LOOP（可选，cooperative 模式）
- `gt loop run --host claude|codex`：每轮一个无头会话，喂续接包；监督器负责预算预留与结算、绝对截止时间、租约与 epoch（同一目标只有一个监督器，旧 epoch 写入被拒绝）、按证据指纹判 stalled、外部操作不明时 blocked。只有 achieved 结束目标。
- `gt loop next` 手动记录同一判定；`gt loop probe` 输出宿主能力报告（逐项写明 probe_passed / documented / unavailable）。
- 控制面：`gt control set` 只由操作者设置预算；子会话（`GT_SUBSESSION=1`）只能 `gt propose`，`auth grant`、完成标准修改、`config set` 拒绝它。这是约定，不是 OS 隔离。

### 评测与验收
- `tests/acceptance.json`：AC01–AC36 固定验收矩阵，`tools/acceptance.py --run` 用实测结算。本版：passed 27、partial 8、not_required 1（各项说明见文件）。
- 评测新增 direct-slugify-fix、tracked-two-tasks 两例与四组对照协议 `evals/comparison.md`；真实模型评测未运行（需要维护者授权额度）。
- `tools/bench_ledger.py`：账本追加与重放微基准。

### 维护决策（方案第三部分的默认值；维护者可改选）
- D1 README：正文人工维护，版本区块由 `gen.py` 写在标记之间。
- D2 状态在 `.goal-teams/`；`tools/check.py` 拒绝跟踪 `docs/`、`develops/`。
- D3 正式资产只在 GitHub Release（`dist/` + `release.json`），不入库。
- D4 `release.yml` 保持 `contents: write`，已存在的 Release 先比对再回读，不一致即停。
- D5 维护者 SSH；安装示例 HTTPS 只读。
- D6 六字段汇报退役为可选格式。
- D7 发行阶段：tests + check、`release.py build`、安全评审（高风险）、publish + readback。
- D8 Stop 钩子不做第二套 LOOP 判停，保留为提醒。
- D9 不单独发布 V2.7；不做 event@1 迁移（照常读取）。
- D10 真实模型评测待授权。
- D11 成员保留 20 个，按需派发。
- D12 LOOP 默认预算：3 轮 / 30 分钟 / 单轮 10 分钟 / 检查 2 分钟 / 宽限 5 秒（待测参数）。

### 已知限制
- cooperative 模式不防同权限的恶意进程；脱离进程组的后代不保证被终止；费用硬上限无法前置执行（取不到时记 unknown）。
- Codex 适配器未在真实 Codex 上运行（本机未安装）；Claude Code 适配器只做了能力探测，未跑真实会话。
- `release.yml` 的发布与已存在比对只做了静态审查。

## V2.7.0 — 2026-10-19（候选，未单独发布，并入 V2.9.0）

破坏性版本：从"规则驱动 + 版本化副本"改为"薄规则 + 确定性工具"。升级步骤见 [MIGRATION.md](MIGRATION.md)。

### 新增
- **gt CLI**（`plugins/goal-teams/skills/goal-teams/scripts/gt.py`，Python 3.9+，仅标准库，Linux/macOS/Windows）：负责所有确定性记账。
  - 账本：只追加，带哈希链。
  - 任务与计划：任务、子任务、依赖图（分层、关键路径、并行宽度）、计划冻结与版本号。
  - 证据：
    - TDD Red/Green 回执：Green 重跑 Red 的同一条命令，测试文件不变，源码内容必须变化（只提交不算），且实现落在本任务的锁定范围里（只改测试数据不算）。medium/large 的 Red 要写 `--expect`；最近一次 Green 没通过会阻断完成。
    - 每个代码任务都要有在最终代码上通过的记录（Green 或 affected，人工结论不算）；之后任何文件变了都要重跑，收尾用 `gt rerun` 一次完成。测试报告等没人读取的命令输出用 `--output` 声明（只能是目标开始后新生成、未跟踪、不在代码范围里的非源码文件；Green 和 rerun 沿用；检查和汇报会列出）或加进 .gitignore，其余改动一律算源码；`task done` 只看本任务自己的实现，不被并行任务的进行中改动挡住。
    - 检查回执：失败只能由同一命令的通过关闭；同一份代码上先失败后通过会被标为不稳定；命令写错的失败可用 `gt retire` 带理由撤销（写进检查和汇报）；命令不存在不算检查结果。`--artifact` 记录构建产物的大小与 SHA-256，声明的产物不算源码。
    - 基于 git 的越界检查（Red 绑定的测试文件算作任务范围）；绑定文件摘要的评审，文件变化后自动过期，过期的任务不计为完成；完成检查以主工作树为准。
  - 账本完整性：哈希链加 `ledger.head` 链头。截断或改写末行会被发现，gt 也不会在不一致的账本上继续追加（确认原因后用 `gt verify --reset-head --reason` 留痕重置）；证据日志不会被覆盖（其他历史留下的同名日志移到 `evidence/orphans/` 并提示）；CRLF 检出不破坏哈希链。
  - 流程：一次性授权、轮次决策、完成检查（`gt check`，含完成轴；`--release` 加发布前门禁）、环境预检（`gt doctor`）、项目约定（`gt config`）。
  - 评审：任务由验证人评审，Goal Lead 评审要加 `--self`；large 的完成审计由 goal_completion_auditor 或用户签署，绑定当前源码。
  - 发布类目标：发布前 `gt check --release`，回读（`--kind release`）通过后才能记为达成。
  - 输出：看板、六字段执行汇报（`gt report`，中/英）、按成员和步骤生成的任务包（`gt task packet --for --phase`）。
- **成员单一来源**（`members/`）：共享协议 + 20 个角色。用 `tools/gen.py` 生成 Codex TOML 与 Claude Code 子代理。
  - runner/read-only 成员在 Claude Code 中禁用 Write/Edit。
  - 所有成员禁止再派子代理。
- **Claude Code 插件与 marketplace**（`.claude-plugin/marketplace.json`、`plugins/goal-teams/`），带一个可选的 Stop 钩子：项目运行 `gt config set enforce_report true` 后，提醒发送 gt report。
- **跨平台安装器** `tools/install.py`：支持 Codex 与 Claude Code。
  - Codex 的 skill 装到 `~/.agents/skills/goal-teams`（Codex 当前的用户 skill 目录），旧位置 `~/.codex/skills/goal-teams` 移入备份。
  - 内置"源目录 = 目标目录"保护：修复 V2.68 中按 README 安装会把 git clone 替换掉的问题。
  - 旧安装和旧成员文件先移入备份，不删除；旧版（V2、git clone）的备份不会自动清理，其他备份保留最近 3 份。
  - 支持校验、卸载、回滚。
- **评测套件**（`plugins/goal-teams/evals/`，用 `claude plugin eval` 运行）：比较有无 Skill 时的结果；GT-BENCH-005 改造为 API 缺陷狩猎用例。
- 真实示例 `examples/`：由 `tools/make_examples.py` 运行 gt 生成，CI 校验与实际输出一致。
- 仓库检查 `tools/check.py`，覆盖：
  - 生成物是否同步
  - 文件字节预算与路由 token 预算
  - 禁止版本化目录
  - 运行时包内无陈旧版本号、本机路径或测试数据（评测夹具除外）
  - SKILL.md 格式，以及路由表与代码一致
- 精简的发布工具 `tools/release.py`（确定性 tarball、SHA256SUMS、release.json、回读校验、可选 ed25519 签名校验）与 `.github/workflows/{ci,release}.yml`。CI 不需要密钥，fork PR 可直接运行。

### 变更
- 路由按规模真正裁剪。按文件原始字节统计：small 读 SKILL.md + core + testing 共 16.5 KB，medium/large 共 30.5 KB；V2.68 按 rule-manifest 的路由归属统计，SMALL-DEVELOPMENT 路由的 owner 规则共 64 KB，另加每次都要读的 SKILL.md、RULES.md、ACTIVE.json 和三份 manifest 共 145 KB。token 数按 `tools/check.py` 估算（small ≈ 6.9K，medium ≈ 12.5K），与 Claude Code `plugin details` 的估算接近，但不是实测。
- **Small 快速通道**：不建账本、不派预检子代理，只做 Red → Green → 摘要；遇到升级信号自动转 medium。
- **讨论、只规划与方案预览**：自由格式回答，不再经过输出网关。执行汇报由 `gt report` 从账本生成，LLM 只写摘要；目标要交付内容本身时，先写内容再附汇报。gt 出错时以内容为先，不再用 blocked 诊断替换答案。
- **项目约束改为项目级配置**（`gt config set`，存于 `.goal-teams/config.json`）：
  - remote 协议沿用仓库现状（V2.68 要求一律 SSH）。
  - 分支默认为"提交前若在默认分支则建功能分支"（V2.68 要求一律建 `develops/` worktree）。
  - 新增单 Agent 模式，用于没有子代理的宿主。
- 字段显示名 `Banchmark` 改为 `Benchmark`；支持 `--lang en`；链接改为项目相对路径。
- 反思只在发现问题或目标结束时写，每次最多 3 条（V2.68 要求每轮按 12 个维度写）。
- 数据库破坏性操作规则从孤立的 V2.68 prompt 迁入核心规则（GT-CORE-DATA）。

### 移除（历史保留在 tag v2.68 及更早版本中）
- **规则与代际**：`references/`（11 代规则与 Legacy Replay）、`prompts/`（未被加载的 626 KB）、版本化的 `schemas/`、`scripts/v2*`、`tests/v2*`、`subagents/`、`benchmarks/`、`release/`、根目录 `SKILL.md` 与 `RULES.md`。仓库 git 跟踪内容从 1,507 个文件 20.9 MB 降到 258 个文件 7.8 MB（其中 6.8 MB 是不随包发布的 `extras/okf-graph` Unicode 测试夹具）；运行时包 `plugins/goal-teams/` 为 163 个文件 481 KB；`tools/release.py build` 生成的 gzip 发布包（运行时包加顶层文档、marketplace 和安装器，171 个文件）约 190 KB。
- **自发行与输出机制**：S0–S4 自发行机制、runtime transition 回执、输出网关及其请求 JSON。
- **安装器**：`install-local.sh` 及其 `--update-team-fallback`。
- **OKF 文档图**：移到 `extras/okf-graph/`，可选，不随包安装。

## V2.68 Published — 2026-09-08

- Published [Goal Teams V2.68](https://github.com/vibe-coding-era/goal-teams/releases/tag/v2.68), Release `384469308`, with annotated tag `v2.68` at source `12728a6878544fbfaf208cb2d7b4a2a16041bc7f`, tree `bf8f0c24dc1883c2a96dff7a4bb16c28ac834450`.
- [Formal Actions run 34190735376](https://github.com/vibe-coding-era/goal-teams/actions/runs/34190735376), attempt 1, passed 589 Current tests and fresh separate-process release security review (I1/correlated, not external independence). S2 built one exact four-asset set; integrity and repository boundary checks passed separately. Medium S3 was not required and invoked zero processes.
- The independent S4 successor published and read back all four assets, then updated the authorized local installation and verified 361 package files and 24 agent files. S4 outcome receipt `d9d13b1195c8d016f41e95fde3d80db5c1e88cd6b3d8b321ecf8ef0fbd74c6d9` records local/correlated evidence, not external attestation.
- This post-publication entry does not rewrite the immutable assets or move the release tag. The candidate-time entries below remain historical. Host send interception and final-frame verification remain unavailable; the release does not implement every item of the V2.68 PRD or establish business acceptance.

## V2.68 Development Candidate

- 将已验证的输出改进接入正式 Current 默认入口：所有 final 经过 typed output gateway 与六字段外层校验/序列化；错误返回受控 blocked/replan 正文。
- 新增轻量文档 prepare → 实际写入 → 真实复核 → observe → render 交付记录，产物交付与输出校验、开发准入分别报告。
- 修复任务全部完成时的空看板，保留真实统计和链接并显示完成提示；进行中任务行及 V2.67 dashboard 输入保持兼容。
- 产品 V2.68 继续复用 exact V2.65 Graph Execution 和 exact V2.67 dashboard 依赖；未实现完整 V2.68 PRD 的其它能力。Host 发送拦截与最终 frame 验证仍 unavailable。
- 提交、Release、安装和 readback 以各自实际回执为准；本条候选说明本身不证明已发布。

## V2.67 Development Candidate — 2026-08-26

- Added a compact, digest-bound execution dashboard inside the existing six-field user-visible Envelope: active/remaining parent and subtask rows, fact-bound parallel Subagent markers, linked Context / Knowledge / Tools, and a four-line P/D/C/A LOOP with round estimates.
- Added a strict V2.67 dashboard schema and deterministic renderer; preview/example data cannot claim nonzero execution progress or current Evidence.
- Kept the V2.65 Graph Execution contract as the unchanged execution layer instead of duplicating runtime code; V2.67 formal Release, installation, external effects, and business validation remain `not_run`.

## V2.65 Development Candidate — 2026-08-22

- Added a typed, canonically hashed Graph contract with node/edge identities, predecessor constraints, authority declarations, Host capability negotiation, and digest-bound Member Packets.
- Added a local SQLite-backed Graph Runtime development slice with durable attempts, checkpoints, compare-and-swap transitions, confirmed idempotency records, recovery projection, and resumable human gates through an explicit Host adapter boundary.
- Added deterministic Context Bundles and append-only proactive evolution reviews for end-of-LOOP and problem-detected reflection across prompt, context, Skill, graph, Harness, and workflow dimensions.
- Activated the V2.65 Current generation with 9 routes and 125 rules; the default package closes over 347 paths while V2.63 remains an exact published predecessor outside the Current execution denominator.
- Passed the 661-case Current Development denominator (`tests/v250` 492 + `tests/v265` 169), strict compilation of all nine V2.65 schemas, immutable V2.63 lifecycle replay fixtures, and a local terminated-process recovery observation that did not repeat a confirmed idempotency key.
- This is a Current Development candidate: GitHub merge, S0-S4, formal Release, installation, real Host/Provider validation, real external side effects, and business execution remain `not_run` until their separate evidence chains close.

## V2.63 — 2026-08-12

- Added deterministic discovery selection, immutable per-session generation snapshots, trusted-fact route derivation, deterministic prompt artifacts, and host observation receipts to govern runtime drift without overstating Provider assembly proof.
- Added Consumer Gate, immutable TaskExactSet/DAG compilation, explicit budgets and exit conditions, independent external blockers, bounded audit-finding admission, Git-derived change receipts, and orthogonal completion projections so time and quality bounds are calculable and auditable.
- Bound input, code, tests, results, authorization, route, scope, and phase exact-sets through digest/receipt chains; preserved honest `BLOCKED` and separated engineering, runtime, business, release, and installation states.
- Removed the fixed user-visible runtime identity fingerprint. Runtime identity remains machine Evidence and is explained only when explicitly requested or needed for drift diagnosis.
- Migrated the product-bound Current candidate, compatibility projection, checks, package closure, and release profile to V2.63 while retaining core policy V2.5, Legacy schema V2.3, published predecessor V2.62, and unchanged human-owned root READMEs.

## V2.62 — 2026-08-08

- Added the OKF Document Graph as a standards-aligned, in-memory RDF 1.1 projection over tracked OKF and Markdown documents, with stable IRIs, revision-aware claims, evidence traceability, native lookup, and deterministic graph-input manifest digests.
- Kept Markdown as the SSOT with **No database**, no cache, no network access, and no document mutation; Current and explicit Replay graph loading remain isolated.
- Made graph quality **Observe-only**: ambiguity, dangling links, and other quality findings are recorded truthfully and do not create a new quality Gate; SPARQL and SHACL engine capability states remain `not_implemented`.
- Published product V2.62 with the annotated `v2.62` tag, fixed four-asset set, exact remote readback, and canonical local installation while retaining core policy V2.5, Execution assets v2.50, V2.6 as the predecessor, and unchanged Legacy Replay.

## V2.6 — 2026-08-07

- Added a typed, fail-closed compatibility graph for `Portable Core -> Host -> Provider -> Model -> optional Bridge -> Role -> Task` while retaining the V2.5 portable core and V2.3 Legacy data schema.
- Added explicit Codex and Claude Code host overlays, DeepSeek and Kimi K3 route metadata, deterministic resolution, and runtime-binding receipt validation without claiming unobserved provider runtime success.
- Added canonical roles plus deterministic thin Codex TOML and Claude Code Markdown projections with missing, drift, and managed-orphan checks.
- Migrated the Current generation, default package closure, active release profile, and compatible V2.5 execution layer to the V2.6 product identity; Legacy Replay remains explicit and root READMEs remain human-maintained.

## V2.52 — 2026-08-07

- Replaced the limited source-available terms with the OSI-approved MIT License, granting unrestricted use, copying, modification, distribution, sublicensing, and sale subject to the license notice.
- Made the first round of every execution LOOP establish the TaskList, assign Owners/Validators, and run an independent environment preflight before implementation.
- Added `goal_release_engineer` as a built-in dual-mode member: lightweight first-round `environment_preflight` plus the existing isolated Release workflow.
- Required medium/large or user-requested development checks to reuse a current compatible environment, or create a repository-contained `codex/develop-v<major.minor>` branch; Small keeps the branch exception.
- Completed the bilingual member introductions with Security, Performance, Refactor, SQA, and Release Engineer.

### V2.51

- Added the Goal Teams Limited Source-Available License 1.0: public source may be read for personal evaluation, while any use, copying, modification, distribution, deployment, derivative work, or commercial/non-commercial exploitation requires the author's prior written permission.
- Required every visible LOOP progress report to include the current iteration and total iterations.
- Required final output to provide evidence-based LOOP improvement suggestions, covering applicable Skill, context, materials, Harness, or process improvements in addition to the Benchmark report.
- Kept the V2.50 execution protocol, schemas, error-code family, and `scripts/v250/` paths as the compatible implementation layer for this small declarative release.

### V2.50

- Carried the V2.49 simplification work into a fresh Current generation and release identity because the protected `v2.49` tag and its unpublished Draft Release could not be moved or reused safely.
- Hardened S4 Draft Release discovery, full pagination, stable asset identity comparison, terminal drift evidence, and reconciliation without replaying external side effects.
- Bound the fresh runtime and formal release predecessor to the actually published and installed V2.48 identity; V2.49 release receipts remain historical and cannot satisfy V2.50 gates.

### V2.49

- Historical partial release only: the protected tag and unpublished Draft Release are retained as evidence and were never promoted or installed.
- Added a digest-bound Current generation, functional-rule templates, explicit Legacy Replay, and zero-Legacy route/package closure checks.
- Added the immutable four-object test chain and separated Development from Release denominators; Medium/Large development now blocks only on TDD and affected-scope checks.
- Moved full regression and the independent security review to final Release readiness, retired S2 double-build/security gates, and made S3 Large-Release-only.
- Added one-time project-start authorization, SSH-only GitHub Git transport, simplified S4 recovery/readback, fresh runtime transition receipts, and the exact six-field output envelope.

### V2.48

- Added an independent Agent Product Manager plus a shared, progressive Agent-development contract for product, frontend, backend, and testing roles.
- Added source-backed capability materials for Codex, Claude Cowork, QoderWork, WorkBuddy, and TRAE/TraeWork, with documented, unknown, and non-inferable boundaries kept separate.
- Added three composable product patterns, five-layer architecture patterns, a V2.48 machine manifest/schema/validator, and regression coverage. V2.47 flow/document/runtime contracts remain replay-compatible while V2.46 remains the only public release engine.

### V2.47

- Added a machine-readable flow test strategy and executable P0 smoke denominator: small uses incremental plus smoke only, medium waits for the user's final-regression choice, and large runs a fresh full denominator without reusing earlier results.
- Added append-only incremental document SSOT, stable-prefix/dynamic-tail ordering, and deterministic final projection without claiming provider cache improvement when usage telemetry is unavailable.
- Reduced user-visible execution updates to task, member, progress, result, Benchmark, and next LOOP/task; out-of-scope discoveries remain proposals until the requested work is complete.
- Added 32 official source records, one portable common contract, eight runtime overlays, a strict selector, schema, and validator for Codex, Claude Code, Cursor, Kimi Code, GLM, Qwen Code, Qoder, and TRAE. Runtime-complete adapter claims remain unverified.

### V2.45

- Added a standalone, progressively loaded Release Engineer for Java, Rust, Go, Python, Node.js, five environment classes, applications, containers, WeChat Mini Programs, and GitHub Skill publication without adding it to the main Goal Teams route.
- Added fixed typed release-evidence requirements, repository-external Ed25519 plan/execution approvals, least-privilege and database-safety attestations, script-closure checks, and fail-closed rejection of destructive database operations.
- Added versioned script bundles, exact digest confirmation for reuse, backup/restore/rollback, benchmark baselines, post-release verification, and shared V2.36 secret redaction.
- Promoted the release-engine profile to V2.45 while retaining V2.44 testing contracts and V2.44/V2.40 release profiles as replay-only compatibility surfaces.

### V2.44

- Added machine-checkable integration test plans, typed API/E2E cases, and run-result contracts with risk denominators, path/digest/discovery identity, attempts, observed assertions, cleanup, and replay.
- Upgraded API/E2E designers, runners, QA, and Reviewer to share one fail-closed testing handoff contract without treating retries, skipped execution, or prose as success.
- Added an append-only issue ledger, seven-dimension 100-point capability manifest, and a deterministic real-behavior API/E2E benchmark with seeded defects.
- Replaced V2.40-only release identity constants with Git-tracked release-engine profiles bound to CP00, operation intents, CP05 approval, CP10 public-scan sealing, GitHub metadata, workflow, and close validation.
- Kept V2.40 as a replay-only protocol/error-code family with explicit external-write rejection, while V2.44 retains the sealed source-commit snapshot and strict four-column file manifest.
- Retained V2.43 engineering metrics and V2.35 test-case inputs as compatibility surfaces, and moved the V2.43 self-release Profile to replay-only routing.

### V2.43

- Added one manifest-driven calculator for 12 engineering metrics across task completion and Benchmark records: FPAR, LCC, HER, SAR, CPAC, DER, RRR, CWR, SDI, RFR, ARCR, and MRT.
- Added append-only JSONL metric events, a V2.43 summary schema, comparable-history aggregation, manifest-bytes identity, correction events, and fail-closed availability states so uncollected data is never reported as zero.
- Added self-contained Google OKF engineering-metrics reports with current, previous, and recent values plus the complete algorithms, Evidence references, coverage, observation windows, and privacy notes.
- Added Benchmark record/summary integration while keeping `quality_pass_rate` distinct from FPAR, and retained V2.42 as a replay-only self-release Profile.

### V2.40

- Added a single controlled release-identity block to both root READMEs so the public repository surface points to `v2.40` and `release/current` without replacing the user-authored body.
- Added the current `goal-teams-self-release-v2.40` Profile and moved V2.39/V2.38 Profiles to replay-only routing while preserving their cache schemas, fixtures, and historical semantics.
- Added development/candidate version projections derived from `VERSION`; stable identity remains an independent live-audit responsibility.
- Added the CP00–CP18 recoverable release lifecycle, exact operation semantics, remote promotion lock, exact main compare-and-swap before publish, immutable tag/Release gates, four-asset verification, and published-asset installation identity.
- Made release telemetry honest by reporting Tokens consumed and Cache hit rate as `未获取到` / `Unavailable` whenever trusted host usage Evidence is absent.

### V2.39

- Added a fail-closed Cache Evidence contract with trusted host capability, ordered request manifest, registered configuration attestation, raw-to-normalized receipts, and an authorization-gated live probe executor.
- Split cache reporting into four orthogonal states: structural validation `passed`, host integration `unavailable`, live probe `not_authorized`, and request hit rate `unavailable`; the release claim is limited to `structural_governance`.
- Added deterministic Google OKF A/B/C classification, safe frontmatter parsing, tracked/changed/bundle/manifest/package-tree checks, and package completeness/identity binding.
- Added the current `goal-teams-self-release-v2.39` Profile and switched current routes to it while preserving the V2.38 Profile, schemas, compilers, observer reports, fixtures, and artifacts for read-only replay.
- Kept live provider and request-hit-rate claims fail-closed because no trusted host observation or live provider probe was authorized for this release.

### V2.38

- Added `references/prompt-cache-manifest.json` as the ordered route-static and byte-budget machine SSOT, including startup headroom enforcement.
- Added order-sensitive `prefix_manifest_sha256`, byte-sensitive `route_static_digest`, host ordered-manifest digest helpers, and explicit unavailable/partial semantics when the final request is not observable.
- Added fail-closed versioned observer aggregation and identity grouping; invalid, legacy, ambiguous, or unattested config inputs cannot produce a supported cache conclusion, and request hit rate remains unavailable.
- Added a plan-only first-seen/repeat probe compiler (`live_ab_status=unavailable`); no live provider A/B records are claimed.
- Added a single-source subagent common-prefix expander/validator and canonical Member Goal Packet compiler with stable, dynamic, combined, and legacy migration digests.
- Documented the platform boundary: Goal Teams can observe reported cache usage but cannot force, clear, or guarantee a provider prompt cache.

### V2.37

- Added progressive member indexes and deterministic index/document-budget gates.
- Split the large runtime reference into routed parts and kept startup context within 12 KiB.
- Moved historical/process knowledge, the complete PRD/architecture, integration catalog, and private release evidence to local-only `docs/`.
- Reduced the install package to current runtime material while retaining legacy schemas and runtime identifiers only for compatibility.
- Added static adapter assessments for Claude Code, Trae, Qoder, WorkBuddy, QoderWork, and Cursor without claiming runtime verification.

### V2.36

- Separated the product version (`V2.36`), general core policy (`V2.5` / `goal-teams-core-v2.5`), and legacy machine-data schema (`V2.3`) so startup identity, execution policy, and persisted data are no longer conflated.
- Moved the 52 assertions, iterations 9/11, four-dimension scoring, candidate reset, and public archive into the repository-only `goal-teams-self-release-v2.36` Profile; ordinary projects no longer inherit this self-release workflow as global invariants.
- Derived gates from the bound product/core versions, task route facts, and execution class. A missing `state_gate_profile` cannot bypass gates, and a supplied value must match the derived gate.
- Restored risk- and size-based Lite/Standard execution, with explicit escalation for cross-module, high-risk, release, security, payment/authentication, and reference-driven UI work.
- Unified secret redaction across runtime and archive paths, including YAML/TOML key-value forms, database URIs, `.netrc`, Authorization/Cookie forms, cloud credentials, collaboration-tool tokens, and fail-closed non-text public copies.
- Added protected Git tree snapshots that auto-cover every tracked modification/deletion and non-ignored untracked file without a caller path list, plus host-attested Agent identity for independent validation claims.
- Added host-signed route receipts, persistent repository-external replay state, process-private trust-key FDs, and a V2.36 acceptance binding that locks Audit, Review, Harness, current Evidence, ledger, checkpoint, traceability, target fingerprint, and snapshot baseline to one completion decision.
- Added bilingual V2.36 pre-audit release summaries and synchronized package/version checks for the three-layer version model and the two policy profiles.

### V2.35

- Added four read-only, proposal-only specialist roles: `goal_security`, `goal_performance`, `goal_refactor`, and `goal_sqa`. Specialists cannot implement, dispatch, spawn nested teams, mutate central state, or self-verify; Goal Lead dispatches independent implementation and validation runs.
- Added deterministic `project_size=large|medium|small` and `work_type=feature|bugfix` routing with safety, risk, UI, and explicit-specialist overrides. Architecture, Environment, independent tests, and Evidence remain required; UI always requires E2E, and BugFix always requires TDD plus integration testing.
- Added the V2.35 test-case contract and canonical validator for non-empty `input`, `processing`, `expected_output`, and executable `assertions`; exit/status-only success cannot substitute for business-output assertions.
- Added explicit, hash-bound V2.35 version descriptors for state, recovery, closure, snapshot, and public archives while retaining byte-compatible V2.34 behavior when no descriptor is supplied. Invalid, stale, mismatched, traversal, or symlink bindings fail before mutation.
- Added strict pre-implementation and release/audit gates: delta contract review, accepted Architecture, ready Environment, independent RED tests, implementation, independent GREEN/full regression, release, remote/local Evidence, then graph-external Completion Audit.
- Added V2.35 schemas, negative fixtures, release-summary documents, package-selection denial of local roadmap/process bundles, and startup/routed-role context budgets.

### V2.34

- Added a contract-first `Gather -> Reason -> Act -> Verify -> Repeat` LOOP with durable four-file state (`feature_list.json`, `progress.md`, `contract.md`, `log.md`), revision/CAS checks, a journal, marker-last commits, reconciliation, and session-scoped crash recovery.
- Added the ordered implementation gates `contract frozen -> architecture accepted -> development environment ready -> independent tests written -> implementation`, with exact-hash Evidence and independent validation; no background daemon is implied.
- Added a constrained iteration-9 reset that can quarantine only a preauthorized disposable candidate, never repository or user data, and a fail-closed iteration-11 delivery gate with no iteration 12.
- Added four independently evidenced quality dimensions (`design`, `originality`, `craft`, `functionality`) scored by four binary 0.25 rubric items; scores supplement rather than replace tests or Evidence.
- Added canonical `GTLOG` intent/judgment frames, five divergence classes, prompt-fix lifecycle states (`proposed`, `applied`, `verified`, `reverted`) with regression plus holdout proof, and deterministic moving-bottleneck selection.
- Added audited public-document archiving under `docs/archive/V2.34/<delivery_id>/`, with invocation-trace sanitization separated from private ledger/evidence/review/audit provenance.

### V2.3

- Breaking contract: replaced legacy handoff/loop completion labels with orthogonal `task_state`, `check_state`, `run_outcome`, `loop_decision`, and `audit_state`; unknown core enums fail closed.
- Breaking persistence: append-only ledger events are the execution SSOT; members submit revision-bound events/patches and only the reducer writes `TaskList.md`. Lowercase `tasklist.md` is read-only V2.2 migration input.
- Separated `agent_type`, `agent_run_id`, `member_id`, localized `display_name`, and `transport_handle`; author/reviewer independence is bound to concrete run identity and artifact hash.
- Added versioned schema/source lock, task-local CAS, deterministic replay/projection, atomic checkpoints, strict Evidence/Traceability/Dual Review/Completion Audit, stable JSON envelopes, and negative mutation gates.
- Added Lite/Standard/Full/Regulated routing, capability manifests and non-escalating fallback, a 12 KiB base-context gate, secret redaction/trust boundaries, and environment-aware pixel validation.
- Added typed V2.2 `scan -> plan -> apply -> verify -> rollback` migration, manifest-driven atomic install/update/rollback/uninstall, dirty-source provenance, Linux/macOS CI, canonical success/blocked/failure/recovery replay, and fresh behavior scenarios.
- Capability boundary: Goal Teams remains a session-scoped orchestration protocol, not a persistent background runner, CI/CD service, or production approval system. OpenSpec and Superpowers coexist without claiming a V2.3 adapter.
- Release boundary: technical RC gates are independently testable; public GA remains fail-closed until the repository owner records a License or internal-sharing decision.

- Tightened V2.3 maintenance rules: startup text now says `规划、执行和交付`, Plan history input accepts `无` or `2`, and completion rules are a checklist.
- Added hard validation that all `SKILL.md` version strings match `VERSION`, and kept progressive-loading path existence checks in `./scripts/check.sh`.
- Moved OKF spec loading out of the all-tasks route and moved `scripts/harness/pixel-diff.py` from the UI route into `references/rules-ui.md` as an executable tool.
- Added Budget/round-limit failure degradation and explicit rule-conflict precedence.
- Restored `Plan Mode` / `先规划` / `只规划` / `需求卡片` trigger terms in `SKILL.md` description and added a routing fixture regression check.
- Bumped current Skill version to `V2.3`.
- Slimmed `SKILL.md` into a trigger-oriented entrypoint with invariants, planning checks, failure-degradation summary, and a progressive-loading router.
- Added conditional rule references: `references/invariants.md`, `references/compat.md`, `references/rules-ui.md`, `references/rules-testing.md`, and `references/rules-loop.md`.
- Extended validation to enforce compact Skill description length, progressive-loading path existence, required conditional references, and repeated-rule limits in `SKILL.md`.
- Added `scripts/check-routing-fixtures.py` for 3 route fixtures: backend CLI, UI replica, and long-running Lead LOOP.
- Added file-level rule validation so missing key rules report the exact owning file instead of only a combined-doc failure.
- Slimmed README/README.en rule sections into entrypoint indexes and centralized version narrative in `references/compat.md`.
- Bumped current Skill version to `V2.1`.
- Added `prompts/lead/loop.md` as the Lead LOOP Protocol with Loop Decision, Loop Gate, integration audit, state snapshot, auto-continuation, stop-boundary, and resume-state rules.
- Added `loop_decision_record` to the handoff artifact SSOT and propagated Lead LOOP fields into Lead planning, dispatch, audit, completion, Member Goal Packet, and Teams plan templates.
- Added `GT-BENCH-004` to benchmark Lead LOOP behavior across `baseline`, `goal-teams-v2.02`, and `goal-teams-v2.1-loop` modes.
- Bumped current Skill version to `V2.02`.
- Added `RULES.md` as the Response Contract for Goal Lead and member responses: execute first, report verified facts, avoid unverified success claims, distinguish observation from conclusion, and minimize unrelated commentary.
- Bumped current Skill version to `V2.01` and startup identity to `我是 Goal Teams Leader V2.01，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，并使用 Harness + SPEC 做为过程与结果产物的约束：`.
- Updated the Plan-mode historical-context prompt to use the `没有请回复“2”` shortcut and made the core Chinese output rule table-first.
- Bumped current Skill version to `V2.0` and startup identity to `我是 Goal Teams Leader V2.0，我会帮你完成以下工作：`.
- Required all SSOT outputs to live under output-directory version subdirectories such as `GoalTeamsWork-<project_version>/versions/<artifact_version>/`.
- Required each project to create `TaskList.md` before implementation or test execution, with feature-level rows for requirement spec, PRD, page spec, HTML prototype, frontend/backend architecture, backend TDD, backend implementation, API integration testing, E2E, BugFix, and test report.
- Added independent TDD/API/E2E subagents: `goal_unit_test_designer`, `goal_unit_test_runner`, `goal_api_integration_test_designer`, `goal_api_integration_test_runner`, `goal_e2e_test_designer`, and `goal_e2e_test_runner`.
- Required backend development to generate Backend Architecture Design before code, then follow TDD with independent unit-test authoring and execution.
- Required API integration test scripts to be generated after architecture design, defaulting to Python + pytest unless the project specifies another stack, and executed only after unit tests pass.
- Required frontend E2E tests to be generated after frontend development by a separate subagent and executed by another independent subagent.
- Bumped current Skill version to `V1.97` and startup identity to `我是 Goal Teams Leader V1.97，我会帮你完成以下工作：`.
- Added local bilingual Google OKF guidance in `references/google-okf-bilingual-spec.md` and made generated Markdown outputs default to OKF frontmatter with a required `type`.
- Changed the default output directory to `GoalTeamsWork-<project_version>/` when the user does not specify a directory.
- Added `prompts/packets/memory.md` and required output-directory `memory.md` to record important user settings, configuration, component library decisions, and context summaries from old to new with author `GoalTeams`.
- Added `prompts/packets/html-prototype-mock.md` and required HTML Prototype MOCK outputs to embed OKF metadata plus component library information.
- Extended page-spec-card, frontend, QA, reviewer, completion-auditor, runtime, README, and validation rules so page prototypes must clarify component library name/version/source or record a blocking question before generation.
- Added `prompts/packets/page-spec-card.md` for PRD-after page specification before HTML Prototype or frontend implementation.
- Added `references/ui-visual-contract-protocol.md` to prevent UI replica leaks from full-page-only pixel diff, visual overlays, missing component assertions, and missing dialog/form interaction states.
- Required frontend, QA, reviewer, and completion-auditor workflows to enforce page specs, component-level visual contracts, locked/unlocked screenshots, local crop/geometric assertions, and visual-risk coverage.
- Added `prompts/packets/handoff-artifacts.md` as the SSOT for Goal Teams handoff artifacts, Owner subagent, validator subagent, and status fields.
- Required every handoff artifact to be written into `tasklist.md` during execution with `handoff_status`, `independent_check_status`, Harness, evidence path, and blocker/defer reason.
- Updated member workflows, templates, runtime examples, README docs, subagent configs, and validation checks to enforce independent checks for every deliverable.
- Bumped current Skill version to `V1.96` and startup identity to `我是 Goal Teams Leader V1.96，我会帮你完成以下工作：`.
- Added user stories and functional acceptance criteria as required fields in requirement cards, Requirement Specification Cards, and PRD handoff.
- Required functional acceptance criteria to flow into tasklist, Harness, test plan, and acceptance evidence.
- Bumped current Skill version to `V1.95` and startup identity to `我是 Goal Teams Leader V1.95，我会帮你完成以下工作：`.
- Added Plan Mode `需求卡片` as a required pre-SPEC concise plan covering core goal, key functions, boundaries, constraints, and risks.
- Added `prompts/lead/requirement-card.md`, `prompts/packets/requirement-card.md`, and the mini-goal-run `spec/requirement-card.md` example.
- Bumped current Skill version to `V1.94` and startup identity to `我是 Goal Teams Leader V1.94，我会帮你完成以下工作：`.
- Added V1.94 member packages under `prompts/members/<role>/` with `prompt.md`, `template.md`, `workflow.md`, and `scripts.md`.
- Added LLM + script dual-review protocol plus artifact comparison and dual-review validation scripts.
- Slimmed `SKILL.md` into a compact core-question and progressive-loading entrypoint.
- Added role prompt directories under `prompts/lead/`, `prompts/members/`, and `prompts/packets/`.
- Moved real scripts into `scripts/checks/`, `scripts/harness/`, `scripts/benchmark/`, and `scripts/install/` while preserving root compatibility wrappers.
- Bumped current Skill version to `V1.92` and startup identity to `我是 Goal Teams Leader V1.92，我会帮你完成以下工作：`.
- Added V1.92 scripted tooling: local install, version sync, agent-name checks, Harness contract validation, pixel diff, and benchmark package validation.
- Added dispatch, Budget Gate, Conflict Policy, UI E2E/pixel protocol, and evidence-insufficiency rules.
- Added `GT-BENCH-003` for UI E2E, replica pixel comparison, and insufficient-evidence rejection.
- Bumped current Skill version to `V1.91` and startup identity to `我是 Goal Teams Leader V1.91，我会帮你完成以下工作：`.
- Required Goal Teams to prefer custom `goal_*` subagents and keep Chinese `member_id` / `display_name` in user-visible records even when the runtime or right sidebar returns English transport handles such as `Reviewer C`.
- Required E2E Harness evidence for every UI-level task, and screenshot-based pixel-level comparison evidence for replica/recreation UI tasks.
- Bumped current Skill version to `V1.9` and startup identity to `我是 Goal Teams Leader V1.9，我会帮你完成以下工作：`.
- Added V1.8 machine-readable automation protocol reference with `harness.yaml`, `evidence.jsonl`, `pipeline-state.json`, `failure_report`, and `approval_gate` templates.
- Added V1.9 production pipeline reference for `Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback`, including Release Gate and safety gate boundaries.
- Added mini-goal-run static samples for automation protocol, evidence ledger, and pipeline gates.
- Added `GT-BENCH-002` benchmark templates for production-flow gate packages, evidence completeness, auto-continuation, and safety boundaries.
- Extended `scripts/validate.py` to check V1.9, V1.8/V1.9 references, mini machine-readable samples, and `GT-BENCH-002`.
- Bumped current Skill version to `V1.7` and startup identity to `我是 Goal Teams Leader V1.7，我会帮你完成以下工作：`.
- Added V1.5 Harness and Loop rules: `SPEC` defines completion, `Harness Contract` defines verification, evidence is required before done, and Goal Teams now documents member, Lead, and Skill Improvement loops.
- Added V1.6 mini Harness replay artifacts under `examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/` with `setup -> run -> checks -> report`.
- Added V1.7 `benchmarks/` templates, including `GT-BENCH-001` task, manual harness, scoring rubric, and expected artifacts for comparing baseline vs Goal Teams.
- Extended `scripts/validate.py` to check V1.7, Harness example files, and benchmark templates.
- Bumped current Skill version to `V1.4` and startup identity to `我是 Goal Teams Leader V1.4，我会帮你完成以下工作：`.
- Added a Plan Mode startup clarification asking whether the user has historical documents, prior experience, or reference material to provide before planning.
- Added direct-execution trigger wording such as `直接执行`, `不用确认`, and `跳过确认`; the lead still shows the `Teams 规划表` as an execution record, then proceeds without waiting for the initial confirmation unless a safety gate applies.
- Added numbered Plan options so users can reply with simple choices like `1`, `2`, or `3`.
- Added repository-level maintenance guidance in `AGENTS.md`.
- Added `scripts/check.sh` and `scripts/validate.py` for package validation.
- Added `examples/mini-goal-run/` as a minimal Goal Teams output example.
- Documented validation and example workflows in both READMEs.
- Updated runtime subagent id, `member_id`, and display names to Chinese role + concrete task names, such as `后端-WIKI 列表后端开发`; when a user assigns a skill, the skill name is used, such as `browser-WIKI 列表页面验证`.
- Kept loadable technical subagent names such as `goal_backend` only in `skill_or_subagent`.
- Required task workflow safety fields in planning tables: serial/parallel workflow and predecessor tasks.
- Required final status tables to include `资源消耗（用户 / tokens / 费用）` for each task or subagent, using `未提供` when runtime usage is unavailable.
- Consolidated Chinese-output behavior into one core model prompt.
- Required a `Teams 规划表` for user confirmation before worker execution.
- Updated the `Teams 规划表` display to four merged columns while preserving the same planning fields.
- Added `goal_completion_auditor` for post-completion unfinished-work audits and automatic continuation cycles inside the confirmed scope.
- Kept License selection pending for the repository owner.
