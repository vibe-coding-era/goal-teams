#!/usr/bin/env bash
# direct-slugify-fix：把 fixture/ 复制进空工作区，建 git 仓库并提交一次。
# claude plugin eval 以 `bash <本脚本在用例目录中的真实路径>` 运行，cwd 是空工作区，
# 所以用例目录就是 "$(dirname "$0")"。只用 PATH 上的 git，不联网，不读全局配置。
set -euo pipefail

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURE="$CASE_DIR/fixture"
if [ ! -d "$FIXTURE" ]; then
  echo "scaffold: fixture directory not found: $FIXTURE" >&2
  exit 1
fi

cp -R "$FIXTURE"/. .
find . -name '__pycache__' -type d -prune -exec rm -rf {} +

export GIT_AUTHOR_DATE="2026-09-01T10:00:00+08:00"
export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"
git init -q -b main
mkdir -p .git/info && echo ".eval-artifacts" >> .git/info/exclude  # CLI 保留名，不进仓库
git add -A
git -c user.name=eval -c user.email=eval@example.invalid -c commit.gpgsign=false \
  commit -q -m "feat: textkit slugify"
