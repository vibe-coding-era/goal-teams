#!/usr/bin/env python3
"""Fail closed when Goal Teams work or release data escapes its directory contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_ONLY = ("docs", "develops", "release/versions")
SOURCE_FORBIDDEN = (*LOCAL_ONLY, "GoalTeamsWork-*", "GoalTeams-PRD-*", "outputs", ".codex", ".goalteams-state", ".goalteams-candidates", ".goalteams-quarantine")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)


def check_manifest() -> None:
    manifest = (ROOT / "scripts/install/package-manifest.txt").read_text(encoding="utf-8")
    for path in LOCAL_ONLY:
        if f"file {path}" in manifest or f"prefix {path.rstrip('/')}/" in manifest:
            fail(f"package manifest includes local-only path: {path}")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for marker in ("/docs/", "/develops/", "/release/versions/"):
        if marker not in ignore:
            fail(f".gitignore missing local-only boundary: {marker}")


def check_git_boundaries() -> None:
    probe = run_git("rev-parse", "--git-common-dir")
    if probe.returncode != 0:
        for path in LOCAL_ONLY:
            if (ROOT / path).exists():
                fail(f"gitless package contains local-only path: {path}")
        return
    tracked = run_git("ls-files", "--", *SOURCE_FORBIDDEN)
    if tracked.returncode != 0:
        fail("cannot inspect tracked local-only paths")
    if tracked.stdout.strip():
        fail(f"nonrelease paths are tracked: {tracked.stdout.strip().splitlines()}")
    common = Path(probe.stdout.strip())
    if not common.is_absolute():
        common = (ROOT / common).resolve()
    canonical_root = common.resolve().parent
    allowed_develops = canonical_root / "develops"
    worktrees = run_git("worktree", "list", "--porcelain")
    if worktrees.returncode != 0:
        fail("cannot inspect Git worktree topology")
    for line in worktrees.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):]).resolve()
            if path != canonical_root and allowed_develops not in path.parents:
                fail(f"worktree escapes repository develops/: {path}")
    siblings = sorted(path for path in canonical_root.parent.glob(f"{canonical_root.name}-*") if path.is_dir())
    if siblings:
        fail(f"Goal Teams version directories exist outside repository: {siblings}")


def main() -> None:
    check_manifest()
    check_git_boundaries()
    print("Workspace boundaries passed: worktrees in develops; docs/develops excluded from Git and package.")


if __name__ == "__main__":
    main()
