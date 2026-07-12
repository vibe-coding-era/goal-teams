# 发布内容

本文档是 Goal Teams 可见发布包的中文索引。英文对应文件为 [release-contents.en.md](release-contents.en.md)。运行时版本始终以仓库根目录 `VERSION` 为准；运行规则以 `SKILL.md`、`RULES.md`、`references/` 与 `prompts/` 的适用契约为准。

## 当前边界

- 本文档只列出当前仓库可验证的包组成，不声明尚未实现的功能。
- V2.35 保留 V2.34 控制面默认行为，新增四专家提案、项目规模/工作类型路由、测试断言契约与显式版本绑定；本索引不能替代契约或验证。
- `SKILL.md` 与 README 的人工维护内容是基线。发布内容索引不能覆盖它们，也不能替代脚本验证。
- 本地规划源 `docs/后续版本规划 V3.3-3.5.md` 由用户维护，不属于仓库或安装包。AI 不得修改；除非用户再次单独授权，也不得将它提交到 GitHub。规划文本不是发布承诺。

## 包组成

| 分类 | 当前发布内容 |
| --- | --- |
| 根文件 | `VERSION`、`SKILL.md`、`RULES.md`、`goal-teams.md`、`AGENTS.md`、`CHANGELOG.md`、`README.md`、`README.en.md`、`agents/openai.yaml` |
| 规则与兼容 | `references/goal-teams-runtime.md`、`references/default-AGENTS.md`、`references/invariants.md`、`references/compat.md`、`references/rules-ui.md`、`references/rules-testing.md`、`references/rules-loop.md`、`references/goal-teams-automation-protocol.md`、`references/goal-teams-production-pipeline.md`、`references/goal-teams-scripted-tooling.md`、`references/goal-teams-v2.3-contract.md`、`references/google-okf-bilingual-spec.md`、`references/ui-e2e-pixel-protocol.md`、`references/ui-visual-contract-protocol.md`、`references/subagent-dispatch-protocol.md`、`references/dual-review-protocol.md` |
| 成员与提示词 | `subagents/goal-*.toml`、`prompts/`、`prompts/lead/`、`prompts/members/`、`prompts/packets/` |
| 工具与校验 | `scripts/check.sh`、兼容入口 `scripts/*.py`、实现目录 `scripts/v23/`、`scripts/checks/`、`scripts/harness/`、`scripts/benchmark/`、`scripts/review/`、`scripts/install/` |
| 机器契约与测试 | `schemas/`、`tests/v23/`、`.github/workflows/` |
| 示例与基准 | `examples/mini-goal-run/`、`examples/canonical-v23/`、`benchmarks/` |
| 发布说明 | 本文档、[版本变更记录](change-history.md)、V2.35 双语 pre-audit release summary，以及按已校验 release version 归档的公开文档 |

## 详细路径索引

为方便安装、校验和人工检查，以下保留发布包的具体路径索引；它是本仓库中发布清单的唯一人类可见承载位置。

- 根文件：`VERSION`、`SKILL.md`、`RULES.md`、`goal-teams.md`、`AGENTS.md`、`CHANGELOG.md`、`README.md`、`README.en.md`、`agents/openai.yaml`。
- rules 与 references：上述兼容文件，以及 V2.35 按需入口 `references/rules-project-sizing.md`、`references/rules-specialists.md`、`references/test-case-assertion-protocol.md`。
- 成员与 prompts：`subagents/goal-*.toml`、`prompts/`、`prompts/lead/core.md`、`prompts/lead/requirement-card.md`、`prompts/members/shared.md`、`prompts/members/backend/prompt.md`、`prompts/members/backend/template.md`、`prompts/members/backend/workflow.md`、`prompts/members/backend/scripts.md`、`prompts/members/unit-test-designer/prompt.md`、`prompts/members/unit-test-runner/prompt.md`、`prompts/members/api-integration-test-designer/prompt.md`、`prompts/members/api-integration-test-runner/prompt.md`、`prompts/members/e2e-test-designer/prompt.md`、`prompts/members/e2e-test-runner/prompt.md`、`prompts/packets/member-goal-packet.md`、`prompts/packets/handoff-artifacts.md`、`prompts/packets/page-spec-card.md`、`prompts/packets/memory.md`、`prompts/packets/html-prototype-mock.md`、`prompts/packets/requirement-card.md`、`prompts/packets/dual-review-record.md`。
- 脚本：`scripts/check.sh`、`scripts/validate.py`、`scripts/install-local.sh`、`scripts/check-version-sync.py`、`scripts/check-routing-fixtures.py`、`scripts/check-agent-names.py`、`scripts/check-member-layout.py`、`scripts/validate-harness.py`、`scripts/pixel-diff.py`、`scripts/compare-artifacts.py`、`scripts/validate-dual-review.py`、`scripts/benchmark-runner.py`、`scripts/validate-test-case-contract.py`；实现目录 `scripts/v23/`、`scripts/checks/`（包括 `scripts/checks/check-routing-fixtures.py` 与 `scripts/checks/validate-test-case-contract.py`）、`scripts/harness/`、`scripts/benchmark/`、`scripts/review/`、`scripts/install/`。
- 契约、测试和回归：`schemas/`、`tests/v23/`、`.github/workflows/`、`examples/mini-goal-run`、`examples/canonical-v23/`、`benchmarks/`。
- 公开完成归档：`docs/archive/<release_version>/<delivery_id>/`，其中 release version 必须由已校验 descriptor 提供；仅包含 sanitizer 和独立审计均通过的 completed/public 文档与公开 manifest。

## 发布前核对

1. 运行 `./scripts/check.sh`，确认包结构、Skill frontmatter、成员配置、README 和关键规则仍一致。
2. 核对 `VERSION`、`SKILL.md` 与 README 的当前版本口径；不要以规划文档替代版本事实。
3. 只提交用户授权的发布内容。开发过程文件、运行痕迹和用户维护的规划源文件默认不属于 GitHub 发布范围；公开归档必须先通过 sanitizer，且不包含调用语、transport handle、内部路径、运行日志或私有 provenance。
4. License 或内部共享的最终决定仍由仓库 owner 作出；没有相应授权时，不能把技术校验写成公开 GA 承诺。
