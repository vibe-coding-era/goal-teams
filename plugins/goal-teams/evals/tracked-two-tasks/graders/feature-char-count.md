---
type: regex
# 结果（两组都计分）：stats.py 有 char_count，且带 spaces 参数（默认不计空白）。
target:
  source: file
  path: textkit/stats.py
pattern: 'def char_count\(\s*text\s*,\s*spaces\s*=\s*False\s*\)'
---
