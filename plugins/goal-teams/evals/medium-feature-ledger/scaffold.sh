#!/usr/bin/env bash
# medium-feature-ledger：把 fixture/ 复制进空工作区，建 git 仓库并提交两次（有一点历史）。
# claude plugin eval 以 `bash <本脚本在用例目录中的真实路径>` 运行，cwd 是空工作区，
# 所以用例目录就是 "$(dirname "$0")"。只用 PATH 上的 git，不联网，不读全局配置。
set -euo pipefail

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURE="$CASE_DIR/fixture"
if [ ! -d "$FIXTURE" ]; then
  echo "scaffold: fixture directory not found: $FIXTURE" >&2
  exit 1
fi

commit() {
  GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" \
    git -c user.name=eval -c user.email=eval@example.invalid -c commit.gpgsign=false \
    commit -q -m "$2"
}

cp -R "$FIXTURE"/. .
find . -name '__pycache__' -type d -prune -exec rm -rf {} +

git init -q -b main
mkdir -p .git/info && echo ".eval-artifacts" >> .git/info/exclude  # CLI 保留名，不进仓库
git add .gitignore inventory/__init__.py inventory/models.py inventory/store.py \
  tests/__init__.py tests/test_store.py data/sample-inventory.json
commit "2026-08-03T09:30:00+08:00" "feat: 库存数据模型、JSON 存储与老数据样例"
git add -A
commit "2026-08-10T15:00:00+08:00" "feat: 命令行 add/adjust/list"
