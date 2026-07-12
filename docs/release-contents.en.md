# Release Contents

This document is the English index of the visible Goal Teams package. Its Chinese counterpart is [release-contents.md](release-contents.md). The runtime version always comes from the repository-root `VERSION`; applicable runtime rules come from `SKILL.md`, `RULES.md`, and the relevant contracts in `references/` and `prompts/`.

## Current boundary

- This inventory lists only verifiable repository contents. It does not claim unimplemented capabilities.
- The current product version is `V2.36`; ordinary projects use general core policy `V2.5`, while existing machine data remains compatible with the legacy `V2.3` schema. This index cannot replace contracts or validation.
- `goal-teams-self-release-v2.36` is used only to release the Goal Teams repository itself. Its 52 assertions, iterations 9/11, four-dimension scoring, and public archive are not global rules for ordinary projects.
- The manually maintained `SKILL.md` and READMEs are the baseline. This inventory cannot override them or replace scripted validation.
- The local planning source `docs/后续版本规划 V3.3-3.5.md` is user-maintained and is not part of the repository or install package. AI must not edit it and, without separate user authorization, must not include it in a GitHub commit. Planning text is not a release commitment.

## Package inventory

| Category | Current release contents |
| --- | --- |
| Root files | `VERSION`, `SKILL.md`, `RULES.md`, `goal-teams.md`, `AGENTS.md`, `CHANGELOG.md`, `README.md`, `README.en.md`, `agents/openai.yaml` |
| Rules and compatibility | `references/goal-teams-core-v2.5.md`, `references/profiles/goal-teams-self-release-v2.36.md`, `references/goal-teams-runtime.md`, `references/default-AGENTS.md`, `references/invariants.md`, `references/compat.md`, `references/rules-ui.md`, `references/rules-testing.md`, `references/rules-loop.md`, `references/goal-teams-automation-protocol.md`, `references/goal-teams-production-pipeline.md`, `references/goal-teams-scripted-tooling.md`, `references/goal-teams-v2.3-contract.md`, `references/google-okf-bilingual-spec.md`, `references/ui-e2e-pixel-protocol.md`, `references/ui-visual-contract-protocol.md`, `references/subagent-dispatch-protocol.md`, `references/dual-review-protocol.md` |
| Members and prompts | `subagents/goal-*.toml`, `prompts/`, `prompts/lead/`, `prompts/members/`, `prompts/packets/` |
| Tooling and checks | `scripts/check.sh`, compatibility entrypoints in `scripts/*.py`, and `scripts/v23/`, `scripts/checks/`, `scripts/harness/`, `scripts/benchmark/`, `scripts/review/`, and `scripts/install/` |
| Machine contracts and tests | `schemas/`, `tests/v23/`, `.github/workflows/` |
| Examples and benchmarks | `examples/mini-goal-run/`, `examples/canonical-v23/`, `benchmarks/` |
| Release documentation | This file, [Change History](change-history.en.md), the bilingual [V2.36 Pre-audit Release Summary](v2.36-release-summary.en.md), and public documents archived by the self-release Profile under a validated release version |

## Detailed path index

For installation, validation, and manual review, this is the detailed path index for the release package. It is the only human-visible release-inventory location in this repository.

- Root files: `VERSION`, `SKILL.md`, `RULES.md`, `goal-teams.md`, `AGENTS.md`, `CHANGELOG.md`, `README.md`, `README.en.md`, `agents/openai.yaml`.
- Rules and references: the compatibility files above plus the general-core entrypoint `references/goal-teams-core-v2.5.md`, the repository-only `references/profiles/goal-teams-self-release-v2.36.md`, and conditional entrypoints `references/rules-project-sizing.md`, `references/rules-specialists.md`, and `references/test-case-assertion-protocol.md`.
- Members and prompts: `subagents/goal-*.toml`, `prompts/`, `prompts/lead/core.md`, `prompts/lead/requirement-card.md`, `prompts/members/shared.md`, `prompts/members/backend/prompt.md`, `prompts/members/backend/template.md`, `prompts/members/backend/workflow.md`, `prompts/members/backend/scripts.md`, `prompts/members/unit-test-designer/prompt.md`, `prompts/members/unit-test-runner/prompt.md`, `prompts/members/api-integration-test-designer/prompt.md`, `prompts/members/api-integration-test-runner/prompt.md`, `prompts/members/e2e-test-designer/prompt.md`, `prompts/members/e2e-test-runner/prompt.md`, `prompts/packets/member-goal-packet.md`, `prompts/packets/handoff-artifacts.md`, `prompts/packets/page-spec-card.md`, `prompts/packets/memory.md`, `prompts/packets/html-prototype-mock.md`, `prompts/packets/requirement-card.md`, `prompts/packets/dual-review-record.md`.
- Scripts: `scripts/check.sh`, `scripts/validate.py`, `scripts/install-local.sh`, `scripts/check-version-sync.py`, `scripts/check-routing-fixtures.py`, `scripts/check-agent-names.py`, `scripts/check-member-layout.py`, `scripts/validate-harness.py`, `scripts/pixel-diff.py`, `scripts/compare-artifacts.py`, `scripts/validate-dual-review.py`, `scripts/benchmark-runner.py`, and `scripts/validate-test-case-contract.py`; implementation directories `scripts/v23/`, `scripts/checks/` (including `scripts/checks/check-routing-fixtures.py` and `scripts/checks/validate-test-case-contract.py`), `scripts/harness/`, `scripts/benchmark/`, `scripts/review/`, and `scripts/install/`.
- Contracts, tests, and regression material: `schemas/`, `tests/v23/`, `.github/workflows/`, `examples/mini-goal-run`, `examples/canonical-v23/`, and `benchmarks/`.
- Public completion archives: only the self-release Profile may write `docs/archive/<release_version>/<delivery_id>/`; the release version comes from a validated descriptor, and the archive contains only completed/public documents plus a public manifest that passed unified redaction, sanitization, and independent audit.

## Pre-release checks

1. Run `./scripts/check.sh` to confirm the package structure, Skill frontmatter, member configurations, READMEs, and key rules remain aligned.
2. Check that `VERSION`, `SKILL.md`, and the READMEs use the same current-version language. A planning document is not version evidence.
3. Commit only release content the user has authorized. Development-process files, runtime traces, and user-maintained planning sources are outside the default GitHub publication scope. A public archive must pass the sanitizer and must not include invocation text, transport handles, internal paths, runtime logs, or private provenance.
4. The repository owner still decides the License or internal-sharing terms. Without that authorization, technical checks must not be presented as a public GA commitment.
