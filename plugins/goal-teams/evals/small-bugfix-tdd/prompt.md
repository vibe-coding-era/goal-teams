---
description: '小 bug 修复（Goal Teams 快速通道）：先补回归测试并亲眼看到它失败（Red），再改代码（Green），汇报证据和未验证项。'
tags: [engineering, small, tdd]
expected_outcome: 'shop/shipping.py 改为达到 9900 分即包邮；tests/test_shipping.py 新增 99.00 元边界用例，先于源码修改写入，修复前跑出失败、修复后通过；回复写明 Red/Green 的命令与结果和未验证项。'
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, Bash, Edit, Write]
---

线上有个 bug：我们的规则是订单满 99 元包邮，但有客户反馈刚好买了 99 元的订单还是被收了 8 块运费。运费逻辑在 `shop/shipping.py`，对应测试在 `tests/test_shipping.py`，现在测试是全绿的（`python3 -m unittest`）。用 Goal Teams 的快速通道帮我修一下，别让它再犯。
