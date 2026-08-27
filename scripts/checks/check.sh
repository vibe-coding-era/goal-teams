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
ROUTE_FACTS_RECEIPT=""
DERIVED_ROUTE_RECEIPT=""
ROUTE_RECEIPT=""
AUTHORIZATION_RECEIPT=""

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
    --route-facts-receipt)
      ROUTE_FACTS_RECEIPT="${2:-}"
      shift 2
      ;;
    --derived-route-receipt)
      DERIVED_ROUTE_RECEIPT="${2:-}"
      shift 2
      ;;
    --route-receipt)
      ROUTE_RECEIPT="${2:-}"
      shift 2
      ;;
    --authorization-receipt)
      AUTHORIZATION_RECEIPT="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: scripts/check.sh [--installed-package] [--phase development|release] [--project-size small|medium|large] [--source-commit SHA] [--source-tree SHA] [--released-runtime-receipt PATH] [--expected-host-execution-id ID] [--route-facts-receipt PATH] [--derived-route-receipt PATH] [--route-receipt PATH] [--authorization-receipt PATH]" >&2
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

PRODUCT_VERSION="$(<VERSION)"

if [[ "$PRODUCT_VERSION" == "V2.66" ]]; then
  CANDIDATE_ACTIVATION="references/current/generations/V2.66/activation-manifest.json"
  CANDIDATE_SHA256="$(shasum -a 256 "$CANDIDATE_ACTIVATION" | awk '{print $1}')"
  ACTIVE_GENERATION="$($PYTHON_BIN -c 'import json; print(json.load(open("references/current/ACTIVE.json"))["generation_id"])')"
  if [[ "$ACTIVE_GENERATION" == "V2.66" ]]; then
    "$PYTHON_BIN" scripts/checks/validate-v250-generation.py \
      --generation-id V2.66 \
      --selection active
  else
    "$PYTHON_BIN" scripts/checks/validate-v250-generation.py \
      --generation-id V2.66 \
      --selection candidate \
      --expected-activation-sha256 "$CANDIDATE_SHA256"
  fi
  "$PYTHON_BIN" scripts/checks/validate-v250-test-gate.py --self-test
  if [[ "$ACTIVE_GENERATION" == "V2.66" ]]; then
    "$PYTHON_BIN" scripts/checks/check-package-manifest.py
  else
    "$PYTHON_BIN" scripts/checks/check-package-manifest.py \
      --candidate-generation V2.66 \
      --activation-sha256 "$CANDIDATE_SHA256"
  fi
  "$PYTHON_BIN" scripts/v250/generate_subagents.py --check
  "$PYTHON_BIN" scripts/v266/project_host_assets.py --check
  if [[ "$PHASE" == "release" ]]; then
    if [[ -z "$SOURCE_COMMIT" || -z "$SOURCE_TREE" || -z "$RELEASED_RUNTIME_RECEIPT" || -z "$EXPECTED_HOST_EXECUTION_ID" || -z "$ROUTE_FACTS_RECEIPT" || -z "$DERIVED_ROUTE_RECEIPT" || -z "$ROUTE_RECEIPT" || -z "$AUTHORIZATION_RECEIPT" ]]; then
      echo "Release phase requires --source-commit, --source-tree, --released-runtime-receipt, --expected-host-execution-id, --route-facts-receipt, --derived-route-receipt, --route-receipt, and --authorization-receipt." >&2
      exit 2
    fi
    "$PYTHON_BIN" scripts/checks/check-v266.py \
      --phase release \
      --project-size "$PROJECT_SIZE" \
      --stage released \
      --release-intent \
      --implementation-scope-complete \
      --source-commit "$SOURCE_COMMIT" \
      --source-tree "$SOURCE_TREE" \
      --expected-host-execution-id "$EXPECTED_HOST_EXECUTION_ID" \
      --released-runtime-receipt "$RELEASED_RUNTIME_RECEIPT" \
      --route-facts-receipt "$ROUTE_FACTS_RECEIPT" \
      --derived-route-receipt "$DERIVED_ROUTE_RECEIPT" \
      --route-receipt "$ROUTE_RECEIPT" \
      --authorization-receipt "$AUTHORIZATION_RECEIPT"
    echo "Goal Teams V2.66 S0/S1 passed; Release control remains incomplete until S2-boundary-S3-S4 plan closure."
    exit 0
  fi
  "$PYTHON_BIN" -m unittest -v \
    tests.v250.test_output_contract \
    tests.v250.test_v251_small_iteration.TestV251SmallIteration.test_every_loop_requires_current_and_total_iteration \
    tests.v250.test_v251_small_iteration.TestV251SmallIteration.test_final_output_requires_loop_improvement_suggestions \
    tests.v250.test_v263_output_contract \
    tests.v266.test_output_contract \
    tests.v266.test_release_gate_denominator \
    tests.v266.test_release_manifest_closure \
    tests.v266.test_release_runtime_transition \
    tests.v266.test_s4_workflow_contract \
    tests.v266.test_version_candidate
  echo "Goal Teams V2.66 affected Development checks passed (${CHECK_MODE}); Release is not_run."
  exit 0
fi

if [[ "$PRODUCT_VERSION" != "V2.65" ]]; then
  echo "This checker only accepts the V2.66 Current flow or the exact V2.65 predecessor helper." >&2
  exit 2
fi

"$PYTHON_BIN" scripts/checks/validate-v250-generation.py --generation-id V2.65 --selection active
"$PYTHON_BIN" scripts/checks/validate-v250-test-gate.py --self-test
"$PYTHON_BIN" scripts/checks/check-package-manifest.py
"$PYTHON_BIN" scripts/v250/generate_subagents.py --check

if [[ "$PHASE" == "development" ]]; then
  "$PYTHON_BIN" -m unittest discover -s tests/v250 -p 'test_*.py'
  "$PYTHON_BIN" -m unittest discover -s tests/v265 -p 'test_*.py'
  "$PYTHON_BIN" scripts/checks/check-v250.py \
    --phase development \
    --project-size "$PROJECT_SIZE" \
    --stage candidate
  echo "Goal Teams V2.65 development checks passed (${CHECK_MODE})."
  exit 0
fi

if [[ -z "$SOURCE_COMMIT" || -z "$SOURCE_TREE" || -z "$RELEASED_RUNTIME_RECEIPT" || -z "$EXPECTED_HOST_EXECUTION_ID" || -z "$ROUTE_FACTS_RECEIPT" || -z "$DERIVED_ROUTE_RECEIPT" || -z "$ROUTE_RECEIPT" || -z "$AUTHORIZATION_RECEIPT" ]]; then
  echo "Release phase requires --source-commit, --source-tree, --released-runtime-receipt, --expected-host-execution-id, --route-facts-receipt, --derived-route-receipt, --route-receipt, and --authorization-receipt." >&2
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
  --released-runtime-receipt "$RELEASED_RUNTIME_RECEIPT" \
  --route-facts-receipt "$ROUTE_FACTS_RECEIPT" \
  --derived-route-receipt "$DERIVED_ROUTE_RECEIPT" \
  --route-receipt "$ROUTE_RECEIPT" \
  --authorization-receipt "$AUTHORIZATION_RECEIPT"

echo "Goal Teams V2.65 final regression and release security review passed (${CHECK_MODE})."
