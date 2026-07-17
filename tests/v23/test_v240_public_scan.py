from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
SCANNER_PATH = ROOT / "scripts" / "release" / "public_scan.py"
VERSION = "V2.40"
TAR_NAME = f"goal-teams-{VERSION}.tar.gz"
OKF_PATH = "references/okf-conformance-manifest.json"
PROVIDER_SAMPLE = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
PEM_SAMPLE = (
    b"-----BEGIN " + b"PRIVATE KEY-----\n"
    b"fixture-private-key-material\n"
    b"-----END " + b"PRIVATE KEY-----\n"
)
DETECTOR_SOURCE = b'''import re
HOME_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\\\\\\\/]+Users[\\\\\\\\/]+[^\\\\\\\\/\\s]+|/" + r"Users/[^/\\\\s]+|/" + r"home/[^/\\\\s]+|/" + r"root|/" + r"var/" + r"root)(?=/|\\\\\\\\|\\b)", re.I)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.I | re.S)
COMMON_TOKEN_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")
ASSIGNMENT_RE = re.compile(r"(?i)(?:token|password|credential)\\s*[:=]\\s*(?!(?:os\\.)?getenv\\(|\\[REDACTED(?::[0-9a-f]{16})?\\])[^\\s]+")
def contains_secret(text):
    return bool(PRIVATE_KEY_RE.search(text) or COMMON_TOKEN_RE.search(text) or ASSIGNMENT_RE.search(text))
'''


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_public_scan_tests", SCANNER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _baseline(assertions: list[dict[str, object]] | None = None) -> bytes:
    normalized = assertions or []
    return _json_bytes(
        {
            "schema_version": scanner.BASELINE_SCHEMA_VERSION,
            "version": VERSION,
            "review": {
                "reviewer_type": "independent_release_reviewer",
                "independent": True,
                "decision": "accepted",
                "review_id": "v240-independent-review",
                "reviewer_member_id": "reviewer-security-01",
                "reviewer_run_id": "run-v240-public-scan-01",
                "reviewed_at": "2026-07-15T00:00:00Z",
                "assertion_set_sha256": scanner.assertion_set_sha256(normalized),
                "occurrence_set_sha256": scanner.occurrence_set_sha256(normalized),
            },
            "assertions": normalized,
        }
    )


def _assertion(row: dict[str, object], reason: str) -> dict[str, object]:
    return {
        "path": row["path"],
        "file_sha256": row["file_sha256"],
        "detector_id": row["detector_id"],
        "kind": row["kind"],
        "occurrence_id": row["occurrence_id"],
        "occurrence_set_sha256": row["occurrence_set_sha256"],
        "reason": reason,
    }


class PublicScanFixture:
    def __init__(self, test: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="v240-public-scan-")
        test.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.snapshot = self.root / "snapshot"
        self.assets_root = self.root / "assets"
        self.source.mkdir()
        self.snapshot.mkdir()
        self.assets_root.mkdir()
        self.assets = {
            name: self.assets_root / name
            for name in (TAR_NAME, "SHA256SUMS", "_release.json", "_files.sha256")
        }

        self._git("init", "-b", "main")
        self._git("config", "user.name", "V240 Scanner Test")
        self._git("config", "user.email", "scanner@example.invalid")
        self._git("config", "commit.gpgSign", "false")
        self.write_source("README.md", b"# Public scanner fixture\n")
        self.write_source("scripts/v23/v236_security.py", DETECTOR_SOURCE)
        self.base_commit = self.commit("base fixture")
        self.write_source("src/app.txt", b"safe candidate content\n")
        self.commit("candidate fixture")

        self.write_snapshot("VERSION", f"{VERSION}\n".encode("utf-8"))
        self.write_snapshot("README.md", b"# Public release fixture\n")
        self.write_snapshot(OKF_PATH, b'{"status":"generated","version":"V2.40"}\n')
        self.rebuild_tar()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.source,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def write_source(self, relative: str, data: bytes) -> None:
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def remove_source(self, relative: str) -> None:
        (self.source / relative).unlink()

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        self._git("commit", "--no-gpg-sign", "-m", message)
        return self._git("rev-parse", "HEAD")

    def write_snapshot(self, relative: str, data: bytes) -> None:
        path = self.snapshot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _snapshot_entries(
        self, overrides: dict[str, bytes] | None = None
    ) -> list[tuple[str, bytes, str]]:
        values = overrides or {}
        entries: list[tuple[str, bytes, str]] = []
        for path in sorted(item for item in self.snapshot.rglob("*") if item.is_file()):
            relative = path.relative_to(self.snapshot).as_posix()
            entries.append((relative, values.get(relative, path.read_bytes()), "file"))
        return entries

    def _write_tar(
        self,
        entries: Iterable[tuple[str, bytes, str]],
        *,
        uname: str = "root",
        gname: str = "root",
        gzip_filename: str = "",
    ) -> None:
        with self.assets[TAR_NAME].open("wb") as raw:
            with gzip.GzipFile(
                filename=gzip_filename, mode="wb", fileobj=raw, mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT
                ) as archive:
                    for relative, data, member_type in entries:
                        info = tarfile.TarInfo(f"goal-teams-{VERSION}/{relative}")
                        info.mode = 0o644
                        info.mtime = 0
                        info.uid = 0
                        info.gid = 0
                        info.uname = uname
                        info.gname = gname
                        if member_type == "file":
                            info.size = len(data)
                            archive.addfile(info, io.BytesIO(data))
                        elif member_type == "symlink":
                            info.type = tarfile.SYMTYPE
                            info.linkname = data.decode("utf-8")
                            archive.addfile(info)
                        elif member_type == "char-device":
                            info.type = tarfile.CHRTYPE
                            info.devmajor = 1
                            info.devminor = 3
                            archive.addfile(info)
                        else:
                            raise AssertionError(f"unsupported test member: {member_type}")

    def _refresh_manifests(self) -> None:
        tar_digest = _sha256(self.assets[TAR_NAME].read_bytes())
        self.assets["SHA256SUMS"].write_text(
            f"{tar_digest}  {TAR_NAME}\n", encoding="utf-8"
        )
        self.assets["_release.json"].write_bytes(
            _json_bytes({"asset": TAR_NAME, "version": VERSION})
        )
        rows = []
        for path in sorted(item for item in self.snapshot.rglob("*") if item.is_file()):
            relative = path.relative_to(self.snapshot).as_posix()
            rows.append(f"{_sha256(path.read_bytes())}  {relative}")
        self.assets["_files.sha256"].write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )

    def rebuild_tar(self, overrides: dict[str, bytes] | None = None) -> None:
        self._write_tar(self._snapshot_entries(overrides))
        self._refresh_manifests()

    def write_custom_tar(
        self, entries: Iterable[tuple[str, bytes, str]]
    ) -> None:
        self._write_tar(entries)
        self._refresh_manifests()

    def scan(self, **overrides: object) -> dict[str, object]:
        candidate = self._git("rev-parse", "HEAD")
        arguments: dict[str, object] = {
            "source_root": self.source,
            "base_commit": self.base_commit,
            "candidate_commit": candidate,
            "candidate_tree": self._git("rev-parse", f"{candidate}^{{tree}}"),
            "version": VERSION,
            "snapshot_root": self.snapshot,
            "asset_paths": self.assets,
            "tag_message": "Goal Teams V2.40",
            "release_title": "Goal Teams V2.40",
            "release_body": "Canonical public release.",
            "checker_digest": _sha256(SCANNER_PATH.read_bytes()),
            "expected_detector_digest": _sha256(DETECTOR_SOURCE),
            "baseline_bytes": _baseline(),
        }
        arguments.update(overrides)
        return scanner.scan_surfaces(**arguments)


class V240PublicScanTests(unittest.TestCase):
    def test_python_checker_and_baseline_bytes_fail_closed(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            scanner._require_python_311((3, 10, 99))
        self.assertEqual(
            str(caught.exception),
            "E_PUBLIC_SCAN_PYTHON: Python 3.11+ required",
        )
        self.assertIsNone(scanner._require_python_311((3, 11, 0)))

        fixture = PublicScanFixture(self)
        with self.assertRaises(scanner.PublicScanError) as checker_error:
            fixture.scan(checker_digest="0" * 64)
        self.assertEqual(
            checker_error.exception.code, "E_PUBLIC_SCAN_CHECKER_DIGEST"
        )

        with self.assertRaises(scanner.PublicScanError) as newline_error:
            scanner.load_baseline(_baseline().rstrip(b"\n"))
        self.assertEqual(
            newline_error.exception.code, "E_PUBLIC_SCAN_BASELINE_CANONICAL"
        )
        duplicate = _baseline().replace(
            b'"version":"V2.40"',
            b'"version":"V2.40","version":"V2.40"',
            1,
        )
        with self.assertRaises(scanner.PublicScanError) as duplicate_error:
            scanner.load_baseline(duplicate)
        self.assertEqual(
            duplicate_error.exception.code, "E_PUBLIC_SCAN_BASELINE_JSON"
        )

    def test_receipt_is_deterministic_portable_and_binds_all_checker_inputs(self) -> None:
        fixture = PublicScanFixture(self)

        first = fixture.scan()
        second = fixture.scan()

        self.assertTrue(first["passed"])
        self.assertEqual(first, second)
        self.assertEqual(first["receipt_sha256"], scanner.receipt_hash(first))
        self.assertEqual(
            first["trust_bindings"]["scanner_blob_sha256"],
            _sha256(SCANNER_PATH.read_bytes()),
        )
        self.assertEqual(
            first["trust_bindings"]["baseline_blob_sha256"], _sha256(_baseline())
        )
        self.assertEqual(
            set(first["trust_bindings"]),
            {
                "scanner_blob_sha256",
                "detector_blob_sha256",
                "baseline_blob_sha256",
                "baseline_assertion_count",
                "baseline_assertions_sha256",
                "baseline_assertion_set_sha256",
                "baseline_occurrence_set_sha256",
                "baseline_review_sha256",
            },
        )
        self.assertEqual(
            first["occurrence_set_sha256"],
            first["coverage"]["occurrence_set_sha256"],
        )
        paths = {row["path"] for row in first["surfaces"]}
        self.assertIn(f"snapshot/{OKF_PATH}", paths)
        self.assertIn(f"tar/{OKF_PATH}", paths)
        rendered = json.dumps(first, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(str(fixture.root), rendered)
        self.assertNotIn("timestamp", rendered.lower())

    def test_unpacked_git_blob_with_provider_token_is_scanned_and_cannot_be_waived(
        self,
    ) -> None:
        fixture = PublicScanFixture(self)
        fixture.write_source(
            "private/unpackaged.txt",
            ("creden" + "tial=" + PROVIDER_SAMPLE + "\n").encode(),
        )
        fixture.write_source("tests/private-key-fixture.pem", PEM_SAMPLE)
        fixture.commit("add scanner credential negatives")

        receipt = fixture.scan()

        self.assertFalse(receipt["passed"])
        provider = next(
            finding
            for finding in receipt["unwaived_findings"]
            if finding["path"] == "git/final/private/unpackaged.txt"
            and finding["detector_id"] == "provider_token"
        )
        private_key_row = next(
            finding
            for finding in receipt["unwaived_findings"]
            if finding["path"] == "git/final/tests/private-key-fixture.pem"
            and finding["detector_id"] == "private_key"
        )
        self.assertIn("provider_token", provider["non_waivable_reasons"])
        self.assertIn("private_key", private_key_row["non_waivable_reasons"])
        self.assertFalse(provider["synthetic_fixture_eligible"])
        self.assertFalse(private_key_row["synthetic_fixture_eligible"])
        self.assertFalse(
            any(
                finding["path"].startswith("snapshot/private/")
                for finding in receipt["unwaived_findings"]
            )
        )

        reviewed = _baseline(
            [_assertion(provider, "detector_literal")]
        )
        with self.assertRaises(scanner.PublicScanError) as forbidden:
            fixture.scan(baseline_bytes=reviewed)
        self.assertEqual(forbidden.exception.code, "E_PUBLIC_SCAN_BASELINE_REASON")

    def test_intermediate_blob_and_raw_commit_message_survive_later_deletion(self) -> None:
        fixture = PublicScanFixture(self)
        fixture.write_source(
            "scratch/intermediate.txt", b"token=dummy-fixture-intermediate\n"
        )
        introduced_at = fixture.commit("token=dummy-fixture-message")
        object_id = fixture._git("rev-parse", f"{introduced_at}:scratch/intermediate.txt")
        fixture.remove_source("scratch/intermediate.txt")
        fixture.commit("remove intermediate file")

        receipt = fixture.scan()

        paths = {finding["path"] for finding in receipt["unwaived_findings"]}
        blob_path = f"git/history/blobs/{object_id}/scratch/intermediate.txt"
        commit_surface = next(
            row
            for row in receipt["surfaces"]
            if row.get("source_kind") == "git_commit_raw"
            and row.get("object_id") == introduced_at
        )
        self.assertIn(blob_path, paths)
        self.assertIn(commit_surface["path"], paths)
        self.assertNotIn("git/final/scratch/intermediate.txt", paths)
        surface = next(row for row in receipt["surfaces"] if row["path"] == blob_path)
        self.assertEqual(surface["object_id"], object_id)
        self.assertIn(
            {"commit": introduced_at, "path": "scratch/intermediate.txt"},
            surface["appearances"],
        )

    def test_reviewed_baseline_is_exact_and_one_byte_change_fails_closed(self) -> None:
        fixture = PublicScanFixture(self)
        relative = "tests/synthetic-fixture.txt"
        fixture.write_snapshot(relative, b"token=dummy-fixture-secret\n")
        fixture.rebuild_tar()

        candidate_receipt = fixture.scan()
        candidates = [
            row
            for row in candidate_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(b"token=dummy-fixture-secret\n")
        ]
        self.assertEqual({row["path"] for row in candidates}, {
            f"snapshot/{relative}", f"tar/{relative}"
        })
        self.assertTrue(all(row["waivable"] for row in candidates))
        self.assertTrue(
            all("synthetic_fixture" in row["allowed_reasons"] for row in candidates)
        )
        reviewed = _baseline(
            [
                _assertion(candidate, "synthetic_fixture")
                for candidate in candidates
            ]
        )
        accepted = fixture.scan(baseline_bytes=reviewed)
        self.assertTrue(accepted["passed"])
        self.assertTrue(
            all(row["reason"] == "synthetic_fixture" for row in accepted["waived_findings"])
        )

        tampered_assertions = [
            {**_assertion(candidate, "synthetic_fixture"), "occurrence_set_sha256": "0" * 64}
            for candidate in candidates
        ]
        exact_set_rejected = fixture.scan(
            baseline_bytes=_baseline(tampered_assertions)
        )
        self.assertFalse(exact_set_rejected["passed"])
        self.assertFalse(exact_set_rejected["waived_findings"])

        fixture.write_snapshot(relative, b"token=dummy-fixture-secret-X\n")
        fixture.rebuild_tar()
        changed = fixture.scan(baseline_bytes=reviewed)

        self.assertFalse(changed["passed"])
        self.assertTrue(
            any(error.startswith("unwaived_finding:snapshot/tests/") for error in changed["errors"])
        )
        self.assertTrue(
            any(
                error.startswith(
                    f"stale_baseline_assertion:{candidates[0]['path']}:{candidates[0]['sha256']}:"
                )
                for error in changed["errors"]
            )
        )

    def test_tar_generated_okf_is_scanned_independently_from_snapshot(self) -> None:
        fixture = PublicScanFixture(self)
        fixture.rebuild_tar(
            {
                OKF_PATH: (
                    '{"to' + 'ken":"dummy-fixture-generated-only"}\n'
                ).encode("utf-8")
            }
        )

        with self.assertRaises(scanner.PublicScanError) as mismatch:
            fixture.scan()
        self.assertEqual(
            mismatch.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH"
        )

    def test_tag_title_and_body_are_nonwaivable_public_surfaces(self) -> None:
        fixture = PublicScanFixture(self)

        receipt = fixture.scan(
            tag_message="token=dummy-fixture-bad-tag",
            release_title=f"Release {PROVIDER_SAMPLE}",
            release_body=(
                PEM_SAMPLE.decode("utf-8")
                + "workspace=/"
                + "Users/Rou/private\n"
            ),
        )

        by_path = {row["path"]: row for row in receipt["unwaived_findings"]}
        self.assertFalse(receipt["passed"])
        for path in ("release/tag-message", "release/title", "release/body"):
            self.assertIn(path, by_path)
            self.assertIn("unwaivable_surface", by_path[path]["non_waivable_reasons"])

    def test_readme_and_changelog_are_hard_even_for_closed_dummy_values(self) -> None:
        fixture = PublicScanFixture(self)
        content = b"token=dummy-fixture-secret\n"
        fixture.write_snapshot("README.extra.md", content)
        fixture.write_snapshot("CHANGELOG.md", content)
        fixture.rebuild_tar()

        receipt = fixture.scan()
        rows = [
            row
            for row in receipt["unwaived_findings"]
            if row["path"]
            in {
                "snapshot/README.extra.md",
                "tar/README.extra.md",
                "snapshot/CHANGELOG.md",
                "tar/CHANGELOG.md",
            }
        ]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["waivable"] is False for row in rows))
        self.assertTrue(
            all("unwaivable_surface" in row["non_waivable_reasons"] for row in rows)
        )

    def test_baseline_schema_rejects_public_surfaces_and_fake_synthetic_scope(self) -> None:
        digest = "a" * 64
        rows = (
            {
                "path": "git/final/README.md",
                "file_sha256": digest,
                "detector_id": "credential_literal",
                "kind": "secret",
                "occurrence_id": digest,
                "occurrence_set_sha256": digest,
                "reason": "detector_literal",
            },
            {
                "path": "release/body",
                "file_sha256": digest,
                "detector_id": "credential_literal",
                "kind": "secret",
                "occurrence_id": digest,
                "occurrence_set_sha256": digest,
                "reason": "detector_literal",
            },
            {
                "path": "snapshot/src/application.py",
                "file_sha256": digest,
                "detector_id": "credential_literal",
                "kind": "secret",
                "occurrence_id": digest,
                "occurrence_set_sha256": digest,
                "reason": "synthetic_fixture",
            },
        )
        for row in rows:
            with self.subTest(path=row["path"]), self.assertRaises(
                scanner.PublicScanError
            ):
                scanner.validate_baseline(scanner.load_baseline(_baseline([row])))

    def test_git_replace_grafts_shallow_partial_and_environment_fail_closed(self) -> None:
        replacement = PublicScanFixture(self)
        candidate = replacement._git("rev-parse", "HEAD")
        replacement._git("replace", candidate, replacement.base_commit)
        with self.assertRaises(scanner.PublicScanError) as replaced:
            replacement.scan()
        self.assertEqual(replaced.exception.code, "E_PUBLIC_SCAN_GIT_REPLACE")

        blob_replacement = PublicScanFixture(self)
        candidate_blob = blob_replacement._git("rev-parse", "HEAD:src/app.txt")
        safe_blob = blob_replacement._git("rev-parse", "HEAD:README.md")
        blob_replacement._git("replace", candidate_blob, safe_blob)
        with self.assertRaises(scanner.PublicScanError) as replaced_blob:
            blob_replacement.scan()
        self.assertEqual(replaced_blob.exception.code, "E_PUBLIC_SCAN_GIT_REPLACE")

        grafted = PublicScanFixture(self)
        common_value = grafted._git("rev-parse", "--git-common-dir")
        common = Path(common_value)
        if not common.is_absolute():
            common = grafted.source / common
        (common / "info").mkdir(parents=True, exist_ok=True)
        (common / "info" / "grafts").write_text(
            grafted._git("rev-parse", "HEAD") + "\n", encoding="utf-8"
        )
        with self.assertRaises(scanner.PublicScanError) as grafts:
            grafted.scan()
        self.assertEqual(grafts.exception.code, "E_PUBLIC_SCAN_GIT_GRAFTS")

        shallow = PublicScanFixture(self)
        git_dir_value = shallow._git("rev-parse", "--git-dir")
        git_dir = Path(git_dir_value)
        if not git_dir.is_absolute():
            git_dir = shallow.source / git_dir
        (git_dir / "shallow").write_text(
            shallow.base_commit + "\n", encoding="ascii"
        )
        with self.assertRaises(scanner.PublicScanError) as shallow_error:
            shallow.scan()
        self.assertEqual(shallow_error.exception.code, "E_PUBLIC_SCAN_GIT_SHALLOW")

        partial = PublicScanFixture(self)
        partial._git("config", "remote.origin.promisor", "true")
        with self.assertRaises(scanner.PublicScanError) as partial_error:
            partial.scan()
        self.assertEqual(partial_error.exception.code, "E_PUBLIC_SCAN_GIT_PARTIAL")

        partial_extension = PublicScanFixture(self)
        partial_extension._git("config", "core.repositoryformatversion", "1")
        partial_extension._git("config", "extensions.partialClone", "origin")
        with self.assertRaises(scanner.PublicScanError) as extension_error:
            partial_extension.scan()
        self.assertEqual(extension_error.exception.code, "E_PUBLIC_SCAN_GIT_PARTIAL")

        environment = PublicScanFixture(self)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(environment.source / ".git")}):
            with self.assertRaises(scanner.PublicScanError) as environment_error:
                environment.scan()
        self.assertEqual(environment_error.exception.code, "E_PUBLIC_SCAN_GIT_ENV")

    def test_detector_is_loaded_from_frozen_candidate_and_digest_bound(self) -> None:
        fixture = PublicScanFixture(self)
        with self.assertRaises(scanner.PublicScanError) as mismatch:
            fixture.scan(expected_detector_digest="0" * 64)
        self.assertEqual(mismatch.exception.code, "E_PUBLIC_SCAN_DETECTOR")

        fixture.write_source(
            "private/credential.txt",
            ("creden" + "tial=" + PROVIDER_SAMPLE + "\n").encode(),
        )
        fixture.commit("add frozen detector negative")
        fixture.write_source(
            "scripts/v23/v236_security.py",
            b"import re\nHOME_PATH_RE=PRIVATE_KEY_RE=COMMON_TOKEN_RE=re.compile('never')\ndef contains_secret(text): return False\n",
        )
        receipt = fixture.scan()
        self.assertFalse(receipt["passed"])
        self.assertTrue(
            any(
                row["path"] == "git/final/private/credential.txt"
                and "provider_token" in row["non_waivable_reasons"]
                for row in receipt["unwaived_findings"]
            )
        )
        self.assertEqual(
            receipt["trust_bindings"]["detector_blob_sha256"],
            _sha256(DETECTOR_SOURCE),
        )

    def test_git_paths_intermediate_renames_and_gitlinks_are_covered(self) -> None:
        fixture = PublicScanFixture(self)
        token_path = f"private/{PROVIDER_SAMPLE}.txt"
        fixture.write_source(token_path, b"safe path payload\n")
        fixture.write_source(".netrc", b"machine example.invalid login nobody\n")
        fixture.commit("add sensitive public paths")
        receipt = fixture.scan()
        by_path = {row["path"]: row for row in receipt["unwaived_findings"]}
        token_finding = by_path[f"git/final/{token_path}"]
        self.assertIn("path", token_finding["finding_sources"])
        self.assertIn("provider_token", token_finding["non_waivable_reasons"])
        netrc = by_path["git/final/.netrc"]
        self.assertIn("private_provenance_path", netrc["non_waivable_reasons"])

        renamed = PublicScanFixture(self)
        intermediate_path = f"private/{PROVIDER_SAMPLE}.txt"
        (renamed.source / "private").mkdir()
        renamed._git("mv", "README.md", intermediate_path)
        intermediate_commit = renamed.commit("temporary sensitive path")
        renamed._git("mv", intermediate_path, "README.md")
        renamed.commit("restore safe path")
        renamed_receipt = renamed.scan()
        self.assertTrue(
            any(
                row["path"].startswith("git/history/tree-paths/")
                and row.get("sha256")
                == _sha256(
                    (
                        "100644\0"
                        + renamed._git(
                            "rev-parse", f"{intermediate_commit}:{intermediate_path}"
                        )
                        + "\0"
                        + intermediate_path
                    ).encode("utf-8")
                )
                and "provider_token" in row["non_waivable_reasons"]
                for row in renamed_receipt["unwaived_findings"]
            )
        )

        gitlink = PublicScanFixture(self)
        gitlink._git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{gitlink.base_commit},vendor/submodule",
        )
        gitlink._git("commit", "--no-gpg-sign", "-m", "add forbidden gitlink")
        with self.assertRaises(scanner.PublicScanError) as gitlink_error:
            gitlink.scan()
        self.assertEqual(gitlink_error.exception.code, "E_PUBLIC_SCAN_GITLINK")

    def test_baseline_never_waives_provider_or_real_credentials(self) -> None:
        provider = PublicScanFixture(self)
        provider_data = (
            "creden" + "tial=" + PROVIDER_SAMPLE + " fixture\n"
        ).encode()
        provider.write_source("tests/synthetic-fixture.txt", provider_data)
        provider.commit("add provider-shaped fixture")
        provider_receipt = provider.scan()
        provider_rows = [
            row
            for row in provider_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(provider_data)
        ]
        self.assertTrue(provider_rows)
        self.assertTrue(all(row["waivable"] is False for row in provider_rows))
        attempted_provider_baseline = _baseline(
            [
                _assertion(row, "synthetic_fixture")
                for row in provider_rows
            ]
        )
        provider_rescan = provider.scan(
            baseline_bytes=attempted_provider_baseline
        )
        self.assertFalse(provider_rescan["passed"])
        self.assertFalse(provider_rescan["waived_findings"])

        credential = PublicScanFixture(self)
        credential_data = (
            "pass" + "word=" + "actual-production-" + "password-value\n"
        ).encode("utf-8")
        credential.write_source("tests/credential-fixture.txt", credential_data)
        credential.commit("add credential negative")
        credential_receipt = credential.scan()
        credential_rows = [
            row
            for row in credential_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(credential_data)
        ]
        self.assertTrue(credential_rows)
        self.assertTrue(
            all("credential" in row.get("non_waivable_reasons", []) for row in credential_receipt["unwaived_findings"] if row["sha256"] == _sha256(credential_data))
        )
        attempted_credential_baseline = _baseline(
            [
                _assertion(row, "synthetic_fixture")
                for row in credential_rows
            ]
        )
        credential_rescan = credential.scan(
            baseline_bytes=attempted_credential_baseline
        )
        self.assertFalse(credential_rescan["passed"])
        self.assertFalse(credential_rescan["waived_findings"])

    def test_occurrence_waiver_cannot_cover_real_secret_on_dummy_marked_line(self) -> None:
        fixture = PublicScanFixture(self)
        relative = "tests/mixed-fixture.txt"
        content = (
            b"token=dummy-fixture-secret marker=dummy\n"
            + ("pass" + "word=" + "actual-production-" + "password-value marker=dummy\n").encode("utf-8")
        )
        fixture.write_snapshot(relative, content)
        fixture.rebuild_tar()

        receipt = fixture.scan()
        rows = [
            row
            for row in receipt["baseline_candidate_rows"]
            if row["file_sha256"] == _sha256(content)
        ]
        synthetic = [
            row for row in rows if "synthetic_fixture" in row["allowed_reasons"]
        ]
        hard = [row for row in rows if row["waivable"] is False]
        self.assertEqual(len(synthetic), 2)
        self.assertEqual(len(hard), 2)
        self.assertEqual(
            {row["occurrence_set_sha256"] for row in rows},
            {rows[0]["occurrence_set_sha256"]},
        )

        reviewed = _baseline(
            [_assertion(row, "synthetic_fixture") for row in synthetic]
        )
        rescanned = fixture.scan(baseline_bytes=reviewed)
        self.assertFalse(rescanned["passed"])
        self.assertEqual(len(rescanned["waived_findings"]), 2)
        self.assertTrue(
            all(
                "credential" in row["non_waivable_reasons"]
                for row in rescanned["unwaived_findings"]
                if row["file_sha256"] == _sha256(content)
            )
        )

    def test_detector_source_path_does_not_waive_unrelated_real_credential(self) -> None:
        fixture = PublicScanFixture(self)
        real_value = b"".join((b"actual-production-", b"password-value"))
        detector = DETECTOR_SOURCE + b'\npassword="' + real_value + b'"\n'
        fixture.write_source("scripts/v23/v236_security.py", detector)
        fixture.commit("add real credential beside detector definitions")

        receipt = fixture.scan(expected_detector_digest=_sha256(detector))
        real_rows = [
            row
            for row in receipt["unwaived_findings"]
            if row["path"] == "git/final/scripts/v23/v236_security.py"
            and row["detector_id"] == "credential_literal"
        ]
        self.assertTrue(real_rows)
        self.assertTrue(all(row["allowed_reasons"] == [] for row in real_rows))
        self.assertTrue(
            all("credential" in row["non_waivable_reasons"] for row in real_rows)
        )

    def test_python_and_json_safe_references_are_not_false_positive_occurrences(self) -> None:
        fixture = PublicScanFixture(self)
        safe_python = (
            "au" + "th = False\n" + "pass" + "word = os.getenv('APP_PASSWORD')\n"
        ).encode("utf-8")
        fixture.write_snapshot("tests/config.py", safe_python)
        fixture.write_snapshot(
            "tests/config.json",
            b'{"auth":false,"password":"${APP_PASSWORD}"}\n',
        )
        fixture.rebuild_tar()

        receipt = fixture.scan()
        paths = {
            row["path"]
            for row in receipt["unwaived_findings"]
            if row["path"].endswith("config.py") or row["path"].endswith("config.json")
        }
        self.assertEqual(paths, set())

        literal = (
            '{"pass' + 'word":"ordinary-literal-password"}\n'
        ).encode("utf-8")
        fixture.write_snapshot("tests/config.json", literal)
        fixture.rebuild_tar()
        hard = fixture.scan()
        literal_rows = [
            row
            for row in hard["unwaived_findings"]
            if row["file_sha256"] == _sha256(literal)
        ]
        self.assertEqual(len(literal_rows), 2)
        self.assertTrue(
            all("credential" in row["non_waivable_reasons"] for row in literal_rows)
        )

    def test_structured_and_generic_detectors_cannot_hide_real_credentials(self) -> None:
        fixture = PublicScanFixture(self)
        duplicate_json = (
            '{"to' + 'ken":"ordinary-visible-token-value",'
            + '"pass' + 'word":"actual-hidden-password-value",'
            + '"pass' + 'word":"${APP_PASSWORD}"}\n'
        ).encode("utf-8")
        python_expression = (
            "pass" + 'word = "actual-production-" + "password-value"\n'
        ).encode("utf-8")
        fixture.write_snapshot("tests/duplicate-config.json", duplicate_json)
        fixture.write_snapshot("tests/expression-config.py", python_expression)
        fixture.rebuild_tar()

        receipt = fixture.scan()
        json_rows = [
            row
            for row in receipt["unwaived_findings"]
            if row["file_sha256"] == _sha256(duplicate_json)
        ]
        python_rows = [
            row
            for row in receipt["unwaived_findings"]
            if row["file_sha256"] == _sha256(python_expression)
        ]
        self.assertEqual(len(json_rows), 4)
        self.assertEqual(len(python_rows), 2)
        self.assertTrue(
            all(
                row["waivable"] is False
                and "credential" in row["non_waivable_reasons"]
                for row in [*json_rows, *python_rows]
            )
        )
        self.assertEqual(
            {row["detector_id"] for row in python_rows},
            {"credential_literal"},
        )

        dynamic_python = (
            "authori" + 'zation = headers.get("Authorization")\n'
            + "pass" + 'word = os.environ.get("APP_PASSWORD")\n'
        ).encode("utf-8")
        fixture.write_snapshot("tests/dynamic-config.py", dynamic_python)
        fixture.rebuild_tar()
        dynamic_receipt = fixture.scan()
        dynamic_rows = [
            row
            for row in dynamic_receipt["baseline_candidate_rows"]
            if row["file_sha256"] == _sha256(dynamic_python)
        ]
        self.assertFalse(
            any(row["detector_id"] == "credential_literal" for row in dynamic_rows)
        )
        self.assertFalse(
            any(
                "credential" in row["non_waivable_reasons"]
                for row in dynamic_rows
            )
        )

        unexplained_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"(?!)"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=lambda value: "opaque" in value,
        )
        unexplained = scanner._detect(
            security=unexplained_security,
            path="git/final/config.json",
            data=b'{"safe":"opaque"}\n',
            appearances=[{"commit": "a" * 40, "path": "config.json"}],
        )
        self.assertEqual(len(unexplained), 1)
        self.assertEqual(
            unexplained[0]["detector_id"], "shared_detector_unclassified"
        )
        self.assertFalse(unexplained[0]["waivable"])
        self.assertIn("credential", unexplained[0]["non_waivable_reasons"])

        mixed_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"known-secret"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=lambda value: (
                "known-secret" in value or "opaque-secret" in value
            ),
        )
        mixed = scanner._detect(
            security=mixed_security,
            path="git/final/mixed.txt",
            data=b"known-secret\nopaque-secret\n",
            appearances=[{"commit": "b" * 40, "path": "mixed.txt"}],
        )
        mixed_ids = {row["detector_id"] for row in mixed}
        self.assertIn("provider_token", mixed_ids)
        self.assertIn("shared_detector_unclassified", mixed_ids)
        self.assertTrue(
            all(
                row["waivable"] is False
                and "credential" in row["non_waivable_reasons"]
                for row in mixed
                if row["detector_id"] == "shared_detector_unclassified"
            )
        )

    def test_production_credentials_never_inherit_fixture_or_detector_waivers(self) -> None:
        empty_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"(?!)"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=lambda _value: False,
        )
        real_value = "".join(("actual-production-", "password-value"))
        detector_test_data = (
            "pass" + "word = \"" + real_value + "\"\n"
        ).encode("utf-8")
        detector_rows = scanner._detect(
            security=empty_security,
            path="git/final/tests/v23/test_v240_public_scan.py",
            data=detector_test_data,
            appearances=[
                {
                    "commit": "c" * 40,
                    "path": "tests/v23/test_v240_public_scan.py",
                }
            ],
        )
        self.assertTrue(detector_rows)
        self.assertTrue(
            all(
                row["waivable"] is False
                and "credential" in row["non_waivable_reasons"]
                for row in detector_rows
            )
        )

        for value in (
            "production-private-password",
            "customer-raw-secret",
            "canonical-production-password",
            "production-example-secret",
            "fake-live-customer-prod",
            "fixture-real-bank-password",
            "synthetic-prod-access-key",
            "dummy-fixture-actual-production-password",
            "dummy-fixture-xproductionx-password",
            "dummy-fixture-xxrealxx-password",
            "dummy-fixture-xbankx-password",
            "dummy-fixture-xcustomerx-password",
            "dummy-fixture-xlivelx-password",
            "dummy-fixture-xprodx-password",
        ):
            rows = scanner._detect(
                security=empty_security,
                path="snapshot/tests/fixture.txt",
                data=("pass" + "word=" + value + "\n").encode("utf-8"),
                appearances=None,
            )
            self.assertTrue(rows, value)
            self.assertTrue(
                all(
                    row["waivable"] is False
                    and "credential" in row["non_waivable_reasons"]
                    for row in rows
                ),
                value,
            )

        accepted_dummy = scanner._detect(
            security=empty_security,
            path="snapshot/tests/fixture.txt",
            data=("pass" + "word=dummy-fixture-redaction-case\n").encode("utf-8"),
            appearances=None,
        )
        self.assertTrue(accepted_dummy)
        self.assertTrue(
            all(
                row["waivable"] is True
                and row["allowed_reasons"] == ["synthetic_fixture"]
                for row in accepted_dummy
            )
        )

    def test_sensitive_python_aliases_and_shape_exemptions_are_fail_closed(self) -> None:
        empty_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"(?!)"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=lambda _value: False,
        )
        sensitive = "pass" + "word"
        real_value = "".join(("actual-production-", "password-value"))
        literal = repr(real_value)
        samples = {
            "lambda": f"{sensitive} = lambda: {literal}\n",
            "walrus": f"if ({sensitive} := {literal}): pass\n",
            "augassign": f"{sensitive} += {literal}\n",
            "computed-dict-key": (
                f"config = {{'pass' + 'word': {literal}}}\n"
            ),
            "globals-subscript": (
                f"globals()['pass' + 'word'] = {literal}\n"
            ),
            "setattr": f"setattr(config, {sensitive!r}, {literal})\n",
            "indirect-join": (
                f"parts = [{literal}]\n{sensitive} = ''.join(parts)\n"
            ),
            "re-compile": f"{sensitive} = re.compile({literal})\n",
            "schema-const": (
                "schema = {'pass' + 'word': "
                f"{{'type': 'string', 'const': {literal}}}}}\n"
            ),
            "path-div": f"{sensitive} = Path({literal}) / 'suffix'\n",
            "authorization-call": (
                f"{'authori' + 'zation'} = make_authorization({literal})\n"
            ),
            "custom-get-keyword": (
                f"{sensitive} = custom.get('KEY', payload={literal})\n"
            ),
        }
        for name, source in samples.items():
            rows = scanner._detect(
                security=empty_security,
                path=f"git/final/config-{name}.py",
                data=source.encode("utf-8"),
                appearances=[
                    {"commit": "d" * 40, "path": f"config-{name}.py"}
                ],
            )
            credentials = [
                row for row in rows if row["detector_id"] == "credential_literal"
            ]
            self.assertTrue(credentials, name)
            self.assertTrue(
                all(
                    row["waivable"] is False
                    and row["allowed_reasons"] == []
                    and "credential" in row["non_waivable_reasons"]
                    for row in credentials
                ),
                name,
            )

    def test_sensitive_sink_provenance_matrix_is_fail_closed(self) -> None:
        empty_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"(?!)"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=lambda _value: False,
        )
        sensitive = "pass" + "word"
        real_value = "".join(("actual-production-", "password-value"))
        literal = repr(real_value)
        samples = {
            "direct-subscript": f"config[{sensitive!r}] = {literal}\n",
            "key-chain": (
                f"a = {sensitive!r}\nb = a\nc = b\nconfig[c] = {literal}\n"
            ),
            "key-join": (
                f"bits = ['pass', 'word']\nk = ''.join(bits)\nconfig[k] = {literal}\n"
            ),
            "tuple-unpack": (
                f"k, val = ({sensitive!r}, {literal})\nconfig[k] = val\n"
            ),
            "update-list": f"config.update([({sensitive!r}, {literal})])\n",
            "update-tuples": f"pairs = (({sensitive!r}, {literal}),)\nconfig.update(pairs)\n",
            "dict-pairs": f"config = dict([({sensitive!r}, {literal})])\n",
            "mapping-key-alias": (
                f"keys = {{'credential': {sensitive!r}}}\nconfig[keys['credential']] = {literal}\n"
            ),
            "update-keyword": f"config.update({sensitive}={literal})\n",
            "update-mapping": f"config.update({{{sensitive!r}: {literal}}})\n",
            "branch-key-safe": (
                f"k = {sensitive!r}\nif flag:\n    k = 'mode'\nconfig[k] = {literal}\n"
            ),
            "branch-key-sensitive": (
                f"k = 'mode'\nif flag:\n    k = {sensitive!r}\nconfig[k] = {literal}\n"
            ),
            "branch-value-safe": (
                f"v = {literal}\nif flag:\n    v = os.getenv('APP_PASSWORD')\n{sensitive} = v\n"
            ),
            "branch-value-risk": (
                f"v = os.getenv('APP_PASSWORD')\nif flag:\n    v = {literal}\n{sensitive} = v\n"
            ),
            "bound-setitem": (
                f"setter = config.__setitem__\nsetter({sensitive!r}, {literal})\n"
            ),
            "bound-setattr": (
                f"setter = setattr\nsetter(config, {sensitive!r}, {literal})\n"
            ),
            "bound-setdefault": (
                f"setter = config.setdefault\nsetter({sensitive!r}, {literal})\n"
            ),
            "direct-setdefault": f"config.setdefault({sensitive!r}, {literal})\n",
            "operator-setitem": (
                f"import operator\noperator.setitem(config, {sensitive!r}, {literal})\n"
            ),
            "object-setattr": (
                f"object.__setattr__(config, {sensitive!r}, {literal})\n"
            ),
            "helper-subscript": (
                f"def put(k, v):\n    config[k] = v\nput({sensitive!r}, {literal})\n"
            ),
            "helper-return": (
                f"def get_value():\n    return {literal}\n{sensitive} = get_value()\n"
            ),
            "append-join": (
                f"parts = []\nparts.append({literal})\n{sensitive} = ''.join(parts)\n"
            ),
            "extend-join": (
                f"parts = []\nparts.extend([{literal}])\n{sensitive} = ''.join(parts)\n"
            ),
            "value-chain": f"a = {literal}\nb = a\n{sensitive} = b\n",
            "class-key": (
                f"class Keys:\n    {'creden' + 'tial'} = {sensitive!r}\n"
                f"config[Keys.{'creden' + 'tial'}] = {literal}\n"
            ),
            "mapping-key": (
                f"keys = {{'credential': {sensitive!r}}}\nk = keys['credential']\nconfig[k] = {literal}\n"
            ),
            "branch-sink-safe": (
                "setter = config.__setitem__\nif flag:\n    setter = print\n"
                f"setter({sensitive!r}, {literal})\n"
            ),
            "branch-sink-sensitive": (
                "setter = print\nif flag:\n    setter = config.__setitem__\n"
                f"setter({sensitive!r}, {literal})\n"
            ),
            "operator-import-alias": (
                f"from operator import setitem\nsetitem(config, {sensitive!r}, {literal})\n"
            ),
            "builtins-import-alias": (
                f"from builtins import setattr as sa\nsa(config, {sensitive!r}, {literal})\n"
            ),
            "getattr-setter": (
                "setter = getattr(config, '__setitem__')\n"
                f"setter({sensitive!r}, {literal})\n"
            ),
            "helper-call-setitem": (
                "def put(k, v):\n    config.__setitem__(k, v)\n"
                f"put({sensitive!r}, {literal})\n"
            ),
            "helper-call-setdefault": (
                "def put(k, v):\n    config.setdefault(k, v)\n"
                f"put({sensitive!r}, {literal})\n"
            ),
            "helper-call-update": (
                "def put(k, v):\n    config.update([(k, v)])\n"
                f"put({sensitive!r}, {literal})\n"
            ),
            "function-alias": (
                f"def get_value():\n    return {literal}\ng = get_value\n{sensitive} = g()\n"
            ),
            "function-call-before-redefinition": (
                f"def get_value():\n    return {literal}\n{sensitive} = get_value()\n"
                "def get_value():\n    return os.getenv('APP_PASSWORD')\n"
            ),
            "string-get-default": (
                f"{sensitive} = \"custom.get('KEY', default={literal})\"\n"
            ),
            "string-getenv-default": (
                f"{sensitive} = \"os.getenv('KEY', {literal})\"\n"
            ),
            "kwargs-alias": (
                f"k = {sensitive!r}\nkwargs = {{k: {literal}}}\nconfig.update(**kwargs)\n"
            ),
            "mapping-or-equals": (
                f"k = {sensitive!r}\nkwargs = {{k: {literal}}}\nconfig |= kwargs\n"
            ),
            "helper-fixed-key": (
                f"def put(v):\n    config[{sensitive!r}] = v\nput({literal})\n"
            ),
            "helper-default-key": (
                f"def put(v, k={sensitive!r}):\n    config[k] = v\nput({literal})\n"
            ),
            "helper-global-assignment": (
                f"def put(v):\n    global {sensitive}\n    {sensitive} = v\nput({literal})\n"
            ),
            "helper-return-default": (
                f"def get_value(v={literal}):\n    return v\n{sensitive} = get_value()\n"
            ),
            "method-direct-return": (
                f"class C:\n def get_{sensitive}(self): return {literal}\n"
                f"{sensitive} = C().get_{sensitive}()\n"
            ),
            "method-bound-return": (
                f"class C:\n def get_{sensitive}(self): return {literal}\n"
                f"c = C()\ng = c.get_{sensitive}\n{sensitive} = g()\n"
            ),
            "method-direct-setter": (
                f"class C:\n def put(self, x): config[{sensitive!r}] = x\n"
                f"C().put({literal})\n"
            ),
            "method-instance-setter": (
                f"class C:\n def put(self, x): config[{sensitive!r}] = x\n"
                f"c = C()\nc.put({literal})\n"
            ),
            "lambda-setter": (
                f"put = lambda x: config.__setitem__({sensitive!r}, x)\n"
                f"put({literal})\n"
            ),
            "partial-setter": (
                f"put = functools.partial(config.__setitem__, {sensitive!r})\n"
                f"put({literal})\n"
            ),
            "helper-keyword-only-value": (
                f"def put(*, x): config[{sensitive!r}] = x\n"
                f"put(x={literal})\n"
            ),
            "helper-keyword-only-key-default": (
                f"def put(x, *, k={sensitive!r}): config[k] = x\n"
                f"put({literal})\n"
            ),
            "staticmethod-return": (
                f"class C:\n @staticmethod\n def get_{sensitive}(): return {literal}\n"
                f"{sensitive} = C.get_{sensitive}()\n"
            ),
            "classmethod-keyword-setter": (
                f"class C:\n @classmethod\n def put(cls, *, x): config[{sensitive!r}] = x\n"
                f"C.put(x={literal})\n"
            ),
            "lambda-keyword-only-setter": (
                f"put = lambda *, x: config.__setitem__({sensitive!r}, x)\n"
                f"put(x={literal})\n"
            ),
            "partial-import-alias-setter": (
                "from functools import partial as bind\n"
                "from operator import setitem as assign\n"
                f"put = bind(assign, config, {sensitive!r})\nput({literal})\n"
            ),
            "inherited-method-return": (
                f"class Base:\n def get_{sensitive}(self): return {literal}\n"
                f"class Child(Base): pass\n{sensitive} = Child().get_{sensitive}()\n"
            ),
            "inherited-method-setter": (
                f"class Base:\n def put(self, x): config[{sensitive!r}] = x\n"
                f"class Child(Base): pass\nChild().put({literal})\n"
            ),
            "inherited-staticmethod-return": (
                f"class Base:\n @staticmethod\n def get_{sensitive}(): return {literal}\n"
                f"class Child(Base): pass\n{sensitive} = Child.get_{sensitive}()\n"
            ),
            "inherited-classmethod-setter": (
                f"class Base:\n @classmethod\n def put(cls, x): config[{sensitive!r}] = x\n"
                f"class Child(Base): pass\nChild.put({literal})\n"
            ),
            "inherited-bound-method-setter": (
                f"class Base:\n def put(self, x): config[{sensitive!r}] = x\n"
                f"class Child(Base): pass\nc = Child()\nm = c.put\nm({literal})\n"
            ),
            "getattr-local-method-setter": (
                f"class C:\n def put(self, x): config[{sensitive!r}] = x\n"
                f"c = C()\nm = getattr(c, 'put')\nm({literal})\n"
            ),
            "dict-literal-key-alias": (
                f"k = {sensitive!r}\nconfig = {{k: {literal}}}\n"
            ),
            "helper-return-dict": (
                "def build(k, v): return {k: v}\n"
                f"config = build({sensitive!r}, {literal})\n"
            ),
            "closed-dict-comprehension": (
                f"config = {{k: v for k, v in [({sensitive!r}, {literal})]}}\n"
            ),
        }
        for name, source in samples.items():
            literal_rows = scanner._python_literal_credential_occurrences(source)
            self.assertTrue(literal_rows, name)
            if name in {
                "direct-subscript",
                "class-key",
                "mapping-key",
                "mapping-key-alias",
            }:
                self.assertTrue(
                    any(row["value"] == real_value for row in literal_rows), name
                )
            rows = scanner._detect(
                security=empty_security,
                path=f"git/final/provenance-{name}.py",
                data=source.encode("utf-8"),
                appearances=[
                    {"commit": "f" * 40, "path": f"provenance-{name}.py"}
                ],
            )
            credentials = [
                row for row in rows if row["detector_id"] == "credential_literal"
            ]
            self.assertTrue(credentials, name)
            self.assertTrue(
                all(
                    row["waivable"] is False
                    and "credential" in row["non_waivable_reasons"]
                    for row in credentials
                ),
                name,
            )

        safe_sources = (
            "index = 1\nstate[index] = record\n",
            "def get_value():\n    return os.getenv('APP_PASSWORD')\n"
            + sensitive
            + " = get_value()\n"
            + "def get_value():\n    return "
            + literal
            + "\n",
            sensitive + " = \"custom.get('KEY', default='$APP_PASSWORD')\"\n",
            sensitive
            + " = \"os.getenv('KEY', 'dummy-fixture-reference')\"\n",
            f"class C:\n def get_{sensitive}(self): return os.getenv('APP_PASSWORD')\n"
            f"{sensitive} = C().get_{sensitive}()\n",
            f"class C:\n def put(self, x): config[{sensitive!r}] = x\n"
            "C().put(os.getenv('APP_PASSWORD'))\n",
            "put = functools.partial(config.__setitem__, 'mode')\n"
            "put('ordinary-record')\n",
            "def put(x, *, k='mode'): config[k] = x\n"
            "put('ordinary-record')\n",
            f"class Base:\n def get_{sensitive}(self): return os.getenv('APP_PASSWORD')\n"
            f"class Child(Base): pass\n{sensitive} = Child().get_{sensitive}()\n",
            f"class Base:\n def put(self, x): config[{sensitive!r}] = x\n"
            "class Child(Base): pass\nChild().put(os.getenv('APP_PASSWORD'))\n",
            "class C:\n def put(self, x): config['mode'] = x\n"
            "c = C()\nm = getattr(c, 'put')\nm('ordinary-record')\n",
            "k = 'mode'\nconfig = {k: 'ordinary-record'}\n",
            "def build(k, v): return {k: v}\n"
            "config = build('mode', 'ordinary-record')\n",
            "def build(k, v): return {k: v}\n"
            "config = build('password', os.getenv('APP_PASSWORD'))\n",
            "config = {k: v for k, v in [('mode', 'ordinary-record')]}\n",
            "config = {k: v for k, v in "
            "[('password', os.getenv('APP_PASSWORD'))]}\n",
        )
        for source in safe_sources:
            rows = scanner._detect(
                security=empty_security,
                path="git/final/provenance-safe.py",
                data=source.encode("utf-8"),
                appearances=[{"commit": "f" * 40, "path": "provenance-safe.py"}],
            )
            self.assertFalse(
                any(row["detector_id"] == "credential_literal" for row in rows),
                source,
            )

    def test_detector_literal_requires_a_real_regex_pattern_body(self) -> None:
        empty_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"(?!)"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=lambda _value: False,
        )
        real_value = "".join(("actual-production-", "password-value"))
        detector_path = "tests/v23/test_v240_public_scan.py"
        appearances = [{"commit": "e" * 40, "path": detector_path}]
        for source in (
            f"compile('pass' + 'word={real_value}', '<x>', 'exec')\n",
            f"PASSWORD_RE = 'pass' + 'word={real_value}'\n",
            f"DETECTOR_PAYLOAD = 'pass' + 'word={real_value}'\n",
        ):
            rows = scanner._detect(
                security=empty_security,
                path=f"git/final/{detector_path}",
                data=source.encode("utf-8"),
                appearances=appearances,
            )
            self.assertTrue(rows, source)
            self.assertTrue(
                all(
                    row["waivable"] is False
                    and "detector_literal" not in row["allowed_reasons"]
                    for row in rows
                ),
                source,
            )

        actual_pattern = (
            "COMMON_TOKEN_RE = re.compile(r'tok_[A-Za-z0-9]{16}')\n"
        )
        spans = scanner._detector_literal_spans(actual_pattern, [detector_path])
        self.assertEqual(len(spans), 1)

    def test_sensitive_python_literal_expressions_are_fail_closed(self) -> None:
        empty_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"(?!)"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=lambda _value: False,
        )
        real_value = "actual-production-" + "password-value"
        samples = (
            "pass" + "word = f\"" + real_value + "\"\n",
            "pass" + "word = f\"actual-production-{1}-password-value\"\n",
            "pass" + "word = \"\".join([\"" + real_value + "\"])\n",
            "pass" + "word = \"" + real_value + "\".format()\n",
        )
        for index, source in enumerate(samples):
            rows = scanner._detect(
                security=empty_security,
                path=f"snapshot/tests/expression-{index}.py",
                data=source.encode("utf-8"),
                appearances=None,
            )
            credentials = [
                row for row in rows if row["detector_id"] == "credential_literal"
            ]
            self.assertTrue(credentials, source)
            self.assertTrue(
                all(
                    row["waivable"] is False
                    and "credential" in row["non_waivable_reasons"]
                    for row in credentials
                ),
                source,
            )

        safe = (
            "authori" + 'zation = headers.get("Authorization")\n'
            + "pass" + 'word = os.environ.get("APP_PASSWORD")\n'
        )
        safe_rows = scanner._detect(
            security=empty_security,
            path="snapshot/tests/dynamic.py",
            data=safe.encode("utf-8"),
            appearances=None,
        )
        self.assertFalse(
            any(row["detector_id"] == "credential_literal" for row in safe_rows)
        )

    def test_every_absolute_home_is_hard_including_generic_identities(self) -> None:
        fixture = PublicScanFixture(self)
        relative = "examples/placeholder-home.txt"
        generic = b"workspace=/" + b"Users/example/project\n"
        fixture.write_snapshot(relative, generic)
        fixture.rebuild_tar()
        receipt = fixture.scan()
        rows = [
            row
            for row in receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(generic)
        ]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["waivable"] is False for row in rows))
        self.assertTrue(
            all(
                "private_home" in row["non_waivable_reasons"]
                for row in receipt["unwaived_findings"]
                if row["file_sha256"] == _sha256(generic)
            )
        )

        private = b"workspace=/" + b"Users/Rou/private\n"
        fixture.write_snapshot(relative, private)
        fixture.rebuild_tar()
        private_receipt = fixture.scan()
        private_rows = [
            row
            for row in private_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(private)
        ]
        self.assertTrue(private_rows)
        self.assertTrue(all(row["waivable"] is False for row in private_rows))

        home_cases = {
            "examples/root-home.txt": b"workspace=/" + b"root/private-project\n",
            "examples/var-root-home.txt": (
                b"workspace=/" + b"var/root/private-project\n"
            ),
            "tests/windows-home.json": (
                b'{"workspace":"C:'
                + b"\\\\"
                + b"Users"
                + b"\\\\Alice\\\\private-project"
                + b'"}\n'
            ),
            "tests/windows-home.py": (
                b'workspace = "C:'
                + b"\\\\"
                + b"Users"
                + b"\\\\Alice\\\\private-project"
                + b'"\n'
            ),
        }
        for relative, data in home_cases.items():
            fixture.write_source(relative, data)
            fixture.write_snapshot(relative, data)
        fixture.commit("add root and escaped Windows home negatives")
        fixture.rebuild_tar()
        expanded = fixture.scan()
        for relative, data in home_cases.items():
            with self.subTest(relative=relative):
                matching = [
                    row
                    for row in expanded["unwaived_findings"]
                    if row["file_sha256"] == _sha256(data)
                    and row["detector_id"] == "absolute_home"
                ]
                self.assertTrue(matching)
                paths = {row["path"] for row in matching}
                self.assertIn(f"git/final/{relative}", paths)
                self.assertIn(f"snapshot/{relative}", paths)
                self.assertIn(f"tar/{relative}", paths)
                self.assertTrue(
                    all(
                        row["waivable"] is False
                        and "private_home" in row["non_waivable_reasons"]
                        for row in matching
                    )
                )

    def test_snapshot_tar_identity_modes_and_membership_are_exact(self) -> None:
        content = PublicScanFixture(self)
        content.rebuild_tar({"README.md": b"different tar content\n"})
        with self.assertRaises(scanner.PublicScanError) as content_error:
            content.scan()
        self.assertEqual(
            content_error.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH"
        )

        mode = PublicScanFixture(self)
        (mode.snapshot / "README.md").chmod(0o755)
        with self.assertRaises(scanner.PublicScanError) as mode_error:
            mode.scan()
        self.assertEqual(
            mode_error.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH"
        )

        membership = PublicScanFixture(self)
        membership.write_snapshot("extra.txt", b"snapshot only\n")
        with self.assertRaises(scanner.PublicScanError) as membership_error:
            membership.scan()
        self.assertEqual(
            membership_error.exception.code,
            "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH",
        )

    def test_snapshot_membership_race_fails_closed(self) -> None:
        fixture = PublicScanFixture(self)
        original = scanner._read_regular_file
        mutated = False

        def racing(path: Path, *, max_bytes: int, code: str) -> bytes:
            nonlocal mutated
            data = original(path, max_bytes=max_bytes, code=code)
            if (
                fixture.snapshot.resolve() in path.resolve().parents
                and not mutated
            ):
                mutated = True
                fixture.write_snapshot("late-added.txt", b"late\n")
            return data

        with mock.patch.object(scanner, "_read_regular_file", side_effect=racing):
            with self.assertRaises(scanner.PublicScanError) as changed:
                fixture.scan()
        self.assertEqual(changed.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_CHANGED")

    def test_secure_read_rejects_path_replacement_hardlink_and_open_modes(self) -> None:
        fixture = PublicScanFixture(self)
        target = fixture.root / "secure-read.txt"
        replacement = fixture.root / "secure-read-replacement.txt"
        target.write_bytes(b"original\n")
        replacement.write_bytes(b"replaced\n")
        original_read = os.read
        replaced = False

        def racing(descriptor: int, size: int) -> bytes:
            nonlocal replaced
            if not replaced:
                replaced = True
                os.replace(replacement, target)
            return original_read(descriptor, size)

        with mock.patch.object(scanner.os, "read", side_effect=racing):
            with self.assertRaises(scanner.PublicScanError) as path_changed:
                scanner._read_regular_file(
                    target,
                    max_bytes=1024,
                    code="E_PUBLIC_SCAN_TEST_READ",
                )
        self.assertEqual(path_changed.exception.code, "E_PUBLIC_SCAN_TEST_READ")

        hardlink_source = fixture.root / "hardlink-source.txt"
        hardlink_target = fixture.root / "hardlink-target.txt"
        hardlink_source.write_bytes(b"linked\n")
        os.link(hardlink_source, hardlink_target)
        with self.assertRaises(scanner.PublicScanError):
            scanner._read_regular_file(
                hardlink_source,
                max_bytes=1024,
                code="E_PUBLIC_SCAN_TEST_READ",
            )

        writable = fixture.root / "world-writable.txt"
        writable.write_bytes(b"unsafe mode\n")
        writable.chmod(0o666)
        with self.assertRaises(scanner.PublicScanError):
            scanner._read_regular_file(
                writable,
                max_bytes=1024,
                code="E_PUBLIC_SCAN_TEST_READ",
            )

    def test_snapshot_census_binds_content_digest_not_only_stat_metadata(self) -> None:
        fixture = PublicScanFixture(self)
        target = fixture.snapshot / "README.md"
        original_census = scanner._snapshot_census
        calls = 0

        def racing(root: Path) -> tuple[tuple[object, ...], ...]:
            nonlocal calls
            rows = original_census(root)
            calls += 1
            if calls == 1:
                metadata = target.stat()
                target.write_bytes(b"X" * metadata.st_size)
                os.utime(
                    target,
                    ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                )
            return rows

        with mock.patch.object(scanner, "_snapshot_census", side_effect=racing):
            with self.assertRaises(scanner.PublicScanError) as changed:
                fixture.scan()
        self.assertEqual(changed.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_CHANGED")

    def test_tar_and_gzip_metadata_must_be_canonical(self) -> None:
        metadata = PublicScanFixture(self)
        metadata._write_tar(
            metadata._snapshot_entries(), uname=PROVIDER_SAMPLE
        )
        metadata._refresh_manifests()
        with self.assertRaises(scanner.PublicScanError) as metadata_error:
            metadata.scan()
        self.assertEqual(metadata_error.exception.code, "E_PUBLIC_SCAN_TAR_METADATA")

        gzip_header = PublicScanFixture(self)
        gzip_header._write_tar(
            gzip_header._snapshot_entries(), gzip_filename="private-build-path.tar"
        )
        gzip_header._refresh_manifests()
        with self.assertRaises(scanner.PublicScanError) as gzip_error:
            gzip_header.scan()
        self.assertEqual(gzip_error.exception.code, "E_PUBLIC_SCAN_GZIP_METADATA")

        ordering = PublicScanFixture(self)
        ordering._write_tar(reversed(ordering._snapshot_entries()))
        ordering._refresh_manifests()
        with self.assertRaises(scanner.PublicScanError) as order_error:
            ordering.scan()
        self.assertEqual(order_error.exception.code, "E_PUBLIC_SCAN_TAR_CANONICAL")

    def test_snapshot_canonical_tar_binary_is_validated_not_text_scanned(self) -> None:
        canonical_relative = f"_artifacts/{TAR_NAME}"

        def binary_sensitive(value: str) -> bool:
            return any(0xDC80 <= ord(character) <= 0xDCFF for character in value)

        binary_security = types.SimpleNamespace(
            PRIVATE_KEY_RE=re.compile(r"(?!)"),
            COMMON_TOKEN_RE=re.compile(r"(?!)"),
            HOME_PATH_RE=re.compile(r"(?!)"),
            contains_secret=binary_sensitive,
        )

        canonical = PublicScanFixture(self)
        canonical_data = canonical.assets[TAR_NAME].read_bytes()
        self.assertTrue(
            binary_sensitive(canonical_data.decode("utf-8", "surrogateescape"))
        )
        canonical.write_snapshot(canonical_relative, canonical_data)
        with mock.patch.object(
            scanner,
            "_security_module",
            return_value=(binary_security, _sha256(DETECTOR_SOURCE)),
        ):
            receipt = canonical.scan()
        canonical_path = f"snapshot/{canonical_relative}"
        surface = next(
            row for row in receipt["surfaces"] if row["path"] == canonical_path
        )
        self.assertEqual(surface["sha256"], _sha256(canonical_data))
        self.assertEqual(surface["size"], len(canonical_data))
        self.assertEqual(surface["mode"], "100644")
        self.assertFalse(
            any(row["path"] == canonical_path for row in receipt["unwaived_findings"])
        )

        credential = PublicScanFixture(self)
        credential_value = "".join(("actual-production-", "password-value"))
        credential_data = ("pass" + "word=" + credential_value + "\n").encode()
        credential_relative = "config/embedded-credential.txt"
        credential.write_snapshot(credential_relative, credential_data)
        credential.rebuild_tar()
        credential.write_snapshot(
            canonical_relative, credential.assets[TAR_NAME].read_bytes()
        )
        credential_receipt = credential.scan()
        hard_paths = {
            row["path"]
            for row in credential_receipt["unwaived_findings"]
            if row["detector_id"] == "credential_literal"
        }
        self.assertIn(f"snapshot/{credential_relative}", hard_paths)
        self.assertIn(f"tar/{credential_relative}", hard_paths)
        self.assertNotIn(f"snapshot/{canonical_relative}", hard_paths)

        disguised = PublicScanFixture(self)
        nested_gzip = disguised.assets[TAR_NAME].read_bytes()
        disguised_relative = f"_artifacts/{TAR_NAME}.backup"
        disguised.write_snapshot(disguised_relative, nested_gzip)
        disguised.rebuild_tar()
        disguised.write_snapshot(
            canonical_relative, disguised.assets[TAR_NAME].read_bytes()
        )
        with mock.patch.object(
            scanner,
            "_security_module",
            return_value=(binary_security, _sha256(DETECTOR_SOURCE)),
        ):
            disguised_receipt = disguised.scan()
        disguised_hard = {
            row["path"]
            for row in disguised_receipt["unwaived_findings"]
            if row["detector_id"] == "shared_detector_unclassified"
        }
        self.assertIn(f"snapshot/{disguised_relative}", disguised_hard)
        self.assertIn(f"tar/{disguised_relative}", disguised_hard)

        mismatch = PublicScanFixture(self)
        mismatch.write_snapshot(canonical_relative, b"not-the-outer-gzip\n")
        with self.assertRaises(scanner.PublicScanError) as mismatch_error:
            mismatch.scan()
        self.assertEqual(
            mismatch_error.exception.code,
            "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH",
        )

    def test_snapshot_and_tar_paths_are_scanned_as_public_surfaces(self) -> None:
        fixture = PublicScanFixture(self)
        relative = f"tests/{PROVIDER_SAMPLE}.txt"
        fixture.write_snapshot(relative, b"safe content\n")
        fixture.rebuild_tar()
        receipt = fixture.scan()
        paths = {row["path"]: row for row in receipt["unwaived_findings"]}
        for surface in (f"snapshot/{relative}", f"tar/{relative}"):
            self.assertIn(surface, paths)
            self.assertIn("path", paths[surface]["finding_sources"])
            self.assertIn("provider_token", paths[surface]["non_waivable_reasons"])

    def test_tar_rejects_traversal_link_device_duplicate_and_limits(self) -> None:
        fixture = PublicScanFixture(self)
        generated = (OKF_PATH, b'{"status":"generated"}\n', "file")
        cases = {
            "traversal": (
                [generated, ("../escape.txt", b"escape\n", "file")],
                "E_PUBLIC_SCAN_TAR_PATH",
            ),
            "symlink": (
                [generated, ("docs/link", b"../../private", "symlink")],
                "E_PUBLIC_SCAN_TAR_TYPE",
            ),
            "device": (
                [generated, ("docs/device", b"", "char-device")],
                "E_PUBLIC_SCAN_TAR_TYPE",
            ),
            "duplicate": (
                [
                    generated,
                    ("docs/repeated.txt", b"first\n", "file"),
                    ("docs/repeated.txt", b"second\n", "file"),
                ],
                "E_PUBLIC_SCAN_TAR_DUPLICATE",
            ),
            "path-limit": (
                [generated, ("x" * 241, b"too long\n", "file")],
                "E_PUBLIC_SCAN_TAR_LIMIT",
            ),
        }
        for name, (entries, expected_code) in cases.items():
            fixture.write_custom_tar(entries)
            with self.subTest(name=name), self.assertRaises(
                scanner.PublicScanError
            ) as caught:
                fixture.scan()
            self.assertEqual(caught.exception.code, expected_code)


if __name__ == "__main__":
    unittest.main()
