#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:?usage: publish-github-release.sh VERSION}"
[[ "$VERSION" =~ ^V[0-9]+\.[0-9]+$ ]] || { echo "invalid VERSION: $VERSION" >&2; exit 1; }
DIR="$ROOT/release/versions/$VERSION"
TAG="v${VERSION#V}"

"$ROOT/scripts/check.sh"
python3 "$ROOT/scripts/release/validate-release.py" --version "$VERSION"
command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
gh auth status >/dev/null
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  echo "GitHub Release $TAG already exists; refusing to overwrite" >&2
  exit 1
fi

COMMIT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_commit"])' "$DIR/_release.json")"
if git -C "$ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  test "$(git -C "$ROOT" rev-list -n 1 "$TAG")" = "$COMMIT" || { echo "$TAG points to a different commit" >&2; exit 1; }
else
  git -C "$ROOT" tag -a "$TAG" "$COMMIT" -m "Goal Teams $VERSION"
fi
git -C "$ROOT" push origin "refs/tags/$TAG"
gh release create "$TAG" \
  "$DIR/_artifacts/goal-teams-$VERSION.tar.gz" \
  "$DIR/_artifacts/SHA256SUMS" \
  "$DIR/_release.json" "$DIR/_files.sha256" \
  --verify-tag --title "Goal Teams $VERSION" --generate-notes

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
gh release download "$TAG" --pattern "goal-teams-$VERSION.tar.gz" --pattern SHA256SUMS --dir "$TMP"
cmp "$DIR/_artifacts/SHA256SUMS" "$TMP/SHA256SUMS"
(cd "$TMP" && shasum -a 256 -c SHA256SUMS)

EVIDENCE="$ROOT/docs/archive/releases/$VERSION/release-evidence"
mkdir -p "$EVIDENCE"
gh release view "$TAG" --json url,tagName,targetCommitish,publishedAt,assets > "$EVIDENCE/github-release.json"
"$ROOT/scripts/install-local.sh" --update-team-fallback 2>&1 | tee "$EVIDENCE/local-install.log"
python3 - "$VERSION" "$COMMIT" "$TAG" "$DIR/_artifacts/SHA256SUMS" "$EVIDENCE/post-release.json" <<'PY'
import datetime, hashlib, json, pathlib, sys
version, commit, tag, sums_path, output = sys.argv[1:]
sums = pathlib.Path(sums_path).read_bytes()
payload = {
    "schema_version": "goal-teams-post-release-v1",
    "version": version,
    "source_commit": commit,
    "tag": tag,
    "sha256sums_sha256": hashlib.sha256(sums).hexdigest(),
    "published_asset_identity": "passed",
    "local_install_command": "scripts/install-local.sh --update-team-fallback",
    "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
pathlib.Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
PY
echo "published, downloaded, installed, and verified: $TAG"
