---
type: Goal Teams Testing Capability Issue Ledger Template
title: V2.44 测试能力问题账本
description: 为 API 与 E2E 测试能力问题提供 append-only 事件格式。
tags: [goal-teams, v2.44, testing, issue-ledger]
timestamp: 2026-07-23T00:00:00+08:00
okf_version: "0.1"
---

# V2.44 测试能力问题账本

账本文件使用 JSONL，每行一个 event。历史 event 不修改、不删除；状态由稳定排序的 reducer 投影。

```json
{
  "schema_version": "goal-teams-testing-issue-event-v2.44",
  "event_id": "uuid-or-stable-event-id",
  "issue_id": "GT244-TEST-013",
  "event_type": "discovered|started|resolved|reopened",
  "dimension": "api_testing",
  "summary": "问题摘要",
  "severity": "low|medium|high|critical",
  "status": "open|in_progress|resolved",
  "artifact_refs": [],
  "evidence_refs": [],
  "agent_run_id": "concrete-run-id",
  "timestamp": "RFC3339"
}
```

规则：

- 新问题分配新 `issue_id`，不得复用或覆盖旧问题。
- 每个问题必须先有且只有一个 `discovered/open` 事件；后续只允许 `started`、`resolved`、`reopened` 的合法状态转换。
- `dimension` 与 `summary` 必须和 canonical manifest 中同一 `issue_id` 完全一致；manifest 与账本问题集合必须相等。
- `resolved` 必须引用修复与独立验证 Evidence；每个 `evidence_refs` 项使用 `{"path":"...","sha256":"..."}`，且文件必须存在、无 symlink、摘要一致。仅提交代码或说明不算解决。
- waiver 不计入满分，也不是 V2.44 满分账本的合法最终状态。
- 得分器重放全部历史；缺失 discovery、resolved-only 历史、非法转换、无关证据或删除已知问题全部 fail closed。
