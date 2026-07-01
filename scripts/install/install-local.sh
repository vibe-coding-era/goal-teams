#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
SKILL_TARGET="$CODEX_HOME/skills/goal-teams"
AGENT_TARGET="$CODEX_HOME/agents"
UPDATE_TEAM_FALLBACK=0

for arg in "$@"; do
  case "$arg" in
    --update-team-fallback) UPDATE_TEAM_FALLBACK=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$CODEX_HOME/skills" "$AGENT_TARGET"
rsync -a --delete \
  --exclude='/.git/' \
  --exclude='/.codex/' \
  --exclude='/outputs/' \
  --exclude='/design.md' \
  --exclude='/ai-coding-harness.md' \
  --exclude='/references/skill-authoring-guide.md' \
  "$ROOT/" "$SKILL_TARGET/"
cp "$ROOT"/subagents/goal-*.toml "$AGENT_TARGET/"

if [[ "$UPDATE_TEAM_FALLBACK" == "1" ]]; then
  fallback_files=(
    "team-implementer.toml"
    "team-qa.toml"
    "team-researcher.toml"
    "team-reviewer.toml"
  )
  for file in "${fallback_files[@]}"; do
    case "$file" in
      "team-implementer.toml") replacement='nickname_candidates = ["实现-功能开发", "实现-修复任务", "实现-集成改造"]' ;;
      "team-qa.toml") replacement='nickname_candidates = ["测试-E2E 验证", "测试-回归检查", "测试-验收证据"]' ;;
      "team-researcher.toml") replacement='nickname_candidates = ["调研-代码路径分析", "调研-资料证据收集", "调研-上下文梳理"]' ;;
      "team-reviewer.toml") replacement='nickname_candidates = ["评审-代码审查", "评审-一致性复核", "评审-风险边界检查"]' ;;
    esac
    path="$AGENT_TARGET/$file"
    [[ -f "$path" ]] || continue
    cp "$path" "$path.bak-v192"
    python3 - "$path" "$replacement" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
replacement = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
updated = [replacement if line.startswith("nickname_candidates = ") else line for line in lines]
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
  done
fi

(cd "$SKILL_TARGET" && ./scripts/check.sh)
echo "Installed goal-teams to $SKILL_TARGET"
