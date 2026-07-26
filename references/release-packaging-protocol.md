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

V2.44 起，发行身份不再散落为脚本中的版本常量，而由
`references/release-profiles/<version>.json` 与
`schemas/release-engine-profile.schema.json` 组成的闭合集合控制。profile 必须绑定
版本、candidate、tag、Release title/body、严格 snapshot 格式、public scan
baseline 与 close schema，并在 CP00、每个 operation intent、CP05 审批、CP10 seal
中绑定其 Git blob。未知版本、工作区未提交配置、配置漂移均 fail closed。
`V2.45` 是唯一 active profile；`V2.44` 与 `V2.40` 保留协议、前序验证和错误码
兼容，但属于 `historical_replay`，GitHub adapter 必须拒绝它们的任何 external
write。

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

## CP00–CP18 唯一执行顺序

| Checkpoint | 固定语义 | 公开命令 |
| --- | --- | --- |
| CP00 | scope/SPEC/route/owner/locked-scope/release-engine profile 冻结；从 active profile 指定的 candidate worktree 执行 | `start` |
| CP01 | active profile 校验 prior-main/current-release continuity；V2.40 历史回放才校验 pre-V2.40 recovery bundle | `promote` |
| CP02 | canonical/candidate/topology 验证 | `promote` |
| CP03 | GitHub authority readback → immutable release enable → ruleset capability verify | `promote` |
| CP04 | development identity | `promote` |
| CP05 | promotion contract 验证 → 外部可信宿主 workflow approval；带 `host_acceptance` 的 profile 在 public `promote/recover` 永久 fail closed | repository-external host |
| CP06 | static gates | `promote` |
| CP07 | quality gates | `promote` |
| CP08 | candidate identity → RC commit freeze | `promote` |
| CP09 | primary build → reproducibility build | `prepare` |
| CP10 | isolated-build equality → asset validation → complete public scan → rescan/snapshot seal | `prepare` |
| CP11 | local release-bundle rehearsal | `promote` |
| CP12 | exact candidate push | `promote` |
| CP13 | candidate exact-SHA CI | `promote` |
| CP14 | authority revalidate → main promotion lock → immutable verify → permanent tag ruleset → promotion lease | `promote` |
| CP15 | annotated tag push | `promote` |
| CP16 | Draft create/recover → fixed four-asset upload → download verify → temporary remote-bundle rehearsal | `promote` |
| CP17 | exact main CAS → publish-last → published download → actual install → post-release CI → independent audit | `promote` |
| CP18 | permanent main protection finalize → canonical archive close；必须从 canonical root 执行；外层 release host 重算 SSOT，候选侧 Completion 必须保持 host-adapter fail-closed | `close` |

CP05 的 `ci_approval` 顶层必须记录 `release_actor_id`，并与 CP03 冻结的
`github_authority.actor_id` 完全一致；它是 CI 执行者身份，不得用独立
reviewer 的 `member_id` 或 `run_id` 代替。CP13 candidate CI、CP17
post-release CI 与最终 live audit 都必须同时回读 Actions run 的
`actor_id` 和 `triggering_actor_id`，二者均须与 `release_actor_id` 及
`github_authority.actor_id` 完全一致。`run_attempt > 1` 可以表示合法 rerun，
但实际触发 rerun 的 actor 不得变化；任一 actor 链漂移均按
`E_V240_CI_TRUST_BINDING` fail closed。

CP05 的同一份独立 approval 还必须完整绑定 `public_scan_bindings`：冻结的
base/candidate/tree、`scripts/release/public_scan.py`、
`scripts/v23/v236_security.py` 与
active profile 指定的 `public_scan_baseline` blob SHA-256、baseline
assertion count/digest 和 review digest。baseline 只能由
`independent_release_reviewer` 逐项接受；发行入口不得自动生成或更新豁免。
provider token、private key、真实 credential、真实 home、README、tag message、
Release title/body 永远不可豁免。

V2.45 CP05 的 `host_acceptance` 使用发行 Profile 冻结的 Ed25519 公钥验证。
`key_id` 必须等于 32-byte 原始公钥的 SHA-256；`signature` 是固定版本域
`goal-teams/v2.45/cp05/host-acceptance/ed25519/v1`、一个 NUL byte 和移除自身
字段后 acceptance 对象的 canonical JSON bytes 的 64-byte Ed25519 签名。候选公共验证器
必须实际验签，不能只检查签名长度或摘要格式。HMAC 仅用于宿主私有 challenge
state 的完整性与防重放，不能作为公开验收签名。

V2.45 的 CP05 不能接收 caller JSON、布尔值、摘要、文件路径、argv/env token
或 module-level object 作为 capability。公开 `release.py promote/recover`
必须在首次状态写入前返回 `E_V244_HOST_CP05_REQUIRED`；私有
`CP05.workflow_approve` helper 同样不得为 V2.45 生成 caller-forged exact
readback。仓库外宿主必须在 Reviewer 退出后重验 candidate/state/trust pins，
从 Keychain 读取不落盘 HMAC key，验证 TTL 与 MAC-protected persistent
challenge state，绑定 pre-state byte SHA、两项 CP05 intent、candidate/tree/base、
workflow/checker/public-scan、真实 Codex observation 和最终 approval core，
V2.45 `current-route-receipt.json` 的原始字节摘要、self-release policy 与冻结
candidate/base。Reviewer 必须从仓库外空工作目录启动，候选树的 `AGENTS.md`
仅作为被审数据；宿主 Git、Node 与 Codex provenance 必须固定，
再在同一宿主事务中消费 challenge 并以单次 CAS 将 CP05 推进到 CP06。完整
signed host acceptance 的 digest 必须进入 workflow readback → operation receipt →
checkpoint receipt 链；仅 hash receipt 不构成授权。宿主必须保留可恢复的 prepared
transaction 与 committed receipt，candidate runtime 永远不得读取 Keychain key。

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

CP15 的 annotated tag message、CP16 Draft 与 CP17 Published Release 的
canonical title/body 均由 frozen release-engine profile 唯一派生；V2.45 分别是
`Goal Teams V2.45`、`Goal Teams V2.45` 与
`Goal Teams V2.45. See release/current/README.md in the tagged source.`，
`targetCommitish` 必须解析到冻结 candidate。Draft create/readback 必须绑定这三项；
Published marker-loss adoption 还必须精确匹配 persisted release ID、annotated
tag 的 peeled candidate、immutable/Latest 状态，并重新下载固定四资产验证
`asset_set_sha256`。release ID、`targetCommitish`、title/body、tag 或资产任一漂移都只能
分类为 `conflict`，不得直接采纳或重放 publish。

V2.45 active profile 的可执行主链是 `start(CP00) → promote(CP01) → doctor(CP02 前必须通过) → promote(CP02–CP08) → prepare(CP09–CP10) → promote(CP11–CP17) → close(CP18)`。CP01 校验 base main 上 V2.44 已发布投影与 candidate 上 V2.45 投影的连续性，并绑定 frozen release-engine profile；不再要求 legacy-root 恢复。V2.44/V2.40 历史回放仍保留前序与 recovery 验证，但不能触发外部写入。`status` 是任意非终态阶段的只读观测，不写 state、不触发外部动作。`recover` 只处理当前已持久化 intent：重读或采纳 exact readback；若必须重放外部写入，还必须提供 `resume_external_writes=true`、原 operation authorization 和 `GOAL_TEAMS_RELEASE_WRITE=1`。

CP18 的正式归档验证同时保留 V2.36 trust boundary：外层 release host 独立重放 ledger、TaskList、Evidence、Harness、Review 与 Audit，并要求候选侧 `completion-audit` 精确 fail closed 为 `E_V236_HOST_ADAPTER_REQUIRED`。此 expected rejection 只证明候选不能自我签发 Completion；最终关闭权限来自 CP17 独立 live audit 与 CP18 外层状态机，不得把该拒绝伪装成内层 `exit_code=0`。

## Release Gate 命令

```bash
./scripts/check.sh
CANONICAL_ROOT="/absolute/path/to/goal-teams"  # 使用前替换为本机 canonical root 绝对路径

cd "$CANONICAL_ROOT/develops/v2.45-release-engineer"
"$PYTHON_BIN" scripts/release/release.py start --input "$CANONICAL_ROOT/docs/release-state/V2.45/start.json"
"$PYTHON_BIN" scripts/release/release.py promote --input "$CANONICAL_ROOT/docs/release-state/V2.45/promote-cp01.json"
"$PYTHON_BIN" scripts/release/release.py doctor --input "$CANONICAL_ROOT/docs/release-state/V2.45/doctor.json"
"$PYTHON_BIN" scripts/release/release.py promote --input "$CANONICAL_ROOT/docs/release-state/V2.45/promote-current-checkpoint.json"
"$PYTHON_BIN" scripts/release/release.py prepare --input "$CANONICAL_ROOT/docs/release-state/V2.45/prepare.json"
"$PYTHON_BIN" scripts/release/release.py status --input "$CANONICAL_ROOT/docs/release-state/V2.45/status.json"
"$PYTHON_BIN" scripts/release/release.py recover --input "$CANONICAL_ROOT/docs/release-state/V2.45/recover.json"

cd "$CANONICAL_ROOT"
"$PYTHON_BIN" scripts/release/release.py close --input "$CANONICAL_ROOT/docs/release-state/V2.45/close.json"
```

所有 active JSON envelope 的 `state_path` 必须是 canonical root 下 `docs/release-state/V2.45/promotion-state.json` 的绝对路径；不得使用会从 candidate cwd 解析到 `develops/v2.45-release-engineer/docs/` 的相对路径，也不得在实际 JSON 中保留 `<canonical-root>` 一类未解析占位值。`start` 从 candidate worktree 执行，但一开始就把 state 写进 canonical root `docs/`，以便移除 candidate 后由 canonical root 上的 `close` 继续读取同一 state。

`promote` 每次只推进当前 checkpoint，不得跳步；远端写入还必须同时满足输入中的 `execute_external_writes=true`、per-operation authorization 与 `GOAL_TEAMS_RELEASE_WRITE=1`。GitHub 只接收已经在本地 `release/versions/<VERSION>/` 验证通过的同一份资产。published 后 actual install 另需 operation parameters 中的 `execute_actual_install=true` 与 `GOAL_TEAMS_RELEASE_INSTALL=1`，GitHub 元数据、安装日志和 post-release 凭证保存在根 `docs/archive/releases/<VERSION>/release-evidence/`，不放进发行包。若上传阶段失败但 tag 已推送，只允许在确认 tag 仍指向 `_release.json.source_commit` 后由 `recover` 重读并恢复同一 Draft；不得移动或覆盖 tag。

## V2.40 历史回放 JSON envelope

下列固定 JSON 块只用于验证 V2.40 状态兼容与恢复语义，不能授权 GitHub 写入。
V2.45 active envelope 必须从当前 state 中提取 intent/CAS，并额外携带 frozen
`release_engine_profile` binding；不得把这些历史样例改写成 active 授权。

下列 JSON 是字段和类型正确的脱敏模板，不是可直接使用的授权。所有 commit/tree 必须换成 40 位 lowercase Git SHA，所有 digest 必须换成 64 位 lowercase SHA-256；`intent_sha256` 和 `expected_before` 必须从当前 state 中同一 operation 的已持久化 intent 精确派生，不得自报成功事实。

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
      "mode": "execute_github",
      "parameters": {}
    }
  }
}
```

### `prepare` / CP09–CP10

`prepare` 只在 current checkpoint 为 CP09 或 CP10 时可用，它内部生成并验证本地 operation authorization，不接受 caller 自报构建成功。

```json
{
  "state_path": "/absolute/path/to/goal-teams/docs/release-state/V2.40/promotion-state.json",
  "expected_state_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
}
```

### `close` / CP18

`close` 必须从 canonical 根运行，state 必须位于根 `docs/`，candidate worktree/登记项必须已移除，归档索引必须直接位于 `docs/archive/releases/V2.40/`。下例保留了最终 ruleset CAS 所需的字段；脱敏 ID、payload 与 digest 必须替换为 CP14 绑定和已批准的 permanent main-protection payload。

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
        "ruleset_name": "goal-teams-promotion-lock-V2.40-<candidate-prefix>",
        "ruleset_payload": {
          "name": "goal-teams-promotion-lock-V2.40-<candidate-prefix>",
          "target": "branch",
          "enforcement": "active",
          "bypass_actors": [
            {"actor_id": 123456, "actor_type": "User", "bypass_mode": "always"}
          ],
          "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
          "rules": [{"type": "update"}]
        },
        "ruleset_sha256": "4444444444444444444444444444444444444444444444444444444444444444"
      },
      "mode": "execute_github",
      "parameters": {
        "ruleset_id": 123456,
        "ruleset_name": "goal-teams-main-protection",
        "ruleset_payload": {
          "name": "goal-teams-main-protection",
          "target": "branch",
          "enforcement": "active",
          "bypass_actors": [],
          "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
          "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
              "type": "pull_request",
              "parameters": {
                "dismiss_stale_reviews_on_push": true,
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
        "ruleset_payload_sha256": "5555555555555555555555555555555555555555555555555555555555555555"
      }
    },
    "CP18.archive_close": {
      "intent_sha256": "6666666666666666666666666666666666666666666666666666666666666666",
      "mode": "execute_local",
      "parameters": {}
    }
  }
}
```

`expected_before.ruleset_id` 与 `parameters.ruleset_id` 必须是 CP14 live readback 绑定的同一个临时 promotion-lock ruleset ID；临时名与永久名必须不同。adapter 先按临时 ID/name/payload 做 pre-mutation CAS，再对同一 ID 执行 PUT，最后按永久 name/payload 复核；任一侧缺失或不一致都必须 fail closed。

## V2.40 GitHub 主权与可恢复 dispatch

所有 release 读写固定绑定 `api_host=github.com` 与 `repository_full_name=vibe-coding-era/goal-teams`，同时记录正整数 repository ID。`GH_HOST` 非空且不等于 `github.com` 时必须在任何远端副作用之前失败；每条 `gh api` 显式指定 `--hostname github.com`，其他 `gh` 命令使用 `github.com/vibe-coding-era/goal-teams`。CP02、CP14、每次远端写入前和 live audit 都必须重新验证 origin 的 raw/resolved fetch/push URL；显式 fork pushurl，以及 local/global/system 任一作用域的 `url.*.insteadOf`/`pushInsteadOf`，一律拒绝。

分支与 tag 的 GitHub REST ref 是主权读回，`git ls-remote origin` 只作独立二次证据，两者缺失状态或对象 ID 不一致即 fail closed。annotated tag 还必须从 REST tag object 读取 canonical message 和 peeled commit，并与 `refs/tags/<tag>^{}` 一致。

CP17 `workflow_dispatch` 不接受调用者选择 intent。release engine 从已持久化 operation `idempotency_key` 内部注入 `release_intent`，workflow `run-name` 固定为 `Goal Teams V2.40 release <release_intent>`。在没有 `run_id` 的恢复路径中，adapter 先枚举固定 workflow 的 `workflow_dispatch` runs，并按 workflow path/id、candidate head、event、actor、triggering actor、display title/intent 精确匹配：0 个才允许首次 dispatch；1 个 pending 或 green run 必须采用且不得重发；超过 1 个为冲突；其他 intent 的 run 不得采用。首次 dispatch 只返回 pending 恢复信号，后续恢复必须通过唯一 run 收敛。
