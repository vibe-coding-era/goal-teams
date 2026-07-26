#!/bin/bash
set -euo pipefail
TOOLCHAIN_HOST={{TOOLCHAIN_HOST_Q}}
TOOLCHAIN_HOST_SHA256={{TOOLCHAIN_HOST_SHA256_Q}}
TOOLCHAIN_ACTION={{TOOLCHAIN_BUILD_ACTION_Q}}
PREFETCH_RECEIPT={{TOOLCHAIN_PREFETCH_RECEIPT_Q}}
TOOLCHAIN_RECEIPT={{TOOLCHAIN_BUILD_RECEIPT_Q}}
ACTION_MANIFEST_SHA256={{TOOLCHAIN_ACTION_MANIFEST_SHA256_Q}}
export GOAL_TEAMS_RELEASE_PROJECT_ROOT={{PROJECT_ROOT_Q}}
export GOAL_TEAMS_RELEASE_DEPENDENCY_BUNDLE={{DEPENDENCY_BUNDLE_Q}}
export GOAL_TEAMS_RELEASE_DEPENDENCY_REQUIREMENTS={{DEPENDENCY_REQUIREMENTS_Q}}
export GOAL_TEAMS_RELEASE_ARTIFACT_PATH={{ARTIFACT_PATH_Q}}
export GOAL_TEAMS_RELEASE_PLAN_PATH={{PLAN_PATH_Q}}
export GOAL_TEAMS_RELEASE_PLAN_DIGEST={{PLAN_DIGEST_Q}}
export GOAL_TEAMS_RELEASE_PREFETCH_RECEIPT="$PREFETCH_RECEIPT"
export GOAL_TEAMS_RELEASE_TOOLCHAIN_RECEIPT="$TOOLCHAIN_RECEIPT"
/usr/bin/python3 -c 'import hashlib,sys; p=sys.argv[1]; expected=sys.argv[2]; observed=hashlib.sha256(open(p,"rb").read()).hexdigest(); raise SystemExit(0 if observed == expected else "toolchain host digest drift")' "$TOOLCHAIN_HOST" "$TOOLCHAIN_HOST_SHA256"
/bin/rm -f -- "$TOOLCHAIN_RECEIPT"
"$TOOLCHAIN_HOST" "$TOOLCHAIN_ACTION"
/usr/bin/python3 -c 'import json,sys; prefetch_path,build_path,action,plan,host,manifest,execution,artifact=sys.argv[1:]; p=json.load(open(prefetch_path,encoding="utf-8")); d=json.load(open(build_path,encoding="utf-8")); fields={"action_id","action_manifest_sha256","artifact_digest","dependency_bundle_digest","execution_id","full_test_execution_count","host_attestation","host_executable_sha256","network_policy","observed_at","plan_digest","schema_version","status"}; digest=lambda v:isinstance(v,str) and len(v)==64 and all(c in "0123456789abcdef" for c in v); ok=set(d)==fields and d["schema_version"]=="goal-teams-toolchain-action-receipt-v2.45" and d["action_id"]==action and d["status"]=="passed" and d["execution_id"]==execution and d["plan_digest"]==plan and d["host_executable_sha256"]==host and d["action_manifest_sha256"]==manifest and d["network_policy"]=="offline_required" and d["full_test_execution_count"]==0 and digest(d["dependency_bundle_digest"]) and d["dependency_bundle_digest"]==p.get("dependency_bundle_digest") and d["artifact_digest"]==artifact and isinstance(d["host_attestation"],dict) and isinstance(d["observed_at"],str) and bool(d["observed_at"]); raise SystemExit(0 if ok else "invalid toolchain build receipt")' "$PREFETCH_RECEIPT" "$TOOLCHAIN_RECEIPT" "$TOOLCHAIN_ACTION" "$GOAL_TEAMS_RELEASE_PLAN_DIGEST" "$TOOLCHAIN_HOST_SHA256" "$ACTION_MANIFEST_SHA256" "$GOAL_TEAMS_RELEASE_EXECUTION_ID" {{ARTIFACT_SHA256_Q}}
