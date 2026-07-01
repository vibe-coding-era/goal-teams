---
type: Page Specification Card Template
title: 页面规格卡 OKF 模板
description: PRD 完成后、HTML 原型 MOCK 或前端实现前使用的页面规格卡模板，包含组件库、视觉契约、交互矩阵、Harness 和 Evidence。
tags: [goal-teams, okf, page-spec-card, visual-contract, harness]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
source_ssot: references/google-okf-bilingual-spec.md
---

# 页面规格卡 OKF 模板

页面规格卡用于 PRD 完成后、HTML Prototype MOCK 或前端实现前，把页面结构、组件库、组件视觉契约、交互状态矩阵、Harness 和 Evidence 固化为可执行输入。需求卡片不得替代页面规格卡。

生成实际 `spec/page-spec-card.md` 时，必须使用 OKF frontmatter，并在头部记录整个组件库名称、版本、来源和确认状态。每一个页面元素都必须记录组件库名；如果组件本身有数据模型，也必须记录数据模型或 mock 数据引用。

```markdown
---
type: Page Specification Card
title: <页面名> <项目版本号>
description: <一句话说明页面目标>
resource: <页面 URL / 本地入口 / 参考页面 / Figma URL>
tags: [goal-teams, page-spec, ui, <业务域>]
timestamp: <ISO 8601 datetime>
okf_version: "0.1"
goal_teams_version: <Vx.x>
project_version: <项目版本号>
output_dir: <GoalTeamsWork-project_version 或用户指定目录>
owner_subagent: goal_product 或 goal_frontend
validator_subagent: goal_reviewer 或 goal_qa
source_prd: spec/PRD.md
source_requirement_card: spec/requirement-card.md
component_library:
  name: <Ant Design / Material UI / Element Plus / 自研组件库名>
  version_or_range: <版本号、commit、tag 或 unknown>
  source: <官网 URL / Git 仓库 / 本地路径 / 用户指定>
  lock_status: confirmed | assumed | unknown
  recorded_in_memory: memory.md
visual_contract_protocol: references/ui-visual-contract-protocol.md
---

# 页面规格卡：<页面名> <项目版本号>

## 1. 基本信息

| 项 | 内容 |
| --- | --- |
| 页面名称 | <页面名> |
| 项目版本 | <project_version> |
| 输出目录 | <GoalTeamsWork-project_version 或用户指定目录> |
| 业务域 | <业务模块> |
| 入口路径 | <URL 或本地入口> |
| 运行方式 | <静态页面 / 前端应用 / 已有项目路由> |
| 技术边界 | <只做前端 / 不做后端 / 不接真实 API> |
| 参考来源 | <Figma / 截图 / 线上页面 / PRD / 原型> |
| 验收优先级 | <像素级复刻 / 高保真还原 / 功能优先> |

## 2. 组件库信息

| 字段 | 值 |
| --- | --- |
| 组件库名称 | <component_library.name> |
| 组件库版本 | <component_library.version_or_range> |
| 组件库来源 | <component_library.source> |
| 确认状态 | confirmed / assumed / unknown |
| 记录位置 | `memory.md` |
| 待确认问题 | <若版本或来源未知，写清问题> |

若用户要求生成页面原型但未提供组件库、URL 或 Git 仓库，必须先澄清，不能直接生成 HTML MOCK。若用户已提供，必须同步写入 `memory.md`、本节和 HTML 原型 OKF 元数据。

## 3. 核心目标

<一句话说明本页面真正要完成什么。>

## 4. 用户故事

| ID | 用户角色 | 用户故事 | 价值 |
| --- | --- | --- | --- |
| US-001 | <角色> | 作为 <角色>，我想要 <能力>，以便 <价值> | <价值说明> |

## 5. 范围边界

### 范围内

- <页面布局>
- <核心交互>
- <mock 数据>
- <E2E 测试>
- <截图和像素证据>

### 范围外

- <后端服务>
- <数据库>
- <真实 API>
- <生产发布>
- <权限/支付/认证等非本轮内容>

### 禁止项

- 不得新增后端目录、数据库脚本或真实接口调用，除非用户明确授权。
- 不得加入规格卡未要求的入口，例如导入、导出、编辑、批量操作等。
- 不得只用静态截图遮挡层作为最终视觉通过依据。

## 6. 参考资产

| 类型 | 路径/链接 | 用途 | 是否必需 | 引用方式 |
| --- | --- | --- | --- | --- |
| Figma 截图 | <path/url> | baseline | 是 | `# Citations` |
| 页面规格 | <path/url> | 功能和验收 | 是 | OKF 链接 |
| 组件库文档 | <path/url/git> | 组件行为和样式 | 是 | `component_library.source` |
| 历史实现 | <path> | 对照 | 否 | OKF 链接 |

## 7. 页面结构

| 区域 | 必须包含 | 禁止出现 | 视觉要求 | component_library |
| --- | --- | --- | --- | --- |
| 顶部栏 | <logo / 租户 / 用户头像> | <禁止项> | <高度、间距、颜色> | <组件库名> |
| 侧边栏 | <菜单> | <禁止项> | <宽度、选中态> | <组件库名> |
| 搜索区 | <字段> | <禁止项> | <展开/收起高度> | <组件库名> |
| 工具栏 | <按钮> | <禁止项> | <按钮顺序、间距> | <组件库名> |
| 表格 | <列> | <禁止项> | <行高、固定列、空态> | <组件库名> |
| 分页 | <分页器> | <禁止项> | <位置、尺寸> | <组件库名> |
| 弹窗 | <新增/详情/确认> | <禁止项> | <宽高、header/body/footer> | <组件库名> |

## 8. 元素和数据模型

| element_id | 元素 | component_library | library_component | library_version | 数据模型 / mock 引用 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `top-avatar` | 顶部头像 | <组件库名> | Avatar | <版本> | `currentUser.avatarUrl` | 无数据时写 mock |
| `search-keyword` | 关键词输入 | <组件库名> | Input | <版本> | `filters.keyword` | 需记录 placeholder |
| `result-table` | 结果表格 | <组件库名> | Table | <版本> | `counterpartyList[]` | 记录列模型 |
| `add-dialog` | 新增弹窗 | <组件库名> | Modal/Form | <版本> | `counterpartyForm` | 记录校验模型 |

有数据模型的组件必须记录字段、类型、默认值、状态来源和 mock 数据路径。

```yaml
data_models:
  counterpartyForm:
    type: object
    fields:
      name:
        type: string
        required: true
        default: ""
      entityType:
        type: enum
        values: [enterprise, personal]
        default: enterprise
```

## 9. 组件级视觉契约

UI 复刻任务必须填写本节。没有组件级视觉契约，不允许标记视觉完成。

| 组件 | component_library | library_component | 状态 | 必验视觉项 | 几何断言 | 截图证据 |
| --- | --- | --- | --- | --- | --- | --- |
| 顶部头像 | <组件库名> | Avatar | 默认态 | 完整圆形、图形不缺失、不被遮挡 | `28x28`、`border-radius:50%`、`overflow:hidden` | `avatar-default.png` |
| 顶部头像 | <组件库名> | Avatar | 解锁/交互后 | 真实 DOM 与默认态一致 | 同上 | `avatar-unlocked.png` |
| 添加弹窗 | <组件库名> | Modal | 打开态 | 宽高、居中、header/body/footer 对齐 | `<宽>x<高>` | `add-dialog-open.png` |
| 表单类型行 | <组件库名> | Radio.Group/Form.Item | 企业/个人 | label 和 radio 水平对齐 | radio y 差值 `<=1px` | `type-row.png` |
| 错误提示 | <组件库名> | Form.Item help | 空态 | 空错误不占位、不撑高 | `display:none` 或高度为 0 | `form-empty-error.png` |
| 错误提示 | <组件库名> | Form.Item help | 错误态 | 文案、颜色、行高符合设计 | 高度稳定 | `form-error.png` |
| 表格 | <组件库名> | Table | 默认态 | 列宽、行高、操作区稳定 | 行高、列宽断言 | `table-default.png` |
| 分页 | <组件库名> | Pagination | 默认态 | 位置、间距、选中态 | bbox 断言 | `pagination.png` |

## 10. 交互状态矩阵

| 功能 | 状态 | 用户动作 | 期望结果 | 必测方式 | component_library |
| --- | --- | --- | --- | --- | --- |
| 查询 | 默认 | 输入筛选并点击查询 | URL/列表/分页同步 | E2E | <组件库名> |
| 搜索区 | 展开/收起 | 点击收起按钮 | 表单值不丢失 | E2E | <组件库名> |
| 新增弹窗 | 打开态 | 点击新增 | 弹窗样式正确 | 截图 + 几何断言 | <组件库名> |
| 新增弹窗 | 校验错误态 | 空提交 | 错误提示正确且不破坏布局 | E2E + 截图 | <组件库名> |
| 新增弹窗 | 类型切换 | 企业/个人切换 | 字段切换、布局稳定 | E2E | <组件库名> |
| 新增弹窗 | 关闭态 | 点击关闭/取消 | 弹窗关闭且状态符合要求 | E2E | <组件库名> |
| 新增弹窗 | 移动端态 | 移动端打开弹窗 | 不溢出、不遮挡、可关闭 | E2E + 截图 | <组件库名> |
| 详情弹窗 | 打开态 | 点击详情 | 只读展示 | E2E + 截图 | <组件库名> |
| 确认弹窗 | 删除/黑名单 | 点击操作 | 二次确认正确 | E2E | <组件库名> |

## 11. 视觉锁层策略

| 项 | 规则 |
| --- | --- |
| 是否允许 baseline overlay | <是/否> |
| overlay 用途 | 只能作为对照辅助，不能作为唯一验收依据 |
| locked 证据 | 必须提供默认锁定态截图 |
| unlocked 证据 | 必须提供真实 DOM 解锁态截图 |
| 禁止完成条件 | 只有 overlay 截图通过，不允许 complete |
| 必备断言 | locked + unlocked 均需检查关键组件 |

若使用视觉锁层，必须满足：

- `locked screenshot` 通过。
- `unlocked real DOM screenshot` 通过。
- 关键组件几何断言通过。
- 关键交互态截图通过。
- Reviewer 不得仅凭整页像素 diff 放行。

## 12. 响应式视口

| 视口 | 尺寸 | 必验项 |
| --- | --- | --- |
| Desktop | `1440x900` 或项目标准 | 主视觉、表格、弹窗 |
| Desktop Full | <项目 baseline 尺寸> | 像素 diff |
| Tablet | `768x1024` | 不白屏、不重叠、可操作 |
| Mobile | `390x844` | 不白屏、不重叠、关键操作可达 |

## 13. 整页和局部像素对比

### 整页对比

| 项 | 值 |
| --- | --- |
| baseline | <baseline path> |
| actual | <actual path> |
| diff | <diff path> |
| viewport | <width>x<height> |
| threshold | 精准复刻默认 `changed_ratio <= 0.01` |
| 结论 | pass/fail |

### 局部对比

| 区域 | baseline | actual | threshold | component_library | 备注 |
| --- | --- | --- | --- | --- | --- |
| 顶部头像 | <path> | <path> | 几何硬断言优先 | <组件库名> | 小区域不只看整页 diff |
| 添加弹窗 | <path> | <path> | `<=0.03` 或项目标准 | <组件库名> | 打开态必须测 |
| 表单错误态 | <path> | <path> | `<=0.03` | <组件库名> | 错误态必须测 |

## 14. E2E Harness 契约

```yaml
e2e_checks:
  critical_user_paths:
    - 默认渲染
    - 查询/重置/URL 同步
    - 搜索区展开收起
    - 新增企业/个人
    - 校验错误态
    - 详情弹窗
    - 删除/黑名单确认
    - 租户切换
  viewports:
    - 1440x900
    - 768x1024
    - 390x844
  console_errors:
    expected: []
  visual_states:
    - default_locked
    - default_unlocked
    - add_dialog_open
    - add_dialog_error
    - add_dialog_person
    - add_dialog_closed
    - add_dialog_mobile
  component_assertions:
    - avatar_complete
    - dialog_geometry
    - form_type_row_alignment
    - empty_error_not_occupying_space
    - radio_horizontal_alignment
    - component_library_metadata_present
  component_library_contract:
    required: true
    name: <组件库名>
    version_or_range: <组件库版本>
    per_element_attribute: data-component-library
  evidence_paths:
    - <artifacts/e2e/summary.json>
    - <artifacts/pixel/metrics.json>
    - <artifacts/screenshots/*.png>
```

## 15. 验收标准

| ID | 对应功能 | Given | When | Then | 证据 |
| --- | --- | --- | --- | --- | --- |
| AC-001 | 页面默认渲染 | 打开页面 | 首屏加载完成 | 关键区域可见且无 console error | E2E summary |
| AC-002 | 头像 | 默认和解锁态 | 检查头像 | 头像完整圆形、不缺失、不遮挡 | 几何断言 + 截图 |
| AC-003 | 添加弹窗 | 点击新增 | 弹窗打开 | 尺寸、布局、radio、错误态符合契约 | E2E + 截图 |
| AC-004 | 像素对比 | 采集截图 | 执行 diff | 整页和局部阈值通过 | metrics.json |
| AC-005 | 组件库记录 | 生成规格卡和 HTML MOCK | 检查 OKF 元数据和元素属性 | 头部和每个元素都记录组件库；有数据模型的元素记录模型 | Harness 元数据检查 |

## 16. 双重复核

| 角色 | 必做 | 不通过条件 |
| --- | --- | --- |
| 脚本复核 | E2E、console、viewport、pixel diff、组件断言、组件库元数据断言 | 任一硬断言失败 |
| LLM Reviewer | 语义一致性、范围控制、视觉风险、证据完整性 | 缺少真实 DOM 证据或组件库记录 |
| Completion Auditor | 审查 Done Criteria 与证据覆盖 | 有风险未补测仍 complete |

## 17. 不允许 complete 的情况

- 只有整页像素 diff，没有组件级断言。
- 只有 locked overlay 截图，没有 unlocked DOM 截图。
- 页面规格卡未记录组件库名称、版本或来源，且没有待确认问题。
- 元素级记录缺少 `component_library`。
- 有数据模型的组件未记录数据模型或 mock 引用。
- 弹窗只测能打开，没有测打开态布局。
- 表单只测提交成功，没有测空错误态和错误态布局。
- Reviewer 发现 P1 视觉风险但没有补偿性 Harness。
- Completion Auditor 只检查证据存在，没有检查证据覆盖风险。

## 18. 证据目录约定

```text
GoalTeamsWork-<project_version>/
  index.md
  memory.md
  spec/
    requirement-card.md
    page-spec-card.md
    HTML-prototype.html
    test-plan.md
    acceptance.md
  artifacts/
    e2e/
      summary.json
      console-errors.json
      screenshots/
    pixel/
      metrics.json
      diff.png
    review/
      dual-review-record.json
      final-review.md
      completion-audit.md
```

## 19. 风险和缓解

| 风险 | 影响 | 缓解方式 | 是否阻塞 |
| --- | --- | --- | --- |
| 视觉锁层遮住真实 DOM | 真实 UI 缺陷漏检 | locked/unlocked 双证据 | 是 |
| 小组件被整页 diff 吞掉 | 头像、图标缺陷漏检 | 局部 crop 或几何断言 | 是 |
| 原生表单元素默认样式干扰 | 弹窗错位 | 使用统一 form-item 结构或重置样式 | 是 |
| 空错误提示撑高布局 | 表单行高异常 | 空态隐藏，错误态显示 | 是 |
| 组件库版本不明 | 样式和交互不可复现 | 先澄清或记录 URL/Git 仓库与锁定状态 | 是 |

## 20. 待确认问题

1. <组件库名称、版本、来源 URL 或 Git 仓库是什么？>
2. <是否允许视觉锁层？>
3. <baseline 以哪个截图为准？>
4. <弹窗和关键组件的目标尺寸是多少？>
5. <哪些范围外入口必须禁止？>

## Citations

[1] [Google OKF SPEC](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
```
