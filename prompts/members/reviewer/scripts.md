# Reviewer Member Scripts

优先脚本：

- `scripts/checks/validate.py`
- `scripts/checks/check-agent-names.py`
- `scripts/checks/check-member-layout.py`
- Member Goal Packet/Harness 指定的 `integration-test-plan` / `test-case` / `test-run-result` validators
- `scripts/checks/check-routing-fixtures.py`
- `scripts/review/compare-artifacts.py`
- `scripts/review/validate-dual-review.py`

规则：

- Reviewer 是 LLM 语义复核者，不替代脚本。
- 脚本失败时直接 reject；无法执行时 blocked。
- `validate-dual-review.py` 与 Completion 使用同一 domain/integrity replay 合同；旧单一 `command`、同日志或 review class 降级必须 reject。
- Reviewer 必须自行重算 file sha256、运行真实 discovery，并用 exact replay recipe 重放选定高风险 case；不得复用 runner 的“已验证”结论。
- 自动 retry 必须关闭或完整披露所有 attempts；只看到最终 pass、fail→pass 被写成 passed 或 cleanup 未验证时 reject。
