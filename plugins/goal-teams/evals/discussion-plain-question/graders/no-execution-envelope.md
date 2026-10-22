---
type: regex
# 讨论类回复不应出现执行汇报的固定标记：六字段报告、任务看板、轮次进度。
target: last_message
match: not_contains
pattern: 'Banchmark|Benchmark[：:]|进度\**\s*[：:]\s*\**\s*第|◆\s*Goal-Teams|任务执行看板|下一轮 LOOP'
---
