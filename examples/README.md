# Goal Teams 示例

除本文件外，这里的文件都由 `python3 tools/make_examples.py` 生成：脚本用真实的 `gt` CLI 跑完一个"购物车折扣计算修复"的 tracked 目标，再把输出原样保存下来。CI 用 `--check` 确认它们与 gt 的实际输出一致。

| 文件 | 内容 |
|---|---|
| [tracked-plan-apply.md](tracked-plan-apply.md) | `gt plan apply`：整份计划在内存里校验后一次写入（分层、关键路径、并行宽度） |
| [tracked-round1-report.md](tracked-round1-report.md) | 第 1 轮结束时的 `gt report`：结果、关键证据、未完成事项三段；测试已写并通过评审，Red 已核对，实现尚未开始 |
| [tracked-resume.md](tracked-resume.md) | `gt resume`：续接包的六类信息，全部来自账本，只读 |
| [tracked-finish.md](tracked-finish.md) | `gt finish`：补跑过期的 Green 与完成标准的 `--check`，共享判定后记录达成 |
| [tracked-check.md](tracked-check.md) | 收尾后的 `gt check`：与 finish 同一判定（同一 snapshot_ref） |
| [tracked-final-report.md](tracked-final-report.md) | 终局 `gt report`（默认简洁格式） |
| [tracked-final-report.six.md](tracked-final-report.six.md) | 同一终局的六字段格式（`--format six`，可选） |
| [tracked-final-report.en.md](tracked-final-report.en.md) | 同一终局的英文输出（`--lang en`） |
| [state/TaskList.md](state/TaskList.md) | gt 生成的完整任务表（分层、关键路径） |
| [state/benchmark.md](state/benchmark.md) | gt 生成的证据清单与评审记录 |
| [state/loop-review.md](state/loop-review.md) | `gt reflect` 追加的反思 |

## Discussion：自由格式（不用 gt，格式示意）

> 用户：Python 的 list 和 tuple 有什么区别？

```text
list 可变，适合元素会增删改的序列；tuple 不可变，可以作为 dict 的键或放进 set（前提是元素也都可哈希），
也常用来表示固定结构的记录。性能上 tuple 稍省内存、创建更快，但差别通常不是选型的主要理由。
```

讨论类回复不输出六字段、看板或进度。

## Small 快速通道：简短摘要（不建 gt 状态，格式示意）

> 用户：`slugify("Hello World")` 返回了 `hello-world-`，多了个横杠。

```text
改动：src/text.py 去掉末尾分隔符（strip("-")）。
Red：python -m pytest -q tests/test_text.py::test_slugify_no_trailing_dash → 失败（'hello-world-' != 'hello-world'）
Green：同一测试 → 通过；受影响检查 python -m pytest -q tests/test_text.py → 12 passed
未验证：未覆盖非 ASCII 输入（现有行为未改动）。
```

改动只涉及 1 个文件，可逆，也没有升级信号，所以不需要 gt。
