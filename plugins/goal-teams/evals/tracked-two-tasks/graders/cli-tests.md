---
type: regex
# 结果（两组都计分）：CLI 测试覆盖了 --chars。
target:
  source: file
  path: tests/test_cli.py
pattern: '"--chars"|\x27--chars\x27'
---
