---
type: Goal Teams Desktop Engineering Protocol
title: Goal Teams V2.46 Rust/Tauri 桌面工程协议
description: Rust、Tauri、桌面复刻与跨平台客户端测试的条件合同。
tags: [goal-teams, rust, tauri, desktop, testing]
timestamp: 2026-07-27T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.46 Rust/Tauri 桌面工程协议

本协议把桌面前端复刻、Rust 后端工程与跨平台客户端测试合并为一个条件路由合同。它不替代
`references/verification-governance-protocol.md`：桌面合同定义验收分母，验证治理协议负责
Evidence 的历史保留、当前适用、状态转换与独立审计。

机器 SSOT：

- 能力清单：`references/desktop-capability-manifest.json`
- 合同 schema：`schemas/v2.46/desktop-engineering.schema.json`
- validator：`scripts/checks/validate-desktop-engineering.py`

## 1. 条件路由

只有 route facts 命中 `desktop=true`、`tauri=true`、`rust=true`、桌面安装包、原生窗口/
菜单/托盘/权限或跨平台客户端测试时才加载本协议。普通 Web、纯文档和无 Rust 的后端任务
不得被无意义升级。

| Profile | 最小要求 |
| --- | --- |
| Lite | 仅局部、低风险且不触及原生能力；保留相关 Rust 门禁或单一 surface 检查。 |
| Standard | 完整相关 UI/Rust 合同、L1/L2，以及至少一个真实目标 tuple 的 L3。 |
| Full | 全部 required platform tuple、L1–L4、独立 QA/Reviewer、对抗路径和安装包隔离。 |
| Regulated | Full，加安全/合规审批、固定 toolchain、可复现包和独立 Completion Audit。 |

`required=true` 的 platform、surface、native capability 或 risk 不得因成本、runner 缺失或
工具不可用改成 N/A。它们只能是 `passed|failed|blocked|not_run|flaky|unavailable`，其中
除 `passed` 外均阻断 `achieved`。N/A 只允许用于产品合同明确不存在的能力，并绑定依据、
审批 Evidence 与非执行者审批身份。

JSON Schema 的 `allOf/if/then` 只提供结构提示，不单独构成验收。desktop validator 必须
完整重算上述 route facts、profile escalation 与派生分母；schema-only 通过不能替代该
semantic validation。

## 2. 桌面前端与“百分百复刻”

“百分百复刻”不是一个模糊分数，必须分别报告：

1. `coverage_complete`：来源清单、窗口、页面、组件、状态、交互和原生 surface 的固定
   分母全部覆盖；只有 `covered == denominator` 才是 100%。
2. `pixel_exact`：同一 `platform_tuple`、窗口尺寸、DPR、字体、主题、locale、WebView
   与捕获区域下，`changed_pixels=0`、`tolerance=0`、`mask_count=0`。任何非零差异都
   不得写成 pixel exact。
3. `high_fidelity`：用于跨 WebView 或无法锁定像素环境的视觉相似性，必须保留算法、
   阈值、实际值和差异图；它不等于 pixel exact。
4. `native_semantic_match`：窗口行为、焦点、快捷键、菜单、托盘、对话框、通知、权限、
   深链、单实例、休眠恢复等原生语义逐项通过；截图不能替代行为断言。

每个 baseline 都绑定 source digest、revision、platform tuple、捕获参数和独立 Reviewer。
不同 OS/WebView 不得共用一个“跨平台像素基线”。

### 2.1 有原型

HTML 或高保真原型先生成 source inventory，再将每一项映射到 desktop/window spec、
state matrix 和 baseline。实现者不得自行删除看似重复或困难的状态；差异项进入
append-only issue ledger。

### 2.2 只有 PRD

强制顺序：

`PRD → desktop application/window spec → 可交互 HTML prototype → 非作者 baseline approval → route revision=replica → Tauri implementation`

在 baseline approval 前，不得宣称进入“百分百复刻”实施，也不得用实现截图反向充当原型。
PRD、窗口规格、HTML 原型和批准记录都必须是可哈希回读的 artifact。

### 2.3 Tauri 前端边界

- Web 前端只负责渲染和用户交互；系统权限、文件、进程、密钥和持久化不得绕过 typed IPC。
- `invoke` command 的输入、输出、错误、授权、超时和取消语义必须进入合同。
- Capability/Permission 按窗口和命令最小授权；拒绝路径与越权调用进入风险分母。
- 测试插件、调试端口、宽泛 Capability 和 instrumented-only feature 不得进入生产包。
- macOS 需要单独验证菜单栏、窗口生命周期、焦点/快捷键、权限提示、签名/公证相关行为
  以及 WKWebView 环境；不能用普通 Chrome 页面代替。

## 3. Rust 后端工程合同

默认逻辑分层为：

`Domain → Application/Ports → Infrastructure → Tauri Adapter → Composition Root`

这是一组职责和依赖方向，不要求为小项目制造空 crate。机器合同至少记录 crate/module DAG、
公开边界和 rationale，并拒绝环依赖。

### 3.1 必须项

- Domain 不依赖 Tauri、WebView 或具体存储；Application 组织用例、事务、取消和超时。
- Infrastructure 实现持久化、网络和 OS port；Tauri Adapter 只做边界校验、授权、
  typed DTO、调用委托和稳定错误映射。
- `ipc_commands` 只在 `tauri=true` 时是非空必需项；纯 Rust route 可省略、置空数组或
  标记不适用，不能为满足 schema 人工制造 Tauri IPC。
- recoverable failure 使用显式 `Result<T,E>`；panic 只表示不可恢复的程序不变量。
  `unwrap/expect` 的生产豁免必须逐项记录。
- `async_contract.applicable=true` 时，ownership、取消、超时、shutdown 和 blocking
  isolation 必须全部为真；共享状态记录锁粒度、死锁/饥饿风险与并发测试。同步且没有
  async runtime 的 Rust 范围不得伪造这些谓词，只能声明 `applicable=false`，写明理由并
  绑定 `rust_contract_na` typed approval，审批者不得是实现、测试、Reviewer、QA 或
  Completion Auditor 角色。
- `persistence_contract.applicable=true` 时，schema version、migration、事务/原子性、
  崩溃恢复和幂等谓词必须全部为真。没有持久化存储的范围同样只能通过带理由和独立 typed
  approval 的 `applicable=false` 表达；“未实现”“尚未测试”或 runner 不可用不是 N/A。
- 依赖记录用途、features、MSRV、lockfile 与安全审查；不得因“常用”无条件引入 Axum、
  Tokio 或任意框架。
- IPC 输入不可信：验证路径、大小、编码、权限、资源上限和序列化边界；敏感值不得进入日志。

### 3.2 可执行质量门

按实际 workspace 绑定可执行命令和 Evidence，至少覆盖：

- `cargo fmt --all -- --check`
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- `cargo test --workspace --all-features`
- 依赖/安全检查、feature 组合、target build 和必要的 migration/recovery 测试

命令文本不是通过证据；Evidence 必须绑定 toolchain、target、features、commit、环境、输出
摘要和真实结论。Clippy 的 restriction/pedantic lint 需逐项选择，不得整组盲开后大量 allow。

## 4. 跨平台桌面测试合同

### 4.1 `platform_tuple`

每个 tuple 至少固定：

`os + os_version + architecture + webview + webview_version + package_format + display_server + theme + locale + scale_factor`

macOS、Windows、Linux 的 required tuple 分别计入风险分母。一个 tuple 的通过不得外推到
另一个 tuple。

### 4.2 Evidence 层级

| Level | 能证明什么 | 不能替代什么 |
| --- | --- | --- |
| L1 | Rust unit/integration、纯 domain/application 行为 | WebView、IPC wiring、原生 OS、安装包 |
| L2 | mock runtime 或 browser-only frontend/IPC contract | 真实 Tauri binary 和原生行为 |
| L3 | instrumented real app、真实 WebView/IPC、诊断日志 | 生产包未携带测试能力、真实安装升级 |
| L4 | production package 的安装、启动、权限、升级/卸载与隔离 | 低层单元故障定位 |

测试结果必须记录 test/case/run ID、tuple、level、输入、处理、期望输出、业务/原生断言、
runner、独立 reviewer、artifact digest 和状态。`achieved` 还必须接收由冻结 Harness 或
trusted host 提供、位于结果 bundle 之外的 `trusted_subject_binding`：其中 40 位
candidate commit/tree、64 位 code revision digest、contract revision、environment
registry 与 toolchain fingerprint 是当前验证 SSOT。每条 Evidence 的 `code_revision`
必须等于该冻结 revision digest，每个 `environment_id` 必须解析到 registry，带 tuple 的
Evidence 还必须与 registry tuple 完全一致；结果文件和 typed Evidence 自洽不能代替这项
外部绑定。截图、页面打开、退出码或日志单独均不足以证明通过。

### 4.3 驱动与平台规则

Tauri 官方当前推荐 WebdriverIO `@wdio/tauri-service`。`embedded` provider 可覆盖
macOS、Windows 和 Linux；直接驱动 `tauri-driver` 的桌面路径只适用于 Windows/Linux。
因此：

- macOS 的自动化合同使用 `@wdio/tauri-service` + `embedded`，或明确批准且可审计的
  原生/Accessibility harness。
- browser mode 和 mock IPC 只能生成 L2。
- L3 构建必须显式标记 instrumented；L4 必须负向证明 WebDriver/test plugin、debug port、
  mock hook 和宽泛测试权限不存在。
- `embedded`/instrumented provider 只能支撑 L3；L4 必须对未携带测试插件的生产包使用
  已批准的原生/Accessibility harness，不能一边依赖注入式 driver 一边声明测试能力已移除。

官方依据：

- <https://v2.tauri.app/develop/tests/>
- <https://v2.tauri.app/develop/tests/webdriver/>
- <https://v2.tauri.app/develop/tests/mocking/>
- <https://doc.rust-lang.org/stable/clippy/continuous_integration/>
- <https://doc.rust-lang.org/cargo/commands/cargo-test.html>

### 4.4 原生与对抗场景

按产品合同纳入窗口创建/关闭/重开、焦点、菜单、托盘、文件对话框、通知、深链、单实例、
权限拒绝、签名/安装、升级/降级/卸载、sleep/resume、网络/磁盘失败、损坏状态、异常输入、
IPC 越权、并发、取消、重试和崩溃恢复。manifest 的 required native risk 必须持续保持
`required=true`，不得降级为 optional/N/A。只有不在 required catalog 且产品合同明确
不存在的能力可使用 N/A，并同时绑定 impact proof、typed approval 与独立 approver；
存在但尚未实现/无法运行必须分别记录 `not_run|blocked|unavailable`。

## 5. 独立性与完成谓词

- 实现者不能批准自己的 source baseline、N/A、测试结果或 Completion。
- 测试设计者与 runner 按现有条件路由保持独立；Full/Regulated 的 QA、Reviewer、
  Completion Auditor 不能与实现者或 runner 同一 run identity。
- `contract_achieved` 只由 schema/validator 在 route 派生的 required denominator 全部 `passed`、
  Evidence 可回读、生产包隔离通过且独立审计闭合后派生。
- Full/Regulated 的 `achieved` 必须同时回读 typed QA receipt 与 typed Completion Audit
  receipt；两者分别绑定 bundle/revision、角色 run ID、完整 Evidence ID 集、完整 Evidence
  binding digest、trusted subject binding digest 和机器重算的完成谓词。只填写角色字符串、
  只绑定 Evidence ID 或篡改 receipt run ID 均 fail closed。
- `decision.run_outcome` 必须按真实阻断状态投影：`failed`、`blocked/unavailable`、
  `not_run`、`flaky/其他未闭合谓词 -> partial` 与 `achieved` 不得互换。
- 任何未知 platform、未声明 driver、层级冒充、伪造/过期 Evidence、分母缩小、缺失
  baseline 或 schema/runtime/docs 漂移都 fail closed。

## 6. 与统一验证治理的连接

桌面合同中的 AC、surface、Rust gate、platform tuple、native capability 和 adversarial risk
都必须进入 `verification_contract` 与 impact assessment。规则升级后：

- 旧桌面 Evidence 仍保留为绑定旧 tuple/工具链/合同的历史事实；
- 仅受影响项变成 `stale/retest_required`，复验生成新的 Evidence ID 并通过
  `supersedes_evidence_id` 关联旧结果；
- 新平台、能力或门禁为 `not_run`；
- 全量桌面回归是当前策略，不等于删除旧 L1–L4 记录。
