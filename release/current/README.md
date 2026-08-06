# Goal Teams V2.51 Release / V2.52 Candidate

V2.51 is the current published GitHub Release. V2.52 is an unreleased candidate and does not become current until its tag, four public assets, remote readback, and formal installation have completed.

The V2.52 candidate is fully open source under the OSI-approved MIT License. It keeps the V2.5 execution protocol and adds a machine-checkable first-round LOOP bootstrap plus independent development-environment reuse and version-branch rules.

## V2.52 candidate changes

- Replaced the limited source-available terms with the MIT License, allowing use, copying, modification, distribution, sublicensing, and sale subject to the license notice.
- Every execution LOOP first establishes TaskList state, task assignments, and an independent environment preflight before implementation.
- `goal_release_engineer` is a built-in dual-mode member: first-round `environment_preflight` remains isolated from its existing Release workflow.
- Medium/Large or user-requested development checks reuse compatible current environments; otherwise they bind a repository-contained `codex/develop-v<major.minor>` branch. Small keeps the branch exception.
- The bilingual README member tables now include Security, Performance, Refactor, SQA, and Release Engineer.
- V2.50 schemas, `scripts/v250/`, route IDs, error-code family, and release protocol remain the compatible V2.5 execution layer.

## Public assets

If V2.52 passes Release Readiness, its fixed public set will be:

- `goal-teams-V2.52.tar.gz`
- `SHA256SUMS`
- `_release.json`
- `_files.sha256`

No `docs/`, `develops/`, local Evidence, credentials, or optional Replay supplement is part of the default asset.

## Assurance boundary

A fresh runtime transition receipt proves only an I1 correlated local-process observation. It does not prove repository-external independence, cryptographic host attestation, or provider final-prompt assembly. Tokens consumed and cache hit rate remain unavailable unless trusted host usage Evidence exists.

Requirements: Python 3.11+ for the complete validated toolchain.
