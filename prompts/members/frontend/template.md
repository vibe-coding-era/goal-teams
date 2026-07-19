# Frontend Member Template

```text
成员：<display_name>
页面/流程：<route_or_flow>
页面规格卡：<spec/page-spec-card.md or not_applicable_reason>
环境配置规划：<Architecture Design 内嵌的 Development Configuration Plan + Production Configuration Plan；不含 secret 值或部署授权>
组件库：<name@version / source / lock_status>
HTML OKF 元数据：<present/missing/not_applicable>
viewport：<desktop/mobile>
开发类型：dynamic frontend page | static HTML prototype
E2E：
- command:
- screenshot:
- console_errors:
动态/静态 Harness：
- dynamic_route_or_state_checks:
- static_structure_or_mock_checks:
- okf_metadata_checks:
- component_library_attribute_checks:
组件级视觉契约：
- component:
- state:
- assertion:
- evidence:
交互状态矩阵：
- dialog_open:
- dialog_error:
- dialog_switch:
- dialog_close:
- mobile_state:
视觉锁层证据：
- locked_screenshot:
- unlocked_real_dom_screenshot:
局部 crop / 几何断言：
- local_crop:
- geometry_assertion:
像素对比：
- baseline:
- actual:
- diff:
- metrics:
复核（先选 review_class）：
- review_class: structural | comparison | safety | semantic
- script_report:
- llm_review:
- not_applicable_half: <reason + reviewer_acceptance=accepted>
ledger event/patch 交接（TaskList 由 reducer 投影）：
- schema_version: goal-teams-v2.3
- task_id:
- title:
- artifact_type: frontend_architecture_design | html_prototype | frontend_implementation | evidence_record
- owner_agent_type:
- owner_member_id:
- owner_run_id:
- validator_agent_type:
- validator_member_id:
- validator_run_id:
- merge_owner_run_id:
- task_state:
- check_state:
- required_for_done:
- acceptance_blocking:
- attempt_id:
- revision:
- base_revision:
- requirement_refs:
- acceptance_criteria_refs:
- artifact_refs:
- evidence_refs:
- harness_refs:
```
