#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

# Internal GitHub adapter.  V2.40 callers must enter through release.py so the
# operation intent, exact lease and live readback are persisted before marker.
[[ "${GOAL_TEAMS_RELEASE_ORCHESTRATOR:-0}" == "1" ]] || {
  echo "internal adapter: use scripts/release/release.py" >&2
  exit 2
}

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_SLUG="vibe-coding-era/goal-teams"

git_trust_fail() {
  echo "E_V240_GIT_OBJECT_GRAPH: $1" >&2
  exit 1
}

sanitize_git_environment() {
  local name value
  local -a poisoned=()
  while IFS= read -r name; do
    [[ "$name" == GIT_* ]] || continue
    value="${!name-}"
    case "$name" in
      GIT_PAGER)
        ;;
      GIT_NO_REPLACE_OBJECTS|GIT_NO_LAZY_FETCH)
        [[ "$value" == "1" ]] || poisoned+=("$name")
        ;;
      GIT_TERMINAL_PROMPT)
        [[ "$value" == "0" ]] || poisoned+=("$name")
        ;;
      *)
        poisoned+=("$name")
        ;;
    esac
    unset "$name"
  done < <(compgen -e)
  ((${#poisoned[@]} == 0)) || git_trust_fail \
    "caller-controlled Git environment is forbidden: ${poisoned[*]}"
  export GIT_NO_REPLACE_OBJECTS=1
  export GIT_NO_LAZY_FETCH=1
  export GIT_TERMINAL_PROMPT=0
  export LC_ALL=C LANG=C
}

git_fixed() {
  command git --no-replace-objects -c core.hooksPath=/dev/null "$@"
}

resolve_git_admin_path() {
  local value="$1"
  [[ -n "$value" ]] || git_trust_fail "Git administrative path is empty"
  if [[ "$value" = /* ]]; then
    (cd "$value" && pwd -P)
  else
    (cd "$SOURCE_ROOT/$value" && pwd -P)
  fi
}

is_fixed_origin_url() {
  case "$1" in
    "git@github.com:$REPO_SLUG"|"git@github.com:$REPO_SLUG.git"|\
    "ssh://git@github.com/$REPO_SLUG"|"ssh://git@github.com/$REPO_SLUG.git"|\
    "https://github.com/$REPO_SLUG"|"https://github.com/$REPO_SLUG.git")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

require_one_fixed_origin_url() {
  local label="$1" values="$2" value count=0
  while IFS= read -r value; do
    [[ -n "$value" ]] || continue
    is_fixed_origin_url "$value" || git_trust_fail \
      "$label is not the fixed github.com/$REPO_SLUG repository"
    count=$((count + 1))
  done <<<"$values"
  [[ "$count" -eq 1 ]] || git_trust_fail "$label must contain exactly one URL"
}

validate_git_repository() {
  local git_dir raw_common replacements shallow partial rc
  local raw_origin raw_pushurl resolved_fetch resolved_push rewrites root
  local forbidden

  git_dir="$(resolve_git_admin_path "$(git_fixed -C "$SOURCE_ROOT" rev-parse --git-dir)")"
  raw_common="$(git_fixed -C "$SOURCE_ROOT" rev-parse --git-common-dir)"
  COMMON_DIR="$(resolve_git_admin_path "$raw_common")"

  replacements="$(git_fixed -C "$SOURCE_ROOT" for-each-ref --format='%(refname)' refs/replace/)"
  [[ -z "$replacements" ]] || git_trust_fail "Git replacement refs are forbidden"

  for root in "$git_dir" "$COMMON_DIR"; do
    for forbidden in \
      "$root/info/grafts" \
      "$root/objects/info/alternates" \
      "$root/objects/info/http-alternates" \
      "$root/shallow" \
      "$root/shallow.lock"; do
      [[ ! -e "$forbidden" && ! -L "$forbidden" ]] || git_trust_fail \
        "Git graft, alternate, or shallow object source exists"
    done
    if [[ -d "$root/objects/pack" ]] && find "$root/objects/pack" \
      -maxdepth 1 -type f -name '*.promisor' -print -quit | grep -q .; then
      git_trust_fail "partial-clone promisor pack exists"
    fi
  done

  shallow="$(git_fixed -C "$SOURCE_ROOT" rev-parse --is-shallow-repository)"
  [[ "$shallow" == "false" ]] || git_trust_fail "shallow repositories are forbidden"

  if partial="$(git_fixed -C "$SOURCE_ROOT" config --local --includes \
    --name-only --get-regexp \
    '^(extensions\.partialClone|remote\..*\.(promisor|partialclonefilter))$' 2>/dev/null)"; then
    [[ -z "$partial" ]] || git_trust_fail "partial-clone configuration is forbidden"
  else
    rc=$?
    [[ "$rc" -eq 1 ]] || git_trust_fail "cannot inspect partial-clone configuration"
  fi

  if rewrites="$(git_fixed -C "$SOURCE_ROOT" config --show-origin --name-only \
    --get-regexp '^url\.' 2>/dev/null)"; then
    [[ -z "$rewrites" ]] || git_trust_fail "Git URL rewrite configuration is forbidden"
  else
    rc=$?
    [[ "$rc" -eq 1 ]] || git_trust_fail "cannot inspect Git URL rewrites"
  fi

  raw_origin="$(git_fixed -C "$SOURCE_ROOT" config --local --get-all remote.origin.url)" || \
    git_trust_fail "remote.origin.url is missing"
  require_one_fixed_origin_url "remote.origin.url" "$raw_origin"
  if raw_pushurl="$(git_fixed -C "$SOURCE_ROOT" config --local --get-all remote.origin.pushurl)"; then
    require_one_fixed_origin_url "remote.origin.pushurl" "$raw_pushurl"
  else
    rc=$?
    [[ "$rc" -eq 1 ]] || git_trust_fail "cannot inspect remote.origin.pushurl"
  fi
  resolved_fetch="$(git_fixed -C "$SOURCE_ROOT" remote get-url --all origin)" || \
    git_trust_fail "cannot resolve origin fetch URL"
  resolved_push="$(git_fixed -C "$SOURCE_ROOT" remote get-url --push --all origin)" || \
    git_trust_fail "cannot resolve origin push URL"
  require_one_fixed_origin_url "resolved origin fetch URL" "$resolved_fetch"
  require_one_fixed_origin_url "resolved origin push URL" "$resolved_push"
}

sanitize_git_environment
COMMON_DIR=""
validate_git_repository
WORKSPACE_ROOT="$(cd "$(dirname "$COMMON_DIR")" && pwd -P)"
VERSION="${1:?usage: publish-github-release.sh VERSION COMMIT create-draft|publish|download}"
COMMIT="${2:?missing frozen commit}"
ACTION="${3:?missing adapter action}"
[[ "$VERSION" =~ ^V[0-9]+\.[0-9]+$ ]] || { echo "invalid VERSION: $VERSION" >&2; exit 2; }
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "commit must be 40 lowercase hex" >&2; exit 2; }
[[ "$ACTION" =~ ^(create-draft|publish|download)$ ]] || { echo "invalid action: $ACTION" >&2; exit 2; }

DIR="$WORKSPACE_ROOT/release/versions/$VERSION"
TAG="v${VERSION#V}"
PYTHON_BIN="${PYTHON:-python3}"
RECORD_COMMIT="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_commit"])' "$DIR/_release.json")"
[[ "$RECORD_COMMIT" == "$COMMIT" ]] || { echo "release record commit mismatch" >&2; exit 1; }

command -v gh >/dev/null || { echo "gh is required" >&2; exit 2; }
[[ "${GH_HOST:-github.com}" == "github.com" ]] || { echo "GH_HOST must be github.com" >&2; exit 1; }
export GH_HOST=github.com
REPO="github.com/$REPO_SLUG"
gh auth status --hostname github.com >/dev/null
OBSERVED_REPO="$(gh repo view "$REPO" --json nameWithOwner -q .nameWithOwner)"
[[ "$OBSERVED_REPO" == "$REPO_SLUG" ]] || { echo "unexpected repository: $OBSERVED_REPO" >&2; exit 1; }

TAG_COMMIT="$(git_fixed -C "$SOURCE_ROOT" ls-remote origin "refs/tags/$TAG^{}" | awk '{print $1}')"
[[ "$TAG_COMMIT" == "$COMMIT" ]] || { echo "remote annotated tag does not peel to candidate commit" >&2; exit 1; }

ASSET_TAR="$DIR/_artifacts/goal-teams-$VERSION.tar.gz"
ASSET_SUMS="$DIR/_artifacts/SHA256SUMS"
ASSET_RELEASE="$DIR/_release.json"
ASSET_FILES="$DIR/_files.sha256"
for asset in "$ASSET_TAR" "$ASSET_SUMS" "$ASSET_RELEASE" "$ASSET_FILES"; do
  [[ -f "$asset" && ! -L "$asset" ]] || { echo "missing/nonregular asset: $asset" >&2; exit 1; }
done

download_and_verify() {
  local expected_state="${1:-either}"
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  gh release view "$TAG" --repo "$REPO" \
    --json databaseId,isDraft,isImmutable,tagName,assets >"$tmp/release.json"
  "$PYTHON_BIN" - "$tmp/release.json" "$TAG" "$expected_state" \
    "goal-teams-$VERSION.tar.gz" SHA256SUMS _release.json _files.sha256 <<'PY'
import json
import sys

path, expected_tag, expected_state, *expected_assets = sys.argv[1:]
release = json.load(open(path, encoding="utf-8"))
observed_assets = [asset.get("name") for asset in release.get("assets", [])]
if release.get("tagName") != expected_tag:
    raise SystemExit("release tag identity mismatch")
if sorted(observed_assets) != sorted(expected_assets):
    raise SystemExit(
        f"release asset set mismatch: expected={sorted(expected_assets)!r} "
        f"observed={sorted(observed_assets)!r}"
    )
if expected_state == "draft" and release.get("isDraft") is not True:
    raise SystemExit("release is not a Draft")
if expected_state == "published" and (
    release.get("isDraft") is not False or release.get("isImmutable") is not True
):
    raise SystemExit("release is not published and immutable")
PY
  if [[ "$expected_state" == "published" ]]; then
    local release_id latest_id
    release_id="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["databaseId"])' "$tmp/release.json")"
    latest_id="$(gh api "repos/$REPO_SLUG/releases/latest" --hostname github.com --jq .id)"
    [[ "$release_id" == "$latest_id" ]] || {
      echo "published release is not GitHub Latest" >&2
      return 1
    }
  fi
  gh release download "$TAG" --repo "$REPO" --dir "$tmp" \
    --pattern "goal-teams-$VERSION.tar.gz" \
    --pattern SHA256SUMS \
    --pattern _release.json \
    --pattern _files.sha256
  cmp "$ASSET_TAR" "$tmp/goal-teams-$VERSION.tar.gz"
  cmp "$ASSET_SUMS" "$tmp/SHA256SUMS"
  cmp "$ASSET_RELEASE" "$tmp/_release.json"
  cmp "$ASSET_FILES" "$tmp/_files.sha256"
  (cd "$tmp" && shasum -a 256 -c SHA256SUMS)
  rm -rf "$tmp"
  trap - RETURN
}

case "$ACTION" in
  create-draft)
    "$PYTHON_BIN" "$SOURCE_ROOT/scripts/release/validate-release.py" --version "$VERSION"
    if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
      IS_DRAFT="$(gh release view "$TAG" --repo "$REPO" --json isDraft -q .isDraft)"
      [[ "$IS_DRAFT" == "true" ]] || { echo "existing release is already published" >&2; exit 1; }
    else
      gh release create "$TAG" \
        "$ASSET_TAR" "$ASSET_SUMS" "$ASSET_RELEASE" "$ASSET_FILES" \
        --repo "$REPO" --verify-tag --target "$COMMIT" --draft \
        --title "Goal Teams $VERSION" \
        --notes "Goal Teams $VERSION. See release/current/README.md in the tagged source."
    fi
    download_and_verify draft
    ;;
  publish)
    IS_DRAFT="$(gh release view "$TAG" --repo "$REPO" --json isDraft -q .isDraft)"
    if [[ "$IS_DRAFT" == "true" ]]; then
      # Publish-last: the Draft must already have the fixed exact asset set and
      # byte-identical local assets before the immutable transition.
      download_and_verify draft
      gh release edit "$TAG" --repo "$REPO" --draft=false --latest
    fi
    download_and_verify published
    ;;
  download)
    download_and_verify
    ;;
esac

gh release view "$TAG" --repo "$REPO" \
  --json databaseId,isDraft,isImmutable,tagName,targetCommitish,publishedAt,assets,url
