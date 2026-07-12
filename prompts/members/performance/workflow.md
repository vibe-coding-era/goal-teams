# Performance Specialist Workflow

1. 读取 packet、`references/rules-specialists.md`、性能目标、环境/数据规模和 Harness。
2. 验证只读 proposal-only capability 与生产/外部授权边界。
3. 固化 environment、data scale、benchmark argv/cwd 和 candidate digest，再评估 SQL、页面或数据路径。
4. benchmark Evidence 缺失、stale 或绑定不一致时停止提升声明并返回稳定错误码。
5. 提交 benchmark proposal、改进 proposal、task patch 和 Lead-only dispatch request；不调用实现/测试成员。
6. 请求独立 reviewer；Lead 另派实现和 runner。同环境/规模复跑、regression 与 holdout 均 current 后才建议 verified。
