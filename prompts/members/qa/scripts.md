# QA Member Scripts

优先脚本：

- `scripts/harness/validate-harness.py`
- `scripts/harness/pixel-diff.py`
- `scripts/review/compare-artifacts.py`
- `scripts/review/validate-dual-review.py`
- Member Goal Packet/Harness 指定的 `integration-test-plan` / `test-case` / `test-run-result` validators
- `scripts/checks/check-member-layout.py`
- `scripts/checks/check-agent-names.py`

规则：

- 从 Harness 推导最低 review_class；comparison/safety 先脚本后独立 LLM，semantic/structural 不互代并按 class matrix 执行。
- required half 结论冲突时使用 failed/blocked 并交给 Lead；不输出 schema 外 `conditional` 状态。
- validator 之前/之后都不得篡改 artifact；QA 重算 sha256、运行真实 discovery，并用 exact argv/cwd 重放选定高风险 case。
- 测试框架自动 retry 必须关闭或完整暴露所有 attempts；只看到最终 pass 时按 Evidence incomplete 处理。
