# SQA Specialist Result Template

```text
成员：<中文展示名>
角色/capability：goal_sqa / sqa_process_review, sqa_archive_proposal
范围：locked_scope=<ledger/docs/process refs>; forbidden_scope=<private/public write paths>
sqa_process_archive_proposal：
- proposal_id / lifecycle_state: proposed
- priority_level: L0 | L1 | L2; relaxes: []
- release_version:
- version_record: version/change_ids
- index_ref:
- classifications:
- version_directory: docs/archive/<release_version>
- public_copy: sanitized/secret_count=0/absolute_home_path_count=0
- private_provenance: retained/ref/sha256
specialist_task_patch：<revision-bound ledger patch>
specialist_dispatch_request：<goal_docs owner + independent validator + scope/AC/review class>
结论：proposal_only | blocked
```
