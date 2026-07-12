# 版本变更记录

本文档按版本提供面向读者的中文变更摘要；英文对应文件为 [change-history.en.md](change-history.en.md)。逐项技术记录仍见仓库根目录 [CHANGELOG.md](../CHANGELOG.md)。当前版本事实以 `VERSION` 为准。

## 记录边界

- 本文档不把规划、建议或未验证事项写成已交付能力。
- V2.33 将 README 中的发布内容与历史入口拆分为本组双语文档；本记录说明其范围，但不能替代 `VERSION` 同步和验证门禁。
- V2.34 的完成公开文档在独立审计和 sanitizer 通过后按 delivery id 归档；过程包与私有 provenance 不进入公开归档。
- V2.35 公开发布摘要在图外 Completion Audit 前生成并明确标注审计尚未运行；最终审计仍只存放在非公开过程包中。
- 本地规划源 `docs/后续版本规划 V3.3-3.5.md` 仅由用户维护，不属于仓库或安装包；不得由 AI 修改或在未获单独授权时提交 GitHub。

## 已记录版本

| 版本 | 已记录变化摘要 |
| --- | --- |
| V2.35 | 增加安全、性能、重构与 SQA 四个只读提案专家，专家不直接实现或派发；增加 `large|medium|small` × `feature|bugfix` 正交路由及安全/UI 覆盖；强制测试用例具有输入、处理、期望输出与可执行断言；用显式 hash-bound 版本 descriptor 隔离 V2.34 默认行为与 V2.35 状态/归档。 |
| V2.34 | 引入合同先行的 `Gather → Reason → Act → Verify → Repeat`；用 `feature_list.json` / `progress.md` / `contract.md` / `log.md` 和 journal/CAS 支持崩溃恢复；要求 Architecture accepted 后的 Environment Evidence；约束第 9 轮候选集 quarantine 与第 11 轮 fail-closed 交付；增加四维评分、GTLOG 分歧/提示词生命周期、moving bottleneck 和公开归档清洗。 |
| V2.33 | 在 V2.3 机器契约基线上明确系统/用户、`AGENTS.md`、不变量、条件规则、`RULES.md`、Lead、Member 的优先级；定义引用文件的 fail-closed 分类和受限降级、显式 no-write `plan_preview` 判定、单值 `check_state` 表述，并将发布内容与历史入口改为独立双语文档。 |
| V2.3 | 引入闭合状态枚举、单写者 append-only ledger、严格 Evidence/Traceability/Dual Review、Profile 路由与能力降级、typed migration、原子安装与确定性 release gates。技术 RC 与公开 GA 仍分开判断。 |
| V2.1 | 增加 Lead LOOP、Loop Decision、Loop Gate、状态快照与 `GT-BENCH-004`，用于记录整合后的续跑或停止决定。 |
| V2.02 | 增加 `RULES.md` 响应契约，要求执行优先、事实优先和不把未验证结果说成完成。 |
| V2.0 | 将 SSOT 输出置于版本子目录，要求先生成 `TaskList.md`，并明确后端架构、TDD、API 集成和 E2E 的独立测试分工。 |
| V1.97 | 增加 Google OKF、本地双语规范、默认输出目录、`memory.md` 与页面规格/HTML 原型的组件库记录。 |
| V1.94–V1.96 | 增加角色成员包、LLM 加脚本双重复核、Plan 模式需求卡片、用户故事与功能验收标准向 Harness、测试和验收流转。 |
| V1.8–V1.93 | 逐步增加机器可读 Harness/Evidence/Pipeline 协议、生产 release gate、脚本化工具、冲突和预算门、渐进式加载入口与成员派发协议。 |
| V1.4–V1.7 | 建立 Plan 模式、Teams 规划表、Harness、成员/Lead/Skill Improvement 三层 Loop、最小示例和 Benchmark 模板。 |

## 维护规则

新增版本时，先更新可验证的技术记录，再同步本文档和英文版本；任何版本号改动仍须遵循 `VERSION`、`SKILL.md`、README 与兼容规则的同步校验。对完整条目、兼容性细节和历史修订，使用 [CHANGELOG.md](../CHANGELOG.md) 而非根据本摘要推断。
