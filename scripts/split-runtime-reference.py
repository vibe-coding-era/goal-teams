#!/usr/bin/env python3
"""Split the large runtime reference into deterministic progressive-loading parts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "references" / "goal-teams-runtime.md"
PARTS = ROOT / "references" / "runtime"
TARGET_BYTES = 40 * 1024


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:48] or "section"


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    if "本文件是渐进式索引" in text:
        raise SystemExit("runtime reference is already split")
    sections = re.split(r"(?=^##\s+)", text, flags=re.MULTILINE)
    preamble = sections.pop(0)
    groups: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for section in sections:
        size = len(section.encode("utf-8"))
        if current and current_size + size > TARGET_BYTES:
            groups.append(current)
            current, current_size = [], 0
        current.append(section)
        current_size += size
    if current:
        groups.append(current)

    PARTS.mkdir(parents=True, exist_ok=True)
    links: list[str] = []
    for number, group in enumerate(groups, 1):
        heading = re.search(r"^##\s+(.+)$", group[0], flags=re.MULTILINE)
        label = heading.group(1).strip() if heading else f"Part {number}"
        name = f"{number:02d}-{slug(label)}.md"
        body = "---\ntype: Goal Teams Runtime Reference Part\ntitle: " + label + "\ndescription: Goal Teams runtime 渐进式分片。\ntags: [goal-teams, runtime, progressive-loading]\ntimestamp: 2026-07-12T00:00:00+08:00\nokf_version: \"0.1\"\n---\n\n# " + label + "\n\n" + "".join(group)
        (PARTS / name).write_text(body, encoding="utf-8")
        links.append(f"- [`runtime/{name}`](runtime/{name})：{label}")

    frontmatter = preamble.split("# Goal Teams", 1)[0].rstrip()
    index = frontmatter + "\n\n# Goal Teams Runtime\n\n本文件是渐进式索引。先按场景选择一个分片，不要一次加载全部 runtime。\n\n" + "\n".join(links) + "\n"
    SOURCE.write_text(index, encoding="utf-8")


if __name__ == "__main__":
    main()
