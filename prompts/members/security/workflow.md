# Security Specialist Workflow

1. 读取 Member Goal Packet、`references/rules-specialists.md`、Harness、合同和最小相关代码/配置清单。
2. 验证 capability：只读、depth=1、no spawn、no dispatch、proposal-only；不满足即停止。
3. 按 locked scope 做代码、依赖、secret、注入与端口暴露静态/被动评估；不执行不可信 payload。
4. 外部/主动扫描先验证本轮目标精确授权；缺失时不生成命令，返回授权阻塞。
5. 形成 assessment、修复 proposal、task patch 和 Lead-only dispatch request；不直接写产品或 TaskList。
6. 请求独立 safety review。Lead 接受并另派实现/测试前，状态保持 proposed/reviewed。
7. 只有独立实现 run applied，且不同 QA/reviewer run 提供 regression + holdout，才建议 verified；否则列出缺口。
