---
type: Knowledge Requirement
title: Grounded answers cite Current evidence
description: A factual answer cites an exact Current Claim occurrence.
timestamp: 2026-08-07T20:00:01+08:00
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: product.current
knowledge_id: REQ-001
revision: "1"
owner: answer-contract-owner
lifecycle: current
modality: requirement
epistemic_state: documented
sensitivity: internal
aliases_en: [grounded answer, cited answer]
---

# Grounded answers cite Current evidence

### CLM-REQ-001-01

A factual answer cites an exact Current Claim occurrence.

#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-REQ-001-01` | `HAS_AC` | `product.current:AC-001@1#CLM-AC-001-01` | [Citation AC](../acceptance/target.md#CLM-AC-001-01) | `asserted` | `declared` | [User evidence](../evidence/request.md#CLM-EVD-001-01) |

#### Evidence

- [User evidence](../evidence/request.md#CLM-EVD-001-01)
