# GT-BENCH-005 Expected Artifacts

## 仓库内固定资产

| 资产 | 作用 |
| --- | --- |
| `task.md` | 统一目标、范围和 Done Criteria。 |
| `harness.md` | baseline、负向 candidate、浏览器降级和清理方法。 |
| `scoring.md` | 10 分 behavior-only scoring 与 fail-closed 规则。 |
| `expected-artifacts.md` | 固定资产和运行输出契约。 |
| `reference_app.py` | loopback HTTP + SQLite 参考服务与 seeded defects。 |
| `static/index.html` | 会话、双击、刷新和恢复的真实 Web UI。 |
| `benchmarks/fixtures/v2.44/testing-capability-cases.json` | case、权重、candidate 与 oracle SSOT。 |
| `scripts/benchmark/v244_testing_capability_runner.py` | API、浏览器、生命周期和自检 runner。 |
| `scripts/benchmark/v244_testing_capability_browser.cjs` | Playwright Chromium 行为执行器。 |
| `scripts/benchmark/v244_testing_capability_scorer.py` | 逐 case fail-closed scorer。 |

## 单次 candidate 输出

```text
<output-dir>/<candidate-mode>/
  orders.sqlite3
  service.log
  evidence.json
  score.json
  raw/
    API-AUTH-001.json
    API-IDEMPOTENCY-001.json
    API-CONCURRENCY-001.json
    API-CONSISTENCY-001.json
    E2E-SESSION-001.json
    E2E-DOUBLE-CLICK-001.json
    E2E-REFRESH-001.json
    E2E-RECOVERY-001.json
  screenshots/
    E2E-SESSION-001.png
    E2E-DOUBLE-CLICK-001.png
    E2E-REFRESH-001.png
    E2E-RECOVERY-001.png
```

关闭或无法执行浏览器时可以没有截图，但对应四个 case 必须是 `not_run`，且 `score.json` 的 E2E earned 为 0。

`evidence.json` 的 `run` 必须含 canonical manifest sha256、UUID run ID、
candidate mode、六个 source digests、SQLite binding 和 service-log binding。
每个 case 必须含 raw JSON binding；E2E pass/fail observation 必须含 PNG binding。
binding 统一包含 evidence-root 相对路径、media type、size 和 sha256。

## 自检输出

`--self-check` 除各 candidate 目录外还生成：

```text
<output-dir>/
  self-check-summary.json
  repeat/
    reference/
      evidence.json
      score.json
      ...
```

`self-check-summary.json` 至少包含：

- `behavior_run=executed`。
- reference 是否 10/10。
- 每个 seeded defect 的 `expected_detected_by` 与 `detected`。
- reference 重复 outcome 是否一致。
- oracle digest。
- `non_behavior_inputs_counted=false`。

## 验收清单

- [ ] task package 包含四个标准 Markdown，且有 baseline、goal-teams、scoring。
- [ ] reference app 仅监听调用方指定的 loopback 地址，状态进入独立 SQLite。
- [ ] API 四项通过真实 HTTP 执行。
- [ ] E2E 四项通过 Playwright Chromium 执行并保留截图。
- [ ] browser unavailable 不计成功。
- [ ] scorer 拒绝 prose、exit code 和无行为 evidence。
- [ ] scorer 无 `--manifest` 覆盖入口，并校验固定 manifest digest、完整 case/风险集合及 6/4 分层。
- [ ] raw、PNG、SQLite 和 log 均为无 symlink 的常规文件，祖先目录无 symlink，并通过 size/sha256 复核。
- [ ] UUID run identity 同时出现在 evidence、browser runtime、raw observations 与 SQLite。
- [ ] source digests 与当前 runner、scorer、reference app、browser runner、static UI 和 manifest 一致。
- [ ] reference 10/10；八个 defect 均被绑定 case 检出。
- [ ] reference 重复运行 outcome 一致。
- [ ] runner 在所有路径终止服务，运行文件只落显式输出目录。
- [ ] 专属 tests 覆盖权重、fail-closed、not_run、API defects 和真实浏览器 reference。

运行输出属于 Evidence，不默认提交。Lead 可引用输出路径和摘要，但不能把一次机器上的浏览器结果描述为所有环境均已通过。
