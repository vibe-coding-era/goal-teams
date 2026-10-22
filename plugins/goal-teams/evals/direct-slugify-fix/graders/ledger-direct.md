---
type: regex
arm: with-only
# 指示项：direct 路径不手动建目标——账本里的 goal 事件是第一条取证命令自动建立的（"auto":true，mode direct）。
# 账本每行一条规范 JSON（键排序）；"auto" 排在 "mode" 前。
target:
  source: file
  path: .goal-teams/ledger.jsonl
pattern: '"auto":true[^\n]*"mode":"direct"[^\n]*"type":"goal"'
---
