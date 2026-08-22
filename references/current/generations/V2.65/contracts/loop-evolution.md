---
type: Goal Teams Functional Contract
title: Proactive LOOP Evolution Contract
description: 定义每轮 LOOP 与发现问题后的用户项目反思、loop-review.md 和改进候选边界。
tags: [goal-teams, v2.65, loop, reflection, evolution]
timestamp: 2026-08-22T00:00:00+08:00
okf_version: "0.1"
---

# Proactive LOOP Evolution Contract

- `contract_id`: `CONTRACT-LOOP-EVOLUTION-V265`
- `purpose`: 用户在使用 Goal Teams Skill 的每轮 LOOP 结束后，或发现问题时，为当前项目生成一次可追溯反思并写入项目 `loop-review.md`。

## trigger_and_exclusion_facts

- 触发：`loop_end`、`problem_detected` 或 `user_correction`。
- 排除：反思不能自动修改全局 Skill、Prompt、Harness、权限或发布规则；候选改进必须进入新的 TaskExactSet、预算、授权和验证链。

## inputs

- loop/round identity、plan/graph revision、TaskExactSet/source digest、当前结果、问题 Evidence、open gaps 和既有 Review chain。

## obligations_and_outputs

- 每次 Review 评估 prompt、context、Skill、graph、materials、Harness、Evidence、members、tools、workflow、runtime 与 cost；无发现维度显式记录 `no_finding`。
- `loop-review.md` 是用户当前项目的 append-only 人类可读投影；签名 Review frame 与 Review Capsule 绑定 previous digest、round、sequence、evidence 和 source revision。
- 问题先做 root-cause 分类，再决定 `no_change|required_fix|candidate_only|replan|stop`；重复 issue 必须幂等去重。
- 每轮生成独立不可变 Capsule；原始 round ID 不直接进入路径，文件名使用完整 digest 派生。
- 提示词、上下文、Skill、资料或 Harness 的提升建议必须写明预期收益、风险、验证方法、消费者和授权边界。
- `not_run|blocked|failed|stale|invalid` 保持原状态；反思文本不能把缺失证据改写成成功。

## oracles_and_evidence

- `schemas/v2.65/loop-review.schema.json`、`schemas/v2.65/loop-coordinator.schema.json`、append receipt、round receipt、reconcile receipt、Capsule digest 与文件 exact readback。

## dependencies

- `FUNCTION-GRAPH-ENGINEERING-V265`
- `CONTRACT-REVIEW-COMPLETION-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`

## owned_rule_ids

- `GT265-LOOP-REFLECT-EACH-ROUND`: 每轮 LOOP 结束都生成一次当前项目反思并 append 到 `loop-review.md`。
- `GT265-LOOP-REFLECT-ON-PROBLEM`: 发现问题时立即记录观察事实、根因、影响、证据和是否 replan，不等待轮末掩盖首个失败。
- `GT265-LOOP-IMPROVEMENT-DIMENSIONS`: 反思至少逐项评估 prompt、context、Skill、graph、materials、Harness、Evidence、members、tools、workflow、runtime 与 cost。
- `GT265-LOOP-CANDIDATE-BOUNDARY`: 改进建议仅为 candidate；任何实际 Skill/Prompt/权限/发布变化都需要独立消费者、TaskExactSet、授权和验证。
- `GT265-LOOP-APPEND-ONLY`: Review chain、round identity 和 Capsule digest 不可覆盖；重复 issue 幂等，跨轮输出使用独立路径。
