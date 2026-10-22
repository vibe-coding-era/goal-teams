---
type: regex
arm: with-only
# 指示项：direct 不建计划、不派任务包——账本里不该出现 plan.applied 或 task.packet 之类的仪式。
target:
  source: file
  path: .goal-teams/ledger.jsonl
match: not_contains
pattern: '"type":"plan\.applied"|"type":"plan\.freeze"'
---
