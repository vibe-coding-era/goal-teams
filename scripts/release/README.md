# Release scripts

- `release.py`：唯一公开发行入口；提供 `start`、`doctor`、`prepare`、`promote`、`status`、`recover` 和 `close`，并以 operation 级 `intent -> live readback -> marker-last` 状态恢复。
- `release_config.py`：只加载 Git-tracked 闭集 profile；V2.45 为 active，V2.44/V2.40 为 historical replay 且不能执行 external write。
- `audit-release.py`：不信任 promote-state，依据 live main、peeled tag、Latest Release、重新下载资产、CI 与安装树独立验证五点身份。
- `build-release.py`（internal）：只接受 40 位 lowercase commit SHA，从不可变 Git 对象在临时目录构建并原子 seal；既有同版本 snapshot 不可覆盖。
- `validate-release.py`（internal）：从 frozen commit 独立重建 generated asset，校验来源、完整文件清单、safe tar、哈希、`--package-tree` 与非发行路径隔离。
- `public_scan.py`（internal）：禁用 Git replace 后扫描完整 Git 历史/树、snapshot、tar、固定四资产和 canonical tag/title/body；仅接受 CP05 独立审批绑定的 exact baseline。
- `publish-github-release.sh`（internal adapter）：由统一入口调用；禁止人工绕过 checkpoint、remote lock、exact main lease、Draft 回下载和 immutable readback。

V2.45 固定公开资产只有 `goal-teams-V2.45.tar.gz`、`SHA256SUMS`、`_release.json` 和 `_files.sha256`。完整门禁见 `references/release-packaging-protocol.md`；顺序为 candidate exact-SHA CI → remote lock → tag → verified Draft → exact main CAS → publish-last → published asset install/audit。

## 解释器门禁

不假设系统 `python3` 指向兼容版本。操作者必须显式把 `PYTHON` 设为 Python 3.11+ 可执行文件，再完成 fail-fast 预检：

```bash
PYTHON_BIN="${PYTHON:?请先将 PYTHON 设为 Python 3.11+ 可执行文件的绝对路径}"
"$PYTHON_BIN" -c 'import sys, tomllib; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ required")'
```

## 公开命令与顺序

| 阶段 | 公开命令 | 语义 |
| --- | --- | --- |
| CP00 | `"$PYTHON_BIN" scripts/release/release.py start --input <start.json>` | 从 active profile 的 `develops/v2.45-release-engineer` candidate 创建 state，冻结 scope/profile 并完成 CP00；state 必须写入 canonical root `docs/` |
| CP01 | `"$PYTHON_BIN" scripts/release/release.py promote --input <promote-cp01.json>` | 校验 prior-main/current-release continuity 与 frozen profile；V2.40 历史回放只保留 legacy recovery 验证 |
| CP01 后、CP02 前 | `"$PYTHON_BIN" scripts/release/release.py doctor --input <doctor.json>` | 采集并通过 canonical/candidate/GitHub topology；不接受 caller 伪造 facts |
| CP02–CP08 | `"$PYTHON_BIN" scripts/release/release.py promote --input <promote.json>` | 每次只推进当前 checkpoint，直到 current checkpoint 为 CP09 |
| CP09–CP10 | `"$PYTHON_BIN" scripts/release/release.py prepare --input <prepare.json>` | 双构建一致、独立验证、完整公开面扫描与二次扫描 seal；一次调用仅处理 CP09/CP10 |
| CP11–CP17 | `"$PYTHON_BIN" scripts/release/release.py promote --input <promote.json>` | 从本地 rehearsal 推进到 published-asset install/post-CI/independent audit，仍每次一个 checkpoint |
| CP18 | `"$PYTHON_BIN" scripts/release/release.py close --input <close.json>` | 只能从 canonical root 且 candidate worktree 已移除后执行；外层重算归档 SSOT，候选侧 Completion 必须保持 host-adapter fail-closed，独立 live audit 通过后才完成永久保护与归档 |
| 任意非终态阶段 | `"$PYTHON_BIN" scripts/release/release.py status --input <status.json>` | 只读返回 phase、current checkpoint、actions 和 state SHA；不推进、不触发副作用 |
| 中断恢复 | `"$PYTHON_BIN" scripts/release/release.py recover --input <recover.json>` | 只对当前已持久化 intent 重读/采纳 exact readback；若必须重放外部写入，还要 `resume_external_writes=true` 与原写入授权 |

V2.45 active 主链是 `start(CP00) → promote(CP01) → doctor(CP02 前必须通过) → promote(CP02–CP08) → prepare(CP09–CP10) → promote(CP11–CP17) → close(CP18)`。`status` 是只读旁路，`recover` 是中断恢复旁路，两者都不是需要顺序执行的新 checkpoint。

实际 envelope 的 `state_path` 必须是 canonical root 下 `docs/release-state/V2.45/promotion-state.json` 的绝对路径，不能写 candidate-relative `docs/...`，也不能保留未解析占位值。`start` 从 candidate worktree 运行并把 state 直接写入 canonical root `docs/`；`close` 从 canonical root 运行并读取同一 state。JSON envelope、绝对路径命令示例和 CP00–CP18 细表见 `references/release-packaging-protocol.md`。
