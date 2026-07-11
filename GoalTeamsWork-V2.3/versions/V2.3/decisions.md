---
type: Goal Teams Decisions
title: Goal Teams V2.3 修复决策
description: 记录本轮协议、范围和发布边界决策。
tags: [goal-teams, v2.3, decisions]
timestamp: 2026-07-10T15:30:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.3 修复决策

| 时间 | 决策 | 依据 | 影响 |
| --- | --- | --- | --- |
| 2026-07-10 | 撤销 M0–M6 accepted/achieved 自报状态 | 深度审计复现假绿 | TaskList 改为 review/partial/replan |
| 2026-07-10 | V2.3 PRD 为范围 SSOT | 仓库 AGENTS 与 wrapper | 不扩展到 V2.4 adapter |
| 2026-07-10 | RC 技术门禁与 GA License 门分离 | AC-23-030 / RG-23-11 | License 未决时 GA 必须 fail-closed |
| 2026-07-10 | 基础上下文包含自动加载入口与强制 Response Contract：`SKILL.md + agents/openai.yaml + RULES.md` | FR-CTX-03/05；独立 Reviewer 指出旧口径隐藏 mandatory refs | 当前 12,128 / 12,288 bytes；invariants/core/planning/memory/compat 作为路由后上下文单独报告 20,468 bytes；最终门禁重新测量 |
| 2026-07-10 | Round 1 绿色不得计为 RC 通过 | 独立 Reviewer 复现 vacuous mutation、伪 Evidence accepted、ID-only trace、raw secret log 等 P0 | `audit_state=failed`，进入 Round 2 replan |
| 2026-07-10 | Behavior Gate 必须区分 deterministic contract test 与 blind-agent eval | FR-EVL-03..07；route/reducer 执行不能证明 agent 遵守规则 | fixture/mock runner 只验证管道，不计 release；真实 runner 缺失时 fail-closed |
| 2026-07-10 | Evidence trust level 影响完成资格 | 外部引用、人工观察、unverified 不能等同 local_verified | 只有严格本地验证且当前的 Evidence 可支撑 accepted；其他证据保留但不提升状态 |
| 2026-07-10 | Mutation 必须先验证 pristine baseline，再断言目标稳定错误码 | Round 1 复制目录改变 mtime 后原样本已失败，导致 mutation 套件空转 | 任一 baseline 失败或仅命中无关错误都使测试失败 |
| 2026-07-10 | Blind eval 被测目录与隐藏评分器物理隔离 | 在仓库根运行可读取 tests、rubric 与 canonical 答案，不能构成盲测 | 只 stage allowlist runtime + 单场景输入；记录 staged/source digest 与 rubric hash |
| 2026-07-10 | Evidence 从“最终 ledger 文件 hash”改为 source revision + 非空 ledger prefix revision/digest | 最终 hash 与 append-only check/accepted 事件形成时序循环 | live workflow 可先产 Evidence 再 append；伪 prefix、退化 prefix 与错时序 fail-closed |
| 2026-07-10 | Completion Audit 改为 required task 图之外的最终门禁 | required Audit task 会形成审计→接受→ledger/digest 改变→再审计的递归 | 标准或自定义 audit 文件被 required/blocking Task/Evidence 引用时返回 `E_AUDIT_SELF_REFERENCE` |
| 2026-07-10 | replay 使用 runtime-locked artifact verifier | canonical-only verifier 可验证无关固定文件，任意 command replay又会扩大代码执行面 | argv 精确绑定 artifact/hash 与 Evidence/Review digest；不把 hash replay表述成原领域工具重跑 |
| 2026-07-10 | 领域执行必须绑定 Check/Comparison 语义 | 任意合法命令或 actual 自比 actual 仍可假绿 | Check 声明 expected argv/cwd；comparison 绑定 distinct actual/baseline 双 hash/path；Run 包络两层执行 |
| 2026-07-10 | Blind provider 信任级别限定为 local-process-attested | PATH + 本地 hash 不能证明远程真实模型 | RC 只声称运行当前解析并锁定的 CLI；更高信任需仓库外 attestation |
| 2026-07-10 | Blind stage 是 installer tracked package 的 blind-safe 投影 | rglob 会带入未跟踪文件，完整 installer 又包含 tests/answers | package manifest + index 为上游，再硬排除 answer-bearing roots、symlink 与 non-regular entries |
| 2026-07-10 | 验收后提交 GitHub 并更新本地安装 | 用户追加明确授权 | 当前分支推送并开 draft PR；只 stage V2.3 范围；安装使用同一验证提交与事务化 installer |
