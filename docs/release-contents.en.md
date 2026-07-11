# Release Contents

This document is the English index of the visible Goal Teams package. Its Chinese counterpart is [release-contents.md](release-contents.md). The runtime version always comes from the repository-root `VERSION`; applicable runtime rules come from `SKILL.md`, `RULES.md`, and the relevant contracts in `references/` and `prompts/`.

## Current boundary

- This inventory lists only verifiable repository contents. It does not claim unimplemented capabilities.
- V2.33 keeps the V2.3 machine-contract baseline and defines rule precedence, classified dependency degradation, `plan_preview` selection, single-value `check_state` language, and this bilingual release-document structure. This index cannot replace those rules or their validation.
- The manually maintained `SKILL.md` and READMEs are the baseline. This inventory cannot override them or replace scripted validation.
- The local planning source `docs/后续版本规划 V3.3-3.5.md` is user-maintained and is not part of the repository or install package. AI must not edit it and, without separate user authorization, must not include it in a GitHub commit. Planning text is not a release commitment.

## Package inventory

| Category | Current release contents |
| --- | --- |
| Root files | `VERSION`, `SKILL.md`, `RULES.md`, `goal-teams.md`, `AGENTS.md`, `CHANGELOG.md`, `README.md`, `README.en.md`, `agents/openai.yaml` |
| Rules and compatibility | `references/goal-teams-runtime.md`, `references/default-AGENTS.md`, `references/invariants.md`, `references/compat.md`, `references/rules-ui.md`, `references/rules-testing.md`, `references/rules-loop.md`, `references/goal-teams-automation-protocol.md`, `references/goal-teams-production-pipeline.md`, `references/goal-teams-scripted-tooling.md`, `references/goal-teams-v2.3-contract.md`, `references/google-okf-bilingual-spec.md`, `references/ui-e2e-pixel-protocol.md`, `references/ui-visual-contract-protocol.md`, `references/subagent-dispatch-protocol.md`, `references/dual-review-protocol.md` |
| Members and prompts | `subagents/goal-*.toml`, `prompts/`, `prompts/lead/`, `prompts/members/`, `prompts/packets/` |
| Tooling and checks | `scripts/check.sh`, compatibility entrypoints in `scripts/*.py`, and `scripts/v23/`, `scripts/checks/`, `scripts/harness/`, `scripts/benchmark/`, `scripts/review/`, and `scripts/install/` |
| Machine contracts and tests | `schemas/`, `tests/v23/`, `.github/workflows/` |
| Examples and benchmarks | `examples/mini-goal-run/`, `examples/canonical-v23/`, `benchmarks/` |
| Release documentation | This file, [Change History](change-history.en.md), and their Chinese counterparts |

## Detailed path index

For installation, validation, and manual review, this is the detailed path index for the release package. It is the only human-visible release-inventory location in this repository.

- Root files: `VERSION`, `SKILL.md`, `RULES.md`, `goal-teams.md`, `AGENTS.md`, `CHANGELOG.md`, `README.md`, `README.en.md`, `agents/openai.yaml`.
- Rules and references: `references/goal-teams-runtime.md`, `references/default-AGENTS.md`, `references/invariants.md`, `references/compat.md`, `references/rules-ui.md`, `references/rules-testing.md`, `references/rules-loop.md`, `references/goal-teams-automation-protocol.md`, `references/goal-teams-production-pipeline.md`, `references/goal-teams-scripted-tooling.md`, `references/goal-teams-v2.3-contract.md`, `references/google-okf-bilingual-spec.md`, `references/ui-e2e-pixel-protocol.md`, `references/ui-visual-contract-protocol.md`, `references/subagent-dispatch-protocol.md`, `references/dual-review-protocol.md`.
- Members and prompts: `subagents/goal-*.toml`, `prompts/`, `prompts/lead/core.md`, `prompts/lead/requirement-card.md`, `prompts/members/shared.md`, `prompts/members/backend/prompt.md`, `prompts/members/backend/template.md`, `prompts/members/backend/workflow.md`, `prompts/members/backend/scripts.md`, `prompts/members/unit-test-designer/prompt.md`, `prompts/members/unit-test-runner/prompt.md`, `prompts/members/api-integration-test-designer/prompt.md`, `prompts/members/api-integration-test-runner/prompt.md`, `prompts/members/e2e-test-designer/prompt.md`, `prompts/members/e2e-test-runner/prompt.md`, `prompts/packets/member-goal-packet.md`, `prompts/packets/handoff-artifacts.md`, `prompts/packets/page-spec-card.md`, `prompts/packets/memory.md`, `prompts/packets/html-prototype-mock.md`, `prompts/packets/requirement-card.md`, `prompts/packets/dual-review-record.md`.
- Scripts: `scripts/check.sh`, `scripts/validate.py`, `scripts/install-local.sh`, `scripts/check-version-sync.py`, `scripts/check-routing-fixtures.py`, `scripts/check-agent-names.py`, `scripts/check-member-layout.py`, `scripts/validate-harness.py`, `scripts/pixel-diff.py`, `scripts/compare-artifacts.py`, `scripts/validate-dual-review.py`, `scripts/benchmark-runner.py`; implementation directories `scripts/v23/`, `scripts/checks/` (including `scripts/checks/check-routing-fixtures.py`), `scripts/harness/`, `scripts/benchmark/`, `scripts/review/`, and `scripts/install/`.
- Contracts, tests, and regression material: `schemas/`, `tests/v23/`, `.github/workflows/`, `examples/mini-goal-run`, `examples/canonical-v23/`, and `benchmarks/`.

## Pre-release checks

1. Run `./scripts/check.sh` to confirm the package structure, Skill frontmatter, member configurations, READMEs, and key rules remain aligned.
2. Check that `VERSION`, `SKILL.md`, and the READMEs use the same current-version language. A planning document is not version evidence.
3. Commit only release content the user has authorized. Development-process files, runtime traces, and user-maintained planning sources are outside the default GitHub publication scope.
4. The repository owner still decides the License or internal-sharing terms. Without that authorization, technical checks must not be presented as a public GA commitment.
