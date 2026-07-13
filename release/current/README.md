# Goal Teams V2.39 Release

V2.39 closes the structural Cache Evidence and Google OKF governance gaps while preserving Goal Teams' V2.38 prompt-cache schemas, fixtures, and read-only replay behavior.

- Every member package has a progressive `INDEX.md`.
- Runtime guidance is split into indexed files below the single-document budget.
- Local knowledge, historical process documents, integration catalogs, and private release evidence live in ignored `docs/`.
- The runtime package contains current release material only; legacy schemas and runtime identifiers remain solely for data compatibility.
- Deterministic gates validate member indexes, document size, context budget, security fixtures, package scope, and install lifecycle.
- Release contents include the prompt-cache manifest, protocol, V2.39 Cache Evidence runtime, OKF policy/checker, and current self-release Profile. The manifest remains the V2.38-compatible route-static order/budget SSOT; current self-release ordered refs point to V2.39 and V2.38 is replay-only. Final `stable_prefix_digest`/`runtime_prompt_digest` require a host-observed ordered request manifest and remain `null` when unavailable.
- Post-turn telemetry reports token-weighted share, uncached input, coverage, and invalid/unsupported counts. Without trusted host config attestation, cache conclusions remain unsupported; request hit rate remains unavailable without request events.
- Cache Evidence reports four independent states: structural validation `passed`, host integration `unavailable`, live probe `not_authorized`, and request hit rate `unavailable`. The release claim is limited to `structural_governance`; no live provider optimization, provider-hit, or request-hit-rate result is claimed.
- The V2.39 live executor remains fail-closed unless trusted capability, configuration, authorization, ordered-manifest, and provider-event semantics are all available. Historical V2.38 plan-only probe and artifacts remain read-only compatibility inputs.
- `scripts/v23/prompt_compilers.py` deterministically expands the single-source member common prefix and serializes Member Goal Packets with stable, dynamic, and combined digests plus legacy migration receipts.
- Tracked and packaged Markdown is classified deterministically under the Google OKF policy. Unknown/overlapping classification, unsafe YAML, stale identity/hash, package drift, or forbidden local roots fail closed.
- Goal Teams cannot force, clear, or guarantee a provider prompt cache.

Requirements: Python 3.11+ for the complete validated toolchain. The installer fails fast when a compatible Python with `tomllib` is unavailable.
