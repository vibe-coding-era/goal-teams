# Security Specialist Result Template

```text
成员：<中文展示名>
角色/capability：goal_security / security_assessment, security_proposal
范围：locked_scope=<paths>; forbidden_scope=<paths>
授权：target_scope=<local|external>; scan_mode=<passive|active>; fresh_exact_authorization=<bool>
security_assessment：
- coverage: [code, dependencies, secrets, injection, ports]
- findings: <severity/evidence/ref>
- required_review_class: safety
specialist_improvement_proposal：
- proposal_id / lifecycle_state: proposed
- priority_level: L0 | L1 | L2
- relaxes: []
specialist_task_patch：<revision-bound ledger patch; not artifact type>
specialist_dispatch_request：
- proposal_ref / proposal_sha256
- requested_owner_agent_type / requested_validator_agent_types
- locked_scope / forbidden_scope / acceptance_criteria_refs
- risk / required_review_class / approval_gate
结论：proposal_only | blocked
错误码：<none | E_V235_EXTERNAL_PORT_SCAN_AUTH_REQUIRED | E_V235_*>
```
