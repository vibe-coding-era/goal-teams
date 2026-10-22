# 订单服务接口约定

## 运行

- 启动：`python3 order_service.py --port 8765 --db data/orders.db`（`--port 0` 自动选端口，启动后打印地址）。只监听 `127.0.0.1`。
- 自动化测试可以在同一进程里启动：`from order_service import start_server`，`base_url, stop = start_server("data/test.db")`，结束时调用 `stop()`。
- 新数据库会写入 2 条演示订单。

## 认证

- `POST /api/login` → `200 {"token": "<token>"}`。
- 其余 `/api/*` 接口必须带 `Authorization: Bearer <token>`。缺少或错误一律返回 `401 {"error": "unauthorized"}`，并且不产生任何副作用。

## 创建订单：`POST /api/orders`

- 请求头 `Idempotency-Key: <非空字符串>`；请求体 `{"sku": "<非空字符串>", "quantity": <正整数>}`。
- 首次创建返回 `201` 和订单 `{"id", "idempotency_key", "sku", "quantity"}`。
- 同一个幂等键无论是顺序重放还是并发提交，都只存在一笔订单；重复请求返回 `200`、同一笔订单，并带响应头 `Idempotent-Replay: true`。
- 参数缺失或非法返回 `400 {"error": "invalid_request"}`。
- 下游瞬时故障返回 `503 {"error": "transient_failure"}`，不落库；客户端可以用同一个幂等键重试。

## 查询订单：`GET /api/orders`

- 返回 `200 {"orders": [...], "count": <n>}`，按 `id` 升序，包含全部订单。
- 读己之写：收到 `201` 后立即查询，必须能看到这笔订单。

## 测试钩子

- `POST /api/test/fail-next`（需认证）：下一次创建订单返回一次 `503`。

## 前端页面：`GET /`（`static/index.html`）

- 登录后刷新页面，会话保持。
- 连点 "Create order" 只产生一笔订单。
- 刷新后显示的订单数与服务端一致。
- 创建失败（例如 503）后出现 "Retry" 按钮，点击后只新增一笔订单。
