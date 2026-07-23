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
  "event_type": "discovered|classified|assigned|evidence_added|resolved|reopened|waived",
  "dimension": "api_testing",
  "summary": "问题摘要",
  "severity": "low|medium|high|critical",
  "status": "open|in_progress|resolved|waived",
  "artifact_refs": [],
  "evidence_refs": [],
  "agent_run_id": "concrete-run-id",
  "timestamp": "RFC3339"
}
```

规则：

- 新问题分配新 `issue_id`，不得复用或覆盖旧问题。
- `resolved` 必须引用修复与独立验证 Evidence；仅提交代码或说明不算解决。
- `waived` 必须保留风险、范围、批准者和到期条件；waiver 不自动计入满分。
- 得分器按当前投影读取 open/waived 问题，但审计仍可重放全部历史。
