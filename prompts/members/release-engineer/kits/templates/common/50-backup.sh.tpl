#!/bin/bash
set -euo pipefail

BACKUP_REQUIRED={{BACKUP_REQUIRED_Q}}
BACKUP_ADAPTER={{BACKUP_ADAPTER_Q}}
BACKUP_ADAPTER_SHA256={{BACKUP_ADAPTER_SHA256_Q}}
export GOAL_TEAMS_RELEASE_PLAN_PATH={{PLAN_PATH_Q}}
export GOAL_TEAMS_RELEASE_PLAN_DIGEST={{PLAN_DIGEST_Q}}

if [[ "$BACKUP_REQUIRED" != "true" ]]; then
  echo "backup_not_applicable"
  exit 0
fi
if [[ -z "$BACKUP_ADAPTER" || ! -f "$BACKUP_ADAPTER" || -L "$BACKUP_ADAPTER" ]]; then
  echo "backup_adapter_required" >&2
  exit 42
fi
python3 -c 'import hashlib,sys; p=sys.argv[1]; expected=sys.argv[2]; observed=hashlib.sha256(open(p,"rb").read()).hexdigest(); raise SystemExit(0 if observed == expected else "backup adapter digest drift")' "$BACKUP_ADAPTER" "$BACKUP_ADAPTER_SHA256"
"$BACKUP_ADAPTER"
