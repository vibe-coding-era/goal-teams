---
type: regex
# 结果（两组都计分）：CLI 的 count 子命令接受 --chars。
target:
  source: file
  path: textkit/cli.py
pattern: '"--chars"|\x27--chars\x27'
---
