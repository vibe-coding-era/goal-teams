---
type: Goal Teams TaskList
title: Generated TaskList
description: Deterministic projection of the V2.3 append-only event ledger.
tags: [goal-teams, tasklist, v2.3]
okf_version: "0.1"
schema_version: "goal-teams-v2.3"
ledger_revision: 21
schema_source_hash: "531ecaa680055e7e7bf887605fba7246d992fe30598f9101e647935b5e31d60e"
generated: true
---

# Generated TaskList

| Task | Title | State | Check | Required | Blocking | Owner member | Owner run | Validator member | Validator run | Merge owner | Attempt | Revision | Requirements | AC | Artifacts | Evidence | Harness | Last event |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-CAN-BLOCKED | Optional blocked branch | blocked | not_started | false | false | 实现-Canonical | RUN-CAN-OWNER | 评审-Canonical | RUN-CAN-REVIEWER | RUN-CAN-LEDGER-OWNER | ATT-CAN-BLOCKED | 2 | REQ-CAN-003 | AC-CAN-003 |  |  | versions/V2.3/harness/harness.json | EVT-CAN-007 |
| TASK-CAN-BLOCKED-RECOVERY | Required blocked then recovered branch | accepted | passed | true | true | 实现-Canonical | RUN-CAN-OWNER | 评审-Canonical | RUN-CAN-REVIEWER | RUN-CAN-LEDGER-OWNER | ATT-CAN-BLOCKED-RECOVERY | 7 | REQ-CAN-002 | AC-CAN-002 | versions/V2.3/evidence/recovery.txt | EVD-CAN-002 | versions/V2.3/harness/harness.json | EVT-CAN-021 |
| TASK-CAN-FAILURE-RECOVERY | Historical check failure and recovery branch | review | failed | false | false | 实现-Canonical | RUN-CAN-OWNER | 评审-Canonical | RUN-CAN-REVIEWER | RUN-CAN-LEDGER-OWNER | ATT-CAN-RECOVERY | 7 | REQ-CAN-004 | AC-CAN-004 |  |  | versions/V2.3/harness/harness.json | EVT-CAN-014 |
| TASK-CAN-SUCCESS | Required success branch | accepted | passed | true | true | 实现-Canonical | RUN-CAN-OWNER | 评审-Canonical | RUN-CAN-REVIEWER | RUN-CAN-LEDGER-OWNER | ATT-CAN-SUCCESS | 5 | REQ-CAN-001 | AC-CAN-001 | versions/V2.3/evidence/artifact.txt | EVD-CAN-001 | versions/V2.3/harness/harness.json | EVT-CAN-005 |
