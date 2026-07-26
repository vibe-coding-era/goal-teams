#!/bin/bash
set -euo pipefail

VERIFY_ADAPTER={{VERIFY_ADAPTER_Q}}
VERIFY_ADAPTER_SHA256={{VERIFY_ADAPTER_SHA256_Q}}
export GOAL_TEAMS_RELEASE_PLAN_PATH={{PLAN_PATH_Q}}
export GOAL_TEAMS_RELEASE_PLAN_DIGEST={{PLAN_DIGEST_Q}}

if [[ -z "$VERIFY_ADAPTER" || ! -f "$VERIFY_ADAPTER" || -L "$VERIFY_ADAPTER" ]]; then
  echo "post_release_verify_adapter_required" >&2
  exit 45
fi
python3 -c 'import hashlib,sys; p=sys.argv[1]; expected=sys.argv[2]; observed=hashlib.sha256(open(p,"rb").read()).hexdigest(); raise SystemExit(0 if observed == expected else "verify adapter digest drift")' "$VERIFY_ADAPTER" "$VERIFY_ADAPTER_SHA256"
"$VERIFY_ADAPTER"
