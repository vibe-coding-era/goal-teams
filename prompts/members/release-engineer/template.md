# Release Engineer Result Template

## Environment preflight receipt

```text
mode: environment_preflight
agent_type: goal_release_engineer
member_id / agent_run_id
project_size / user_requested_check
repository_root / source_commit / source_tree
decision: reuse | create | blocked
reuse_candidate / reuse_identity / freshness
worktree: <repository-root/develops/vmajor.minor-or-existing>
logical_branch: develop-v<major.minor> | not_required
branch: <host-namespace>/develop-v<major.minor> | develop-v<major.minor> | not_required
toolchain / dependency digests / workspace boundary
environment_state: ready | failed | blocked
evidence_refs / revalidation_trigger
```

## Final release evidence report

```text
agent_type: goal_release_engineer
member_id: <project-assigned stable id>
delivery_run_id: <id>
candidate_identity: <commit/tree/artifact digest>
environment_identity: <name/document digest>
environment_provenance: <created_at/architecture baseline commit/issuer>
evidence_status: ready | not_ready | blocked
checked_existing_evidence: <kinds/path/digest/status/binding/trusted-host attestation/issuer run>
full_test_execution_count: 0
missing_or_stale: <items>
release_intent_source: explicit_user_prompt | post_check_confirmation | none
next_gate: plan | stop | original_owner_evidence_required
```

## Release plan

```text
plan_version / plan_digest
candidate / environment / release surface
surface identity / surface_identity_digest
previous-good rollback identity / rollback_identity_digest
script discovery report / unmanaged or invalid scripts / user decision
selected kit ids and digests
dependency/toolchain/artifact identities
backup and restore proof
benchmark baseline contract
steps / expected side effects / permissions
rollback / forward-fix / manual steps
plan approval / expires_at
```

## Script bundle and execution result

```text
release_root / release_run_id
script_bundle_version / script_bundle_digest
plan_digest / environment_digest / artifact_digest
execution approval / execution_id / mode / operation / requested capabilities
isolation and credential-scrubbing attestation
step receipts / attempts / idempotency keys
publish_state / platform readback
typed current-execution benchmark / backup / post_release_verification receipts
rollback_or_manual_recovery
independent_validation_state: pending | passed | failed | blocked
delivery_outcome: <set only by an independent validator>
```
