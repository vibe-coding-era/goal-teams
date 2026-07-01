---
type: Doc Capsule Template
title: Doc Capsule OKF 模板
description: 读完源文档后的最小 OKF 摘要模板。
tags: [goal-teams, okf, doc-capsule]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Doc Capsule

读完任何源文档后压缩成：

```text
Doc Capsule（文档摘要）:
- source:
- decision:
- must_do:
- must_not_do:
- test_refs:
- doc_update_refs:
- open_questions:
```

有长期价值的摘要写入输出目录的 `doc-capsules.jsonl` 或 `memory.md`。没有用户指定生成目录时，输出目录为 `GoalTeamsWork-<project_version>/`。
