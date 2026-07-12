# Refactor Specialist Result Template

```text
成员：<中文展示名>
角色/capability：goal_refactor / refactor_equivalence, refactor_proposal
范围：locked_scope=<engineering/code/docs paths>; forbidden_scope=<paths>
refactor_equivalence_proposal：
- proposal_id / lifecycle_state: proposed
- priority_level: L0 | L1 | L2; relaxes: []
- equivalence_contract: public_behavior_sha256/scope
- regression_evidence: evidence_id/current/state
- holdout_evidence: evidence_id/current/state
- rollback_boundary: paths/command
specialist_task_patch：<revision-bound ledger patch>
specialist_dispatch_request：<proposal hash, implementation owner, independent validators, scope, AC>
结论：proposal_only | blocked
```
