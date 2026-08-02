---
type: Goal Teams Functional Contract
title: Approval and Side Effects Contract
description: 定义一次开始授权、外部副作用、GitHub SSH transport 与结果回读合同。
tags: [goal-teams, v2.50, authorization, side-effects, github]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Approval and Side Effects Contract

- `contract_id`: `CONTRACT-APPROVAL-SIDE-EFFECTS-V250`
- `purpose`: 定义项目开始一次授权、外部写入、不可逆动作、GitHub SSH transport 和 exact readback。

## trigger_and_exclusion_facts

- 触发：预计存在 commit、push、PR、merge、tag、Release、上传、安装、部署、删除或其他外部写入。
- 排除：只读检查和已锁定范围内可逆本地实现不产生重复过程授权；新范围不能在当前 LOOP 中追加授权。

## inputs

- repository/version/target、action allowlist、风险与不可逆性、有效期、授权主体和 intent digest。

## obligations_and_outputs

- 在任何实施写入前一次展示全部可预见动作并取得 Authorization Receipt。
- 后续只执行 receipt 覆盖的动作，不再逐步询问；每项外部动作 execute once 并 exact readback。
- GitHub Git transport 使用 SSH，平台保护保持启用。

## oracles_and_evidence

- Authorization Receipt digest/lineage、remote transport、action/process receipt、远端/安装 readback 和 reconciliation。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`

## dependencies

- `CORE-V250`

## owned_rule_ids

- `GT250-AUTH-START`: 项目开始时一次冻结 repository、version、target、action allowlist、有效期、风险和范围漂移条件；授权回执必须绑定 intent digest。
- `GT250-AUTH-NO-REPROMPT`: receipt 覆盖范围内后续 commit、push、PR、Release、安装或其他外部写入不得再次请求过程授权。
- `GT250-AUTH-DRIFT`: 新仓库、新版本、新外部系统、新动作类别、授权过期或实质范围漂移立即 blocked/new_scope_required，不在当前 LOOP 追加权限。
- `GT250-AUTH-EXECUTE-ONCE`: 不可幂等动作使用 `intent → execute once → exact readback → reconciliation`，禁止自动 replay。
- `GT250-AUTH-READBACK`: 外部写成功必须通过目标系统 exact identity/readback 验证；本地命令退出码不能替代远端事实。
- `GT250-AUTH-SSH`: GitHub Git transport 只允许 SSH remote；凭证不得写入命令、日志、artifact 或公开输出。
- `GT250-AUTH-PLATFORM`: 不得关闭或绕过 GitHub、操作系统、宿主或仓库外平台强制保护；需要新权限时保持 blocked。
