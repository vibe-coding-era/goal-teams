# UI E2E And Pixel Protocol V1.94

本协议适用于所有页面、组件、HTML Prototype、浏览器工作流、视觉还原和复刻任务。

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
- diff 图建议放入 `GoalTeamsWork-<project_version>/artifacts/` 或项目测试报告目录。
- HTML Prototype MOCK 建议检查 `application/okf+yaml`、OKF 注释和关键元素 `data-component-library` 属性。

## 不适用条件

只有以下情况可以写 `not_applicable_reason`：

- 任务不是界面级任务。
- 静态文档示例没有运行应用，且已标记 `sample_only`。
- 复刻任务没有用户提供或可访问的参考图/参考页面，此时应标记阻塞或请求参考。
- 环境缺少浏览器或截图能力，且用户明确批准本轮只记录风险。

不适用原因必须写入 tasklist、test plan 或 acceptance。
