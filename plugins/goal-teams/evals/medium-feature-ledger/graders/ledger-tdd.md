---
type: regex
arm: with-only
# 指示项：账本里有成立的 Red（tdd.red，outcome red_verified 或 red_observed），之后的某一行有成立的 Green（tdd.green，outcome green_ok）。
# gt 只在同一任务已有成立的 Red、测试文件未变且源码确实变了时才记 green_ok，所以这一对就是"先红后绿"。
# red_unexpected_pass / red_expect_mismatch / green_failed 等不成立的回执都不算。
target:
  source: file
  path: .goal-teams/ledger.jsonl
pattern: '(?:"outcome":"red_(?:verified|observed)"[^\n]*"type":"tdd\.red"|"type":"tdd\.red"[^\n]*"outcome":"red_(?:verified|observed)")[^\n]*\n[\s\S]*?(?:"outcome":"green_ok"[^\n]*"type":"tdd\.green"|"type":"tdd\.green"[^\n]*"outcome":"green_ok")'
---
