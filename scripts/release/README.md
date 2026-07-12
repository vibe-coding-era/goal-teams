# Release scripts

- `build-release.py`：从冻结 Git ref 生成纯净发行目录和可复现压缩包。
- `validate-release.py`：校验来源 commit、文件清单、哈希、压缩包及非发行路径隔离。
- `publish-github-release.sh`：校验后创建/push tag、上传 GitHub Release，并下载复核 SHA-256。

完整门禁见 `references/release-packaging-protocol.md`。发布顺序不可颠倒。
