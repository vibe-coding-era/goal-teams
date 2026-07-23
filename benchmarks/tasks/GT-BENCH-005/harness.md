# GT-BENCH-005 Harness

## 环境

必需能力：

- Python 3 标准库（HTTP server、SQLite、并发请求、JSON）。
- loopback 端口。

E2E 完整得分还需要 Node.js、Playwright Node module 和可启动的 Chromium/Chrome。runner 会先探测这些能力；不可用时不下载依赖、不访问外网，四个 E2E case 输出 `not_run`。

## 正向 baseline

```bash
run_dir="$(mktemp -d)"
python3 scripts/benchmark/v244_testing_capability_runner.py \
  --output-dir "$run_dir" \
  --candidate-mode reference \
  --browser required
```

退出 0 只表示 runner 完成。是否 10/10 必须读取 `<run_dir>/reference/score.json`，并核对 `evidence.json` 中八个 case 的真实观测。

## 负向 candidate

可用 `--candidate-mode` 逐个运行 manifest 中的 seeded defect。完整 oracle 回归使用：

```bash
run_dir="$(mktemp -d)"
python3 scripts/benchmark/v244_testing_capability_runner.py \
  --output-dir "$run_dir" \
  --self-check
```

自检会：

1. 启动每个 candidate 的独立服务和 SQLite。
2. 执行四个 API 行为。
3. 对 reference 与 E2E defect 启动真实浏览器。
4. 验证各 defect 绑定 case 为 `failed`。
5. 重复执行 reference，比较 case outcome。
6. 生成 `self-check-summary.json`。

完整 `--self-check` 对 reference 和全部八个 defect candidate 都强制真实浏览器；任一 case 为 `not_run`，自检即失败。单独诊断某个 API defect 时可以显式使用 `--browser off`，但该次运行只能是 partial，E2E 为 0/4，不能作为完整自检证据。

## 独立 scoring

```bash
python3 scripts/benchmark/v244_testing_capability_scorer.py \
  <run-dir>/reference/evidence.json \
  --output <run-dir>/reference/rescored.json
```

scorer 只读取 manifest 和逐 case evidence。以下输入都不能得分：

- 一段“8/8 通过”的 prose。
- 只有测试命令与 exit code。
- `behavior_observed=false` 的 `passed`。
- 缺失的 case。
- E2E `not_run`。

## 清理与复盘

runner 使用显式输出目录保存 SQLite、服务日志、evidence、score 和 E2E 截图；服务在成功、失败和异常退出路径均会被终止。若输出目录由 `mktemp -d` 创建，评测者在保存所需 evidence 后负责删除该目录。不要把运行数据库、日志或截图提交到 source tree。

复盘至少引用：

- `evidence.json` 的逐 case 请求/状态变化/浏览器观测。
- `score.json` 的 API 6 分与 E2E 4 分。
- `self-check-summary.json` 的 defect detection 与 repeatability。
- `screenshots/*.png` 的四个 UI 终态。

## 停止条件

- 无法绑定 loopback 端口或启动 Python 服务。
- `reference_app.py`、manifest、runner 或 scorer digest 发生未解释漂移。
- E2E 要求 `required` 但浏览器不可用。
- candidate 需要真实外部账号、网络、支付或生产数据。

停止时必须输出 `not_run` 或错误，不得以结构检查替代行为。
