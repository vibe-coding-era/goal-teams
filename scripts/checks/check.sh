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
"$PYTHON_BIN" scripts/checks/check-routing-fixtures.py
"$PYTHON_BIN" scripts/checks/check-agent-names.py
"$PYTHON_BIN" scripts/checks/check-member-layout.py
"$PYTHON_BIN" scripts/checks/check-context-budget.py
"$PYTHON_BIN" scripts/checks/check-security-fixtures.py
"$PYTHON_BIN" scripts/checks/validate-test-case-contract.py --self-test
if [[ -f .github/workflows/check.yml ]]; then
  "$PYTHON_BIN" scripts/checks/check-ci-pins.py
fi
"$PYTHON_BIN" scripts/harness/validate-harness.py --self-test
"$PYTHON_BIN" scripts/harness/pixel-diff.py --self-test
"$PYTHON_BIN" scripts/review/compare-artifacts.py --self-test
"$PYTHON_BIN" scripts/review/validate-dual-review.py --self-test
GOAL_TEAMS_INSTALL_VALIDATION=1 "$PYTHON_BIN" scripts/checks/check-v23.py
"$PYTHON_BIN" scripts/benchmark/benchmark-runner.py --check-only
if [[ "${GOAL_TEAMS_INSTALL_VALIDATION:-0}" != "1" ]]; then
  "$PYTHON_BIN" scripts/checks/check-install-lifecycle.py
fi
