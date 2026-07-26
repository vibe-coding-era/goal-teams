#!/bin/bash
set -euo pipefail

ARTIFACT_PATH={{ARTIFACT_PATH_Q}}
ARTIFACT_SHA256={{ARTIFACT_SHA256_Q}}

test -f "$ARTIFACT_PATH"
test ! -L "$ARTIFACT_PATH"
python3 -c 'import hashlib,sys; p=sys.argv[1]; expected=sys.argv[2]; observed=hashlib.sha256(open(p,"rb").read()).hexdigest(); raise SystemExit(0 if observed == expected else "artifact digest drift")' "$ARTIFACT_PATH" "$ARTIFACT_SHA256"
