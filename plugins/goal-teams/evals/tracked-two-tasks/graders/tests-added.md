---
type: regex
# 结果（两组都计分）：测试覆盖了 char_count（含 spaces=True 的分支）。
target:
  source: file
  path: tests/test_stats.py
pattern: 'char_count\([^\n]*spaces\s*=\s*True'
---
