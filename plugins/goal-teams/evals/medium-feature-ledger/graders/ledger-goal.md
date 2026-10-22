---
type: regex
arm: with-only
# 指示项：gt 账本已建立，并按 medium（或 large）记下目标。直接读账本文件，不看工具调用：
# 成员子代理里的 Bash 调用不一定出现在主轨迹，账本才是 gt 实际写下的记录。
# 账本每行一条规范 JSON（键排序），data 在前、"type" 在最后；两种键序都接受。
target:
  source: file
  path: .goal-teams/ledger.jsonl
pattern: '"size":"(?:medium|large)"[^\n]*"type":"goal"|"type":"goal"[^\n]*"size":"(?:medium|large)"'
---
