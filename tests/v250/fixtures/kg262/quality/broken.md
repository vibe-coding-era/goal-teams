---
type: Knowledge Requirement
title: Broken relation remains observable
description: This fixture has a dangling asserted relation.
timestamp: not-a-timestamp
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: product.quality
knowledge_id: REQ-BROKEN-001
revision: "1"
owner: unresolved-owner
lifecycle: current
modality: requirement
epistemic_state: conflicted
sensitivity: internal
---

# Broken relation remains observable

### CLM-REQ-BROKEN-001-01

The usable portion of the document remains queryable.

#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-BROKEN-001` | `HAS_AC` | `product.quality:AC-MISSING@1#CLM-MISSING-01` | [Missing target](missing.md#CLM-MISSING-01) | `asserted` | `declared` | [Missing evidence](missing-evidence.md#CLM-EVD-MISSING-01) |
| `REL-CONFLICT-SUPPORT` | `SUPPORTS` | `product.quality:REQ-BROKEN-001@1#CLM-REQ-BROKEN-001-01` | [Self](broken.md#CLM-REQ-BROKEN-001-01) | `asserted` | `declared` | [Self](broken.md#CLM-REQ-BROKEN-001-01) |
| `REL-CONFLICT-REFUTE` | `REFUTES` | `product.quality:REQ-BROKEN-001@1#CLM-REQ-BROKEN-001-01` | [Self](broken.md#CLM-REQ-BROKEN-001-01) | `asserted` | `declared` | [Self](broken.md#CLM-REQ-BROKEN-001-01) |
