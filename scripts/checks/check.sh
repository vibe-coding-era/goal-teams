#!/usr/bin/env bash
set -euo pipefail

export PYTHONDONTWRITEBYTECODE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if SOURCE_COMMIT="$(git rev-parse HEAD 2>/dev/null)"; then
  echo "Goal Teams source commit: $SOURCE_COMMIT"
else
  echo "Goal Teams source commit: unavailable"
fi

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
"$PYTHON_BIN" scripts/checks/check-version-sync.py --mode development --published-version V2.40
"$PYTHON_BIN" scripts/checks/check-v241-flow.py
"$PYTHON_BIN" scripts/checks/check-workspace-boundaries.py
"$PYTHON_BIN" scripts/checks/check-routing-fixtures.py
"$PYTHON_BIN" scripts/checks/check-agent-names.py
"$PYTHON_BIN" scripts/checks/check-member-layout.py
"$PYTHON_BIN" scripts/checks/check-prompt-cache.py
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  "$PYTHON_BIN" scripts/checks/check-okf.py --root "$ROOT" --tracked
  "$PYTHON_BIN" scripts/checks/check-okf.py --root "$ROOT" --preview-package-manifest
else
  "$PYTHON_BIN" scripts/checks/check-okf.py --root "$ROOT" --package-tree "$ROOT"
fi
"$PYTHON_BIN" scripts/checks/check-okf.py --root "$ROOT" --bundle-root examples/canonical-v23
"$PYTHON_BIN" scripts/checks/check-okf.py --root "$ROOT" --bundle-root examples/mini-goal-run/.codex/goal-teams
"$PYTHON_BIN" scripts/checks/check-context-budget.py
"$PYTHON_BIN" scripts/checks/check-progressive-loading.py
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
