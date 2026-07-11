---
type: HTML Prototype Mock Template
title: HTML 原型 MOCK OKF 模板
description: HTML 原型生成时的 OKF 元数据和组件库记录模板。
tags: [goal-teams, okf, html-prototype, component-library]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# HTML 原型 MOCK 模板

适用于用户要求生成页面原型、HTML Prototype、静态页面 MOCK 或动态前端页面 MOCK 的任务。

## 生成前澄清

- 如果用户没有明确组件库名称、版本、来源 URL 或 Git 仓库，必须先询问组件库，例如 `Ant Design`、`Material UI`、`Element Plus`、项目自研组件库 URL/Git 仓库。
- 如果用户提示词已经包含组件库信息，直接写入输出目录的 `memory.md`、`spec/page-spec-card.md` 和 HTML 原型 OKF 元数据。
- 组件库信息至少包含 `name`、`version_or_range`、`source`、`lock_status`；无法确认版本时写 `unknown`，并记录待确认问题。

## HTML OKF 元数据块

HTML 文件不是 Markdown，但必须在 `<head>` 内嵌 OKF 元数据。推荐同时使用 HTML 注释和 `application/okf+yaml` 脚本块，方便人类和工具读取。

```html
<!doctype html>
<html
  lang="zh-CN"
  data-okf-version="0.1"
  data-okf-type="HTML Prototype Mock"
  data-component-library-name="<组件库名>"
  data-component-library-version="<组件库版本>"
>
<head>
  <meta charset="utf-8" />
  <title><页面名> - HTML Prototype</title>
  <!--
  okf_frontmatter:
    type: HTML Prototype Mock
    title: <页面名> HTML Prototype
    description: <一句话摘要>
    okf_version: "0.1"
    goal_teams_version: <Vx.x>
    project_version: <项目版本号>
    output_dir: <GoalTeamsWork-project_version 或用户指定目录>
    source_spec: spec/page-spec-card.md
    component_library:
      name: <组件库名>
      version_or_range: <组件库版本>
      source: <URL/Git 仓库/本地路径>
      lock_status: confirmed | assumed | unknown
    owner_agent_type: goal_frontend
    owner_member_id: <稳定成员 ID>
    owner_agent_run_id: <本次运行 ID>
    validator_agent_type: goal_qa 或 goal_reviewer
    validator_member_id: <独立检查成员 ID>
    validator_agent_run_id: <独立检查运行 ID>
  end_okf_frontmatter
  -->
  <script type="application/okf+yaml" id="goalteams-okf-metadata">
type: HTML Prototype Mock
title: <页面名> HTML Prototype
description: <一句话摘要>
okf_version: "0.1"
goal_teams_version: <Vx.x>
project_version: <项目版本号>
source_spec: spec/page-spec-card.md
component_library:
  name: <组件库名>
  version_or_range: <组件库版本>
  source: <URL/Git 仓库/本地路径>
  lock_status: confirmed | assumed | unknown
elements:
  - id: <element_id>
    library: <组件库名>
    library_component: <Button/Table/Form/Modal/...>
    data_model_ref: <可选，字段模型或 mock 数据>
    visual_contract_ref: spec/page-spec-card.md#组件级视觉契约
  </script>
</head>
```

## 元素级记录

每个用户可见元素必须能在 HTML 中追踪到组件库来源，推荐写入 `data-*` 属性：

```html
<button
  data-okf-element-id="primary-search-button"
  data-component-library="<组件库名>"
  data-library-component="Button"
  data-library-version="<组件库版本>"
  data-data-model-ref="filters.keyword"
>
  查询
</button>
```

规则：

- 按钮、表单、菜单、头像、表格、分页、弹窗、toast、drawer、tabs 等用户可见组件都要记录组件库名。
- 有数据模型的组件必须记录 `data-data-model-ref` 或在 OKF 元数据块的 `elements` 中记录数据模型。
- HTML 原型 Harness 必须验证 OKF 元数据存在、组件库字段不为空、关键元素带有 `data-component-library`。
- 若使用第三方 CSS/JS CDN，必须在 `# Citations` 或 HTML 注释中记录版本和来源。
