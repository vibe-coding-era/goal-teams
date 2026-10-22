---
type: regex
# 结果（两组都计分）：最终回复本身就带着缺陷清单（不能只写"见 qa-report.md"或只发 gt 汇报）——
# 至少一条针对 /api/orders 的请求（方法 + 路径或 URL），以及 201 或 401 这类实际状态码。
target: last_message
pattern: '^(?=[\s\S]*\b(?:201|401)\b)[\s\S]*?\b(?:POST|GET)\b[^\n]{0,160}/api/orders'
---
