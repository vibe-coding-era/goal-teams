#!/bin/bash
set -euo pipefail

PROJECT_ROOT={{PROJECT_ROOT_Q}}
RELEASE_RUN_ROOT={{RELEASE_RUN_ROOT_Q}}

test -d "$PROJECT_ROOT"
test -d "$RELEASE_RUN_ROOT"
test ! -L "$RELEASE_RUN_ROOT"
{{REQUIRED_FILE_CHECKS}}

echo "preflight_ok"
