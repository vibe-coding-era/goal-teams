# Backend Member Scripts

优先脚本：

- `scripts/harness/validate-harness.py`：校验后端 Harness 字段。
- `scripts/review/compare-artifacts.py`：比较 API schema、golden output、报告或生成文件。
- `scripts/review/validate-dual-review.py`：确认脚本结果和 LLM 复核都存在。
- 后端单元测试由 `goal_unit_test_runner` 执行；API 集成测试默认由 `goal_api_integration_test_runner` 使用 `python -m pytest` 或项目命令执行。

规则：

- 脚本通过只代表可机械验证项通过。
- 仍需要 `goal_reviewer` 或指定 reviewer 做 LLM 语义复核。
- 数据迁移、认证、支付、破坏性写入必须停在审批门前。
- 后端实现者不得作为唯一测试执行者，不得为了通过而放宽 TDD 测试。
