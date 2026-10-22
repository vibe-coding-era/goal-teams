---
type: llm
# 结果（两组都计分）：读缺陷清单文件 qa-report.md。
focus:
  source: file
  path: qa-report.md
---

评审对象：QA 写下的缺陷清单（qa-report.md）。

PASS：报告了"刚创建成功的订单在 `GET /api/orders` 里查不到"的缺陷（也可以表述为：最新一笔订单缺失、列表总比实际少一笔、读己之写不成立）。报告里给出了证据：创建返回的订单 id，和随后查询结果里的 id 列表或 count 的对比。

FAIL：没有报告这个问题；或只给结论没有查询结果作为证据。
