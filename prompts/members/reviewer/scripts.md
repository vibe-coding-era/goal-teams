# Reviewer Member Scripts

优先脚本：

- `scripts/checks/validate.py`
- `scripts/checks/check-agent-names.py`
- `scripts/checks/check-member-layout.py`
- `scripts/review/compare-artifacts.py`
- `scripts/review/validate-dual-review.py`

规则：

- Reviewer 是 LLM 语义复核者，不替代脚本。
- 脚本失败时直接 reject 或 conditional。
- `validate-dual-review.py` 与 Completion 使用同一 domain/integrity replay 合同；旧单一 `command`、同日志或 review class 降级必须 reject。
