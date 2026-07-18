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
import tempfile
from pathlib import Path, PurePosixPath

SOURCE_ROOT = Path(__file__).resolve().parents[2]

_SAFE_GIT_ENV = {
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
_INERT_GIT_ENV = frozenset({"GIT_PAGER"})


class V240GitTrustError(RuntimeError):
    """Reject a caller-controlled or incomplete Git object graph."""

    def __init__(self, message: str) -> None:
        self.receipt = {
            "passed": False,
            "error_code": "E_V240_GIT_OBJECT_GRAPH",
            "mutation_count": 0,
            "external_side_effect_count": 0,
        }
        super().__init__(f"E_V240_GIT_OBJECT_GRAPH: {message}")


def _git_environment() -> dict[str, str]:
    """Return a closed Git environment after rejecting redirection inputs."""

    poisoned = sorted(
        key
        for key, value in os.environ.items()
        if key.startswith("GIT_")
        and key not in _INERT_GIT_ENV
        and (key not in _SAFE_GIT_ENV or value != _SAFE_GIT_ENV[key])
    )
    if poisoned:
        raise V240GitTrustError(
            "caller-controlled Git environment is forbidden: "
            + ",".join(poisoned)
        )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(_SAFE_GIT_ENV)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    return environment


def _run_git(
    *args: str,
    text: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    """Run one fixed Git command with replace objects and lazy fetch disabled."""

    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=SOURCE_ROOT,
        check=False,
        capture_output=True,
        text=text,
        env=_git_environment(),
    )
    if check and result.returncode != 0:
        result.check_returncode()
    return result


def _resolve_git_admin_path(value: str) -> Path:
    if not value:
        raise V240GitTrustError("Git administrative path is empty")
    path = Path(value)
    if not path.is_absolute():
        path = SOURCE_ROOT / path
    return path.resolve()


def _assert_trusted_git_repository() -> None:
    """Reject object substitution, omission, and external object sources."""

    git_dir_result = _run_git("rev-parse", "--git-dir", text=True)
    common_result = _run_git("rev-parse", "--git-common-dir", text=True)
    assert isinstance(git_dir_result.stdout, str)
    assert isinstance(common_result.stdout, str)
    git_dir = _resolve_git_admin_path(git_dir_result.stdout.strip())
    common_dir = _resolve_git_admin_path(common_result.stdout.strip())

    replacements = _run_git(
        "for-each-ref",
        "--format=%(refname)",
        "refs/replace/",
        text=True,
    )
    assert isinstance(replacements.stdout, str)
    if replacements.stdout.strip():
        raise V240GitTrustError("Git replacement refs are forbidden")

    for administrative_root in {git_dir, common_dir}:
        forbidden_paths = (
            administrative_root / "info" / "grafts",
            administrative_root / "objects" / "info" / "alternates",
            administrative_root / "objects" / "info" / "http-alternates",
            administrative_root / "shallow",
            administrative_root / "shallow.lock",
        )
        if any(path.exists() or path.is_symlink() for path in forbidden_paths):
            raise V240GitTrustError(
                "Git graft, alternate, or shallow object source exists"
            )
        pack_root = administrative_root / "objects" / "pack"
        if pack_root.is_dir() and any(pack_root.glob("*.promisor")):
            raise V240GitTrustError("partial-clone promisor pack exists")

    shallow = _run_git("rev-parse", "--is-shallow-repository", text=True)
    assert isinstance(shallow.stdout, str)
    if shallow.stdout.strip() != "false":
        raise V240GitTrustError("shallow repositories are forbidden")

    configuration = _run_git(
        "config",
        "--local",
        "--includes",
        "--name-only",
        "--list",
        text=True,
    )
    assert isinstance(configuration.stdout, str)
    risky_names = {
        line.strip().lower()
        for line in configuration.stdout.splitlines()
        if line.strip()
    }
    if any(
        name == "extensions.partialclone"
        or (name.startswith("remote.") and name.endswith(".promisor"))
        or (name.startswith("remote.") and name.endswith(".partialclonefilter"))
        for name in risky_names
    ):
        raise V240GitTrustError("partial-clone configuration is forbidden")


def workspace_root() -> Path:
    try:
        result = _run_git("rev-parse", "--git-common-dir", text=True, check=False)
    except OSError:
        return SOURCE_ROOT
    # Pure manifest helpers are imported by the Gitless installed-package
    # regression suite.  Actual build operations still fail closed on their
    # first immutable Git object read.
    if result.returncode != 0:
        return SOURCE_ROOT
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
    "V2.40": "codex/v2.40",
}
OKF_GENERATED_PATH = "references/okf-conformance-manifest.json"
FROZEN_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class V240FilesManifestError(RuntimeError):
    """A stable, zero-effect receipt for malformed V2.40 file manifests."""

    def __init__(self, message: str) -> None:
        self.receipt = {
            "passed": False,
            "error_code": "E_V240_FILES_MANIFEST_COLUMNS",
            "mutation_count": 0,
            "external_side_effect_count": 0,
        }
        super().__init__(f"E_V240_FILES_MANIFEST_COLUMNS: {message}")


def format_v240_files_manifest(rows: list[dict[str, object]]) -> str:
    """Serialize the frozen V2.40 checksum/mode/size/path contract."""

    output: list[str] = []
    seen: set[str] = set()
    for row in rows:
        digest = row.get("sha256")
        mode = row.get("mode")
        size = row.get("size")
        path_value = row.get("path")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or mode not in {"100644", "100755"}
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(path_value, str)
        ):
            raise V240FilesManifestError("row does not match sha256, mode, size, path")
        try:
            path_value = safe_manifest_path(path_value)
        except RuntimeError as exc:
            raise V240FilesManifestError(str(exc)) from exc
        if path_value in seen:
            raise V240FilesManifestError(f"duplicate path: {path_value}")
        seen.add(path_value)
        output.append(f"{digest}\t{mode}\t{size}\t{path_value}\n")
    return "".join(output)


def git(*args: str, text: bool = False) -> bytes | str:
    _assert_trusted_git_repository()
    result = _run_git(*args, text=text)
    return result.stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_frozen_commit(value: str) -> str:
    """Accept only an immutable, canonical commit object identity."""

    if not FROZEN_COMMIT_RE.fullmatch(value):
        raise RuntimeError("release input must be a 40-character lowercase commit SHA")
    kind = str(git("cat-file", "-t", value, text=True)).strip()
    if kind != "commit":
        raise RuntimeError(f"release input is not a commit object: {value} ({kind})")
    return value


def tree(commit: str) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    raw = git("ls-tree", "-r", "-z", commit)
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


def manifest_rules(commit: str) -> tuple[set[str], tuple[str, ...], set[str], str]:
    content = git("show", f"{commit}:scripts/install/package-manifest.txt")
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
                raise RuntimeError(f"invalid file rule in {commit}: {line}")
            files.add(safe_manifest_path(value))
        elif kind == "prefix":
            if not value.endswith("/"):
                raise RuntimeError(f"invalid prefix rule in {commit}: {line}")
            safe_manifest_path(value)
            prefixes.append(value)
        elif kind == "generated":
            if value.endswith("/"):
                raise RuntimeError(f"invalid generated rule in {commit}: {line}")
            generated.add(safe_manifest_path(value))
        else:
            raise RuntimeError(f"invalid manifest rule in {commit}: {line}")
    if generated and generated != {OKF_GENERATED_PATH}:
        raise RuntimeError(f"unsupported generated package assets in {commit}: {sorted(generated)}")
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
    """Generate and replay the canonical staged OKF package asset."""

    runtime_path = target / "scripts" / "v23" / "okf_conformance.py"
    checker_path = target / "scripts" / "checks" / "check-okf.py"
    if not runtime_path.is_file() or runtime_path.is_symlink() or not checker_path.is_file():
        raise RuntimeError("OKF runtime/checker is missing from the staged payload")
    module_name = f"_goalteams_release_okf_{commit[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, runtime_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load staged OKF runtime")
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
    # GNU longname records keep long paths deterministic without trusting PAX
    # `path` overrides, which the validator and Gitless installer reject.
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
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


def build(
    version: str,
    commit: str,
    *,
    source_ref: str | None = None,
    release_root: Path = RELEASE_ROOT,
    archive_root: Path | None = ARCHIVE_ROOT,
) -> dict[str, object]:
    """Build and atomically seal one snapshot from an immutable commit.

    ``source_ref`` is display-only provenance.  Every Git read is bound to the
    validated commit SHA so a branch moving during the build cannot change the
    output.  An existing version directory is a seal and is never overwritten.
    """

    if not re.fullmatch(r"V[0-9]+\.[0-9]+", version):
        raise RuntimeError(f"invalid release version: {version}")
    commit = require_frozen_commit(commit)
    entries = tree(commit)
    forbidden_source = [path for path in entries if nonrelease_reason(path)]
    if forbidden_source:
        raise RuntimeError(f"source tree contains nonrelease paths: {forbidden_source}")
    files, prefixes, generated, manifest_sha = manifest_rules(commit)
    if version in {"V2.39", "V2.40"} and generated != {OKF_GENERATED_PATH}:
        raise RuntimeError(
            f"{version} requires exactly one generated OKF conformance manifest"
        )
    tracked_generated = sorted(generated & set(entries))
    if tracked_generated:
        raise RuntimeError(
            f"builder-generated assets must not be tracked in frozen source: {tracked_generated}"
        )
    selected = sorted(path for path in entries if path in files or any(path.startswith(p) for p in prefixes))
    excluded = [{"path": path, "reason": nonrelease_reason(path)} for path in selected if nonrelease_reason(path)]
    release_paths = [path for path in selected if not nonrelease_reason(path)]

    release_root.mkdir(parents=True, exist_ok=True)
    target = release_root / version
    if target.exists():
        raise RuntimeError(f"sealed release snapshot already exists: {target}")

    stage = Path(tempfile.mkdtemp(prefix=f".tmp-{version}-", dir=release_root))
    try:
        rows: list[dict[str, object]] = []
        for path in release_paths:
            mode, object_id = entries[path]
            data = blob(object_id)
            write_file(stage / path, data, mode)
            rows.append(
                {
                    "path": path,
                    "mode": mode,
                    "size": len(data),
                    "sha256": sha256(data),
                }
            )
        if (stage / "VERSION").read_text(encoding="utf-8").strip() != version:
            raise RuntimeError(f"{commit}: VERSION does not equal requested {version}")

        generated_rows: list[dict[str, object]] = []
        okf_summary: dict[str, object] | None = None
        git_tree_id = str(git("rev-parse", f"{commit}^{{tree}}", text=True)).strip()
        if generated:
            generated_row, okf_summary = generate_okf_manifest(
                stage,
                commit=commit,
                git_tree_id=git_tree_id,
                package_manifest_sha256=manifest_sha,
            )
            rows.append(generated_row)
            generated_rows.append(generated_row)
        rows.sort(key=lambda row: str(row["path"]))

        digest_input = b"".join(
            f"{row['path']}\0{row['mode']}\0{row['size']}\0{row['sha256']}\n".encode()
            for row in rows
        )
        artifact = stage / "_artifacts" / f"goal-teams-{version}.tar.gz"
        artifact_sha = deterministic_tar(artifact, version, rows, stage)
        record = {
            "schema_version": "goal-teams-release-snapshot-v2.40",
            "version": version,
            "identity_authority": "source_commit",
            "source_ref": source_ref or commit,
            "source_commit": commit,
            "source_git_tree_id": git_tree_id,
            "source_package_manifest_sha256": manifest_sha,
            "file_count": len(rows),
            "total_bytes": sum(int(row["size"]) for row in rows),
            "tree_sha256": sha256(digest_input),
            "artifact": {
                "path": artifact.relative_to(stage).as_posix(),
                "sha256": artifact_sha,
                "size": artifact.stat().st_size,
            },
            "excluded_nonrelease_count": len(excluded),
            "excluded_categories": sorted({str(row["reason"]) for row in excluded}),
            "builder_generated_files": generated_rows,
            "okf_conformance": okf_summary,
            "sealed": True,
        }
        (stage / "_release.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if version == "V2.40":
            file_manifest = format_v240_files_manifest(rows)
        else:
            file_manifest = "".join(
                f"{row['sha256']}  {row['path']}\n" for row in rows
            )
        (stage / "_files.sha256").write_text(file_manifest, encoding="utf-8")
        (stage / "_artifacts" / "SHA256SUMS").write_text(
            f"{artifact_sha}  {artifact.name}\n", encoding="utf-8"
        )
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    if archive_root is not None:
        version_archive = archive_root / version
        if version_archive.exists():
            shutil.rmtree(version_archive)
        archive = version_archive / "repository-docs"
        archive.mkdir(parents=True)
        archive_rows = []
        for path, (mode, object_id) in sorted(entries.items()):
            reason = nonrelease_reason(path)
            if not reason:
                continue
            data = blob(object_id)
            write_file(archive / path, data, mode)
            archive_rows.append(
                {
                    "path": path,
                    "reason": reason,
                    "size": len(data),
                    "sha256": sha256(data),
                }
            )
        (version_archive / "archive-index.json").write_text(
            json.dumps(
                {
                    "schema_version": "goal-teams-release-doc-archive-v1",
                    "version": version,
                    "source_ref": source_ref or commit,
                    "source_commit": commit,
                    "file_count": len(archive_rows),
                    "files": archive_rows,
                    "manifest_exclusions": excluded,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="append", help="Version to build, e.g. V2.40")
    parser.add_argument("--commit", help="Frozen 40-character lowercase commit SHA")
    parser.add_argument("--source-ref", help="Display-only provenance; never read for bytes")
    parser.add_argument("--output-root", type=Path, help="Alternate isolated release root")
    parser.add_argument("--all-known", action="store_true", help="Build every known historical release")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all_known:
        if args.version or args.commit or args.source_ref:
            raise SystemExit(
                "--all-known cannot be combined with --version/--commit/--source-ref"
            )
        releases = [
            (
                version,
                str(git("rev-parse", f"{ref}^{{commit}}", text=True)).strip(),
                ref,
            )
            for version, ref in KNOWN_RELEASES.items()
        ]
    else:
        versions = args.version or []
        if not versions:
            raise SystemExit("use --version VERSION --commit 40HEX or --all-known")
        if len(versions) != 1 or not args.commit:
            raise SystemExit("one --version and --commit 40HEX are required")
        releases = [(versions[0], args.commit, args.source_ref)]
    output_root = (args.output_root or RELEASE_ROOT).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root == RELEASE_ROOT.resolve():
        ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
        archive_root: Path | None = ARCHIVE_ROOT
    else:
        archive_root = None
    built = [
        build(
            version,
            commit,
            source_ref=source_ref,
            release_root=output_root,
            archive_root=archive_root,
        )
        for version, commit, source_ref in releases
    ]
    existing = []
    for path in sorted(output_root.glob("V*")):
        meta = path / "_release.json"
        if meta.is_file():
            existing.append(json.loads(meta.read_text(encoding="utf-8")))
    (output_root / "index.json").write_text(json.dumps({"schema_version": "goal-teams-release-index-v2", "releases": existing}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"built": built}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
