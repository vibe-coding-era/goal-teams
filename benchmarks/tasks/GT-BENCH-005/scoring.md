# GT-BENCH-005 Scoring

总分 10 分，只计真实 API 与浏览器行为。

| 维度 | Case | 分值 | 满分 oracle |
| --- | --- | ---: | --- |
| 权限与副作用 | `API-AUTH-001` | 1.5 | 无认证返回 401，订单数不变。 |
| 顺序幂等 | `API-IDEMPOTENCY-001` | 1.5 | 首次 201、重放 200、同一 ID、replay header、只增 1。 |
| 并发幂等 | `API-CONCURRENCY-001` | 1.5 | 4 个并发响应指向同一 ID，只有一次 201，只增 1。 |
| 最终一致性 | `API-CONSISTENCY-001` | 1.5 | 成功创建的 ID 在有界读取窗口内出现。 |
| 会话恢复 | `E2E-SESSION-001` | 1.0 | 浏览器登录后刷新仍显示 signed in。 |
| 双击保护 | `E2E-DOUBLE-CLICK-001` | 1.0 | 浏览器同步双击后订单只增 1。 |
| 刷新恢复 | `E2E-REFRESH-001` | 1.0 | 创建后刷新，UI 恢复相同服务端计数。 |
| 错误恢复 | `E2E-RECOVERY-001` | 1.0 | 注入一次 503 后出现 Retry，重试只增 1。 |

## 计分规则

- `passed` 且 `behavior_observed=true`：获得该 case 全部分值。
- `failed`：0 分。
- `not_run`：0 分，整体 score 状态为 `partial`。
- API 满分 6，E2E 满分 4，总分固定 10。
- scorer 不根据 candidate 名称、文档、测试数量、prose、文件存在或退出码推断通过。

## Fail-closed

以下情况 scorer 拒绝整个 candidate 输出，而不是猜测分数：

- schema 或 benchmark ID 不匹配。
- case 缺失、重复或未知。
- status 不是 `passed`、`failed`、`not_run`。
- pass/fail 没有行为观测。
- evidence 不是结构化对象。
- manifest 权重之和不是 10。
- 调用方尝试指定 manifest，或 canonical manifest path/digest、8 case、API 6/E2E 4、风险/期望缺陷集合发生漂移。
- UUID run identity 未同时绑定 browser runtime、raw observations 与 SQLite `benchmark_run`。
- runner/reference app/browser/static UI/scorer 的 source digest 不匹配当前受评分源码。
- raw JSON、SQLite、service log 或 PNG 的大小/sha256 不匹配。
- artifact 本身或 evidence root 内任一祖先目录是 symlink，或路径绝对化、含 `..`。
- embedded observation 与绑定 raw JSON 内容不同，或 PNG header 无效。

## Seeded defect oracle

| Candidate | 至少必须失败 |
| --- | --- |
| `api_auth_bypass` | `API-AUTH-001` |
| `api_idempotency_broken` | `API-IDEMPOTENCY-001` |
| `api_concurrency_race` | `API-CONCURRENCY-001` |
| `api_eventual_consistency_stale` | `API-CONSISTENCY-001` |
| `e2e_session_lost` | `E2E-SESSION-001` |
| `e2e_double_click` | `E2E-DOUBLE-CLICK-001` |
| `e2e_refresh_drops_state` | `E2E-REFRESH-001` |
| `e2e_error_no_recovery` | `E2E-RECOVERY-001` |

额外失败可以揭示故障传播，但不能掩盖绑定 case 未检出。reference 必须 10/10 且 `not_run_count=0`，否则 benchmark 自检失败。表中的 risk 与 expected defect binding 是 canonical manifest 的固定集合，不能通过自选 manifest 缩减。

## 与 100 分能力评分的关系

这 10 分只代表“真实 benchmark”维度。它不能替代测试计划、API/E2E 用例机器合同、运行结果合同、风险与覆盖率等其余 90 分，也不能用结构门通过推导为行为通过。
