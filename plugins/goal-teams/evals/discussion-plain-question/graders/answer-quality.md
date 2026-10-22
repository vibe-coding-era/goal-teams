---
type: llm
---

评审对象：助手对"HTTP 缓存里 no-cache、no-store 和 ETag"这个问题的最终回复。

PASS（需同时满足）：
1. 说对 no-store：响应不得被任何缓存（包括浏览器）存储。
2. 说对 no-cache：可以存储，但每次使用前必须先向服务器验证；没有把它说成"不缓存"或等同于 no-store。
3. 说对 ETag：作为验证器，配合 If-None-Match 发条件请求，内容未变时返回 304 Not Modified、不带响应体。
4. 给出贴合问题的配置建议：带内容哈希的静态资源用长 max-age（可加 immutable），HTML 入口用 no-cache；敏感或个性化接口用 no-store（或 private），其他接口可用 no-cache 或短 max-age 配合 ETag。具体取值可以不同，方向正确即可。
5. 简洁直接：回复本身就是答案，没有任务看板、轮次进度、成员分工、执行计划之类的内容，也没有与问题无关的大段铺陈。开头一句"我是 Goal Teams Lead ……"之类的身份介绍不算违规。

FAIL：上面任一条不满足；或把 no-cache 解释为禁止缓存；或回复主要在安排任务、汇报进度，而不是回答问题。
