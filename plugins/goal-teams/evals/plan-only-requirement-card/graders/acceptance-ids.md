---
type: regex
# 结果：验收标准带稳定编号，例如 AC-01、AC1、AC-ROOM-2、验收-3。
target: last_message
pattern: '\bAC[-_.]?(?:[A-Za-z]+[-_.])?\d+|验收(?:标准)?[-_]\d+'
---
