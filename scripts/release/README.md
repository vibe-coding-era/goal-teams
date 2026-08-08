# Release scripts

## V2.62 两阶段 Skill 发行

V2.62 开发阶段只运行 TDD 与受影响面增量检查，不进入 S0–S4。只有 exact released
identity 进入 Release Readiness 后，才由 `check-v250.py --phase release` 各运行一次最终全量
回归和独立 `release_security_review`，并形成绑定 commit/tree 的两个 receipt。

S2 对每个 asset set 只调用一次 `build-release.py`；不执行第二次构建、逐字节复现比较或
S2 安全检查。S3 仅适用于 Large Release 且要求 S1 `passed/current`。S4 使用项目开始时的
`project_start_authorization_receipt`，不再发起第二次过程授权。操作者 Git fetch/push 使用
GitHub SSH；PR、Actions/ruleset 回读和 GitHub Release 使用 `gh` API/CLI。

```bash
python3 scripts/release/skill_release.py plan --version V2.62 --commit <40-hex>

EVIDENCE_DIR=docs/v2.62-release-runtime
mkdir -p "$EVIDENCE_DIR"
SOURCE_COMMIT="$(git rev-parse 'HEAD^{commit}')"
SOURCE_TREE="$(git rev-parse "${SOURCE_COMMIT}^{tree}")"
ROUTE_RECEIPT="$EVIDENCE_DIR/large-release-route.json"
RUNTIME_RECEIPT="$EVIDENCE_DIR/released-runtime-transition.json"
S1_CHECK_RECEIPT="$EVIDENCE_DIR/s1-check-result.json"
AUTH_RECEIPT=docs/v2.62-execution/versions/V2.62/evidence/project-start-authorization-receipt.json
HANDOFF_RECEIPT="${HANDOFF_RECEIPT:?请提供由已安装 V2.6 Codex 宿主签发的 handoff receipt}"
HOST_EXECUTION_ID="${HOST_EXECUTION_ID:?请提供外部宿主 execution ID}"
PYTHON_BIN="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.executable).resolve())')"

"$PYTHON_BIN" -c 'import json, pathlib, sys; from scripts.v250.generation_runtime import load_generation; from scripts.v250.route_closure import compile_route_closure; root=pathlib.Path(".").resolve(); pathlib.Path(sys.argv[1]).write_text(json.dumps(compile_route_closure(root, load_generation(root), "V250-ROUTE-LARGE-RELEASE"), ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")' "$ROUTE_RECEIPT"

"$PYTHON_BIN" scripts/v250/runtime_host_adapter.py launch \
  --stage released --source-commit "$SOURCE_COMMIT" --source-tree "$SOURCE_TREE" \
  --project-size large --route-receipt "$ROUTE_RECEIPT" \
  --authorization-receipt "$AUTH_RECEIPT" \
  --controller-handoff-receipt "$HANDOFF_RECEIPT" \
  --host-execution-id "$HOST_EXECUTION_ID" \
  --adapter-identity local-external-runtime-host \
  --adapter-code scripts/v250/runtime_host_adapter.py > "$RUNTIME_RECEIPT"

./scripts/check.sh --phase release --project-size large \
  --source-commit "$SOURCE_COMMIT" --source-tree "$SOURCE_TREE" \
  --expected-host-execution-id "$HOST_EXECUTION_ID" \
  --released-runtime-receipt "$RUNTIME_RECEIPT" > "$S1_CHECK_RECEIPT"
```

handoff 只能由已安装的 V2.6 Codex 宿主在仓库外签发，仓库代码不生成它。host adapter 会验证
固定 owner SSH 公钥、完整 Current prompt 闭包、route、项目起始授权和 adapter digest，并在获得
真实 child PID 后才传入 launch receipt、校验 child ack；其结果仍只有 I1/correlated assurance。
`S1_CHECK_RECEIPT` 只关闭 S0/S1。后续 S2 必须显式调用一次 `build-release.py`，再用
`skill_release.py validate` 校验同一 asset set；不要对 V2.62 调用兼容命令 `verify`。
实际外部操作必须经 `scripts/v250/github_ssh.py` 的 SSH remote 检查，并由上层发布编排器执行与回读。

## V2.48 Skill 简单发行兼容

V2.48 默认使用 `skill_simple`，入口是 `skill_release.py`。它只做本地 plan/verify 和
release receipt，不执行 GitHub、tag 或正式安装：

```bash
python3 scripts/release/skill_release.py plan --version V2.48 --commit <commit>
python3 scripts/release/skill_release.py verify --version V2.48 --commit <commit>
```

本地验证完成后状态为 `ready_for_publish_approval`。只有用户针对 exact version、commit/tree、
tag、资产 hash 和外部操作做一次明确确认后，才可另行执行 push/tag/GitHub Release 或正式安装。
普通 Skill 发行不使用 CP00–CP18、两阶段签名批准或 nonce authority。
V2.48 GitHub 必需状态检查只有 `check-macos` 与 `release-asset-gate`；
`check-ubuntu` 不属于 small 流程或普通 Skill 发行的合并门禁。

以下 `release.py` 与 CP00–CP18 内容是 V2.46 governed 兼容路径，不是 V2.62
Current Skill 发行默认入口。

- `release.py`：legacy/governed 发行入口；提供 `start`、`doctor`、`prepare`、`promote`、`status`、`recover` 和 `close`，并以 operation 级 `intent -> live readback -> marker-last` 状态恢复。
- `release_config.py`：只加载 Git-tracked 闭集 profile；V2.62 是候选 `skill_simple` profile，V2.6 保持已安装基线直到 atomic cutover，V2.46 保留 governed replay engine。
- `audit-release.py`：不信任 promote-state，依据 live main、peeled tag、Latest Release、重新下载资产、CI 与安装树独立验证五点身份。
- `build-release.py`（internal）：只接受 40 位 lowercase commit SHA，从不可变 Git 对象在临时目录构建并原子 seal；既有同版本 snapshot 不可覆盖。
- `validate-release.py`（internal）：从 frozen commit 独立重建 generated asset，校验来源、完整文件清单、safe tar、哈希、`--package-tree` 与非发行路径隔离。
- `public_scan.py`（internal）：禁用 Git replace 后扫描完整 Git 历史/树、snapshot、tar、固定四资产和 canonical tag/title/body；仅接受 CP05 独立审批绑定的 exact baseline。
- `publish-github-release.sh`（internal adapter）：由统一入口调用；禁止人工绕过 checkpoint、remote lock、exact main lease、Draft 回下载和 immutable readback。

V2.46 固定公开资产只有 `goal-teams-V2.46.tar.gz`、`SHA256SUMS`、`_release.json` 和 `_files.sha256`。完整门禁见 `references/release-packaging-protocol.md`；顺序为 candidate exact-SHA CI → remote lock → tag → verified Draft → exact main CAS → publish-last → published asset install/audit。

## 解释器门禁

不假设系统 `python3` 指向兼容版本。操作者必须显式把 `PYTHON` 设为 Python 3.11+ 可执行文件，再完成 fail-fast 预检：

```bash
PYTHON_BIN="${PYTHON:?请先将 PYTHON 设为 Python 3.11+ 可执行文件的绝对路径}"
"$PYTHON_BIN" -c 'import sys, tomllib; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ required")'
```

## 公开命令与顺序

| 阶段 | 公开命令 | 语义 |
| --- | --- | --- |
| CP00 | `"$PYTHON_BIN" scripts/release/release.py start --input <start.json>` | 从 active profile 的 `develops/v2.46-verification-governance` candidate 创建 state，冻结 scope/profile 并完成 CP00；state 必须写入 canonical root `docs/` |
| CP01 | `"$PYTHON_BIN" scripts/release/release.py promote --input <promote-cp01.json>` | 校验 prior-main/current-release continuity 与 frozen profile；V2.40 历史回放只保留 legacy recovery 验证 |
| CP01 后、CP02 前 | `"$PYTHON_BIN" scripts/release/release.py doctor --input <doctor.json>` | 采集并通过 canonical/candidate/GitHub topology；不接受 caller 伪造 facts |
| CP02–CP08 | `"$PYTHON_BIN" scripts/release/release.py promote --input <promote.json>` | 每次只推进当前 checkpoint，直到 current checkpoint 为 CP09 |
| CP09–CP10 | `"$PYTHON_BIN" scripts/release/release.py prepare --input <prepare.json>` | 双构建一致、独立验证、完整公开面扫描与二次扫描 seal；一次调用仅处理 CP09/CP10 |
| CP11–CP17 | `"$PYTHON_BIN" scripts/release/release.py promote --input <promote.json>` | 从本地 rehearsal 推进到 published-asset install/post-CI/independent audit，仍每次一个 checkpoint |
| CP18 | `"$PYTHON_BIN" scripts/release/release.py close --input <close.json>` | 只能从 canonical root 且 candidate worktree 已移除后执行；外层重算归档 SSOT，候选侧 Completion 必须保持 host-adapter fail-closed，独立 live audit 通过后才完成永久保护与归档 |
| 任意非终态阶段 | `"$PYTHON_BIN" scripts/release/release.py status --input <status.json>` | 只读返回 phase、current checkpoint、actions 和 state SHA；不推进、不触发副作用 |
| 中断恢复 | `"$PYTHON_BIN" scripts/release/release.py recover --input <recover.json>` | 只对当前已持久化 intent 重读/采纳 exact readback；若必须重放外部写入，还要 `resume_external_writes=true` 与原写入授权 |

V2.46 governed 主链是 `start(CP00) → promote(CP01) → doctor(CP02 前必须通过) → promote(CP02–CP08) → prepare(CP09–CP10) → promote(CP11–CP17) → close(CP18)`。它不是 V2.48 默认入口；`status` 是只读旁路，`recover` 是中断恢复旁路。

实际 envelope 的 `state_path` 必须是 canonical root 下 `docs/release-state/V2.46/promotion-state.json` 的绝对路径，不能写 candidate-relative `docs/...`，也不能保留未解析占位值。`start` 从 candidate worktree 运行并把 state 直接写入 canonical root `docs/`；`close` 从 canonical root 运行并读取同一 state。JSON envelope、绝对路径命令示例和 CP00–CP18 细表见 `references/release-packaging-protocol.md`。
