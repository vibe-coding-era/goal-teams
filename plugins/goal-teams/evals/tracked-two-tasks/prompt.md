---
description: 'tracked 路径：两个互不重叠的小功能，用户明确要求计划与分工。期待一份 plan.json 一次 apply、两个任务各自 Red→Green、gt finish 收尾；gt 调用不超过 12 次。'
tags: [engineering, tracked, plan]
expected_outcome: 'textkit/stats.py 新增 char_count(text, spaces=False)；textkit/cli.py 的 count 子命令支持 --chars；tests/ 覆盖两者且全部通过。WITH 组：账本有一条含 T1、T2 的 plan.applied 和 outcome=achieved 的 goal.finished；gt 调用 ≤ 12 次。回复分清已验证与未验证。'
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Agent, Bash, Edit, Write]
---

给 `textkit` 加两个功能，用 Goal Teams 的 tracked 流程做，先给我计划（两个任务、谁负责、怎么验收），然后执行：

1. `textkit/stats.py` 增加 `char_count(text, spaces=False)`：统计字符数，默认不计空白；`spaces=True` 时计入。
2. `python3 -m textkit.cli count <文件>` 增加 `--chars` 选项，输出字符数（规则同上，默认不计空白）。

两件事互不重叠，可以分开做。现有测试 `python3 -m unittest` 全绿，完成后也要全绿。
