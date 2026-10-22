---
type: regex
arm: with-only
# 指示项：最终回复带轮次进度，例如"进度：第 1 轮/共 2 轮"（允许 Markdown 加粗和半角冒号）。
target: last_message
pattern: '进度\**\s*[：:]\s*\**\s*第\s*\d+\s*轮\s*/\s*共\s*\d+\s*轮'
---
