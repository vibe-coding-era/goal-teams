---
type: Dual Review Record Template
title: Dual Review Record OKF 模板
description: 脚本复核和 LLM 复核的双重复核记录模板。
tags: [goal-teams, okf, dual-review]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Dual Review Record

对比和校验类任务必须同时记录脚本复核和 LLM 复核：

```text
Dual Review Record（双重复核记录）:
- artifact:
- script_review:
  - tool:
  - status: passed | failed | blocked
  - evidence_path:
  - summary:
- llm_review:
  - reviewer:
  - status: passed | failed | blocked
  - evidence_path:
  - summary:
- final_decision:
  - status: pass | conditional | blocked
  - reason:
```

规则：

- 脚本失败时，最终结论不能是 `pass`。
- LLM 复核失败时，最终结论不能是 `pass`。
- 两者不一致时，交给 Lead 重新规划或要求补证据。
- 可用 `scripts/review/validate-dual-review.py` 校验 JSON 记录。
