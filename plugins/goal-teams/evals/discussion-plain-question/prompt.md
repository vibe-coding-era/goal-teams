---
description: '纯技术问答：直接、简洁地答对；不出执行看板或轮次进度，不跑命令，不派成员。'
tags: [discussion, smoke]
expected_outcome: '讲清 no-store 与 no-cache 的区别、ETag 的作用，并给出静态资源和接口的配置建议。'
max_turns: 8
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

问一下：HTTP 缓存里 `Cache-Control: no-cache` 和 `no-store` 到底有什么区别？我们前端的静态资源和接口响应分别该怎么配？顺便讲讲 ETag 在里面起什么作用，简单说说就行。
