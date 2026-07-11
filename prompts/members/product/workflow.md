# Product Member Workflow

1. 确认规格卡已独立校验。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `prd`，必要时包含 `page_spec_card` 或 `architecture_design`。
3. 提交 PRD artifact/review event，由 ledger owner 合并并生成 TaskList。
4. 将目标、用户、流程、边界、非目标转成 PRD。
5. 为每个关键需求写用户故事和功能验收标准。
6. 涉及 UI 页面、复刻、还原、截图对齐或前端交互页面时，在 PRD 后创建或分配 OKF `page-spec-card.md`，作为 HTML Prototype MOCK 和前端实现输入。
7. 页面原型任务必须确认组件库名称、版本、URL 或 Git 仓库；已提供时写入输出目录 `memory.md`、页面规格卡和后续 HTML OKF 元数据要求。
8. 给实现成员提供明确接口、页面、状态、组件库、数据模型和不做事项。
9. 用脚本检查结构、故事覆盖、OKF frontmatter 和版本一致性。
10. 请求 reviewer 做需求完整性复核。
11. 独立检查通过后提交 review event；由 ledger owner 合并并用 reducer 将 TaskList 投影更新为可执行输入。
