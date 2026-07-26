#!/bin/bash
set -euo pipefail

BENCHMARK_ADAPTER={{BENCHMARK_ADAPTER_Q}}
BENCHMARK_ADAPTER_SHA256={{BENCHMARK_ADAPTER_SHA256_Q}}
export GOAL_TEAMS_RELEASE_PLAN_PATH={{PLAN_PATH_Q}}
export GOAL_TEAMS_RELEASE_PLAN_DIGEST={{PLAN_DIGEST_Q}}

if [[ -z "$BENCHMARK_ADAPTER" || ! -f "$BENCHMARK_ADAPTER" || -L "$BENCHMARK_ADAPTER" ]]; then
  echo "benchmark_adapter_required" >&2
  exit 43
fi
python3 -c 'import hashlib,sys; p=sys.argv[1]; expected=sys.argv[2]; observed=hashlib.sha256(open(p,"rb").read()).hexdigest(); raise SystemExit(0 if observed == expected else "benchmark adapter digest drift")' "$BENCHMARK_ADAPTER" "$BENCHMARK_ADAPTER_SHA256"
"$BENCHMARK_ADAPTER"
