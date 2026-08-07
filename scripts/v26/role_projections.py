"""Project and verify thin host-role assets from V2.6 canonical role metadata."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


PLAN_PATH = Path("references/compatibility/v2.6/role-projections.json")


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("E_V26_PROJECTION_PATH_INVALID")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("E_V26_PROJECTION_PATH_INVALID")
    return value


def _load_plan(root: Path) -> dict[str, Any]:
    try:
        plan = json.loads((root / PLAN_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("E_V26_PROJECTION_PLAN_INVALID") from exc
    if not isinstance(plan, dict) or plan.get("schema_version") != "goal-teams-compatibility-v2.6-role-projections-v1":
        raise ValueError("E_V26_PROJECTION_PLAN_INVALID")
    if not isinstance(plan.get("roles"), list) or not isinstance(plan.get("portable_core_ref"), str):
        raise ValueError("E_V26_PROJECTION_PLAN_INVALID")
    return plan


def _render(target: dict[str, Any], role: dict[str, Any], portable_core_ref: str) -> str:
    canonical_ref, path, format_name, role_id = _safe_path(role.get("canonical_ref")), _safe_path(target.get("path")), target.get("format"), role.get("role_id")
    if not isinstance(role_id, str) or not role_id:
        raise ValueError("E_V26_PROJECTION_ROLE_INVALID")
    if format_name == "toml":
        return f'name = "{role_id}"\ndescription = "V2.6 thin compatibility projection for {role_id}"\ncanonical_ref = "{canonical_ref}"\nportable_core_ref = "{portable_core_ref}"\n'
    if format_name == "markdown":
        return f"---\ntype: Goal Teams Host Role Projection\ntitle: V2.6 {role_id} Claude Code Projection\ndescription: Thin Claude Code projection for the canonical {role_id} compatibility role.\ntimestamp: 2026-08-07T00:00:00+08:00\nokf_version: \"0.1\"\nname: {role_id}\ncanonical_ref: {canonical_ref}\nportable_core_ref: {portable_core_ref}\n---\n\n# {role_id}\n\nThin V2.6 host projection; canonical role content is loaded from `canonical_ref`.\n"
    raise ValueError(f"E_V26_PROJECTION_FORMAT:{path}")


def _expected(root: Path) -> dict[str, str]:
    plan, expected = _load_plan(root), {}
    portable_core_ref = _safe_path(plan["portable_core_ref"])
    for role in plan["roles"]:
        if not isinstance(role, dict) or not isinstance(role.get("targets"), list):
            raise ValueError("E_V26_PROJECTION_ROLE_INVALID")
        for target in role["targets"]:
            if not isinstance(target, dict):
                raise ValueError("E_V26_PROJECTION_TARGET_INVALID")
            path = _safe_path(target.get("path"))
            if path in expected:
                raise ValueError("E_V26_PROJECTION_TARGET_DUPLICATE")
            expected[path] = _render(target, role, portable_core_ref)
    return expected


def project_role_projections(root: Path | str) -> dict[str, Any]:
    root_path, expected = Path(root), _expected(Path(root))
    for relative, rendered in expected.items():
        path = root_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    return {"projected_paths": sorted(expected), "digest": hashlib.sha256("".join(expected.values()).encode("utf-8")).hexdigest()}


def check_role_projections(root: Path | str) -> dict[str, Any]:
    root_path, expected, errors = Path(root), _expected(Path(root)), []
    actual_candidates: set[str] = set()
    managed_directories = {
        ((root_path / relative).parent, Path(relative).suffix)
        for relative in expected
    }
    for parent, suffix in managed_directories:
        if parent.is_dir():
            actual_candidates.update(path.relative_to(root_path).as_posix() for path in parent.glob(f"*{suffix}") if path.is_file())
    for relative, rendered in expected.items():
        path = root_path / relative
        if not path.is_file(): errors.append("E_V26_PROJECTION_MISSING")
        elif path.read_text(encoding="utf-8") != rendered: errors.append("E_V26_PROJECTION_DRIFT")
    if actual_candidates - set(expected): errors.append("E_V26_PROJECTION_ORPHAN")
    return {"ok": not errors, "errors": sorted(set(errors)), "projected_paths": sorted(expected)}
