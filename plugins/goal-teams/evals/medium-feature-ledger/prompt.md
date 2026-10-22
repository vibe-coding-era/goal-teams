---
description: '中型需求按 Goal Teams 团队流程交付。两组都计分：功能、测试、README 落地，汇报证明测试先红后绿、如实分清已验证/未验证；gt 账本（Red/Green 回执、report 事件）与六字段报告只作 WITH 组指示项。'
tags: [engineering, medium, team]
expected_outcome: 'store.low_stock()、CLI low-stock 子命令（含 --json）、--reorder-level、老数据兼容、tests/test_store.py 与 tests/test_cli.py 的新测试、README 用法；汇报给出实现前失败、实现后通过的证据和未验证项。WITH 组的 .goal-teams/ledger.jsonl 应有 medium 目标、成立的 tdd.red（red_verified/red_observed）之后的 tdd.green(green_ok) 和 report 事件，最终回复是 gt report 输出。'
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Agent, Bash, Edit, Write]
---

用 goal teams 按团队流程交付这个需求。项目就是当前目录（只用 Python 标准库，测试跑 `python3 -m unittest`）。

需求：库存低于补货阈值时能查出来。
1. 商品新增补货阈值 `reorder_level`（整数，默认 0）；`add` 命令支持 `--reorder-level N`。
2. `InventoryStore.low_stock()` 返回 `quantity <= reorder_level` 的商品，按 SKU 排序。
3. 新增 `low-stock` 子命令：默认每行输出 `SKU<TAB>数量<TAB>阈值<TAB>名称`；加 `--json` 时输出 JSON 数组。
4. 老数据文件（比如 `data/sample-inventory.json`）没有 `reorder_level` 字段，必须照常读取，并按 0 处理。
5. 测试按现有结构补到 `tests/test_store.py` 和 `tests/test_cli.py`，README 补上用法。

做完给我一份交付汇报。
