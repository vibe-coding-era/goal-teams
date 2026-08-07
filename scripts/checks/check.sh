#!/usr/bin/env bash
set -euo pipefail

export PYTHONDONTWRITEBYTECODE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PHASE="development"
PROJECT_SIZE="medium"
CHECK_MODE="source"
SOURCE_COMMIT=""
SOURCE_TREE=""
RELEASED_RUNTIME_RECEIPT=""
EXPECTED_HOST_EXECUTION_ID=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --installed-package)
      CHECK_MODE="installed-package"
      shift
      ;;
    --phase)
      PHASE="${2:-}"
      shift 2
      ;;
    --project-size)
      PROJECT_SIZE="${2:-}"
      shift 2
      ;;
    --source-commit)
      SOURCE_COMMIT="${2:-}"
      shift 2
      ;;
    --source-tree)
      SOURCE_TREE="${2:-}"
      shift 2
      ;;
    --released-runtime-receipt)
      RELEASED_RUNTIME_RECEIPT="${2:-}"
      shift 2
      ;;
    --expected-host-execution-id)
      EXPECTED_HOST_EXECUTION_ID="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: scripts/check.sh [--installed-package] [--phase development|release] [--project-size small|medium|large] [--source-commit SHA] [--source-tree SHA] [--released-runtime-receipt PATH] [--expected-host-execution-id ID]" >&2
      exit 2
      ;;
  esac
done

if [[ "$PHASE" != "development" && "$PHASE" != "release" ]]; then
  echo "Invalid phase: $PHASE" >&2
  exit 2
fi
if [[ "$PROJECT_SIZE" != "small" && "$PROJECT_SIZE" != "medium" && "$PROJECT_SIZE" != "large" ]]; then
  echo "Invalid project size: $PROJECT_SIZE" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.11+ is required." >&2
  exit 2
fi

if [[ "$(<VERSION)" != "V2.6" ]]; then
  echo "This Current checker only accepts VERSION=V2.6." >&2
  exit 2
fi

"$PYTHON_BIN" scripts/checks/validate-v250-generation.py --generation-id V2.6
"$PYTHON_BIN" scripts/checks/validate-v250-test-gate.py --self-test
"$PYTHON_BIN" scripts/checks/check-package-manifest.py
"$PYTHON_BIN" scripts/v250/generate_subagents.py --check

if [[ "$PHASE" == "development" ]]; then
  "$PYTHON_BIN" -m unittest discover -s tests/v250 -p 'test_*.py'
  "$PYTHON_BIN" scripts/checks/check-v250.py \
    --phase development \
    --project-size "$PROJECT_SIZE" \
    --stage candidate
  echo "Goal Teams V2.6 development checks passed (${CHECK_MODE})."
  exit 0
fi

if [[ -z "$SOURCE_COMMIT" || -z "$SOURCE_TREE" || -z "$RELEASED_RUNTIME_RECEIPT" || -z "$EXPECTED_HOST_EXECUTION_ID" ]]; then
  echo "Release phase requires --source-commit, --source-tree, --released-runtime-receipt, and --expected-host-execution-id." >&2
  exit 2
fi

"$PYTHON_BIN" scripts/checks/check-v250.py \
  --phase release \
  --project-size "$PROJECT_SIZE" \
  --stage released \
  --release-intent \
  --implementation-scope-complete \
  --source-commit "$SOURCE_COMMIT" \
  --source-tree "$SOURCE_TREE" \
  --expected-host-execution-id "$EXPECTED_HOST_EXECUTION_ID" \
  --released-runtime-receipt "$RELEASED_RUNTIME_RECEIPT"

echo "Goal Teams V2.6 final regression and release security review passed (${CHECK_MODE})."
