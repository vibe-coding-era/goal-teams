#!/usr/bin/env python3
"""Validate or summarize Goal Teams benchmark task packages."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = ROOT / "benchmarks" / "tasks"
REQUIRED_FILES = ["task.md", "harness.md", "scoring.md", "expected-artifacts.md"]
REQUIRED_TERMS = ["baseline", "goal-teams", "scoring"]


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def check_tasks() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task_dir in sorted(TASKS_DIR.glob("GT-BENCH-*")):
        missing = [name for name in REQUIRED_FILES if not (task_dir / name).is_file()]
        combined = "\n".join((task_dir / name).read_text(encoding="utf-8") for name in REQUIRED_FILES if (task_dir / name).is_file())
        combined_lower = combined.lower()
        missing_terms = [term for term in REQUIRED_TERMS if term.lower() not in combined_lower]
        rows.append({"task": task_dir.name, "missing_files": missing, "missing_terms": missing_terms})
    if not rows:
        fail("No benchmark tasks found")
    failures = [row for row in rows if row["missing_files"] or row["missing_terms"]]
    if failures:
        fail(json.dumps(failures, ensure_ascii=False, indent=2))
    return rows


def write_report(rows: list[dict[str, object]], output: Path) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_count": len(rows),
        "tasks": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".json":
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        lines = ["# Goal Teams Benchmark Report", "", f"- generated_at: {payload['generated_at']}", f"- task_count: {len(rows)}", ""]
        lines.append("| Task | Status |")
        lines.append("| --- | --- |")
        for row in rows:
            lines.append(f"| {row['task']} | ready |")
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", default="benchmarks/runs/latest-report.md")
    args = parser.parse_args()
    rows = check_tasks()
    if not args.check_only:
        write_report(rows, ROOT / args.output)
    print(f"Benchmark package validation passed for {len(rows)} tasks.")


if __name__ == "__main__":
    main()
