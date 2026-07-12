#!/usr/bin/env python3
"""Validate local release snapshots before GitHub publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_ROOT = ROOT / "release" / "versions"
META = {"_release.json", "_files.sha256", "_artifacts/SHA256SUMS"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def source_entries(commit: str) -> dict[str, tuple[str, bytes]]:
    result: dict[str, tuple[str, bytes]] = {}
    for raw in git_bytes("ls-tree", "-r", "-z", commit).split(b"\0"):
        if not raw:
            continue
        metadata, path_raw = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        if kind == "blob":
            result[path_raw.decode()] = (mode, git_bytes("cat-file", "blob", object_id))
    return result


def excluded(path: str) -> bool:
    return path.startswith(("docs/", "GoalTeamsWork-", "GoalTeams-PRD-", "outputs/", ".goalteams-", ".codex/"))


def trusted_release_files(commit: str) -> tuple[dict[str, tuple[str, bytes]], str]:
    entries = source_entries(commit)
    manifest = entries["scripts/install/package-manifest.txt"][1]
    exact: set[str] = set()
    prefixes: list[str] = []
    for raw in manifest.decode().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, value = line.split(maxsplit=1)
        if kind == "file": exact.add(value)
        elif kind == "prefix": prefixes.append(value)
        else: raise RuntimeError(f"invalid source manifest rule: {line}")
    selected = {p: entries[p] for p in entries if (p in exact or any(p.startswith(x) for x in prefixes)) and not excluded(p)}
    return selected, hashlib.sha256(manifest).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="append", help="Version to validate; default: every local version")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    versions = args.version or sorted(p.name for p in RELEASE_ROOT.glob("V*") if p.is_dir())
    errors: list[str] = []
    results: list[dict[str, object]] = []
    for version in versions:
        if not re.fullmatch(r"V[0-9]+\.[0-9]+", version):
            errors.append(f"invalid release version: {version}")
            continue
        root = RELEASE_ROOT / version
        record_path, checksum_path = root / "_release.json", root / "_files.sha256"
        if not record_path.is_file() or not checksum_path.is_file():
            errors.append(f"{version}: release metadata missing")
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("version") != version or (root / "VERSION").read_text(encoding="utf-8").strip() != version:
            errors.append(f"{version}: version mismatch")
        current_manifest = root / "release" / "current" / "manifest.json"
        if not current_manifest.is_file():
            errors.append(f"{version}: current release manifest missing")
        else:
            current = json.loads(current_manifest.read_text(encoding="utf-8"))
            if current.get("product_version") != version or current.get("status") != "release":
                errors.append(f"{version}: current release manifest is not final")
        source_ref = str(record.get("source_ref"))
        resolved = subprocess.run(["git", "rev-parse", f"{source_ref}^{{commit}}"], cwd=ROOT, text=True, capture_output=True)
        if resolved.returncode or resolved.stdout.strip() != record.get("source_commit"):
            errors.append(f"{version}: source ref missing or commit drifted")

        listed = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            expected_hash, relative = line.split("  ", 1)
            if relative in listed:
                errors.append(f"{version}: duplicate checksum path {relative}")
            listed[relative] = expected_hash
        files = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file() and not p.relative_to(root).as_posix().startswith("_artifacts/") and p.name not in META}
        mismatches = [path for path, file in files.items() if listed.get(path) != digest(file)]
        if set(files) != set(listed): errors.append(f"{version}: file manifest mismatch")
        if mismatches: errors.append(f"{version}: file hash mismatch {mismatches}")
        forbidden = [p for p in files if excluded(p)]
        if forbidden: errors.append(f"{version}: nonrelease paths present {forbidden}")

        if resolved.returncode == 0:
            commit = resolved.stdout.strip()
            trusted, manifest_sha = trusted_release_files(commit)
            if set(trusted) != set(files):
                errors.append(f"{version}: release files differ from source allowlist")
            source_mismatches = [p for p, (_, data) in trusted.items() if p not in files or hashlib.sha256(data).hexdigest() != digest(files[p])]
            if source_mismatches:
                errors.append(f"{version}: files differ from frozen Git source {source_mismatches}")
            rows = [{"path": p, "mode": mode, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for p, (mode, data) in sorted(trusted.items())]
            tree_input = b"".join(f"{r['path']}\0{r['mode']}\0{r['size']}\0{r['sha256']}\n".encode() for r in rows)
            expected_record = {
                "source_package_manifest_sha256": manifest_sha,
                "file_count": len(rows),
                "total_bytes": sum(int(r["size"]) for r in rows),
                "tree_sha256": hashlib.sha256(tree_input).hexdigest(),
            }
            for key, expected in expected_record.items():
                if record.get(key) != expected:
                    errors.append(f"{version}: metadata {key} is not bound to frozen source")

        artifact_info = record.get("artifact", {})
        expected_artifact_path = f"_artifacts/goal-teams-{version}.tar.gz"
        if artifact_info.get("path") != expected_artifact_path:
            errors.append(f"{version}: artifact path must be {expected_artifact_path}")
        artifact = root / expected_artifact_path
        artifact_ok = artifact.is_file() and digest(artifact) == artifact_info.get("sha256") and artifact.stat().st_size == artifact_info.get("size")
        if not artifact_ok:
            errors.append(f"{version}: artifact metadata/hash mismatch")
        sums = root / "_artifacts" / "SHA256SUMS"
        expected_sum = f"{artifact_info.get('sha256')}  {artifact.name}\n"
        if not sums.is_file() or sums.read_text(encoding="utf-8") != expected_sum:
            errors.append(f"{version}: SHA256SUMS mismatch")
        tar_paths: set[str] = set()
        if artifact.is_file():
            prefix = f"goal-teams-{version}/"
            seen_members: set[str] = set()
            try:
                with tarfile.open(artifact, "r:gz") as archive:
                    for member in archive.getmembers():
                        if not member.isfile() or not member.name.startswith(prefix) or ".." in Path(member.name).parts:
                            errors.append(f"{version}: unsafe/non-file tar member {member.name}")
                            continue
                        relative = member.name[len(prefix):]
                        if relative in seen_members:
                            errors.append(f"{version}: duplicate tar member {relative}")
                        seen_members.add(relative)
                        tar_paths.add(relative)
                        stream = archive.extractfile(member)
                        if stream is None or hashlib.sha256(stream.read()).hexdigest() != listed.get(relative):
                            errors.append(f"{version}: tar content mismatch {relative}")
                if tar_paths != set(listed): errors.append(f"{version}: tar manifest mismatch")
            except tarfile.TarError as exc:
                errors.append(f"{version}: invalid tar archive: {exc}")
        archive_index = ROOT / "docs" / "archive" / "releases" / version / "archive-index.json"
        if not archive_index.is_file():
            errors.append(f"{version}: root docs archive missing")
        else:
            archive_record = json.loads(archive_index.read_text(encoding="utf-8"))
            if archive_record.get("source_commit") != record.get("source_commit") or archive_record.get("source_ref") != source_ref:
                errors.append(f"{version}: docs archive source binding mismatch")
            archive_root = archive_index.parent / "repository-docs"
            archive_listed = archive_record.get("files", [])
            archive_paths: set[str] = set()
            for item in archive_listed:
                path = str(item.get("path", ""))
                if path in archive_paths:
                    errors.append(f"{version}: duplicate docs archive path {path}")
                archive_paths.add(path)
                file = archive_root / path
                if not file.is_file() or file.stat().st_size != item.get("size") or digest(file) != item.get("sha256"):
                    errors.append(f"{version}: docs archive content mismatch {path}")
            actual_archive = {p.relative_to(archive_root).as_posix() for p in archive_root.rglob("*") if p.is_file()}
            if actual_archive != archive_paths or archive_record.get("file_count") != len(archive_paths):
                errors.append(f"{version}: docs archive manifest mismatch")
            if resolved.returncode == 0:
                expected_archive = {p: data for p, (_, data) in source_entries(resolved.stdout.strip()).items() if excluded(p)}
                if set(expected_archive) != archive_paths:
                    errors.append(f"{version}: docs archive differs from frozen Git exclusions")
                archive_source_mismatches = [p for p, data in expected_archive.items() if not (archive_root / p).is_file() or hashlib.sha256(data).hexdigest() != digest(archive_root / p)]
                if archive_source_mismatches:
                    errors.append(f"{version}: docs archive differs from frozen Git source {archive_source_mismatches}")
        results.append({"version": version, "files": len(files), "hash_mismatches": len(mismatches), "forbidden": len(forbidden), "artifact_ok": artifact_ok})
    payload = {"schema_version": "goal-teams-release-validation-v2", "passed": not errors, "versions": results, "errors": errors}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
