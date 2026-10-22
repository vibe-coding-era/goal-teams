---
description: 'direct 路径：一个 slug 函数的尾部横杠 bug。期待先 Red 再 Green，不建计划、不派成员；WITH 组的账本只有自动建立的 direct 目标和 gt finish 的达成记录。'
tags: [engineering, direct, tdd]
expected_outcome: 'textkit/slug.py 的 slugify 不再在首尾留下横杠（"Hello World!" → "hello-world"），tests/test_slug.py 新增首尾标点的用例，修复前跑出失败、修复后通过；回复写明 Red/Green 与未验证项。WITH 组：.goal-teams/ledger.jsonl 有 mode=direct 的自动目标和 outcome=achieved 的 goal.finished，没有 plan.applied。'
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, Bash, Edit, Write]
---

`slugify("Hello World!")` 返回了 `hello-world-`，多了个横杠。规则是：全部小写，连续的非字母数字替换成一个横杠，首尾不留横杠。代码在 `textkit/slug.py`，测试在 `tests/test_slug.py`，现在测试全绿（`python3 -m unittest`）。用 Goal Teams 直接修一下就行，不用拆任务、不用派人，但要让我看到先失败再通过的证据。
