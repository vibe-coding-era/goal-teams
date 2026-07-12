---
type: Goal Teams Project Sizing Rules
title: Goal Teams V2.35 项目分级与正交路由
description: project_size 与 work_type 双轴、风险覆盖、专项加载和研发测试门禁规则。
tags: [goal-teams, v2.35, routing, project-size, okf]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.35 项目分级与正交路由

本文件只在进入持久化执行路由时按需加载。`plan_preview` 继续使用 V2.33 显式 no-write 判定，不创建 ledger、任务或专家派发。

## 输入合同

路由只接收结构化事实，不从自由文本猜规模：

```json
{
  "schema_version": "goal-teams-project-route-v2.35",
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
  "specialist_requests": []
}
```

- 所有字段必填且类型精确；未知字段、缺字段、字符串布尔值、未知枚举、多源冲突值一律 fail closed。
- `specialist_requests` 只允许 `security|performance|refactor|sqa`，只能增加检查，不能删除门禁。
- `project_size` 与 `work_type` 是正交事实；`bugfix` 不是 size，risk 也不能改写 size。
- 相同规范化输入必须生成 byte-equivalent policy body、稳定排序的 `rule_set` 与 `reason_codes`。

## 固定优先级

1. 系统/用户授权与 `references/invariants.md` 的 L0 安全边界。
2. `security_sensitive|external_write|auth|payment|migration|destructive` 为 true，或 `risk=high|critical`：强制 `profile=regulated`、`required_review_class=safety`、`security=required`。
3. `ui=true`：强制独立 E2E；规模、bugfix 或专家缺省不能绕过。
4. `work_type=bugfix`：Architecture、Environment、TDD red/green 和 integration 必需；UI bugfix 再加 E2E。
5. 应用 `project_size` 默认矩阵。
6. 应用用户已确认的显式专项请求，只做加法。

低优先级规则不得放宽高优先级规则；冲突时返回 blocked 与稳定 `E_V235_*` 错误码。

## 默认矩阵

| 组合 | 专项默认 | 研发与证据门 | 测试门 |
| --- | --- | --- | --- |
| large + Release | security、performance、refactor、sqa 全部 required | 完整需求、Architecture、Environment、Evidence、release/post-release | 适用 unit/TDD/integration/CLI/API；UI 加 E2E；full regression |
| large + 非 Release | 风险或显式请求决定；Release 前重新路由 | Architecture、Environment、独立测试不减 | 技术面适用测试 + full regression |
| medium + feature | 四专家默认不加载 | Architecture、Environment、独立测试与 Evidence 必需 | 技术面适用测试；UI 强制 E2E |
| small + feature | 四专家默认不加载；可缩短需求文档 | Architecture、Environment、独立测试与 Evidence 必需 | 技术面适用测试；UI 强制 E2E |
| 任意 size + bugfix | 风险或显式请求决定 | 可缩短需求文档，不得缩 Architecture/Environment | TDD red/green + integration；UI 强制 E2E |
| 任意 size + 安全覆盖 | security required | regulated + safety，不得被规模降级 | safety 双重复核与适用回归 |

“小型项目直接进入开发”只表示可缩短需求材料，不表示跳过 Architecture、Environment、独立测试、Harness、Evidence 或独立验证。

## 输出合同

输出必须保留 `project_size`、`work_type`，并包含：

```text
profile
required_review_class
gates.architecture/environment/tdd/integration/e2e/full_regression/release_evidence
specialists.security/performance/refactor/sqa
rule_set
reason_codes
blocked
```

专项至少一个为 required/requested 时，Lead 才加载 `references/rules-specialists.md` 和对应单一成员包；测试设计、执行或评审时才加载 `references/test-case-assertion-protocol.md`。禁止把四个专家包预载进启动上下文。

## 失败语义

- 未知或冲突输入：blocked，禁止猜测或静默回退。
- 高风险覆盖缺失：blocked，`required_review_class` 不得低于 safety。
- `ui=true` 而 E2E 非 required：blocked。
- medium/small 缺 Architecture、Environment、独立测试或 Evidence：blocked。
- bugfix 缺 TDD 或 integration：blocked。
