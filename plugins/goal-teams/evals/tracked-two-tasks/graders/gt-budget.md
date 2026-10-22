---
type: tool_used
arm: with-only
# 指示项：两任务流程的 gt 调用不超过 12 次（目标 ≤ 10；goal、plan apply、2×red、2×green、finish、review、finish）。
# 子代理里的调用不在主轨迹，所以这里只约束 Lead 自己的调用。
tool: Bash
input_match: 'gt\.py'
max: 12
---
