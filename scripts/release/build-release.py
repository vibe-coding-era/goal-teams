#!/usr/bin/env python3
"""Build a reproducible release snapshot before any GitHub publication."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=SOURCE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = (SOURCE_ROOT / common).resolve()
    return common.parent


WORKSPACE_ROOT = workspace_root()
RELEASE_ROOT = WORKSPACE_ROOT / "release" / "versions"
ARCHIVE_ROOT = WORKSPACE_ROOT / "docs" / "archive" / "releases"
KNOWN_RELEASES = {
    "V2.33": "codex/v2.33-finalize",
    "V2.34": "codex/v2.34-release",
    "V2.35": "codex/v2.35-release",
    "V2.36": "codex/v2.36",
    "V2.37": "codex/v2.37",
    "V2.38": "codex/v2.38",
    "V2.39": "codex/v2.39",
}
OKF_GENERATED_PATH = "references/okf-conformance-manifest.json"


def git(*args: str, text: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=SOURCE_ROOT, check=True, capture_output=True, text=text)
    return result.stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree(ref: str) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    raw = git("ls-tree", "-r", "-z", ref)
    assert isinstance(raw, bytes)
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path_raw = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split(" ")
        if kind == "blob":
            rows[path_raw.decode("utf-8")] = (mode, object_id)
    return rows


def blob(object_id: str) -> bytes:
    value = git("cat-file", "blob", object_id)
    assert isinstance(value, bytes)
    return value


def safe_manifest_path(value: str) -> str:
    normalized = value.rstrip("/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RuntimeError(f"unsafe package manifest path: {value}")
    return normalized


def manifest_rules(ref: str) -> tuple[set[str], tuple[str, ...], set[str], str]:
    content = git("show", f"{ref}:scripts/install/package-manifest.txt")
    assert isinstance(content, bytes)
    files: set[str] = set()
    prefixes: list[str] = []
    generated: set[str] = set()
    for raw in content.decode("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, value = line.split(maxsplit=1)
        if kind == "file":
            if value.endswith("/"):
                raise RuntimeError(f"invalid file rule in {ref}: {line}")
            files.add(safe_manifest_path(value))
        elif kind == "prefix":
            if not value.endswith("/"):
                raise RuntimeError(f"invalid prefix rule in {ref}: {line}")
            safe_manifest_path(value)
            prefixes.append(value)
        elif kind == "generated":
            if value.endswith("/"):
                raise RuntimeError(f"invalid generated rule in {ref}: {line}")
            generated.add(safe_manifest_path(value))
        else:
            raise RuntimeError(f"invalid manifest rule in {ref}: {line}")
    if generated and generated != {OKF_GENERATED_PATH}:
        raise RuntimeError(f"unsupported generated package assets in {ref}: {sorted(generated)}")
    return files, tuple(prefixes), generated, sha256(content)


def nonrelease_reason(path: str) -> str | None:
    if path.startswith("docs/"):
        return "repository_docs"
    if path.startswith("develops/"):
        return "development_workspace"
    if path.startswith("GoalTeamsWork-"):
        return "process_bundle"
    if path.startswith((".codex/", ".goalteams-", "outputs/")):
        return "local_process_state"
    if path.startswith("GoalTeams-PRD-"):
        return "product_knowledge"
    return None


def write_file(target: Path, data: bytes, mode: str) -> None:
    if mode not in {"100644", "100755"}:
        raise RuntimeError(f"unsupported release file mode {mode}: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o755 if mode == "100755" else 0o644)


def generate_okf_manifest(
    target: Path,
    *,
    commit: str,
    git_tree_id: str,
    package_manifest_sha256: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Generate and replay the sole V2.39 staged package asset."""

    runtime_path = target / "scripts" / "v23" / "okf_conformance.py"
    checker_path = target / "scripts" / "checks" / "check-okf.py"
    if not runtime_path.is_file() or runtime_path.is_symlink() or not checker_path.is_file():
        raise RuntimeError("V2.39 OKF runtime/checker is missing from the staged payload")
    module_name = f"_goalteams_release_okf_{commit[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, runtime_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load staged V2.39 OKF runtime")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    policy = module.load_policy(target)
    manifest = module.build_package_manifest(
        target,
        policy,
        source_binding={
            "commit_sha256": commit,
            "git_tree_id": git_tree_id,
            "package_manifest_sha256": package_manifest_sha256,
        },
    )
    if (
        manifest.get("manifest_scope") != "installed_package_complete"
        or manifest.get("source", {}).get("commit_sha256") != commit
        or manifest.get("source", {}).get("git_tree_id") != git_tree_id
        or manifest.get("source", {}).get("package_manifest_sha256")
        != package_manifest_sha256
    ):
        raise RuntimeError("generated OKF manifest did not bind the frozen source")
    data = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    output = target / OKF_GENERATED_PATH
    write_file(output, data, "100644")

    replay = subprocess.run(
        [
            sys.executable,
            str(checker_path),
            "--root",
            str(target),
            "--package-tree",
            str(target),
        ],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        replay_payload = json.loads(replay.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("staged OKF package-tree replay did not emit JSON") from exc
    if (
        replay.returncode != 0
        or replay_payload.get("passed") is not True
        or replay_payload.get("package_completeness_state") != "complete"
    ):
        raise RuntimeError(
            "staged OKF package-tree replay failed: "
            + json.dumps(replay_payload, ensure_ascii=False, sort_keys=True)
        )
    row: dict[str, object] = {
        "path": OKF_GENERATED_PATH,
        "mode": "100644",
        "size": len(data),
        "sha256": sha256(data),
    }
    summary: dict[str, object] = {
        "manifest_path": OKF_GENERATED_PATH,
        "manifest_sha256": row["sha256"],
        "payload_tree_sha256": manifest["package"]["payload_tree_sha256"],
        "policy_sha256": manifest["policy"]["sha256"],
        "checker_bindings": manifest["checkers"],
        "package_completeness_state": "complete",
    }
    return row, summary


def deterministic_tar(target: Path, version: str, rows: list[dict[str, object]], root: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for row in rows:
            relative = str(row["path"])
            data = (root / relative).read_bytes()
            info = tarfile.TarInfo(f"goal-teams-{version}/{relative}")
            info.size = len(data)
            info.mode = 0o755 if row["mode"] == "100755" else 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(data))
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(buffer.getvalue())
    return hashlib.sha256(target.read_bytes()).hexdigest()


def build(version: str, ref: str) -> dict[str, object]:
    if not re.fullmatch(r"V[0-9]+\.[0-9]+", version):
        raise RuntimeError(f"invalid release version: {version}")
    commit = str(git("rev-parse", f"{ref}^{{commit}}", text=True)).strip()
    entries = tree(ref)
    forbidden_source = [path for path in entries if nonrelease_reason(path)]
    if forbidden_source:
        raise RuntimeError(f"source tree contains nonrelease paths: {forbidden_source}")
    files, prefixes, generated, manifest_sha = manifest_rules(ref)
    if version == "V2.39" and generated != {OKF_GENERATED_PATH}:
        raise RuntimeError("V2.39 requires exactly one generated OKF conformance manifest")
    tracked_generated = sorted(generated & set(entries))
    if tracked_generated:
        raise RuntimeError(
            f"builder-generated assets must not be tracked in frozen source: {tracked_generated}"
        )
    selected = sorted(path for path in entries if path in files or any(path.startswith(p) for p in prefixes))
    excluded = [{"path": path, "reason": nonrelease_reason(path)} for path in selected if nonrelease_reason(path)]
    release_paths = [path for path in selected if not nonrelease_reason(path)]

    target = RELEASE_ROOT / version
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for path in release_paths:
        mode, object_id = entries[path]
        data = blob(object_id)
        write_file(target / path, data, mode)
        rows.append({"path": path, "mode": mode, "size": len(data), "sha256": sha256(data)})
    if (target / "VERSION").read_text(encoding="utf-8").strip() != version:
        raise RuntimeError(f"{ref}: VERSION does not equal requested {version}")

    generated_rows: list[dict[str, object]] = []
    okf_summary: dict[str, object] | None = None
    if generated:
        git_tree_id = str(git("rev-parse", f"{commit}^{{tree}}", text=True)).strip()
        generated_row, okf_summary = generate_okf_manifest(
            target,
            commit=commit,
            git_tree_id=git_tree_id,
            package_manifest_sha256=manifest_sha,
        )
        rows.append(generated_row)
        generated_rows.append(generated_row)
    rows.sort(key=lambda row: str(row["path"]))

    digest_input = b"".join(f"{r['path']}\0{r['mode']}\0{r['size']}\0{r['sha256']}\n".encode() for r in rows)
    artifact = target / "_artifacts" / f"goal-teams-{version}.tar.gz"
    artifact_sha = deterministic_tar(artifact, version, rows, target)
    record = {
        "schema_version": "goal-teams-release-snapshot-v2",
        "version": version,
        "source_ref": ref,
        "source_commit": commit,
        "source_git_tree_id": str(git("rev-parse", f"{commit}^{{tree}}", text=True)).strip(),
        "source_package_manifest_sha256": manifest_sha,
        "file_count": len(rows),
        "total_bytes": sum(int(r["size"]) for r in rows),
        "tree_sha256": sha256(digest_input),
        "artifact": {"path": artifact.relative_to(target).as_posix(), "sha256": artifact_sha, "size": artifact.stat().st_size},
        "excluded_nonrelease_count": len(excluded),
        "excluded_categories": sorted({str(r["reason"]) for r in excluded}),
        "builder_generated_files": generated_rows,
        "okf_conformance": okf_summary,
    }
    (target / "_release.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "_files.sha256").write_text("".join(f"{r['sha256']}  {r['path']}\n" for r in rows), encoding="utf-8")
    (target / "_artifacts" / "SHA256SUMS").write_text(f"{artifact_sha}  {artifact.name}\n", encoding="utf-8")

    archive = ARCHIVE_ROOT / version / "repository-docs"
    if archive.exists():
        shutil.rmtree(archive)
    archive.mkdir(parents=True)
    archive_rows = []
    for path, (mode, object_id) in sorted(entries.items()):
        reason = nonrelease_reason(path)
        if not reason:
            continue
        data = blob(object_id)
        write_file(archive / path, data, mode)
        archive_rows.append({"path": path, "reason": reason, "size": len(data), "sha256": sha256(data)})
    (ARCHIVE_ROOT / version / "archive-index.json").write_text(json.dumps({
        "schema_version": "goal-teams-release-doc-archive-v1", "version": version,
        "source_ref": ref, "source_commit": commit, "file_count": len(archive_rows),
        "files": archive_rows, "manifest_exclusions": excluded,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="append", help="Version to build, e.g. V2.38")
    parser.add_argument("--ref", help="Explicit Git ref; valid with exactly one --version")
    parser.add_argument("--all-known", action="store_true", help="Build every known historical release")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all_known:
        if args.version or args.ref:
            raise SystemExit("--all-known cannot be combined with --version/--ref")
        releases = KNOWN_RELEASES
    else:
        versions = args.version or []
        if not versions:
            raise SystemExit("use --version VERSION [--ref REF] or --all-known")
        if args.ref and len(versions) != 1:
            raise SystemExit("--ref requires exactly one --version")
        releases = {v: args.ref or KNOWN_RELEASES.get(v, f"codex/{v.lower()}") for v in versions}
    RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    built = [build(version, ref) for version, ref in releases.items()]
    existing = []
    for path in sorted(RELEASE_ROOT.glob("V*")):
        meta = path / "_release.json"
        if meta.is_file():
            existing.append(json.loads(meta.read_text(encoding="utf-8")))
    (RELEASE_ROOT / "index.json").write_text(json.dumps({"schema_version": "goal-teams-release-index-v2", "releases": existing}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"built": built}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
