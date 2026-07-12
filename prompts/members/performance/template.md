# Performance Specialist Result Template

```text
成员：<中文展示名>
角色/capability：goal_performance / performance_benchmark, performance_proposal
范围：locked_scope=<SQL/page/data paths>; forbidden_scope=<paths/services>
performance_benchmark_proposal：
- proposal_id / lifecycle_state: proposed
- priority_level: L0 | L1 | L2; relaxes: []
- benchmark.environment_digest:
- benchmark.data_scale:
- benchmark.command.argv/cwd:
- benchmark.candidate_digest:
- benchmark_evidence: evidence_id/current/environment_digest/data_scale/candidate_digest
- claim.performance_improved: <bool; only with current evidence>
specialist_task_patch：<revision-bound ledger patch>
specialist_dispatch_request：<proposal hash, owner/validators, scope, AC, risk, review class>
结论：proposal_only | blocked
```
