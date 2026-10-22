---
type: llm
# 结果（两组都计分）：读提示词要求的缺陷清单文件 qa-report.md（最终回复里是否也给了清单由 repro-evidence 核对）。
focus:
  source: file
  path: qa-report.md
---

评审对象：QA 写下的缺陷清单（qa-report.md）。

PASS：报告了"不带 Authorization 请求头也能访问订单接口"的缺陷。例如不带该请求头的 `POST /api/orders` 返回 201 并真的创建了订单，或不带请求头的 `GET /api/orders` 返回了订单列表；而约定要求 401 且没有副作用。报告里给出了具体的复现请求，以及实际观察到的状态码或响应内容。

FAIL：没有报告这个问题；只测了错误 token（得到 401）就判定认证正常；或只凭读代码推测，没有任何实际请求和响应作为证据。
