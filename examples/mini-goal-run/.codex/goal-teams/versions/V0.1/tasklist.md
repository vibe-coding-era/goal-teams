# Goal Teams Tasklist

Goal: 规划登录页空状态提示 V0.1
Status: blocked

V2.35 下 `sample_only` 只限制分发/生产声明，不豁免 Architecture、Environment、独立测试、Evidence 或 UI E2E。

## Member Ownership

| Task ID | Member | Skill/Subagent | Workflow / 前置 | Status | Locked Scope | Deliverable | Done Criteria | Harness Contract | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | 需求分析-空状态 | `goal_requirements_analyst` | 串行 / - | done | `spec/` | requirement spec | 用户故事/功能验收标准齐备 | 结构和边界 | `goal_reviewer` |
| GT-002 | 产品-空状态 PRD | `goal_product` | 串行 / GT-001 | done | `spec/` | PRD | 可追溯到 requirement spec | 溯源检查 | `goal_reviewer` |
| GT-011 | 架构-空状态 | `goal_backend` | 串行 / GT-002 | blocked | `spec/architecture-design.md` | Architecture accepted Evidence | 独立 accepted 且 hash-bound | 作者/校验者独立 | `goal_reviewer` |
| GT-012 | 环境-空状态 | `goal_backend` | 串行 / GT-011 | blocked | `spec/development-environment-check.md` | `development_environment_check` | Architecture-bound + `ready` | current environment Evidence | `goal_qa` |
| GT-003 | 前端-HTML 原型 | `goal_frontend` | 串行 / GT-012 | blocked | `spec/HTML-prototype.html` | HTML prototype | 只有上游门开放后可 accepted | HTML 静态结构；像素对比 `not_applicable_reason=无参考图` | `goal_reviewer` |
| GT-009 | E2E用例-空状态 | `goal_e2e_test_designer` | 串行 / GT-003 | blocked | `spec/e2e-test-cases.json` | E2E test cases | `input/processing/expected_output/assertions` 齐备 | V2.35 test-case contract | `goal_reviewer` |
| GT-010 | E2E执行-空状态 | `goal_e2e_test_runner` | 串行 / GT-009 | blocked | read-only | screenshot/trace/assertion Evidence | 真实浏览器 current Evidence | browser E2E | `goal_reviewer` |
| GT-004 | QA-空状态 | `goal_qa` | 串行 / GT-010 | blocked | `spec/test-plan.md` | test plan/result | 静态覆盖 + E2E accepted | 整体证据门 | `goal_reviewer` |
| GT-005 | 文档-验收 | `goal_docs` | 串行 / GT-004 | blocked | `spec/acceptance.md` | acceptance | required Evidence 完整 | 证据完整性 | `goal_reviewer` |
| GT-006 | 文档-Harness | `goal_docs` | 串行 / GT-005 | blocked | `harness/` | setup -> run -> checks -> report | 如实保留 blocker | `sample_only` / `no_runner` 不充当 E2E | `goal_reviewer` |
| GT-007 | 评审-完整性 | `goal_reviewer` | 串行 / GT-011, GT-012, GT-003, GT-009, GT-010, GT-004, GT-005, GT-006 | blocked | read-only | review record | 不把 blocker 写成 passed | 只读独立评审 | not applicable |

## Handoff Artifact Ledger

Source SSOT: `prompts/packets/handoff-artifacts.md`

| Task ID | Handoff Artifact | Artifact Type | Owner Subagent | Validator Subagent | Handoff Status | Independent Check Status | Harness | Evidence Path | Blocked/Deferred Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GT-001 | Requirement Specification | requirement_spec_card | goal_requirements_analyst | goal_reviewer | done | passed | 结构校验 | `progress.md` | - |
| GT-002 | PRD | prd | goal_product | goal_reviewer | done | passed | 溯源校验 | `progress.md` | - |
| GT-011 | Architecture | architecture_design | goal_backend | goal_reviewer | blocked | blocked | exact hash + independent review | missing | independent acceptance missing |
| GT-012 | Environment | development_environment_check | goal_backend | goal_qa | blocked | blocked | Architecture-bound current Evidence | missing | Architecture not accepted |
| GT-003 | HTML Prototype | html_prototype | goal_frontend | goal_reviewer | blocked | blocked | gate order + static structure | `spec/HTML-prototype.html` | upstream gates closed |
| GT-009 | E2E Test Cases | e2e_test_cases | goal_e2e_test_designer | goal_reviewer | blocked | blocked | four-part contract | missing | no test contract |
| GT-010 | E2E Execution | e2e_test_execution | goal_e2e_test_runner | goal_reviewer | blocked | blocked | browser Evidence | missing | no_runner |
| GT-004 | Test Plan | test_plan | goal_qa | goal_reviewer | blocked | blocked | static + E2E coverage | `spec/test-plan.md` | E2E not accepted |
| GT-005 | Acceptance | acceptance_record | goal_docs | goal_reviewer | blocked | blocked | Evidence completeness | `spec/acceptance.md` | required Evidence missing |
| GT-006 | Harness | evidence_record | goal_docs | goal_reviewer | blocked | blocked | setup/run/checks/report trace | `harness/report.md` | static only |
| GT-007 | Review | dual_review_record | goal_reviewer | not applicable | blocked | not applicable | read-only gap review | `progress.md` | upstream tasks blocked; reviewer 本身是独立检查者，不用图外 auditor 自证 |

## Graph-external Completion Audit

- Audit id: `AUD-V0.1-001`
- Legacy compatibility label: `GT-008` (not a task, not required, not blocking, and not present in the Handoff Artifact Ledger).
- `audit_state=not_started`; `goal_completion_auditor` is not dispatched until every required task is accepted.

## Independent Validation

| Artifact | Author | Validator | Method | Evidence |
| --- | --- | --- | --- | --- |
| requirement/PRD | Goal Lead / requirement / product | `goal_reviewer` | structure and traceability | `progress.md` |
| Architecture | `goal_backend` | `goal_reviewer` | independent exact-hash acceptance | missing / blocked |
| Environment | `goal_backend` | `goal_qa` | current Architecture-bound check | missing / blocked |
| HTML/E2E | frontend / E2E designer / E2E runner | `goal_reviewer` | real browser assertions and Evidence | missing / blocked |
| Completion state | graph-external auditor | n/a | not started before required acceptance | `progress.md` |
