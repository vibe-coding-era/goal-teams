#!/bin/bash
set -euo pipefail

DEPLOY_ADAPTER={{DEPLOY_ADAPTER_Q}}
DEPLOY_ADAPTER_SHA256={{DEPLOY_ADAPTER_SHA256_Q}}
export GOAL_TEAMS_RELEASE_PLAN_PATH={{PLAN_PATH_Q}}
export GOAL_TEAMS_RELEASE_PLAN_DIGEST={{PLAN_DIGEST_Q}}

if [[ -z "$DEPLOY_ADAPTER" || ! -f "$DEPLOY_ADAPTER" || -L "$DEPLOY_ADAPTER" ]]; then
  echo "deploy_adapter_required" >&2
  exit 44
fi
python3 -c 'import hashlib,sys; p=sys.argv[1]; expected=sys.argv[2]; observed=hashlib.sha256(open(p,"rb").read()).hexdigest(); raise SystemExit(0 if observed == expected else "deploy adapter digest drift")' "$DEPLOY_ADAPTER" "$DEPLOY_ADAPTER_SHA256"
"$DEPLOY_ADAPTER"
