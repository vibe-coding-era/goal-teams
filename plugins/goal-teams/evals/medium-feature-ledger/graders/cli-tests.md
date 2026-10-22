---
type: regex
# 结果（两组都计分）：tests/test_cli.py 覆盖了 low-stock 子命令（原文件没有）。
target:
  source: file
  path: tests/test_cli.py
pattern: 'low-stock'
---
