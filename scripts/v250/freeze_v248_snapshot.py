#!/usr/bin/env python3
"""Materialize or verify the exact V2.48 rollback snapshot from frozen Git objects.

This maintainer tool is deliberately scoped to the recorded V2.48 source
commit and tree.  ``--check`` is read-only.  ``--write`` performs only the
deterministic first-generation snapshot copy under the isolated Legacy Replay
root; it never edits Current owner files or contacts a remote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "23720434b38976c7242735925a3514012283c486"
SOURCE_TREE = "b21f65db96419cef200ce130befa557c5122ce25"
SNAPSHOT_ROOT = Path("references/legacy-replay/generations/V2.48/snapshot")
SOURCE_PATHS = (
    "AGENTS.md",
    ".agents/skills/goal-teams/SKILL.md",
    "SKILL.md",
    "RULES.md",
    "goal-teams.md",
    "agents/openai.yaml",
    "references/compat.md",
    "references/dual-review-protocol.md",
    "references/goal-teams-core-v2.5.md",
    "references/invariants.md",
    "references/profiles/goal-teams-self-release-v2.36.md",
    "references/rules-project-sizing.md",
    "references/rules-specialists.md",
    "references/rules-testing.md",
    "references/test-case-assertion-protocol.md",
    "references/skill-release-simple-protocol.md",
    "references/prompt-cache-manifest.json",
    "scripts/install/package-manifest.txt",
    "subagents/common-developer-instructions.txt",
    "subagents/goal-agent-product-manager.toml",
    "subagents/goal-api-integration-test-designer.toml",
    "subagents/goal-api-integration-test-runner.toml",
    "subagents/goal-backend.toml",
    "subagents/goal-completion-auditor.toml",
    "subagents/goal-docs.toml",
    "subagents/goal-e2e-test-designer.toml",
    "subagents/goal-e2e-test-runner.toml",
    "subagents/goal-frontend.toml",
    "subagents/goal-performance.toml",
    "subagents/goal-product.toml",
    "subagents/goal-qa.toml",
    "subagents/goal-refactor.toml",
    "subagents/goal-requirements-analyst.toml",
    "subagents/goal-reviewer.toml",
    "subagents/goal-security.toml",
    "subagents/goal-sqa.toml",
    "subagents/goal-unit-test-designer.toml",
    "subagents/goal-unit-test-runner.toml",
)


def _git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"git command failed: {' '.join(args)}")
    return result.stdout


def _safe_target(root: Path, source_path: str) -> Path:
    pure = PurePosixPath(source_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"unsafe frozen source path: {source_path}")
    snapshot = (root / SNAPSHOT_ROOT).resolve()
    target = snapshot.joinpath(*pure.parts)
    target.resolve().relative_to(snapshot)
    return target


def materialize(root: Path, *, write: bool) -> dict[str, object]:
    observed_tree = _git_bytes(root, "rev-parse", f"{SOURCE_COMMIT}^{{tree}}").decode().strip()
    if observed_tree != SOURCE_TREE:
        raise RuntimeError(
            f"V2.48 source tree drift: expected {SOURCE_TREE}, observed {observed_tree}"
        )

    entries: list[dict[str, object]] = []
    errors: list[str] = []
    for source_path in SOURCE_PATHS:
        data = _git_bytes(root, "show", f"{SOURCE_COMMIT}:{source_path}")
        target = _safe_target(root, source_path)
        relative = target.relative_to(root).as_posix()
        digest = hashlib.sha256(data).hexdigest()
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".v248-snapshot.tmp")
            temporary.write_bytes(data)
            os.replace(temporary, target)
        if not target.is_file() or target.is_symlink():
            errors.append(f"E_V248_SNAPSHOT_MISSING:{relative}")
            observed = None
        else:
            observed = hashlib.sha256(target.read_bytes()).hexdigest()
            if observed != digest:
                errors.append(f"E_V248_SNAPSHOT_DRIFT:{relative}")
        entries.append(
            {
                "source_path": source_path,
                "path": relative,
                "sha256": digest,
                "bytes": len(data),
                "observed_sha256": observed,
            }
        )
    return {
        "schema_version": "goal-teams-v248-snapshot-freeze-receipt-v1",
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "snapshot_root": SNAPSHOT_ROOT.as_posix(),
        "mode": "write" if write else "check",
        "member_count": len(entries),
        "entries": entries,
        "errors": errors,
        "passed": not errors,
        "external_side_effect_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--write", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    result = materialize(args.repo_root.resolve(), write=args.write)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SNAPSHOT_ROOT",
    "SOURCE_COMMIT",
    "SOURCE_PATHS",
    "SOURCE_TREE",
    "materialize",
]
