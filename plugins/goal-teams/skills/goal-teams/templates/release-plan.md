---
type: Goal Teams Release Plan Template
title: 发布计划模板
---

何时使用：用户要求发布、上线或部署，且实现任务已完成并通过评审后；先给用户看本计划，再做外部写入。

# 发布计划：<项目名> <版本号>

## 1. 范围

- 包含：<功能与修复，引用 REQ 或任务 ID>
- 不包含：<推迟的内容>
- 发布目标：<如 GitHub Release、包仓库、容器镜像、生产环境>

## 2. 冻结版本

- 版本号：<x.y.z>；commit：<40 位 SHA>；tag：<v 加版本号>
- 冻结后源文件一有变化，第 3 节的检查全部重跑。

## 3. 检查（对冻结版本各跑一次）

| 检查 | 记录命令 | receipt id | 结果 |
| --- | --- | --- | --- |
| 全量回归 | `gt run - --kind regression -- <命令>` | <编号> | <passed / failed> |
| 安全检查 | `gt run - --kind security -- <命令>` | <编号> | <结果> |
| 构建产物 | `gt run - --kind build --artifact <产物> -- <命令>` | <编号> | <结果> |
| 发布判定 | `gt check --release` | 无 | <退出码> |

## 4. 产物

| 文件 | 大小（字节） | SHA-256 |
| --- | --- | --- |
| <产物文件名> | <大小> | <哈希值> |

## 5. 授权动作（用户一次确认）

| 动作 | 目标 | 可逆 |
| --- | --- | --- |
| push | <远端与分支> | 是 |
| tag | <tag 名> | 否 |
| release | <Release 页面> | 否 |

用户在对话中明确同意本表后执行 `gt auth grant --actions push,tag,release --scope "<版本与目标>"`。每个动作前先 `gt auth check <动作>`，退出码 3 即停止并询问用户。

## 6. 不可逆动作预览（执行前逐条展示）

- tag：`git push origin <tag 名>` → 远端出现该 tag，之后不覆盖
- release：`gh release create <tag 名> <产物>` → 公开页面与下载链接
- deploy：`<部署命令>` → <受影响的服务与用户>

## 7. 回滚

- 触发条件：<冒烟失败、错误率上升、回读不一致>
- 步骤：<恢复到上一版本的命令>
- 数据：<备份位置；只用可逆迁移>

## 8. 回读（每个外部动作之后）

| 动作 | 回读命令 | 期望 |
| --- | --- | --- |
| tag | `git ls-remote --tags origin <tag 名>` | 指向冻结 commit |
| release | `gh release view <tag 名>` | 产物名与 SHA-256 一致 |
| deploy | <健康检查或版本接口> | 返回 <版本号> |

用 `gt run - --kind release -- <回读命令>` 记录。目标、版本或权限有偏差时立即停止并告知用户。
