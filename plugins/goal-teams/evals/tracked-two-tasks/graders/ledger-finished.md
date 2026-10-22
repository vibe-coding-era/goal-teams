---
type: regex
arm: with-only
# 指示项：收尾用的是 gt finish（唯一完成判定），账本里有 outcome=achieved 的 goal.finished。
target:
  source: file
  path: .goal-teams/ledger.jsonl
pattern: '"outcome":"achieved"[^\n]*"type":"goal.finished"'
---
