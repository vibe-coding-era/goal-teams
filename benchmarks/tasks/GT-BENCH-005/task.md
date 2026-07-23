# GT-BENCH-005：API + E2E 测试成员真实行为闭环

## 任务目的

评估 API 集成测试与 E2E 测试是否真的观察业务行为，而不只检查文档结构、测试文件数量、命令退出码或自然语言结论。本任务提供一个仅监听 loopback 的订单 API、SQLite 状态、静态 Web UI、reference oracle 和八个 seeded defect candidate。它是 V2.44 测试能力评分中独立的 10 分真实 benchmark。

## 统一输入

`baseline` 与 `goal-teams` 使用同一服务、同一候选变体和同一 scoring：

```text
你正在执行 GT-BENCH-005。

目标：验证订单服务在权限、幂等、并发、最终一致性、会话、双击、刷新和错误恢复上的真实行为。
约束：
1. API 必须通过真实 loopback HTTP 请求执行，状态必须落入 SQLite。
2. E2E 必须通过真实浏览器操作页面；浏览器不可用时写 not_run，不得计为通过。
3. 只能把逐用例 behavior evidence 交给 scorer。文档、测试文件存在、自然语言、exit code 0 都不能代替行为。
4. reference candidate 应得 10/10；每个 seeded defect 必须被其绑定的 oracle case 识别。
5. 每次运行必须终止服务进程，并把数据库、请求结果、浏览器观测和截图放在显式输出目录或临时目录。
```

## 被测行为

| Case ID | 层 | 行为 | 分值 |
| --- | --- | --- | ---: |
| `API-AUTH-001` | API | 未认证创建被拒绝且无状态副作用 | 1.5 |
| `API-IDEMPOTENCY-001` | API | 相同幂等键顺序重放只创建一笔 | 1.5 |
| `API-CONCURRENCY-001` | API | 相同幂等键并发提交只创建一笔 | 1.5 |
| `API-CONSISTENCY-001` | API | 成功响应后的订单在读取窗口内可见 | 1.5 |
| `E2E-SESSION-001` | E2E | 登录会话在页面刷新后保持 | 1.0 |
| `E2E-DOUBLE-CLICK-001` | E2E | 双击提交只创建一笔订单 | 1.0 |
| `E2E-REFRESH-001` | E2E | 刷新后从服务端恢复订单状态 | 1.0 |
| `E2E-RECOVERY-001` | E2E | 瞬时失败后用户可重试恢复 | 1.0 |

## Candidate 变体

`reference` 是正向 baseline。其余 candidate 分别注入认证绕过、幂等破坏、并发竞争、永久陈旧读取、会话丢失、双击重复创建、刷新丢状态和错误无恢复入口。机器 SSOT 位于 `benchmarks/fixtures/v2.44/testing-capability-cases.json`。

候选输出不是一段“通过”文字，而是 `goal-teams-testing-capability-evidence-v2.44` JSON：每个 Case ID 必须有 `passed`、`failed` 或 `not_run`、`behavior_observed`、结构化 `evidence` 和绑定 raw JSON artifact。run provenance 必须把 canonical manifest digest、runner/source digest、UUID run identity、SQLite identity、service log、raw observations 与 PNG screenshots 串成同一次运行。scorer 会拒绝缺项、重复项、未知项、没有行为证据的 pass/fail、manifest 替换、hash 漂移、run identity 漂移及文件或祖先目录 symlink。

## 允许范围

- loopback HTTP 服务和临时 SQLite。
- 无外网的本地 Chromium/Chrome。
- 显式 benchmark 输出目录或系统临时目录。
- 参考 runner、scorer 与专属聚焦测试。

## 禁止范围

- 连接生产、共享测试环境、真实账号、真实支付或外部网络。
- 将浏览器缺失、`not_run`、测试文件存在、文档完整或 `exit code = 0` 记为行为通过。
- 为提高分数删除失败用例、改变权重或只运行 reference。
- 把 seeded defect 名称当成候选行为证据。

## Done Criteria

- reference candidate 的 8 项行为真实执行且为 10/10。
- 8 个 seeded defect 均被绑定 oracle case 检出。
- reference 重复运行的 case outcome 一致。
- API 使用真实 HTTP 和 SQLite；E2E 使用真实浏览器。
- 浏览器不可用时 E2E 明确 `not_run` 并得 0/4。
- 服务进程始终终止；运行 evidence、score、raw observations、截图、数据库及其 sha256 binding 可复盘。
- scorer 只能使用固定路径且固定 digest 的 8-case canonical manifest；API/E2E 固定为 6/4，reference + 八类风险/期望缺陷集合不可由调用方替换。
