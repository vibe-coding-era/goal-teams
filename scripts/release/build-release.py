#!/usr/bin/env python3
"""Build a reproducible release snapshot before any GitHub publication."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_ROOT = ROOT / "release" / "versions"
ARCHIVE_ROOT = ROOT / "docs" / "archive" / "releases"
KNOWN_RELEASES = {
    "V2.33": "codex/v2.33-finalize",
    "V2.34": "codex/v2.34-release",
    "V2.35": "codex/v2.35-release",
    "V2.36": "codex/v2.36",
    "V2.37": "codex/v2.37",
}


def git(*args: str, text: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=text)
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


def manifest_rules(ref: str) -> tuple[set[str], tuple[str, ...], str]:
    content = git("show", f"{ref}:scripts/install/package-manifest.txt")
    assert isinstance(content, bytes)
    files: set[str] = set()
    prefixes: list[str] = []
    for raw in content.decode("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, value = line.split(maxsplit=1)
        if kind == "file":
            files.add(value)
        elif kind == "prefix":
            prefixes.append(value)
        else:
            raise RuntimeError(f"invalid manifest rule in {ref}: {line}")
    return files, tuple(prefixes), sha256(content)


def nonrelease_reason(path: str) -> str | None:
    if path.startswith("docs/"):
        return "repository_docs"
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
    files, prefixes, manifest_sha = manifest_rules(ref)
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

    digest_input = b"".join(f"{r['path']}\0{r['mode']}\0{r['size']}\0{r['sha256']}\n".encode() for r in rows)
    artifact = target / "_artifacts" / f"goal-teams-{version}.tar.gz"
    artifact_sha = deterministic_tar(artifact, version, rows, target)
    record = {
        "schema_version": "goal-teams-release-snapshot-v2",
        "version": version,
        "source_ref": ref,
        "source_commit": commit,
        "source_package_manifest_sha256": manifest_sha,
        "file_count": len(rows),
        "total_bytes": sum(int(r["size"]) for r in rows),
        "tree_sha256": sha256(digest_input),
        "artifact": {"path": artifact.relative_to(target).as_posix(), "sha256": artifact_sha, "size": artifact.stat().st_size},
        "excluded_nonrelease_count": len(excluded),
        "excluded_categories": sorted({str(r["reason"]) for r in excluded}),
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
    parser.add_argument("--version", action="append", help="Version to build, e.g. V2.37")
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
