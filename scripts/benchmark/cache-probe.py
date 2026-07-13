#!/usr/bin/env python3
"""Prompt-cache probe CLI facade.

The historical CLI continues to emit the V2.38 plan-only schedule.  V2.39
planner/executor business rules live only in ``scripts/v23/cache_probe.py`` and
are exposed here as thin compatibility forwards.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime():
    path = ROOT / "scripts" / "v23" / "prompt_cache.py"
    return _load_module("_goalteams_cache_probe_v238", path)


def load_v239_runtime():
    path = ROOT / "scripts" / "v23" / "cache_probe.py"
    return _load_module("_goalteams_cache_probe_v239", path)


def build_live_probe_plan(
    current: dict[str, Any],
    candidate: dict[str, Any],
    controls: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    return load_v239_runtime().build_live_probe_plan(
        current, candidate, controls, policy
    )


def execute_live_probe(
    plan: dict[str, Any],
    authorization: dict[str, Any],
    adapter_registry: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    return load_v239_runtime().execute_live_probe(
        plan, authorization, adapter_registry, output_root
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", default="benchmark")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = load_runtime().build_cache_probe_plan(ROOT, args.route, args.repeats)
    rendered = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
