# UI 视觉防漏协议

适用范围：所有前端页面、HTML Prototype、浏览器工作流、UI 复刻、截图还原、Figma 对齐、视觉临摹、组件实现和交互样式验收任务。

本协议目标：防止“整页像素通过但真实 DOM 有问题”“视觉锁层遮住缺陷”“小组件缺陷被整页阈值吞掉”“弹窗/表单交互态未验收”等问题再次发生。

## 1. 核心原则

1. 整页 pixel diff 只能作为视觉证据之一，不能单独作为完成依据。
2. 任何用户可见组件都必须有组件级视觉契约。
3. 任何交互组件都必须覆盖至少一个交互态截图或几何断言。
4. 任何使用 baseline overlay、视觉锁层、截图遮挡层的页面，都必须同时验证 locked 与 unlocked real DOM。
5. 小区域、小图标、小头像、小按钮不能只靠整页 diff，必须有局部 crop 或几何断言。
6. 页面规格卡和 HTML Prototype MOCK 必须记录组件库名称、版本、来源和元素级组件库归属。
7. Reviewer 和 Completion Auditor 必须审查证据是否覆盖风险，而不只是证据是否存在。

## 2. 必须触发本协议的场景

只要任务满足以下任一条件，即必须启用本协议：

- 用户要求“100% 一致”“像素级一致”“复刻”“还原”“临摹”“按截图实现”。
- 使用 Figma、截图、线上页面、设计稿或参考页面作为视觉标准。
- 页面包含弹窗、表单、表格、菜单、头像、图标、分页、导航、卡片、工具栏等用户可见组件。
- 实现中使用了 `pixel-baseline.png`、baseline overlay、视觉锁层、截图遮挡层、首屏覆盖层。
- 验收需要截图、Playwright、Browser/Chrome 自动化、像素 diff 或 viewport 检查。

## 3. 页面规格卡要求

UI 任务必须生成或更新页面规格卡。页面规格卡至少包含：

- 页面结构。
- 组件库信息，包含组件库名称、版本、来源 URL 或 Git 仓库、确认状态。
- 每个用户可见元素的组件库归属；有数据模型的组件必须记录数据模型或 mock 引用。
- 组件级视觉契约。
- 交互状态矩阵。
- 视觉锁层策略。
- 响应式视口。
- 整页和局部像素对比。
- E2E Harness 契约。
- 验收标准。
- 双重复核规则。
- 不允许 `audit_state=passed` 或 `run_outcome=achieved` 的情况。
- 证据目录约定。
- 风险和缓解方式。

如果任务不是 UI 任务，必须写明 `not_applicable_reason`。

## 4. 视觉锁层规则

视觉锁层包括但不限于：

- `body::before` 或 `body::after` 覆盖整页截图。
- `position: fixed` 的 baseline overlay。
- 用静态截图遮住真实 DOM。
- 首屏展示图片，交互后再显示真实 DOM。
- 任何为了像素对齐而添加的非真实 UI 遮罩层。

### 4.1 允许条件

视觉锁层只允许作为辅助对齐手段，不能作为唯一验收依据。

使用视觉锁层时，必须同时提供：

- locked screenshot：视觉锁层启用时截图。
- unlocked real DOM screenshot：视觉锁层移除后真实 DOM 截图。
- locked component assertions：锁层状态下关键组件局部校验。
- unlocked component assertions：真实 DOM 状态下关键组件校验。
- 交互态截图：弹窗、菜单、错误态、切换态等。

### 4.2 禁止条件

以下情况不得输出 `audit_state=passed` 或 `run_outcome=achieved`：

- 只有 locked 截图，没有 unlocked real DOM 截图。
- 只有整页 baseline diff，没有组件级断言。
- 视觉锁层覆盖了真实 DOM，但没有说明风险和补测。
- Reviewer 已指出“锁层不证明真实 DOM”，但没有新增 harness。
- Completion Auditor 只检查证据存在，没有检查证据覆盖范围。

## 5. 组件级视觉契约

每个关键组件都必须定义 Visual Contract。格式建议：

| 组件 | 状态 | 必验视觉项 | 几何断言 | 截图证据 |
| --- | --- | --- | --- | --- |
| <组件名> | <默认/打开/错误/切换/禁用> | <颜色、尺寸、对齐、裁剪、间距> | <bbox、宽高、y 坐标差、display> | <截图路径> |

组件级视觉契约还必须包含 `component_library` 和 `library_component` 字段；例如 `Ant Design` 的 `Modal`、`Table`、`Avatar`。HTML 原型应通过 `application/okf+yaml`、HTML 注释或 `data-component-library` 让 Harness 能追踪这些字段。

### 5.1 常见组件必验项

| 组件 | 必验项 |
| --- | --- |
| 头像 | 宽高、圆形、裁剪、图形完整、不被遮挡 |
| 图标 | 尺寸、颜色、位置、可见性、hover/active 态 |
| 按钮 | 尺寸、文字不溢出、图标对齐、disabled/loading 态 |
| 弹窗 | 宽高、居中、header/body/footer、遮罩、关闭按钮、滚动区域 |
| 表单 | label 对齐、控件高度、占位符、必填星号、错误态、空错误态 |
| Radio/Checkbox | 横纵排列、选中态、label 对齐、可点击区域 |
| 表格 | 列宽、行高、表头、固定列、操作列、空态、分页联动 |
| 菜单 | 单实例、位置、层级、关闭行为、选中态 |
| 分页 | 位置、间距、当前页、pageSize、禁用态 |
| Toast/Message | 位置、层级、停留时间、成功/失败态 |

## 6. 交互状态矩阵

不能只测试“页面能打开”。交互组件必须覆盖状态矩阵。

| 类型 | 必测状态 |
| --- | --- |
| 弹窗 | 打开态、关闭态、提交 loading、错误态、切换态、滚动态、移动端态 |
| 表单 | 空态、输入态、校验错误态、清错态、disabled 态 |
| 菜单 | 打开态、关闭态、点击外部关闭、切换单实例 |
| 表格 | 默认态、空态、分页态、筛选态、操作后刷新态 |
| 搜索区 | 展开态、收起态、重置态、URL 回填态 |
| 确认框 | 打开态、取消态、确认态、loading 态 |

每个状态至少需要以下证据之一：

- Playwright/E2E 断言。
- 截图证据。
- DOM 几何断言。
- 局部像素对比。

## 7. 截图证据要求

### 7.1 必备截图

UI 页面任务默认至少需要：

- `default-locked.png`：如果存在视觉锁层。
- `default-unlocked.png`：真实 DOM 默认态。
- `viewport-desktop.png`。
- `viewport-tablet.png`。
- `viewport-mobile.png`。
- `dialog-open.png`：如果有弹窗。
- `dialog-error.png`：如果有表单校验。
- `component-<name>.png`：关键小组件局部截图。

### 7.2 截图命名

推荐路径：

```text
GoalTeamsWork-<project_version>/artifacts/e2e/screenshots/
  default-locked.png
  default-unlocked.png
  add-dialog-open.png
  add-dialog-error.png
  mobile-default.png
```

## 8. 像素对比规则

### 8.1 整页 pixel diff

整页 diff 必须记录：

```yaml
pixel_diff_checks:
  baseline_image: <path>
  actual_image: <path>
  diff_image: <path>
  viewport: <width>x<height>
  threshold: <changed_ratio threshold>
  changed_ratio: <number>
  mae: <number>
  conclusion: pass/fail
```

默认阈值：

| 场景 | changed_ratio |
| --- | --- |
| 精准复刻 | `<= 0.01` |
| 响应式近似还原 | `<= 0.03` |
| 内容动态但布局稳定 | `<= 0.05` |

阈值必须在 Plan、Harness 或页面规格卡中提前声明。不得在失败后为了通过而事后放宽。

### 8.2 局部 pixel diff

以下场景必须做局部 crop 或几何断言：

- 头像、图标、徽标、小按钮。
- 弹窗局部区域。
- 表单错误提示。
- 表格操作列。
- 菜单浮层。
- 任何整页 diff 容易吞掉的小面积视觉问题。

局部对比建议记录：

```yaml
local_pixel_checks:
  - name: avatar
    baseline_crop: <path>
    actual_crop: <path>
    threshold: <number>
    fallback_assertion: width/height/border-radius/visibility
```

## 9. E2E Harness 要求

UI E2E Harness 至少记录：

```yaml
e2e_checks:
  critical_user_paths:
    - <关键路径>
  viewports:
    - 1440x900
    - 768x1024
    - 390x844
  console_errors:
    expected: []
  visual_states:
    - default_locked
    - default_unlocked
    - dialog_open
    - dialog_error
  component_assertions:
    - <组件断言名>
  component_library_checks:
    - component_library_metadata_present
    - per_element_data_component_library
    - data_model_refs_present
  evidence_paths:
    - <summary.json>
    - <console-errors.json>
    - <screenshots>
    - <pixel metrics>
```

## 10. 推荐断言清单

### 10.1 头像

- 宽高符合规格，例如 `28px x 28px`。
- `border-radius: 50%`。
- `overflow: hidden`。
- 内部图形或图片可见。
- 不被 overlay、header、容器裁剪。
- locked 与 unlocked 状态均通过。

### 10.2 弹窗

- 宽高符合规格。
- 在 viewport 内居中或符合设计位置。
- header/body/footer 高度稳定。
- 关闭按钮位置正确。
- body 滚动区域不挤压 footer。
- 移动端不溢出，不遮挡主操作。

### 10.3 表单

- label 列宽稳定。
- 控件高度稳定。
- radio/checkbox label 同行对齐。
- 空 `.error-text` 不占位，除非设计明确要求预留。
- 错误态显示后行高可预测。
- 切换字段时隐藏字段不占位。

### 10.4 表格

- 表头和内容列对齐。
- 行高稳定。
- 操作列不换行、不被遮挡。
- 空态位置正确。
- 分页操作后列表和页码一致。

## 11. Reviewer 门禁

Reviewer 必须检查：

- 是否存在视觉锁层或 overlay。
- 是否有 locked 与 unlocked 两套证据。
- 是否只依赖整页 pixel diff。
- 是否有组件级视觉契约。
- 是否有关键交互态截图。
- 是否有小组件局部 crop 或几何断言。
- 是否有 console error 记录。
- 是否覆盖主要 viewport。
- 是否有范围外入口或非目标功能。
- 页面规格卡头部、元素级记录和 HTML OKF 元数据是否包含组件库名称、版本和来源。
- 有数据模型的组件是否记录数据模型或 mock 引用。

以下情况必须标为 P1 或更高：

- 使用视觉锁层但没有 unlocked real DOM 证据。
- 关键组件缺少 visual contract。
- 弹窗、表单、菜单只有功能测试，没有视觉状态测试。
- 整页 pixel diff 通过，但局部组件明显缺证据。
- 用户要求 100% 一致，但没有脚本 + LLM 双重复核。
- HTML Prototype MOCK 缺少组件库元数据或关键元素缺少 `data-component-library`。

## 12. Completion Auditor 门禁

Completion Auditor 不只检查“证据是否存在”，还必须检查“证据是否覆盖风险”。

必须回答：

- Done Criteria 是否全部被证据覆盖？
- 页面规格卡中的组件级视觉契约是否全部验证？
- 交互状态矩阵是否全部有证据或明确延期原因？
- 视觉锁层风险是否有补偿性 harness？
- 小组件是否避免被整页 diff 吞掉？
- Reviewer 提出的 P0/P1/P2 是否已处理或明确接受？
- 是否仍有用户可见视觉风险未补测？
- 组件库信息是否覆盖 `memory.md`、页面规格卡头部、元素级记录和 HTML OKF 元数据？

如果答案为否，必须按原因输出单一 `audit_state=failed` 或 `audit_state=blocked`，并由 Lead 选择 `loop_decision=continue|replan|stop`；不得输出 `run_outcome=achieved`。

## 13. 不允许 `audit_state=passed` / `run_outcome=achieved` 的情况

出现以下任一情况，不允许完成：

- 缺少页面规格卡，且没有 `not_applicable_reason`。
- 页面原型任务未澄清组件库，且没有待确认问题。
- 页面规格卡或 HTML 原型缺少组件库名称、版本、来源或元素级归属。
- 只有功能 E2E，没有视觉状态证据。
- 只有整页 pixel diff，没有组件级断言。
- 只有 locked overlay 截图，没有 unlocked DOM 截图。
- 弹窗没有打开态截图。
- 表单没有错误态和空错误态检查。
- 小组件缺少局部检查。
- console error 未检查。
- 主要 viewport 未检查。
- Reviewer 或 Auditor 发现视觉风险但未补测。

## 14. 证据目录建议

```text
GoalTeamsWork-<project_version>/
  spec/
    requirement-card.md
    page-spec-card.md
    test-plan.md
    acceptance.md
  artifacts/
    e2e/
      summary.json
      console-errors.json
      screenshots/
        default-locked.png
        default-unlocked.png
        dialog-open.png
        dialog-error.png
    pixel/
      metrics.json
      diff.png
      local/
    review/
      dual-review-record.json
      final-review.md
      completion-audit.md
```

## 15. 典型缺陷映射

| 缺陷 | 常见原因 | 必须补的门禁 |
| --- | --- | --- |
| 头像不完整 | overlay 压住真实 DOM；小区域未局部检查 | locked/unlocked 双断言；头像几何断言 |
| 弹窗错位 | 原生元素默认样式；尺寸未锁定；状态未截图 | 弹窗打开态截图；宽高断言；表单行断言 |
| radio 竖排或错位 | label/control 结构不统一 | y 坐标断言；radio row flex 断言 |
| 空错误提示撑高布局 | 空 `.error-text` 默认显示 | 空态 display/height 断言 |
| 整页 diff 通过但组件错 | 组件面积太小，被阈值吞掉 | 局部 crop；bbox 断言 |
| 移动端重叠 | 只测 desktop | tablet/mobile viewport 截图 |

## 16. 建议写入提示词

每次 UI 任务可以使用：

```text
必须启用 UI 视觉防漏协议：
1. 不允许只用整页 pixel diff 作为视觉通过依据。
2. 如果使用 baseline overlay 或视觉锁层，必须提供 locked screenshot 和 unlocked real DOM screenshot。
3. 必须为关键组件建立并执行组件级视觉断言。
4. 弹窗必须覆盖打开态、错误态、切换态、关闭态和移动端态。
5. 小组件必须使用局部 crop 或几何断言。
6. Reviewer 发现视觉锁层风险、组件断言缺失、交互态截图缺失时，必须 LOOP，不得输出 `audit_state=passed` 或 `run_outcome=achieved`。
7. Completion Auditor 必须审查证据是否覆盖风险，而不只是证据是否存在。
```
