---
type: regex
arm: with-only
# 指示项：计划一次写入——账本里有一条 plan.applied，它的 tasks 里同时有两个任务 id。
# 账本每行一条规范 JSON（键排序）："data" 在 "type" 前，tasks 列表里每个任务的 "id" 在前。
target:
  source: file
  path: .goal-teams/ledger.jsonl
pattern: '"tasks":\[\{[^\n]*"id":"[^"]+"[^\n]*\{[^\n]*"id":"[^"]+"[^\n]*"type":"plan\.applied"'
---
