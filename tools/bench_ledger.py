#!/usr/bin/env python3
"""Micro-benchmark for the ledger: append cost per event and full replay time.

  python3 tools/bench_ledger.py --events 1000
  python3 tools/bench_ledger.py --events 10000 --json

A component metric only (decision in the V2.9 plan: no checkpoints until replay is shown to be a
bottleneck). Runs in a temporary directory; nothing is left behind.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "goal-teams" / "skills" / "goal-teams" / "scripts"))

from goalteams.ledger import Project, init_state  # noqa: E402
from goalteams.state import reduce  # noqa: E402


def run(events: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="gt-bench-"))
    try:
        project = Project(tmp, tmp)
        init_state(project, "bench", "zh")
        project.append("goal", {"id": "G1", "title": "bench", "criteria": [], "mode": "tracked", "risk": "normal"}, "lead")
        started = time.perf_counter()
        for index in range(events):
            if index % 3 == 0:
                project.append("task.add", {"id": "T%d" % index, "title": "t", "owner": "goal_backend",
                                            "validator": "goal_reviewer", "scopes": ["src/%d.py" % index],
                                            "accept": "a", "exit": "e"}, "lead")
            elif index % 3 == 1:
                project.append("run", {"id": "R%d" % index, "task": "T%d" % (index - 1), "kind": "affected",
                                       "passed": True, "exit_code": 0, "cmd": ["true"], "source_digest": "x",
                                       "code_digest": "x", "goal": "G1"}, "goal_unit_test_runner")
            else:
                project.append("review", {"task": "T%d" % (index - 2), "by": "goal_reviewer", "verdict": "pass",
                                          "assurance": "correlated_reviewer", "binds": {}}, "lead")
        append_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        loaded = project.events()
        load_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        state = reduce(loaded)
        replay_ms = (time.perf_counter() - started) * 1000
        return {"events": events, "ledger_bytes": project.ledger_path.stat().st_size,
                "append_ms_per_event": round(append_ms / max(events, 1), 3), "load_ms": round(load_ms, 1),
                "replay_ms": round(replay_ms, 1), "tasks": len(state.tasks), "receipts": len(state.receipts)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.events)
    if args.json:
        print(json.dumps(result))
    else:
        print("%(events)d events, %(ledger_bytes)d bytes: append %(append_ms_per_event).2f ms/event, "
              "load %(load_ms).0f ms, replay %(replay_ms).0f ms (%(tasks)d tasks, %(receipts)d receipts)" % result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
