# Goal Teams 发布打包规范

## Objective

任何 GitHub Release 都必须先在本地 `release/versions/<VERSION>/` 形成完整、可复现、已校验的发行目录；未经本地门禁通过，不得创建 tag 或上传发行资产。

## Key Results

1. 冻结唯一 `VERSION`、Git ref 与 commit，发行内容只从该 commit 和 `scripts/install/package-manifest.txt` 生成。
2. 先运行仓库质量门禁，再执行 `python3 scripts/release/build-release.py --version <VERSION> --ref <REF>`。
3. 发行目录必须包含纯发行文件、`_release.json`、`_files.sha256`、`_artifacts/goal-teams-<VERSION>.tar.gz` 与 `_artifacts/SHA256SUMS`。
4. `docs/`、过程包、根 PRD、输出物和本地状态不得进入发行包；历史与过程资料只能归档到根 `docs/archive/releases/<VERSION>/`。
5. `python3 scripts/release/validate-release.py --version <VERSION>` 必须通过，才可运行 `scripts/release/publish-github-release.sh <VERSION>`。
6. 发布脚本必须校验 tag 指向、拒绝覆盖既有 GitHub Release，并在上传后重新下载压缩包；下载的 `SHA256SUMS` 必须与本地冻结凭证逐字节一致，再核对资产 SHA-256。
7. 任一门禁失败即停止发布；不得以人工口头确认替代脚本证据。

## Release Gate

```bash
./scripts/check.sh
python3 scripts/release/build-release.py --version V2.38 --ref codex/v2.38
python3 scripts/release/validate-release.py --version V2.38
scripts/release/publish-github-release.sh V2.38
```

GitHub 只接收已经在本地 `release/versions/<VERSION>/` 验证通过的同一份资产。发布脚本随后更新本地安装，并把 GitHub 元数据、安装日志和 post-release 凭证保存在根 `docs/archive/releases/<VERSION>/release-evidence/`，不放进发行包。若上传阶段失败但 tag 已推送，只允许在确认 tag 仍指向 `_release.json.source_commit` 且 GitHub Release 不存在后重跑；不得移动或覆盖 tag。
