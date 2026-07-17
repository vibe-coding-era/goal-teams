---
type: Release Protocol
title: Goal Teams 发布打包规范
description: 定义可复现发行目录、资产校验、GitHub Release 与本地边界门禁。
tags: [goal-teams, release, packaging, validation]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams 发布打包规范

## Objective

任何 GitHub Release 都必须先在本地 `release/versions/<VERSION>/` 形成完整、可复现、已校验的发行目录；未经本地门禁通过，不得创建 tag 或上传发行资产。

## Key Results

1. 冻结唯一 `VERSION`、Git ref 与 commit，发行内容只从该 commit 和 `scripts/install/package-manifest.txt` 生成。`file`/`prefix` 只选择 Git-tracked payload；`generated references/okf-conformance-manifest.json` 是唯一 builder-generated required asset，源 Git 禁止跟踪占位文件。
2. 唯一公开发行入口是 `"$PYTHON_BIN" scripts/release/release.py <command> --input <ignored-json>`；输入必须绑定 exact 40 位 lowercase commit、state CAS、operation intent、expected-before 与逐操作授权。`build-release.py`、`validate-release.py`、`publish-github-release.sh` 和 installer 的 release-bundle 模式只允许由该入口作为 internal adapter 调用；README 中普通源码安装命令不属于发行提升。
3. builder 先复制冻结 payload，再以 commit、Git tree、package manifest、policy、checker 和 payload tree 生成 canonical `references/okf-conformance-manifest.json`，立即执行 `scripts/checks/check-okf.py --package-tree <staged-root>`；随后才把该文件纳入完整 tree、`_files.sha256`、tarball 与 `SHA256SUMS`。发行目录必须包含纯发行文件、`_release.json`、`_files.sha256`、`_artifacts/goal-teams-<VERSION>.tar.gz` 与 `_artifacts/SHA256SUMS`。
4. `docs/`、过程包、根 PRD、输出物和本地状态不得进入发行包；历史与过程资料只能归档到根 `docs/archive/releases/<VERSION>/`。
   `develops/` 以及仓库父目录中的任何 Goal Teams 版本副本同样禁止进入 Git、安装包或发行资产；开发 worktree 只能位于根 `develops/`。
5. internal validator 必须从 frozen commit 独立重建 canonical OKF manifest、逐字节比较、重放 `--package-tree` 并验证它是唯一额外资产；CI 的两次隔离构建分别使用 `--release-root ... --isolated-no-docs-archive` 验证，本地 canonical 模式仍强制检查 `docs/archive/releases/<VERSION>/`。任何验证失败都不得进入 Draft。
6. 发布脚本必须校验 tag 指向、拒绝覆盖既有 GitHub Release，并在上传后重新下载压缩包；下载的 `SHA256SUMS` 必须与本地冻结凭证逐字节一致，再核对资产 SHA-256。
7. 任一门禁失败即停止发布；不得以人工口头确认替代脚本证据。

## Python 3.11+ 门禁

不假设系统 `python3` 可用或指向兼容版本。发行操作者必须显式设置 `PYTHON` 为 Python 3.11+ 可执行文件，所有公开命令复用同一个 `PYTHON_BIN`：

```bash
PYTHON_BIN="${PYTHON:?请先将 PYTHON 设为 Python 3.11+ 可执行文件的绝对路径}"
"$PYTHON_BIN" -c 'import sys, tomllib; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ required")'
```

## Published installer 的原子变更边界

从 GitHub Release 资产执行的真实安装必须把 passwd database 返回的 login home 作为
唯一根权限；`HOME`、`CODEX_HOME`、目标 owner/mode、无 symlink 祖先以及全程 held
dirfd 任一不一致都在首次目标写入前 fail closed。所有 source→quarantine、
quarantine→destination 和 rollback restore 只允许使用内核原子 no-replace primitive：
Darwin 为 `renameatx_np(RENAME_EXCL)`，Linux 为
`renameat2(RENAME_NOREPLACE)`。目标已存在、不支持该 primitive、跨文件系统、未知 errno
或 restore 冲突都必须失败；禁止退回“先检查不存在、再 `rename`/`replace`”的实现，
也禁止在恢复时覆盖当前 source/destination。

`remove_path`、`unlink_path`、原子 JSON/bytes 写入中的旧对象与失败临时文件不得执行
name-based `unlink`、`rmtree` 或 `rmdir`。安装器只把经过 inode 校验的对象连同 0700
mutation capsule 原子移入
`~/.codex/state/goal-teams/quarantine/`；该目录与 `preserved/` 一样必须由 passwd-home
能力链创建、校验并保持 dirfd。若 post-check 发现同一父目录的已知 sibling 被换入，
只用 no-replace 尽力恢复其原名；任何冲突对象保留在 tombstone 中并失败，绝不覆盖或
自动删除。安装报告的 `retained_mutation_quarantines` 必须记录 operation、原相对路径、
device/inode、tombstone ref 与状态。自动安装、rollback、uninstall 和后续发行均不得
清理 tombstone；容量检查和离线人工清理属于显式运维动作，必须在无 installer 进程且
用户单独授权时进行。终态安装报告不复用通用 replace 流程：先创建并持久化中央
quarantine capsule/receipt，在其 held fd 内以 `O_EXCL` 写完 `entry`、完成
fsync/metadata 校验，再以原子 no-replace 提交到最终 reports dirfd。目标已存在或在提交时
被并发占用就直接失败，禁止覆盖旧报告；写入中断或提交冲突时 partial/full pending 只保留
在该中央 capsule 中。成功报告必须收录它自己的 terminal-report capsule receipt，因而无论
成功或失败都不会让 partial JSON 出现在终态路径，也不会产生 quarantine SSOT 之外的临时文件。

## CP00–CP18 唯一执行顺序

| Checkpoint | 固定语义 | 公开命令 |
| --- | --- | --- |
| CP00 | scope/SPEC/route/owner/locked-scope 冻结；必须从 `develops/v2.40` candidate worktree 执行 | `start` |
| CP01 | 校验固定的 pre-V2.40 recovery bundle；legacy root 尚在时做 live readback，已恢复为 clean main 时改验固定 stash attestation；全程不修改 stash、ref 或 worktree registry | `promote` |
| CP02 | canonical/candidate/topology 验证 | `promote` |
| CP03 | GitHub authority readback → immutable release enable → ruleset capability verify | `promote` |
| CP04 | development identity | `promote` |
| CP05 | promotion contract 验证 → workflow approval | `promote` |
| CP06 | static gates | `promote` |
| CP07 | quality gates | `promote` |
| CP08 | candidate identity → RC commit freeze | `promote` |
| CP09 | primary build → reproducibility build | `prepare` |
| CP10 | isolated-build equality → asset validation → complete public scan → rescan/snapshot seal | `prepare` |
| CP11 | local release-bundle rehearsal | `promote` |
| CP12 | exact candidate push | `promote` |
| CP13 | candidate exact-SHA CI | `promote` |
| CP14 | authority revalidate → reusable permanent main ruleset create/exact-adopt → immutable verify → permanent tag ruleset → promotion lease | `promote` |
| CP15 | annotated tag push | `promote` |
| CP16 | Draft create/recover → fixed four-asset upload → download verify → temporary remote-bundle rehearsal | `promote` |
| CP17 | 由 CP10/CP05/CP16 exact readback 内部生成 intent → exact main CAS → publish-last → published download → actual install → post-release CI → independent live audit；audit 不冻结尚未 finalization 的 SSOT tree | `promote` |
| CP18 | CP17 后外层 host finalization 最终 SSOT → permanent main protection exact reuse/final verification → canonical archive close；最终 archive/SSOT/Completion 边界在远端写入前后各重验一次 | `close` |

CP05 的 `ci_approval` 顶层必须记录 `release_actor_id`，并与 CP03 冻结的
`github_authority.actor_id` 完全一致；它是 CI 执行者身份，不得用独立
reviewer 的 `member_id` 或 `run_id` 代替。CP13 candidate CI、CP17
post-release CI 与最终 live audit 都必须同时回读 Actions run 的
`actor_id` 和 `triggering_actor_id`，二者均须与 `release_actor_id` 及
`github_authority.actor_id` 完全一致。`run_attempt > 1` 可以表示合法 rerun，
但实际触发 rerun 的 actor 不得变化；任一 actor 链漂移均按
`E_V240_CI_TRUST_BINDING` fail closed。

同一 approval 还必须绑定固定 workflow 的正整数 `workflow_id`、canonical source path
`.github/workflows/release-gate.yml` 与 candidate tree 中该文件的 blob SHA。`workflow_id`
只能从 `GET actions/workflows/release-gate.yml` 的 active metadata 取得；run 返回的原始
`path` 只允许 canonical path 本身或 GitHub 官方形态
`.github/workflows/release-gate.yml@main`。receipt 必须同时保留 raw path/ref 与 canonical
source path；`@v2.40`、`@refs/heads/main`、`@refs/tags/v2.40`、其他文件路径或 metadata
ID/path/state 漂移均为 trust conflict，不能把 raw `run.path` 当作可读取的 Git path。

required workflow 的 `check-ubuntu` 与 `check-macos` 都必须先在显式固定
`GOAL_TEAMS_INSTALL_VALIDATION=0` 的 step 中运行 `./scripts/check.sh`，再在同样固定为 `0` 的独立 step 中运行
`python3 scripts/checks/check-install-lifecycle.py`。前者覆盖当前平台的 native no-replace
primitive（Linux `renameat2(RENAME_NOREPLACE)` / Darwin `renameatx_np(RENAME_EXCL)`），后者覆盖
dirty/dry-run/install/update/failure/rollback/uninstall；任一 job 只跑前者都不构成完整 required gate。

installer 在 source、staging 与 post-switch 阶段运行 `scripts/check.sh` 时固定设置
`GOAL_TEAMS_INSTALL_VALIDATION=1`；这是受限的 package-validation profile，只执行安装包结构、
版本、OKF、prompt/cache、security fixture、Harness/Review self-test 与 benchmark 检查，禁止在
每个安装事务内递归重跑完整 V2.3 release suite 或 installer lifecycle。该 profile 的成功不能
作为 CP07、required CI 或 CP11 Evidence；顶层 `./scripts/check.sh` 必须在该变量未设置或显式为 `0` 时运行，
并由独立 installer-lifecycle step 与最终 release-tar CP11 rehearsal 补齐行为覆盖。任何把
package-validation profile 冒充完整 release gate 的 receipt 都必须 fail closed。
CP07 必须清除/拒绝外部 `GOAL_TEAMS_INSTALL_VALIDATION`；required workflow 的每个完整 gate step
必须把它显式覆盖为 `0`，不得依赖 ambient runner environment。receipt 必须声明
`quality_gate_profile=full_release_gate`、`installer_package_profile=false`。required
workflow 同时 provision Python 3.11 与 3.13，以 Python 3.11 运行顶层 gate，并设置
`GOAL_TEAMS_REQUIRE_CROSS_PYTHON=1`；找不到第二个受支持解释器必须失败，不能 skip 后继续发布。
CP07 必须在四条固定命令执行前后分别重验 live canonical candidate checkout；持久 receipt 只保存
`location=develops/v2.40`、branch、commit、clean digest，不保存宿主绝对路径。四条 stdout/stderr
摘要的 `receipt_trust_level` 固定为 `local_unattested`，不能自报 `host_attested`，也不构成执行
attestation；`authoritative_execution_proof` 必须固定指向绑定 exact candidate SHA 的
`CP13.candidate_ci` 及 `check-ubuntu`、`check-macos`、`release-asset-gate` 三个 required jobs。
因此任意本地可重算摘要都不能替代 CP13 与仓库外 host attestation。
顶层 `check.sh` 调用完整 `check-v23.py` 时也不得自行注入值 `1`；required workflow 必须显式注入
`GOAL_TEAMS_INSTALL_VALIDATION=0`；只有 installer 发起的嵌套 package validation 可以设置值 `1`。

CP05 的同一份独立 approval 还必须完整绑定 `public_scan_bindings`：冻结的
base/candidate/tree、`scripts/release/public_scan.py`、
`scripts/v23/v236_security.py` 与
`references/public-release-scan-baseline-v2.40.json` 的 blob SHA-256、baseline
assertion count/digest、assertion set、occurrence set 和 review digest。baseline
review 只能记录独立 reviewer 的 member/run/review identity、两个 reviewed-set
digest 与 `reviewed_at`，不得记录最终 `source_commit` 或 `candidate_tree`：baseline
文件本身位于 candidate tree 中，写入最终 Git identity 会形成不可解的哈希自引用。
最终 commit/tree 只由仓库外 detached CP05 approval 绑定；该 approval 的 reviewer
identity、两个 set digest 和时间必须与 baseline review 逐字段相等，同时其
`source_commit`/`candidate_tree` 必须与 release state 相等。scope owner
`RUN-V240-LEAD`、`Goal-Lead`/`架构-Lead` 或发行作者不得自审，也不得用
`independent=true` 自报绕过。baseline 只能由 `independent_release_reviewer`
逐项接受；发行入口不得自动生成或更新豁免。
provider token、private key、真实 credential、真实 home、README、tag message、
Release title/body 永远不可豁免。

Python/测试中的 detector literal、运行时拼接的合成 marker、以及非 README/CHANGELOG
表面的纯协议词汇，最多只能进入逐 occurrence、逐 digest 的独立 baseline review；它们
不是自动豁免。实际 provider token、private key、production credential、真实 home，
以及 README/CHANGELOG/tag/title/body 上的命中始终为 hard finding。

scanner receipt 必须逐字匹配 V2 receipt schema、base/candidate/tree/fixed-four-assets
identity、上述八项 trust bindings，并由冻结 scanner 重新计算
`receipt_sha256`；缺字段、多字段、set digest 漂移、review digest 漂移或 receipt
hash 漂移一律按 `E_V240_PUBLIC_SCAN` fail closed。

CP10 的固定顺序是：确认 canonical snapshot 与 CP09 两次隔离构建逐字节一致 →
运行 canonical release validator → 扫描完整候选 Git 树、base..candidate 历史
commit/blob/tree path、snapshot、tar、四个外层资产与 canonical tag/title/body →
重新扫描并 seal。snapshot 与 tar 的 path/content/mode 必须完全相等，gzip/tar
元数据必须 canonical；`passed=true`、`errors=[]`、`unwaived_findings=[]` 三项缺一
不可继续。CP12–CP17 每个 GitHub checkpoint 与 CP18 close 都必须重算同一份
deterministic receipt，并与 CP10 完整收据相等。

所有 release Git 读取必须使用禁用 replace 的固定命令与清洗环境，并拒绝
`refs/replace`、`info/grafts`、object alternates、shallow/partial/promisor clone 和
危险 `GIT_*` 重定向。任一命中统一按 `E_V240_GIT_OBJECT_GRAPH` fail closed；
不得在 builder、validator、GitHub adapter 或发布 shell 中使用不同的 Git 语义。

CP15 的 annotated tag message、CP16 Draft 与 CP17 Published Release 的 canonical
title/body 必须从已校验的根 `VERSION` 派生，adapter 收到的 version 与该文件不一致时
在任何远端写入前 fail closed；不得把 V2.40 literal 带入 V2.41。当前 V2.40 的 tag
message/title 为 `Goal Teams V2.40`，body 为
`Goal Teams V2.40. See release/current/README.md in the tagged source.`，
`targetCommitish` 的 raw 值必须就是冻结 candidate SHA，且解析结果仍须等于该 candidate；
`main`、tag 或其他 ref 即使在 promotion 后解析到相同 commit 也不接受。Draft
create/readback 还必须绑定 `draft=true`、`prerelease=false` 与上述三项；CP17 publish 的
最终 Draft projection 另外必须绑定 `immutable=false`；
Published marker-loss adoption 还必须精确匹配 persisted release ID、annotated
tag 的 peeled candidate、immutable/Latest 状态，并重新下载固定四资产验证
`asset_set_sha256`。release ID、`targetCommitish`、title/body、tag 或资产任一漂移都只能
分类为 `conflict`，不得直接采纳或重放 publish。

CP16 开始前 GitHub Draft 的 `databaseId` 不存在，因此 CP15/CP16 envelope 都必须省略
`next_checkpoint_expected_before`，调用方不得预测或选择 CP16 后续 operation 或 CP17 的
Release ID。引擎在 CP15 通过后只落盘 `CP16.draft_create` intent；create/adopt 得到 exact
Draft readback 后，才从 CP10 seal 与该 numeric `databaseId` 内部派生并以 CAS marker-last
追加四个 upload、download verify 与 remote rehearsal 六个 intent。第一次 CP16 调用到此
返回，phase/current checkpoint 保持不变；调用方读取新 state digest 后，必须在第二次调用
逐项授权新 intent。恢复态只允许 operation-plan exact prefix 长度 `1` 或完整长度 `7`；
长度 `2..6`、caller-supplied Release ID、伪造 expected-before/intent hash 都 fail closed。
Draft side effect 后 marker 丢失时复用原 draft intent 做 exact adopt；readback 已落盘但六个
intent marker 丢失时先 fresh observe 再重新派生，不得重复创建 Draft 或绕过第二次授权。

引擎只在 CP16 七个 operation 都形成 exact readback 后，从
`CP10.snapshot_seal` 的固定四资产/validator seal、`CP05.workflow_approve` 的独立
approval，以及 `CP16.draft_create`、`CP16.asset_download_verify`、
`CP16.remote_bundle_rehearsal` 内部生成完整 CP17 expected-before。Draft ID、canonical
title/body/target、asset ID/digest/set、candidate、rehearsal 或 approval 任一不一致都按
`E_V240_STATE_DERIVATION`/`E_V240_CI_TRUST_BINDING` fail closed；marker 丢失时只能从同一组
已持久化 readback 重建相同 map，调用方不能覆盖。四个 REST asset ID 的排序 identity
digest 同时绑定 publish、published download、actual install 与 independent audit，禁止以
相同字节删除重传出新 asset ID 后继续。

CP17 publish 在 mutation-edge ruleset/main guard 之后、PATCH 之前，必须重新读取同一
numeric Draft ID、`draft=true`、`immutable=false`、`prerelease=false`、tag、raw target
等于 candidate 且解析后仍等于 candidate、canonical name/body，以及
固定四资产逐项 REST ID、size、digest；任一漂移都必须保持 publish PATCH 为 0。GitHub
update-release 没有已文档化、覆盖资产集合的强 ETag/条件写协议，因此不得把普通二次读取
宣称为 CAS，也不得伪造 `If-Match` 能力。剩余服务端窗口只能由真正的仓库外 release host
持有 exclusive mutation window。candidate repository 不实现、接收或验证任何 positive
publish authority，也不存在 callback/duck object/CLI/config/promotion-state 注入路径；它在
完成两次只读 projection 后始终以 `E_V240_EXCLUSIVE_HOST_AUTHORITY_REQUIRED` 在 PATCH 前
fail closed，candidate publish PATCH 数必须为 0。实际外部 host 必须在自己的受信进程和
排他窗口内独立绑定 repository、version/tag、candidate、numeric Release ID 与两项 asset
digest，重新读取并验证完整 Draft projection，然后自行执行完整 PATCH。该外部 host 不属于
本仓库候选实现，不能用候选侧单元测试中的普通对象或回调模拟为信任证明。外部 PATCH 必须
重申 `tag_name`、`target_commitish`、`name`、`body`、`draft=false`、
`prerelease=false` 与 `make_latest=true` 的完整 canonical metadata，而不是只翻转 draft。

CP01 前的 canonical root 已知为 dirty/non-main；该历史事实由固定 recovery bundle
绑定，不能伪装成 CP02 topology 已通过。

本次 legacy-root 迁移的可执行主链是 `start(CP00) → promote(CP01) → 根恢复并切换到 clean main → doctor(CP02 前必须通过) → promote(CP02–CP08) → prepare(CP09–CP10) → promote(CP11–CP17) → close(CP18)`。如果 CP01 首次执行时 legacy root 仍是冻结的 dirty/non-main worktree，它继续做 exact live readback，随后由操作者按凭证 stash 并恢复为 clean `main`；如果状态重启时 root 已经恢复，CP01 只接受固定路径 `docs/release-state/V2.40/root-recovery-stash.json` 的 closed v2 attestation。该 attestation 必须绑定固定 bundle、stash reflog 中的三父 commit/tree、由父对象重构的 staged/unstaged/untracked 集合、恢复前 CP01 archive receipt chain、当前 clean `main`，以及 canonical root 只读解析的 `refs/remotes/origin/main^{commit}`；该 remote-tracking ref 必须等于 frozen base，receipt 写 observed 值而不是复制 state。禁止 caller-selected path；真正的 GitHub live main 仍由紧随其后的 CP02 doctor 读取。两种路径都只在隔离 clone 中重放 bundle，绝不执行 `stash apply/drop`、`update-ref` 或 `git worktree add/remove`；CP01 整体前后即使异常也必须比较 refs/worktree registry snapshot。所有 Git 读取禁用 global/system config，并拒绝本地 `core.fsmonitor`、`core.hooksPath`、`include.path`/`includeIf.*.path`、external diff/textconv 与 clean/smudge/process filter；diff 固定带 `--no-ext-diff --no-textconv`。`develops/v2.38` 仍须保持 live source exact，并完成相同隔离重放。真正的 topology gate 位于 CP01 后、CP02 前，且必须返回通过。`status` 是任意非终态阶段的只读观测，不写 state、不触发外部动作。`recover` 只处理当前已持久化 intent：重读或采纳 exact readback；若必须重放外部写入，还必须提供 `resume_external_writes=true`、原 operation authorization 和 `GOAL_TEAMS_RELEASE_WRITE=1`。

CP18 的正式归档验证同时保留 V2.36 trust boundary：外层 release host 独立重放 ledger、TaskList、Evidence、Harness、Review 与 Audit，并要求候选侧 `completion-audit` 精确 fail closed 为 `E_V236_HOST_ADAPTER_REQUIRED`。此 expected rejection 只证明候选不能自我签发 Completion；最终关闭权限来自 CP17 独立 live audit 与 CP18 外层状态机，不得把该拒绝伪装成内层 `exit_code=0`。

CP17 与 CP18 采用显式两阶段关闭边界。第一阶段的 `CP17.independent_audit` 只冻结 main/tag/Latest/asset/install/README、candidate/post-release CI 与远端保护等 live 发行事实；receipt 禁止出现 `goal_teams_work_tree`、`ssot_tree`、`ssot_receipt`、`host_receipt` 或 `host_authority`。CP17 marker-last 通过后返回 `current_checkpoint=CP18`，形成唯一合法 SSOT finalization window；此前仍为 `running` 的 RELEASE task、未来 Evidence 或缺失 Completion 均不能通过 CP18。外层 host 在该窗口补齐最终 Evidence、accepted tasks、Review、Completion 与归档清单，但 candidate 的 `promote`/`close` envelope 不接受任何 positive host authority/receipt 输入。

第二阶段 `close` 必须重新运行 live audit，并与 CP17 receipt（含 `receipt_sha256`）逐字一致；`close-index.json.audit_receipt_sha256` 再绑定该 exact receipt。`_validate_archived_goal_teams_ssot` 对最终归档树独立重放 ledger/TaskList/Evidence/Harness/Review/Completion，并把完整 tree receipt 纳入 close boundary。该完整边界第一次验证后先 marker-last seal；同一次 `close` 调用中、紧贴 `promotion_lock_finalize` 的 actual/adopt 分支之前必须 fresh 重算且逐字匹配该 seal，远端写入后、`CLOSED` marker 前还必须再验证一次。若 `CP18.archive_close` exact readback 已落盘而最终 marker 丢失，`recover` 仍须 fresh 重算完整边界并精确匹配 stored readback；ledger、Completion、manifest、root 或 worktree 任一漂移都以 `E_V240_RECOVERY_STALE_READBACK` 或对应 close 错误 fail closed，不能用旧 readback 进入 `CLOSED`。CP17 前五个已具 exact receipt 的 side effect 在恢复时只 fresh observe/adopt，不重放。

`CLOSED` 的机器语义只允许 `closure_scope=distribution_and_archive_only`、`goal_achieved=false`、`external_host_acceptance_required=true`、`completion_authority=repository_external_single_use_host`。四字段只能从 CP18 exact archive readback 派生并 marker-last 写入 promotion state；非 `CLOSED` state 禁止携带，`status`、`recover` 与 `close` 的终态返回必须逐项回显。候选侧观察到 `E_V236_HOST_ADAPTER_REQUIRED` 仅证明自验边界 fail closed，不能成为 authoritative completion；真正 Goal achieved 必须另有仓库外的 single-use host acceptance。

## Release Gate 命令

```bash
./scripts/check.sh
CANONICAL_ROOT="/absolute/path/to/goal-teams"  # 使用前替换为本机 canonical root 绝对路径

cd "$CANONICAL_ROOT/develops/v2.40"
"$PYTHON_BIN" scripts/release/release.py start --input "$CANONICAL_ROOT/docs/release-state/V2.40/start.json"
"$PYTHON_BIN" scripts/release/release.py promote --input "$CANONICAL_ROOT/docs/release-state/V2.40/promote-cp01.json"
# legacy root 尚未恢复时，按 CP01 live 凭证 stash 并切换到 clean main；
# 已恢复/重启时，CP01 改验固定 root-recovery-stash.json，且不会应用或删除 stash。
"$PYTHON_BIN" scripts/release/release.py doctor --input "$CANONICAL_ROOT/docs/release-state/V2.40/doctor.json"
"$PYTHON_BIN" scripts/release/release.py promote --input "$CANONICAL_ROOT/docs/release-state/V2.40/promote-current-checkpoint.json"
"$PYTHON_BIN" scripts/release/release.py prepare --input "$CANONICAL_ROOT/docs/release-state/V2.40/prepare.json"
"$PYTHON_BIN" scripts/release/release.py status --input "$CANONICAL_ROOT/docs/release-state/V2.40/status.json"
"$PYTHON_BIN" scripts/release/release.py recover --input "$CANONICAL_ROOT/docs/release-state/V2.40/recover.json"

cd "$CANONICAL_ROOT"
"$PYTHON_BIN" scripts/release/release.py close --input "$CANONICAL_ROOT/docs/release-state/V2.40/close.json"
```

所有 JSON envelope 的 `state_path` 必须是 canonical root 下 `docs/release-state/V2.40/promotion-state.json` 的绝对路径；不得使用会从 candidate cwd 解析到 `develops/v2.40/docs/` 的相对路径，也不得在实际 JSON 中保留 `<canonical-root>` 一类未解析占位值。`start` 从 candidate worktree 执行，但一开始就把 state 写进 canonical root `docs/`，以便移除 candidate 后由 canonical root 上的 `close` 继续读取同一 state。

`promote` 每次只推进当前 checkpoint，不得跳步；远端写入还必须同时满足输入中的 `execute_external_writes=true`、per-operation authorization 与 `GOAL_TEAMS_RELEASE_WRITE=1`。GitHub 只接收已经在本地 `release/versions/<VERSION>/` 验证通过的同一份资产。published 后 actual install 另需 operation parameters 中的 `execute_actual_install=true` 与 `GOAL_TEAMS_RELEASE_INSTALL=1`，GitHub 元数据、安装日志和 post-release 凭证保存在根 `docs/archive/releases/<VERSION>/release-evidence/`，不放进发行包。若上传阶段失败但 tag 已推送，只允许在确认 tag 仍指向 `_release.json.source_commit` 后由 `recover` 重读并恢复同一 Draft；不得移动或覆盖 tag。

## JSON envelope 约定

下列 JSON 是字段和类型正确的脱敏模板，不是可直接使用的授权。所有 commit/tree 必须换成 40 位 lowercase Git SHA，所有 digest 必须换成 64 位 lowercase SHA-256；`intent_sha256`、`expected_before`、`parameters_sha256` 和 `expected_after_sha256` 必须从当前 state 中同一 operation 的已持久化 intent 精确派生，不得自报成功事实。CP03 的三个 operation 与所有远端 mutation intent 都必须持有 action-specific、非空的 `expected_before`；空对象不能表示 CAS。它们的 authorization 必须逐字回显两个摘要，并提供与 `parameters_sha256` 相同的完整 parameters，调用方不得在执行时改名、改 payload、改 workflow 或补入新字段。

### `start` / CP00

`scope.locked_scope`、`route_receipt_sha256` 和 `spec_sha256` 必须分别精确匹配 `current-route-receipt.json`、该文件 bytes 与固定 SPEC 文件列表。

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "repository": "vibe-coding-era/goal-teams",
  "version": "V2.40",
  "base_main_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "candidate_tree": "cccccccccccccccccccccccccccccccccccccccc",
  "scope": {
    "repository": "vibe-coding-era/goal-teams",
    "version": "V2.40",
    "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "owner_run_id": "RUN-V240-LEAD",
    "locked_scope": ["<exact locked-scope item from current-route-receipt.json>"],
    "route_receipt_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "spec_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "done_criteria": ["<frozen done criterion>"]
  }
}
```

### `doctor` 与 `status`

`doctor` 只接受 state/CAS 与不能放宽的固定 scope；禁止传入 `workspace_facts`。

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "expected_state_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "expected_scope": {
    "repository": "vibe-coding-era/goal-teams",
    "version": "V2.40",
    "tag": "v2.40",
    "canonical_branch": "main",
    "candidate_location": "develops/v2.40",
    "candidate_branch": "codex/v2.40"
  }
}
```

`status` 只需 state 与可选 CAS：

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "expected_state_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
}
```

### `promote` 和 `recover`

下例是本地 CP01。每个 current operation 都必须有同名 authorization；`mode` 只能按 operation 类型取 `execute_local`、`observe` 或 `execute_github`。

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "expected_state_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "checkpoint_id": "CP01",
  "operation_authorizations": {
    "CP01.legacy_recovery": {
      "intent_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
      "mode": "execute_local",
      "parameters": {}
    }
  }
}
```

在完成 CP11 并创建外部 CP12 intent 时，同一 envelope 还必须提供下一 checkpoint 的 exact expected-before：

```json
{
  "next_checkpoint_expected_before": {
    "CP12.candidate_push": {
      "remote_candidate_commit": null
    }
  }
}
```

### CP16 两阶段授权检查点

CP15 通过后的 state 中，`CP16.operations` 必须只有 `CP16.draft_create`。第一次 CP16
envelope 的 `operation_authorizations` 也必须只含该项；提前夹带 upload/download/rehearsal
authorization、`state_updates` 或任何 next-checkpoint map 都在状态写入和外部动作前拒绝。
成功 create 或 adopt exact Draft 后，本次返回必须同时满足：

- `checkpoint=CP16`、`next_checkpoint=CP16`，phase 仍为 `TAG_PUSHED`；
- `checkpoint_stage=draft_bound_followup_intents_persisted`；
- state CAS digest 已更新，CP16 operation 数从 `1` 原子变为 `7`；
- 尚未执行任何 asset upload、download 或 rehearsal。

操作者随后重新读取 state，用新 `state_sha256` 为七个 persisted intent 生成逐项 authorization；
第二次 CP16 调用会 fresh observe 已有 Draft、跳过重复 create，再执行余下六项。若进程在远端
create 后、readback 前中断，`recover` 使用同一 draft intent adopt；若在 readback 后、六 intent
CAS 前中断，恢复调用先 fresh observe，再生成完全相同的六项并返回同一 stage。任何阶段都
不能根据日志手填 numeric Release ID，也不能把部分长度 `2..6` 的 operation list 当作恢复态。

上述规则不适用于 CP15→CP16 或 CP16→CP17：两者 envelope 都必须省略
`next_checkpoint_expected_before`。CP15 后引擎仅派生 Draft-create intent；其 exact numeric
ID 落盘后，第一次 CP16 调用 marker-last 追加六个后续 intent 并返回
`checkpoint_stage=draft_bound_followup_intents_persisted`，第二次 CP16 调用才可逐项授权执行。
CP16 全部 exact 后再内部派生 CP17 六个 intent。任一阶段提供该字段（包括 JSON `null`）
都会在任何 side effect 前以 `E_V240_STATE_EXPECTED_BEFORE` 拒绝。

外部写入中断后的 `recover` 使用同一 persisted intent，并显式开启重放授权：

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "expected_state_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "checkpoint_id": "CP12",
  "execute_external_writes": true,
  "resume_external_writes": true,
  "operation_authorizations": {
    "CP12.candidate_push": {
      "intent_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
      "expected_before": {
        "remote_candidate_commit": null
      },
      "parameters_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
      "expected_after_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
      "mode": "execute_github",
      "parameters": {}
    }
  }
}
```

CP15–CP17 每次真正的远端 mutation 之前都必须重新读取两份 CP14 ruleset：可复用的永久
`goal-teams-main-protection` 与永久 `refs/tags/v*` tag ruleset。main ruleset 从 CP14 起就必须同时
包含固定三项 required checks、PR/非快进/删除保护，以及唯一 exact release actor bypass；同名同
payload 可零写 adopt，任一弱策略、actor 漂移或 payload 漂移都 fail closed。readback 必须同时包含 GitHub 正整数
`ruleset_id`、name、完整 live-normalized payload 与该 payload 的 SHA-256；禁止把 intent 中的
expected payload 复制成 readback。任一 ruleset 缺失、numeric ID 变化、payload/摘要变化或
`remote_lock` 与 CP14 binding 不同，都在本次 mutation 前失败。该 fresh guard 对 CP15 tag、
CP16 Draft 与每一个 asset upload、CP17 main CAS、Release publish 和 post-release dispatch
逐次执行，不能复用上一次检查结果。完整 guard 以
`goal-teams-v2.40-remote-mutation-guard-v1` 写入 operation parameters，并由
`intent.parameters_sha256` 绑定；调用方改动、删除或跨 operation 复用都会在授权阶段失败。
release 层的提前检查只用于早失败，不能替代 adapter 在实际 `git push`、Release/Draft/asset
HTTP write、Release PATCH 或 workflow dispatch 命令紧前的最后一次 fresh guard。若初次
observe 后才发生 ruleset/main 漂移，adapter 仍必须在真实写调用前返回且 mutation count 为 0。

ruleset 按名称查找必须对 `GET /rulesets` 使用 `--paginate --slurp`，兼容 `gh` 返回的
flat rows 或任意数量的 nested page rows，再对全部页面做 exact-name 全局唯一匹配；目标只在
后续页面时必须读取，跨页出现两个同名条目必须按 conflict fail closed，不能只检查第一页。

同一 guard 还重新读取 `refs/heads/main`：CP15/CP16 必须仍等于 `base_main_commit`；CP17
执行 `main_promote` 前必须等于 base，后续 publish/dispatch 前必须等于 candidate。若
`main_promote` 的 exact marker 已落盘，恢复 readback 必须看到 candidate；marker 丢失的
只读 adopt 可观察 base 或 candidate，再由 adapter 以 persisted intent 分类，不能把第三个
commit 当作可恢复状态。CP17 的 Release publish 因而绝不能在 main 尚未到 candidate 时发生。

### `prepare` / CP09–CP10

`prepare` 只在 current checkpoint 为 CP09 或 CP10 时可用，它内部生成并验证本地 operation authorization，不接受 caller 自报构建成功。

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "expected_state_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
}
```

### `close` / CP18

`close` 必须从 canonical 根运行，state 必须位于根 `docs/`，candidate worktree/登记项必须已移除，归档索引必须直接位于 `docs/archive/releases/V2.40/`。下例保留了最终 ruleset exact-reuse CAS 所需的字段；脱敏 ID、payload 与 digest 必须替换为 CP14 绑定和已批准的 permanent main-protection payload。

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "expected_state_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "checkpoint_id": "CP18",
  "archive_index_path": "/absolute/path/to/goal-teams/docs/archive/releases/V2.40/close-index.json",
  "execute_external_writes": true,
  "operation_authorizations": {
    "CP18.promotion_lock_finalize": {
      "intent_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
      "expected_before": {
        "ruleset_id": 123456,
        "ruleset_name": "goal-teams-main-protection",
        "ruleset_payload": {
          "name": "goal-teams-main-protection",
          "target": "branch",
          "enforcement": "active",
          "bypass_actors": [
            {"actor_id": 123456, "actor_type": "User", "bypass_mode": "always"}
          ],
          "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
          "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
              "type": "pull_request",
              "parameters": {
                "dismiss_stale_reviews_on_push": true,
                "require_code_owner_review": false,
                "require_last_push_approval": true,
                "required_approving_review_count": 1,
                "required_review_thread_resolution": true
              }
            },
            {
              "type": "required_status_checks",
              "parameters": {
                "strict_required_status_checks_policy": true,
                "do_not_enforce_on_create": false,
                "required_status_checks": [
                  {"context": "check-ubuntu"},
                  {"context": "check-macos"},
                  {"context": "release-asset-gate"}
                ]
              }
            }
          ]
        },
        "ruleset_sha256": "4444444444444444444444444444444444444444444444444444444444444444"
      },
      "parameters_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
      "expected_after_sha256": "6666666666666666666666666666666666666666666666666666666666666666",
      "mode": "execute_github",
      "parameters": {
        "ruleset_id": 123456,
        "ruleset_name": "goal-teams-main-protection",
        "ruleset_payload": {
          "name": "goal-teams-main-protection",
          "target": "branch",
          "enforcement": "active",
          "bypass_actors": [
            {"actor_id": 123456, "actor_type": "User", "bypass_mode": "always"}
          ],
          "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
          "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
              "type": "pull_request",
              "parameters": {
                "dismiss_stale_reviews_on_push": true,
                "require_code_owner_review": false,
                "require_last_push_approval": true,
                "required_approving_review_count": 1,
                "required_review_thread_resolution": true
              }
            },
            {
              "type": "required_status_checks",
              "parameters": {
                "strict_required_status_checks_policy": true,
                "do_not_enforce_on_create": false,
                "required_status_checks": [
                  {"context": "check-ubuntu"},
                  {"context": "check-macos"},
                  {"context": "release-asset-gate"}
                ]
              }
            }
          ]
        },
        "ruleset_payload_sha256": "4444444444444444444444444444444444444444444444444444444444444444"
      }
    },
    "CP18.archive_close": {
      "intent_sha256": "8888888888888888888888888888888888888888888888888888888888888888",
      "mode": "execute_local",
      "parameters": {}
    }
  }
}
```

`expected_before.ruleset_id` 与 `parameters.ruleset_id` 必须是 CP14 live readback 绑定的同一个 reusable main-protection ruleset ID；name、完整 live-normalized payload 与摘要也必须完全相同。adapter 在 CP14 对 absent 执行一次 create，对已有同名 exact policy 零写 adopt；CP18 只按同一 numeric ID/name/payload 做 final exact reuse/CAS，不能把弱策略升级为成功，也不能更换 release actor。main protection 的唯一 bypass actor 必须等于 CP03/CP05 冻结的 `github_authority.actor_id`/`release_actor_id`，使后续版本仍可使用受控 `force-with-lease`，其他 actor 继续受三项 required checks 与 PR 规则约束。永久 tag lock 使用跨版本稳定名称 `goal-teams-tag-protection`，禁止创建 `-v2.40`、`-v2.41` 等版本后缀规则；同名规则只有完整 normalized payload exact 才能零写 adopt。其 `update` rule 显式固定 `update_allows_fetch_and_merge=false`，另含 `deletion`，范围必须是 `refs/tags/v*` 且 `exclude=[]`；main protection 的 pull-request 参数显式固定 `require_code_owner_review=false`，不得依赖 GitHub 默认值。

## V2.40 GitHub 主权与可恢复 dispatch

所有 release 读写固定绑定 `api_host=github.com` 与 `repository_full_name=vibe-coding-era/goal-teams`，同时记录正整数 repository ID。`GH_HOST` 非空且不等于 `github.com` 时必须在任何远端副作用之前失败；每条 `gh api` 显式指定 `--hostname github.com`，其他 `gh` 命令使用 `github.com/vibe-coding-era/goal-teams`。CP02、CP14、每次远端写入前和 live audit 都必须重新验证 origin 的 raw/resolved fetch/push URL；显式 fork pushurl，以及 local/global/system 任一作用域的 `url.*.insteadOf`/`pushInsteadOf`，一律拒绝。

CP03 bootstrap、CP14 revalidate 与每次 write-authority refresh 还必须读取 classic
`main` branch protection，不能只验证 reusable ruleset。classic protection 缺失可继续；
若存在，则只有“管理员且 `enforce_admins=false` 的明确 bypass”，或“允许 force push、
release actor 未被 restrictions 排除且无 required checks/reviews/signatures/linear-history/
branch-lock 阻断”才兼容受控 `force-with-lease`。任何 classic 策略与 release actor 或
reusable main ruleset 冲突都以 `E_V240_CLASSIC_BRANCH_PROTECTION` fail closed，并把
normalized compatibility receipt 纳入冻结 authority digest，防止 CP03/CP14 之间漂移。

分支与 tag 的 GitHub REST ref 是主权读回，`git ls-remote origin` 只作独立二次证据，两者缺失状态或对象 ID 不一致即 fail closed。annotated tag 还必须从 REST tag object 读取 canonical message 和 peeled commit，并与 `refs/tags/<tag>^{}` 一致。

CP13 candidate CI 与 CP17 post-release CI 在没有 `run_id` 的恢复路径中，都必须查询 numeric
workflow endpoint `actions/workflows/{workflow_id}/runs?per_page=100`，并使用
`--paginate --slurp` 读取全部页面。请求不得带 `branch`、`event`、`head_sha`、`status` 等
服务端 filter，以避开 GitHub filtered workflow runs 的 1,000-result cap；也不得用百分号编码的
full-path endpoint。workflow ID/path、candidate head、event、actor、triggering actor 等谓词必须
在完整结果上本地执行，并要求全局唯一。

CP17 `workflow_dispatch` 另外不接受调用者选择 intent。release engine 从已持久化 operation
`idempotency_key` 内部注入 `release_intent`，workflow `run-name` 由已校验 `VERSION` 派生为
当前 `Goal Teams V2.40 release <release_intent>`。本地过滤还须匹配 display title/intent；
不得因目标 run 位于第 2 页以后或第 1,000 条以后而判定 absent。全量结果 0 个才允许首次
dispatch；1 个 pending 或 green run 必须采用且不得重发；超过 1 个为冲突；其他 intent 的
run 不得采用。首次 dispatch 只返回 pending 恢复信号，后续恢复必须通过唯一 run 收敛。
