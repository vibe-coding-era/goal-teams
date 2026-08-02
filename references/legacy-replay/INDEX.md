# Goal Teams Legacy Replay

本目录只提供显式、只读、隔离的历史机器合同回放入口，不参与 Current route、Prompt plan、完成判定或发行门禁。

约束：

- 只有可信 `explicit_intent=true` 或已识别历史 artifact 才能选择 `legacy_version`。
- runner 只执行 manifest 声明的 digest 校验操作；不继承环境、不启动子进程、不访问网络、不写文件。
- 所有历史路径使用 exact repo-relative path 与 SHA-256；路径或 digest 漂移返回历史失败。
- `generations/V2.48/snapshot/` 是从冻结 commit/tree 逐字节提取的 38 成员 rollback 快照；`references/current/generations/V2.48/activation-manifest.json` 只指向该隔离根，不复用已被 V2.50 改写的共享路径。
- Replay manifest 的 raw SHA-256 与 allowlist digest 必须同时由 `ACTIVE` activation 绑定；只修改 Replay manifest 和其自报 digest 不能生效。
- 输出状态只允许 `historical_passed`、`historical_failed`、`replay_unavailable`。
- Replay verdict 永远不能满足 Current 的 `accepted`、release-ready 或 `achieved`。

首批 manifest 保留一个冻结兼容样本；新增版本必须先补齐 exact closure、fixture、digest 和预期 verdict，禁止使用目录通配符。
