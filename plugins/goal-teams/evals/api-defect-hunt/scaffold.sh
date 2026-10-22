#!/usr/bin/env bash
# api-defect-hunt：把预埋缺陷的订单服务（fixture/）复制进空工作区，建 git 仓库并提交一次。
# claude plugin eval 以 `bash <本脚本在用例目录中的真实路径>` 运行，cwd 是空工作区，
# 所以用例目录就是 "$(dirname "$0")"。不启动服务、不联网；服务由被测 agent 自己在本机起。
set -euo pipefail

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURE="$CASE_DIR/fixture"
if [ ! -d "$FIXTURE" ]; then
  echo "scaffold: fixture directory not found: $FIXTURE" >&2
  exit 1
fi

cp -R "$FIXTURE"/. .
find . -name '__pycache__' -type d -prune -exec rm -rf {} +

export GIT_AUTHOR_DATE="2026-09-15T14:00:00+08:00"
export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"
git init -q -b main
mkdir -p .git/info && echo ".eval-artifacts" >> .git/info/exclude  # CLI 保留名，不进仓库
git add -A
git -c user.name=eval -c user.email=eval@example.invalid -c commit.gpgsign=false \
  commit -q -m "feat: 订单服务（认证、幂等创建、查询）与控制台页面"
