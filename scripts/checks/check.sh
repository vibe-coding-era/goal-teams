#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON_CANDIDATES=()
if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_CANDIDATES+=("$PYTHON")
fi
PYTHON_CANDIDATES+=(python3.13 python3.12 python3.11 python3)

PYTHON_BIN=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" - <<'PY' >/dev/null 2>&1; then
import tomllib
PY
    PYTHON_BIN="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "No Python with tomllib found. Install Python 3.11+ or set PYTHON to a compatible interpreter." >&2
  exit 2
fi

"$PYTHON_BIN" scripts/checks/validate.py
"$PYTHON_BIN" scripts/checks/check-version-sync.py
"$PYTHON_BIN" scripts/checks/check-agent-names.py
"$PYTHON_BIN" scripts/checks/check-member-layout.py
"$PYTHON_BIN" scripts/harness/validate-harness.py --self-test
"$PYTHON_BIN" scripts/harness/pixel-diff.py --self-test
"$PYTHON_BIN" scripts/review/compare-artifacts.py --self-test
"$PYTHON_BIN" scripts/review/validate-dual-review.py --self-test
"$PYTHON_BIN" scripts/benchmark/benchmark-runner.py --check-only
