#!/bin/bash
set -euo pipefail

ROLLBACK_ADAPTER={{ROLLBACK_ADAPTER_Q}}
ROLLBACK_ADAPTER_SHA256={{ROLLBACK_ADAPTER_SHA256_Q}}
export GOAL_TEAMS_RELEASE_PLAN_PATH={{PLAN_PATH_Q}}
export GOAL_TEAMS_RELEASE_PLAN_DIGEST={{PLAN_DIGEST_Q}}

if [[ -z "$ROLLBACK_ADAPTER" || ! -f "$ROLLBACK_ADAPTER" || -L "$ROLLBACK_ADAPTER" ]]; then
  echo "rollback_adapter_required" >&2
  exit 46
fi
python3 -c 'import hashlib,sys; p=sys.argv[1]; expected=sys.argv[2]; observed=hashlib.sha256(open(p,"rb").read()).hexdigest(); raise SystemExit(0 if observed == expected else "rollback adapter digest drift")' "$ROLLBACK_ADAPTER" "$ROLLBACK_ADAPTER_SHA256"
"$ROLLBACK_ADAPTER"
