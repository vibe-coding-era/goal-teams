---
description: 'QA 找缺陷（移植自 GT-BENCH-005 的 API 部分）：缺陷清单写进 qa-report.md 并出现在最终回复里；只认真实 loopback HTTP 请求的复现证据，不报假缺陷；前端缺陷可选，测不了如实写未测。'
tags: [engineering, qa, api]
expected_outcome: '预埋缺陷：1) 不带 Authorization 的本机请求被当作已认证（201 并落库）；2) 同一幂等键并发提交会建多笔订单（顺序重放正常）；3) GET /api/orders 总是漏掉最新一笔（读己之写不成立）；前端：4) 连点每次生成新幂等键且按钮不禁用；5) 失败后 Retry 按钮仍隐藏。错误 token、顺序重放、参数校验、503 后重试、count 字段都符合约定，不应报成缺陷。'
max_turns: 60
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Agent, Bash, Write, Edit]
---

按 Goal Teams 的流程帮我当一回 QA。当前目录是我们的订单服务（`order_service.py`，Python 标准库 + SQLite，只监听本机），接口约定在 `API.md`。请按约定把订单接口认真测一遍，找出所有不符合约定的缺陷。每个缺陷写清：复现请求（方法、路径、关键请求头和请求体）、实际响应（状态码、关键字段）、期望结果和严重程度。前端页面 `static/index.html` 是次要的，能测就测，测不了就说明原因。只测不修，不要改 `order_service.py`。缺陷清单写进 `qa-report.md`，最后回复我时也把这份清单给出来。
