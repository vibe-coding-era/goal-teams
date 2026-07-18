---
type: Goal Teams Project Sizing Rules
title: Goal Teams V2.36 项目分级与 Profile 路由
description: Core V2.5 的规模/风险分级、UI 模式、Profile 派生和研发测试门禁规则。
tags: [goal-teams, v2.36, routing, project-size, policy-profile, okf]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.36 项目分级与 Profile 路由

本文件只在进入持久化执行路由时按需加载。`plan_preview` 继续使用 V2.33 显式 no-write 判定，不创建 ledger、任务或专家派发。

## 输入合同

路由只接收结构化事实，不从自由文本猜规模：

```json
{
  "schema_version": "goal-teams-project-route-v2.36",
  "product_version": "V2.36",
  "target_kind": "generic_project|goal_teams_repository",
  "project_size": "large|medium|small",
  "work_type": "feature|bugfix",
  "release": true,
  "ui": false,
  "backend": true,
  "api": true,
  "cli": true,
  "tests": true,
  "risk": "low|medium|high|critical",
  "security_sensitive": false,
  "external_write": false,
  "auth": false,
  "payment": false,
  "migration": false,
  "destructive": false,
  "ui_mode": "none|original|replica",
  "specialist_requests": []
}
```

- 所有字段必填且类型精确；未知字段、缺字段、字符串布尔值、未知枚举、多源冲突值一律 fail closed。
- `specialist_requests` 只允许 `security|performance|refactor|sqa`，只能增加检查，不能删除门禁。
- `project_size` 与 `work_type` 是正交事实；`bugfix` 不是 size，risk 也不能改写 size。
- `target_kind` 必须由可信 workspace adapter 从仓库身份生成，不能根据自由文本猜测；只有 `goal_teams_repository + release=true + product_version=V2.36` 派生自发布 Profile。
- `ui=false` 时 `ui_mode` 必须为 `none`；`ui=true` 时只能为 `original|replica`。`policy_profile|task_type` 只由路由器生成；`state_gate_profile` 可省略，显式提供时必须与派生值精确匹配。
- 相同规范化输入必须生成 byte-equivalent policy body、稳定排序的 `rule_set` 与 `reason_codes`。

## 固定优先级

1. 系统/用户授权与 `references/invariants.md` 的 L0 安全边界。
2. `security_sensitive|external_write|auth|payment|migration|destructive` 为 true，或 `risk=high|critical`：强制 `profile=regulated`、`required_review_class=safety`、`security=required`。
3. Goal Teams 仓库当前 V2.40 自发布：强制 `policy_profile=goal-teams-self-release-v2.40` 与 `profile=full|regulated`，并加载专项 Profile；历史 V2.36/V2.37/V2.38/V2.39 route 只用于兼容 replay。
4. reference-driven/复刻 UI：强制 `profile=full|regulated`、独立 E2E 与 pixel comparison；原创 UI 只按规模/风险分级，不自动 full。
5. `large|release`：至少 full；`medium|risk=medium|backend|api`：至少 standard；其余符合 low-risk 条件的 small 局部任务为 lite。
6. `work_type=bugfix` 只增加与行为影响匹配的 regression/TDD/integration，不再跨规模强制完整 Architecture/Environment。
7. 应用用户已确认的显式专项请求，只做加法。

低优先级规则不得放宽高优先级规则；V2.36 路由冲突返回 blocked 与稳定 `E_V236_*` 错误码，V2.35 replay 保留原 `E_V235_*`。

## 默认矩阵

| 路由 | 典型条件 | 研发与证据门 | 测试门 |
| --- | --- | --- | --- |
| `lite` | small + low risk + 非 release + 非 backend/API；可为局部 CLI 或原创 UI | scoped contract、目标 Evidence；Architecture 不要求，Environment 为轻量 preflight | 变更行为的 targeted regression；原创 UI 执行关键浏览器路径/DOM/截图，不要求 pixel baseline |
| `standard` | medium，或 small 但含 backend/API，或 risk=medium | 影响分析、Environment、Evidence、独立 Review；Architecture 仅合同/API/数据/跨模块边界变化时 required | 适用独立测试；bugfix 要 targeted regression/TDD，backend-only 局部修复的 integration 为条件门，API/CLI 或跨组件边界变化才 required；原创 UI E2E required |
| `full` | large、任意 release、replica/reference-driven UI、多系统 | Architecture、Environment、独立测试、Harness/Evidence、Completion Audit 强门 | 适用 TDD/integration/E2E/full regression；replica 强制 pixel comparison |
| `regulated` | high/critical risk 或任一安全覆盖 | full 全部门 + safety/授权/安全 Evidence | safety 双重复核与适用全回归 |

Lite/Standard 不是“少写文档但仍走 Full”。它们减少不适用门禁，但 scoped contract、当前 Evidence、适用测试、独立结论与安全边界仍不可省略。

## 输出合同

输出必须保留 `project_size`、`work_type`，并包含：

```text
profile
policy_profile
state_gate_profile
task_type
required_review_class
gates.contract/architecture/environment/independent_tests/evidence/targeted_validation/tdd/integration/e2e/pixel_comparison/full_regression/release_evidence
specialists.security/performance/refactor/sqa
rule_set
reason_codes
blocked
```

专项至少一个为 required/requested 时，Lead 才加载 `references/rules-specialists.md` 和对应单一成员包；测试设计、执行或评审时才加载 `references/test-case-assertion-protocol.md`。禁止把四个专家包预载进启动上下文。

## 失败语义

- 未知或冲突输入：blocked，禁止猜测或静默回退。
- 高风险覆盖缺失：blocked，`required_review_class` 不得低于 safety。
- `ui` 与 `ui_mode` 冲突：blocked；原创 UI 被要求 reference baseline 或 replica 未加载 pixel protocol 也 blocked。
- Lite/Standard 缺当前 Evidence 或当前等级适用检查：blocked；不因 Architecture 为 conditional/not_required 而阻塞。
- Full/Regulated 缺 Architecture、Environment、独立测试、Evidence 或适用全回归：blocked。
- 调用方提交 `policy_profile|task_type`，或显式 `state_gate_profile` 与派生值不匹配：blocked；省略 `state_gate_profile` 仍自动应用派生门禁。
