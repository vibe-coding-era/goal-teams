# UI E2E And Pixel Protocol V1.94

本协议只在路由结果为 `ui_mode=replica`（复刻、临摹、还原、对照参考图/页面或其他 reference-driven UI）时作为 required 规则加载。原创 UI 的 browser/DOM/截图/几何检查由 `references/rules-ui.md` 定义，不加载本文件，也不因缺少 reference baseline blocked。

## UI E2E 必填项

界面级任务的 Harness 至少记录：

```text
e2e_checks:
- critical_user_paths:
- viewports:
- console_errors:
- visible_final_state:
- accessibility_smoke:
- okf_metadata_checks:
- component_library_checks:
- evidence_paths:
```

推荐 viewport：

| 类型 | 尺寸 |
| --- | --- |
| desktop | 1440x900 |
| tablet | 768x1024 |
| mobile | 390x844 |

如果项目已有自己的 viewport 标准，优先使用项目标准并在 Harness 中记录。

## 复刻像素级对比

复刻、临摹、还原、对照参考图或参考页面的任务必须记录：

```text
pixel_diff_checks:
- baseline_image:
- actual_image:
- diff_image:
- viewport:
- threshold:
- changed_ratio:
- mae:
- conclusion:
```

默认阈值：

| 场景 | changed_ratio |
| --- | --- |
| 精准复刻 | `<= 0.01` |
| 响应式近似还原 | `<= 0.03` |
| 内容动态但布局稳定 | `<= 0.05` |

阈值必须在 Plan 或 Harness 中提前写明。任务完成后不能为了通过而事后放宽阈值。

整页 diff 不能覆盖小组件缺陷时，必须增加局部 crop 或几何断言。头像、图标、徽标、小按钮、弹窗局部区域、表单错误提示、表格操作列和菜单浮层不能只依赖整页 diff。

如果默认主截图来自 baseline overlay、视觉锁层或截图遮挡层，必须额外采集 unlocked real DOM screenshot，并对关键组件执行真实 DOM 几何断言。锁层截图只能作为对照辅助，不能作为唯一通过证据。

弹窗和表单类组件必须至少有打开态和错误态截图；涉及类型切换、关闭、移动端布局时，还必须补充对应状态截图或几何断言。

pixel threshold 不能在失败后为了通过而放宽。确需调整阈值时，必须回到 Plan、Harness 或页面规格卡重新说明原因、风险和独立校验者。

## 局部视觉与组件断言

当整页 pixel diff 可能吞掉小区域问题时，使用以下补偿性 Harness：

```text
local_pixel_checks:
- name:
- baseline_crop:
- actual_crop:
- threshold:
- fallback_assertion:

component_assertions:
- name:
- selector:
- expected_geometry:
- expected_visibility:
- evidence_path:
```

页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面任务还必须检查：

```text
component_library_checks:
- component_library_name:
- component_library_version_or_range:
- source_url_or_git:
- html_okf_metadata_present:
- per_element_data_component_library:
- data_model_refs_present:
```

缺少组件库名称、版本、URL/Git 仓库或 HTML OKF 元数据时，不能用截图通过替代。

典型必测组件：

| 组件 | 必测证据 |
| --- | --- |
| 头像 | locked/unlocked 截图、宽高、圆形、裁剪、无遮挡 |
| 弹窗 | 打开态、错误态、切换态、关闭态、移动端态 |
| 表单 | label/control 对齐、空错误态不占位、错误态行高稳定 |
| 菜单 | 打开/关闭、单实例、位置和层级 |
| 表格/分页 | 行高、列宽、操作列、空态、分页联动 |

## 工具建议

- 使用 Playwright 或 Browser/Chrome 工具采集截图和控制台错误。
- 使用 `scripts/harness/pixel-diff.py` 计算 diff 指标；兼容入口 `scripts/pixel-diff.py` 仍可用。没有 Pillow 时可使用 PPM 输入。
- reference-driven/复刻 UI 必须使用 `--ui-mode replica`，该模式自动要求 `--baseline-environment`、`--actual-environment` 与 `--baseline-approval`，缺一即非零失败。`--ui-mode original` 只保留脚本兼容性，不代表原创 UI 必须运行 pixel comparison。
- environment JSON 必须覆盖 browser/version、viewport、DPR、fonts 和 OS；baseline approval JSON 必须包含独立 `reviewer_run_id`、`approved_at`、`reason` 与 `baseline_sha256`。
- diff 图建议放入 `GoalTeamsWork-<project_version>/artifacts/` 或项目测试报告目录。
- HTML Prototype MOCK 建议检查 `application/okf+yaml`、OKF 注释和关键元素 `data-component-library` 属性。

## 不适用条件

只有以下情况可以创建 `required=false`、`acceptance_blocking=false` 的 `not_required` Check 并写 `not_applicable_reason`：

- 任务不是 replica/reference-driven UI。
- 静态文档示例没有运行应用，且已标记 `sample_only`。
- 用户明确把原 UI/复刻目标改成非 UI 或 `sample_only` 文档范围；范围变更必须有独立 reviewer/用户决策记录。

Replica/reference-driven UI 缺参考、浏览器、截图或环境指纹时必须 `blocked`，不得用 waiver/not_required 获得 accepted。原创 UI 缺外部参考不 blocked，但仍必须满足 `rules-ui.md` 派生的 browser/DOM/可见状态证据。用户只批准“记录风险”并不等于完成；只有显式改变目标范围并重新路由后才按新 Check 计算。不适用原因必须写入 ledger event，并由 TaskList、test plan 或 acceptance 引用。
