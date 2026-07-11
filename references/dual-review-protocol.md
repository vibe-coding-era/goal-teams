# Dual Review Protocol V2.3

V2.3 按 `review_class` 分级。脚本负责可机械判断的事实，LLM reviewer 负责语义、风险、上下文和用户目标一致性；只有 comparison/safety 等同时需要两类判断的任务强制双重复核，不能为纯 semantic 任务编造无意义脚本结果。

最低等级只从 `harness_contract.task_type`、`required_review_class` 与风险推导；外层同名字段无效，review 记录不得自降级。semantic 与 structural 不能互相替代；它们可升级为 comparison/safety，comparison 可升级为 safety，safety 不可降级。replica/comparison 至少 comparison，security/external-write/regulated 至少 safety。

## 适用场景

| review_class | 必需复核 | 例子 |
| --- | --- | --- |
| `structural` | 确定性脚本；语义复核可结构化 N/A | schema、目录、格式、hash |
| `comparison` | 脚本 + LLM | artifact diff、像素对比、迁移前后等价性 |
| `safety` | 脚本 + 独立 LLM/安全 reviewer | 权限、secret、生产边界 |
| `semantic` | 独立 LLM；无适用脚本时写结构化 N/A 并由 reviewer 接受 | PRD、用户意图、风险取舍 |

## 复核职责

| 复核者 | 负责内容 | 不负责内容 |
| --- | --- | --- |
| 脚本复核 subagent | 文件存在、schema、版本同步、路径、hash、像素指标、报告结构 | 业务语义、用户意图、风险取舍 |
| LLM 复核 subagent | 语义正确性、规则完整性、风险、需求一致性、是否遗漏 | 精确 hash、像素指标、schema 机械一致性 |

## 决策规则

- 当前 review_class 要求脚本时，脚本失败则最终结论不能是 `pass`。
- 当前 review_class 要求 LLM 复核时，LLM 失败则最终结论不能是 `pass`。
- 适用复核结论不一致时，按可执行性记录单一 `check_state=failed` 或 `blocked`，交给 Lead replan。
- 只有该 review_class 的全部必需复核通过，证据文件与 artifact version/hash 绑定，且 author/reviewer `agent_run_id` 不同，才允许 `final_decision.status=pass`。
- author/reviewer `agent_run_id` 相同时必须拒绝，标准机器错误码是 `E_REVIEW_SELF`。
- 不适用原因必须结构化并由独立 reviewer 接受；自由文本不能绕过门禁。
- 原领域脚本结果及日志先固化为报告中的 `domain_execution`；Completion Gate 只重放独立的 `integrity_replay` runtime-locked verifier，重验 contained artifact ref/hash、领域执行与 review `binding_digest`。两层日志必须不同，replay 不得早于领域执行结束；它不执行领域 argv，也不代表重新运行原脚本。
- comparison 的义务在升级为 safety 时仍保留。V2.3 generic comparison 只接受 trusted `compare-artifacts` 的 `exact_hash_match`：actual 与预先独立批准的 baseline 必须是不同 path/inode、各自 hash current 且 hash 相同；tool path/hash、规范 argv 与 exact JSON log 都由 runtime 重算。阈值型 pixel comparison 使用专用 pixel validator，不接受任意工具自报 `ok`。

## 记录格式

```json
{
  "schema_version": "goal-teams-v2.3",
  "review_class": "comparison",
  "author_run_id": "RUN-AUTHOR-001",
  "reviewer_run_id": "RUN-REVIEWER-001",
  "artifact": {
    "artifact_ref": "path/to/artifact",
    "artifact_sha256": "<sha256>",
    "artifact_version": "V2.3"
  },
  "script_review": {
    "reviewer_run_id": "RUN-SCRIPT-REVIEWER-001",
    "tool": "scripts/review/compare-artifacts.py",
    "status": "passed",
    "exit_code": 0,
    "evidence_path": "path/to/script-report.json",
    "evidence_sha256": "<sha256>",
    "evidence_size": 123,
    "artifact_sha256": "<sha256>",
    "artifact_version": "V2.3"
  },
  "llm_review": {
    "reviewer_run_id": "RUN-REVIEWER-001",
    "status": "passed",
    "evidence_path": "path/to/review.md",
    "evidence_sha256": "<sha256>",
    "summary": "语义和风险均通过",
    "artifact_sha256": "<sha256>",
    "artifact_version": "V2.3"
  },
  "final_decision": {
    "status": "pass",
    "reason": "脚本复核和 LLM 复核均通过"
  }
}
```

`script_review.evidence_path` 指向的 JSON 报告还必须含：

```json
{
  "binding_digest": "<sha256>",
  "comparison_mode": "exact_hash_match",
  "tool_ref": "scripts/review/compare-artifacts.py",
  "tool_sha256": "<sha256>",
  "comparison_inputs": {"actual_ref": "<artifact>", "actual_sha256": "<sha256>", "baseline_ref": "<approved baseline>", "baseline_sha256": "<same sha256>", "baseline_approver_run_id": "<registered independent run>", "baseline_approved_at": "<date-time before execution>"},
  "domain_execution": {"argv": ["<real tool>"], "cwd": ".", "started_at": "<date-time>", "ended_at": "<date-time>", "exit_code": 0, "log_path": "reviews/domain.log", "log_sha256": "<sha256>", "log_size": 1},
  "integrity_replay": {"argv": ["<runtime-locked verifier>", "<artifact>", "<artifact sha256>", "<binding digest>"], "cwd": ".", "started_at": "<date-time>", "ended_at": "<date-time>", "exit_code": 0, "log_path": "reviews/integrity.log", "log_sha256": "<sha256>", "log_size": 1}
}
```

使用 `scripts/review/validate-dual-review.py` 或兼容入口 `scripts/validate-dual-review.py` 校验记录结构。
