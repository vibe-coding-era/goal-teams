#!/usr/bin/env python3
"""Deterministically generate concise progressive-loading indexes for member packages."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ROOT / "prompts" / "members"
FILES = ("prompt.md", "template.md", "workflow.md", "scripts.md")


def title(text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else fallback


def build(role_dir: Path) -> str:
    prompt = (role_dir / "prompt.md").read_text(encoding="utf-8")
    role_title = title(prompt, role_dir.name)
    role_id = "goal_" + role_dir.name.replace("-", "_")
    bullets = [
        re.sub(r"^[-*]\s+", "", line).strip()
        for line in prompt.splitlines()
        if re.match(r"^[-*]\s+\S", line)
    ]
    role_line = next((line.strip() for line in prompt.splitlines() if line.startswith("角色：")), "")
    description = role_line or (bullets[0] if bullets else f"承担 {role_title} 的目标交接物。")
    role_rule = (bullets[0] if bullets else "按角色 prompt 完成交接并提交 current Evidence").rstrip("。；")
    return f"""# {role_title} 索引

先读本文件，再按任务阶段加载；不要一次读取整个成员包。

- role: `{role_id}`
- description: {description}
- triggers: Lead 路由或 Member Goal Packet 指定 `{role_id}` 时加载。
- rules: {role_rule}；同时遵守 invariants、locked scope、Harness/Evidence 与独立验证。
- forbidden: 不直接改中央 TaskList，不越过 locked scope，不自我批准，不创建嵌套团队。
- inputs: `context_refs`、`fetch_recipe`、SPEC 和任务 ledger 前缀。
- outputs: revision-bound event/patch、角色交接物、current Evidence 与阻塞说明。
- validator: Goal Packet 指定的不同 member/run；缺失时 blocked。

| 需要 | 文件 | 加载时机 |
| --- | --- | --- |
| 身份、边界、完成条件 | `prompt.md` | 派发与执行前必读 |
| 交付结构 | `template.md` | 需要生成交接物时 |
| 阶段与门禁 | `workflow.md` | 进入具体执行阶段时 |
| 确定性工具 | `scripts.md` | 选择或运行脚本时 |

共享规则仅在需要时读取 `../shared.md`；上层以 Member Goal Packet 的 `context_refs` 与 `fetch_recipe` 为准。
"""


def main() -> None:
    for role_dir in sorted(path for path in MEMBERS.iterdir() if path.is_dir()):
        missing = [name for name in FILES if not (role_dir / name).is_file()]
        if missing:
            raise SystemExit(f"missing member files for {role_dir.name}: {', '.join(missing)}")
        (role_dir / "INDEX.md").write_text(build(role_dir), encoding="utf-8")


if __name__ == "__main__":
    main()
