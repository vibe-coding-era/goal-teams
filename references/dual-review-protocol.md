# Dual Review Protocol V1.94

V1.94 要求对比和校验类任务采用 LLM + 脚本双重复核。脚本负责确定性检查，LLM reviewer 负责语义、风险、上下文和用户目标一致性判断。二者不能互相替代。

## 适用场景

- 代码、文档、SPEC、模板、benchmark、配置或生成产物对比。
- UI E2E、像素级对比、artifact diff、schema、Harness 或安装结构检查。
- 任何要给出 `pass`、`complete`、`release ready` 或 `done` 结论的验收任务。

## 复核职责

| 复核者 | 负责内容 | 不负责内容 |
| --- | --- | --- |
| 脚本复核 subagent | 文件存在、schema、版本同步、路径、hash、像素指标、报告结构 | 业务语义、用户意图、风险取舍 |
| LLM 复核 subagent | 语义正确性、规则完整性、风险、需求一致性、是否遗漏 | 精确 hash、像素指标、schema 机械一致性 |

## 决策规则

- 脚本失败时，最终结论不能是 `pass`。
- LLM 复核失败时，最终结论不能是 `pass`。
- 两者结论不一致时，最终结论为 `conditional` 或 `blocked`，并交给 Lead 重新规划。
- 只有脚本复核和 LLM 复核都通过，且证据路径齐全，才允许 `pass`。

## 记录格式

```json
{
  "artifact": "path-or-task-id",
  "script_review": {
    "tool": "scripts/review/compare-artifacts.py",
    "status": "passed",
    "evidence_path": "path/to/script-report.json"
  },
  "llm_review": {
    "reviewer": "评审-具体任务复核",
    "status": "passed",
    "evidence_path": "path/to/review.md",
    "summary": "语义和风险均通过"
  },
  "final_decision": {
    "status": "pass",
    "reason": "脚本复核和 LLM 复核均通过"
  }
}
```

使用 `scripts/review/validate-dual-review.py` 或兼容入口 `scripts/validate-dual-review.py` 校验记录结构。
