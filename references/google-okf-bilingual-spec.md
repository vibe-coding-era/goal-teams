---
type: Reference
title: Google OKF 本地双语规范 / Local Bilingual Google OKF Specification
description: Goal Teams 对 Google Open Knowledge Format v0.1 Draft 的本地中英文落地规范。
resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
tags: [goal-teams, okf, knowledge-catalog, documentation-format]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# 中文规范

本文是 Goal Teams 使用的本地 OKF 规范版本，来源为 GoogleCloudPlatform Knowledge Catalog（`knowledge-catalog`）仓库中的 Open Knowledge Format v0.1 Draft。Goal Teams 生成的 Markdown 文档默认采用 OKF：一个文档就是一个 Concept Document，顶部用 YAML frontmatter 记录机器可读元数据，正文用结构化 Markdown 记录人类和 agent 可读内容。

## 1. 目标

- 所有 Goal Teams 生成文档默认可被人和 agent 直接读取、diff、审查和迁移。
- 每份文档都能通过 `type`、`title`、`description`、`tags`、`timestamp` 等字段被检索、路由和索引。
- SPEC、tasklist、Harness、Evidence、Page Specification Card、HTML Prototype MOCK 和 memory 之间通过路径或 Markdown 链接保持可追溯。
- OKF 不替代领域 schema；API、数据模型、组件 props、Harness schema 等仍保留原有格式，并作为 OKF 文档正文或扩展字段的一部分。

## 2. Bundle 目录

当用户没有指定输出目录时，Goal Teams 默认把本轮输出写入：

```text
GoalTeamsWork-<project_version>/
```

推荐结构：

```text
GoalTeamsWork-<project_version>/
  index.md
  memory.md
  log.md
  versions/
    <artifact_version>/
      index.md
      ledger/events.jsonl
      ledger/checkpoint.json
      TaskList.md        # reducer-generated projection
      identity/registry.json
      plan.md
      progress.md
      decisions.md
      goal-packet.md
      spec/
        requirement-card.md
        requirement-spec-card.md
        PRD.md
        page-spec-card.md
        frontend-architecture-design.md
        backend-architecture-design.md
        HTML-prototype.html
        test-plan.md
        acceptance.md
      tests/
        unit/
        api-integration/
        e2e/
        reports/
      artifacts/
        e2e/
        pixel/
        review/
      harness/harness.json
      harness/traceability.json
      evidence/evidence.jsonl
      reviews/dual-review.json
      reviews/semantic-review.md
      audit/completion-audit.json
```

根部 `index.md` 用于跨版本渐进式索引，`log.md` 可记录目录更新历史，`memory.md` 用于记录用户重要设置、配置和上下文摘要。所有 SSOT 产出物必须位于 `versions/<artifact_version>/`；机器闭包路径以 `schemas/v2.3/goal-teams.schema.json` 为准，不得用 V1.8 根级 `harness.yaml` / `evidence.jsonl` / `pipeline-state.json` 替代。用户明确指定其他生成目录时仍用版本子目录隔离 SSOT。

## 3. Concept Document

除保留文件外，每个 Markdown 文档都应包含 YAML frontmatter：

```yaml
---
type: <概念类型，必填>
title: <显示标题>
description: <一句话摘要>
resource: <可选，底层资源或来源 URI>
tags: [<tag>, <tag>]
timestamp: <ISO 8601 datetime>
okf_version: "0.1"
goal_teams_version: <Vx.x>
project_version: <项目版本号>
owner_agent_type: <Owner agent type>
owner_member_id: <Owner member ID>
owner_agent_run_id: <Owner run ID>
validator_agent_type: <Validator agent type>
validator_member_id: <Validator member ID>
validator_agent_run_id: <Validator run ID>
source_ssot: <适用时填写 SSOT 文件>
---
```

必填字段：

- `type`：概念类型，例如 `Requirement Card`、`PRD`、`Page Specification Card`、`Harness Contract`、`Memory Ledger`。

推荐字段：

- `title`：人类可读标题。
- `description`：一句话摘要。
- `resource`：与文档绑定的真实资源或来源。
- `tags`：短标签数组。
- `timestamp`：最后一次重要修改时间。
- `okf_version`：当前使用 `"0.1"`。
- `goal_teams_version`：当前 Skill 版本。
- `project_version`：用户项目版本。
- `owner_agent_type` / `validator_agent_type`：可加载角色或 skill。
- `owner_member_id` / `validator_member_id`：项目内稳定成员身份。
- `owner_agent_run_id` / `validator_agent_run_id`：本次具体运行身份；用于独立性判断。

扩展字段允许存在，消费者不得因为未知字段拒绝读取。Goal Teams 常用扩展字段包括 `harness_ref`、`evidence_paths`、`component_library`、`data_model_ref`、`acceptance_refs`、`not_applicable_reason`。

## 4. 正文结构

正文使用标准 Markdown。优先使用标题、表格、列表和 fenced code block，避免把可检索信息写成长段散文。常用章节：

- `# Summary` / `# 摘要`
- `# Context` / `# 背景`
- `# Schema` / `# 数据结构`
- `# Examples` / `# 示例`
- `# Harness` / `# 验证契约`
- `# Evidence` / `# 证据`
- `# Citations` / `# 引用`

## 5. 链接和引用

- 目录内文档优先使用相对链接，例如 `[PRD](PRD.md)`。
- 跨目录引用可以使用 bundle-relative 路径，例如 `[TaskList](/versions/<artifact_version>/TaskList.md)`。
- 外部来源、附件、URL、Git 仓库和参考资产放入 `# Citations` 或 `# 参考资产`。
- 消费者应容忍暂时断开的链接；断链应进入待办或风险，不应导致整个 bundle 不可读。

## 6. index.md 和 log.md

- `index.md` 是目录索引，列出同目录文档和子目录，支持渐进式加载。
- bundle 根 `index.md` 可以声明 `okf_version: "0.1"`；其他索引默认不写 frontmatter。
- `log.md` 可按日期记录更新历史。Goal Teams 若使用 `memory.md` 记录用户配置，必须按用户要求从旧到新排列；`log.md` 可按 OKF 建议用日期分组。

## 7. Goal Teams 生成文档规则

- 需求卡片、需求规格卡、PRD、页面规格卡、测试计划、验收记录、评审记录、Doc Capsule 和 memory 都必须是 OKF Markdown 文档。
- `HTML-prototype.html` 不是 Markdown，但必须内嵌 OKF 元数据块，见 `prompts/packets/html-prototype-mock.md`。
- 所有交接物变化必须先写入版本目录 append-only ledger，并保持 `prompts/packets/handoff-artifacts.md` 的 SSOT 字段；`TaskList.md` 只由 reducer 生成，`tasklist.md` 仅作为 V2.2 migration 输入。
- 用户未指定目录时，所有输出默认进入 `GoalTeamsWork-<project_version>/`。
- 每次新建或更新输出目录时，必须创建或更新 `memory.md`，记录重要设置、组件库、输出目录、项目版本、关键上下文摘要和用户偏好。

## 8. Conformance / 符合性

Goal Teams OKF bundle 视为符合本地规范，当且仅当：

1. 非保留 Markdown 文档有可解析 YAML frontmatter。
2. frontmatter 包含非空 `type`。
3. 输出目录包含 `index.md` 和 `memory.md`，或记录不能创建的阻塞原因。
4. `memory.md` 按时间线从老到新记录，作者为 `GoalTeams`。
5. 页面规格卡和 HTML 原型在 UI 任务中记录组件库名称、版本、来源和每个元素的组件库归属。

# English Specification

This file is the local Goal Teams adaptation of Google Open Knowledge Format v0.1 Draft from the GoogleCloudPlatform Knowledge Catalog (`knowledge-catalog`) repository. Goal Teams generated Markdown documents are OKF concept documents by default: YAML frontmatter provides machine-readable metadata, and the Markdown body provides human- and agent-readable content.

## 1. Goals

- Make generated documents readable, diffable, reviewable, and portable.
- Make each document discoverable and routable through `type`, `title`, `description`, `tags`, and `timestamp`.
- Keep SPEC, tasklist, Harness, Evidence, Page Specification Card, HTML Prototype MOCK, and memory traceable through links and paths.
- OKF does not replace domain schemas. API contracts, data models, component props, and Harness schemas remain in their native forms as body sections or extension fields.

## 2. Bundle Directory

When the user does not provide an output directory, Goal Teams writes outputs to:

```text
GoalTeamsWork-<project_version>/
```

The recommended structure mirrors the Chinese section above: the root contains cross-version `index.md`, `memory.md`, and optional `log.md`; SSOT outputs live under `versions/<artifact_version>/` with `TaskList.md`, plan/progress/decision documents, `spec/`, `tests/`, and `artifacts/`.

## 3. Concept Documents

Every non-reserved Markdown file should include YAML frontmatter with a required non-empty `type` field. Recommended fields include `title`, `description`, `resource`, `tags`, `timestamp`, `okf_version`, `goal_teams_version`, `project_version`, `owner_agent_type`, `owner_member_id`, `owner_agent_run_id`, `validator_agent_type`, `validator_member_id`, and `validator_agent_run_id`. Producers may add extension fields; consumers should preserve and tolerate unknown keys.

## 4. Body

The body is standard Markdown. Prefer headings, tables, lists, and fenced code blocks. Common sections include Summary, Context, Schema, Examples, Harness, Evidence, and Citations.

## 5. Links and Citations

Use relative links inside the bundle and cite external sources under `# Citations` or a reference-asset section. Broken links are treated as incomplete knowledge or risk, not as a fatal parsing error.

## 6. Goal Teams Rules

- Requirement Card, Requirement Specification Card, PRD, Page Specification Card, Test Plan, Acceptance, review records, Doc Capsules, and memory are OKF Markdown documents.
- `HTML-prototype.html` embeds OKF metadata using the contract in `prompts/packets/html-prototype-mock.md`.
- The default output root is `GoalTeamsWork-<project_version>/` unless the user specifies another directory.
- SSOT outputs must live under `versions/<artifact_version>/`; SPEC, TaskList, Harness, Evidence, and Acceptance for different versions must not be mixed.
- `memory.md` is created or updated in the output directory and records important user settings, configuration, component library decisions, output directory, project version, and context summaries from old to new, authored by `GoalTeams`.

## Citations

[1] [GoogleCloudPlatform knowledge-catalog README](https://github.com/GoogleCloudPlatform/knowledge-catalog)
[2] [Open Knowledge Format v0.1 Draft SPEC](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
