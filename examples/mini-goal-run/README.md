# Mini Goal Run 示例

这个目录展示一次最小 Goal Teams 执行产物。它不是完整业务项目，而是用于检查 skill 输出结构、文档索引、tasklist、SPEC 和独立校验记录是否清楚。

## 示例目标

为一个演示项目规划“登录页空状态提示 V0.1”，只生成计划和文档，不修改真实业务代码。

## 推荐提示词

```text
Use $goal-teams。
请为“登录页空状态提示 V0.1”生成一个最小 Goal Teams 示例。
先汇报：我是 Goal Teams Leader V1.3，我会帮你完成以下工作：
只做规划和文档产物，不修改实现文件。
过程和结果保存到 V0.1 版本目录。
必须先列出四列合并展示的 Teams 规划表，并包含需求规格卡、PRD、架构设计、HTML 原型、测试计划、验收清单、独立校验计划和收尾审计。
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
  INDEX.md
  team-state.json
  versions/V0.1/
    INDEX.md
    plan.md
    progress.md
    decisions.md
    tasklist.md
    spec/
      requirement-spec-card.md
      PRD.md
      architecture-design.md
      HTML-prototype.html
      test-plan.md
      acceptance.md
```

## 使用方式

维护者可以对照这个示例检查：

- 多文档前是否先有总索引和版本索引。
- `plan.md` 是否先列出四列合并展示的 Teams 规划表，且成员名是否采用 `角色-具体任务名`，例如 `后端-WIKI 列表后端开发`。
- 开始前是否先汇报 `我是 Goal Teams Leader V1.3，我会帮你完成以下工作：`。
- 如果提示词包含 `直接执行` / `不用确认` / `跳过确认`，是否仍展示执行计划并跳过等待确认。
- 如果等待用户选择，是否使用数字选项让用户能回复 `1`、`2` 或 `3`。
- tasklist 是否包含成员、认领、锁定范围、验收和校验者。
- SPEC 是否从需求规格卡到 PRD 再到设计/测试/验收逐层展开。
- 独立校验证据是否进入 `progress.md` 或 `acceptance.md`。
- 是否由 `goal_completion_auditor` 做收尾审计，并在有未完成工作时自动续跑。
