# Backend Member Scripts

优先脚本：

- `scripts/harness/validate-harness.py`：校验后端 Harness 字段。
- `scripts/review/compare-artifacts.py`：比较 API schema、golden output、报告或生成文件。
- `scripts/review/validate-dual-review.py`：按 review_class 校验 required half 与结构化 N/A。
- 后端单元测试由 `goal_unit_test_runner` 执行；API 集成测试默认由 `goal_api_integration_test_runner` 使用 `python -m pytest` 或项目命令执行。

规则：

- 脚本通过只代表可机械验证项通过。
- 从 Harness 推导最低 review_class；comparison/safety 需要脚本 + 独立 LLM，structural/semantic 不互代并按 class matrix 执行，不能把不适用半边伪写 passed。
- 数据迁移、认证、支付、破坏性写入必须停在审批门前。
- 后端实现者不得作为唯一测试执行者，不得为了通过而放宽 TDD 测试。
