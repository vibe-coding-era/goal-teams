---
type: Goal Teams Rules
title: UI 与桌面规则
---

# UI 与桌面规则

何时读取：改变用户可见界面、交互或桌面应用（`--domain ui|desktop`）。

## 1. 规格先行

- **GT-UI-TRIGGER**：以实际的界面或交互变化为准，仓库里有前端文件不算。
- **GT-UI-SIZE**：复刻、视觉锁定、多状态页面是行为变更，需要真实 E2E；单个组件的文案或样式修正用 `--impact presentation_only`，截图核对受影响状态即可（`gt run <T> --kind e2e --manual --evidence <截图>`）。
- **GT-UI-SPEC**：新页面、跨页面状态或重要交互变化，先写页面规格卡（`templates/page-spec-card.md`），再做原型（`templates/html-prototype.md`）或实现。
- **GT-UI-LIBRARY**：规格卡写明组件库名称、版本、来源；用户没提供时先问清，再 `gt memory add "组件库：<名称>@<版本>（<来源>）"`。
- **GT-UI-STATES**：每个页面和关键组件覆盖状态矩阵：正常、加载、空、错误、禁用、无权限、浮层；没有的状态写「不适用：原因」。
- **GT-UI-AC**：每条 AC 对应可观察断言（DOM、URL、文本、请求或存储）。
- **GT-UI-COMPONENTS**：弹窗测打开、校验错误、切换、关闭、移动端；表单测空、输入、错误、清错、禁用；小元素用几何断言（宽高、可见、未被遮挡）。

## 2. E2E

- **GT-UI-E2E**：用真实交互加回读验证行为：点击或输入后，读取 DOM、URL、可见状态和业务数据。用 Playwright，选择器优先 role、label、`data-testid`。
- **GT-UI-E2E-GATE**：UI 行为变更只有在当前源码上有通过的 E2E 记录才能达成；人工走查用 `--manual --evidence <截图>`，写清步骤和看到的结果。
- **GT-UI-E2E-RUNNER**：`goal_e2e_test_designer` 写用例，`goal_e2e_test_runner`（非实现者）执行并记录：`gt run <T> --kind e2e --as goal_e2e_test_runner -- npx playwright test <用例>`。
- **GT-UI-E2E-HONEST**：保留首次失败；重试后才通过的记为 flaky，并开修复任务。自动化跑不起来时 `gt task block <T> --reason "<原因>"`。
- **GT-UI-VIEWPORT**：覆盖项目标准视口；没有标准时用 1440x900、768x1024、390x844，并查 console 错误。
- **GT-UI-REVIEW**：评审核对证据是否覆盖状态矩阵和已知风险，不只看证据有无；有缺口时 `gt review <T> --by <评审成员> --verdict fail --note "<缺口>"`。

## 3. 像素对比（仅复刻与视觉锁定）

- **GT-UI-PIXEL-SCOPE**：只在复刻、还原、按截图或设计稿实现、用户要求视觉锁定时做像素对比。原创 UI 用 DOM 断言和截图核对，缺参考图不构成阻塞。
- **GT-UI-PIXEL-BASELINE**：基线截图由非实现者确认，并记录环境指纹：OS、浏览器及版本、视口、缩放（DPR）、字体。只比较指纹相同的截图；缺基线或指纹时任务保持 blocked。
- **GT-UI-PIXEL-CROP**：整页对比之外，对关键组件和文案区域（头像、图标、按钮文字、弹窗局部、表单错误提示）逐个裁剪对比或几何断言；1440x900 整页上，一处文案改动常不到 0.1% 像素，整页阈值会放过。
- **GT-UI-PIXEL-THRESHOLD**：阈值在规格卡里提前写定（参考 maxDiffPixelRatio：精准复刻 0.001，响应式近似 0.03，内容动态但布局稳定 0.05）。失败后保持阈值；确需调整时先改规格卡、写明理由并重新评审。
- **GT-UI-PIXEL-TOOL**：用 Playwright 截图断言 `await expect(page).toHaveScreenshot('<名称>.png', { maxDiffPixelRatio: 0.001, mask: [<动态区域定位器>] })`，组件裁剪用 `expect(locator).toHaveScreenshot()`，非浏览器截图用 `expect(readFileSync('<截图>.png')).toMatchSnapshot('<名称>.png', { maxDiffPixelRatio: 0.001 })`。`--update-snapshots` 先经评审。记录：`gt run <T> --kind e2e --name pixel -- npx playwright test <视觉用例>`。
- **GT-UI-PIXEL-OVERLAY**：用了基线叠加层或视觉锁层时，再截一张去掉锁层的真实 DOM 图并断言；锁层截图只作对照。
- **GT-UI-PIXEL-100**：用户要求「100% 一致」时分四项给结论：覆盖完整（每个状态都有证据）、同环境像素零差异、阈值内高保真、原生行为一致。

## 4. 桌面应用（Tauri、Electron、原生）

- **GT-DESK-CAPABILITY**：浏览器自动化、computer use、桌面控制按当前主机实测报告，写成「<工具> 在 <主机与 OS> 上已实测 <动作>」。文档写有不等于可用；不可用时记 blocked。
- **GT-DESK-LEVELS**：按层级取证，互不替代：L1 逻辑单元或集成测试；L2 浏览器或 mock IPC；L3 真实应用（测试构建、真实 WebView 与 IPC）；L4 生产安装包（安装、启动、权限、升级、卸载）。在 `gt run --name` 里标层级，如 `--name L3-login`。
- **GT-DESK-NATIVE**：窗口、菜单、托盘、快捷键、文件对话框、通知、权限、深链、单实例、休眠恢复按产品需要逐项验证；原生行为用 L3/L4 证据证明，浏览器截图只证明渲染。
- **GT-DESK-PLATFORM**：macOS、Windows、Linux 分别记录 OS 版本、架构、WebView 版本、缩放、主题，分别保存基线；每个平台单独给结论。
- **GT-DESK-DRIVER**：按框架当前官方文档选择自动化驱动，记录驱动名称和版本；先在目标平台确认驱动可用，再写 L3 结论。
- **GT-DESK-IPC**：前端负责渲染与交互；文件、进程、密钥走类型化 IPC（如 Tauri command、Electron preload 里的 contextBridge），按窗口最小授权；越权调用和拒绝路径写进测试计划的风险清单。
- **GT-DESK-ISOLATION**：测试插件、调试端口和宽泛测试权限只放在测试构建；L4 检查确认生产包里没有它们。
- **GT-DESK-RUST**：Rust 代码跑 `cargo fmt --check`、`cargo clippy -- -D warnings`、`cargo test`，用 `gt run <T> --kind lint` 和 `--kind affected` 记录。
