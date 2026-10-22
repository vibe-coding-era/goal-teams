---
type: regex
arm: with-only
# 指示项：汇报由 gt report 从账本生成（每次 gt report 都会追加一条 report 事件），而不是手写看板。
target:
  source: file
  path: .goal-teams/ledger.jsonl
pattern: '"type":"report"'
---
