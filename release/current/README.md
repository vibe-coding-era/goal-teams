# Goal Teams V2.48 Release / V2.49 Candidate

V2.48 remains the current published GitHub Release. V2.49 is an unreleased candidate and does not become the current release until its tag, four public assets, remote readback, and formal installation have completed.

The V2.49 candidate replaces version-stacked hot paths with a digest-bound Current generation and explicit, isolated Legacy Replay. Its default prompt plan and installation package are intended to contain only V2.49 Current rules plus exact execution dependencies.

## V2.49 candidate changes

- Bootstrap is thin; requirements, architecture/implementation, testing, UI/desktop, Agent runtime, and release operations each have one functional Owner template.
- Current route closure is verified against an explicit Legacy classification and a fixed 72,194-byte ceiling.
- Test governance uses `RiskDenominator -> immutable TestCase -> TestRunReceipt -> TestReviewReceipt` with separate Development and Release denominators.
- Medium/Large development blocks only on TDD and affected-scope incremental checks. Final Release readiness runs one Current full regression and one independent security review bound to the exact released commit/tree.
- S2 builds each exact released asset set once. It does not run a second deterministic build or S2 security checks, so reproducibility and S2 security are explicitly not verified by policy.
- S3 runs only for a Large Release after S1 is passed/current. S4 reuses project-start authorization and performs exact remote/readback recovery without a second authorization flow.
- GitHub Git remotes are SSH-only; PR, Actions, ruleset, and Release operations use authenticated GitHub API/CLI surfaces.

## Planned public assets

If V2.49 passes Release Readiness, its fixed public set will be:

- `goal-teams-V2.49.tar.gz`
- `SHA256SUMS`
- `_release.json`
- `_files.sha256`

No `docs/`, `develops/`, local Evidence, credentials, or optional Replay supplement is part of the default asset.

## Assurance boundary

A fresh runtime transition receipt proves only an I1 correlated local-process observation. It does not prove repository-external independence, cryptographic host attestation, or provider final-prompt assembly. Tokens consumed and cache hit rate remain unavailable unless trusted host usage Evidence exists.

Requirements: Python 3.11+ for the complete validated toolchain.
