---
type: regex
# 结果（两组都计分）：tests/test_store.py 覆盖了 low_stock()（原文件没有）。
target:
  source: file
  path: tests/test_store.py
pattern: 'low_stock\s*\('
---
