# Release scripts

## V2.68 两阶段 Skill 发行

V2.68 Development 只运行 TDD 与受影响面增量检查。实现和独立复核完成后，先验证
prepared generation，再以受控 ACTIVE 切换和新会话绑定 V2.68；最终 commit/merge 后，
只从 clean、exact main commit/tree 进入 Release。candidate 或 prepared-active 的加载结果
不能替代正式 released runtime receipt。

正式顺序为 fresh V2.68 runtime → S0 → S1 全量回归及独立安全审核 → 单次 S2 →
独立 repository boundary → 适用 S3 → Actions S4 plan → 独立 S4 发布、安装与 exact readback。
S1 由 `scripts/checks/check-v268.py --phase release` 对同一冻结身份执行；
当前测试根是 `tests/v250` 和 `tests/v268`，前驱 `tests/v267` 调用数为 0。

本次 medium 发行的 S3 为 `not_required`，安装生命周期进程调用数为 0；风险高或需要
外部写入不将 medium 自动升级成 large。正式本地更新仍在后续 S4 中执行。S2 每个 exact
asset set 只构建一次，不做第二构建、逐字节复现比较或 S2 安全检查；恢复时复用同一四资产。

S4 复用项目开始时已取得的授权，不再次要求签名或过程确认。Git fetch/push/tag transport
使用 SSH；PR、Actions 与 Release 使用已认证的 `gh` API/CLI。根 README 两份由人类维护；
过程记录保留在主仓 `docs/v268-release`，不提交、装包或上传该目录。

### 实际已安装 V2.67 前态

本地捕获必须读取真实安装 state 和受管文件，校验文件集合、hash、size、mode、版本和
前驱 Release 身份。额外文件、symlink、缺失或摘要不匹配必须失败；不能由仓库中的
predecessor identity 合成一份“已安装”receipt。以下在主仓根运行，`authorization.json`
是本项目已经锁定的真实授权，不是手写示例：

~~~bash
export PYTHONDONTWRITEBYTECODE=1
PYTHON_BIN="${PYTHON:?设置已预检的 Python 3.11+ 可执行文件绝对路径}"
V268_EVIDENCE_DIR=docs/v268-release
V268_CODE_HOME="${CODEX_HOME:-$HOME/.codex}"
V268_AUTH_RECEIPT="$V268_EVIDENCE_DIR/authorization.json"
V268_PREDECESSOR_RECEIPT="$V268_EVIDENCE_DIR/installed-predecessor-observation.json"
mkdir -p "$V268_EVIDENCE_DIR"

"$PYTHON_BIN" scripts/v268/installed_predecessor.py \
  --installation-root "$V268_CODE_HOME/skills/goal-teams" \
  --state-path "$V268_CODE_HOME/state/goal-teams/current.json" \
  --authorization-receipt "$V268_AUTH_RECEIPT" \
  --expected-identity references/current/generations/V2.68/contracts/predecessor-release-identity.json \
  > "$V268_PREDECESSOR_RECEIPT"
~~~

传给 Actions 的只是一份授权绑定的 compact I1/correlated 报告，包含实际 readback 摘要，
不含文件正文、凭证或本机绝对路径。远端能够验证该报告与授权、版本、前驱身份的绑定，
不因此获得“独立读取本机安装字节”的证明。历史观察的 `captured_at` 保留原值；
本次 fresh handoff 的 `issued_at/expires_at` 和 child launch 单独记录，不改写观察时间续期。

### Medium route 派生与 fresh runtime 接口

下面展示已有 API 的本地调用形式，供授权编排器使用；只有 scope 已实现、冻结 source
已确认、V2.68 已成为 ACTIVE 时，才能将事实设为 released。它不是另行执行第二份 S1/S2
的许可。正式发行工作流会以自己的 exact SHA/run/attempt 重新生成同类 route triplet。

~~~bash
SOURCE_COMMIT="$(git rev-parse 'HEAD^{commit}')"
SOURCE_TREE="$(git rev-parse "${SOURCE_COMMIT}^{tree}")"
ROUTE_FACTS_RECEIPT="$V268_EVIDENCE_DIR/medium-release-route-facts.json"
DERIVED_ROUTE_RECEIPT="$V268_EVIDENCE_DIR/medium-release-route-derived.json"
ROUTE_RECEIPT="$V268_EVIDENCE_DIR/medium-release-route-closure.json"
RUNTIME_RECEIPT="$V268_EVIDENCE_DIR/released-runtime-transition.json"
HOST_EXECUTION_ID="${HOST_EXECUTION_ID:?绑定实际宿主执行 ID}"

"$PYTHON_BIN" - \
  "$ROUTE_FACTS_RECEIPT" "$DERIVED_ROUTE_RECEIPT" "$ROUTE_RECEIPT" \
  "$SOURCE_COMMIT" "$SOURCE_TREE" "$V268_AUTH_RECEIPT" <<'PY'
import json
import pathlib
import sys

from scripts.v250.generation_runtime import canonical_json_digest, load_generation
from scripts.v250.route_closure import compile_derived_route_closure
from scripts.v250.route_derivation import derive_route

root = pathlib.Path.cwd()
authorization = json.loads(pathlib.Path(sys.argv[6]).read_text(encoding="utf-8"))
facts_source = {
    "schema_version": "goal-teams-project-route-facts-source-v2.68",
    "repository": "vibe-coding-era/goal-teams",
    "source_commit": sys.argv[4],
    "source_tree": sys.argv[5],
    "project_start_authorization_receipt_sha256": canonical_json_digest(authorization),
}
project_route_facts = {
    "project_size": "medium",
    "workflow_phase": "release",
    "stage": "released",
    "release_intent": True,
    "implementation_scope_complete": True,
    "risk": "high",
    "failure_consequence": "high",
    "reversibility": "partially_reversible",
    "compliance": "none",
    "external_write": True,
    "security_sensitive": True,
    "ui_or_desktop": False,
    "agent_runtime": True,
    "environment_check_required": True,
    "authorization_state": "granted",
    "facts_source_sha256": canonical_json_digest(facts_source),
}
derived_route = derive_route(project_route_facts, generation_id="V2.68")
receipt = compile_derived_route_closure(root, load_generation(root), derived_route)

def write_json(path, value):
    pathlib.Path(path).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

write_json(sys.argv[1], {
    "facts_source": facts_source,
    "project_route_facts": project_route_facts,
    "project_route_facts_sha256": canonical_json_digest(project_route_facts),
})
write_json(sys.argv[2], derived_route)
write_json(sys.argv[3], receipt)
PY

"$PYTHON_BIN" scripts/v268/runtime_host_adapter.py launch \
  --stage released --source-commit "$SOURCE_COMMIT" --source-tree "$SOURCE_TREE" \
  --project-size medium \
  --route-facts-receipt "$ROUTE_FACTS_RECEIPT" \
  --derived-route-receipt "$DERIVED_ROUTE_RECEIPT" \
  --route-receipt "$ROUTE_RECEIPT" \
  --authorization-receipt "$V268_AUTH_RECEIPT" \
  --predecessor-observation-receipt "$V268_PREDECESSOR_RECEIPT" \
  --host-execution-id "$HOST_EXECUTION_ID" \
  --adapter-identity local-runtime-host \
  --adapter-code scripts/v268/runtime_host_adapter.py \
  > "$RUNTIME_RECEIPT"
~~~

必须使用必填的 `--predecessor-observation-receipt`。launcher 验证实际前态报告后，
通过真实 Popen 获得 child PID，再经 stdin 传入 launch 合同并校验 child ACK；新 child
读取 exact source 的 V2.68 Current 输入。这里不要求 SSH 签名；加载证明仍为 I1/correlated，
不声称宿主强制拦截、外部独立或 Provider 最终 prompt assembly 已验证。

### Actions continuation 与独立 S4

受保护 merge 完成、remote main 与冻结 SHA 一致后，同一次正式发行使用下列已存在
workflow 输入。发送的是两个明确的 JSON payload，不上传整个本地 docs 目录：

~~~bash
gh workflow run release-gate.yml --ref main \
  -f workflow_phase=release \
  -f project_size=medium \
  -F project_start_authorization_receipt_json=@"$V268_AUTH_RECEIPT" \
  -F predecessor_observation_receipt_json=@"$V268_PREDECESSOR_RECEIPT"
~~~

Actions 只在明确 release dispatch 下依次生成 fresh runtime、S0/S1、一次 S2、同资产
validation、独立 boundary、medium 的 not-required S3 和 S4 authorized-operation plan。
S1 receipt 的整体 Release control 仍为 incomplete；不能把 S1 passed 或 Actions 绿色直接
表述成已发布。Actions 中外部 S4 写入数为 0。

官方 continuation artifact 名为 `goal-teams-v268-release-<exact released SHA>`。必须核验
workflow run ID/attempt、SHA 和 `ready_for_s4` checkpoint，并将同一四资产及完整
`_receipts` 恢复到主仓 `release/versions/V2.68`。四公开资产仅为
`goal-teams-V2.68.tar.gz`、`SHA256SUMS`、`_release.json`、`_files.sha256`；
`installed-predecessor-observation.json` 随官方 continuation 的 receipt 链保存，不是新增
GitHub Release 公开资产。诊断 artifact 不能替代 ready continuation，下载后重建调用数为 0。

完成官方 artifact 身份与布局核验后，由独立 successor 在 clean exact source 主仓运行：

~~~bash
V268_RECEIPT_ROOT=release/versions/V2.68/_receipts
V268_RUN_ID="${V268_RUN_ID:?使用已核验的官方 workflow run ID}"
V268_RUN_ATTEMPT="${V268_RUN_ATTEMPT:?使用同次官方 workflow run attempt}"

"$PYTHON_BIN" scripts/v268/s4_executor.py \
  --version V2.68 \
  --commit "$SOURCE_COMMIT" \
  --release-control-receipt "$V268_RECEIPT_ROOT/release-control.json" \
  --checkpoint-receipt "$V268_RECEIPT_ROOT/_checkpoint.json" \
  --receipt-root "$V268_RECEIPT_ROOT" \
  --release-root release/versions \
  --expected-workflow-run-id "$V268_RUN_ID" \
  --expected-workflow-run-attempt "$V268_RUN_ATTEMPT" \
  > "$V268_EVIDENCE_DIR/s4-outcome.json"
~~~

S4 复用开始授权，在每项外部操作前重验链、来源、边界和 SSH remote；执行或恢复 tag、
Release、资产上传及正式本地更新，并逐项 exact readback。已确认操作不重复执行，仅推进
未确认后继。发布、安装、Current 投影各自记录状态；后置文档投影不移动已发布 tag、不覆盖
旧资产、不把新维护 commit 伪装成原 released SHA。

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

以下 `release.py` 与 CP00–CP18 内容是 V2.46 governed 兼容路径，不是 V2.68
Current Skill 发行默认入口。

- `release.py`：legacy/governed 发行入口；提供 `start`、`doctor`、`prepare`、`promote`、`status`、`recover` 和 `close`，并以 operation 级 `intent -> live readback -> marker-last` 状态恢复。
- `release_config.py`：只加载 Git-tracked 闭集 profile；V2.68 是当前 `skill_simple` profile，V2.67 是此次更新的已发布安装前态；V2.46 保留 governed replay engine。
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
