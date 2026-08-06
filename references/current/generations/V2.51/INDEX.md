# Goal Teams V2.51 Current Generation

本目录是 V2.51 Current generation 的人类导航投影。规范语义只存在于 Owner Markdown；`rule-manifest.json` 与本文件不得覆盖 Owner。

加载顺序固定为：

1. `core.md`
2. `routing.md`
3. `assurance-levels.md`
4. route 命中的 `functions/*`
5. route 命中的 `contracts/*`

机器入口：

- `activation-manifest.json`：冻结 generation 成员与 digest。
- `.github/workflows/*` 是仓库侧、不可安装的 CI 控制面，明确不属于 generation root；它由 exact source/tree、V2.51 release profile 与 command contract 单独绑定，不能表述为 ACTIVE 全仓绑定。
- `rule-manifest.json`：稳定 rule ID、唯一 Owner、依赖与 route membership 投影。
- `prompt-manifest.json`：route ordered refs、Gate 与复杂度预算投影。

Owner 清单：

- Core：`CORE-V250`
- Routing：`ROUTING-V250`
- Assurance：`ASSURANCE-V250`
- Functions：Requirements、Architecture/Implementation、Testing、UI/Desktop、Agent Runtime、Release Operations
- Contracts：Task State、Test Case Gate、Harness/Evidence、Review/Completion、Approval/Side Effects

历史回放不属于 Current 优先级或 Prompt plan；只有可信显式 replay dispatch 才进入隔离只读 runner。
