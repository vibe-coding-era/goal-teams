---
type: regex
# 结果（两组都计分）：CLI 注册了 low-stock 子命令，并支持 --json。
target:
  source: file
  path: inventory/cli.py
pattern: '^(?=[\s\S]*--json)[\s\S]*add_parser\(\s*.low-stock.'
---
