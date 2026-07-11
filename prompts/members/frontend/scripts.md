# Frontend Member Scripts

优先脚本：

- `scripts/harness/pixel-diff.py`：截图像素对比。
- `scripts/harness/validate-harness.py`：UI Harness 结构。
- `scripts/review/compare-artifacts.py`：HTML、CSS、截图 manifest 或报告对比。
- `scripts/review/validate-dual-review.py`：双重复核记录检查。

规则：

- UI 任务没有 E2E Evidence 不能 accepted。
- 复刻任务没有 baseline、actual、diff 或指标不能 accepted。
- UI 页面、复刻、还原、截图对齐或前端交互页面缺少 `page-spec-card.md` 且没有 `not_applicable_reason` 时不能 accepted。
- 页面原型任务缺少组件库名称、版本、URL/Git 仓库记录，且没有待确认问题时不能 accepted。
- HTML Prototype MOCK 缺少 OKF 元数据、`application/okf+yaml`、组件库 HTML 注释或关键元素 `data-component-library` 属性时不能 accepted。
- 动态前端页面 Harness 必须覆盖真实路由/状态变化/DOM 几何断言/交互态截图。
- 静态 HTML Prototype Harness 必须覆盖静态结构、mock 数据、响应式截图、组件几何断言、组件库元数据断言和不适用原因。
- 使用视觉锁层、baseline overlay 或截图遮挡层时，缺少 unlocked real DOM screenshot 不能 accepted。
- 头像、图标、小按钮、弹窗局部区域、表单错误提示、表格操作列和菜单浮层必须有局部 crop 或几何断言。
