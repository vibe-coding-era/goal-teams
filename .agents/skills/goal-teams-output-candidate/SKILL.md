---
name: goal-teams-output-candidate
description: Goal Teams V2.68 本地输出候选入口；在本工作树中校验并序列化 discussion、文档交付与 execution 回复，不代表 Current 激活或 Host 发送拦截。
---

# Goal Teams 输出候选入口

这是显式选择的 V2.68 本地候选，不替换 Current V2.67，不更改 ACTIVE，不安装为全局 Skill。用户授权与仓库 `AGENTS.md` 优先；调用输出入口不会授予开发、发布或外部写入权限。

1. 定位包含本文件的仓库根，完整读取 [候选输出合同](../../../references/candidates/V2.68/output-contract.md)。请求形状见 [output-request.schema.json](../../../schemas/v2.68/output-request.schema.json)；以运行时校验为准。
2. 使用 Python 3.11+，以该仓库根为工作目录，调用 `python -m scripts.v268.output_gateway`。按真实活动选择 typed facts；文档交付必须在写入前 prepare，写入后 observe，获得真实 reviewer note 后再声明完成。
3. CLI 只输出到 stdout。由调用者将必要记录保存到已授权的本地 `docs/`，保留原始记录和摘要；不要把返回 JSON 当成已落盘证据。
4. 每条 final 在发送前调用 `render`，将返回 `body` 原样用作 assistant final 正文；失败使用返回的 `blocked/replan` 正文并修正输入，不手写替代看板。独立保留 `artifact_delivery`，不能把输出失败改写成产物回滚。
5. commentary 与上层 machine trailer 由各自上层协议处理，均不拼入待校验正文。返回值仅证明本地校验/序列化，`host_enforcement=unavailable`；禁止声称候选入口已拦截 Host 的全部发送。

从仓库根检索本入口：`rg --files .agents/skills/goal-teams-output-candidate references/candidates/V2.68 schemas/v2.68`。
