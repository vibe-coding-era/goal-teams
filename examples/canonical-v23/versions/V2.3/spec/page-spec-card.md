---
type: Page Specification Card
title: Canonical UI Replica Behavior Spec
description: 为 canonical 的 ui-replica 行为场景声明组件库、参考源、交互态和视觉证据契约。
tags: [goal-teams, page-spec, canonical, ui-replica]
timestamp: 2026-07-10T00:00:00Z
okf_version: "0.1"
goal_teams_version: V2.3
artifact_version: V2.3
component_library: Native HTML fixture components
component_library_version: V2.3
component_library_url: https://html.spec.whatwg.org/
ui_mode: replica
reference_source: behavior/ui-replica reference fixture
---

# Canonical UI Replica Behavior Spec

## Component Visual Contract

- `canonical-button`：default、hover、focus、disabled 四态必须出现在 trace。
- deterministic fixture viewport：`2x2`；DPR：`1`；font：`Goal Teams Fixture Sans`；browser：`Chromium fixture-1`。
- Pixel Gate：颜色容差、mask、MAE、关键区域和环境指纹共同决定结果。

## Evidence

- Behavior record：`../behavior/ui-replica.json`
- Pixel report：`../behavior/evidence/ui-replica/pixel-report.json`
- Baseline approval：`../behavior/evidence/ui-replica/baseline-approval.json`
- Baseline / actual environment：`../behavior/evidence/ui-replica/baseline-environment.json`、`../behavior/evidence/ui-replica/actual-environment.json`
- 发布期 blind execution：`scripts/benchmark/benchmark-runner.py --mode blind-agent --release-gate ...`
