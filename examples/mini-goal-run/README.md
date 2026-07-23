# Mini Goal Run 示例

这个目录展示一次最小 Goal Teams 执行产物。它不是完整业务项目，而是用于检查 skill 输出结构、文档索引、tasklist、SPEC 和独立校验记录是否清楚。

新增的 `harness/` 目录提供最小复盘 Harness：维护者可以按 `setup -> run -> checks -> report` 顺序检查一次 Goal Teams 文档运行的输入、执行记录、校验点和验收证据。

## 示例目标

为一个演示项目规划“登录页空状态提示 V0.1”，只生成计划、文档、HTML 原型和 Harness 复盘资料，不修改真实业务代码。

## 推荐提示词

```text
Use $goal-teams。
请为“登录页空状态提示 V0.1”生成一个最小 Goal Teams 示例。
先汇报：我是 Goal Teams Lead V2.44。
只做规划和文档产物，不修改实现文件。
过程和结果保存到 V0.1 版本目录。
结构化路由记录 `project_size=small`、`work_type=feature`、`ui=true`；不因 small 省略 Architecture、Environment、独立测试或 Evidence，UI 仍要求 E2E。
必须先写入包含用户故事和功能验收标准的需求卡片，再列出四列合并展示的 Teams 规划表，并包含 workflow、前置任务、需求规格卡、PRD、架构设计、HTML 原型、TaskList、测试计划、验收清单、独立校验计划和收尾审计。真实后端/前端项目还要按 V2.0 拆出后端 TDD、API 集成测试和 E2E 生成/执行任务；本示例不涉及真实代码时写 `not_applicable_reason`。
```

如果希望示例直接进入执行，可以写：

```text
Use $goal-teams。
请直接执行：生成“登录页空状态提示 V0.1”的最小 Goal Teams 示例。
仍然先展示 Teams 规划表作为执行记录，但不用等我确认。
```

## 产物结构

```text
.codex/goal-teams/
  index.md
  memory.md
  team-state.json
  versions/V0.1/
    index.md
    plan.md
    progress.md
    decisions.md
    TaskList.md
    tasklist.md
    spec/
      requirement-card.md
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
    harness/
      README.md
      setup.md
      run.md
      checks.md
      report.md
      automation-protocol.sample.yaml
      evidence-ledger.sample.json
      pipeline-gates.sample.yaml
```

## 使用方式

维护者可以对照这个示例检查：

- 多文档前是否先有总索引和版本索引。
- `plan.md` 是否先列出四列合并展示的 Teams 规划表，且运行时 subagent id、member_id 和成员展示名是否采用 `<中文角色>-<具体任务名>`，例如 `后端-WIKI 列表后端开发`；如果用户指定 skill，则使用 skill 名称，例如 `browser-WIKI 列表页面验证`。
- 首次建立身份时是否只简短汇报 `我是 Goal Teams Lead V2.44。`。
- 是否只在缺少历史资料会改变执行时才询问；上下文已经完整时直接工作，并在需要时记录 `历史资料：未提供`。
- 如果提示词包含 `直接执行` / `不用确认` / `跳过确认`，是否仍展示执行计划并跳过等待确认。
- 如果等待用户选择，是否使用数字选项让用户能回复 `1`、`2` 或 `3`。
- TaskList 是否包含成员、认领、workflow、前置任务、锁定范围、验收和校验者；真实项目是否拆到 V2.0 最小颗粒度。
- Plan 是否先写入 `spec/requirement-card.md` 并覆盖核心目标、关键功能、用户故事、功能验收标准、边界、约束和风险。
- SPEC 是否从需求规格卡到 PRD 再到设计/测试/验收逐层展开。
- 涉及 HTML 原型时是否强制界面级 E2E；`sample_only` / `no_runner` 只说明当前不可执行，不豁免门禁，应将 E2E 及下游验收标为 blocked。复刻任务还必须截图做像素级对比。
- 独立校验证据是否进入 `progress.md` 或 `acceptance.md`。
- Completion Audit 是否保持在 required task 图外，只在全部 required tasks accepted 后派发 `goal_completion_auditor`；有未完成工作时先续跑 required tasks。
- Harness 复盘资料是否能从 `harness/setup.md`、`harness/run.md`、`harness/checks.md`、`harness/report.md` 追到 `progress.md` 和 `acceptance.md`。
- automation protocol、evidence ledger 和 pipeline gates 样例是否标明 `sample_only`，且不声明真实生产、CI、凭证、支付或认证接入。
